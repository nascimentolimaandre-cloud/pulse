"""Repository for BC4 — Metrics data access.

Provides async read methods for fetching engineering data
that metrics domain functions need as input.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.contexts.engineering_data.models import EngDeployment, EngIssue, EngPullRequest, EngSprint


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
        raise NotImplementedError("Phase 2: implement with SQLAlchemy select")

    async def get_deployments(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        environment: str = "production",
    ) -> list[EngDeployment]:
        """Fetch deployments within the given date range."""
        raise NotImplementedError("Phase 2: implement with SQLAlchemy select")

    async def get_issues(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        project_key: str | None = None,
    ) -> list[EngIssue]:
        """Fetch issues within the given date range."""
        raise NotImplementedError("Phase 2: implement with SQLAlchemy select")

    async def get_sprints(
        self,
        tenant_id: UUID,
        board_id: str | None = None,
        limit: int = 10,
    ) -> list[EngSprint]:
        """Fetch recent sprints, optionally filtered by board."""
        raise NotImplementedError("Phase 2: implement with SQLAlchemy select")
