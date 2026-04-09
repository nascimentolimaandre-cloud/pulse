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
        """Fetch issues from DevLake domain table.

        Uses updated_date for incremental sync watermark instead of created_date,
        because Jira issues may have been created long ago but only recently
        ingested/updated in DevLake. Using created_date would miss old issues
        that were just collected for the first time.
        """
        base = """
            SELECT
                i.id, i.url, i.issue_key, i.title, i.status,
                i.original_status, i.story_point, i.priority,
                i.created_date, i.updated_date, i.resolution_date,
                i.lead_time_minutes,
                i.assignee_name, i.type, si.sprint_id
            FROM issues i
            LEFT JOIN sprint_issues si ON si.issue_id = i.id
        """
        if since is not None:
            query = text(base + " WHERE i.updated_date > :since ORDER BY i.updated_date DESC LIMIT 5000")
            params = {"since": since}
        else:
            query = text(base + " ORDER BY i.updated_date DESC LIMIT 5000")
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

    async def fetch_issue_changelogs(
        self, issue_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch status transition changelogs for a batch of issues.

        Queries DevLake's issue_changelogs table for status field changes.
        Returns a dict mapping issue_id -> list of status transitions,
        sorted chronologically.

        DevLake populates this table from Jira's changelog API.
        For GitHub issues (which lack changelogs), this returns empty lists.
        """
        if not issue_ids:
            return {}

        query = text("""
            SELECT
                ic.issue_id,
                ic.original_from_value AS from_status,
                ic.original_to_value AS to_status,
                ic.created_date
            FROM issue_changelogs ic
            WHERE ic.issue_id = ANY(:issue_ids)
              AND LOWER(ic.field_name) = 'status'
            ORDER BY ic.issue_id, ic.created_date ASC
        """)

        try:
            async with self._session_factory() as session:
                result = await session.execute(query, {"issue_ids": issue_ids})
                rows = result.mappings().all()
        except Exception:
            # Table may not exist if Jira plugin is not yet configured in DevLake
            logger.warning(
                "Could not fetch issue_changelogs (table may not exist yet) — "
                "returning empty transitions"
            )
            return {}

        changelogs: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            issue_id = str(row["issue_id"])
            if issue_id not in changelogs:
                changelogs[issue_id] = []
            changelogs[issue_id].append(dict(row))

        logger.info(
            "Fetched changelogs for %d issues (%d total transitions)",
            len(changelogs),
            len(rows),
        )
        return changelogs

    # ------------------------------------------------------------------
    # Count helpers — used by Pipeline Monitor for source/target comparison
    # ------------------------------------------------------------------

    async def count_pull_requests(self) -> int:
        """Count total pull requests in DevLake DB."""
        async with self._engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM pull_requests"))
            return result.scalar() or 0

    async def count_issues(self) -> int:
        """Count total issues in DevLake DB."""
        async with self._engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM issues"))
            return result.scalar() or 0

    async def count_deployments(self) -> int:
        """Count total deployment commits in DevLake DB."""
        async with self._engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM cicd_deployment_commits"))
            return result.scalar() or 0

    async def count_sprints(self) -> int:
        """Count total sprints in DevLake DB."""
        async with self._engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM sprints"))
            return result.scalar() or 0

    async def count_all(self) -> dict[str, int]:
        """Count all entities in DevLake DB for comparison with PULSE DB."""
        return {
            "pull_requests": await self.count_pull_requests(),
            "issues": await self.count_issues(),
            "deployments": await self.count_deployments(),
            "sprints": await self.count_sprints(),
        }

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
