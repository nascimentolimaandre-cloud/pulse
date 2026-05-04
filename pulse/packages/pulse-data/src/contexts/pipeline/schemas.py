"""Pydantic v2 response models for Pipeline Monitor v2.

Complete replacement of v1 schemas. All models use camelCase aliases
for JSON output as required by the frontend spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


# ---------------------------------------------------------------------------
# Status literal types
# ---------------------------------------------------------------------------

StepStatus = Literal["pending", "running", "done", "error", "degraded"]
EntityStatus = Literal["idle", "healthy", "running", "backfilling", "degraded", "error"]
SourceStatus = Literal["healthy", "backfilling", "degraded", "error", "slow"]
IntegrationStatus = Literal["healthy", "backfilling", "degraded", "error", "disabled"]
HealthStatus = Literal["healthy", "degraded", "error", "backfilling", "slow"]


# ---------------------------------------------------------------------------
# Base config for camelCase output
# ---------------------------------------------------------------------------

class _CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


# ---------------------------------------------------------------------------
# Step / Entity / Source
# ---------------------------------------------------------------------------

class Step(_CamelModel):
    """A single processing step within an entity sync cycle.

    TODO: replace synthesis with real per-step instrumentation once sync
    worker emits step-level events (see docs/backlog.md).
    """

    name: Literal["fetch", "changelog", "normalize", "upsert"]
    status: StepStatus
    processed: int
    total: int
    duration_sec: float | None = None
    eta_sec: float | None = None
    throughput_per_sec: float | None = None


class Entity(_CamelModel):
    """Status of a single entity type within a source."""

    type: str  # pull_requests | reviews | commits | deployments | issues | sprints | builds
    label: str  # pt-BR display label
    status: EntityStatus
    watermark: datetime | None = None
    last_cycle_records: int | None = None
    last_cycle_duration_sec: float | None = None
    error: str | None = None
    steps: list[Step] | None = None  # Only present when status == "running"


class CatalogCounts(_CamelModel):
    """Counts per catalog status for a source."""

    active: int = 0
    discovered: int = 0
    paused: int = 0
    blocked: int = 0
    archived: int = 0


class Source(_CamelModel):
    """A configured data source with its entities."""

    id: str  # github | jira | jenkins
    name: str
    status: SourceStatus
    connections: int
    rate_limit_pct: float  # 0..1 — PLACEHOLDER until real tracking
    watermark: datetime | None = None
    catalog: CatalogCounts
    entities: list[Entity]


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class Integration(_CamelModel):
    """Status of an integration connector (configured or not)."""

    id: str  # github | jira | jenkins | gitlab | azure | bitbucket
    name: str
    connected: bool
    status: IntegrationStatus
    detail: str  # pt-BR description


# ---------------------------------------------------------------------------
# TeamHealth
# ---------------------------------------------------------------------------

class TeamHealth(_CamelModel):
    """Health status for a squad/team derived from Jira project activity.

    FDD-PIPE-001: only QUALIFIED squads are returned by `/pipeline/teams`.
    The `tier` field tells the UI how to weight the squad in displays
    (active/marginal/dormant) — never used to hide rows here, only to
    style/sort them in the combobox / lists.
    """

    id: str  # project_key lowercased
    name: str
    tribe: str | None = None
    squad_key: str  # ENO, FID, etc
    health: str
    repos: int
    jira_projects: list[str]
    jenkins_jobs: int
    pr_count: int
    issue_count: int
    deploy_count: int
    link_rate: float  # 0..1
    last_sync: datetime | None = None
    lag_sec: int
    # FDD-PIPE-001 — Activity tier (orthogonal to qualification)
    tier: Literal["active", "marginal", "dormant"] = "active"
    # FDD-PIPE-001 — How this squad qualified ('auto' = heuristic; 'override' = forced by operator)
    qualification_source: Literal["auto", "override"] = "auto"


# ---------------------------------------------------------------------------
# TimelineEvent
# ---------------------------------------------------------------------------

class TimelineEvent(_CamelModel):
    """A pipeline activity event for the timeline feed."""

    ts: datetime
    severity: Literal["success", "info", "warning", "error"]
    stage: str  # github | jira | jenkins | system | metrics_worker
    message: str  # pt-BR


# ---------------------------------------------------------------------------
# KPIs / Health
# ---------------------------------------------------------------------------

class ReposWithDeploy(_CamelModel):
    """Deploy coverage counts."""

    covered: int
    total: int


class KPIs(_CamelModel):
    """Pipeline health KPIs."""

    records_today: int
    records_trend_pct: float
    pr_issue_link_rate: float  # 0..1
    pr_issue_link_trend_pp: float
    repos_with_deploy_30d: ReposWithDeploy = Field(..., alias="reposWithDeploy30d")
    avg_sync_lag_sec: int
    p95_sync_lag_sec: int


class PipelineHealthResponse(_CamelModel):
    """Top-level pipeline health response for GET /health."""

    health: HealthStatus
    last_updated_at: datetime
    kpis: KPIs


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

class OrphanPrefix(_CamelModel):
    """A project key prefix found in PR titles but missing from the catalog."""

    prefix: str
    pr_mentions: int


class ActiveProjectWithoutIssues(_CamelModel):
    """A catalog entry marked active but with zero issues."""

    key: str
    name: str


class CoverageResponse(_CamelModel):
    """Pipeline coverage analysis response."""

    repos_with_deploy: ReposWithDeploy
    pr_issue_link_rate: float  # 0..1
    orphan_prefixes: list[OrphanPrefix]
    active_projects_without_issues: list[ActiveProjectWithoutIssues]


# ---------------------------------------------------------------------------
# FDD-OPS-015 — Per-scope progress (Pipeline Jobs endpoint)
# ---------------------------------------------------------------------------

ProgressJobStatus = Literal["running", "done", "failed", "paused", "cancelled"]
ProgressJobPhase = Literal[
    "pre_flight", "fetching", "normalizing", "persisting", "done", "failed",
]


class ProgressJob(_CamelModel):
    """One row in `GET /data/v1/pipeline/jobs` — one ingestion scope's progress.

    Mirrors `pipeline_progress` table with a few computed fields:
      - `progress_pct`: 0-100 when estimate is available, else None
      - `is_stalled`: True when status='running' AND last_progress_at > 60s ago
    """

    scope_key: str
    entity_type: str
    phase: ProgressJobPhase
    status: ProgressJobStatus
    items_done: int
    items_estimate: int | None  # None = pre-flight count failed/skipped
    progress_pct: float | None  # computed — None when no estimate
    items_per_second: float
    eta_seconds: int | None  # None = unknown
    started_at: datetime
    last_progress_at: datetime
    finished_at: datetime | None
    is_stalled: bool  # computed — running + no progress for >60s
    last_error: str | None
