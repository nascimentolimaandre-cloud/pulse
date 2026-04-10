"""Unit tests for ConnectorAggregator.

Verifies routing, aggregation, fallback logic, cached-changelog optimisation,
error isolation, and the _detect_source_from_id helper without importing any
real connector implementation. All connectors are AsyncMock objects that
satisfy the BaseConnector interface.

Key behaviours under test:
- Connectors are registered by their source_type.
- Each fetch_* method routes to the correct connector(s) and merges results.
- fetch_issue_changelogs drains get_cached_changelogs() before fetching individually.
- A connector that raises during fetch does not prevent other connectors from running.
- test_all_connections and close() iterate over every registered connector.
- _detect_source_from_id correctly maps ID prefixes to source names.
- An empty aggregator (no connectors) returns empty lists / dicts gracefully.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.aggregator import ConnectorAggregator


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_connector(source_type: str, **method_returns: Any) -> MagicMock:
    """Build a mock connector whose source_type property is fixed.

    Pass keyword arguments matching connector method names to set return values.
    For example: _make_connector("github", fetch_pull_requests=[{"id": 1}])
    """
    connector = MagicMock()
    connector.source_type = source_type

    # Async methods with default empty-list/dict returns
    defaults: dict[str, Any] = {
        "fetch_pull_requests": [],
        "fetch_issues": [],
        "fetch_issue_changelogs": {},
        "fetch_deployments": [],
        "fetch_sprints": [],
        "fetch_sprint_issues": [],
        "test_connection": {"status": "healthy", "message": "ok", "details": {}},
        "close": None,
    }
    defaults.update(method_returns)

    for method_name, return_value in defaults.items():
        mock_method = AsyncMock(return_value=return_value)
        setattr(connector, method_name, mock_method)

    return connector


_NOW = datetime(2024, 2, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestConnectorAggregator:
    """Tests for ConnectorAggregator routing, aggregation, and lifecycle behaviour."""

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def test_registration_maps_connector_by_source_type(self) -> None:
        """Connectors are stored keyed by their source_type after construction."""
        github = _make_connector("github")
        jira = _make_connector("jira")
        jenkins = _make_connector("jenkins")

        aggregator = ConnectorAggregator(connectors=[github, jira, jenkins])

        assert set(aggregator.connector_types) == {"github", "jira", "jenkins"}
        assert aggregator.get_connector("github") is github
        assert aggregator.get_connector("jira") is jira
        assert aggregator.get_connector("jenkins") is jenkins

    def test_get_connector_returns_none_for_unregistered_type(self) -> None:
        """get_connector returns None when the source type is not registered."""
        aggregator = ConnectorAggregator(connectors=[])
        assert aggregator.get_connector("gitlab") is None

    # ------------------------------------------------------------------
    # fetch_pull_requests
    # ------------------------------------------------------------------

    async def test_fetch_pull_requests_routes_to_github_connector(self) -> None:
        """fetch_pull_requests collects PRs from the github connector."""
        prs = [{"id": "PR-1"}, {"id": "PR-2"}]
        github = _make_connector("github", fetch_pull_requests=prs)
        aggregator = ConnectorAggregator(connectors=[github])

        result = await aggregator.fetch_pull_requests(since=_NOW)

        assert result == prs
        github.fetch_pull_requests.assert_called_once_with(_NOW)

    async def test_fetch_pull_requests_aggregates_github_and_gitlab(self) -> None:
        """fetch_pull_requests aggregates PRs from both github and gitlab connectors."""
        github_prs = [{"id": "GH-1"}]
        gitlab_prs = [{"id": "GL-1"}, {"id": "GL-2"}]
        github = _make_connector("github", fetch_pull_requests=github_prs)
        gitlab = _make_connector("gitlab", fetch_pull_requests=gitlab_prs)

        aggregator = ConnectorAggregator(connectors=[github, gitlab])
        result = await aggregator.fetch_pull_requests()

        assert {"id": "GH-1"} in result
        assert {"id": "GL-1"} in result
        assert len(result) == 3

    async def test_fetch_pull_requests_returns_empty_with_no_connectors(self) -> None:
        """fetch_pull_requests returns an empty list when no connectors are registered."""
        aggregator = ConnectorAggregator(connectors=[])
        result = await aggregator.fetch_pull_requests()
        assert result == []

    # ------------------------------------------------------------------
    # fetch_issues
    # ------------------------------------------------------------------

    async def test_fetch_issues_routes_to_jira_connector(self) -> None:
        """fetch_issues collects issues from the jira connector."""
        issues = [{"id": "PROJ-1"}, {"id": "PROJ-2"}]
        jira = _make_connector("jira", fetch_issues=issues)

        aggregator = ConnectorAggregator(connectors=[jira])
        result = await aggregator.fetch_issues(since=_NOW)

        assert result == issues
        jira.fetch_issues.assert_called_once_with(_NOW)

    async def test_fetch_issues_aggregates_across_jira_and_github(self) -> None:
        """fetch_issues merges issues from jira and github when both are registered."""
        jira_issues = [{"id": "JIRA-1"}]
        github_issues = [{"id": "GH-ISSUE-1"}]
        jira = _make_connector("jira", fetch_issues=jira_issues)
        github = _make_connector("github", fetch_issues=github_issues)

        aggregator = ConnectorAggregator(connectors=[jira, github])
        result = await aggregator.fetch_issues()

        assert len(result) == 2

    # ------------------------------------------------------------------
    # fetch_deployments
    # ------------------------------------------------------------------

    async def test_fetch_deployments_routes_to_jenkins_connector(self) -> None:
        """fetch_deployments collects deployments from the jenkins connector."""
        deploys = [{"id": "BUILD-100"}, {"id": "BUILD-101"}]
        jenkins = _make_connector("jenkins", fetch_deployments=deploys)

        aggregator = ConnectorAggregator(connectors=[jenkins])
        result = await aggregator.fetch_deployments(since=_NOW)

        assert result == deploys
        jenkins.fetch_deployments.assert_called_once_with(_NOW)

    async def test_fetch_deployments_aggregates_jenkins_and_github(self) -> None:
        """fetch_deployments merges deployments from jenkins and github Actions."""
        jenkins_deploys = [{"id": "J-1"}]
        github_deploys = [{"id": "GHA-1"}]
        jenkins = _make_connector("jenkins", fetch_deployments=jenkins_deploys)
        github = _make_connector("github", fetch_deployments=github_deploys)

        aggregator = ConnectorAggregator(connectors=[jenkins, github])
        result = await aggregator.fetch_deployments()

        assert len(result) == 2

    # ------------------------------------------------------------------
    # fetch_sprints
    # ------------------------------------------------------------------

    async def test_fetch_sprints_routes_to_jira_connector(self) -> None:
        """fetch_sprints collects sprints exclusively from the jira connector."""
        sprints = [{"id": "SP-1"}, {"id": "SP-2"}]
        jira = _make_connector("jira", fetch_sprints=sprints)
        github = _make_connector("github")  # github doesn't have sprints

        aggregator = ConnectorAggregator(connectors=[jira, github])
        result = await aggregator.fetch_sprints(since=_NOW)

        assert result == sprints
        jira.fetch_sprints.assert_called_once_with(_NOW)
        github.fetch_sprints.assert_not_called()

    # ------------------------------------------------------------------
    # fetch_sprint_issues
    # ------------------------------------------------------------------

    async def test_fetch_sprint_issues_detects_jira_prefix_and_routes(self) -> None:
        """fetch_sprint_issues detects 'jira' in the sprint ID and routes to jira."""
        sprint_issues = [{"id": "PROJ-1"}, {"id": "PROJ-2"}]
        jira = _make_connector("jira", fetch_sprint_issues=sprint_issues)

        aggregator = ConnectorAggregator(connectors=[jira])
        result = await aggregator.fetch_sprint_issues("jira:Sprint:1:42")

        assert result == sprint_issues
        jira.fetch_sprint_issues.assert_called_once_with("jira:Sprint:1:42")

    async def test_fetch_sprint_issues_falls_back_to_jira_for_unknown_prefix(self) -> None:
        """fetch_sprint_issues falls back to the jira connector for unknown prefixes."""
        sprint_issues = [{"id": "PROJ-5"}]
        jira = _make_connector("jira", fetch_sprint_issues=sprint_issues)

        aggregator = ConnectorAggregator(connectors=[jira])
        result = await aggregator.fetch_sprint_issues("unknown:Sprint:9999")

        assert result == sprint_issues

    async def test_fetch_sprint_issues_returns_empty_when_no_suitable_connector(self) -> None:
        """fetch_sprint_issues returns [] when neither the detected nor jira connector exists."""
        aggregator = ConnectorAggregator(connectors=[])
        result = await aggregator.fetch_sprint_issues("jira:Sprint:1:42")
        assert result == []

    # ------------------------------------------------------------------
    # fetch_issue_changelogs — caching
    # ------------------------------------------------------------------

    async def test_fetch_issue_changelogs_drains_cached_changelogs_first(self) -> None:
        """When get_cached_changelogs() provides all requested IDs no individual fetch occurs."""
        cached = {
            "JIRA-1": [{"from_status": "To Do", "to_status": "In Progress"}],
            "JIRA-2": [{"from_status": "In Progress", "to_status": "Done"}],
        }
        jira = _make_connector("jira")
        jira.get_cached_changelogs = MagicMock(return_value=cached)

        aggregator = ConnectorAggregator(connectors=[jira])
        result = await aggregator.fetch_issue_changelogs(["JIRA-1", "JIRA-2"])

        assert result == cached
        # fetch_issue_changelogs (the connector method) must NOT have been called
        jira.fetch_issue_changelogs.assert_not_called()

    async def test_fetch_issue_changelogs_fetches_individually_when_no_cache(self) -> None:
        """When no get_cached_changelogs attribute exists each missing ID is fetched directly."""
        individual_result = {
            "JIRA-1": [{"from_status": "To Do", "to_status": "Done"}],
        }
        jira = _make_connector("jira", fetch_issue_changelogs=individual_result)
        # No get_cached_changelogs attribute → hasattr() check in aggregator returns False

        aggregator = ConnectorAggregator(connectors=[jira])
        result = await aggregator.fetch_issue_changelogs(["JIRA-1"])

        assert result == individual_result
        jira.fetch_issue_changelogs.assert_called_once()

    async def test_fetch_issue_changelogs_mixed_cached_and_individual(self) -> None:
        """Cached IDs are used directly; missing IDs are fetched individually via connector."""
        cached = {"JIRA-1": [{"from_status": "To Do", "to_status": "In Progress"}]}
        individual_result = {"JIRA-2": [{"from_status": "In Progress", "to_status": "Done"}]}

        jira = _make_connector("jira", fetch_issue_changelogs=individual_result)
        jira.get_cached_changelogs = MagicMock(return_value=cached)

        aggregator = ConnectorAggregator(connectors=[jira])
        result = await aggregator.fetch_issue_changelogs(["JIRA-1", "JIRA-2"])

        assert "JIRA-1" in result
        assert "JIRA-2" in result
        # The connector's fetch_issue_changelogs should only be called for JIRA-2
        jira.fetch_issue_changelogs.assert_called_once_with(["JIRA-2"])

    async def test_fetch_issue_changelogs_empty_issue_ids_returns_empty(self) -> None:
        """fetch_issue_changelogs with an empty list returns an empty dict immediately."""
        jira = _make_connector("jira")
        jira.get_cached_changelogs = MagicMock(return_value={})

        aggregator = ConnectorAggregator(connectors=[jira])
        result = await aggregator.fetch_issue_changelogs([])

        assert result == {}
        jira.fetch_issue_changelogs.assert_not_called()

    # ------------------------------------------------------------------
    # Error isolation
    # ------------------------------------------------------------------

    async def test_fetch_pull_requests_error_in_one_connector_does_not_prevent_others(
        self,
    ) -> None:
        """If one connector raises during fetch_pull_requests, other connectors still run."""
        github = _make_connector("github")
        github.fetch_pull_requests = AsyncMock(side_effect=RuntimeError("GitHub is down"))
        gitlab_prs = [{"id": "GL-1"}]
        gitlab = _make_connector("gitlab", fetch_pull_requests=gitlab_prs)

        aggregator = ConnectorAggregator(connectors=[github, gitlab])
        result = await aggregator.fetch_pull_requests()

        # gitlab results must still arrive
        assert result == gitlab_prs

    async def test_fetch_issues_error_in_one_connector_does_not_prevent_others(self) -> None:
        """If jira raises during fetch_issues, github issues are still returned."""
        jira = _make_connector("jira")
        jira.fetch_issues = AsyncMock(side_effect=ConnectionError("Jira unreachable"))
        github_issues = [{"id": "GH-ISSUE-9"}]
        github = _make_connector("github", fetch_issues=github_issues)

        aggregator = ConnectorAggregator(connectors=[jira, github])
        result = await aggregator.fetch_issues()

        assert result == github_issues

    async def test_fetch_deployments_error_in_jenkins_does_not_block_github(self) -> None:
        """If jenkins raises during fetch_deployments, github deployments still return."""
        jenkins = _make_connector("jenkins")
        jenkins.fetch_deployments = AsyncMock(side_effect=TimeoutError("Jenkins timeout"))
        github_deploys = [{"id": "GHA-DEPLOY-1"}]
        github = _make_connector("github", fetch_deployments=github_deploys)

        aggregator = ConnectorAggregator(connectors=[jenkins, github])
        result = await aggregator.fetch_deployments()

        assert result == github_deploys

    # ------------------------------------------------------------------
    # test_all_connections
    # ------------------------------------------------------------------

    async def test_all_connections_calls_test_connection_on_each_connector(self) -> None:
        """test_all_connections returns a health dict for every registered connector."""
        github = _make_connector(
            "github",
            test_connection={"status": "healthy", "message": "ok", "details": {}},
        )
        jira = _make_connector(
            "jira",
            test_connection={"status": "healthy", "message": "connected", "details": {}},
        )

        aggregator = ConnectorAggregator(connectors=[github, jira])
        results = await aggregator.test_all_connections()

        assert set(results.keys()) == {"github", "jira"}
        assert results["github"]["status"] == "healthy"
        assert results["jira"]["status"] == "healthy"
        github.test_connection.assert_called_once()
        jira.test_connection.assert_called_once()

    async def test_all_connections_captures_error_without_raising(self) -> None:
        """test_all_connections catches connector exceptions and records them in the result."""
        github = _make_connector("github")
        github.test_connection = AsyncMock(side_effect=ConnectionError("refused"))

        aggregator = ConnectorAggregator(connectors=[github])
        results = await aggregator.test_all_connections()

        assert results["github"]["status"] == "error"
        assert "refused" in results["github"]["message"]

    # ------------------------------------------------------------------
    # close
    # ------------------------------------------------------------------

    async def test_close_calls_close_on_all_connectors(self) -> None:
        """close() calls close() on every registered connector."""
        github = _make_connector("github")
        jira = _make_connector("jira")
        jenkins = _make_connector("jenkins")

        aggregator = ConnectorAggregator(connectors=[github, jira, jenkins])
        await aggregator.close()

        github.close.assert_called_once()
        jira.close.assert_called_once()
        jenkins.close.assert_called_once()

    async def test_close_does_not_raise_when_connector_close_fails(self) -> None:
        """close() swallows exceptions from individual connectors so all are attempted."""
        github = _make_connector("github")
        github.close = AsyncMock(side_effect=RuntimeError("close failed"))
        jira = _make_connector("jira")

        aggregator = ConnectorAggregator(connectors=[github, jira])
        # Should not raise
        await aggregator.close()

        jira.close.assert_called_once()

    # ------------------------------------------------------------------
    # _detect_source_from_id
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("entity_id", "expected_source"),
        [
            ("jira:JiraIssue:1:123", "jira"),
            ("JIRA:Sprint:5:42", "jira"),        # case-insensitive
            ("github:GithubPullRequest:1:99", "github"),
            ("GITHUB:GithubRepo:2:7", "github"),  # case-insensitive
            ("jenkins:CICDDeployment:1:500", "jenkins"),
            ("Jenkins:Build:1:200", "jenkins"),   # case-insensitive
            ("gitlab:MergeRequest:3:88", "gitlab"),
            ("azure:WorkItem:1:77", "azure"),
            ("unknown:Entity:0:1", "unknown"),
            ("plain-id-without-prefix", "unknown"),
        ],
    )
    def test_detect_source_from_id(self, entity_id: str, expected_source: str) -> None:
        """_detect_source_from_id maps ID prefixes to the correct source type."""
        result = ConnectorAggregator._detect_source_from_id(entity_id)
        assert result == expected_source

    # ------------------------------------------------------------------
    # No connectors — edge cases
    # ------------------------------------------------------------------

    async def test_no_connectors_fetch_pull_requests_returns_empty(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        assert await aggregator.fetch_pull_requests() == []

    async def test_no_connectors_fetch_issues_returns_empty(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        assert await aggregator.fetch_issues() == []

    async def test_no_connectors_fetch_deployments_returns_empty(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        assert await aggregator.fetch_deployments() == []

    async def test_no_connectors_fetch_sprints_returns_empty(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        assert await aggregator.fetch_sprints() == []

    async def test_no_connectors_fetch_sprint_issues_returns_empty(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        assert await aggregator.fetch_sprint_issues("jira:Sprint:1:1") == []

    async def test_no_connectors_test_all_connections_returns_empty_dict(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        assert await aggregator.test_all_connections() == {}

    async def test_no_connectors_close_does_not_raise(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        await aggregator.close()  # Should complete without error

    async def test_no_connectors_fetch_issue_changelogs_returns_empty(self) -> None:
        aggregator = ConnectorAggregator(connectors=[])
        result = await aggregator.fetch_issue_changelogs(["JIRA-1", "JIRA-2"])
        assert result == {}
