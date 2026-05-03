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
    sprint_name: str | None = Field(None, description="Sprint name from metadata")
    started_at: str | None = Field(None, description="Sprint start date (ISO)")
    completed_at: str | None = Field(None, description="Sprint end date (ISO)")


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


class LeadTimeCoverage(BaseModel):
    """Coverage info for the strict Lead Time card.

    Surfaces how many PRs in the period have a deploy timestamp linked
    versus the total. Frontend uses this to render a 'X / Y PRs' subtitle
    so users can judge representativeness of the strict P50.
    """

    covered: int = 0
    total: int = 0
    pct: float = 0.0


class HomeMetricCard(BaseModel):
    """A single metric card for the home dashboard."""

    value: float | None = None
    unit: str | None = None
    level: str | None = None
    trend_direction: str | None = None  # "up" | "down" | "flat" | None
    trend_percentage: float | None = None  # % change vs previous period (null = no data)
    previous_value: float | None = None  # value from previous equivalent period
    # Optional — populated only on lead_time_strict for the home dashboard.
    coverage: LeadTimeCoverage | None = None
    # Optional — populated only on `time_to_restore` (FDD-DSH-050). Number of
    # resolved incidents that contributed to the median (post flaky-filter)
    # and number of failures still "open" (no recovery in window). Frontend
    # renders these as a sub-line under the value: "n=73 resolved · 3 open".
    incident_count: int | None = None
    open_incident_count: int | None = None


class HomeMetricsData(BaseModel):
    """Summary metrics for the home dashboard."""

    deployment_frequency: HomeMetricCard = Field(default_factory=HomeMetricCard)
    # `lead_time` is the LEGACY inclusive variant (uses merged_at fallback) —
    # kept for backward compat with consumers that haven't migrated yet.
    lead_time: HomeMetricCard = Field(default_factory=HomeMetricCard)
    # `lead_time_strict` is the canonical DORA variant (deployed_at only).
    # Frontend should prefer this card. See FDD-DSH-082.
    lead_time_strict: HomeMetricCard = Field(default_factory=HomeMetricCard)
    change_failure_rate: HomeMetricCard = Field(default_factory=HomeMetricCard)
    cycle_time: HomeMetricCard = Field(default_factory=HomeMetricCard)
    cycle_time_p85: HomeMetricCard = Field(default_factory=HomeMetricCard)
    wip: HomeMetricCard = Field(default_factory=HomeMetricCard)
    throughput: HomeMetricCard = Field(default_factory=HomeMetricCard)
    # MTTR/Time to Restore is roadmap R1 — requires incident ingestion pipeline.
    # Card renders "—" with tooltip until backend calculates it (see backlog FDD-DSH-041).
    time_to_restore: HomeMetricCard = Field(default_factory=HomeMetricCard)
    overall_dora_level: str | None = None


class HomeMetricsResponse(MetricsEnvelope):
    """GET /data/v1/metrics/home response."""

    data: HomeMetricsData = Field(default_factory=HomeMetricsData)


# ---------------------------------------------------------------------------
# Kanban Flow Health (Aging WIP + Flow Efficiency) — FDD-KB-003 / FDD-KB-004
# ---------------------------------------------------------------------------


class AgingWipItem(BaseModel):
    """A single open work item with its current age.

    ANTI-SURVEILLANCE CONTRACT: this model deliberately omits `assignee`,
    `author`, `reporter`, `creator`, and any individual-level identifier.
    `issue_key` is a public artifact (appears in commit messages, PR
    titles, etc.) and carries no PII on its own. `title`/`description`
    are issue-level fields — they CAN contain PII typed by humans in the
    ticket body, so the API always truncates `description` before
    returning it and the frontend treats both as display-only. If you
    ever need to add a NEW PII-adjacent field, it MUST go through CISO
    review.
    """

    issue_key: str = Field(description="Public issue key (e.g. 'OKM-4312').")
    # FDD-KB-014 — title + issue_type + description surfaced in the squad
    # drawer. `title` and `issue_type` are cheap (already in eng_issues);
    # `description` is truncated to ~300 chars before being returned.
    title: str | None = Field(
        None, description="Issue summary from Jira (ticket title)."
    )
    description: str | None = Field(
        None,
        description=(
            "Plain-text description, truncated to ~300 chars at the API "
            "boundary (storage cap = 4000). Null when Jira has no body or "
            "the backfill has not yet run for this tenant."
        ),
    )
    issue_type: str | None = Field(
        None,
        description="Normalized type: 'epic' | 'story' | 'task' | 'bug' | 'subtask'.",
    )
    age_days: float = Field(
        description="Days since the item last entered an active status."
    )
    status: str = Field(description="Raw Jira status (e.g. 'Em Desenvolvimento').")
    status_category: str = Field(
        description="Normalized category: 'in_progress' | 'in_review'."
    )
    squad_key: str | None = Field(
        None, description="Jira project key; null only when source lacks it."
    )
    squad_name: str | None = Field(
        None,
        description=(
            "Human-readable squad name from jira_project_catalog.name "
            "(e.g. 'PF - OEM Integração'). Falls back to squad_key when "
            "the project isn't in the catalog."
        ),
    )
    is_at_risk: bool = Field(
        description="True when age_days > at_risk_threshold_days."
    )


