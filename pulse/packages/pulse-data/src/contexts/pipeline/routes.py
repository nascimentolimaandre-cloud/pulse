"""Pipeline Monitor v2 API routes.

Complete replacement of v1 routes. Provides six GET endpoints plus one
stub POST for the retry feature (backlogged).

All endpoints are READ-ONLY against the PULSE DB. No external system
calls are made.

v2: per-step breakdown, team health, coverage analysis, timeline feed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Response
from sqlalchemy import func, select, text

from src.config import settings
from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
)
from src.contexts.pipeline.models import (
    PipelineEvent,
    PipelineIngestionProgress,
    PipelineProgress,
    PipelineSyncLog,
    PipelineWatermark,
)
from src.contexts.pipeline.schemas import (
    ActiveProjectWithoutIssues,
    CatalogCounts,
    CoverageResponse,
    Entity,
    Integration,
    KPIs,
    OrphanPrefix,
    PipelineHealthResponse,
    ProgressJob,
    ReposWithDeploy,
    Source,
    Step,
    TeamHealth,
    TimelineEvent,
)
from src.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/v1/pipeline", tags=["Pipeline Monitor"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID(settings.default_tenant_id)

# Source -> entity_types mapping
_SOURCE_ENTITIES: dict[str, list[dict[str, str]]] = {
    "github": [
        {"type": "pull_requests", "label": "Pull Requests"},
        {"type": "deployments", "label": "Deployments (GitHub Actions)"},
    ],
    "jira": [
        {"type": "issues", "label": "Issues / Historias"},
        {"type": "sprints", "label": "Sprints"},
    ],
    "jenkins": [
        {"type": "deployments", "label": "Deployments (Jenkins)"},
    ],
}

# Entity type -> watermark entity_type in pipeline_watermarks
_ENTITY_WATERMARK_MAP: dict[str, str] = {
    "pull_requests": "pull_requests",
    "issues": "issues",
    "deployments": "deployments",
    "sprints": "sprints",
}

# pt-BR entity labels
_ENTITY_LABELS: dict[str, str] = {
    "pull_requests": "Pull Requests",
    "reviews": "Revisoes",
    "commits": "Commits",
    "deployments": "Deployments",
    "issues": "Issues / Historias",
    "sprints": "Sprints",
    "builds": "Builds",
}

# Placeholder rate limit percentages (not tracked yet — see docs/backlog.md)
_RATE_LIMIT_PLACEHOLDERS: dict[str, float] = {
    "github": 0.42,
    "jira": 0.78,
    "jenkins": 0.21,
}

# Integration registry — all six connectors
_ALL_INTEGRATIONS: list[dict[str, str]] = [
    {"id": "github", "name": "GitHub", "token_attr": "github_token"},
    {"id": "jira", "name": "Jira Cloud", "token_attr": "jira_api_token"},
    {"id": "jenkins", "name": "Jenkins", "token_attr": "jenkins_api_token"},
    {"id": "gitlab", "name": "GitLab", "token_attr": ""},
    {"id": "azure", "name": "Azure DevOps", "token_attr": ""},
    {"id": "bitbucket", "name": "Bitbucket", "token_attr": ""},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_source_configured(source_id: str) -> bool:
    """Check if a source has a configured API token."""
    attr_map = {"github": "github_token", "jira": "jira_api_token", "jenkins": "jenkins_api_token"}
    attr = attr_map.get(source_id, "")
    return bool(getattr(settings, attr, "")) if attr else False


def _derive_health_from_sources(source_statuses: list[str]) -> str:
    """Derive overall health from individual source statuses.

    Worst status wins (priority order): error > degraded > slow > backfilling > healthy.
    """
    priority = {"error": 0, "degraded": 1, "slow": 2, "backfilling": 3, "healthy": 4}
    if not source_statuses:
        return "healthy"
    worst = min(source_statuses, key=lambda s: priority.get(s, 99))
    return worst


def _derive_source_status(
    watermark: datetime | None,
    has_errors: bool,
    is_running: bool,
) -> str:
    """Derive a source's status from watermark age, errors, and run state."""
    now = datetime.now(timezone.utc)
    if has_errors:
        return "error"
    if is_running:
        return "backfilling"
    if watermark is None:
        return "degraded"
    lag = (now - watermark).total_seconds()
    if lag > 7200:  # >2h
        return "degraded"
    if lag > 3600:  # >1h
        return "slow"
    return "healthy"


def _synthesize_steps(
    progress: Any,
    now: datetime,
) -> list[Step]:
    """Synthesize aggregated steps from ingestion progress.

    TODO: replace synthesis with real per-step instrumentation once sync
    worker emits step-level events (see docs/backlog.md).
    """
    elapsed_sec = (
        (now - progress.started_at).total_seconds()
        if progress.started_at
        else 0.0
    )
    records = progress.records_ingested or 0
    sources_done = progress.sources_done or 0
    total_sources = progress.total_sources or 0
    all_done = sources_done >= total_sources and total_sources > 0

    # ETA calculation (same logic as v1)
    eta_sec: float | None = None
    if sources_done > 0 and total_sources > sources_done:
        sec_per_source = elapsed_sec / sources_done
        remaining = total_sources - sources_done
        eta_sec = round(sec_per_source * remaining, 1)

    throughput = round(records / elapsed_sec, 1) if elapsed_sec > 0 and records > 0 else None

    return [
        Step(
            name="fetch",
            status="done" if all_done else "running",
            processed=records,
            total=records,  # proxy — real total unknown without step instrumentation
            duration_sec=round(elapsed_sec, 1) if elapsed_sec else None,
            throughput_per_sec=throughput,
        ),
        Step(
            name="upsert",
            status="running" if not all_done else "done",
            processed=records,
            total=records,
            eta_sec=eta_sec,
            throughput_per_sec=throughput,
        ),
    ]


