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

from fastapi import APIRouter, Depends, HTTPException, Query
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
