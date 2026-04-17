"""INC-004 — Backfill `eng_pull_requests.deployed_at` by linking merged PRs
to the first production deployment that followed their merge.

Before this fix, `deployed_at` was always NULL. The DORA Lead Time for
Changes calculation (deployed_at - first_commit_at) fell back to the
cycle-time fallback (merged_at - first_commit_at), making Lead Time
numerically identical to Cycle Time and erasing the "deploy queue time"
signal.

Strategy — TEMPORAL MATCH (SHA match is not viable):
- Jenkins deployments expose a `sha` field that is actually a Jenkins
  build identifier (`jenkins:JenkinsBuild:...`), NOT a git commit SHA.
  Adding `merge_commit_sha` to PRs and enriching from GitHub would be
  high-cost. See INC-004 report for the decision rationale.
- Instead: for each merged PR, find the earliest production deployment
  in the same repo that occurred AFTER merged_at, within a configurable
  window (default 30 days). That deployment's timestamp becomes
  `deployed_at`. Multiple PRs linking to the same deploy is expected
  and correct (a single deploy can ship many merges).

Repo normalization:
- `eng_pull_requests.repo`  = "webmotors-private/<name>"  (GitHub full)
- `eng_deployments.repo`    = "<name>"                    (Jenkins short)
- Join key: `split_part(pr.repo, '/', 2) = d.repo` (case-sensitive).

Idempotent: a PR whose `deployed_at` is already within 1s of the
proposed value is skipped (`prs_unchanged`).

READ-ONLY on external systems — operates entirely on PULSE DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text

from src.database import get_session

logger = logging.getLogger(__name__)

Scope = Literal["stale", "all", "last-60d"]
Strategy = Literal["sha", "temporal", "both"]

DEFAULT_WINDOW_DAYS = 30


@dataclass
class DeployedAtBackfillResult:
    scope: Scope
    strategy: Strategy
    window_days: int
    dry_run: bool
    prs_processed: int = 0
    prs_updated: int = 0
    prs_no_match: int = 0
    prs_unchanged: int = 0
    strategy_breakdown: dict[str, int] = field(
        default_factory=lambda: {"sha_match": 0, "temporal_match": 0}
    )
    sample_matches: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_sec: float = 0.0


# ---------------------------------------------------------------------------
# Linking SQL
# ---------------------------------------------------------------------------
#
# Single CTE that (a) selects the candidate PRs per scope, (b) LATERAL-joins
# the earliest production deploy after merged_at within the window, and
# (c) returns the proposed (pr_id, new_deployed_at) tuples. We do the linking
# in SQL to avoid an N+1 round-trip; the Python layer only needs to decide
# sample/idempotency/dry-run handling before issuing the UPDATE.

_SELECT_LINKS_SQL = """
WITH candidates AS (
    SELECT id, repo, merged_at, deployed_at, external_id, title
    FROM eng_pull_requests
    WHERE tenant_id = :tenant_id
      AND is_merged = TRUE
      AND merged_at IS NOT NULL
      {scope_filter}
)
SELECT
    c.id            AS pr_id,
    c.external_id   AS pr_external_id,
    c.repo          AS pr_repo,
    c.title         AS pr_title,
    c.merged_at     AS pr_merged_at,
    c.deployed_at   AS pr_deployed_at_current,
    d.deployed_at   AS proposed_deployed_at
FROM candidates c
LEFT JOIN LATERAL (
    SELECT deployed_at
    FROM eng_deployments
    WHERE tenant_id = :tenant_id
      AND environment = 'production'
      AND repo = split_part(c.repo, '/', 2)
      AND deployed_at > c.merged_at
      AND deployed_at <= c.merged_at + make_interval(days => :window_days)
    ORDER BY deployed_at ASC
    LIMIT 1
) d ON TRUE
"""

_UPDATE_SQL = """
UPDATE eng_pull_requests
SET deployed_at = :deployed_at,
    updated_at  = now()
WHERE tenant_id = :tenant_id
  AND id = :pr_id
