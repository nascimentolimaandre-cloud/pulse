"""Base connector — abstract interface for all source connectors.

Each connector (GitHub, Jira, Jenkins) implements this interface.
The return format matches what normalizer.py expects so it can be
swapped in place of DevLakeReader with zero changes to normalizer logic.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract interface that every source connector must implement.

    Return format contract:
        Each fetch method returns list[dict] where the dict keys match
        the column names that normalizer.py expects (same as DevLake's
        domain table columns). This ensures the normalizer works unchanged.

    Incremental sync:
        All fetch methods accept an optional `since` datetime parameter
        for watermark-based incremental sync. When provided, only records
        updated/created after that timestamp should be returned.
    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the source identifier (e.g., 'github', 'jira', 'jenkins')."""
        ...

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Test connectivity to the source API.

        Returns:
            Dict with keys: status ('healthy'|'error'), message, details
        """
        ...

    @abstractmethod
    async def fetch_pull_requests(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch pull requests / merge requests.

        Expected dict keys (normalizer contract):
            id, base_repo_id, head_repo_id, status, title, url,
            author_name, created_date, merged_date, closed_date,
            merge_commit_sha, base_ref, head_ref, additions, deletions

        Optional enrichment keys (prefixed with underscore):
            _files_changed, _reviewers, _first_review_at, _approved_at
        """
        ...

    @abstractmethod
    async def fetch_issues(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch issues / work items.

        Expected dict keys (normalizer contract):
            id, url, issue_key, title, status, original_status,
            story_point, priority, created_date, updated_date,
            resolution_date, lead_time_minutes, assignee_name,
            type, sprint_id
        """
        ...

    @abstractmethod
    async def fetch_issue_changelogs(
        self, issue_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch status transition changelogs for a batch of issues.

        Returns:
            Dict mapping issue_id -> list of transition dicts.
            Each transition dict has keys:
                issue_id, from_status, to_status, created_date
        """
        ...

    @abstractmethod
    async def fetch_deployments(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch deployment / build records.

        Expected dict keys (normalizer contract):
            id, cicd_deployment_id, repo_id, name, result, status,
            environment, created_date, started_date, finished_date
        """
        ...

    @abstractmethod
    async def fetch_sprints(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch sprint records.

        Expected dict keys (normalizer contract):
            id, original_board_id, name, url, status,
            started_date, ended_date, completed_date, total_issues
        """
        ...

    @abstractmethod
    async def fetch_sprint_issues(
        self, sprint_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch all issues belonging to a specific sprint.

        Expected dict keys (normalizer contract):
            id, issue_key, status, original_status,
            story_point, type, resolution_date
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources (HTTP sessions, connections, etc)."""
        ...

    # ------------------------------------------------------------------
    # Default no-op implementations for connectors that don't support
    # all entity types (e.g., Jenkins doesn't have PRs or issues)
    # ------------------------------------------------------------------

    async def _not_supported(self, entity: str) -> list[dict[str, Any]]:
        """Return empty list for unsupported entity types."""
        logger.debug("%s connector does not support %s", self.source_type, entity)
        return []
