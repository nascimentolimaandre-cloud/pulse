"""Pipeline Monitor API routes.

Provides a consolidated view of the data pipeline health: stage
statuses, record counts (DevLake vs PULSE), sync logs, errors,
and DevLake API pipeline status.

All DevLake calls are wrapped in try/except — the pipeline monitor
degrades gracefully when DevLake is unavailable.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import func, select, text

from src.config import settings
from src.contexts.engineering_data.devlake_reader import DevLakeReader
from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
    EngSprint,
)
from src.contexts.pipeline.devlake_api import DevLakeAPIClient
from src.contexts.metrics.infrastructure.models import MetricsSnapshot
from src.contexts.pipeline.models import PipelineEvent, PipelineSyncLog, PipelineWatermark
from src.contexts.pipeline.schemas import (
    DevLakePipelineInfo,
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


async def _get_devlake_counts(reader: DevLakeReader) -> dict[str, int]:
    """Query DevLake DB for record counts per entity type.

    Returns a dict like {"pull_requests": 120, "issues": 300, ...}.
    Falls back to zeros if any query fails.
    """
    counts: dict[str, int] = {
        "pull_requests": 0,
        "issues": 0,
        "deployments": 0,
        "sprints": 0,
    }
    table_map = {
        "pull_requests": "pull_requests",
        "issues": "issues",
        "deployments": "cicd_deployment_commits",
        "sprints": "sprints",
    }
    async with reader._session_factory() as session:
        for entity, table in table_map.items():
            try:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
                counts[entity] = result.scalar() or 0
            except Exception:
                logger.warning("Could not count DevLake table %s", table)
    return counts


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status() -> PipelineStatusResponse:
    """Get consolidated pipeline health status.

    Aggregates data from: PULSE DB tables, DevLake reader counts,
    DevLake API status, sync logs, and watermarks.
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

    # --- 2. Record counts (DevLake DB) ---
    devlake_counts: dict[str, int] = {
        "pull_requests": 0,
        "issues": 0,
        "deployments": 0,
        "sprints": 0,
    }
    try:
        reader = DevLakeReader()
        devlake_counts = await _get_devlake_counts(reader)
        await reader.close()
    except Exception:
        logger.warning("Could not connect to DevLake DB for record counts")

    record_counts = []
    for entity in ["pull_requests", "issues", "deployments", "sprints"]:
        dl = devlake_counts.get(entity, 0)
        pl = pulse_counts.get(entity, 0)
        record_counts.append(RecordCount(
            entity=entity,
            devlake_count=dl,
            pulse_count=pl,
            difference=dl - pl,
            is_synced=abs(dl - pl) <= 5,  # tolerance of 5 records
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

    # --- 7. Pending sync (difference between DevLake and PULSE) ---
    pending = sum(max(0, rc.difference) for rc in record_counts)

    # --- 8. DevLake API status ---
    devlake_info = DevLakePipelineInfo()
    try:
        client = DevLakeAPIClient()
        health = await client.get_pipeline_health()
        devlake_info = DevLakePipelineInfo(
            is_running=health.get("is_running", False),
            last_status=health.get("last_status"),
            last_finished_at=health.get("last_finished_at"),
        )
    except Exception:
        logger.warning("Could not reach DevLake API for pipeline health")

    # --- 9. Build stage statuses ---
    total_records = sum(pulse_counts.values())

    # Determine overall status
    latest_sync = sync_logs[0] if sync_logs else None
    if errors_24h > 5:
        overall = "error"
    elif errors_24h > 0 or pending > 50:
        overall = "degraded"
    elif devlake_info.is_running or (latest_sync and latest_sync.status == "running"):
        overall = "syncing"
    else:
        overall = "healthy"

    # Determine per-stage status
    source_status = "healthy" if total_records > 0 else "idle"
    devlake_status = (
        "syncing"
        if devlake_info.is_running
        else ("healthy" if devlake_info.last_status == "TASK_COMPLETED" else "idle")
    )
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
            label="Sources",
            detail=f"{len([r for r in record_counts if r.devlake_count > 0])} active",
        ),
        PipelineStageStatus(
            name="devlake",
            status=devlake_status,
            label="DevLake",
            detail="ETL Layer",
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

    # --- 11. Source connections (static for MVP) ---
    source_connections: list[dict] = [
        {"type": "github", "label": "GitHub", "icon": "code", "active": True, "syncing": True},
        {"type": "jira", "label": "Jira Cloud", "icon": "task_alt", "active": True, "syncing": False},
        {"type": "jenkins", "label": "Jenkins", "icon": "terminal", "active": True, "syncing": False},
        {"type": "bitbucket", "label": "Bitbucket", "icon": "code", "active": False, "syncing": False},
        {"type": "gitlab", "label": "GitLab", "icon": "code", "active": False, "syncing": False},
    ]

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
    is_active = source_type in ("github", "jira")
    source_stage_status = "healthy" if is_active and entity_count > 0 else "idle"
    stages = [
        PipelineStageStatus(name="ingestion", status=source_stage_status, label="Ingestion", detail=f"{entity_count} records"),
        PipelineStageStatus(name="devlake", status="healthy" if is_active else "standby", label="DevLake ETL", detail="Transform"),
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
