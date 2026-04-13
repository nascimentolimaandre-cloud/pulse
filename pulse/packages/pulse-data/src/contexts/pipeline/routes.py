"""Pipeline Monitor API routes.

Provides a consolidated view of the data pipeline health: stage
statuses, PULSE DB record counts, connector health, sync logs, and errors.

v2: Uses direct source connectors instead of DevLake (ADR-005).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from src.config import settings
from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
    EngSprint,
)
from src.contexts.metrics.infrastructure.models import MetricsSnapshot
from src.contexts.pipeline.models import (
    PipelineEvent,
    PipelineIngestionProgress,
    PipelineSyncLog,
    PipelineWatermark,
)
from src.contexts.pipeline.schemas import (
    DevLakePipelineInfo,
    IngestionEntityProgress,
    IngestionProgressResponse,
    MetricsWorkerSnapshot,
    MetricsWorkerStatus,
    PipelineError,
    PipelineEventEntry,
    PipelineKPIs,
    PipelineStageStatus,
    PipelineStatusResponse,
    RecordCount,
    SourceFilteredStatus,
    SyncLogEntry,
)
from src.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/v1/pipeline", tags=["Pipeline Monitor"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_connector_health() -> dict[str, dict]:
    """Check health of configured source connectors.

    Returns a dict like {"github": {"status": "healthy", ...}, ...}.
    """
    health: dict[str, dict] = {}
    configured_sources = []

    if settings.github_token:
        configured_sources.append(("github", "GitHub"))
    if settings.jira_api_token:
        configured_sources.append(("jira", "Jira Cloud"))
    if settings.jenkins_api_token:
        configured_sources.append(("jenkins", "Jenkins"))

    for source_type, label in configured_sources:
        health[source_type] = {
            "status": "configured",
            "label": label,
        }

    return health


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status() -> PipelineStatusResponse:
    """Get consolidated pipeline health status.

    Aggregates data from: PULSE DB tables, connector counts,
    sync logs, and watermarks.
    """
    tenant_id = uuid.UUID(settings.default_tenant_id)
    now = datetime.now(timezone.utc)

    # --- 1. Record counts (PULSE DB) ---
    async with get_session(tenant_id) as session:
        pr_count = (await session.execute(select(func.count(EngPullRequest.id)))).scalar() or 0
        issue_count = (await session.execute(select(func.count(EngIssue.id)))).scalar() or 0
        deploy_count = (await session.execute(select(func.count(EngDeployment.id)))).scalar() or 0
        sprint_count = (await session.execute(select(func.count(EngSprint.id)))).scalar() or 0

    pulse_counts = {
        "pull_requests": pr_count,
        "issues": issue_count,
        "deployments": deploy_count,
        "sprints": sprint_count,
    }

    # --- 2. Record counts (direct connectors — no intermediate DB) ---
    record_counts = []
    for entity in ["pull_requests", "issues", "deployments", "sprints"]:
        pl = pulse_counts.get(entity, 0)
        record_counts.append(RecordCount(
            entity=entity,
            devlake_count=pl,  # No separate source DB; use PULSE count
            pulse_count=pl,
            difference=0,
            is_synced=True,
        ))

    # --- 3. Recent sync logs ---
    sync_logs: list[PipelineSyncLog] = []
    try:
        async with get_session(tenant_id) as session:
            sync_logs_result = await session.execute(
                select(PipelineSyncLog)
                .order_by(PipelineSyncLog.started_at.desc())
                .limit(10)
            )
            sync_logs = list(sync_logs_result.scalars().all())
    except Exception:
        logger.warning("Could not fetch sync logs (table may not exist yet)")

    recent_syncs = [
        SyncLogEntry(
            id=str(s.id),
            started_at=s.started_at,
            finished_at=s.finished_at,
            status=s.status,
            trigger=s.trigger,
            duration_seconds=s.duration_seconds,
            records_processed=s.records_processed or {},
            error_count=s.error_count,
        )
        for s in sync_logs
    ]

    # --- 4. Recent errors (from sync logs) ---
    recent_errors: list[PipelineError] = []
    for s in sync_logs:
        if s.errors:
            for err in s.errors[:5]:
                recent_errors.append(PipelineError(
                    stage=err.get("stage", "unknown"),
                    message=err.get("message", "Unknown error"),
                    timestamp=(
                        datetime.fromisoformat(err["timestamp"])
                        if "timestamp" in err
                        else s.started_at
                    ),
                    error_code=err.get("error_code"),
                    context=err.get("context", {}),
                ))
    recent_errors = recent_errors[:10]  # max 10

    # --- 5. Errors in last 24h ---
    errors_24h = sum(
        s.error_count
        for s in sync_logs
        if s.started_at and s.started_at >= now - timedelta(hours=24)
    )

    # --- 6. Synced today count ---
    synced_today = sum(
        sum((s.records_processed or {}).values())
        for s in sync_logs
        if s.started_at
        and s.started_at.date() == now.date()
        and s.status in ("completed", "partial")
    )

    # --- 7. Pending sync ---
    pending = 0  # No intermediate DB; pending is tracked via watermarks

    # --- 8. Connector health ---
    connector_health = await _get_connector_health()
    devlake_info = DevLakePipelineInfo()  # Deprecated: kept for frontend schema compat

    # --- 9. Build stage statuses ---
    total_records = sum(pulse_counts.values())

    # Determine overall status
    latest_sync = sync_logs[0] if sync_logs else None
    if errors_24h > 5:
        overall = "error"
    elif errors_24h > 0:
        overall = "degraded"
    elif latest_sync and latest_sync.status == "running":
        overall = "syncing"
    else:
        overall = "healthy"

    # Determine per-stage status
    num_connectors = len(connector_health)
    source_status = "healthy" if num_connectors > 0 and total_records > 0 else "idle"
    sync_status = (
        "syncing"
        if (latest_sync and latest_sync.status == "running")
        else "healthy"
    )
    db_status = "healthy" if total_records > 0 else "standby"
    metrics_status = "healthy"  # Metrics worker is always-on Kafka consumer

    stages = [
        PipelineStageStatus(
            name="sources",
            status=source_status,
            label="Connectors",
            detail=f"{num_connectors} configured",
        ),
        PipelineStageStatus(
            name="sync_worker",
            status=sync_status,
            label="Sync Worker",
            detail="Kafka Cluster",
        ),
        PipelineStageStatus(
            name="pulse_db",
            status=db_status,
            label="PULSE DB",
            detail=f"{total_records:,} Rec",
        ),
        PipelineStageStatus(
            name="metrics_worker",
            status=metrics_status,
            label="Metrics",
            detail="Calculations",
        ),
    ]

    # --- 10. Recent pipeline events ---
    recent_events: list[PipelineEventEntry] = []
    try:
        async with get_session(tenant_id) as session:
            events_result = await session.execute(
                select(PipelineEvent)
                .order_by(PipelineEvent.occurred_at.desc())
                .limit(10)
            )
            recent_events = [
                PipelineEventEntry(
                    id=str(e.id),
                    event_type=e.event_type,
                    source=e.source,
                    title=e.title,
                    detail=e.detail,
                    severity=e.severity,
                    metadata=e.event_meta or {},
                    occurred_at=e.occurred_at,
                )
                for e in events_result.scalars().all()
            ]
    except Exception:
        logger.warning("Could not fetch pipeline events (table may not exist yet)")

    # --- 11. Source connections (from connector health) ---
    source_connections: list[dict] = [
        {
            "type": src,
            "label": info.get("label", src),
            "icon": {"github": "code", "jira": "task_alt", "jenkins": "terminal"}.get(src, "code"),
            "active": True,
            "syncing": latest_sync.status == "running" if latest_sync else False,
        }
        for src, info in connector_health.items()
    ]
    # Add unconfigured sources as inactive
    for src, label, icon in [("bitbucket", "Bitbucket", "code"), ("gitlab", "GitLab", "code")]:
        if src not in connector_health:
            source_connections.append({"type": src, "label": label, "icon": icon, "active": False, "syncing": False})

    return PipelineStatusResponse(
        overall_status=overall,
        stages=stages,
        kpis=PipelineKPIs(
            total_records=total_records,
            synced_today=synced_today,
            pending_sync=pending,
            errors_24h=errors_24h,
        ),
        record_counts=record_counts,
        recent_syncs=recent_syncs,
        recent_errors=recent_errors,
        recent_events=recent_events,
        source_connections=source_connections,
        devlake=devlake_info,
        last_updated=now,
    )


# ---------------------------------------------------------------------------
# Source-filtered status (Tela 2)
# ---------------------------------------------------------------------------


@router.get("/status/source/{source_type}", response_model=SourceFilteredStatus)
async def get_source_status(source_type: str) -> SourceFilteredStatus:
    """Get pipeline status filtered by a specific source type.

    Returns source-specific KPIs, active syncs, and recent events
    for the given source (github, jira, jenkins, etc.).
    """
    tenant_id = uuid.UUID(settings.default_tenant_id)
    now = datetime.now(timezone.utc)

    # Map source types to entity models for counting
    source_entity_map: dict[str, list] = {
        "github": [EngPullRequest, EngDeployment],
        "jira": [EngIssue, EngSprint],
        "jenkins": [EngDeployment],
        "bitbucket": [EngPullRequest],
        "gitlab": [EngPullRequest],
    }
    entities = source_entity_map.get(source_type, [])

    # --- Source-specific KPIs ---
    entity_count = 0
    synced_today = 0
    try:
        async with get_session(tenant_id) as session:
            for model in entities:
                count = (await session.execute(select(func.count(model.id)))).scalar() or 0
                entity_count += count
    except Exception:
        logger.warning("Could not count entities for source %s", source_type)

    # Count records synced today from sync logs for this source
    try:
        async with get_session(tenant_id) as session:
            sync_logs_result = await session.execute(
                select(PipelineSyncLog)
                .where(PipelineSyncLog.started_at >= now.replace(hour=0, minute=0, second=0, microsecond=0))
                .where(PipelineSyncLog.status.in_(["completed", "partial"]))
                .order_by(PipelineSyncLog.started_at.desc())
                .limit(20)
            )
            for s in sync_logs_result.scalars().all():
                rp = s.records_processed or {}
                for entity_key in source_entity_map.get(source_type, []):
                    table_name = getattr(entity_key, "__tablename__", "")
                    # Map model tablename to records_processed keys
                    key_map = {
                        "eng_pull_requests": "pull_requests",
                        "eng_issues": "issues",
                        "eng_deployments": "deployments",
                        "eng_sprints": "sprints",
                    }
                    mapped_key = key_map.get(table_name, "")
                    synced_today += rp.get(mapped_key, 0)
    except Exception:
        logger.warning("Could not compute synced_today for source %s", source_type)

    kpis = {
        "entities": entity_count,
        "synced_today": synced_today,
        "latency_ms": 120,  # Placeholder — real latency tracking in R2
        "webhooks": 0,
    }

    # --- Stages (same pipeline, status adjusted for source) ---
    is_active = source_type in ("github", "jira", "jenkins")
    source_stage_status = "healthy" if is_active and entity_count > 0 else "idle"
    stages = [
        PipelineStageStatus(name="connector", status=source_stage_status, label="Connector", detail=f"{entity_count} records"),
        PipelineStageStatus(name="normalizer", status="healthy" if is_active else "standby", label="Normalizer", detail="Transform"),
        PipelineStageStatus(name="sync_worker", status="healthy" if is_active else "standby", label="Sync Worker", detail="Kafka"),
        PipelineStageStatus(name="pulse_db", status="healthy" if entity_count > 0 else "standby", label="PULSE DB", detail="Persist"),
    ]

    # --- Active syncs (mock enriched for MVP) ---
    active_syncs: list[dict] = []
    if source_type == "github":
        active_syncs = [
            {"name": "webmotors/api", "type": "repository", "progress": 100, "last_sync": now.isoformat()},
            {"name": "webmotors/frontend", "type": "repository", "progress": 100, "last_sync": now.isoformat()},
        ]
    elif source_type == "jira":
        active_syncs = [
            {"name": "PULSE Board", "type": "board", "progress": 100, "last_sync": now.isoformat()},
        ]

    # --- Recent events for this source ---
    recent_logs: list[PipelineEventEntry] = []
    try:
        async with get_session(tenant_id) as session:
            events_result = await session.execute(
                select(PipelineEvent)
                .where(PipelineEvent.source == source_type)
                .order_by(PipelineEvent.occurred_at.desc())
                .limit(10)
            )
            recent_logs = [
                PipelineEventEntry(
                    id=str(e.id),
                    event_type=e.event_type,
                    source=e.source,
                    title=e.title,
                    detail=e.detail,
                    severity=e.severity,
                    metadata=e.event_meta or {},
                    occurred_at=e.occurred_at,
                )
                for e in events_result.scalars().all()
            ]
    except Exception:
        logger.warning("Could not fetch pipeline events for source %s", source_type)

    # Health percentage — 100 if active with records, 0 if inactive
    health_pct = 100.0 if is_active and entity_count > 0 else (50.0 if is_active else 0.0)

    return SourceFilteredStatus(
        source=source_type,
        kpis=kpis,
        stages=stages,
        active_syncs=active_syncs,
        recent_logs=recent_logs,
        health_pct=health_pct,
        sync_mode="delta",
    )


# ---------------------------------------------------------------------------
# Metrics Worker status (Tela 3)
# ---------------------------------------------------------------------------


@router.get("/metrics-worker/status", response_model=MetricsWorkerStatus)
async def get_metrics_worker_status() -> MetricsWorkerStatus:
    """Get Metrics Worker drill-down view.

    Returns KPIs, processing stages, recent metric snapshots,
    and cluster logs from pipeline events.
    """
    tenant_id = uuid.UUID(settings.default_tenant_id)

    # --- 1. Query recent metrics snapshots ---
    snapshots: list[MetricsWorkerSnapshot] = []
    total_processed = 0
    try:
        async with get_session(tenant_id) as session:
            snap_result = await session.execute(
                select(MetricsSnapshot)
                .order_by(MetricsSnapshot.calculated_at.desc())
                .limit(20)
            )
            for s in snap_result.scalars().all():
                # Estimate records processed from snapshot data
                data = s.value or {}
                records = len(data.get("series", [])) if isinstance(data, dict) else 1
                total_processed += records
                snapshots.append(MetricsWorkerSnapshot(
                    snapshot_id=str(s.id),
                    metric_type=s.metric_type,
                    timestamp=s.calculated_at,
                    duration_seconds=None,  # Not tracked yet
                    records_processed=records,
                    status="success",
                ))
    except Exception:
        logger.warning("Could not fetch metrics snapshots for worker status")

    # --- 2. Cluster logs (pipeline events from metrics_worker) ---
    cluster_logs: list[dict] = []
    try:
        async with get_session(tenant_id) as session:
            events_result = await session.execute(
                select(PipelineEvent)
                .where(PipelineEvent.source == "metrics_worker")
                .order_by(PipelineEvent.occurred_at.desc())
                .limit(10)
            )
            cluster_logs = [
                {
                    "id": str(e.id),
                    "event_type": e.event_type,
                    "title": e.title,
                    "detail": e.detail,
                    "severity": e.severity,
                    "occurred_at": e.occurred_at.isoformat(),
                }
                for e in events_result.scalars().all()
            ]
    except Exception:
        logger.warning("Could not fetch cluster logs for metrics worker")

    # --- 3. KPIs ---
    kpis = {
        "processing_rate": f"{total_processed}/cycle",
        "queue_latency": "< 1s",
        "active_nodes": 1,
        "dora_health": "healthy" if total_processed > 0 else "idle",
    }

    # --- 4. Stages ---
    stages = [
        {"name": "ingest", "label": "Ingest", "status": "healthy", "detail": "Kafka consumer"},
        {"name": "metrics_worker", "label": "Metrics Worker", "status": "healthy", "detail": f"{len(snapshots)} snapshots"},
        {"name": "persist", "label": "Persist", "status": "healthy", "detail": "PostgreSQL"},
        {"name": "dispatch", "label": "Dispatch", "status": "healthy", "detail": "API ready"},
    ]

    return MetricsWorkerStatus(
        kpis=kpis,
        stages=stages,
        snapshots=snapshots,
        cluster_logs=cluster_logs,
    )


# ---------------------------------------------------------------------------
# Ingestion Progress (real-time tracking)
# ---------------------------------------------------------------------------


@router.get("/ingestion/progress", response_model=IngestionProgressResponse)
async def get_ingestion_progress() -> IngestionProgressResponse:
    """Get real-time ingestion progress for all entity types.

    Returns progress per entity (pull_requests, issues, etc.) including:
    - Sources processed vs total
    - Records ingested so far
    - Current source being processed
    - Rate (records/minute) and ETA
    """
    tenant_id = uuid.UUID(settings.default_tenant_id)
    now = datetime.now(timezone.utc)

    entities: list[IngestionEntityProgress] = []
    any_running = False

    try:
        async with get_session(tenant_id) as session:
            result = await session.execute(
                select(PipelineIngestionProgress)
                .order_by(PipelineIngestionProgress.entity_type)
            )
            rows = list(result.scalars().all())
    except Exception:
        logger.warning("Could not fetch ingestion progress (table may not exist)")
        rows = []

    for row in rows:
        # Calculate computed fields
        progress_pct = 0.0
        if row.total_sources > 0:
            progress_pct = round((row.sources_done / row.total_sources) * 100, 1)

        elapsed_minutes = 0.0
        rate_per_minute = 0.0
        eta_minutes = None

        if row.started_at:
            elapsed = (now - row.started_at).total_seconds() / 60.0
            elapsed_minutes = round(elapsed, 1)

            if elapsed > 0 and row.records_ingested > 0:
                rate_per_minute = round(row.records_ingested / elapsed, 1)

            # ETA based on sources remaining at current rate
            if row.sources_done > 0 and row.total_sources > row.sources_done:
                minutes_per_source = elapsed / row.sources_done
                remaining_sources = row.total_sources - row.sources_done
                eta_minutes = round(minutes_per_source * remaining_sources, 1)

        is_running = row.status == "running"
        if is_running:
            any_running = True

        entities.append(IngestionEntityProgress(
            entity_type=row.entity_type,
            status=row.status,
            total_sources=row.total_sources,
            sources_done=row.sources_done,
            records_ingested=row.records_ingested,
            current_source=row.current_source,
            started_at=row.started_at,
            last_batch_at=row.last_batch_at,
            finished_at=row.finished_at,
            error_message=row.error_message,
            progress_pct=progress_pct,
            rate_per_minute=rate_per_minute,
            eta_minutes=eta_minutes,
            elapsed_minutes=elapsed_minutes,
        ))

    return IngestionProgressResponse(
        entities=entities,
        any_running=any_running,
        last_updated=now,
    )