def _humanize_lag_ptbr(watermark: datetime | None) -> str:
    """Return a pt-BR string like 'há 4min' for the lag from now to watermark."""
    if watermark is None:
        return "sem dados"
    now = datetime.now(timezone.utc)
    delta = now - watermark
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"há {seconds}s"
    if seconds < 3600:
        return f"há {seconds // 60}min"
    if seconds < 86400:
        return f"há {seconds // 3600}h"
    return f"há {seconds // 86400}d"


# ---------------------------------------------------------------------------
# 1. GET /health
# ---------------------------------------------------------------------------


@router.get("/health", response_model=PipelineHealthResponse)
async def get_pipeline_health() -> PipelineHealthResponse:
    """Consolidated pipeline health with KPIs."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    records_today = 0
    records_yesterday = 0
    pr_link_rate = 0.0
    pr_link_rate_7d_ago = 0.0
    repos_covered = 0
    repos_total = 0
    avg_lag_sec = 0
    p95_lag_sec = 0
    source_statuses: list[str] = []

    try:
        async with get_session(_TENANT_ID) as session:
            # --- records today vs yesterday from pipeline_sync_log ---
            today_result = await session.execute(
                select(func.coalesce(func.sum(PipelineSyncLog.error_count * 0 + 1), 0))
                .where(PipelineSyncLog.started_at >= today_start)
            )
            # Actually sum records_processed (JSONB) - use raw SQL
            today_row = await session.execute(text("""
                SELECT COALESCE(SUM(
                    (SELECT COALESCE(SUM(v::int), 0)
                     FROM jsonb_each_text(COALESCE(records_processed, '{}'::jsonb)) AS t(k, v))
                ), 0) AS total
                FROM pipeline_sync_log
                WHERE started_at >= :today_start
            """), {"today_start": today_start})
            records_today = today_row.scalar() or 0

            yesterday_row = await session.execute(text("""
                SELECT COALESCE(SUM(
                    (SELECT COALESCE(SUM(v::int), 0)
                     FROM jsonb_each_text(COALESCE(records_processed, '{}'::jsonb)) AS t(k, v))
                ), 0) AS total
                FROM pipeline_sync_log
                WHERE started_at >= :yesterday_start AND started_at < :today_start
            """), {"yesterday_start": yesterday_start, "today_start": today_start})
            records_yesterday = yesterday_row.scalar() or 0

            # --- PR-issue link rate ---
            link_row = await session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE linked_issue_ids IS NOT NULL AND linked_issue_ids != '[]'::jsonb) AS linked,
                    COUNT(*) AS total
                FROM eng_pull_requests
            """))
            link_data = link_row.first()
            if link_data and link_data.total > 0:
                pr_link_rate = round(link_data.linked / link_data.total, 4)

            # link rate 7 days ago (PRs created before 7d ago)
            link_7d_row = await session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE linked_issue_ids IS NOT NULL AND linked_issue_ids != '[]'::jsonb) AS linked,
                    COUNT(*) AS total
                FROM eng_pull_requests
                WHERE created_at < NOW() - INTERVAL '7 days'
            """))
            link_7d_data = link_7d_row.first()
            if link_7d_data and link_7d_data.total > 0:
                pr_link_rate_7d_ago = round(link_7d_data.linked / link_7d_data.total, 4)

            # --- repos with deploy (30d) ---
            deploy_coverage_row = await session.execute(text("""
                SELECT
                    COUNT(DISTINCT repo) FILTER (WHERE source IS NOT NULL) AS covered,
                    (SELECT COUNT(DISTINCT repo) FROM eng_pull_requests) AS total
                FROM eng_deployments
                WHERE deployed_at >= NOW() - INTERVAL '30 days'
            """))
            dc = deploy_coverage_row.first()
            if dc:
                repos_covered = dc.covered or 0
                repos_total = dc.total or 0

            # --- sync lag from watermarks ---
            lag_row = await session.execute(text("""
                SELECT
                    COALESCE(AVG(EXTRACT(EPOCH FROM (NOW() - last_synced_at)))::int, 0) AS avg_lag,
                    COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (NOW() - last_synced_at)))::int, 0) AS p95_lag
                FROM pipeline_watermarks
            """))
            lag_data = lag_row.first()
            if lag_data:
                avg_lag_sec = lag_data.avg_lag or 0
                p95_lag_sec = lag_data.p95_lag or 0

            # --- per-source status for health derivation ---
            for source_id in ("github", "jira", "jenkins"):
                if not _is_source_configured(source_id):
                    continue
                entity_types = [e["type"] for e in _SOURCE_ENTITIES.get(source_id, [])]
                if not entity_types:
                    continue
                wm_row = await session.execute(
                    select(func.max(PipelineWatermark.last_synced_at))
                    .where(PipelineWatermark.entity_type.in_(entity_types))
                )
                wm = wm_row.scalar()

                # Check for errors in last 24h
                err_row = await session.execute(text("""
                    SELECT COUNT(*) AS cnt FROM pipeline_events
                    WHERE source = :source AND severity = 'error'
                      AND occurred_at >= NOW() - INTERVAL '24 hours'
                """), {"source": source_id})
                has_errors = (err_row.scalar() or 0) > 3

                # Check if running
                running_row = await session.execute(
                    select(func.count())
                    .select_from(PipelineIngestionProgress)
                    .where(PipelineIngestionProgress.status == "running")
                    .where(PipelineIngestionProgress.entity_type.in_(entity_types))
                )
                is_running = (running_row.scalar() or 0) > 0

                source_statuses.append(_derive_source_status(wm, has_errors, is_running))

    except Exception:
        logger.warning("Error computing pipeline health KPIs", exc_info=True)

    # Trend calculations
    records_trend_pct = 0.0
    if records_yesterday > 0:
        records_trend_pct = round(
            ((records_today - records_yesterday) / records_yesterday) * 100, 1
        )

    pr_link_trend_pp = round((pr_link_rate - pr_link_rate_7d_ago) * 100, 2)

    health = _derive_health_from_sources(source_statuses)

    return PipelineHealthResponse(
        health=health,
        last_updated_at=now,
        kpis=KPIs(
            records_today=records_today,
            records_trend_pct=records_trend_pct,
            pr_issue_link_rate=pr_link_rate,
            pr_issue_link_trend_pp=pr_link_trend_pp,
            repos_with_deploy_30d=ReposWithDeploy(covered=repos_covered, total=repos_total),
            avg_sync_lag_sec=avg_lag_sec,
            p95_sync_lag_sec=p95_lag_sec,
        ),
    )


# ---------------------------------------------------------------------------
# 2. GET /sources
# ---------------------------------------------------------------------------


@router.get("/sources", response_model=list[Source])
async def get_sources() -> list[Source]:
    """Return configured sources with entities and running steps."""
    now = datetime.now(timezone.utc)
    sources: list[Source] = []

    for source_id, entity_defs in _SOURCE_ENTITIES.items():
        if not _is_source_configured(source_id):
            continue

        entity_types = [e["type"] for e in entity_defs]

        try:
            async with get_session(_TENANT_ID) as session:
                # --- Connections count ---
                if source_id == "github":
                    conn_row = await session.execute(text(
                        "SELECT COUNT(DISTINCT repo) FROM eng_pull_requests"
                    ))
                    connections = conn_row.scalar() or 0
                elif source_id == "jira":
                    # Active projects from jira_project_catalog
                    conn_row = await session.execute(text(
                        "SELECT COUNT(*) FROM jira_project_catalog WHERE status IN ('active', 'discovered')"
                    ))
                    connections = conn_row.scalar() or 0
                elif source_id == "jenkins":
                    conn_row = await session.execute(text(
                        "SELECT COUNT(DISTINCT repo) FROM eng_deployments WHERE source = 'jenkins'"
                    ))
                    connections = conn_row.scalar() or 0
                else:
                    connections = 0

                # --- Catalog counts ---
                catalog = CatalogCounts(active=connections)
                if source_id == "jira":
                    try:
                        cat_row = await session.execute(text("""
                            SELECT
                                COUNT(*) FILTER (WHERE status = 'active') AS active,
                                COUNT(*) FILTER (WHERE status = 'discovered') AS discovered,
                                COUNT(*) FILTER (WHERE status = 'paused') AS paused,
                                COUNT(*) FILTER (WHERE status = 'blocked') AS blocked,
                                COUNT(*) FILTER (WHERE status = 'archived') AS archived
                            FROM jira_project_catalog
                        """))
                        cr = cat_row.first()
                        if cr:
                            catalog = CatalogCounts(
                                active=cr.active or 0,
                                discovered=cr.discovered or 0,
                                paused=cr.paused or 0,
                                blocked=cr.blocked or 0,
                                archived=cr.archived or 0,
                            )
                    except Exception:
                        logger.warning("Could not fetch jira_project_catalog counts")

                # --- Source-level watermark ---
                wm_row = await session.execute(
                    select(func.max(PipelineWatermark.last_synced_at))
                    .where(PipelineWatermark.entity_type.in_(entity_types))
                )
                source_watermark = wm_row.scalar()

                # --- Check for errors ---
                err_row = await session.execute(text("""
                    SELECT COUNT(*) FROM pipeline_events
                    WHERE source = :source AND severity = 'error'
                      AND occurred_at >= NOW() - INTERVAL '24 hours'
                """), {"source": source_id})
                has_errors = (err_row.scalar() or 0) > 3

                # --- Running check ---
                running_row = await session.execute(
                    select(func.count())
                    .select_from(PipelineIngestionProgress)
                    .where(PipelineIngestionProgress.status == "running")
                    .where(PipelineIngestionProgress.entity_type.in_(entity_types))
                )
                is_running = (running_row.scalar() or 0) > 0

                source_status = _derive_source_status(source_watermark, has_errors, is_running)

                # --- Build entities ---
                entities: list[Entity] = []
                for edef in entity_defs:
                    etype = edef["type"]
                    elabel = edef["label"]

                    # Per-entity watermark
                    ewm_row = await session.execute(
                        select(PipelineWatermark.last_synced_at)
                        .where(PipelineWatermark.entity_type == etype)
                        .limit(1)
                    )
                    ewatermark = ewm_row.scalar()

                    # Last completed sync log for this entity
                    last_cycle_row = await session.execute(text("""
                        SELECT
                            records_processed->:etype AS records,
                            duration_seconds
                        FROM pipeline_sync_log
                        WHERE status IN ('completed', 'partial')
                          AND records_processed ? :etype
                        ORDER BY finished_at DESC NULLS LAST
                        LIMIT 1
                    """), {"etype": etype})
                    lc = last_cycle_row.first()
                    last_cycle_records = None
                    last_cycle_duration = None
                    if lc and lc.records is not None:
                        try:
                            last_cycle_records = int(lc.records)
                        except (ValueError, TypeError):
                            pass
                        last_cycle_duration = lc.duration_seconds

                    # Check ingestion progress for running status
                    prog_row = await session.execute(
                        select(PipelineIngestionProgress)
                        .where(PipelineIngestionProgress.entity_type == etype)
                        .limit(1)
                    )
                    progress = prog_row.scalars().first()

                    entity_status: str = "idle"
                    steps: list[Step] | None = None
                    error_msg: str | None = None

                    if progress:
                        if progress.status == "running":
                            entity_status = "running"
                            steps = _synthesize_steps(progress, now)
                        elif progress.status == "completed":
                            entity_status = "healthy"
                        elif progress.status == "failed":
                            entity_status = "error"
                            error_msg = progress.error_message
                        else:
                            entity_status = "idle"
                    elif ewatermark is not None:
                        # Has data but no active progress row -> healthy
                        entity_status = "healthy"

                    entities.append(Entity(
                        type=etype,
                        label=elabel,
                        status=entity_status,
                        watermark=ewatermark,
                        last_cycle_records=last_cycle_records,
                        last_cycle_duration_sec=last_cycle_duration,
                        error=error_msg,
                        steps=steps,
                    ))

        except Exception:
            logger.warning("Error building source %s", source_id, exc_info=True)
            entities = [
                Entity(
                    type=e["type"],
                    label=e["label"],
                    status="error",
                    error="Falha ao consultar dados do pipeline",
                )
                for e in entity_defs
            ]
            source_status = "error"
            connections = 0
            source_watermark = None
            catalog = CatalogCounts()

        sources.append(Source(
            id=source_id,
            name={"github": "GitHub", "jira": "Jira Cloud", "jenkins": "Jenkins"}[source_id],
            status=source_status,
            connections=connections,
            rate_limit_pct=_RATE_LIMIT_PLACEHOLDERS.get(source_id, 0.0),
            watermark=source_watermark,
            catalog=catalog,
            entities=entities,
        ))

    return sources


# ---------------------------------------------------------------------------
# 3. GET /integrations
# ---------------------------------------------------------------------------


@router.get("/integrations", response_model=list[Integration])
async def get_integrations() -> list[Integration]:
    """Return all six integration connectors with status."""
    integrations: list[Integration] = []

    for reg in _ALL_INTEGRATIONS:
        int_id = reg["id"]
        int_name = reg["name"]
        token_attr = reg["token_attr"]

        connected = bool(getattr(settings, token_attr, "")) if token_attr else False

        if not connected:
            integrations.append(Integration(
                id=int_id,
                name=int_name,
                connected=False,
                status="disabled",
                detail="Não configurado",
            ))
            continue

        # Connected source — compute detail from watermark
        entity_types = [e["type"] for e in _SOURCE_ENTITIES.get(int_id, [])]
        watermark: datetime | None = None
        connections = 0

        try:
            async with get_session(_TENANT_ID) as session:
                if entity_types:
                    wm_row = await session.execute(
                        select(func.max(PipelineWatermark.last_synced_at))
                        .where(PipelineWatermark.entity_type.in_(entity_types))
                    )
                    watermark = wm_row.scalar()

                # Connection count
                if int_id == "github":
                    cr = await session.execute(text(
                        "SELECT COUNT(DISTINCT repo) FROM eng_pull_requests"
                    ))
                    connections = cr.scalar() or 0
                elif int_id == "jira":
                    cr = await session.execute(text(
                        "SELECT COUNT(*) FROM jira_project_catalog WHERE status IN ('active', 'discovered')"
                    ))
                    connections = cr.scalar() or 0
                elif int_id == "jenkins":
                    cr = await session.execute(text(
                        "SELECT COUNT(DISTINCT repo) FROM eng_deployments WHERE source = 'jenkins'"
                    ))
                    connections = cr.scalar() or 0

                # Errors in last 24h for status
                err_row = await session.execute(text("""
                    SELECT COUNT(*) FROM pipeline_events
                    WHERE source = :source AND severity = 'error'
                      AND occurred_at >= NOW() - INTERVAL '24 hours'
                """), {"source": int_id})
                err_count = err_row.scalar() or 0

        except Exception:
            logger.warning("Error fetching integration details for %s", int_id, exc_info=True)

        lag_str = _humanize_lag_ptbr(watermark)
        detail = f"{connections} repos" if int_id in ("github", "jenkins") else f"{connections} projetos"
        detail += f" · Última sync {lag_str}"

        status: str = "healthy"
        if err_count > 3:
            status = "error"
        elif err_count > 0:
            status = "degraded"
        elif watermark and (datetime.now(timezone.utc) - watermark).total_seconds() > 3600:
            status = "degraded"  # Stale watermark — "slow" not in IntegrationStatus

        integrations.append(Integration(
            id=int_id,
            name=int_name,
            connected=True,
            status=status,
            detail=detail,
        ))

    return integrations


# ---------------------------------------------------------------------------
# 4. GET /teams
# ---------------------------------------------------------------------------


@router.get("/teams", response_model=list[TeamHealth])
async def get_teams() -> list[TeamHealth]:
    """Return team/squad health derived from PR title references (last 90d).

    A 'team' = a project_key extracted from PR titles that has ≥1 PR in the last
    90 days. This gives a dynamic, self-healing list of active eng squads — NOT
    tied to the stale `jira_project_catalog.pr_reference_count` column.

    For each squad we compute repos, pr_count, issue_count, link_rate, deploy_count,
    and derive status via lag + link rate thresholds.
    """
    now = datetime.now(timezone.utc)
    teams: list[TeamHealth] = []

    try:
        async with get_session(_TENANT_ID) as session:
            # 1. Aggregate PR activity per squad via title regex + apply
            #    qualification rule. FDD-PIPE-001 — only QUALIFIED squads
            #    are returned. The activity tier (active/marginal/dormant)
            #    is computed alongside so the UI can sort/badge.
            #
            # Qualification rule (default config — see migration 014):
            #   has_metadata = (catalog.name IS NOT NULL AND name != '')
            #     → Jira API confirmed the project exists. Filters regex
            #       noise (RC, CVE, REDIRECTS, RELEASE, AXIOS — names empty
            #       because they were never enriched).
            #   has_any_activity = (issue_count >= 1 OR pr_count_90d >= 1)
            #     → Some sign of life.
            #   qualified = has_metadata AND has_any_activity
            #              UNLESS qualification_override='excluded'
            #              OR qualification_override='qualified' (forced in)
            #
            # Activity tier (orthogonal — never excludes, just labels):
            #   active   = pr_count_90d >= min_prs_90d_active_tier
            #   marginal = 1 <= pr_count_90d < min_prs_90d_active_tier
            #   dormant  = pr_count_90d == 0 AND issue_count >= 1
            #
            # `min_prs_90d_active_tier` reads from
            # `tenant_jira_config.squad_qualification_config` per tenant.
            agg_rows = await session.execute(text(r"""
                WITH config AS (
                    SELECT
                        COALESCE(
                            (squad_qualification_config->>'min_prs_90d_active_tier')::int,
                            5
                        ) AS min_prs_active,
                        COALESCE(
                            (squad_qualification_config->>'qualification_requires_metadata')::boolean,
                            TRUE
                        ) AS req_metadata,
                        COALESCE(
                            (squad_qualification_config->>'qualification_requires_any_activity')::boolean,
                            TRUE
                        ) AS req_activity
                    FROM tenant_jira_config
                    LIMIT 1
                ),
                pr_refs AS (
                    SELECT
                        UPPER((regexp_match(pr.title, '\m([A-Za-z][A-Za-z0-9]+)-\d+'))[1]) AS project_key,
                        pr.id AS pr_id,
                        pr.repo,
                        (pr.linked_issue_ids IS NOT NULL
                         AND pr.linked_issue_ids != '[]'::jsonb) AS is_linked
                    FROM eng_pull_requests pr
                    WHERE pr.created_at >= NOW() - INTERVAL '90 days'
                ),
                pr_aggregated AS (
                    SELECT
                        project_key,
                        COUNT(*) AS prs_referenced,
                        COUNT(*) FILTER (WHERE is_linked) AS prs_linked,
                        COUNT(DISTINCT repo) AS repos
                    FROM pr_refs
                    WHERE project_key IS NOT NULL
                    GROUP BY project_key
                ),
                -- Outer join: a squad qualifies via PRs OR via issues alone
                -- (data-only squad like Engenharia de Dados — INC-015).
                candidates AS (
                    SELECT
                        c.project_key,
                        c.name,
                        COALESCE(c.issue_count, 0) AS issue_count,
                        c.status AS catalog_status,
                        c.qualification_override,
                        COALESCE(p.prs_referenced, 0) AS prs_referenced,
                        COALESCE(p.prs_linked,     0) AS prs_linked,
                        COALESCE(p.repos,          0) AS repos
                    FROM jira_project_catalog c
                    LEFT JOIN pr_aggregated p ON p.project_key = c.project_key
                    WHERE c.status IN ('active', 'discovered')
                ),
                classified AS (
                    SELECT
                        cand.*,
                        cfg.min_prs_active,
                        -- Has Jira metadata? (Jira API confirmed project exists)
                        (cand.name IS NOT NULL AND cand.name != '') AS has_metadata,
                        -- Any sign of engineering life?
                        (cand.issue_count >= 1 OR cand.prs_referenced >= 1) AS has_activity,
                        -- Activity tier (computed even if not qualified — UI uses for sort)
                        CASE
                            WHEN cand.prs_referenced >= cfg.min_prs_active THEN 'active'
                            WHEN cand.prs_referenced BETWEEN 1 AND cfg.min_prs_active - 1 THEN 'marginal'
                            WHEN cand.prs_referenced = 0 AND cand.issue_count >= 1 THEN 'dormant'
                            ELSE 'marginal'
                        END AS tier
                    FROM candidates cand
                    CROSS JOIN config cfg
                )
                SELECT
                    project_key,
                    name,
                    issue_count,
                    catalog_status,
                    qualification_override,
                    prs_referenced,
                    prs_linked,
                    repos,
                    has_metadata,
                    has_activity,
                    tier,
                    -- Final qualification decision: override wins, otherwise heuristic.
                    CASE
                        WHEN qualification_override = 'excluded' THEN FALSE
                        WHEN qualification_override = 'qualified' THEN TRUE
                        ELSE (has_metadata AND has_activity)
                    END AS qualified,
                    CASE
                        WHEN qualification_override IN ('qualified','excluded') THEN 'override'
                        ELSE 'auto'
                    END AS qualification_source
                FROM classified
                ORDER BY tier ASC, prs_referenced DESC
            """))
            all_candidates = agg_rows.fetchall()

            # Filter: only qualified squads reach the response.
            squads = [s for s in all_candidates if s.qualified]

            if not squads:
                return []

            squad_keys = [s.project_key for s in squads]

            # 2. Enrichment: catalog (name, issue_count, last_sync_at, status)
            catalog_map: dict[str, dict] = {}
            try:
                cat_rows = await session.execute(text("""
                    SELECT project_key, name, issue_count, status, last_sync_at
                    FROM jira_project_catalog
                    WHERE project_key = ANY(:keys)
                """), {"keys": squad_keys})
                for r in cat_rows.fetchall():
                    catalog_map[r.project_key] = {
                        "name": r.name,
                        "issue_count": r.issue_count or 0,
                        "status": r.status,
                        "last_sync_at": r.last_sync_at,
                    }
            except Exception:
                logger.warning("catalog enrichment failed", exc_info=True)

            # 3. Deploy counts + Jenkins job counts per squad
            #    (single query via CTE with regex match, repo normalised with split_part)
            deploy_map: dict[str, int] = {}
            jenkins_map: dict[str, int] = {}
            try:
                dep_rows = await session.execute(text(r"""
                    WITH pr_squads AS (
                        SELECT DISTINCT
                            UPPER((regexp_match(pr.title, '\m([A-Za-z][A-Za-z0-9]+)-\d+'))[1]) AS project_key,
                            pr.repo
                        FROM eng_pull_requests pr
                        WHERE pr.created_at >= NOW() - INTERVAL '90 days'
                    )
                    SELECT ps.project_key,
                           COUNT(DISTINCT d.id) AS deploys,
                           COUNT(DISTINCT d.repo) FILTER (WHERE d.source = 'jenkins') AS jenkins_repos
                    FROM pr_squads ps
                    JOIN eng_deployments d ON d.repo = split_part(ps.repo, '/', 2)
                    WHERE d.deployed_at >= NOW() - INTERVAL '90 days'
                      AND ps.project_key IS NOT NULL
                    GROUP BY ps.project_key
                """))
                for r in dep_rows.fetchall():
                    deploy_map[r.project_key] = r.deploys or 0
                    jenkins_map[r.project_key] = r.jenkins_repos or 0
            except Exception:
                logger.warning("deploy aggregation failed", exc_info=True)

            # 4. Tribe lookup from teams table (board_config.jira.projects)
            tribe_map: dict[str, str] = {}
            try:
                tribe_rows = await session.execute(text("SELECT name, board_config FROM teams"))
                for row in tribe_rows.fetchall():
                    bc = row.board_config
                    if isinstance(bc, dict):
                        for pk in bc.get("jira", {}).get("projects", []) or []:
                            tribe_map[str(pk).upper()] = row.name
            except Exception:
                logger.warning("teams table not available for tribe lookup")

            # 5. Assemble response
            issue_wm_row = await session.execute(
                select(func.max(PipelineWatermark.last_synced_at))
                .where(PipelineWatermark.entity_type == "issues")
            )
            issues_watermark = issue_wm_row.scalar()

            for s in squads:
                pk = s.project_key
                cat = catalog_map.get(pk, {})
                pname = cat.get("name") or pk
                link_rate = round(s.prs_linked / s.prs_referenced, 4) if s.prs_referenced > 0 else 0.0
                last_sync = cat.get("last_sync_at") or issues_watermark

                if last_sync:
                    lag_sec = int((now - last_sync).total_seconds())
                else:
                    lag_sec = 0

                # Health derivation — sync cadence is periodic (hours/daily),
                # so use generous thresholds for team-level health status.
                # NOTE: cell-level lag coloring still uses strict spec thresholds
                # (<600s green, 600-1800 yellow, >1800 red) in the frontend.
                if last_sync is None or lag_sec > 172800:  # >48h = error
                    health = "error"
                elif link_rate < 0.15 or lag_sec > 86400:  # <15% link rate OR >24h = degraded
                    health = "degraded"
                elif cat.get("status") == "discovered":
                    health = "backfilling"
                else:
                    health = "healthy"

                teams.append(TeamHealth(
                    id=pk.lower(),
                    name=pname,
                    tribe=tribe_map.get(pk),
                    squad_key=pk,
                    health=health,
                    repos=s.repos or 0,
                    jira_projects=[pk],
                    jenkins_jobs=jenkins_map.get(pk, 0),
                    pr_count=s.prs_referenced or 0,
                    issue_count=cat.get("issue_count", 0),
                    deploy_count=deploy_map.get(pk, 0),
                    link_rate=link_rate,
                    last_sync=last_sync,
                    lag_sec=lag_sec,
                    # FDD-PIPE-001 — propagate qualification metadata
                    tier=s.tier,
                    qualification_source=s.qualification_source,
                ))

    except Exception:
        logger.warning("Error computing team health", exc_info=True)

    return teams


# ---------------------------------------------------------------------------
# 5. GET /timeline
# ---------------------------------------------------------------------------


@router.get("/timeline", response_model=list[TimelineEvent])
async def get_timeline(
    severity: str = Query(default="", description="Filter: info, warning, error, success, or 'warn+' for warning+error"),
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None, description="Cursor: only events before this ISO timestamp"),
) -> list[TimelineEvent]:
    """Return pipeline timeline events."""
    events: list[TimelineEvent] = []

    try:
        async with get_session(_TENANT_ID) as session:
            # Build severity filter
            severity_filter = ""
            params: dict[str, Any] = {"limit": limit}

            if severity == "warn+":
                severity_filter = "AND severity IN ('warning', 'error')"
            elif severity:
                allowed = [s.strip() for s in severity.split(",") if s.strip()]
                if allowed:
                    severity_filter = f"AND severity IN ({','.join(':s' + str(i) for i in range(len(allowed)))})"
                    for i, s in enumerate(allowed):
                        params[f"s{i}"] = s

            before_filter = ""
            if before:
                before_filter = "AND occurred_at < :before"
                params["before"] = before

            rows = await session.execute(text(f"""
                SELECT occurred_at, severity, source, title
                FROM pipeline_events
                WHERE 1=1 {severity_filter} {before_filter}
                ORDER BY occurred_at DESC
                LIMIT :limit
            """), params)

            for row in rows.fetchall():
                events.append(TimelineEvent(
                    ts=row.occurred_at,
                    severity=row.severity,
                    stage=row.source,
                    message=row.title,
                ))

    except Exception:
        logger.warning("Error fetching timeline events", exc_info=True)

    return events


# ---------------------------------------------------------------------------
# 6. GET /coverage
# ---------------------------------------------------------------------------


@router.get("/coverage", response_model=CoverageResponse)
async def get_coverage() -> CoverageResponse:
    """Return pipeline coverage analysis."""
    repos_covered = 0
    repos_total = 0
    pr_link_rate = 0.0
    orphans: list[OrphanPrefix] = []
    active_no_issues: list[ActiveProjectWithoutIssues] = []

    try:
        async with get_session(_TENANT_ID) as session:
            # --- repos with deploy ---
            dc_row = await session.execute(text("""
                SELECT
                    COUNT(DISTINCT repo) FILTER (WHERE source IS NOT NULL) AS covered,
                    (SELECT COUNT(DISTINCT repo) FROM eng_pull_requests) AS total
                FROM eng_deployments
                WHERE deployed_at >= NOW() - INTERVAL '30 days'
            """))
            dc = dc_row.first()
            if dc:
                repos_covered = dc.covered or 0
                repos_total = dc.total or 0

            # --- PR-issue link rate ---
            lr_row = await session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE linked_issue_ids IS NOT NULL AND linked_issue_ids != '[]'::jsonb) AS linked,
                    COUNT(*) AS total
                FROM eng_pull_requests
            """))
            lr = lr_row.first()
            if lr and lr.total > 0:
                pr_link_rate = round(lr.linked / lr.total, 4)

            # --- Orphan prefixes ---
            try:
                orphan_rows = await session.execute(text("""
                    SELECT prefix, COUNT(*) AS mentions
                    FROM (
                        SELECT (regexp_match(pr.title, '\\m([A-Z][A-Z0-9]+)-\\d+'))[1] AS prefix
                        FROM eng_pull_requests pr
                        WHERE pr.created_at > NOW() - INTERVAL '90 days'
                    ) sub
                    WHERE prefix IS NOT NULL
                      AND prefix NOT IN (SELECT project_key FROM jira_project_catalog)
                    GROUP BY prefix
                    ORDER BY mentions DESC
                    LIMIT 5
                """))
                for row in orphan_rows.fetchall():
                    orphans.append(OrphanPrefix(prefix=row.prefix, pr_mentions=row.mentions))
            except Exception:
                logger.warning("Error computing orphan prefixes (jira_project_catalog may not exist)")

            # --- Active projects with zero issues ---
            try:
                no_issues_rows = await session.execute(text("""
                    SELECT project_key, name
                    FROM jira_project_catalog
                    WHERE status = 'active'
                      AND (issue_count IS NULL OR issue_count = 0)
                    ORDER BY project_key
                """))
                for row in no_issues_rows.fetchall():
                    active_no_issues.append(
                        ActiveProjectWithoutIssues(key=row.project_key, name=row.name or row.project_key)
                    )
            except Exception:
                logger.warning("Error fetching active projects without issues")

    except Exception:
        logger.warning("Error computing coverage", exc_info=True)

    return CoverageResponse(
        repos_with_deploy=ReposWithDeploy(covered=repos_covered, total=repos_total),
        pr_issue_link_rate=pr_link_rate,
        orphan_prefixes=orphans,
        active_projects_without_issues=active_no_issues,
    )


