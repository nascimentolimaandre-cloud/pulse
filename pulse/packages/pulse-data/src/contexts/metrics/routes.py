"""API routes for BC4 — Metrics & Analytics.

Reads pre-calculated metrics from the metrics_snapshots table.
Snapshots are written by the Metrics Worker; these endpoints never
calculate metrics on the fly.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from src.config import settings
from src.contexts.metrics.infrastructure.models import MetricsSnapshot
from src.contexts.metrics.repositories import MetricsRepository
from src.contexts.metrics.services.home_on_demand import (
    compute_home_metrics_on_demand,
    compute_previous_period,
)
from src.contexts.metrics.services.recalculate import recalculate as _recalc_service
from src.contexts.metrics.schemas import (
    CycleTimeBreakdownData,
    CycleTimeMetricsData,
    CycleTimeResponse,
    DoraClassifications,
    DoraMetricsData,
    DoraResponse,
    HomeMetricCard,
    HomeMetricsData,
    HomeMetricsResponse,
    LeadTimeCoverage,
    LeanMetricsData,
    LeanResponse,
    SprintComparisonData,
    SprintMetricsData,
    SprintOverviewData,
    SprintResponse,
    ThroughputMetricsData,
    ThroughputResponse,
)
from src.database import get_session
from src.shared.tenant import get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/v1/metrics", tags=["metrics"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^(\d+)d$")
_VALID_PERIODS = {"7d", "14d", "30d", "60d", "90d", "120d", "custom"}
_MAX_CUSTOM_DAYS = 365


def _parse_period(
    period: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[datetime, datetime]:
    """Parse a period descriptor into (start, end) datetimes.

    Supports two modes:
    - Relative: "7d" | "14d" | "30d" | "60d" | "90d" | "120d"
    - Absolute: "custom" with explicit start_date and end_date (ISO dates).

    Raises HTTPException 400 on invalid input.
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(sorted(_VALID_PERIODS))}",
        )

    if period == "custom":
        if not start_date or not end_date:
            raise HTTPException(
                status_code=400,
                detail="Custom period requires both start_date and end_date (ISO YYYY-MM-DD).",
            )
        try:
            start = datetime.fromisoformat(start_date)
            end = datetime.fromisoformat(end_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid ISO date: {exc}",
            ) from exc
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start >= end:
            raise HTTPException(
                status_code=400,
                detail="start_date must be strictly before end_date.",
            )
        if (end - start).days > _MAX_CUSTOM_DAYS:
            raise HTTPException(
                status_code=400,
                detail=f"Custom period cannot exceed {_MAX_CUSTOM_DAYS} days.",
            )
        return start, end

    match = _PERIOD_RE.match(period)
    days = int(match.group(1))  # type: ignore[union-attr]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return start, end


async def _get_latest_snapshot(
    tenant_id: UUID,
    metric_type: str,
    metric_name: str,
    team_id: UUID | None,
) -> MetricsSnapshot | None:
    """Fetch the most recent snapshot for a given metric type/name."""
    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        snapshots = await repo.get_latest_snapshots(
            tenant_id=tenant_id,
            metric_type=metric_type,
            team_id=team_id,
            limit=20,
        )
        for snap in snapshots:
            if snap.metric_name == metric_name:
                return snap
        return None


