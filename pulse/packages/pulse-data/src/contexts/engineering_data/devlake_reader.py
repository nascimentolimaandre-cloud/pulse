"""DevLake DB reader — async queries against DevLake's domain tables.

Reads from DevLake's normalized PostgreSQL tables (pull_requests, issues,
cicd_deployment_commits, sprints, boards) and returns raw dicts for the
normalizer to transform into PULSE domain models.

Uses a separate SQLAlchemy engine connected to the DevLake database (read-only).
All queries use watermark-based incremental sync via `since` parameter.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

logger = logging.getLogger(__name__)


def _make_devlake_async_url(url: str) -> str:
    """Convert a DevLake DB URL to async format (asyncpg)."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    raise ValueError(f"Unsupported DevLake DB URL scheme: {url}")


class DevLakeReader:
    """Reads normalized data from DevLake's PostgreSQL domain tables.

    Each fetch method accepts a `since` datetime for incremental sync
    (watermark pattern). Returns raw dicts that the normalizer converts
    to PULSE domain models.
    """

    def __init__(self, devlake_db_url: str | None = None) -> None:
        url = devlake_db_url or settings.devlake_db_url
        async_url = _make_devlake_async_url(url)
        self._engine = create_async_engine(
            async_url,
            echo=False,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def close(self) -> None:
        """Dispose the engine connection pool."""
        await self._engine.dispose()
        logger.info("DevLake reader connection pool disposed")

    async def fetch_pull_requests(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch pull requests from DevLake domain table."""
        base = """
            SELECT
                pr.id, pr.base_repo_id, pr.head_repo_id, pr.status,
                pr.title, pr.url, pr.author_name,
                pr.created_date, pr.merged_date, pr.closed_date,
                pr.merge_commit_sha, pr.base_ref, pr.head_ref,
                pr.additions, pr.deletions
            FROM pull_requests pr
        """
        if since is not None:
            query = text(base + " WHERE pr.created_date > :since ORDER BY pr.created_date DESC LIMIT 5000")
            params = {"since": since}
        else:
            query = text(base + " ORDER BY pr.created_date DESC LIMIT 5000")
            params = {}

        async with self._session_factory() as session:
            result = await session.execute(query, params)
            rows = result.mappings().all()
            logger.info("Fetched %d pull requests from DevLake (since=%s)", len(rows), since)
            return [dict(row) for row in rows]

    async def fetch_issues(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch issues from DevLake domain table."""
        base = """
            SELECT
                i.id, i.url, i.issue_key, i.title, i.status,
                i.original_status, i.story_point, i.priority,
                i.created_date, i.resolution_date, i.lead_time_minutes,
                i.assignee_name, i.type, si.sprint_id
            FROM issues i
            LEFT JOIN sprint_issues si ON si.issue_id = i.id
        """
        if since is not None:
            query = text(base + " WHERE i.created_date > :since ORDER BY i.created_date DESC LIMIT 5000")
            params = {"since": since}
        else:
            query = text(base + " ORDER BY i.created_date DESC LIMIT 5000")
            params = {}

        async with self._session_factory() as session:
            result = await session.execute(query, params)
            rows = result.mappings().all()
            logger.info("Fetched %d issues from DevLake (since=%s)", len(rows), since)
            return [dict(row) for row in rows]

    async def fetch_deployments(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch CICD deployment commits from DevLake domain table."""
        base = """
            SELECT
                dc.id, dc.cicd_deployment_id, dc.repo_id, dc.name,
                dc.result, dc.status, dc.environment,
                dc.created_date, dc.started_date, dc.finished_date
            FROM cicd_deployment_commits dc
        """
        if since is not None:
            query = text(base + " WHERE dc.finished_date > :since ORDER BY dc.finished_date DESC NULLS LAST LIMIT 5000")
            params = {"since": since}
        else:
            query = text(base + " ORDER BY dc.finished_date DESC NULLS LAST LIMIT 5000")
            params = {}

        async with self._session_factory() as session:
            result = await session.execute(query, params)
            rows = result.mappings().all()
            logger.info("Fetched %d deployments from DevLake (since=%s)", len(rows), since)
            return [dict(row) for row in rows]

    async def fetch_sprints(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch sprints from DevLake domain table."""
        base = """
            SELECT
                s.id, s.original_board_id, s.name, s.url, s.status,
                s.started_date, s.ended_date, s.completed_date,
                COUNT(si.issue_id) AS total_issues
            FROM sprints s
            LEFT JOIN sprint_issues si ON si.sprint_id = s.id
        """
        group_order = """
            GROUP BY s.id, s.original_board_id, s.name, s.url, s.status,
                     s.started_date, s.ended_date, s.completed_date
            ORDER BY s.started_date DESC NULLS LAST
            LIMIT 500
        """
        if since is not None:
            query = text(base + " WHERE s.started_date > :since " + group_order)
            params = {"since": since}
        else:
            query = text(base + group_order)
            params = {}

        async with self._session_factory() as session:
            result = await session.execute(query, params)
            rows = result.mappings().all()
            logger.info("Fetched %d sprints from DevLake (since=%s)", len(rows), since)
            return [dict(row) for row in rows]

    async def fetch_sprint_issues(self, sprint_id: str) -> list[dict[str, Any]]:
        """Fetch all issues belonging to a specific sprint."""
        query = text("""
            SELECT
                i.id, i.issue_key, i.status, i.original_status,
                i.story_point, i.type, i.resolution_date
            FROM sprint_issues si
            JOIN issues i ON i.id = si.issue_id
            WHERE si.sprint_id = :sprint_id
        """)

        async with self._session_factory() as session:
            result = await session.execute(query, {"sprint_id": sprint_id})
            rows = result.mappings().all()
            logger.info("Fetched %d issues for sprint %s from DevLake", len(rows), sprint_id)
            return [dict(row) for row in rows]
