"""SQLAlchemy models for BC5 — Pipeline Monitor.

Tables: pipeline_watermarks, pipeline_sync_log, pipeline_events,
        pipeline_ingestion_progress.
All tables enforce tenant_id (NOT NULL) for RLS.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import TenantModel


class PipelineWatermark(TenantModel):
    """Stores sync watermarks per (tenant, entity, scope) for incremental sync.

    Replaces the in-memory _WATERMARKS dict with persistent DB storage,
    so watermarks survive worker restarts and scale across replicas.

    FDD-OPS-014 (migration 010): added `scope_key` so a single entity_type
    can have multiple scopes. E.g.:
        scope_key='*'                   → legacy global (one row, all sources)
        scope_key='jira:project:BG'     → Jira project BG
        scope_key='github:repo:foo/bar' → specific GitHub repo
        scope_key='jenkins:job:deploy-X'→ specific Jenkins job

    The legacy `uq_watermark_entity` constraint coexists with the new
    `uq_watermark_entity_scope` UNIQUE — to be dropped in migration 011
    after all worker code is writing per-scope.
    """

    __tablename__ = "pipeline_watermarks"
    __table_args__ = (
        # Per-scope constraint (active from migration 010 onward).
        # Legacy uq_watermark_entity (without scope_key) was dropped in
        # migration 011 — Postgres enforces all UniqueConstraints on every
        # INSERT, so "harmless coexistence" was impossible: legacy blocked
        # any per-scope insert because the (tenant, entity) tuple already
        # existed via the '*' row. Discovered immediately after Phase 2-A
        # deployment.
        UniqueConstraint(
            "tenant_id", "entity_type", "scope_key",
            name="uq_watermark_entity_scope",
        ),
    )

    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )  # pull_requests | issues | deployments | sprints
    scope_key: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="*",
    )  # see class docstring for format
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    records_synced: Mapped[int] = mapped_column(Integer, default=0)


class PipelineSyncLog(TenantModel):
    """Records each sync cycle for observability and debugging.

    Tracks start/end times, status, record counts per entity,
    and any errors encountered during the sync cycle.
    """

    __tablename__ = "pipeline_sync_log"

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )  # running | completed | failed | partial
    trigger: Mapped[str] = mapped_column(
        String(32), nullable=False, default="scheduled",
    )  # scheduled | manual | bootstrap
    duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    records_processed: Mapped[dict | None] = mapped_column(
        JSONB, nullable=False, default=dict,
    )  # {"pull_requests": 42, "issues": 10, ...}
    errors: Mapped[list | None] = mapped_column(
        JSONB, nullable=False, default=list,
    )  # [{"stage": "issues", "message": "...", "timestamp": "..."}]
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class PipelineEvent(TenantModel):
    """Feed of pipeline activity events (MVP-1.7.10)."""

    __tablename__ = "pipeline_events"

    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )  # sync_completed | error | config_change | webhook
    source: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )  # github | jira | jenkins | system | metrics_worker
    title: Mapped[str] = mapped_column(
        String(256), nullable=False,
    )
    detail: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    severity: Mapped[str] = mapped_column(
        String(16), server_default="info",
    )  # info | warning | error | success
    event_meta: Mapped[dict] = mapped_column(
        "event_meta", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )


class PipelineIngestionProgress(TenantModel):
    """Tracks real-time progress of data ingestion per entity type.

    Updated by the sync worker after each batch (e.g., each repo's PRs).
    Queried by the Pipeline Monitor API to show ingestion progress to users.
    """

    __tablename__ = "pipeline_ingestion_progress"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", name="uq_ingestion_progress_entity"),
    )

    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )  # pull_requests | issues | deployments | sprints
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="idle",
    )  # idle | running | completed | failed
    total_sources: Mapped[int] = mapped_column(Integer, default=0)
    sources_done: Mapped[int] = mapped_column(Integer, default=0)
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    current_source: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_batch_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_details: Mapped[dict] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False,
    )


class PipelineProgress(TenantModel):
    """FDD-OPS-015 — per-scope ingestion progress tracking.

    Distinct from `PipelineIngestionProgress` (per-`entity_type` aggregate,
    4 rows total). This table holds one row per active SCOPE during a sync
    cycle: per Jira project, per GitHub repo, per Jenkins job. During a
    Webmotors backfill that is ~32+ rows in flight.

    Workers upsert by (tenant, entity_type, scope_key) on every batch tick:
    update items_done, items_per_second, eta_seconds, last_progress_at.
    On done/failed, set status + finished_at.

    Operators query via `GET /data/v1/pipeline/jobs` to see per-scope
    progress, rate, ETA, and detect stalls (last_progress_at > 60s ago
    while status='running').

    Retention: live + historical. External cron should
    `DELETE WHERE status IN ('done','failed') AND last_progress_at <
    now() - interval '7 days'` to bound table size.
    """

    __tablename__ = "pipeline_progress"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "entity_type", "scope_key",
            name="uq_pipeline_progress_scope",
        ),
    )

    # FDD-OPS-014 scope_key convention: '<source>:<dimension>:<value>'
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )  # pull_requests | issues | deployments | sprints
    # Phase: pre_flight | fetching | normalizing | persisting | done | failed
    phase: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pre_flight",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="running",
    )  # running | done | failed | paused | cancelled
    items_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    # NULLABLE — estimate may not be available (count call too expensive
    # or unsupported). Worker falls back to heuristic when None.
    items_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_per_second: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.0",
    )
    # ETA in seconds remaining. None = unknown (no estimate or rate yet).
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    last_progress_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
