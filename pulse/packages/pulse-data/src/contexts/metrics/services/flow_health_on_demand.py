"""On-demand Flow Health (Aging WIP + Flow Efficiency) computation.

Implements the v1 simplified formula documented in
`pulse/docs/metrics/kanban-formulas-v1.md` (FDD-KB-003 / FDD-KB-004).

Design decisions (from data-scientist validation, 2026-04-17):

- Aging WIP: age = NOW() - MAX(entered_at) over status_transitions
  entries whose normalized status ∈ {in_progress, in_review}. Fallback:
  started_at, then created_at. Reopen resets age (MAX semantics).
  WIP scope: normalized_status ∈ {in_progress, in_review} only
  (todo / done / backlog excluded).

- Flow Efficiency (v1 simplified):
    touch_time = Σ duration in transitions (in_progress, in_review)
    cycle_time = completed_at - started_at
    wait_time  = cycle_time - touch_time (implicit)
    FE = Σ touch_time / Σ cycle_time  (weighted sum, not mean-of-ratios)
  Issues with cycle_time < 1h or completed_at <= started_at are
  excluded (noise / corrupted). Sample floor = 5. When touch > cycle
  the item is capped at FE=1.0 and flagged `corrupted` in the detail.

- Snapshots deferred: Aging WIP mutates minute-to-minute and FE on a
  60d window changes hourly with ingestion. Compute on-demand with
  partial indexes; persist only if observability shows p95 > 1s.
  See FDD-KB-006.

Anti-surveillance:
- Output NEVER contains assignee, author, reporter, creator, or any
  individual-level identifier. `issue_key` is a public artifact.
- Title is intentionally excluded from items to cap blast radius in
  case of log capture — the frontend can fetch it via the
  engineering-data endpoint (which is rate-limited and audited).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.contexts.metrics.schemas import (
    AgingWipItem,
    AgingWipSummary,
    FlowEfficiencyData,
    FlowHealthResponse,
)
from src.database import get_session

logger = logging.getLogger(__name__)

# Cap item list to 500 (payload safety + frontend scatter density).
_AGING_WIP_ITEM_LIMIT = 500

# Min sample for a statistically honest FE — below it we flag insufficient_data.
_FE_MIN_SAMPLE = 5

# Absolute fallback for baseline P85 when both squad + tenant are empty.
# Conservative: 14 days — aligns with data-scientist doc section 5.
_BASELINE_ABSOLUTE_FALLBACK_DAYS = 14.0

# Statement timeout for the heavier Aging WIP / FE queries (milliseconds).
# 3s hard cap to fail-fast if JSONB parsing degrades at 800+ issues.
_STATEMENT_TIMEOUT_MS = 3000

# Baseline window for squad P85 cycle time (days).
_BASELINE_WINDOW_DAYS = 90

_FORMULA_DISCLAIMER_PT_BR = (
    "Fluxo de Eficiência calculado como tempo ativo (touch time) dividido pelo "
    "tempo total de ciclo. Versão simplificada — ainda não distingue filas "
    "explícitas de bloqueio (ex.: \"Aguardando Code Review\" conta como ativo). "
    "Interprete como tendência, não como número absoluto. Refinamento previsto "
    "com a configuração de workflow por tenant (R2)."
)


# ---------------------------------------------------------------------------
# SQL queries (ported from kanban-formulas-v1.md, sections 4-6)
# ---------------------------------------------------------------------------

# Aging WIP — list of open items with age (in days) derived from JSONB.
_SQL_AGING_WIP_ITEMS = """
SELECT
    i.issue_key,
    i.project_key                                   AS squad_key,
    i.normalized_status,
    i.status                                        AS raw_status,
    i.issue_type,
    GREATEST(
        0.0,
        COALESCE(
            EXTRACT(EPOCH FROM (NOW() - (
                SELECT MAX((t->>'entered_at')::timestamptz)
                FROM jsonb_array_elements(
                    COALESCE(i.status_transitions, '[]'::jsonb)
                ) AS t
                WHERE t->>'status' IN ('in_progress', 'in_review')
            ))) / 86400.0,
            EXTRACT(EPOCH FROM (NOW() - i.started_at)) / 86400.0,
            EXTRACT(EPOCH FROM (NOW() - i.created_at)) / 86400.0
        )
    )::numeric(10,1)                                AS age_days