# ---------------------------------------------------------------------------
# 7. POST /entities/{sourceId}/{entityType}/retry — STUB
# ---------------------------------------------------------------------------


@router.post("/entities/{source_id}/{entity_type}/retry", status_code=501)
async def retry_entity(source_id: str, entity_type: str, response: Response) -> dict[str, str]:
    """Feature-flagged retry — not yet implemented.

    See docs/backlog.md for roadmap.
    """
    return {"detail": "Retry feature is in backlog -- see docs/backlog.md"}


# ---------------------------------------------------------------------------
# 8. GET /schema-drift — FDD-OPS-001 Line 3
# ---------------------------------------------------------------------------


@router.get("/schema-drift")
async def get_schema_drift(
    hours: int = Query(24, ge=1, le=168, description="Look-back window in hours (max 168 = 7d)"),
) -> dict[str, Any]:
    """Return snapshots written with schema drift in the last N hours.

    Surfaces cases where a Python worker wrote a snapshot missing fields
    declared on the current domain dataclass — the signature pattern of
    worker bytecode being out of sync with code on disk. Consumed by the
    Pipeline Monitor banner so operators see drift without digging
    through logs.

    Drift is annotated inside `metrics_snapshots.value->>'_schema_drift'`
    by `snapshot_writer._detect_schema_drift`.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)

    by_metric: list[dict[str, Any]] = []
    total_affected = 0

    try:
        async with get_session(_TENANT_ID) as session:
            rows = await session.execute(text("""
                SELECT
                    metric_type,
                    metric_name,
                    value->'_schema_drift'->'missing_fields' AS missing_fields,
                    COUNT(*) AS cnt,
                    MIN(updated_at) AS first_seen,
                    MAX(updated_at) AS last_seen
                FROM metrics_snapshots
                WHERE updated_at >= :window_start
                  AND value ? '_schema_drift'
                GROUP BY metric_type, metric_name, value->'_schema_drift'->'missing_fields'
                ORDER BY last_seen DESC
            """), {"window_start": window_start})

            for row in rows.fetchall():
                # missing_fields is a JSONB array — psycopg returns a Python list.
                missing = row.missing_fields if isinstance(row.missing_fields, list) else []
                total_affected += row.cnt or 0
                by_metric.append({
                    "metric_type": row.metric_type,
                    "metric_name": row.metric_name,
                    "missing_fields": missing,
                    "first_seen": row.first_seen,
                    "last_seen": row.last_seen,
                    "count": row.cnt or 0,
                    "remedy": (
                        "Stale worker bytecode — `docker compose restart "
                        "metrics-worker pulse-data` or POST /admin/metrics/recalculate"
                    ),
                })

    except Exception:
        logger.warning("Error querying schema drift", exc_info=True)

    return {
        "detected_at": now,
        "window_hours": hours,
        "total_affected_snapshots": total_affected,
        "by_metric": by_metric,
    }


# ---------------------------------------------------------------------------
# FDD-OPS-015 — Per-scope progress endpoint
# ---------------------------------------------------------------------------

# Threshold (seconds) above which a still-running job is flagged as "stalled".
# 60s matches the FDD acceptance criterion ("60 seconds without progress").
_STALL_THRESHOLD_SECONDS = 60


@router.get("/jobs", response_model=list[ProgressJob])
async def get_pipeline_jobs(
    status: str | None = Query(
        default=None,
        description="Filter by status (running | done | failed | paused | cancelled)",
    ),
    entity_type: str | None = Query(
        default=None,
        description="Filter by entity_type (issues | pull_requests | deployments | sprints)",
    ),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ProgressJob]:
    """FDD-OPS-015 — Per-scope ingestion progress.

    Returns one row per active (or recently completed) ingestion scope.
    During a Webmotors backfill that's ~32+ rows (one per Jira project +
    one per GitHub repo). Sorted: running first (newest first), then
    completed (most recent first).

    Computed fields:
      - `progress_pct`: 0-100 when items_estimate is set
      - `is_stalled`: True when status='running' and last_progress_at is
        more than 60 seconds in the past — operator signal that something
        upstream (network, source API) needs attention

    Operators use this for "is the BG project still progressing or
    stalled?" type questions. Pipeline Monitor UI consumes the same
    endpoint via polling.
    """
    now = datetime.now(timezone.utc)
    stall_cutoff = now - timedelta(seconds=_STALL_THRESHOLD_SECONDS)

    async with get_session(_TENANT_ID) as session:
        conditions = [PipelineProgress.tenant_id == _TENANT_ID]
        if status:
            conditions.append(PipelineProgress.status == status)
        if entity_type:
            conditions.append(PipelineProgress.entity_type == entity_type)

        # Order: running first (most recent activity), then anything else
        # by most recent activity. CASE clause for status priority.
        from sqlalchemy import case as sql_case
        status_priority = sql_case(
            (PipelineProgress.status == "running", 0),
            (PipelineProgress.status == "failed", 1),
            (PipelineProgress.status == "paused", 2),
            else_=3,
        )

        stmt = (
            select(PipelineProgress)
            .where(*conditions)
            .order_by(status_priority, PipelineProgress.last_progress_at.desc())
            .limit(limit)
        )
        rows = await session.execute(stmt)
        records = rows.scalars().all()

    jobs: list[ProgressJob] = []
    for r in records:
        # Computed: progress_pct
        pct: float | None = None
        if r.items_estimate and r.items_estimate > 0:
            pct = min(100.0, 100.0 * r.items_done / r.items_estimate)

        # Computed: is_stalled (running + last update > 60s ago)
        is_stalled = bool(
            r.status == "running" and r.last_progress_at < stall_cutoff
        )

        jobs.append(
            ProgressJob(
                scope_key=r.scope_key,
                entity_type=r.entity_type,
                phase=r.phase,
                status=r.status,
                items_done=r.items_done,
                items_estimate=r.items_estimate,
                progress_pct=pct,
                items_per_second=r.items_per_second,
                eta_seconds=r.eta_seconds,
                started_at=r.started_at,
                last_progress_at=r.last_progress_at,
                finished_at=r.finished_at,
                is_stalled=is_stalled,
                last_error=r.last_error,
            )
        )

    return jobs


# ===========================================================================
# Admin router — squad qualification override (FDD-PIPE-001)
# ===========================================================================
# Lets an operator force a squad into or out of the qualified list,
# bypassing the heuristic. Persisted as `jira_project_catalog.qualification_override`.

squad_admin_router = APIRouter(
    prefix="/data/v1/admin/squads",
    tags=["pipeline-admin"],
)


def _check_admin_token(x_admin_token: str | None) -> None:
    """Validate admin token (constant-time compare). Mirrors the pattern in
    other admin routers — `_check_admin_token` is duplicated rather than
    shared because the token-check helper is intentionally local to each
    router so removal of one router doesn't break the others.
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