"""


def _build_scope_filter(scope: Scope) -> str:
    if scope == "stale":
        # PRs that don't yet have a deployed_at (the primary target).
        return "AND deployed_at IS NULL"
    if scope == "last-60d":
        return "AND merged_at >= (now() - INTERVAL '60 days')"
    # scope == "all" — no extra filter
    return ""


async def run_backfill(
    tenant_id: UUID,
    scope: Scope = "stale",
    strategy: Strategy = "both",
    window_days: int = DEFAULT_WINDOW_DAYS,
    dry_run: bool = False,
    max_prs: int | None = None,
) -> DeployedAtBackfillResult:
    """Backfill `deployed_at` for merged PRs using the temporal linking
    strategy. `strategy='sha'` is currently a no-op (no SHA available on
    Jenkins deployments); `strategy='both'` and `strategy='temporal'` are
    equivalent in the MVP.
    """
    started = datetime.now(timezone.utc)
    result = DeployedAtBackfillResult(
        scope=scope,
        strategy=strategy,
        window_days=window_days,
        dry_run=dry_run,
    )

    if strategy == "sha":
        result.errors.append(
            "strategy=sha is not supported: Jenkins deployments do not carry "
            "git commit SHAs (only Jenkins build identifiers). Use "
            "strategy=temporal or strategy=both."
        )
        result.duration_sec = (datetime.now(timezone.utc) - started).total_seconds()
        return result

    scope_filter = _build_scope_filter(scope)
    select_sql = _SELECT_LINKS_SQL.format(scope_filter=scope_filter)

    logger.warning(
        "[backfill INC-004] start tenant=%s scope=%s strategy=%s "
        "window_days=%d dry_run=%s max_prs=%s",
        tenant_id, scope, strategy, window_days, dry_run, max_prs,
    )

    async with get_session(tenant_id) as session:
        rows_result = await session.execute(
            text(select_sql),
            {"tenant_id": str(tenant_id), "window_days": window_days},
        )
        rows = rows_result.mappings().all()

    if max_prs is not None:
        rows = list(rows)[:max_prs]

    logger.info("[backfill INC-004] candidates=%d", len(rows))

    # Process in Python so we can honour idempotency + samples + dry-run.
    # We batch UPDATEs by session for speed.
    async with get_session(tenant_id) as session:
        flushed_in_tx = 0
        for row in rows:
            result.prs_processed += 1
            pr_id: UUID = row["pr_id"]
            proposed: datetime | None = row["proposed_deployed_at"]
            current: datetime | None = row["pr_deployed_at_current"]
            pr_merged_at: datetime = row["pr_merged_at"]

            if proposed is None:
                result.prs_no_match += 1
                continue

            # Idempotency: already-correct value within 1s.
            if current is not None and abs(
                (current - proposed).total_seconds()
            ) <= 1:
                result.prs_unchanged += 1
                continue

            # Sample first 3 fresh matches
            if len(result.sample_matches) < 3:
                delta_hours = (
                    (proposed - pr_merged_at).total_seconds() / 3600.0
                )
                result.sample_matches.append({
                    "pr_external_id": row["pr_external_id"],
                    "pr_repo": row["pr_repo"],
                    "pr_title": (row["pr_title"] or "")[:80],
                    "merged_at": pr_merged_at.isoformat(),
                    "deployed_at": proposed.isoformat(),
                    "delta_hours": round(delta_hours, 2),
                    "strategy": "temporal",
                })

            result.prs_updated += 1
            result.strategy_breakdown["temporal_match"] += 1

            if not dry_run:
                await session.execute(
                    text(_UPDATE_SQL),
                    {
                        "pr_id": pr_id,
                        "tenant_id": str(tenant_id),
                        "deployed_at": proposed,
                    },
                )
                flushed_in_tx += 1
                # Flush every 500 to keep transactions bounded.
                if flushed_in_tx >= 500:
                    await session.commit()
                    flushed_in_tx = 0

        if not dry_run and flushed_in_tx > 0:
            await session.commit()

    result.duration_sec = round(
        (datetime.now(timezone.utc) - started).total_seconds(), 2,
    )
    logger.warning(
        "[backfill INC-004] done processed=%d updated=%d unchanged=%d "
        "no_match=%d errors=%d duration=%.2fs",
        result.prs_processed, result.prs_updated, result.prs_unchanged,
        result.prs_no_match, len(result.errors), result.duration_sec,
    )
    return result


# ---------------------------------------------------------------------------
# Forward-path helper (called from _sync_deployments)
# ---------------------------------------------------------------------------

_FORWARD_LINK_SQL = """
UPDATE eng_pull_requests pr
SET deployed_at = d.deployed_at,
    updated_at  = now()
FROM eng_deployments d
WHERE pr.tenant_id = :tenant_id
  AND d.tenant_id  = :tenant_id
  AND d.environment = 'production'
  AND d.deployed_at >= :since_at
  AND pr.is_merged = TRUE
  AND pr.merged_at IS NOT NULL
  AND pr.deployed_at IS NULL
  AND d.repo = split_part(pr.repo, '/', 2)
  AND d.deployed_at > pr.merged_at
  AND d.deployed_at <= pr.merged_at + make_interval(days => :window_days)
  AND d.deployed_at = (
        SELECT MIN(d2.deployed_at)
        FROM eng_deployments d2
        WHERE d2.tenant_id  = :tenant_id
          AND d2.environment = 'production'
          AND d2.repo        = d.repo
          AND d2.deployed_at > pr.merged_at
  )
"""


async def link_recent_deploys_to_prs(
    tenant_id: UUID,
    since_at: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> int:
    """Forward-path linker: after _sync_deployments ingests new deploys,
    bind any merged PRs (repo match, merged before deploy, within window)
    to those deploys. Returns the number of PRs updated.

    Idempotent: PRs that already have a deployed_at are skipped via the
    `pr.deployed_at IS NULL` filter. Multiple PRs → one deploy is normal.
    """
    async with get_session(tenant_id) as session:
        res = await session.execute(
            text(_FORWARD_LINK_SQL),
            {
                "tenant_id": str(tenant_id),
                "since_at": since_at,
                "window_days": window_days,
            },
        )
        await session.commit()
        count = res.rowcount or 0
    if count:
        logger.info(
            "[INC-004 forward-link] linked %d PRs to newly ingested deploys "
            "(since_at=%s window_days=%d)",
            count, since_at.isoformat(), window_days,
        )
    return count
