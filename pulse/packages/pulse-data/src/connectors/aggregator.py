"""Connector Aggregator — merges data from multiple source connectors.

Provides the same interface that DevLakeReader had, so the sync worker
can swap data sources without changing its watermark/upsert/kafka logic.

The aggregator routes each fetch call to the appropriate connector:
- pull_requests → GitHub (or GitLab in the future)
- issues, changelogs, sprints → Jira
- deployments → Jenkins (or GitHub Actions in the future)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class ConnectorAggregator:
    """Aggregates data from multiple source connectors into a unified interface.

    Drop-in replacement for DevLakeReader — the sync worker calls the same
    methods (fetch_pull_requests, fetch_issues, etc.) and gets back dicts
    in the same format the normalizer expects.

    Usage:
        aggregator = ConnectorAggregator(connectors=[github, jira, jenkins])
        prs = await aggregator.fetch_pull_requests(since=watermark)
    """

    def __init__(self, connectors: list[BaseConnector]) -> None:
        self._connectors: dict[str, BaseConnector] = {}
        for connector in connectors:
            self._connectors[connector.source_type] = connector
            logger.info("Registered connector: %s", connector.source_type)

    @property
    def connector_types(self) -> list[str]:
        """Return list of registered connector source types."""
        return list(self._connectors.keys())

    def get_connector(self, source_type: str) -> BaseConnector | None:
        """Get a specific connector by source type."""
        return self._connectors.get(source_type)

    # ------------------------------------------------------------------
    # Unified fetch methods — same signatures as DevLakeReader
    # ------------------------------------------------------------------

    async def fetch_pull_requests(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch PRs from all code-hosting connectors (GitHub, GitLab)."""
        all_prs: list[dict[str, Any]] = []
        for source in ("github", "gitlab", "azure"):
            connector = self._connectors.get(source)
            if connector:
                try:
                    prs = await connector.fetch_pull_requests(since)
                    all_prs.extend(prs)
                    logger.info("Fetched %d PRs from %s", len(prs), source)
                except Exception:
                    logger.exception("Error fetching PRs from %s", source)
        return all_prs

    async def fetch_issues(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch issues from all work-tracking connectors (Jira, GitHub Issues)."""
        all_issues: list[dict[str, Any]] = []
        for source in ("jira", "github", "azure"):
            connector = self._connectors.get(source)
            if connector:
                try:
                    issues = await connector.fetch_issues(since)
                    all_issues.extend(issues)
                    logger.info("Fetched %d issues from %s", len(issues), source)
                except Exception:
                    logger.exception("Error fetching issues from %s", source)
        return all_issues

    async def fetch_issue_changelogs(
        self, issue_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch changelogs from all work-tracking connectors.

        Optimization: if the Jira connector has cached changelogs from
        a previous fetch_issues() call (expand=changelog), use those first
        and only fetch individually for any missing issues.
        """
        all_changelogs: dict[str, list[dict[str, Any]]] = {}

        # First, drain any cached changelogs from connectors that support it
        for source_type, connector in self._connectors.items():
            if hasattr(connector, "get_cached_changelogs"):
                cached = connector.get_cached_changelogs()
                if cached:
                    all_changelogs.update(cached)
                    logger.info(
                        "Used %d cached changelogs from %s",
                        len(cached), source_type,
                    )

        # Find which issues still need changelogs fetched individually
        missing_ids = [iid for iid in issue_ids if iid not in all_changelogs]
        if not missing_ids:
            return all_changelogs

        logger.info(
            "Fetching changelogs individually for %d/%d issues",
            len(missing_ids), len(issue_ids),
        )

        # Route remaining issue_ids by their source prefix
        source_groups: dict[str, list[str]] = {}
        for issue_id in missing_ids:
            source = self._detect_source_from_id(issue_id)
            source_groups.setdefault(source, []).append(issue_id)

        for source, ids in source_groups.items():
            connector = self._connectors.get(source)
            if connector:
                try:
                    changelogs = await connector.fetch_issue_changelogs(ids)
                    all_changelogs.update(changelogs)
                except Exception:
                    logger.exception("Error fetching changelogs from %s", source)
        return all_changelogs

    async def fetch_deployments(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch deployments from all CI/CD connectors (Jenkins, GitHub Actions)."""
        all_deploys: list[dict[str, Any]] = []
        for source in ("jenkins", "github", "gitlab", "azure"):
            connector = self._connectors.get(source)
            if connector:
                try:
                    deploys = await connector.fetch_deployments(since)
                    all_deploys.extend(deploys)
                    logger.info("Fetched %d deployments from %s", len(deploys), source)
                except Exception:
                    logger.exception("Error fetching deployments from %s", source)
        return all_deploys

    async def fetch_sprints(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch sprints from work-tracking connectors (Jira)."""
        all_sprints: list[dict[str, Any]] = []
        for source in ("jira",):
            connector = self._connectors.get(source)
            if connector:
                try:
                    sprints = await connector.fetch_sprints(since)
                    all_sprints.extend(sprints)
                    logger.info("Fetched %d sprints from %s", len(sprints), source)
                except Exception:
                    logger.exception("Error fetching sprints from %s", source)
        return all_sprints

    async def fetch_sprint_issues(
        self, sprint_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch issues for a specific sprint from the appropriate connector."""
        source = self._detect_source_from_id(sprint_id)
        connector = self._connectors.get(source)
        if connector:
            return await connector.fetch_sprint_issues(sprint_id)
        # Fallback: try Jira (most common sprint source)
        connector = self._connectors.get("jira")
        if connector:
            return await connector.fetch_sprint_issues(sprint_id)
        return []

    # ------------------------------------------------------------------
    # Health check — used by Pipeline Monitor
    # ------------------------------------------------------------------

    async def test_all_connections(self) -> dict[str, dict[str, Any]]:
        """Test connectivity to all registered connectors.

        Returns:
            Dict mapping source_type -> { status, message, details }
        """
        results: dict[str, dict[str, Any]] = {}
        for source_type, connector in self._connectors.items():
            try:
                results[source_type] = await connector.test_connection()
            except Exception as e:
                results[source_type] = {
                    "status": "error",
                    "message": str(e),
                }
        return results

    async def close(self) -> None:
        """Close all connector resources."""
        for source_type, connector in self._connectors.items():
            try:
                await connector.close()
                logger.info("Closed connector: %s", source_type)
            except Exception:
                logger.exception("Error closing connector: %s", source_type)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_source_from_id(entity_id: str) -> str:
        """Detect source type from entity ID prefix (e.g., 'jira:JiraIssue:1:123')."""
        lower_id = entity_id.lower()
        if "github" in lower_id:
            return "github"
        if "jira" in lower_id:
            return "jira"
        if "jenkins" in lower_id:
            return "jenkins"
        if "gitlab" in lower_id:
            return "gitlab"
        if "azure" in lower_id:
            return "azure"
        return "unknown"