async def _get_all_latest_snapshots(
    tenant_id: UUID,
    metric_type: str,
    team_id: UUID | None,
    period_days: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch latest snapshots for all metric_names of a given type.

    Returns a dict keyed by metric_name, each containing the snapshot's
    value, calculated_at, period_start, and period_end.
    The worker stores individual metric_names (e.g. "breakdown", "trend")
    rather than a single "all" snapshot, so this helper collects them.

    When `period_days` is provided, the selection prefers snapshots whose
    (period_end - period_start) window matches the requested length (±1 day
    for rounding). If no matching-period snapshot exists for a metric_name,
    we fall back to the latest snapshot of any period — preserves the prior
    behavior so partially-calculated tenants still get something. This closes
    the surface-level half of INC-002: snapshots are written per-period by
    the worker/recalc service, but the API was previously picking whichever
    one had the freshest `calculated_at` regardless of window length.
    """
    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        snapshots = await repo.get_latest_snapshots(
            tenant_id=tenant_id,
            metric_type=metric_type,
            team_id=team_id,
            # Widen window — with 6 periods × many metric_names we need room
            # to see at least one per period per metric_name.
            limit=200,
        )

        matched: dict[str, dict[str, Any]] = {}
        fallback: dict[str, dict[str, Any]] = {}

        for snap in snapshots:
            entry = {
                "value": snap.value,
                "calculated_at": snap.calculated_at,
                "period_start": snap.period_start,
                "period_end": snap.period_end,
            }

            if period_days is not None and snap.period_start and snap.period_end:
                span_days = (snap.period_end - snap.period_start).days
                if abs(span_days - period_days) <= 1 and snap.metric_name not in matched:
                    matched[snap.metric_name] = entry
                    continue

            if snap.metric_name not in fallback:
                fallback[snap.metric_name] = entry

        if period_days is None:
            return fallback

        # Merge: prefer matched, keep fallback for metric_names without a
        # period-specific snapshot (e.g. sprint overviews which ignore period).
        for name, entry in fallback.items():
            matched.setdefault(name, entry)
        return matched


async def _get_snapshot_by_period(
    tenant_id: UUID,
    metric_type: str,
    metric_name: str,
    period_start: datetime,
    period_end: datetime,
    team_id: UUID | None,
) -> MetricsSnapshot | None:
    """Fetch a snapshot matching the requested period window.

    Exact `period_start/period_end` matching fails whenever the worker and
    the API use different `now()` values (a few seconds apart), so we
    instead match by window length in days — the invariant that
    distinguishes 30d from 60d from 120d. Falls back to latest snapshot
    of any period as a last resort so partially-calculated tenants still
    render something.
    """
    requested_days = (period_end - period_start).days

    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        snapshots = await repo.get_latest_snapshots(
            tenant_id=tenant_id,
            metric_type=metric_type,
            team_id=team_id,
            limit=200,
        )

        # First pass: match same metric_name + same period length
        for snap in snapshots:
            if snap.metric_name != metric_name:
                continue
            if snap.period_start is None or snap.period_end is None:
                continue
            span_days = (snap.period_end - snap.period_start).days
            if abs(span_days - requested_days) <= 1:
                return snap

        # Fallback: any period, latest calculated_at
        for snap in snapshots:
            if snap.metric_name == metric_name:
                return snap
        return None


# ---------------------------------------------------------------------------
# DORA
# ---------------------------------------------------------------------------


@router.get("/dora", response_model=DoraResponse)
async def get_dora_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    squad_key: str | None = Query(
        None,
        description="(Accepted for URL compat; squad scoping not yet wired here — see FDD-DSH-060)",
        max_length=32,
    ),
    period: str = Query("30d", description="Time period (7d|14d|30d|60d|90d|120d|custom)"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> DoraResponse:
    """Get DORA metrics (DF, LT, CFR, MTTR) for the given period.

    Note: when `period=custom`, the response is computed from the snapshot with
    the closest matching window-length. Custom periods won't have perfect
    snapshots; for deep-dive accuracy on custom windows, use /metrics/home
    which computes on demand.
    """
    _ = squad_key  # documented no-op on this endpoint
    period_start, period_end = _parse_period(period, start_date, end_date)

    snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="dora",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )

    if not snapshot:
        return DoraResponse(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            calculated_at=None,
            data=DoraMetricsData(),
        )

    value = snapshot.value or {}

    classifications = None
    if any(value.get(k) for k in ("df_level", "lt_level", "cfr_level", "mttr_level")):
        classifications = DoraClassifications(
            deployment_frequency=value.get("df_level"),
            lead_time=value.get("lt_level"),
            change_failure_rate=value.get("cfr_level"),
            mttr=value.get("mttr_level"),
        )

    return DoraResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=snapshot.calculated_at,
        data=DoraMetricsData(
            deployment_frequency_per_day=value.get("deployment_frequency_per_day"),
            deployment_frequency_per_week=value.get("deployment_frequency_per_week"),
            lead_time_for_changes_hours=value.get("lead_time_for_changes_hours"),
            change_failure_rate=value.get("change_failure_rate"),
            mean_time_to_recovery_hours=value.get("mean_time_to_recovery_hours"),
            overall_level=value.get("overall_level"),
            classifications=classifications,
        ),
    )


# ---------------------------------------------------------------------------
# Lean
# ---------------------------------------------------------------------------


@router.get("/lean", response_model=LeanResponse)
async def get_lean_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    squad_key: str | None = Query(None, max_length=32),
    period: str = Query("30d", description="Time period (7d|14d|30d|60d|90d|120d|custom)"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> LeanResponse:
    """Get Lean metrics (CFD, WIP, Lead Time Distribution, Throughput).

    The worker writes separate snapshots per sub-metric (cfd, wip,
    lead_time_distribution, throughput, scatterplot). This endpoint
    combines them into a single response.
    """
    _ = squad_key  # See FDD-DSH-060
    period_start, period_end = _parse_period(period, start_date, end_date)
    period_days = (period_end - period_start).days

    all_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id,
        metric_type="lean",
        team_id=team_id,
        period_days=period_days,
    )

    if not all_snaps:
        return LeanResponse(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            calculated_at=None,
            data=LeanMetricsData(),
        )

    # Extract from individual snapshots
    cfd_raw = all_snaps.get("cfd", {}).get("value", {})
    cfd_points = cfd_raw.get("points") if isinstance(cfd_raw, dict) else None

    wip_raw = all_snaps.get("wip", {}).get("value", {})
    wip_count = wip_raw.get("wip_count") if isinstance(wip_raw, dict) else None

    lt_raw = all_snaps.get("lead_time_distribution", {}).get("value")

    tp_raw = all_snaps.get("throughput", {}).get("value", {})
    tp_points = tp_raw.get("points") if isinstance(tp_raw, dict) else None

    scatter_raw = all_snaps.get("scatterplot", {}).get("value")

    # Pick the most recent calculated_at across sub-snapshots
    calc_times = [
        s["calculated_at"] for s in all_snaps.values() if s.get("calculated_at")
    ]
    latest_calc = max(calc_times) if calc_times else None

    return LeanResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=latest_calc,
        data=LeanMetricsData(
            cfd=cfd_points,
            wip=wip_count,
            lead_time_distribution=lt_raw,
            throughput=tp_points,
            scatterplot=scatter_raw,
        ),
    )


# ---------------------------------------------------------------------------
# Cycle Time
# ---------------------------------------------------------------------------


@router.get("/cycle-time", response_model=CycleTimeResponse)
async def get_cycle_time_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    squad_key: str | None = Query(None, max_length=32),
    period: str = Query("30d", description="Time period (7d|14d|30d|60d|90d|120d|custom)"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> CycleTimeResponse:
    """Get cycle time breakdown and trend."""
    _ = squad_key  # See FDD-DSH-060
    period_start, period_end = _parse_period(period, start_date, end_date)
    period_days = (period_end - period_start).days

    # Worker writes separate snapshots: (cycle_time, breakdown) and (cycle_time, trend)
    all_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id,
        period_days=period_days,
        metric_type="cycle_time",
        team_id=team_id,
    )

    if not all_snaps:
        return CycleTimeResponse(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            calculated_at=None,
            data=CycleTimeMetricsData(),
        )

    breakdown_snap = all_snaps.get("breakdown", {})
    trend_snap = all_snaps.get("trend", {})

    breakdown_raw = breakdown_snap.get("value") if breakdown_snap else None
    breakdown = None
    if breakdown_raw and isinstance(breakdown_raw, dict):
        breakdown = CycleTimeBreakdownData(**breakdown_raw)

    # trend snapshot value is {"points": [...]}, schema expects the list directly
    trend_raw = trend_snap.get("value") if trend_snap else None
    trend_value = None
    if isinstance(trend_raw, dict):
        trend_value = trend_raw.get("points")
    elif isinstance(trend_raw, list):
        trend_value = trend_raw

    # Pick the most recent calculated_at across sub-snapshots
    calc_times = [
        s["calculated_at"] for s in all_snaps.values() if s.get("calculated_at")
    ]
    latest_calc = max(calc_times) if calc_times else None

    return CycleTimeResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=latest_calc,
        data=CycleTimeMetricsData(
            breakdown=breakdown,
            trend=trend_value,
        ),
    )


# ---------------------------------------------------------------------------
# Throughput
# ---------------------------------------------------------------------------


@router.get("/throughput", response_model=ThroughputResponse)
async def get_throughput_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    squad_key: str | None = Query(None, max_length=32),
    period: str = Query("30d", description="Time period (7d|14d|30d|60d|90d|120d|custom)"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> ThroughputResponse:
    """Get throughput trend and PR analytics."""
    _ = squad_key  # See FDD-DSH-060
    period_start, period_end = _parse_period(period, start_date, end_date)
    period_days = (period_end - period_start).days

    # Worker writes separate snapshots: (throughput, trend) and (throughput, pr_analytics)
    all_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id,
        metric_type="throughput",
        period_days=period_days,
        team_id=team_id,
    )

    if not all_snaps:
        return ThroughputResponse(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            calculated_at=None,
            data=ThroughputMetricsData(),
        )

    trend_snap = all_snaps.get("trend", {})
    pr_snap = all_snaps.get("pr_analytics", {})

    # trend snapshot value is {"points": [...]}, schema expects the list directly
    trend_raw = trend_snap.get("value") if trend_snap else None
    trend_value = None
    if isinstance(trend_raw, dict):
        trend_value = trend_raw.get("points")
    elif isinstance(trend_raw, list):
        trend_value = trend_raw

    pr_value = pr_snap.get("value") if pr_snap else None

    # Pick the most recent calculated_at across sub-snapshots
    calc_times = [
        s["calculated_at"] for s in all_snaps.values() if s.get("calculated_at")
    ]
    latest_calc = max(calc_times) if calc_times else None

    return ThroughputResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=latest_calc,
        data=ThroughputMetricsData(
            trend=trend_value,
            pr_analytics=pr_value,
        ),
    )


# ---------------------------------------------------------------------------
# Sprints
# ---------------------------------------------------------------------------


@router.get("/sprints", response_model=SprintResponse)
async def get_sprint_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    squad_key: str | None = Query(None, max_length=32),
    sprint_id: UUID | None = Query(None, description="Specific sprint"),
    period: str | None = Query(None, description="Accepted for URL compat; ignored"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> SprintResponse:
    """Get sprint overview and comparison metrics.

    The worker writes overview snapshots as "overview_{sprint_id}" and
    a single "comparison" snapshot. This endpoint finds the most recent
    overview and combines it with the comparison data.
    """
    _ = (squad_key, sprint_id, period, start_date, end_date)  # Accepted for URL compat
    all_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id,
        metric_type="sprint",
        team_id=team_id,
    )

    if not all_snaps:
        return SprintResponse(
            team_id=team_id,
            calculated_at=None,
            data=SprintMetricsData(),
        )

    # Find the latest overview_* snapshot (most recent period_end)
    overview = None
    latest_overview_time = None
    for key, snap in all_snaps.items():
        if not key.startswith("overview_"):
            continue
        snap_time = snap.get("calculated_at")
        if latest_overview_time is None or (snap_time and snap_time > latest_overview_time):
            latest_overview_time = snap_time
            ov = snap.get("value", {})
            if ov:
                overview = SprintOverviewData(**{
                    k: v for k, v in ov.items()
                    if k in SprintOverviewData.model_fields
                })

    # Comparison snapshot
    comparison = None
    comparison_snap = all_snaps.get("comparison", {})
    cv = comparison_snap.get("value", {})
    if cv:
        comparison = SprintComparisonData(**cv)

    # Pick the most recent calculated_at
    calc_times = [
        s["calculated_at"] for s in all_snaps.values() if s.get("calculated_at")
    ]
    calculated_at = max(calc_times) if calc_times else None

    return SprintResponse(
        team_id=team_id,
        calculated_at=calculated_at,
        data=SprintMetricsData(
            overview=overview,
            comparison=comparison,
        ),
    )


# ---------------------------------------------------------------------------
# Home Dashboard Summary
# ---------------------------------------------------------------------------


def _compute_trend(
    current: float | None,
    previous: float | None,
) -> tuple[float | None, str | None]:
    """Compute % change and direction between current and previous values.

    Returns (trend_percentage, trend_direction).
    - trend_percentage is None when comparison is impossible (no previous data).
    - trend_direction is "up" | "down" | "flat".
    """
    if current is None or previous is None:
        return None, None
    if previous == 0:
        if current == 0:
            return 0.0, "flat"
        return None, None  # can't compute % from zero base

    pct = round(((current - previous) / abs(previous)) * 100, 1)
    if pct > 5:
        direction = "up"
    elif pct < -5:
        direction = "down"
    else:
        direction = "flat"
    return pct, direction


async def _get_previous_period_snapshots(
    tenant_id: UUID,
    metric_type: str,
    team_id: UUID | None,
    cutoff_date: datetime,
) -> dict[str, dict[str, Any]]:
    """Fetch snapshots calculated BEFORE the cutoff date (previous period).

    Used for period-over-period comparison. For a 30d view, pass
    cutoff_date = now - 30 days to get snapshots from the previous 30d window.
    """
    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        snapshots = await repo.get_snapshots_before_date(
            tenant_id=tenant_id,
            metric_type=metric_type,
            before_date=cutoff_date,
            team_id=team_id,
            limit=20,
        )
        result: dict[str, dict[str, Any]] = {}
        for snap in snapshots:
            if snap.metric_name not in result:
                result[snap.metric_name] = {
                    "value": snap.value,
                    "calculated_at": snap.calculated_at,
                }
        return result


def _build_home_response(
    *,
    period: str,
    period_start: datetime,
    period_end: datetime,
    team_id: UUID | None,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> HomeMetricsResponse:
    """Shared response builder for the on-demand home metrics path.

    Mirrors the structure of the snapshot-driven path. `current` and `previous`
    are dicts returned by compute_home_metrics_on_demand.
    """
    dora_all = current.get("dora_all") or {}
    ct_val = current.get("cycle_time_breakdown") or {}
    tp_val = current.get("throughput_pr_analytics") or {}
    wip_val = current.get("lean_wip") or {}

    prev_dora = previous.get("dora_all") or {}
    prev_ct = previous.get("cycle_time_breakdown") or {}
    prev_tp = previous.get("throughput_pr_analytics") or {}
    prev_wip = previous.get("lean_wip") or {}

    df_val = dora_all.get("deployment_frequency_per_day")
    prev_df_val = prev_dora.get("deployment_frequency_per_day")
    df_pct, df_dir = _compute_trend(df_val, prev_df_val)

    lt_val = dora_all.get("lead_time_for_changes_hours")
    prev_lt_val = prev_dora.get("lead_time_for_changes_hours")
    lt_pct, lt_dir = _compute_trend(lt_val, prev_lt_val)

    # Strict DORA Lead Time (FDD-DSH-082) — deployed_at only.
    lt_strict_val = dora_all.get("lead_time_for_changes_hours_strict")
    prev_lt_strict = prev_dora.get("lead_time_for_changes_hours_strict")
    lt_strict_pct, lt_strict_dir = _compute_trend(lt_strict_val, prev_lt_strict)
    lt_strict_eligible = int(dora_all.get("lead_time_strict_eligible_count") or 0)
    lt_strict_total = int(dora_all.get("lead_time_strict_total_count") or 0)
    lt_strict_pct_cov = (
        round(lt_strict_eligible / lt_strict_total, 4)
        if lt_strict_total > 0
        else 0.0
    )

    cfr_val = dora_all.get("change_failure_rate")
    prev_cfr_val = prev_dora.get("change_failure_rate")
    cfr_pct, cfr_dir = _compute_trend(cfr_val, prev_cfr_val)

    ct_p50 = ct_val.get("total_p50")
    ct_p85 = ct_val.get("total_p85")
    prev_ct_p50 = prev_ct.get("total_p50")
    prev_ct_p85 = prev_ct.get("total_p85")
    ct_pct, ct_dir = _compute_trend(ct_p50, prev_ct_p50)
    ct85_pct, ct85_dir = _compute_trend(ct_p85, prev_ct_p85)

    tp_total = tp_val.get("total_merged")
    prev_tp_total = prev_tp.get("total_merged")
    tp_pct, tp_dir = _compute_trend(tp_total, prev_tp_total)

    wip_count = wip_val.get("wip_count")
    prev_wip_count = prev_wip.get("wip_count")
    wip_pct, wip_dir = _compute_trend(wip_count, prev_wip_count)

    return HomeMetricsResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=datetime.now(timezone.utc),
        data=HomeMetricsData(
            deployment_frequency=HomeMetricCard(
                value=df_val, unit="deploys/day", level=dora_all.get("df_level"),
                trend_direction=df_dir, trend_percentage=df_pct, previous_value=prev_df_val,
            ),
            lead_time=HomeMetricCard(
                value=lt_val, unit="hours", level=dora_all.get("lt_level"),
                trend_direction=lt_dir, trend_percentage=lt_pct, previous_value=prev_lt_val,
            ),
            lead_time_strict=HomeMetricCard(
                value=lt_strict_val, unit="hours", level=dora_all.get("lt_strict_level"),
                trend_direction=lt_strict_dir, trend_percentage=lt_strict_pct,
                previous_value=prev_lt_strict,
                coverage=LeadTimeCoverage(
                    covered=lt_strict_eligible,
                    total=lt_strict_total,
                    pct=lt_strict_pct_cov,
                ),
            ),
            change_failure_rate=HomeMetricCard(
                value=cfr_val, unit="ratio", level=dora_all.get("cfr_level"),
                trend_direction=cfr_dir, trend_percentage=cfr_pct, previous_value=prev_cfr_val,
            ),
            cycle_time=HomeMetricCard(
                value=ct_p50, unit="hours",
                trend_direction=ct_dir, trend_percentage=ct_pct, previous_value=prev_ct_p50,
            ),
            cycle_time_p85=HomeMetricCard(
                value=ct_p85, unit="hours",
                trend_direction=ct85_dir, trend_percentage=ct85_pct, previous_value=prev_ct_p85,
            ),
            time_to_restore=HomeMetricCard(unit="hours"),
            wip=HomeMetricCard(
                value=wip_count, unit="items",
                trend_direction=wip_dir, trend_percentage=wip_pct, previous_value=prev_wip_count,
            ),
            throughput=HomeMetricCard(
                value=tp_total, unit="PRs merged",
                trend_direction=tp_dir, trend_percentage=tp_pct, previous_value=prev_tp_total,
            ),
            overall_dora_level=dora_all.get("overall_level"),
        ),
    )


@router.get("/home", response_model=HomeMetricsResponse)
async def get_home_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team (UUID)"),
    squad_key: str | None = Query(
        None,
        description="Filter by squad project key (e.g. 'OKM'). Uses on-demand computation.",
        max_length=32,
    ),
    period: str = Query("30d", description="Time period (7d|14d|30d|60d|90d|120d|custom)"),
    start_date: str | None = Query(None, description="ISO date (required if period=custom)"),
    end_date: str | None = Query(None, description="ISO date (required if period=custom)"),
) -> HomeMetricsResponse:
    """Get summary metrics for the home dashboard.

    Three computation paths:

    1. **Fast path** (squad_key=None, period ∈ standard set): reads pre-calculated
       snapshots from `metrics_snapshots`. Period-over-period trend uses a prior
       snapshot from the history.
    2. **Squad-filtered path** (squad_key set): computes on-demand by filtering
       PRs/issues/deploys scoped to the squad's project key. Snapshots don't exist
       per-squad (27 squads × 6 periods × 4 metric types would explode the
       table), so we compute each request. Previous period is also computed on
       demand for trend arrows.
    3. **Custom period path** (period='custom'): computes on-demand for an
       arbitrary window. Previous period = same-length window immediately before.

    Paths 2 and 3 share the same service (compute_home_metrics_on_demand).
    """
    period_start, period_end = _parse_period(period, start_date, end_date)
    period_days = (period_end - period_start).days

    # --- On-demand path for squad_key or custom period ---
    if squad_key or period == "custom":
        logger.info(
            "[home] on-demand compute tenant=%s squad=%s period=%s days=%d",
            tenant_id, squad_key, period, period_days,
        )
        current = await compute_home_metrics_on_demand(
            tenant_id,
            period_start=period_start,
            period_end=period_end,
            squad_key=squad_key,
        )
        previous = await compute_previous_period(
            tenant_id,
            current_start=period_start,
            current_end=period_end,
            squad_key=squad_key,
        )
        return _build_home_response(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            current=current,
            previous=previous,
        )

    # --- Snapshot (fast) path below ---
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=period_days)

    # ── Current period snapshots ──
    dora_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="dora", team_id=team_id,
        period_days=period_days,
    )
    lean_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="lean", team_id=team_id,
        period_days=period_days,
    )
    ct_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="cycle_time", team_id=team_id,
        period_days=period_days,
    )
    tp_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="throughput", team_id=team_id,
        period_days=period_days,
    )

    # ── Previous period snapshots (for trend comparison) ──
    prev_dora = await _get_previous_period_snapshots(
        tenant_id, "dora", team_id, cutoff_date,
    )
    prev_lean = await _get_previous_period_snapshots(
        tenant_id, "lean", team_id, cutoff_date,
    )
    prev_ct = await _get_previous_period_snapshots(
        tenant_id, "cycle_time", team_id, cutoff_date,
    )
    prev_tp = await _get_previous_period_snapshots(
        tenant_id, "throughput", team_id, cutoff_date,
    )

    # ── Extract CURRENT values ──
    dora_all = dora_snaps.get("all", {}).get("value", {}) if dora_snaps.get("all") else {}
    ct_breakdown_val = ct_snaps.get("breakdown", {}).get("value", {}) if ct_snaps.get("breakdown") else {}
    ct_p50 = ct_breakdown_val.get("total_p50") if isinstance(ct_breakdown_val, dict) else None
    ct_p85 = ct_breakdown_val.get("total_p85") if isinstance(ct_breakdown_val, dict) else None
    tp_analytics_val = tp_snaps.get("pr_analytics", {}).get("value", {}) if tp_snaps.get("pr_analytics") else {}
    tp_total = tp_analytics_val.get("total_merged") if isinstance(tp_analytics_val, dict) else None
    # Lean worker writes individual snapshots (wip, cfd, etc.) not a single "all"
    lean_wip_snap = lean_snaps.get("wip", {}).get("value", {}) if lean_snaps.get("wip") else {}
    lean_wip = lean_wip_snap.get("wip_count") if isinstance(lean_wip_snap, dict) else None

    # ── Extract PREVIOUS values ──
    prev_dora_all = prev_dora.get("all", {}).get("value", {}) if prev_dora.get("all") else {}
    prev_ct_val = prev_ct.get("breakdown", {}).get("value", {}) if prev_ct.get("breakdown") else {}
    prev_ct_p50 = prev_ct_val.get("total_p50") if isinstance(prev_ct_val, dict) else None
    prev_ct_p85 = prev_ct_val.get("total_p85") if isinstance(prev_ct_val, dict) else None
    prev_tp_val = prev_tp.get("pr_analytics", {}).get("value", {}) if prev_tp.get("pr_analytics") else {}
    prev_tp_total = prev_tp_val.get("total_merged") if isinstance(prev_tp_val, dict) else None
    prev_lean_wip_snap = prev_lean.get("wip", {}).get("value", {}) if prev_lean.get("wip") else {}
    prev_lean_wip = prev_lean_wip_snap.get("wip_count") if isinstance(prev_lean_wip_snap, dict) else None

    # ── Compute trends (current vs previous) ──
    df_val = dora_all.get("deployment_frequency_per_day")
    prev_df_val = prev_dora_all.get("deployment_frequency_per_day")
    df_pct, df_dir = _compute_trend(df_val, prev_df_val)

    lt_val = dora_all.get("lead_time_for_changes_hours")
    prev_lt_val = prev_dora_all.get("lead_time_for_changes_hours")
    lt_pct, lt_dir = _compute_trend(lt_val, prev_lt_val)

    # Strict DORA Lead Time (FDD-DSH-082) — present in snapshots written
    # AFTER the schema bump. Older snapshots will simply omit these keys
    # and the card renders empty (frontend handles null gracefully).
    lt_strict_val = dora_all.get("lead_time_for_changes_hours_strict")
    prev_lt_strict_val = prev_dora_all.get("lead_time_for_changes_hours_strict")
    lt_strict_pct, lt_strict_dir = _compute_trend(lt_strict_val, prev_lt_strict_val)
    lt_strict_eligible = int(dora_all.get("lead_time_strict_eligible_count") or 0)
    lt_strict_total = int(dora_all.get("lead_time_strict_total_count") or 0)
    lt_strict_pct_cov = (
        round(lt_strict_eligible / lt_strict_total, 4)
        if lt_strict_total > 0
        else 0.0
    )

    cfr_val = dora_all.get("change_failure_rate")
    prev_cfr_val = prev_dora_all.get("change_failure_rate")
    cfr_pct, cfr_dir = _compute_trend(cfr_val, prev_cfr_val)

    ct_pct, ct_dir = _compute_trend(ct_p50, prev_ct_p50)
    ct85_pct, ct85_dir = _compute_trend(ct_p85, prev_ct_p85)
    wip_pct, wip_dir = _compute_trend(lean_wip, prev_lean_wip)
    tp_pct, tp_dir = _compute_trend(tp_total, prev_tp_total)

    # ── Determine latest calculated_at ──
    timestamps = [
        s["calculated_at"]
        for snaps in (dora_snaps, lean_snaps, ct_snaps, tp_snaps)
        for s in snaps.values()
        if s.get("calculated_at")
    ]
    latest_calc = max(timestamps) if timestamps else None

    return HomeMetricsResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=latest_calc,
        data=HomeMetricsData(
            deployment_frequency=HomeMetricCard(
                value=df_val,
                unit="deploys/day",
                level=dora_all.get("df_level"),
                trend_direction=df_dir,
                trend_percentage=df_pct,
                previous_value=prev_df_val,
            ),
            lead_time=HomeMetricCard(
                value=lt_val,
                unit="hours",
                level=dora_all.get("lt_level"),
                trend_direction=lt_dir,
                trend_percentage=lt_pct,
                previous_value=prev_lt_val,
            ),
            lead_time_strict=HomeMetricCard(
                value=lt_strict_val,
                unit="hours",
                level=dora_all.get("lt_strict_level"),
                trend_direction=lt_strict_dir,
                trend_percentage=lt_strict_pct,
                previous_value=prev_lt_strict_val,
                coverage=LeadTimeCoverage(
                    covered=lt_strict_eligible,
                    total=lt_strict_total,
                    pct=lt_strict_pct_cov,
                ),
            ),
            change_failure_rate=HomeMetricCard(
                value=cfr_val,
                unit="ratio",
                level=dora_all.get("cfr_level"),
                trend_direction=cfr_dir,
                trend_percentage=cfr_pct,
                previous_value=prev_cfr_val,
            ),
            cycle_time=HomeMetricCard(
                value=ct_p50,
                unit="hours",
                trend_direction=ct_dir,
                trend_percentage=ct_pct,
                previous_value=prev_ct_p50,
            ),
            cycle_time_p85=HomeMetricCard(
                value=ct_p85,
                unit="hours",
                trend_direction=ct85_dir,
                trend_percentage=ct85_pct,
                previous_value=prev_ct_p85,
            ),
            # Time to Restore (MTTR) requires incident ingestion pipeline (R1 roadmap).
            # Returns an empty card so the frontend renders "—" with explanatory tooltip.
            # See backlog: FDD-DSH-050 — MTTR/Time to Restore.
            time_to_restore=HomeMetricCard(unit="hours"),
            wip=HomeMetricCard(
                value=lean_wip,
                unit="items",
                trend_direction=wip_dir,
                trend_percentage=wip_pct,
                previous_value=prev_lean_wip,
            ),
            throughput=HomeMetricCard(
                value=tp_total,
                unit="PRs merged",
                trend_direction=tp_dir,
                trend_percentage=tp_pct,
                previous_value=prev_tp_total,
            ),
            overall_dora_level=dora_all.get("overall_level"),
        ),
    )


# ---------------------------------------------------------------------------
# Admin — manual snapshot recalculation
# ---------------------------------------------------------------------------
#
# Protected by a shared internal token (X-Admin-Token). The worker's normal
# path is still event-driven via Kafka; this endpoint exists so operators can
# force a refresh without waiting for the sync cycle (e.g. after deploying a
# fix that changed how snapshots are calculated).
#
# READ-ONLY w.r.t. external systems: this endpoint only reads PULSE DB and
# writes metrics_snapshots. It never calls Jenkins/Jira/GitHub.

admin_router = APIRouter(prefix="/data/v1/admin/metrics", tags=["metrics-admin"])


def _check_admin_token(x_admin_token: str | None) -> None:
    """Validate the admin token using constant-time comparison.

    Unlike discovery_scheduler's `_check_internal_token`, we do NOT fall back
    to "allow all" when the token is empty — this endpoint mutates DB state
    and must always be authenticated. Ops must set INTERNAL_API_TOKEN.
    """
    import hmac

    expected = getattr(settings, "internal_api_token", "") or ""
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin endpoint disabled: INTERNAL_API_TOKEN not configured",
        )
    if x_admin_token is None or not hmac.compare_digest(
        x_admin_token.encode(), expected.encode()
    ):
        raise HTTPException(status_code=403, detail="Invalid admin token")


@admin_router.post("/recalculate")
async def admin_recalculate_metrics(
    metric_type: str = Query("all", description="throughput|cycle_time|dora|lean|sprint|all"),
    period: str = Query("all", description="7d|14d|30d|60d|90d|120d|all"),
    team_id: UUID | None = Query(None, description="Optional team scope"),
    dry_run: bool = Query(False, description="Count entities without writing snapshots"),
    tenant_id: UUID = Depends(get_tenant_id),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Force a metrics recalculation for the current tenant.

    Useful when code changes mean the last Kafka-driven snapshots are stale
    (e.g. after adding new period windows or fixing a calculation bug) and
    waiting for the next PR/issue event would delay validation.
    """
    _check_admin_token(x_admin_token)

    started = datetime.now(timezone.utc)
    logger.warning(
        "[admin] Recalc triggered tenant=%s metric_type=%s period=%s team=%s dry_run=%s",
        tenant_id, metric_type, period, team_id, dry_run,
    )

    try:
        result = await _recalc_service(
            tenant_id=tenant_id,
            metric_type=metric_type,
            period=period,
            team_id=team_id,
            dry_run=dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    finished = datetime.now(timezone.utc)
    return {
        "status": "completed",
        "triggered_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_sec": round((finished - started).total_seconds(), 2),
        "dry_run": dry_run,
        "tenant_id": str(tenant_id),
        "team_id": str(team_id) if team_id else None,
        "recalculated": result.recalculated,
        "snapshots_written": result.snapshots_written,
        "scanned": result.scanned,
        "errors": result.errors,
    }
