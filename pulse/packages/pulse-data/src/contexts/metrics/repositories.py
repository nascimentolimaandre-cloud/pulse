"""Repository for BC4 -- Metrics data access.

Provides async read methods for fetching engineering data
that metrics domain functions need as input.

All queries are tenant-scoped via RLS (set by get_session).
"""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
    EngSprint,
)
from src.contexts.metrics.infrastructure.models import MetricsSnapshot

logger = logging.getLogger(__name__)


class MetricsRepository:
    """Reads engineering data for metric calculations.

    This repository fetches raw data; the actual metric math
    happens in pure domain functions (no DB access in domain layer).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_pull_requests(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        repo: str | None = None,
    ) -> list[EngPullRequest]:
        """Fetch pull requests within the given date range."""
        conditions = [
            EngPullRequest.tenant_id == tenant_id,
            EngPullRequest.created_at >= start_date,
            EngPullRequest.created_at <= end_date,
        ]
        if repo:
            conditions.append(EngPullRequest.repo == repo)

        stmt = (
            select(EngPullRequest)
            .where(and_(*conditions))
            .order_by(EngPullRequest.created_at.desc())
            .limit(5000)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_deployments(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        environment: str = "production",
    ) -> list[EngDeployment]:
        """Fetch deployments within the given date range."""
        conditions = [
            EngDeployment.tenant_id == tenant_id,
            EngDeployment.deployed_at >= start_date,
            EngDeployment.deployed_at <= end_date,
        ]
        if environment:
            conditions.append(EngDeployment.environment == environment)

        stmt = (
            select(EngDeployment)
            .where(and_(*conditions))
            .order_by(EngDeployment.deployed_at.desc())
            .limit(5000)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_issues(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        project_key: str | None = None,
    ) -> list[EngIssue]:
        """Fetch issues within the given date range."""
        conditions = [
            EngIssue.tenant_id == tenant_id,
            EngIssue.created_at >= start_date,
            EngIssue.created_at <= end_date,
        ]
        if project_key:
            conditions.append(EngIssue.project_key == project_key)

        stmt = (
            select(EngIssue)
            .where(and_(*conditions))
            .order_by(EngIssue.created_at.desc())
            .limit(5000)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_sprints(
        self,
        tenant_id: UUID,
        board_id: str | None = None,
        limit: int = 10,
    ) -> list[EngSprint]:
        """Fetch recent sprints, optionally filtered by board."""
        conditions = [EngSprint.tenant_id == tenant_id]
        if board_id:
            conditions.append(EngSprint.board_id == board_id)

        stmt = (
            select(EngSprint)
            .where(and_(*conditions))
            .order_by(EngSprint.started_at.desc().nulls_last())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_snapshot(
        self,
        tenant_id: UUID,
        metric_type: str,
        metric_name: str,
        period_start: datetime,
        period_end: datetime,
        team_id: UUID | None = None,
    ) -> MetricsSnapshot | None:
        """Fetch a specific metrics snapshot."""
        conditions = [
            MetricsSnapshot.tenant_id == tenant_id,
            MetricsSnapshot.metric_type == metric_type,
            MetricsSnapshot.metric_name == metric_name,
            MetricsSnapshot.period_start == period_start,
            MetricsSnapshot.period_end == period_end,
        ]
        if team_id:
            conditions.append(MetricsSnapshot.team_id == team_id)
        else:
            conditions.append(MetricsSnapshot.team_id.is_(None))

        stmt = select(MetricsSnapshot).where(and_(*conditions))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_snapshots(
        self,
        tenant_id: UUID,
        metric_type: str,
        team_id: UUID | None = None,
        limit: int = 10,
    ) -> list[MetricsSnapshot]:
        """Fetch the most recent snapshots for a metric type."""
        conditions = [
            MetricsSnapshot.tenant_id == tenant_id,
            MetricsSnapshot.metric_type == metric_type,
        ]
        if team_id:
            conditions.append(MetricsSnapshot.team_id == team_id)
        else:
            conditions.append(MetricsSnapshot.team_id.is_(None))

        stmt = (
            select(MetricsSnapshot)
            .where(and_(*conditions))
            .order_by(MetricsSnapshot.calculated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_snapshots_before_date(
        self,
        tenant_id: UUID,
        metric_type: str,
        before_date: datetime,
        team_id: UUID | None = None,
        limit: int = 20,
    ) -> list[MetricsSnapshot]:
        """Fetch most recent snapshots for a metric type calculated before a date.

        Used for period-over-period comparison: e.g. to get the "previous 30d"
        snapshot, pass before_date = now - 30 days.
        """
        conditions = [
            MetricsSnapshot.tenant_id == tenant_id,
            MetricsSnapshot.metric_type == metric_type,
            MetricsSnapshot.calculated_at < before_date,
        ]
        if team_id:
            conditions.append(MetricsSnapshot.team_id == team_id)
        else:
            conditions.append(MetricsSnapshot.team_id.is_(None))

        stmt = (
            select(MetricsSnapshot)
            .where(and_(*conditions))
            .order_by(MetricsSnapshot.calculated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