class SquadFlowSummary(BaseModel):
    """Per-squad aggregate for the Flow Health default 'squad view' (FDD-KB-014).

    The Flow Health dashboard opens with the squad list expanded by
    default; clicking a row opens a drawer with the items underneath.
    This summary is what renders each row and powers the drawer header.

    Sorted by `at_risk_count DESC, risk_pct DESC` in the response so the
    most pressured squads appear first.
    """

    squad_key: str = Field(description="Jira project key (e.g. 'OKM').")
    squad_name: str = Field(
        description="Real squad name from jira_project_catalog; falls back to key."
    )
    wip_count: int = Field(
        description="Items currently in_progress or in_review for the squad."
    )
    at_risk_count: int = Field(
        description="Subset of wip_count whose age exceeds at_risk_threshold_days."
    )
    risk_pct: float = Field(
        ge=0.0, le=1.0,
        description="at_risk_count / wip_count (0 when wip_count=0).",
    )
    p50_age_days: float | None = Field(
        None, description="Median age of active items in this squad."
    )
    p85_age_days: float | None = Field(
        None, description="85th-percentile age — upper tail of aging items."
    )
    flow_efficiency: float | None = Field(
        None,
        ge=0.0, le=1.0,
        description=(
            "v1 simplified Flow Efficiency for this squad's completed work "
            "in the period window. Null when insufficient_data "
            "(sample < 5) or cycle_sum = 0."
        ),
    )
    fe_sample_size: int = Field(
        0,
        description="Number of completed issues contributing to flow_efficiency.",
    )
    intensity_throughput_30d: int = Field(
        0,
        description=(
            "'Intensidade' = items completed in the last 30 days. "
            "Proxy for how active the squad is right now — not a DORA "
            "metric. Refinement tracked in R1 if product wants a better "
            "signal."
        ),
    )


class AgingWipSummary(BaseModel):
    """Aggregate stats for a squad's (or tenant's) in-flight WIP."""

    count: int = Field(description="Total items currently in_progress or in_review.")
    p50_days: float | None = None
    p85_days: float | None = None
    at_risk_count: int = 0
    at_risk_threshold_days: float | None = Field(
        None,
        description="2 × baseline P85 cycle time. Used to flag aging outliers.",
    )
    baseline_source: str = Field(
        description=(
            "Which baseline was used: 'squad_p85_90d' (squad has ≥10 "
            "completed issues in 90d), 'tenant_p85_90d' (tenant-wide "
            "request — tenant baseline is the correct scope), "
            "'tenant_p85_90d_fallback' (squad-scoped request but squad "
            "lacked history — fell back to tenant-wide), or "
            "'absolute_fallback' (tenant also lacked history, defaulted "
            "to 14d)."
        )
    )


class FlowEfficiencyData(BaseModel):
    """Flow Efficiency — v1 simplified (touch time / cycle time)."""

    value: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Ratio 0..1. Null when insufficient_data or cycle_sum=0.",
    )
    sample_size: int = Field(
        description="Issues resolved in-window with cycle_time ≥ 1h."
    )
    formula_version: str = Field(
        default="v1_simplified",
        description="Version tag; frontend keys the disclaimer off of this.",
    )
    formula_disclaimer: str = Field(
        description="PT-BR text shown beside the metric in the UI."
    )
    insufficient_data: bool = Field(
        description="True when sample_size < 5 or no valid cycle time."
    )


class FlowHealthResponse(MetricsEnvelope):
    """GET /data/v1/metrics/flow-health response.

    Combines Aging WIP (current snapshot of in-flight items) and Flow
    Efficiency (retrospective metric over `period_days`). Each metric
    renders independently on the frontend so either may be in a
    degraded/insufficient state without blocking the other.
    """

    squad_key: str | None = None
    period_days: int = 60
    aging_wip: AgingWipSummary = Field(default_factory=lambda: AgingWipSummary(
        count=0, at_risk_count=0, baseline_source="absolute_fallback",
    ))
    aging_wip_items: list[AgingWipItem] = Field(default_factory=list)
    flow_efficiency: FlowEfficiencyData = Field(
        default_factory=lambda: FlowEfficiencyData(
            value=None,
            sample_size=0,
            formula_version="v1_simplified",
            formula_disclaimer="",
            insufficient_data=True,
        )
    )
    # FDD-KB-014 — always present. When `squad_key` is passed, the list
    # contains exactly one entry for context consistency. When absent,
    # all squads with WIP > 0 are returned (no server-side limit — ~27
    # squads at Webmotors — frontend paginates).
    squads: list[SquadFlowSummary] = Field(default_factory=list)


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
    issue_type: str
    status: str
    normalized_status: str
    assignee: str | None = None
    story_points: float | None = None
    sprint_id: str | None = None
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
