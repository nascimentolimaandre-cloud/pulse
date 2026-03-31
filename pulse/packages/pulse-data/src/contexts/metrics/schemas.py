"""Pydantic v2 response models for BC4 — Metrics API.

Typed responses for all metrics endpoints. Each model corresponds to the
JSONB shape stored in metrics_snapshots.value, with an outer envelope
that includes metadata (period, calculated_at, team_id).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared envelope
# ---------------------------------------------------------------------------


class MetricsEnvelope(BaseModel):
    """Common response wrapper for all metrics endpoints."""

    period: str = Field(description="Requested period (e.g. 7d, 14d, 30d, 90d)")
    period_start: datetime | None = Field(None, description="Period start datetime")
    period_end: datetime | None = Field(None, description="Period end datetime")
    team_id: UUID | None = Field(None, description="Team filter applied (null = org-wide)")
    calculated_at: datetime | None = Field(None, description="When the snapshot was calculated")


# ---------------------------------------------------------------------------
# DORA
# ---------------------------------------------------------------------------


class DoraClassifications(BaseModel):
    """Per-metric DORA performance levels."""

    deployment_frequency: str | None = None
    lead_time: str | None = None
    change_failure_rate: str | None = None
    mttr: str | None = None


class DoraMetricsData(BaseModel):
    """DORA metric values."""

    deployment_frequency_per_day: float | None = None
    deployment_frequency_per_week: float | None = None
    lead_time_for_changes_hours: float | None = None
    change_failure_rate: float | None = None
    mean_time_to_recovery_hours: float | None = None
    overall_level: str | None = None
    classifications: DoraClassifications | None = None


class DoraResponse(MetricsEnvelope):
    """GET /data/v1/metrics/dora response."""

    data: DoraMetricsData = Field(default_factory=DoraMetricsData)


# ---------------------------------------------------------------------------
# Lean
# ---------------------------------------------------------------------------


class LeanMetricsData(BaseModel):
    """Lean metric values (CFD, WIP, lead time distribution, throughput)."""

    cfd: list[dict[str, Any]] | None = None
    wip: int | None = None
    lead_time_distribution: dict[str, Any] | None = None
    throughput: list[dict[str, Any]] | None = None
    scatterplot: dict[str, Any] | None = None


class LeanResponse(MetricsEnvelope):
    """GET /data/v1/metrics/lean response."""

    data: LeanMetricsData = Field(default_factory=LeanMetricsData)


# ---------------------------------------------------------------------------
# Cycle Time
# ---------------------------------------------------------------------------


class CycleTimeBreakdownData(BaseModel):
    """Cycle time phase breakdown with percentiles."""

    coding_p50: float | None = None
    coding_p85: float | None = None
    coding_p95: float | None = None
    pickup_p50: float | None = None
    pickup_p85: float | None = None
    pickup_p95: float | None = None
    review_p50: float | None = None
    review_p85: float | None = None
    review_p95: float | None = None
    deploy_p50: float | None = None
    deploy_p85: float | None = None
    deploy_p95: float | None = None
    total_p50: float | None = None
    total_p85: float | None = None
    total_p95: float | None = None
    bottleneck_phase: str | None = None
    pr_count: int = 0


class CycleTimeMetricsData(BaseModel):
    """Cycle time metrics payload."""

    breakdown: CycleTimeBreakdownData | None = None
    trend: list[dict[str, Any]] | None = None


class CycleTimeResponse(MetricsEnvelope):
    """GET /data/v1/metrics/cycle-time response."""

    data: CycleTimeMetricsData = Field(default_factory=CycleTimeMetricsData)


# ---------------------------------------------------------------------------
# Throughput
# ---------------------------------------------------------------------------


class ThroughputMetricsData(BaseModel):
    """Throughput metrics payload."""

    trend: list[dict[str, Any]] | None = None
    pr_analytics: dict[str, Any] | None = None


class ThroughputResponse(MetricsEnvelope):
    """GET /data/v1/metrics/throughput response."""

    data: ThroughputMetricsData = Field(default_factory=ThroughputMetricsData)


# ---------------------------------------------------------------------------
# Sprint
# ---------------------------------------------------------------------------


class SprintOverviewData(BaseModel):
    """Sprint overview metrics for the latest sprint."""

    committed_items: int = 0
    added_items: int = 0
    removed_items: int = 0
    completed_items: int = 0
    carried_over_items: int = 0
    final_scope_items: int = 0
    completion_rate: float | None = None
    scope_creep_pct: float | None = None
    carryover_rate: float | None = None
    committed_points: float = 0.0
    completed_points: float = 0.0
    completion_rate_points: float | None = None


class SprintComparisonData(BaseModel):
    """Sprint comparison across multiple sprints."""

    sprints: list[dict[str, Any]] = Field(default_factory=list)
    avg_velocity: float | None = None
    velocity_trend: str = "insufficient_data"


class SprintMetricsData(BaseModel):
    """Sprint metrics payload."""

    overview: SprintOverviewData | None = None
    comparison: SprintComparisonData | None = None


class SprintResponse(BaseModel):
    """GET /data/v1/metrics/sprints response."""

    team_id: UUID | None = None
    calculated_at: datetime | None = None
    data: SprintMetricsData = Field(default_factory=SprintMetricsData)


# ---------------------------------------------------------------------------
# Home dashboard summary
# ---------------------------------------------------------------------------


class HomeMetricCard(BaseModel):
    """A single metric card for the home dashboard."""

    value: float | None = None
    unit: str | None = None
    level: str | None = None
    trend_direction: str | None = None  # "up" | "down" | "flat" | None
    trend_percentage: float | None = None  # % change vs previous period (null = no data)
    previous_value: float | None = None  # value from previous equivalent period


class HomeMetricsData(BaseModel):
    """Summary metrics for the home dashboard."""

    deployment_frequency: HomeMetricCard = Field(default_factory=HomeMetricCard)
    lead_time: HomeMetricCard = Field(default_factory=HomeMetricCard)
    change_failure_rate: HomeMetricCard = Field(default_factory=HomeMetricCard)
    cycle_time: HomeMetricCard = Field(default_factory=HomeMetricCard)
    wip: HomeMetricCard = Field(default_factory=HomeMetricCard)
    throughput: HomeMetricCard = Field(default_factory=HomeMetricCard)
    overall_dora_level: str | None = None


class HomeMetricsResponse(MetricsEnvelope):
    """GET /data/v1/metrics/home response."""

    data: HomeMetricsData = Field(default_factory=HomeMetricsData)


# ---------------------------------------------------------------------------
# Engineering data: Pull Request list
# ---------------------------------------------------------------------------


class PullRequestItem(BaseModel):
    """A single pull request in the paginated list."""

    id: UUID
    external_id: str
    source: str
    repo: str
    title: str
    author: str
    state: str
    additions: int = 0
    deletions: int = 0
    files_changed: int = 0
    created_at: datetime
    merged_at: datetime | None = None
    lead_time_hours: float | None = None
    cycle_time_hours: float | None = None


class PullRequestListResponse(BaseModel):
    """GET /data/v1/engineering/pull-requests response."""

    data: list[PullRequestItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


# ---------------------------------------------------------------------------
# Engineering data: Issues list
# ---------------------------------------------------------------------------


class IssueItem(BaseModel):
    """A single issue in the paginated list."""

    id: UUID
    external_id: str
    source: str
    project_key: str
    title: str
    type: str
    status: str
    normalized_status: str
    assignee: str | None = None
    story_points: float | None = None
    sprint_id: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lead_time_hours: float | None = None
    cycle_time_hours: float | None = None


class IssueListResponse(BaseModel):
    """GET /data/v1/engineering/issues response."""

    data: list[IssueItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


# ---------------------------------------------------------------------------
# Engineering data: Integrations
# ---------------------------------------------------------------------------


class IntegrationStatus(BaseModel):
    """Status of a configured data connection."""

    name: str
    source: str  # github | gitlab | jira | azure
    status: str  # connected | syncing | error | disconnected
    last_sync_at: datetime | None = None
    record_count: int = 0


class IntegrationListResponse(BaseModel):
    """GET /data/v1/engineering/integrations response."""

    data: list[IntegrationStatus] = Field(default_factory=list)
    total: int = 0