_VALID_OVERRIDES = {"qualified", "excluded", None}


@squad_admin_router.post("/{squad_key}/qualification")
async def admin_set_squad_qualification(
    squad_key: str,
    override: str | None = Query(
        None,
        description="'qualified' | 'excluded' | null (clear). Null restores automatic heuristic.",
    ),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """FDD-PIPE-001 — Force-include or force-exclude a squad from the
    qualified list. Set `override=null` to restore automatic qualification.

    Use cases:
      - `qualified`: include a squad whose Jira metadata is missing
        (e.g. project moved to a different Jira instance, sync gap).
      - `excluded`: hide a squad that auto-qualifies but isn't engineering
        (e.g. a tribe-wide tag matched the regex).
      - `null` (clear): return to heuristic — most common after data quality
        issues are fixed.

    Persists in `jira_project_catalog.qualification_override`. Reflected in
    the next `GET /pipeline/teams` response (no caching).
    """
    _check_admin_token(x_admin_token)

    # Validate squad_key format (mirrors pattern in metrics/routes.py).
    if not squad_key or len(squad_key) > 32 or not squad_key[0].isalpha():
        raise HTTPException(
            status_code=422,
            detail="Invalid squad_key. Must be 2-32 alphanumeric chars starting with a letter.",
        )
    squad_key_upper = squad_key.upper()

    # Normalize override: empty string from query coerces to None.
    if override == "" or override == "null":
        override = None

    if override not in _VALID_OVERRIDES:
        raise HTTPException(
            status_code=422,
            detail="Invalid override. Use 'qualified' | 'excluded' | null.",
        )

    logger.warning(
        "[admin] set_squad_qualification squad=%s override=%s",
        squad_key_upper, override,
    )

    async with get_session(_TENANT_ID) as session:
        # Verify squad exists in catalog (don't silently create rows).
        existing = await session.execute(
            text("""
                SELECT project_key, qualification_override, name, status
                FROM jira_project_catalog
                WHERE project_key = :key
            """),
            {"key": squad_key_upper},
        )
        row = existing.first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Squad '{squad_key_upper}' not in jira_project_catalog. "
                       "Activate the project first or wait for discovery.",
            )

        previous = row.qualification_override

        # Update — Postgres handles NULL correctly here.
        await session.execute(
            text("""
                UPDATE jira_project_catalog
                SET qualification_override = :override,
                    updated_at = now()
                WHERE project_key = :key
            """),
            {"override": override, "key": squad_key_upper},
        )
        await session.commit()

    return {
        "status": "updated",
        "squad_key": squad_key_upper,
        "previous_override": previous,
        "current_override": override,
        "name": row.name or "",
        "catalog_status": row.status,
    }
