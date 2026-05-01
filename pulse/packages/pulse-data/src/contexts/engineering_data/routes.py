"""API routes for BC3 — Engineering Data.

Serves normalized pull requests, issues, and integration status.
All queries are tenant-scoped via RLS.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
)
from src.contexts.metrics.schemas import (
    IntegrationListResponse,
    IntegrationStatus,
    IssueItem,
    IssueListResponse,
    PullRequestItem,
    PullRequestListResponse,
)
from src.config import settings
from src.contexts.engineering_data.services.backfill_first_commits import (
    run_backfill as _run_first_commits_backfill,
)
from src.contexts.engineering_data.services.backfill_mttr import (
    run_backfill as _run_mttr_backfill,
)
from src.contexts.engineering_data.services.backfill_deployed_at import (
    run_backfill as _run_deployed_at_backfill,
)
from src.contexts.engineering_data.services.backfill_descriptions import (
    run_backfill as _run_descriptions_backfill,
)
from src.database import get_session
from src.shared.tenant import get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/v1/engineering", tags=["engineering-data"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^(\d+)d$")
_VALID_PERIODS = {"7d", "14d", "30d", "90d"}


def _parse_period_to_start(period: str) -> datetime:
    """Parse a period string into a start datetime (now - N days).

    Returns start datetime. End is always 'now'.
    Raises HTTPException 400 for invalid period values.
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(sorted(_VALID_PERIODS))}",
        )
    match = _PERIOD_RE.match(period)
    days = int(match.group(1))  # type: ignore[union-attr]
    return datetime.now(timezone.utc) - timedelta(days=days)


# ---------------------------------------------------------------------------
# Pull Requests
# ---------------------------------------------------------------------------


