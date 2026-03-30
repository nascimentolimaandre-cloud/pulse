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

from fastapi import APIRouter, Depends, HTTPException, Query

from src.contexts.metrics.infrastructure.models import MetricsSnapshot
from src.contexts.metrics.repositories import MetricsRepository
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
_VALID_PERIODS = {"7d", "14d", "30d", "90d"}


def _parse_period(period: str) -> tuple[datetime, datetime]:
    """Parse a period string like '30d' into (start, end) datetimes.

    Raises HTTPException 400 for invalid period values.
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(sorted(_VALID_PERIODS))}",
        )
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
) -> dict[str, dict[str, Any]]:
    """Fetch latest snapshots for all metric_names of a given type.

    Returns a dict keyed by metric_name, each containing the snapshot's
    value, calculated_at, period_start, and period_end.
    The worker stores individual metric_names (e.g. "breakdown", "trend")
    rather than a single "all" snapshot, so this helper collects them.
    """
    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        snapshots = await repo.get_latest_snapshots(
            tenant_id=tenant_id,
            metric_type=metric_type,
            team_id=team_id,
            limit=20,
        )
        result: dict[str, dict[str, Any]] = {}
        for snap in snapshots:
            if snap.metric_name not in result:  # keep latest only
                result[snap.metric_name] = {
                    "value": snap.value,
                    "calculated_at": snap.calculated_at,
                    "period_start": snap.period_start,
                    "period_end": snap.period_end,
                }
        return result


async def _get_snapshot_by_period(
    tenant_id: UUID,
    metric_type: str,
    metric_name: str,
    period_start: datetime,
    period_end: datetime,
    team_id: UUID | None,
) -> MetricsSnapshot | None:
    """Fetch a snapshot matching the exact period, or fall back to latest."""
    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        # Try exact period match first
        snapshot = await repo.get_snapshot(
            tenant_id=tenant_id,
            metric_type=metric_type,
            metric_name=metric_name,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
        )
        if snapshot:
            return snapshot

        # Fall back to the latest snapshot for this metric type/name
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


# ---------------------------------------------------------------------------
# DORA
# ---------------------------------------------------------------------------


@router.get("/dora", response_model=DoraResponse)
async def get_dora_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    period: str = Query("30d", description="Time period (7d|14d|30d|90d)"),
) -> DoraResponse:
    """Get DORA metrics (DF, LT, CFR, MTTR) for the given period."""
    period_start, period_end = _parse_period(period)

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
    period: str = Query("30d", description="Time period (7d|14d|30d|90d)"),
) -> LeanResponse:
    """Get Lean metrics (CFD, WIP, Lead Time Distribution, Throughput)."""
    period_start, period_end = _parse_period(period)

    snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="lean",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )

    if not snapshot:
        return LeanResponse(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            calculated_at=None,
            data=LeanMetricsData(),
        )

    value = snapshot.value or {}

    return LeanResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=snapshot.calculated_at,
        data=LeanMetricsData(
            cfd=value.get("cfd"),
            wip=value.get("wip"),
            lead_time_distribution=value.get("lead_time_distribution"),
            throughput=value.get("throughput"),
            scatterplot=value.get("scatterplot"),
        ),
    )


# ---------------------------------------------------------------------------
# Cycle Time
# ---------------------------------------------------------------------------


@router.get("/cycle-time", response_model=CycleTimeResponse)
async def get_cycle_time_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    period: str = Query("30d", description="Time period (7d|14d|30d|90d)"),
) -> CycleTimeResponse:
    """Get cycle time breakdown and trend."""
    period_start, period_end = _parse_period(period)

    # Worker writes separate snapshots: (cycle_time, breakdown) and (cycle_time, trend)
    all_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id,
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
    period: str = Query("30d", description="Time period (7d|14d|30d|90d)"),
) -> ThroughputResponse:
    """Get throughput trend and PR analytics."""
    period_start, period_end = _parse_period(period)

    # Worker writes separate snapshots: (throughput, trend) and (throughput, pr_analytics)
    all_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id,
        metric_type="throughput",
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
    sprint_id: UUID | None = Query(None, description="Specific sprint"),
) -> SprintResponse:
    """Get sprint overview and comparison metrics."""
    # Sprint metrics use the latest snapshot (not period-based)
    overview_snapshot = await _get_latest_snapshot(
        tenant_id=tenant_id,
        metric_type="sprint",
        metric_name="overview",
        team_id=team_id,
    )

    comparison_snapshot = await _get_latest_snapshot(
        tenant_id=tenant_id,
        metric_type="sprint",
        metric_name="comparison",
        team_id=team_id,
    )

    overview = None
    comparison = None
    calculated_at = None

    if overview_snapshot:
        ov = overview_snapshot.value or {}
        overview = SprintOverviewData(**ov) if ov else None
        calculated_at = overview_snapshot.calculated_at

    if comparison_snapshot:
        cv = comparison_snapshot.value or {}
        comparison = SprintComparisonData(**cv) if cv else None
        if not calculated_at:
            calculated_at = comparison_snapshot.calculated_at

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


@router.get("/home", response_model=HomeMetricsResponse)
async def get_home_metrics(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team"),
    period: str = Query("30d", description="Time period (7d|14d|30d|90d)"),
) -> HomeMetricsResponse:
    """Get summary metrics for the home dashboard.

    Aggregates key values from DORA, Lean, Cycle Time, and Throughput
    snapshots into a single response for the overview cards.
    """
    period_start, period_end = _parse_period(period)

    # Fetch latest snapshots for each metric type individually.
    # Worker writes individual metric_names, not a single "all" snapshot.
    dora_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="dora", team_id=team_id,
    )
    lean_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="lean", team_id=team_id,
    )
    ct_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="cycle_time", team_id=team_id,
    )
    tp_snaps = await _get_all_latest_snapshots(
        tenant_id=tenant_id, metric_type="throughput", team_id=team_id,
    )

    # Extract values from individual snapshots
    # DORA: may have "all" or individual metric names -- not in DB yet, safe defaults
    dora_all = dora_snaps.get("all", {}).get("value", {}) if dora_snaps.get("all") else {}

    # Cycle time: breakdown snapshot contains total_p50
    ct_breakdown_val = ct_snaps.get("breakdown", {}).get("value", {}) if ct_snaps.get("breakdown") else {}
    ct_p50 = ct_breakdown_val.get("total_p50") if isinstance(ct_breakdown_val, dict) else None

    # Throughput: pr_analytics snapshot contains total_merged
    tp_analytics_val = tp_snaps.get("pr_analytics", {}).get("value", {}) if tp_snaps.get("pr_analytics") else {}
    tp_total = tp_analytics_val.get("total_merged") if isinstance(tp_analytics_val, dict) else None

    # Lean: wip value
    lean_all = lean_snaps.get("all", {}).get("value", {}) if lean_snaps.get("all") else {}
    lean_wip = lean_all.get("wip")

    # Determine the latest calculated_at across all snapshots
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
                value=dora_all.get("deployment_frequency_per_day"),
                unit="deploys/day",
                level=dora_all.get("df_level"),
            ),
            lead_time=HomeMetricCard(
                value=dora_all.get("lead_time_for_changes_hours"),
                unit="hours",
                level=dora_all.get("lt_level"),
            ),
            change_failure_rate=HomeMetricCard(
                value=dora_all.get("change_failure_rate"),
                unit="ratio",
                level=dora_all.get("cfr_level"),
            ),
            cycle_time=HomeMetricCard(
                value=ct_p50,
                unit="hours",
            ),
            wip=HomeMetricCard(
                value=lean_wip,
                unit="items",
            ),
            throughput=HomeMetricCard(
                value=tp_total,
                unit="PRs merged",
            ),
            overall_dora_level=dora_all.get("overall_level"),
        ),
    )
