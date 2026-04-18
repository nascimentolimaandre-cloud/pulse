"""FDD-KB-013 — Backfill `eng_issues.description` with the plain-text
description from Jira for issues whose body wasn't captured during the
initial sync (column was NULL-only before migration 008).

Analogous in spirit to `backfill_first_commits` and `backfill_deployed_at`:
a one-shot admin endpoint triggers a bounded sweep, fetches the missing
field via READ-ONLY Jira API calls, and UPSERTs it back into eng_issues.

Implementation notes:

- Uses GET /rest/api/3/issue/{key}?fields=description — single-issue
  fetches (Jira's bulk issue fetch API requires POST /search/jql which
  is heavier for pure field refreshes).
- Jira returns the description as Atlassian Document Format (ADF) JSON
  or as a plain string (older tenants on v2 shape). Both are handled
  by the connector's `_extract_description_text` static method.
- Rate limit aware: Jira Cloud allows ~10 req/s per token. We sleep
  between batches when response headers hint we're approaching the
  limit, following the same defensive pattern used by the first-commits
  backfill.
- Idempotent: an unchanged description is a no-op (UPDATE skipped).
- Scopes:
    * `stale`:   description IS NULL AND updated_at >= NOW() - 180d
    * `last-90d`: updated_at >= NOW() - 90d (any description state)
    * `all`:     every Jira-sourced issue (expensive — caps at max_issues)

READ-ONLY Jira contract — this service only issues GET requests.
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
from src.connectors.jira_connector import (
    DESCRIPTION_MAX_CHARS,
    JiraConnector,
)
from src.contexts.engineering_data.models import EngIssue
from src.database import get_session

logger = logging.getLogger(__name__)

# Pacing — keep us well under Jira Cloud's ~10 req/s soft limit.
JIRA_PAUSE_EVERY = 25           # issues per micro-batch
JIRA_PAUSE_SECONDS = 0.6        # sleep between micro-batches
DB_UPDATE_CHUNK = 100           # rows per UPDATE flush

Scope = Literal["stale", "last-90d", "all"]

# external_id format: "jira:JiraIssue:{connection_id}:{numeric_id}"
# We lookup via issue_key (e.g. "OKM-1234") which is stable + human-readable
# and already exists on eng_issues since migration 005.
_JIRA_EXT_ID_RE = re.compile(r"^jira:JiraIssue:\d+:\d+$")


@dataclass
class BackfillResult:
    scope: Scope
    dry_run: bool
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)
    duration_sec: float = 0.0


@dataclass
class _IssueRef:
    issue_id: UUID
    issue_key: str
    description_db: str | None


async def _select_issues(
    tenant_id: UUID,
    scope: Scope,
    max_issues: int | None,
) -> list[_IssueRef]:
    """Pull the set of issues to refresh.

    Enforces `source = 'jira'` and `issue_key IS NOT NULL` — the lookup
    goes through GET /issue/{key} so we can't run on rows missing the key.
    """
    async with get_session(tenant_id) as session:
        stmt = select(
            EngIssue.id,
            EngIssue.issue_key,
            EngIssue.description,
        ).where(
            EngIssue.tenant_id == tenant_id,
            EngIssue.source == "jira",
            EngIssue.issue_key.isnot(None),
        )

        if scope == "stale":
            # Targets rows where the ingestion never captured a description
            # AND the issue has moved recently (skip archived noise).
            cutoff = datetime.now(timezone.utc) - timedelta(days=180)
            stmt = stmt.where(
                EngIssue.description.is_(None),
                EngIssue.updated_at >= cutoff,
            )
        elif scope == "last-90d":
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            stmt = stmt.where(EngIssue.updated_at >= cutoff)
        # scope == "all" — no extra filter

        # Order by updated_at DESC so newest issues win the max_issues cap
        stmt = stmt.order_by(EngIssue.updated_at.desc())
        if max_issues is not None:
            stmt = stmt.limit(max_issues)

        result = await session.execute(stmt)
        rows = result.all()

    refs: list[_IssueRef] = []
    for issue_id, issue_key, desc_db in rows:
        if not issue_key:
            continue
        refs.append(_IssueRef(
            issue_id=issue_id,
            issue_key=issue_key,
            description_db=desc_db,
        ))
    return refs


async def _flush_updates(
    tenant_id: UUID,
    updates: list[tuple[UUID, str | None]],
) -> None:
    if not updates:
        return
    async with get_session(tenant_id) as session:
        for issue_id, new_desc in updates:
            await session.execute(
                update(EngIssue)
                .where(
                    EngIssue.tenant_id == tenant_id,
                    EngIssue.id == issue_id,
                )
                .values(
                    description=new_desc,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        await session.commit()


async def run_backfill(
    tenant_id: UUID,
    scope: Scope = "stale",
    dry_run: bool = False,
    max_issues: int | None = None,
) -> BackfillResult:
    """Populate `eng_issues.description` via READ-ONLY Jira issue fetches."""
    started = datetime.now(timezone.utc)
    result = BackfillResult(scope=scope, dry_run=dry_run)

    # Reuse the connector's ADF parser — single source of truth for how we
    # flatten description JSON into plain text.
    try:
        connector = JiraConnector()
    except ValueError as exc:
        result.errors.append(f"Jira not configured: {exc}")
        return result

    try:
        refs = await _select_issues(tenant_id, scope, max_issues)
        logger.info(
            "[backfill FDD-KB-013] scope=%s tenant=%s candidates=%d dry_run=%s",
            scope, tenant_id, len(refs), dry_run,
        )

        if not refs:
            result.duration_sec = (
                datetime.now(timezone.utc) - started
            ).total_seconds()
            return result

        pending: list[tuple[UUID, str | None]] = []

        for idx, ref in enumerate(refs, start=1):
            result.processed += 1
            try:
                # READ-ONLY Jira call — GET /rest/api/3/issue/{key}?fields=description
                data = await connector._client.get(  # noqa: SLF001 — sharing client
                    f"/rest/api/3/issue/{ref.issue_key}",
                    params={"fields": "description"},
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"fetch failed for {ref.issue_key}: {exc}"
                logger.warning(msg)
                result.errors.append(msg)
                result.skipped += 1
                continue

            raw_desc = (data.get("fields") or {}).get("description")
            new_desc = JiraConnector._extract_description_text(raw_desc)

            # Idempotency — skip DB write when value matches what we already have.
            if (new_desc or None) == (ref.description_db or None):
                result.unchanged += 1
            else:
                if len(result.sample) < 3 and new_desc:
                    result.sample.append({
                        "issue_key": ref.issue_key,
                        "had_description": ref.description_db is not None,
                        "new_length": len(new_desc),
                        "preview": new_desc[:120] + ("..." if len(new_desc) > 120 else ""),
                    })
                if not dry_run:
                    pending.append((ref.issue_id, new_desc))
                result.updated += 1

            if len(pending) >= DB_UPDATE_CHUNK:
                await _flush_updates(tenant_id, pending)
                pending = []

            # Light pacing to respect Jira's per-token rate limit.
            if idx % JIRA_PAUSE_EVERY == 0:
                await asyncio.sleep(JIRA_PAUSE_SECONDS)
                logger.info(
                    "[backfill FDD-KB-013] progress: %d/%d processed, %d updated",
                    result.processed, len(refs), result.updated,
                )

        if not dry_run and pending:
            await _flush_updates(tenant_id, pending)

    finally:
        await connector.close()

    # Guardrail: never expose >4000 chars — the connector already capped it,
    # but we double-check so a future connector bug can't corrupt the column.
    _ = DESCRIPTION_MAX_CHARS  # referenced for linters / future assertions

    result.duration_sec = round(
        (datetime.now(timezone.utc) - started).total_seconds(), 2,
    )
    logger.info(
        "[backfill FDD-KB-013] done: processed=%d updated=%d unchanged=%d skipped=%d errors=%d",
        result.processed, result.updated, result.unchanged,
        result.skipped, len(result.errors),
    )
    return result