@router.get("/pull-requests", response_model=PullRequestListResponse)
async def list_pull_requests(
    tenant_id: UUID = Depends(get_tenant_id),
    team_id: UUID | None = Query(None, description="Filter by team (reserved for future use)"),
    repo: str | None = Query(None, description="Filter by repository"),
    state: str | None = Query(None, description="Filter by state (open|merged|closed)"),
    author: str | None = Query(None, description="Filter by author"),
    period: str = Query("30d", description="Time period (7d|14d|30d|90d)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PullRequestListResponse:
    """List normalized pull requests for the current tenant."""
    period_start = _parse_period_to_start(period)

    async with get_session(tenant_id) as session:
        # Base conditions
        conditions = [
            EngPullRequest.tenant_id == tenant_id,
            EngPullRequest.created_at >= period_start,
        ]

        if repo:
            conditions.append(EngPullRequest.repo == repo)
        if state:
            conditions.append(EngPullRequest.state == state)
        if author:
            conditions.append(EngPullRequest.author == author)

        where_clause = and_(*conditions)

        # Count total matching records
        count_stmt = select(func.count()).select_from(EngPullRequest).where(where_clause)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Fetch paginated data
        data_stmt = (
            select(EngPullRequest)
            .where(where_clause)
            .order_by(EngPullRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        data_result = await session.execute(data_stmt)
        rows = data_result.scalars().all()

        items = [
            PullRequestItem(
                id=row.id,
                external_id=row.external_id,
                source=row.source,
                repo=row.repo,
                title=row.title,
                author=row.author,
                state=row.state,
                additions=row.additions,
                deletions=row.deletions,
                files_changed=row.files_changed,
                created_at=row.created_at,
                merged_at=row.merged_at,
                lead_time_hours=row.lead_time_hours,
                cycle_time_hours=row.cycle_time_hours,
            )
            for row in rows
        ]

    return PullRequestListResponse(
        data=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


@router.get("/issues", response_model=IssueListResponse)
async def list_issues(
    tenant_id: UUID = Depends(get_tenant_id),
    project_key: str | None = Query(None, description="Filter by project key"),
    normalized_status: str | None = Query(None, description="Filter by status (todo|in_progress|done)"),
    sprint_id: UUID | None = Query(None, description="Filter by sprint"),
    period: str = Query("30d", description="Time period (7d|14d|30d|90d)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> IssueListResponse:
    """List normalized issues for the current tenant."""
    period_start = _parse_period_to_start(period)

    async with get_session(tenant_id) as session:
        conditions = [
            EngIssue.tenant_id == tenant_id,
            EngIssue.created_at >= period_start,
        ]

        if project_key:
            conditions.append(EngIssue.project_key == project_key)
        if normalized_status:
            conditions.append(EngIssue.normalized_status == normalized_status)
        if sprint_id:
            conditions.append(EngIssue.sprint_id == sprint_id)

        where_clause = and_(*conditions)

        # Count total
        count_stmt = select(func.count()).select_from(EngIssue).where(where_clause)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Fetch paginated
        data_stmt = (
            select(EngIssue)
            .where(where_clause)
            .order_by(EngIssue.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        data_result = await session.execute(data_stmt)
        rows = data_result.scalars().all()

        items = [
            IssueItem(
                id=row.id,
                external_id=row.external_id,
                source=row.source,
                project_key=row.project_key,
                title=row.title,
                type=row.type,
                status=row.status,
                normalized_status=row.normalized_status,
                assignee=row.assignee,
                story_points=row.story_points,
                sprint_id=row.sprint_id,
                created_at=row.created_at,
                started_at=row.started_at,
                completed_at=row.completed_at,
                lead_time_hours=row.lead_time_hours,
                cycle_time_hours=row.cycle_time_hours,
            )
            for row in rows
        ]

    return IssueListResponse(
        data=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Integrations (read-only status)
# ---------------------------------------------------------------------------


@router.get("/integrations", response_model=IntegrationListResponse)
async def list_integrations(
    tenant_id: UUID = Depends(get_tenant_id),
) -> IntegrationListResponse:
    """List configured data connections with sync status.

    MVP: derives integration status from the presence of engineering data
    records per source. A real integration registry will replace this in R1.
    """
    async with get_session(tenant_id) as session:
        # Detect active sources from engineering data tables
        sources: list[IntegrationStatus] = []

        # Check pull requests by source
        pr_stmt = (
            select(
                EngPullRequest.source,
                func.count().label("record_count"),
                func.max(EngPullRequest.created_at).label("last_sync"),
            )
            .where(EngPullRequest.tenant_id == tenant_id)
            .group_by(EngPullRequest.source)
        )
        pr_result = await session.execute(pr_stmt)
        for row in pr_result:
            sources.append(
                IntegrationStatus(
                    name=f"{row.source} (Pull Requests)",
                    source=row.source,
                    status="connected",
                    last_sync_at=row.last_sync,
                    record_count=row.record_count,
                )
            )

        # Check issues by source
        issue_stmt = (
            select(
                EngIssue.source,
                func.count().label("record_count"),
                func.max(EngIssue.created_at).label("last_sync"),
            )
            .where(EngIssue.tenant_id == tenant_id)
            .group_by(EngIssue.source)
        )
        issue_result = await session.execute(issue_stmt)
        for row in issue_result:
            sources.append(
                IntegrationStatus(
                    name=f"{row.source} (Issues)",
                    source=row.source,
                    status="connected",
                    last_sync_at=row.last_sync,
                    record_count=row.record_count,
                )
            )

        # Check deployments by source
        deploy_stmt = (
            select(
                EngDeployment.source,
                func.count().label("record_count"),
                func.max(EngDeployment.deployed_at).label("last_sync"),
            )
            .where(EngDeployment.tenant_id == tenant_id)
            .group_by(EngDeployment.source)
        )
        deploy_result = await session.execute(deploy_stmt)
        for row in deploy_result:
            sources.append(
                IntegrationStatus(
                    name=f"{row.source} (Deployments)",
                    source=row.source,
                    status="connected",
                    last_sync_at=row.last_sync,
                    record_count=row.record_count,
                )
            )

    return IntegrationListResponse(
        data=sources,
        total=len(sources),
    )


# ---------------------------------------------------------------------------
# Admin — ad-hoc data-quality operations (INC-003)
# ---------------------------------------------------------------------------
#
# Protected by the shared INTERNAL_API_TOKEN. These endpoints trigger
# read-only GitHub GraphQL calls plus DB UPDATEs on PULSE-owned tables;
# they never mutate external systems.

admin_router = APIRouter(prefix="/data/v1/admin/prs", tags=["engineering-data-admin"])


def _check_admin_token(x_admin_token: str | None) -> None:
    """Validate admin token (constant-time compare). No implicit allow."""
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


@admin_router.post("/refresh-first-commits")
async def admin_refresh_first_commits(
    scope: str = Query(
        "stale",
        description="stale|all|last-60d — which PRs to refresh",
    ),
    dry_run: bool = Query(False, description="Count without writing"),
    max_prs: int | None = Query(
        None, description="Cap processed PRs (for quick smoke tests)",
    ),
    tenant_id: UUID = Depends(get_tenant_id),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Backfill `eng_pull_requests.first_commit_at` with the real first-commit
    authored_date from GitHub (INC-003 fix).

    scope:
      - `stale` (default): PRs where first_commit_at == created_at (bug symptom)
      - `all`: every GitHub PR for the tenant
      - `last-60d`: PRs with merged_at in the last 60 days (fast validation)
    """
    _check_admin_token(x_admin_token)

    if scope not in {"stale", "all", "last-60d"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid scope. Use: stale | all | last-60d",
        )

    logger.warning(
        "[admin] refresh-first-commits tenant=%s scope=%s dry_run=%s max_prs=%s",
        tenant_id, scope, dry_run, max_prs,
    )

    result = await _run_first_commits_backfill(
        tenant_id=tenant_id,
        scope=scope,  # type: ignore[arg-type]
        dry_run=dry_run,
        max_prs=max_prs,
    )

    return {
        "status": "completed" if not result.errors else "completed_with_errors",
        "scope": result.scope,
        "dry_run": result.dry_run,
        "tenant_id": str(tenant_id),
        "prs_processed": result.prs_processed,
        "prs_updated": result.prs_updated,
        "prs_unchanged": result.prs_unchanged,
        "prs_skipped": result.prs_skipped,
        "duration_sec": result.duration_sec,
        "rate_limit_remaining_start": result.rate_limit_remaining_start,
        "rate_limit_remaining_end": result.rate_limit_remaining_end,
        "sample_diffs": result.sample_diffs,
        "errors": result.errors,
    }


# ---------------------------------------------------------------------------
# Admin — INC-004 backfill `deployed_at` via temporal linking
# ---------------------------------------------------------------------------


@admin_router.post("/refresh-deployed-at")
async def admin_refresh_deployed_at(
    scope: str = Query(
        "stale",
        description="stale|all|last-60d — which PRs to refresh",
    ),
    strategy: str = Query(
        "both",
        description=(
            "sha|temporal|both — SHA match is not available today "
            "(Jenkins deploys carry no git SHA); defaults to temporal."
        ),
    ),
    window_days: int = Query(
        30,
        ge=1,
        le=180,
        description="Max days between merge and deploy to accept a temporal link",
    ),
    dry_run: bool = Query(False, description="Count without writing"),
    max_prs: int | None = Query(
        None, description="Cap processed PRs (for quick smoke tests)",
    ),
    tenant_id: UUID = Depends(get_tenant_id),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Backfill `eng_pull_requests.deployed_at` by linking each merged PR
    to the earliest production deployment in the same repo that occurred
    within `window_days` after merge (INC-004 fix).

    scope:
      - `stale` (default): PRs with `deployed_at IS NULL` (primary target)
      - `all`: every merged PR for the tenant
      - `last-60d`: PRs with merged_at in the last 60 days (fast validation)

    strategy:
      - `sha`: NOT SUPPORTED today (Jenkins deploys use build IDs, not SHAs)
      - `temporal`: repo + merged_at < deployed_at <= merged_at + window
      - `both`: equivalent to `temporal` until SHA enrichment lands
    """
    _check_admin_token(x_admin_token)

    if scope not in {"stale", "all", "last-60d"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid scope. Use: stale | all | last-60d",
        )
    if strategy not in {"sha", "temporal", "both"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid strategy. Use: sha | temporal | both",
        )

    logger.warning(
        "[admin] refresh-deployed-at tenant=%s scope=%s strategy=%s "
        "window_days=%d dry_run=%s max_prs=%s",
        tenant_id, scope, strategy, window_days, dry_run, max_prs,
    )

    result = await _run_deployed_at_backfill(
        tenant_id=tenant_id,
        scope=scope,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
        window_days=window_days,
        dry_run=dry_run,
        max_prs=max_prs,
    )

    return {
        "status": "completed" if not result.errors else "completed_with_errors",
        "scope": result.scope,
        "strategy": result.strategy,
        "window_days": result.window_days,
        "dry_run": result.dry_run,
        "tenant_id": str(tenant_id),
        "prs_processed": result.prs_processed,
        "prs_updated": result.prs_updated,
        "prs_no_match": result.prs_no_match,
        "prs_unchanged": result.prs_unchanged,
        "strategy_breakdown": result.strategy_breakdown,
        "duration_sec": result.duration_sec,
        "sample_matches": result.sample_matches,
        "errors": result.errors,
    }


# ---------------------------------------------------------------------------
# Admin — FDD-KB-013 backfill `eng_issues.description`
# ---------------------------------------------------------------------------
#
# Separate router prefix (`/data/v1/admin/issues`) since the existing
# `admin_router` is scoped to `/prs`. Both share the same admin token check.

issues_admin_router = APIRouter(
    prefix="/data/v1/admin/issues",
    tags=["engineering-data-admin"],
)


@issues_admin_router.post("/refresh-descriptions")
async def admin_refresh_descriptions(
    scope: str = Query(
        "stale",
        description="stale|last-90d|last-180d|in_progress|all — which issues to refresh",
    ),
    dry_run: bool = Query(False, description="Count without writing"),
    max_issues: int | None = Query(
        None, description="Cap processed issues (smoke tests / rate-limit budgeting)",
    ),
    tenant_id: UUID = Depends(get_tenant_id),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Backfill `eng_issues.description` with plain-text content from Jira
    (FDD-KB-013).

    scope:
      - `stale` (default): description IS NULL AND issue updated in the last 180d
      - `last-90d`: every issue updated in the last 90 days (refresh changed bodies)
      - `all`: entire tenant — expensive, cap with max_issues

    READ-ONLY on Jira — issues GET /rest/api/3/issue/{key} only.
    """
    _check_admin_token(x_admin_token)

    if scope not in {"stale", "last-90d", "last-180d", "in_progress", "all"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid scope. Use: stale | last-90d | last-180d | in_progress | all",
        )
    if max_issues is not None and max_issues <= 0:
        raise HTTPException(
            status_code=400,
            detail="max_issues must be a positive integer when provided",
        )

    logger.warning(
        "[admin] refresh-descriptions tenant=%s scope=%s dry_run=%s max_issues=%s",
        tenant_id, scope, dry_run, max_issues,
    )

    result = await _run_descriptions_backfill(
        tenant_id=tenant_id,
        scope=scope,  # type: ignore[arg-type]
        dry_run=dry_run,
        max_issues=max_issues,
    )

    return {
        "status": "completed" if not result.errors else "completed_with_errors",
        "scope": result.scope,
        "dry_run": result.dry_run,
        "tenant_id": str(tenant_id),
        "processed": result.processed,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "skipped": result.skipped,
        "duration_sec": result.duration_sec,
        "sample": result.sample,
        "errors": result.errors,
    }


# ---------------------------------------------------------------------------
# Admin — FDD-DSH-050 / INC-005 backfill MTTR (incident pairing)
# ---------------------------------------------------------------------------
#
# Separate router prefix `/data/v1/admin/deployments` since the existing
# admin routers are scoped to `/prs` and `/issues`. Same admin token check.

deployments_admin_router = APIRouter(
    prefix="/data/v1/admin/deployments",
    tags=["engineering-data-admin"],
)


@deployments_admin_router.post("/refresh-mttr")
async def admin_refresh_mttr(
    scope: str = Query(
        "stale",
        description="all|stale|last-90d — which failure rows to classify",
    ),
    open_window_days: int = Query(
        7,
        ge=1, le=90,
        description="Days to wait for a recovery deploy before tagging 'open'",
    ),
    dry_run: bool = Query(False, description="Classify without writing"),
    max_failures: int | None = Query(
        None, description="Cap processed failure rows (smoke testing)",
    ),
    tenant_id: UUID = Depends(get_tenant_id),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """FDD-DSH-050 — Pair `is_failure=true` deploys with their next
    successful deploy on the same (repo, environment) and populate
    `recovery_time_hours` + `incident_status` on the failure rows.

    Closes INC-005 (MTTR always NULL → DORA overall_level missing 1 of 4).

    Behavior:
      - For each prod failure: lookup next prod success on same repo
        within `open_window_days`.
      - Single failure with recovery in window → status='resolved' +
        recovery_time_hours computed.
      - Back-to-back failures (no success between them) → only the FIRST
        is the anchor; subsequent get status='superseded' pointing to
        the chain anchor (avoids inflating MTTR sample).
      - Failure with no recovery in window → status='open' (excluded
        from MTTR median, counted in mttr_open_incident_count).

    Idempotent: re-running on the same scope is safe (skips unchanged rows).

    scope:
      - `stale` (default): rows where `incident_status IS NULL` (un-classified)
      - `all`: every prod deploy regardless of current status
      - `last-90d`: prod deploys in the last 90 days (fast smoke)
    """
    _check_admin_token(x_admin_token)

    if scope not in {"all", "stale", "last-90d"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid scope. Use: all | stale | last-90d",
        )

    logger.warning(
        "[admin] refresh-mttr tenant=%s scope=%s window=%dd dry_run=%s "
        "max_failures=%s",
        tenant_id, scope, open_window_days, dry_run, max_failures,
    )

    result = await _run_mttr_backfill(
        tenant_id=tenant_id,
        scope=scope,  # type: ignore[arg-type]
        open_window_days=open_window_days,
        dry_run=dry_run,
        max_failures=max_failures,
    )

    return {
        "status": "completed" if not result.errors else "completed_with_errors",
        "scope": result.scope,
        "open_window_days": result.open_window_days,
        "dry_run": result.dry_run,
        "tenant_id": str(tenant_id),
        "deploys_scanned": result.deploys_scanned,
        "failures_anchored": result.failures_anchored,
        "failures_resolved": result.failures_resolved,
        "failures_open": result.failures_open,
        "failures_superseded": result.failures_superseded,
        "failures_unchanged": result.failures_unchanged,
        "duration_sec": result.duration_sec,
        "sample_pairings": result.sample_pairings,
        "errors": result.errors,
    }
