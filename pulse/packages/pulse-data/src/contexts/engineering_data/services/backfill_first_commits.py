"""INC-003 — Backfill `eng_pull_requests.first_commit_at` with the real
authored_date of the first commit on each PR.

Before this fix, the normalizer copied `created_at` (PR open time) into
`first_commit_at`, which made Cycle Time and Lead Time collapse to the
merge-to-open delta. For 45% of Webmotors' PRs, that delta is under 10
minutes — the real work happened on the branch days earlier, the PR was
only opened at approval time and merged immediately.

This service:
1. Selects PRs from `eng_pull_requests` whose `first_commit_at` is stale
   (equal to `created_at`) or via an explicit scope (all | last-60d).
2. Groups by repo, then calls GitHub GraphQL in aliased batches (one query
   fetches first-commit authoredDate for N PRs at once — ~20x fewer calls
   than REST).
3. UPSERTs the real timestamps back into the table.

Rate limit awareness:
- Monitors `rateLimit.remaining` from each GraphQL response
- Pauses (+ logs) if the remaining quota drops below GRAPHQL_PAUSE_THRESHOLD
- Never exceeds GitHub's hourly budget of 5,000 points

Idempotent: running twice is safe. When `_is_unchanged()` detects a DB
value that already matches the live GitHub value, no UPDATE is issued.

READ-ONLY on GitHub — only issues GraphQL queries. Never mutates.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, update

from src.config import settings
from src.contexts.engineering_data.models import EngPullRequest
from src.database import get_session
from src.shared.http_client import ResilientHTTPClient

logger = logging.getLogger(__name__)

# Tuning knobs
BATCH_SIZE_GRAPHQL = 25       # PRs per aliased GraphQL query (keeps complexity low)
DB_UPDATE_CHUNK = 200         # Rows per UPDATE flush to DB
GRAPHQL_PAUSE_THRESHOLD = 500 # Pause if remaining quota drops below this
GRAPHQL_PAUSE_SECONDS = 60    # Poll interval while paused (retries rateLimit)

Scope = Literal["stale", "all", "last-60d"]

# external_id format: "github:GithubPullRequest:{connection_id}:{owner}/{repo}:{pr_number}"
_EXT_ID_RE = re.compile(
    r"^github:GithubPullRequest:(?P<conn>\d+):(?P<repo>[^:]+/[^:]+):(?P<num>\d+)$"
)


@dataclass
class BackfillResult:
    scope: Scope
    dry_run: bool
    prs_processed: int = 0
    prs_updated: int = 0
    prs_skipped: int = 0
    prs_unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    sample_diffs: list[dict[str, Any]] = field(default_factory=list)
    duration_sec: float = 0.0
    rate_limit_remaining_start: int | None = None
    rate_limit_remaining_end: int | None = None


@dataclass
class _PRRef:
    pr_id: UUID
    external_id: str
    repo_full_name: str
    pr_number: int
    created_at: datetime | None
    first_commit_at_db: datetime | None


def _parse_external_id(external_id: str) -> tuple[str, int] | None:
    m = _EXT_ID_RE.match(external_id)
    if not m:
        return None
    return m.group("repo"), int(m.group("num"))


async def _select_prs(
    tenant_id: UUID,
    scope: Scope,
) -> list[_PRRef]:
    """Select the set of PRs to refresh, per scope."""
    async with get_session(tenant_id) as session:
        stmt = select(
            EngPullRequest.id,
            EngPullRequest.external_id,
            EngPullRequest.created_at,
            EngPullRequest.first_commit_at,
        ).where(
            EngPullRequest.tenant_id == tenant_id,
            EngPullRequest.source == "github",
        )

        if scope == "stale":
            # Sintoma do bug: first_commit_at == created_at (cópia direta)
            stmt = stmt.where(EngPullRequest.first_commit_at == EngPullRequest.created_at)
        elif scope == "last-60d":
            cutoff = datetime.now(timezone.utc) - timedelta(days=60)
            stmt = stmt.where(EngPullRequest.merged_at >= cutoff)
        # scope == "all" — no extra filter

        result = await session.execute(stmt)
        rows = result.all()

    refs: list[_PRRef] = []
    for pr_id, ext_id, created, fca in rows:
        parsed = _parse_external_id(ext_id or "")
        if parsed is None:
            continue
        repo, num = parsed
        refs.append(_PRRef(
            pr_id=pr_id,
            external_id=ext_id,
            repo_full_name=repo,
            pr_number=num,
            created_at=created,
            first_commit_at_db=fca,
        ))
    return refs


def _build_graphql_batch_query(items: list[tuple[str, int]]) -> tuple[str, dict[str, Any]]:
    """Build a single GraphQL document that queries N PRs at once via aliases.

    items: list of (repo_full_name, pr_number)
    Returns: (query_string, variables_dict)
    """
    # Use one variable per PR for owner/name/number so we can reuse across batches
    var_defs: list[str] = []
    field_blocks: list[str] = []
    variables: dict[str, Any] = {}
    for i, (repo_full_name, pr_number) in enumerate(items):
        owner, name = repo_full_name.split("/", 1)
        var_defs.append(f"$owner{i}: String!, $name{i}: String!, $num{i}: Int!")
        variables[f"owner{i}"] = owner
        variables[f"name{i}"] = name
        variables[f"num{i}"] = pr_number
        field_blocks.append(
            f"""
            pr{i}: repository(owner: $owner{i}, name: $name{i}) {{
              pullRequest(number: $num{i}) {{
                number
                createdAt
                commits(first: 1) {{
                  totalCount
                  nodes {{
                    commit {{
                      authoredDate
                      oid
                    }}
                  }}
                }}
              }}
            }}"""
        )

    query = (
        "query("
        + ", ".join(var_defs)
        + ") {\n"
        + "  rateLimit { remaining resetAt cost }\n"
        + "".join(field_blocks)
        + "\n}"
    )
    return query, variables


async def _call_graphql(
    client: ResilientHTTPClient,
    query: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post("/graphql", json_body={"query": query, "variables": variables})
    return response


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


async def _wait_for_rate_limit(
    client: ResilientHTTPClient,
    current_remaining: int,
) -> int:
    """Pause while GraphQL remaining quota is below threshold. Returns new remaining."""
    while current_remaining < GRAPHQL_PAUSE_THRESHOLD:
        logger.warning(
            "GraphQL rate limit low (%d remaining) — pausing %ds",
            current_remaining, GRAPHQL_PAUSE_SECONDS,
        )
        await asyncio.sleep(GRAPHQL_PAUSE_SECONDS)
        try:
            status = await client.post(
                "/graphql",
                json_body={"query": "query { rateLimit { remaining resetAt } }"},
            )
            current_remaining = (
                ((status.get("data") or {}).get("rateLimit") or {}).get("remaining", 0)
            )
        except Exception:
            logger.exception("Failed to poll rate limit — continuing with cached value")
            break
    return current_remaining


async def _flush_updates(
    tenant_id: UUID,
    updates: list[tuple[UUID, datetime]],
) -> None:
    if not updates:
        return
    async with get_session(tenant_id) as session:
        for pr_id, new_ts in updates:
            await session.execute(
                update(EngPullRequest)
                .where(
                    EngPullRequest.tenant_id == tenant_id,
                    EngPullRequest.id == pr_id,
                )
                .values(
                    first_commit_at=new_ts,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        await session.commit()


async def run_backfill(
    tenant_id: UUID,
    scope: Scope = "stale",
    dry_run: bool = False,
    max_prs: int | None = None,
) -> BackfillResult:
    """Backfill `first_commit_at` for all matching GitHub PRs of a tenant."""
    started = datetime.now(timezone.utc)
    result = BackfillResult(scope=scope, dry_run=dry_run)

    token = settings.github_token
    if not token:
        result.errors.append("GITHUB_TOKEN not configured")
        result.duration_sec = 0.0
        return result

    api_url = (settings.github_api_url or "https://api.github.com").rstrip("/")
    client = ResilientHTTPClient(
        base_url=api_url,
        auth={"token": token},
        timeout=30.0,
        max_retries=3,
        extra_headers={"X-GitHub-Api-Version": "2022-11-28"},
    )

    try:
        refs = await _select_prs(tenant_id, scope)
        if max_prs is not None:
            refs = refs[:max_prs]

        logger.info(
            "[backfill INC-003] scope=%s tenant=%s candidates=%d dry_run=%s",
            scope, tenant_id, len(refs), dry_run,
        )

        if not refs:
            result.duration_sec = (datetime.now(timezone.utc) - started).total_seconds()
            return result

        pending_updates: list[tuple[UUID, datetime]] = []
        remaining_quota: int | None = None

        # Process in batches of BATCH_SIZE_GRAPHQL PRs per GraphQL call
        for start in range(0, len(refs), BATCH_SIZE_GRAPHQL):
            chunk = refs[start:start + BATCH_SIZE_GRAPHQL]
            items = [(r.repo_full_name, r.pr_number) for r in chunk]
            query, variables = _build_graphql_batch_query(items)

            try:
                response = await _call_graphql(client, query, variables)
            except Exception as exc:  # noqa: BLE001
                msg = f"GraphQL batch failed (start={start}): {exc}"
                logger.exception(msg)
                result.errors.append(msg)
                result.prs_skipped += len(chunk)
                continue

            # Capture rate-limit info
            rate = ((response.get("data") or {}).get("rateLimit") or {})
            remaining_quota = rate.get("remaining", remaining_quota)
            if result.rate_limit_remaining_start is None and remaining_quota is not None:
                result.rate_limit_remaining_start = remaining_quota

            # Non-fatal errors array (e.g., NOT_FOUND on a deleted repo)
            gql_errors = response.get("errors") or []
            if gql_errors:
                logger.warning(
                    "GraphQL partial errors in batch start=%d: %s",
                    start, [e.get("message") for e in gql_errors][:3],
                )

            data = response.get("data") or {}
            for idx, ref in enumerate(chunk):
                result.prs_processed += 1
                alias = f"pr{idx}"
                repo_data = data.get(alias)
                if not repo_data:
                    result.prs_skipped += 1
                    continue
                pr_data = repo_data.get("pullRequest")
                if not pr_data:
                    result.prs_skipped += 1
                    continue

                commits = (pr_data.get("commits") or {}).get("nodes") or []
                if not commits:
                    # No commits on PR (rare — empty/draft). Keep DB value.
                    logger.debug("PR has no commits: %s#%d", ref.repo_full_name, ref.pr_number)
                    result.prs_skipped += 1
                    continue

                first_commit_obj = (commits[0] or {}).get("commit") or {}
                new_ts = _parse_datetime(first_commit_obj.get("authoredDate"))
                if new_ts is None:
                    result.prs_skipped += 1
                    continue

                # Idempotency check — skip if DB value is already correct (±1s)
                old_ts = ref.first_commit_at_db
                if old_ts is not None and abs((old_ts - new_ts).total_seconds()) <= 1:
                    result.prs_unchanged += 1
                    continue

                # Capture sample diffs (first 3 big shifts)
                if len(result.sample_diffs) < 3 and ref.created_at is not None:
                    delta_days = (ref.created_at - new_ts).total_seconds() / 86400.0
                    if abs(delta_days) >= 0.1:  # at least ~2.5h shift
                        result.sample_diffs.append({
                            "external_id": ref.external_id,
                            "repo": ref.repo_full_name,
                            "pr_number": ref.pr_number,
                            "created_at": ref.created_at.isoformat(),
                            "old_first_commit_at": old_ts.isoformat() if old_ts else None,
                            "new_first_commit_at": new_ts.isoformat(),
                            "delta_days": round(delta_days, 2),
                        })

                if not dry_run:
                    pending_updates.append((ref.pr_id, new_ts))
                result.prs_updated += 1

                if len(pending_updates) >= DB_UPDATE_CHUNK:
                    await _flush_updates(tenant_id, pending_updates)
                    pending_updates = []

            # Rate limit guard
            if remaining_quota is not None and remaining_quota < GRAPHQL_PAUSE_THRESHOLD:
                remaining_quota = await _wait_for_rate_limit(client, remaining_quota)

            # Progress log every 500 PRs processed
            if result.prs_processed % 500 < BATCH_SIZE_GRAPHQL:
                logger.info(
                    "[backfill INC-003] progress: %d/%d processed, %d updated, rate_remaining=%s",
                    result.prs_processed, len(refs), result.prs_updated, remaining_quota,
                )

        # Final flush
        if not dry_run and pending_updates:
            await _flush_updates(tenant_id, pending_updates)

        result.rate_limit_remaining_end = remaining_quota

    finally:
        await client.close()

    result.duration_sec = round(
        (datetime.now(timezone.utc) - started).total_seconds(), 2,
    )
    logger.info(
        "[backfill INC-003] done: processed=%d updated=%d unchanged=%d skipped=%d errors=%d",
        result.prs_processed, result.prs_updated, result.prs_unchanged,
        result.prs_skipped, len(result.errors),
    )
    return result
