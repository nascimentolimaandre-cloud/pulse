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
            limit=1,
        )
        return snapshots[0] if snapshots else None


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

        # Fall back to the latest snapshot for this metric type
        snapshots = await repo.get_latest_snapshots(
            tenant_id=tenant_id,
            metric_type=metric_type,
            team_id=team_id,
            limit=1,
        )
        return snapshots[0] if snapshots else None


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

    snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="cycle_time",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )

    if not snapshot:
        return CycleTimeResponse(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            calculated_at=None,
            data=CycleTimeMetricsData(),
        )

    value = snapshot.value or {}

    breakdown_raw = value.get("breakdown")
    breakdown = None
    if breakdown_raw and isinstance(breakdown_raw, dict):
        breakdown = CycleTimeBreakdownData(**breakdown_raw)

    return CycleTimeResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=snapshot.calculated_at,
        data=CycleTimeMetricsData(
            breakdown=breakdown,
            trend=value.get("trend"),
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

    snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="throughput",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )

    if not snapshot:
        return ThroughputResponse(
            period=period,
            period_start=period_start,
            period_end=period_end,
            team_id=team_id,
            calculated_at=None,
            data=ThroughputMetricsData(),
        )

    value = snapshot.value or {}

    return ThroughputResponse(
        period=period,
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
        calculated_at=snapshot.calculated_at,
        data=ThroughputMetricsData(
            trend=value.get("trend"),
            pr_analytics=value.get("pr_analytics"),
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

    # Fetch all relevant snapshots in parallel-ish (sequential but reuses connection pool)
    dora_snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="dora",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )
    lean_snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="lean",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )
    cycle_time_snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="cycle_time",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )
    throughput_snapshot = await _get_snapshot_by_period(
        tenant_id=tenant_id,
        metric_type="throughput",
        metric_name="all",
        period_start=period_start,
        period_end=period_end,
        team_id=team_id,
    )

    # Build home cards from snapshot values
    dora_val = (dora_snapshot.value or {}) if dora_snapshot else {}
    lean_val = (lean_snapshot.value or {}) if lean_snapshot else {}
    ct_val = (cycle_time_snapshot.value or {}) if cycle_time_snapshot else {}
    tp_val = (throughput_snapshot.value or {}) if throughput_snapshot else {}

    # Extract cycle time P50 from breakdown
    ct_breakdown = ct_val.get("breakdown", {}) or {}
    ct_p50 = ct_breakdown.get("total_p50") if isinstance(ct_breakdown, dict) else None

    # Extract throughput: total merged from pr_analytics
    tp_analytics = tp_val.get("pr_analytics", {}) or {}
    tp_total = tp_analytics.get("total_merged") if isinstance(tp_analytics, dict) else None

    # Determine the latest calculated_at across all snapshots
    timestamps = [
        s.calculated_at
        for s in (dora_snapshot, lean_snapshot, cycle_time_snapshot, throughput_snapshot)
        if s and s.calculated_at
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
                value=dora_val.get("deployment_frequency_per_day"),
                unit="deploys/day",
                level=dora_val.get("df_level"),
            ),
            lead_time=HomeMetricCard(
                value=dora_val.get("lead_time_for_changes_hours"),
                unit="hours",
                level=dora_val.get("lt_level"),
            ),
            change_failure_rate=HomeMetricCard(
                value=dora_val.get("change_failure_rate"),
                unit="ratio",
                level=dora_val.get("cfr_level"),
            ),
            cycle_time=HomeMetricCard(
                value=ct_p50,
                unit="hours",
            ),
            wip=HomeMetricCard(
                value=lean_val.get("wip"),
                unit="items",
            ),
            throughput=HomeMetricCard(
                value=tp_total,
                unit="PRs merged",
            ),
            overall_dora_level=dora_val.get("overall_level"),
        ),
    )