FROM eng_issues i
WHERE
    i.tenant_id = :tenant_id
    AND i.normalized_status IN ('in_progress', 'in_review')
    AND ((:squad_key)::text IS NULL OR i.project_key = :squad_key)
ORDER BY age_days DESC
LIMIT :item_limit;
"""

# Baseline — P85 cycle time for a squad (or tenant-wide fallback).
# Returns two rows max: one scoped to squad_key (if provided) and one tenant-wide.
# The caller picks the squad row when n >= 10, else the tenant row.
_SQL_BASELINE = """
WITH squad_stats AS (
    SELECT
        project_key                                 AS scope,
        COUNT(*)                                    AS n,
        PERCENTILE_CONT(0.85) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                           AS p85_cycle_days
    FROM eng_issues
    WHERE
        tenant_id = :tenant_id
        AND normalized_status = 'done'
        AND completed_at IS NOT NULL
        AND started_at IS NOT NULL
        AND completed_at > started_at
        AND completed_at >= NOW() - INTERVAL '1 day' * :baseline_window_days
        AND ((:squad_key)::text IS NULL OR project_key = :squad_key)
    GROUP BY project_key
),
tenant_stats AS (
    SELECT
        'TENANT_WIDE'                               AS scope,
        COUNT(*)                                    AS n,
        PERCENTILE_CONT(0.85) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                           AS p85_cycle_days
    FROM eng_issues
    WHERE
        tenant_id = :tenant_id
        AND normalized_status = 'done'
        AND completed_at IS NOT NULL
        AND started_at IS NOT NULL
        AND completed_at > started_at
        AND completed_at >= NOW() - INTERVAL '1 day' * :baseline_window_days
)
SELECT scope, n, p85_cycle_days FROM squad_stats
UNION ALL
SELECT scope, n, p85_cycle_days FROM tenant_stats;
"""

# Flow Efficiency — weighted sum over resolved issues in the window.
# Returns one row with (sample_size, touch_total_sec, cycle_total_sec, corrupted_count).
_SQL_FLOW_EFFICIENCY = """
WITH issue_touch_time AS (
    SELECT
        i.id,
        EXTRACT(EPOCH FROM (i.completed_at - i.started_at))     AS cycle_time_seconds,
        COALESCE(
            (
                SELECT SUM(
                    CASE
                        WHEN (t->>'exited_at') IS NOT NULL THEN
                            EXTRACT(EPOCH FROM (
                                (t->>'exited_at')::timestamptz -
                                (t->>'entered_at')::timestamptz
                            ))
                        ELSE 0
                    END
                )
                FROM jsonb_array_elements(
                    COALESCE(i.status_transitions, '[]'::jsonb)
                ) AS t
                WHERE
                    t->>'status' IN ('in_progress', 'in_review')
                    AND (t->>'entered_at') IS NOT NULL
                    AND (
                        (t->>'exited_at') IS NULL
                        OR (t->>'exited_at')::timestamptz >
                           (t->>'entered_at')::timestamptz
                    )
            ),
            0
        )                                                        AS touch_time_seconds
    FROM eng_issues i
    WHERE
        i.tenant_id = :tenant_id
        AND i.normalized_status = 'done'
        AND i.completed_at IS NOT NULL
        AND i.started_at IS NOT NULL
        AND i.completed_at > i.started_at
        AND i.completed_at >= NOW() - INTERVAL '1 day' * :period_days
        AND EXTRACT(EPOCH FROM (i.completed_at - i.started_at)) >= 3600
        AND ((:squad_key)::text IS NULL OR i.project_key = :squad_key)
)
SELECT
    COUNT(*)                                                     AS sample_size,
    COALESCE(SUM(LEAST(touch_time_seconds, cycle_time_seconds)), 0)
                                                                 AS touch_total_sec,
    COALESCE(SUM(cycle_time_seconds), 0)                         AS cycle_total_sec,
    COUNT(CASE WHEN touch_time_seconds > cycle_time_seconds
               THEN 1 END)                                       AS corrupted_count,
    COUNT(CASE WHEN touch_time_seconds = 0 THEN 1 END)
                                                                 AS no_transitions_count
