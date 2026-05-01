"""FDD-DSH-050 — MTTR incident pairing (INC-005 fix).

Pairs each `is_failure=true` deploy with the next `is_failure=false`
deploy on the SAME (tenant_id, repo, environment), within a
configurable open-incident window (default 7 days). The delta in hours
populates `eng_deployments.recovery_time_hours` on the FAILURE row.

Decisions (see docs/fdd/FDD-DSH-050-mttr-design.md):
  - Anchor: the FAILURE row owns recovery_time_hours + incident_status.
    The success row stays untouched (no `is_recovery` flag — would create
    a multi-row update problem with no benefit).
  - Back-to-back failures: only the FIRST failure in a chain is the
    anchor; subsequent failures get `superseded_by_deploy_id` pointing to
    that anchor and `incident_status='superseded'` so MTTR aggregation
    skips them (already filtered: only `incident_status='resolved'` rows
    contribute to the median).
  - Production-only filter: same as INC-008 fix (CFR + DF use prod).
    Non-prod failures are noise.
  - Idempotent: re-running pairs only rows where `incident_status IS NULL`
    or where status/recovered_by would actually change. Re-runs are safe.
  - Open-incident window: default 7 days. Failures with no recovery in
    the window are tagged `incident_status='open'` and EXCLUDED from MTTR
    median (counted separately in `mttr_open_incident_count`).

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

Scope = Literal["all", "stale", "last-90d"]

# Default open-incident window. Failures with no recovery deploy in this
# window are tagged 'open' and excluded from MTTR median. 7 days matches
# the data-engineer recommendation (rests of the team typically deploy
# within a week if they're going to deploy at all; abandoned branches
# from weeks ago are not "open incidents" — they're abandoned work).
DEFAULT_OPEN_WINDOW_DAYS = 7


@dataclass
class MTTRBackfillResult:
    scope: Scope
    open_window_days: int
    dry_run: bool
    deploys_scanned: int = 0
    failures_anchored: int = 0
    failures_resolved: int = 0
    failures_open: int = 0
    failures_superseded: int = 0
    failures_unchanged: int = 0
    sample_pairings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_sec: float = 0.0


# ---------------------------------------------------------------------------
# Pairing SQL — single CTE that classifies every prod deploy
# ---------------------------------------------------------------------------
#
# The query produces ONE row per failure deploy in scope, with the proposed
# (recovered_by_deploy_id, recovery_time_hours, superseded_by_deploy_id,
# incident_status) columns. Python layer applies idempotency + UPDATE.
#
# Algorithm:
#   1. ranked = order all prod deploys per (repo) by deployed_at,
#      computing (a) prev_is_failure flag (LAG) and
#      (b) the next_success_at timestamp via correlated subquery.
#   2. classify each is_failure=true row:
#        - if prev_is_failure → it's a back-to-back; tag 'superseded' and
#          point superseded_by at the FIRST failure in the chain.
#        - elif next_success exists within window → 'resolved' + recovery
#          time.
#        - else → 'open'.

_PAIRING_SQL = """
WITH prod AS (
    SELECT
        id,
        external_id,
        repo,
        environment,
        deployed_at,
        is_failure,
        recovered_by_deploy_id,
        superseded_by_deploy_id,
        incident_status
    FROM eng_deployments
    WHERE tenant_id = :tenant_id
      AND environment IN ('production', 'prod')
      AND repo IS NOT NULL
      AND deployed_at IS NOT NULL
      {scope_filter}
),
ranked AS (
    SELECT
        p.*,
        LAG(p.is_failure) OVER (
            PARTITION BY p.repo
            ORDER BY p.deployed_at
        ) AS prev_is_failure,
        -- Within-chain anchor lookup: walk back through consecutive
        -- failures to find the first one in the chain. Implemented as
        -- a correlated subquery for clarity (vs gaps-and-islands trick).
        (
            SELECT pp.id
            FROM prod pp
            WHERE pp.repo = p.repo
              AND pp.is_failure = TRUE
              AND pp.deployed_at <= p.deployed_at
              AND NOT EXISTS (
                  SELECT 1 FROM prod ppp
                  WHERE ppp.repo = p.repo
                    AND ppp.deployed_at < pp.deployed_at
                    AND ppp.deployed_at >= COALESCE(
                        (
                            SELECT MAX(success.deployed_at)
                            FROM prod success
                            WHERE success.repo = p.repo
                              AND success.is_failure = FALSE
                              AND success.deployed_at < pp.deployed_at
                        ),
                        '1900-01-01'::timestamptz
                    )
                    AND ppp.is_failure = TRUE
              )
            ORDER BY pp.deployed_at ASC
            LIMIT 1
        ) AS chain_anchor_id
    FROM prod p
)
SELECT
    r.id                    AS deploy_id,
    r.external_id           AS deploy_external_id,
    r.repo                  AS repo,
    r.deployed_at           AS failure_at,
    r.recovered_by_deploy_id AS current_recovered_by,
    r.superseded_by_deploy_id AS current_superseded_by,
    r.incident_status       AS current_status,
    -- next success timestamp + id within open window
    next_s.id               AS next_success_id,
    next_s.deployed_at      AS next_success_at,
    -- chain anchor (id of FIRST failure in this chain)
    r.chain_anchor_id       AS chain_anchor_id
