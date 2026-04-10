"""Pydantic v2 response models for BC5 — Pipeline Monitor API.

Typed responses for the pipeline status endpoint. Models represent
the pipeline stages, KPIs, record counts, sync logs, and errors
that make up the consolidated pipeline health view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Pipeline stage status
# ---------------------------------------------------------------------------


class PipelineStageStatus(BaseModel):
    """Status of a single pipeline stage."""

    name: str  # "sources" | "sync_worker" | "pulse_db" | "metrics_worker"
    status: str  # "healthy" | "syncing" | "idle" | "error" | "standby"
    label: str  # Human-readable label
    detail: str | None = None  # e.g. "12 active" or "1.4 GB/s"
    last_activity: datetime | None = None


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------


class PipelineKPIs(BaseModel):
    """Key performance indicators for the pipeline."""

    total_records: int = 0
    synced_today: int = 0
    pending_sync: int = 0
    errors_24h: int = 0
    total_records_trend: float | None = None  # % change vs last period


# ---------------------------------------------------------------------------
# Record counts
# ---------------------------------------------------------------------------


class RecordCount(BaseModel):
    """Record count for a single entity type."""

    entity: str  # "pull_requests" | "issues" | "deployments" | "sprints"
    devlake_count: int = 0  # Legacy field name; now mirrors pulse_count (no intermediate DB)
    pulse_count: int = 0
    difference: int = 0
    is_synced: bool = True


# ---------------------------------------------------------------------------
# Sync logs
# ---------------------------------------------------------------------------


class SyncLogEntry(BaseModel):
    """A single sync cycle log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    trigger: str = "scheduled"
    duration_seconds: float | None = None
    records_processed: dict[str, Any] = Field(default_factory=dict)
    error_count: int = 0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PipelineError(BaseModel):
    """A recent pipeline error."""

    stage: str
    message: str
    timestamp: datetime
    error_code: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Legacy pipeline info (kept for API backward compatibility)
# ---------------------------------------------------------------------------


class DevLakePipelineInfo(BaseModel):
    """Legacy pipeline info stub. Always returns defaults since DevLake was removed (ADR-005)."""

    is_running: bool = False
    last_status: str | None = None
    last_finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# Pipeline events
# ---------------------------------------------------------------------------


class PipelineEventEntry(BaseModel):
    """A pipeline activity event."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    source: str
    title: str
    detail: str | None = None
    severity: str = "info"
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


# ---------------------------------------------------------------------------
# Source-filtered status (Tela 2)
# ---------------------------------------------------------------------------


class SourceFilteredStatus(BaseModel):
    """Pipeline status filtered by source type (Tela 2)."""

    source: str
    kpis: dict[str, Any]  # Dynamic KPIs per source
    stages: list[PipelineStageStatus]
    active_syncs: list[dict[str, Any]]  # Board/repo sync details
    recent_logs: list[PipelineEventEntry]
    health_pct: float = 100.0
    sync_mode: str = "delta"


# ---------------------------------------------------------------------------
# Metrics worker (Tela 3)
# ---------------------------------------------------------------------------


class MetricsWorkerSnapshot(BaseModel):
    """Metrics worker snapshot entry (Tela 3)."""

    snapshot_id: str
    metric_type: str  # "DORA" | "Lean & Flow" | "Cycle Time" | "Throughput"
    timestamp: datetime | None = None
    duration_seconds: float | None = None
    records_processed: int = 0
    status: str = "idle"  # "success" | "calculating" | "idle" | "error"


class MetricsWorkerStatus(BaseModel):
    """Metrics Worker drill-down view (Tela 3)."""

    kpis: dict[str, Any]
    stages: list[dict[str, Any]]
    snapshots: list[MetricsWorkerSnapshot]
    cluster_logs: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Consolidated response
# ---------------------------------------------------------------------------


class PipelineStatusResponse(BaseModel):
    """Full pipeline status response — consolidates all pipeline health data.

    GET /data/v1/pipeline/status response.
    """

    overall_status: str  # "healthy" | "syncing" | "degraded" | "error"
    stages: list[PipelineStageStatus]
    kpis: PipelineKPIs
    record_counts: list[RecordCount]
    recent_syncs: list[SyncLogEntry]
    recent_errors: list[PipelineError]
    recent_events: list[PipelineEventEntry] = []
    source_connections: list[dict[str, Any]] = []
    devlake: DevLakePipelineInfo
    last_updated: datetime