FROM issue_touch_time;
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def compute_flow_health(
    tenant_id: UUID,
    *,
    squad_key: str | None = None,
    period_days: int = 60,
) -> FlowHealthResponse:
    """Compute Aging WIP + Flow Efficiency for a tenant/squad on demand.

    Args:
        tenant_id: Tenant scope (enforced via RLS).
        squad_key: Optional Jira project_key (already uppercased by caller).
            When None, the computation is tenant-wide.
        period_days: Window for Flow Efficiency sample (default 60d). The
            Aging WIP baseline uses a fixed 90d window regardless.

    Returns:
        FlowHealthResponse with both metrics and metadata. Never raises;
        on DB error returns a response with zeroed/insufficient flags
        and logs the exception — frontend handles the degraded state.

    Anti-surveillance: the returned payload contains no PII. See
    `AgingWipItem` docstring for the full field list.
    """
    now = datetime.now(timezone.utc)
    squad_key_norm = squad_key.upper() if squad_key else None

    aging_summary = AgingWipSummary(
        count=0,
        p50_days=None,
        p85_days=None,
        at_risk_count=0,
        at_risk_threshold_days=None,
        baseline_source="absolute_fallback",
    )
    aging_items: list[AgingWipItem] = []
    fe = FlowEfficiencyData(
        value=None,
        sample_size=0,
        formula_version="v1_simplified",
        formula_disclaimer=_FORMULA_DISCLAIMER_PT_BR,
        insufficient_data=True,
    )

    async with get_session(tenant_id) as session:
        # Hard timeout protects the API pool from runaway JSONB scans.
        await session.execute(
            text(f"SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}")
        )

        # --- 1. Baseline P85 (squad preferred, tenant fallback) ---
        baseline_p85_days: float | None = None
        baseline_source = "absolute_fallback"
        try:
            baseline_rows = (
                await session.execute(
                    text(_SQL_BASELINE),
                    {
                        "tenant_id": str(tenant_id),
                        "squad_key": squad_key_norm,
                        "baseline_window_days": _BASELINE_WINDOW_DAYS,
                    },
                )
            ).fetchall()

            # When squad_key is None we're measuring tenant-wide, so we
            # only care about the TENANT_WIDE row. When a specific squad
            # is requested the squad_stats CTE returns at most one row
            # (due to the WHERE project_key = :squad_key filter).
            squad_row = (
                next(
                    (r for r in baseline_rows if r.scope != "TENANT_WIDE"),
                    None,
                )
                if squad_key_norm is not None
                else None
            )
            tenant_row = next(
                (r for r in baseline_rows if r.scope == "TENANT_WIDE"), None
            )

            if squad_row and squad_row.n >= 10 and squad_row.p85_cycle_days:
                baseline_p85_days = float(squad_row.p85_cycle_days)
                baseline_source = "squad_p85_90d"
            elif tenant_row and tenant_row.n >= 10 and tenant_row.p85_cycle_days:
                baseline_p85_days = float(tenant_row.p85_cycle_days)
                # For tenant-wide requests, tenant baseline is the correct
                # scope (not a "fallback"). Distinguish the labels so the
                # frontend chip doesn't mislead the user.
                baseline_source = (
                    "tenant_p85_90d"
                    if squad_key_norm is None
                    else "tenant_p85_90d_fallback"
                )
            else:
                baseline_p85_days = _BASELINE_ABSOLUTE_FALLBACK_DAYS
                baseline_source = "absolute_fallback"
        except Exception:  # noqa: BLE001
            logger.exception(
                "[flow_health] baseline query failed tenant=%s squad=%s",
                tenant_id, squad_key_norm,
            )
            baseline_p85_days = _BASELINE_ABSOLUTE_FALLBACK_DAYS

        at_risk_threshold_days = (
            baseline_p85_days * 2 if baseline_p85_days is not None else None
        )

        # --- 2. Aging WIP items ---
        try:
            item_rows = (
                await session.execute(
                    text(_SQL_AGING_WIP_ITEMS),
                    {
                        "tenant_id": str(tenant_id),
                        "squad_key": squad_key_norm,
                        "item_limit": _AGING_WIP_ITEM_LIMIT,
                    },
                )
            ).fetchall()

            ages: list[float] = []
            at_risk_count = 0
            for row in item_rows:
                age = float(row.age_days or 0.0)
                ages.append(age)
                is_at_risk = (
                    at_risk_threshold_days is not None
                    and age > at_risk_threshold_days
                )
                if is_at_risk:
                    at_risk_count += 1
                aging_items.append(
                    AgingWipItem(
                        issue_key=row.issue_key or "",
                        age_days=age,
                        status=row.raw_status or "",
                        status_category=row.normalized_status or "",
                        squad_key=row.squad_key,
                        is_at_risk=is_at_risk,
                    )
                )

            aging_summary = AgingWipSummary(
                count=len(ages),
                p50_days=_percentile(ages, 0.50),
                p85_days=_percentile(ages, 0.85),
                at_risk_count=at_risk_count,
                at_risk_threshold_days=(
                    round(at_risk_threshold_days, 1)
                    if at_risk_threshold_days is not None
                    else None
                ),
                baseline_source=baseline_source,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[flow_health] aging_wip query failed tenant=%s squad=%s",
                tenant_id, squad_key_norm,
            )

        # --- 3. Flow Efficiency ---
        try:
            fe_row = (
                await session.execute(
                    text(_SQL_FLOW_EFFICIENCY),
                    {
                        "tenant_id": str(tenant_id),
                        "squad_key": squad_key_norm,
                        "period_days": period_days,
                    },
                )
            ).fetchone()

            if fe_row is None:
                fe_sample, touch_sec, cycle_sec = 0, 0.0, 0.0
            else:
                fe_sample = int(fe_row.sample_size or 0)
                touch_sec = float(fe_row.touch_total_sec or 0)
                cycle_sec = float(fe_row.cycle_total_sec or 0)

            if fe_sample < _FE_MIN_SAMPLE or cycle_sec <= 0:
                fe = FlowEfficiencyData(
                    value=None,
                    sample_size=fe_sample,
                    formula_version="v1_simplified",
                    formula_disclaimer=_FORMULA_DISCLAIMER_PT_BR,
                    insufficient_data=True,
                )
            else:
                raw = touch_sec / cycle_sec
                # Cap defensively — the SQL already does LEAST() but we cap
                # again in case of float rounding.
                value = round(min(max(raw, 0.0), 1.0), 4)
                fe = FlowEfficiencyData(
                    value=value,
                    sample_size=fe_sample,
                    formula_version="v1_simplified",
                    formula_disclaimer=_FORMULA_DISCLAIMER_PT_BR,
                    insufficient_data=False,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[flow_health] flow_efficiency query failed tenant=%s squad=%s",
                tenant_id, squad_key_norm,
            )

    return FlowHealthResponse(
        period=f"{period_days}d",
        period_start=None,
        period_end=now,
        team_id=None,
        calculated_at=now,
        squad_key=squad_key_norm,
        period_days=period_days,
        aging_wip=aging_summary,
        aging_wip_items=aging_items,
        flow_efficiency=fe,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile. Returns None on empty list."""
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return round(sorted_vals[0], 1)
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac, 1)