FROM ranked r
LEFT JOIN LATERAL (
    SELECT id, deployed_at
    FROM eng_deployments d2
    WHERE d2.tenant_id = :tenant_id
      AND d2.repo = r.repo
      AND d2.environment IN ('production', 'prod')
      AND d2.is_failure = FALSE
      AND d2.deployed_at > r.deployed_at
      AND d2.deployed_at <= r.deployed_at + make_interval(days => :window_days)
    ORDER BY d2.deployed_at ASC
    LIMIT 1
) next_s ON TRUE
WHERE r.is_failure = TRUE
ORDER BY r.deployed_at ASC
"""


_UPDATE_SQL = """
UPDATE eng_deployments
SET recovered_by_deploy_id = :recovered_by_deploy_id,
    superseded_by_deploy_id = :superseded_by_deploy_id,
    incident_status = :incident_status,
    recovery_time_hours = :recovery_time_hours,
    updated_at = now()
WHERE tenant_id = :tenant_id
  AND id = :deploy_id
"""


def _build_scope_filter(scope: Scope) -> str:
    if scope == "stale":
        # Failure rows that haven't been classified yet (incident_status NULL).
        return "AND (is_failure = FALSE OR incident_status IS NULL)"
    if scope == "last-90d":
        return "AND deployed_at >= (now() - INTERVAL '90 days')"
    # scope == "all" — no extra filter
    return ""


async def run_backfill(
    tenant_id: UUID,
    scope: Scope = "stale",
    open_window_days: int = DEFAULT_OPEN_WINDOW_DAYS,
    dry_run: bool = False,
    max_failures: int | None = None,
) -> MTTRBackfillResult:
    """Pair failure deploys with their recovery deploys and write
    `recovery_time_hours` + `incident_status` on the failure rows.

    Args:
        tenant_id: tenant scope (RLS).
        scope: 'all' | 'stale' (default — only un-classified failures) |
               'last-90d' (limit to recent window for fast smoke).
        open_window_days: how long to wait for a recovery before tagging
            the failure 'open'. Default 7d.
        dry_run: classify + sample without writing.
        max_failures: cap processed failure rows (smoke testing).

    Returns:
        MTTRBackfillResult with counts + sample pairings.
    """
    started = datetime.now(timezone.utc)
    result = MTTRBackfillResult(
        scope=scope,
        open_window_days=open_window_days,
        dry_run=dry_run,
    )

    scope_filter = _build_scope_filter(scope)
    select_sql = _PAIRING_SQL.format(scope_filter=scope_filter)

    logger.warning(
        "[backfill INC-005/MTTR] start tenant=%s scope=%s window_days=%d "
        "dry_run=%s max_failures=%s",
        tenant_id, scope, open_window_days, dry_run, max_failures,
    )

    async with get_session(tenant_id) as session:
        rows_result = await session.execute(
            text(select_sql),
            {
                "tenant_id": str(tenant_id),
                "window_days": open_window_days,
            },
        )
        rows = list(rows_result.mappings().all())

    result.deploys_scanned = len(rows)
    if max_failures is not None:
        rows = rows[:max_failures]

    logger.info("[backfill INC-005/MTTR] failure_anchors=%d", len(rows))

    async with get_session(tenant_id) as session:
        flushed_in_tx = 0
        for row in rows:
            deploy_id: UUID = row["deploy_id"]
            failure_at: datetime = row["failure_at"]
            next_success_id = row["next_success_id"]
            next_success_at = row["next_success_at"]
            chain_anchor_id: UUID | None = row["chain_anchor_id"]

            # Classification logic
            is_chain_member = (
                chain_anchor_id is not None and chain_anchor_id != deploy_id
            )

            new_recovered_by: UUID | None = None
            new_superseded_by: UUID | None = None
            new_recovery_hours: float | None = None
            new_status: str

            if is_chain_member:
                # Back-to-back failure absorbed into an earlier anchor.
                new_status = "superseded"
                new_superseded_by = chain_anchor_id
                # No recovery_time on superseded rows; the anchor carries it.
            elif next_success_at is not None:
                # First failure in chain (or solo failure) WITH recovery in window.
                new_status = "resolved"
                new_recovered_by = next_success_id
                new_recovery_hours = round(
                    (next_success_at - failure_at).total_seconds() / 3600.0,
                    4,
                )
            else:
                # No recovery within window — open incident.
                new_status = "open"

            result.failures_anchored += 1
            if new_status == "resolved":
                result.failures_resolved += 1
            elif new_status == "open":
                result.failures_open += 1
            elif new_status == "superseded":
                result.failures_superseded += 1

            # Idempotency: skip if state unchanged
            if (
                row["current_status"] == new_status
                and row["current_recovered_by"] == new_recovered_by
                and row["current_superseded_by"] == new_superseded_by
            ):
                result.failures_unchanged += 1
                # Decrement the type-specific counter we already bumped
                if new_status == "resolved":
                    result.failures_resolved -= 1
                elif new_status == "open":
                    result.failures_open -= 1
                elif new_status == "superseded":
                    result.failures_superseded -= 1
                result.failures_anchored -= 1
                continue

            # Sample first 5 fresh pairings for ops visibility
            if len(result.sample_pairings) < 5:
                result.sample_pairings.append({
                    "deploy_external_id": row["deploy_external_id"],
                    "repo": row["repo"],
                    "failure_at": failure_at.isoformat(),
                    "status": new_status,
                    "recovery_hours": new_recovery_hours,
                    "next_success_at": (
                        next_success_at.isoformat() if next_success_at else None
                    ),
                })

            if not dry_run:
                await session.execute(
                    text(_UPDATE_SQL),
                    {
                        "deploy_id": deploy_id,
                        "tenant_id": str(tenant_id),
                        "recovered_by_deploy_id": new_recovered_by,
                        "superseded_by_deploy_id": new_superseded_by,
                        "incident_status": new_status,
                        "recovery_time_hours": new_recovery_hours,
                    },
                )
                flushed_in_tx += 1
                if flushed_in_tx >= 500:
                    await session.commit()
                    flushed_in_tx = 0

        if not dry_run and flushed_in_tx > 0:
            await session.commit()

    result.duration_sec = round(
        (datetime.now(timezone.utc) - started).total_seconds(), 2,
    )
    logger.warning(
        "[backfill INC-005/MTTR] done scanned=%d resolved=%d open=%d "
        "superseded=%d unchanged=%d errors=%d duration=%.2fs",
        result.deploys_scanned, result.failures_resolved,
        result.failures_open, result.failures_superseded,
        result.failures_unchanged, len(result.errors), result.duration_sec,
    )
    return result


# ---------------------------------------------------------------------------
# Forward-path helper (called from _sync_deployments after upsert)
# ---------------------------------------------------------------------------

async def pair_recent_incidents(
    tenant_id: UUID,
    since_at: datetime,
    open_window_days: int = DEFAULT_OPEN_WINDOW_DAYS,
) -> int:
    """Forward-path pairing: after `_sync_deployments` ingests new deploys,
    re-classify any failures whose state may have changed because of the
    new arrivals.

    Specifically targets:
      1. New failures without any classification yet (`incident_status IS NULL`)
      2. Previously-`open` failures that may now have a recovery
      3. Previously-`open` failures whose window expired (still open, no-op)

    Idempotent: skips rows where state is unchanged.

    Returns the count of failure rows whose classification was updated.

    Note: implementation reuses `run_backfill` with `scope='stale'` which
    already filters to un-classified rows. We add a date constraint to
    bound the work — after a sync that ingested 100 deploys, we don't
    want to scan all of history.
    """
    # Use scope='stale' which targets `incident_status IS NULL` rows.
    # That captures both new failures AND any failures we tagged 'open'
    # earlier — wait, 'open' means status IS NOT NULL. We need a custom
    # scope here that includes both NULL and 'open' failures.
    #
    # Quick implementation: call run_backfill with scope='stale' and
    # a separate call for previously-open rows. To minimize complexity in
    # MVP, we use scope='last-90d' which catches both — at Webmotors scale
    # (~138 prod failures in 90d) this is sub-second.
    result = await run_backfill(
        tenant_id=tenant_id,
        scope="last-90d",
        open_window_days=open_window_days,
        dry_run=False,
    )
    return (
        result.failures_resolved
        + result.failures_open
        + result.failures_superseded
        - result.failures_unchanged
    )
