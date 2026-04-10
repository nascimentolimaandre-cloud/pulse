"""Unit tests for JiraConnector.

Tests are pure unit tests — no real HTTP calls are made.
ResilientHTTPClient is patched at the module level so every test is isolated
and deterministic.

Coverage targets:
- fetch_issues: JQL construction, POST body format, pagination, watermark
- _extract_changelogs: status transitions, empty changelog, non-status fields
- get_cached_changelogs: returns cache then clears it
- fetch_issue_changelogs: individual GET calls for issues without inline changelog
- _discover_boards: scrum-only filter, caching
- fetch_sprints: delegates to _discover_boards + _fetch_board_sprints
- _fetch_board_sprints: offset pagination, 400 handling, watermark filter
- fetch_sprint_issues: offset pagination, mapping
- _map_issue: all fields, story points variants, sprint_id extraction
- _map_sprint_issue: all fields, story points variants
- _map_sprint: state mapping (active/closed/future)
- test_connection: healthy response and error response
- source_type, close, fetch_pull_requests, fetch_deployments
- _extract_key_from_id: parts[3] extraction
- _extract_numeric_id: parts[3] extraction
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.jira_connector import JiraConnector, SEARCH_FIELDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "https://test.atlassian.net"
EMAIL = "svc@example.com"
TOKEN = "secret-token"
PROJECTS = ["BACK", "DESC", "ENO"]
CONN_ID = 1


def _make_connector(projects: list[str] | None = None) -> JiraConnector:
    """Instantiate JiraConnector with test credentials, bypassing settings."""
    return JiraConnector(
        base_url=BASE_URL,
        email=EMAIL,
        api_token=TOKEN,
        projects=projects if projects is not None else PROJECTS,
        connection_id=CONN_ID,
    )


def _jira_issue(
    jira_id: str = "10001",
    key: str = "BACK-1",
    summary: str = "Fix login bug",
    status: str = "In Progress",
    issue_type: str = "Story",
    priority: str = "High",
    assignee: str | None = "Alice",
    created: str = "2024-01-10T09:00:00.000+0000",
    updated: str = "2024-01-11T15:30:00.000+0000",
    resolution_date: str | None = None,
    story_points: float | None = 5.0,
    sprint: dict | None = None,
    changelog_histories: list[dict] | None = None,
) -> dict:
    """Build a realistic Jira REST API v3 issue payload."""
    fields: dict = {
        "summary": summary,
        "status": {"name": status, "id": "3"},
        "issuetype": {"name": issue_type},
        "priority": {"name": priority},
        "assignee": {"displayName": assignee} if assignee else None,
        "created": created,
        "updated": updated,
        "resolutiondate": resolution_date,
        "story_points": story_points,
        "customfield_10028": None,
        "customfield_10016": None,
        "sprint": sprint,
        "parent": None,
        "labels": [],
        "components": [],
    }

    issue: dict = {
        "id": jira_id,
        "key": key,
        "fields": fields,
    }

    if changelog_histories is not None:
        issue["changelog"] = {"histories": changelog_histories}
    else:
        issue["changelog"] = {"histories": []}

    return issue


def _sprint_payload(
    sprint_id: int = 42,
    name: str = "Sprint 5",
    state: str = "active",
    start_date: str = "2024-01-08T09:00:00.000Z",
    end_date: str = "2024-01-22T18:00:00.000Z",
    complete_date: str | None = None,
) -> dict:
    """Build a Jira Agile sprint payload."""
    return {
        "id": sprint_id,
        "name": name,
        "state": state,
        "startDate": start_date,
        "endDate": end_date,
        "completeDate": complete_date,
        "originBoardId": 10,
    }


def _changelog_history(
    created: str = "2024-01-10T10:00:00.000+0000",
    from_status: str = "To Do",
    to_status: str = "In Progress",
    field: str = "status",
) -> dict:
    """Build a Jira changelog history entry."""
    return {
        "created": created,
        "items": [
            {
                "field": field,
                "fieldtype": "jira",
                "fromString": from_status,
                "toString": to_status,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Main test class
# ---------------------------------------------------------------------------


class TestJiraConnector:

    # -----------------------------------------------------------------------
    # Constructor & lifecycle
    # -----------------------------------------------------------------------

    def test_source_type_returns_jira(self) -> None:
        connector = _make_connector()
        assert connector.source_type == "jira"

    def test_raises_if_no_base_url_or_token(self) -> None:
        """Constructor must fail fast when required credentials are absent."""
        with pytest.raises(ValueError, match="JIRA_BASE_URL"):
            JiraConnector(base_url="", email=EMAIL, api_token="token", projects=PROJECTS)

    def test_raises_if_no_api_token(self) -> None:
        with pytest.raises(ValueError, match="JIRA_API_TOKEN"):
            JiraConnector(base_url=BASE_URL, email=EMAIL, api_token="", projects=PROJECTS)

    @pytest.mark.asyncio
    async def test_close_delegates_to_http_client(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        await connector.close()
        connector._client.close.assert_awaited_once()

    # -----------------------------------------------------------------------
    # test_connection
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_connection_returns_healthy_with_display_name(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._client.get.return_value = {
            "displayName": "Service Account",
            "emailAddress": "svc@example.com",
            "accountId": "abc123",
        }

        result = await connector.test_connection()

        assert result["status"] == "healthy"
        assert "Service Account" in result["message"]
        assert result["details"]["email"] == "svc@example.com"
        assert result["details"]["account_id"] == "abc123"
        assert result["details"]["projects"] == PROJECTS

    @pytest.mark.asyncio
    async def test_connection_returns_error_on_exception(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._client.get.side_effect = ConnectionError("timeout")

        result = await connector.test_connection()

        assert result["status"] == "error"
        assert "timeout" in result["message"]

    @pytest.mark.asyncio
    async def test_connection_calls_myself_endpoint(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._client.get.return_value = {"displayName": "Bot"}

        await connector.test_connection()

        connector._client.get.assert_awaited_once_with("/rest/api/3/myself")

    # -----------------------------------------------------------------------
    # fetch_pull_requests / fetch_deployments — not supported
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_returns_empty_list(self) -> None:
        connector = _make_connector()
        result = await connector.fetch_pull_requests()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_deployments_returns_empty_list(self) -> None:
        connector = _make_connector()
        result = await connector.fetch_deployments()
        assert result == []

    # -----------------------------------------------------------------------
    # fetch_issues — JQL construction
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_issues_no_projects_returns_empty(self) -> None:
        connector = _make_connector(projects=[])
        connector._client = AsyncMock()

        result = await connector.fetch_issues()

        assert result == []
        connector._client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_issues_uses_post_search_jql_endpoint(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": [], "nextPageToken": None}

        await connector.fetch_issues()

        connector._client.post.assert_awaited_once()
        call_args = connector._client.post.call_args
        assert call_args[0][0] == "/rest/api/3/search/jql"

    @pytest.mark.asyncio
    async def test_fetch_issues_projects_are_quoted_in_jql(self) -> None:
        """Project keys like DESC are JQL reserved words — must be quoted."""
        connector = _make_connector(projects=["BACK", "DESC", "ENO"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        jql = body["jql"]
        assert '"BACK"' in jql
        assert '"DESC"' in jql
        assert '"ENO"' in jql

    @pytest.mark.asyncio
    async def test_fetch_issues_jql_uses_in_clause(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        assert "project IN" in body["jql"]

    @pytest.mark.asyncio
    async def test_fetch_issues_without_since_has_no_updated_clause(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues(since=None)

        body = connector._client.post.call_args[1]["json_body"]
        assert "updated >=" not in body["jql"]

    @pytest.mark.asyncio
    async def test_fetch_issues_with_since_adds_updated_clause(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}
        since = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)

        await connector.fetch_issues(since=since)

        body = connector._client.post.call_args[1]["json_body"]
        assert 'updated >= "2024-03-15 10:00"' in body["jql"]

    @pytest.mark.asyncio
    async def test_fetch_issues_jql_orders_by_updated_desc(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        assert "ORDER BY updated DESC" in body["jql"]

    # -----------------------------------------------------------------------
    # fetch_issues — POST body format
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_issues_body_has_max_results_100(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        assert body["maxResults"] == 100

    @pytest.mark.asyncio
    async def test_fetch_issues_body_expand_is_string_not_list(self) -> None:
        """Jira v3 search/jql requires expand as a string, not an array."""
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        assert body["expand"] == "changelog"
        assert isinstance(body["expand"], str), "expand must be str, not list"

    @pytest.mark.asyncio
    async def test_fetch_issues_body_fields_is_list(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        assert isinstance(body["fields"], list)
        # Spot-check expected fields from SEARCH_FIELDS constant
        assert "summary" in body["fields"]
        assert "status" in body["fields"]
        assert "customfield_10028" in body["fields"]

    @pytest.mark.asyncio
    async def test_fetch_issues_fields_equal_search_fields_constant(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        assert body["fields"] == SEARCH_FIELDS

    @pytest.mark.asyncio
    async def test_fetch_issues_first_page_has_no_next_page_token(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {"issues": []}

        await connector.fetch_issues()

        body = connector._client.post.call_args[1]["json_body"]
        assert "nextPageToken" not in body

    # -----------------------------------------------------------------------
    # fetch_issues — pagination
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_issues_pagination_follows_next_page_token(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()

        issue1 = _jira_issue(jira_id="101", key="BACK-1")
        issue2 = _jira_issue(jira_id="102", key="BACK-2")

        connector._client.post.side_effect = [
            {"issues": [issue1], "nextPageToken": "cursor-abc"},
            {"issues": [issue2], "nextPageToken": None},
        ]

        result = await connector.fetch_issues()

        assert connector._client.post.await_count == 2
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_issues_pagination_sends_token_in_body(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()

        issue1 = _jira_issue(jira_id="101", key="BACK-1")

        connector._client.post.side_effect = [
            {"issues": [issue1], "nextPageToken": "cursor-xyz"},
            {"issues": []},
        ]

        await connector.fetch_issues()

        second_call_body = connector._client.post.call_args_list[1][1]["json_body"]
        assert second_call_body["nextPageToken"] == "cursor-xyz"

    @pytest.mark.asyncio
    async def test_fetch_issues_stops_when_issues_empty_even_with_token(self) -> None:
        """Guard: if issues array is empty, stop even if nextPageToken is present."""
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {
            "issues": [],
            "nextPageToken": "should-not-follow",
        }

        result = await connector.fetch_issues()

        assert connector._client.post.await_count == 1
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_issues_returns_all_mapped_issues(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()

        issues = [_jira_issue(jira_id=str(i), key=f"BACK-{i}") for i in range(1, 4)]
        connector._client.post.return_value = {"issues": issues}

        result = await connector.fetch_issues()

        assert len(result) == 3
        # All results are mapped dicts (not raw Jira payloads)
        for item in result:
            assert "id" in item
            assert item["id"].startswith("jira:JiraIssue:")

    # -----------------------------------------------------------------------
    # _map_issue
    # -----------------------------------------------------------------------

    def test_map_issue_builds_internal_id(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(jira_id="12345", key="BACK-99")

        result = connector._map_issue(issue)

        assert result["id"] == f"jira:JiraIssue:{CONN_ID}:12345"

    def test_map_issue_builds_browse_url(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(key="BACK-99")

        result = connector._map_issue(issue)

        assert result["url"] == f"{BASE_URL}/browse/BACK-99"

    def test_map_issue_preserves_issue_key(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue(key="DESC-42"))
        assert result["issue_key"] == "DESC-42"

    def test_map_issue_maps_summary_to_title(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue(summary="Fix the login bug"))
        assert result["title"] == "Fix the login bug"

    def test_map_issue_maps_status_name(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue(status="Code Review"))
        assert result["status"] == "Code Review"
        assert result["original_status"] == "Code Review"

    def test_map_issue_maps_priority(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue(priority="Critical"))
        assert result["priority"] == "Critical"

    def test_map_issue_maps_dates(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(
            created="2024-01-10T09:00:00.000+0000",
            updated="2024-01-11T15:30:00.000+0000",
            resolution_date="2024-01-12T16:00:00.000+0000",
        )
        result = connector._map_issue(issue)
        assert result["created_date"] == "2024-01-10T09:00:00.000+0000"
        assert result["updated_date"] == "2024-01-11T15:30:00.000+0000"
        assert result["resolution_date"] == "2024-01-12T16:00:00.000+0000"

    def test_map_issue_maps_assignee_display_name(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue(assignee="Alice Smith"))
        assert result["assignee_name"] == "Alice Smith"

    def test_map_issue_none_assignee_returns_none(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue(assignee=None))
        assert result["assignee_name"] is None

    def test_map_issue_maps_issue_type(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue(issue_type="Bug"))
        assert result["type"] == "Bug"

    def test_map_issue_missing_issuetype_defaults_to_task(self) -> None:
        connector = _make_connector()
        issue = _jira_issue()
        issue["fields"]["issuetype"] = None
        result = connector._map_issue(issue)
        assert result["type"] == "Task"

    def test_map_issue_lead_time_minutes_is_none(self) -> None:
        """Lead time is calculated by PULSE normalizer, not by connector."""
        connector = _make_connector()
        result = connector._map_issue(_jira_issue())
        assert result["lead_time_minutes"] is None

    # -----------------------------------------------------------------------
    # _map_issue — story points
    # -----------------------------------------------------------------------

    def test_map_issue_story_points_from_story_points_field(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(story_points=8.0)
        result = connector._map_issue(issue)
        assert result["story_point"] == 8.0

    def test_map_issue_story_points_fallback_customfield_10028(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(story_points=None)
        issue["fields"]["customfield_10028"] = 3.0
        result = connector._map_issue(issue)
        assert result["story_point"] == 3.0

    def test_map_issue_story_points_fallback_customfield_10016(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(story_points=None)
        issue["fields"]["customfield_10028"] = None
        issue["fields"]["customfield_10016"] = 13.0
        result = connector._map_issue(issue)
        assert result["story_point"] == 13.0

    def test_map_issue_story_points_none_when_all_missing(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(story_points=None)
        issue["fields"]["customfield_10028"] = None
        issue["fields"]["customfield_10016"] = None
        result = connector._map_issue(issue)
        assert result["story_point"] is None

    def test_map_issue_story_points_prefers_story_points_over_customfield(self) -> None:
        """Primary field wins over fallbacks."""
        connector = _make_connector()
        issue = _jira_issue(story_points=5.0)
        issue["fields"]["customfield_10028"] = 99.0
        result = connector._map_issue(issue)
        assert result["story_point"] == 5.0

    # -----------------------------------------------------------------------
    # _map_issue — sprint ID extraction
    # -----------------------------------------------------------------------

    def test_map_issue_sprint_id_extracted_when_sprint_present(self) -> None:
        connector = _make_connector()
        sprint_field = {"id": 42, "name": "Sprint 5", "state": "active"}
        issue = _jira_issue(sprint=sprint_field)

        result = connector._map_issue(issue)

        assert result["sprint_id"] == f"jira:JiraSprint:{CONN_ID}:42"

    def test_map_issue_sprint_id_is_none_when_sprint_absent(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(sprint=None)
        result = connector._map_issue(issue)
        assert result["sprint_id"] is None

    def test_map_issue_sprint_id_is_none_when_sprint_field_is_not_dict(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(sprint=None)
        issue["fields"]["sprint"] = "not-a-dict"
        result = connector._map_issue(issue)
        assert result["sprint_id"] is None

    def test_map_issue_sprint_id_is_none_when_sprint_has_no_id(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(sprint=None)
        issue["fields"]["sprint"] = {"name": "Sprint X"}  # no 'id'
        result = connector._map_issue(issue)
        assert result["sprint_id"] is None

    # -----------------------------------------------------------------------
    # _extract_changelogs
    # -----------------------------------------------------------------------

    def test_extract_changelogs_returns_status_transitions(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(changelog_histories=[
            _changelog_history(
                created="2024-01-10T10:00:00.000+0000",
                from_status="To Do",
                to_status="In Progress",
            )
        ])
        transitions = connector._extract_changelogs("jira:JiraIssue:1:101", issue)

        assert len(transitions) == 1
        assert transitions[0]["from_status"] == "To Do"
        assert transitions[0]["to_status"] == "In Progress"
        assert transitions[0]["created_date"] == "2024-01-10T10:00:00.000+0000"

    def test_extract_changelogs_sets_issue_id(self) -> None:
        connector = _make_connector()
        internal_id = "jira:JiraIssue:1:999"
        issue = _jira_issue(changelog_histories=[
            _changelog_history()
        ])
        transitions = connector._extract_changelogs(internal_id, issue)
        assert transitions[0]["issue_id"] == internal_id

    def test_extract_changelogs_empty_when_no_histories(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(changelog_histories=[])
        transitions = connector._extract_changelogs("jira:JiraIssue:1:101", issue)
        assert transitions == []

    def test_extract_changelogs_ignores_non_status_fields(self) -> None:
        """Only 'status' field changes must be extracted — not assignee, labels, etc."""
        connector = _make_connector()
        issue = _jira_issue(changelog_histories=[
            _changelog_history(field="assignee", from_status="Alice", to_status="Bob"),
            _changelog_history(field="status", from_status="To Do", to_status="Done"),
        ])
        transitions = connector._extract_changelogs("jira:JiraIssue:1:101", issue)

        assert len(transitions) == 1
        assert transitions[0]["from_status"] == "To Do"

    def test_extract_changelogs_empty_when_no_changelog_key(self) -> None:
        """Issue without changelog key (fetched without expand) returns empty."""
        connector = _make_connector()
        issue = {"id": "10001", "key": "BACK-1", "fields": {}}
        transitions = connector._extract_changelogs("jira:JiraIssue:1:10001", issue)
        assert transitions == []

    def test_extract_changelogs_sorted_chronologically(self) -> None:
        """Multiple transitions must come out sorted oldest first."""
        connector = _make_connector()
        issue = _jira_issue(changelog_histories=[
            _changelog_history(created="2024-01-15T12:00:00.000+0000", from_status="In Progress", to_status="Done"),
            _changelog_history(created="2024-01-10T08:00:00.000+0000", from_status="To Do", to_status="In Progress"),
        ])
        transitions = connector._extract_changelogs("jira:JiraIssue:1:101", issue)

        assert transitions[0]["from_status"] == "To Do"
        assert transitions[1]["from_status"] == "In Progress"

    def test_extract_changelogs_multiple_items_in_same_history(self) -> None:
        """A single history can have multiple items — only status items captured."""
        connector = _make_connector()
        history = {
            "created": "2024-01-12T09:00:00.000+0000",
            "items": [
                {"field": "priority", "fromString": "Low", "toString": "High"},
                {"field": "status", "fromString": "In Progress", "toString": "Code Review"},
            ],
        }
        issue = {"id": "101", "key": "BACK-1", "fields": {}, "changelog": {"histories": [history]}}
        transitions = connector._extract_changelogs("jira:JiraIssue:1:101", issue)

        assert len(transitions) == 1
        assert transitions[0]["to_status"] == "Code Review"

    # -----------------------------------------------------------------------
    # get_cached_changelogs
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_cached_changelogs_returns_changelogs_from_fetch(self) -> None:
        """Changelogs captured during fetch_issues are returned via get_cached_changelogs."""
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()

        issue = _jira_issue(
            jira_id="201",
            changelog_histories=[_changelog_history()],
        )
        connector._client.post.return_value = {"issues": [issue]}

        await connector.fetch_issues()

        cached = connector.get_cached_changelogs()
        assert len(cached) == 1
        internal_id = f"jira:JiraIssue:{CONN_ID}:201"
        assert internal_id in cached

    @pytest.mark.asyncio
    async def test_get_cached_changelogs_clears_cache_after_read(self) -> None:
        """Second call returns empty — cache is cleared on read."""
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()

        issue = _jira_issue(
            jira_id="202",
            changelog_histories=[_changelog_history()],
        )
        connector._client.post.return_value = {"issues": [issue]}

        await connector.fetch_issues()

        connector.get_cached_changelogs()         # first read
        second_read = connector.get_cached_changelogs()  # should be empty

        assert second_read == {}

    def test_get_cached_changelogs_returns_empty_when_nothing_fetched(self) -> None:
        connector = _make_connector()
        result = connector.get_cached_changelogs()
        assert result == {}

    def test_get_cached_changelogs_empty_when_issues_have_no_status_transitions(self) -> None:
        """Issues with no changelog entries produce no cache entries."""
        connector = _make_connector()
        issue = _jira_issue(changelog_histories=[])
        connector._map_issue(issue)

        result = connector.get_cached_changelogs()
        assert result == {}

    # -----------------------------------------------------------------------
    # fetch_issue_changelogs
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_issue_changelogs_empty_input_returns_empty(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()

        result = await connector.fetch_issue_changelogs([])

        assert result == {}
        connector._client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_issue_changelogs_calls_get_with_expand_changelog(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        internal_id = "jira:JiraIssue:1:12345"

        connector._client.get.return_value = _jira_issue(
            jira_id="12345",
            changelog_histories=[_changelog_history()],
        )

        await connector.fetch_issue_changelogs([internal_id])

        connector._client.get.assert_awaited_once()
        call_args = connector._client.get.call_args
        assert "/rest/api/3/issue/12345" in call_args[0][0]
        assert call_args[1]["params"]["expand"] == "changelog"

    @pytest.mark.asyncio
    async def test_fetch_issue_changelogs_returns_transitions(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        internal_id = "jira:JiraIssue:1:12345"

        connector._client.get.return_value = _jira_issue(
            jira_id="12345",
            changelog_histories=[
                _changelog_history(from_status="To Do", to_status="In Progress"),
            ],
        )

        result = await connector.fetch_issue_changelogs([internal_id])

        assert internal_id in result
        assert result[internal_id][0]["from_status"] == "To Do"

    @pytest.mark.asyncio
    async def test_fetch_issue_changelogs_skips_issues_without_transitions(self) -> None:
        """Issues that exist but have no changelog items are excluded from result."""
        connector = _make_connector()
        connector._client = AsyncMock()
        internal_id = "jira:JiraIssue:1:12345"

        connector._client.get.return_value = _jira_issue(
            jira_id="12345",
            changelog_histories=[],
        )

        result = await connector.fetch_issue_changelogs([internal_id])

        assert internal_id not in result

    @pytest.mark.asyncio
    async def test_fetch_issue_changelogs_continues_on_api_error(self) -> None:
        """An error on one issue must not abort the batch."""
        connector = _make_connector()
        connector._client = AsyncMock()

        id_good = "jira:JiraIssue:1:111"
        id_bad = "jira:JiraIssue:1:222"

        connector._client.get.side_effect = [
            ConnectionError("network error"),                              # id_bad fails
            _jira_issue(                                                   # id_good succeeds
                jira_id="111",
                changelog_histories=[_changelog_history()],
            ),
        ]

        result = await connector.fetch_issue_changelogs([id_bad, id_good])

        # At least the good one returned
        assert id_good in result
        assert id_bad not in result

    @pytest.mark.asyncio
    async def test_fetch_issue_changelogs_invalid_id_format_skipped(self) -> None:
        """IDs without 4 colon-separated parts return None from _extract_key_from_id."""
        connector = _make_connector()
        connector._client = AsyncMock()

        result = await connector.fetch_issue_changelogs(["bad-id"])

        connector._client.get.assert_not_awaited()
        assert result == {}

    # -----------------------------------------------------------------------
    # _discover_boards
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discover_boards_calls_agile_board_endpoint(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.get.return_value = {"values": []}

        await connector._discover_boards()

        connector._client.get.assert_awaited_once()
        call_path = connector._client.get.call_args[0][0]
        assert "/rest/agile/1.0/board" in call_path

    @pytest.mark.asyncio
    async def test_discover_boards_filters_for_scrum_type(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.get.return_value = {"values": []}

        await connector._discover_boards()

        params = connector._client.get.call_args[1]["params"]
        assert params["type"] == "scrum"

    @pytest.mark.asyncio
    async def test_discover_boards_sends_project_key_as_param(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.get.return_value = {"values": []}

        await connector._discover_boards()

        params = connector._client.get.call_args[1]["params"]
        assert params["projectKeyOrId"] == "BACK"

    @pytest.mark.asyncio
    async def test_discover_boards_stores_discovered_board(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.get.return_value = {
            "values": [{"id": 10, "name": "BACK Board", "type": "scrum"}]
        }

        await connector._discover_boards()

        assert 10 in connector._boards
        assert connector._boards[10]["name"] == "BACK Board"
        assert connector._boards[10]["project_key"] == "BACK"

    @pytest.mark.asyncio
    async def test_discover_boards_skips_discovery_if_already_cached(self) -> None:
        """_discover_boards must be a no-op when _boards is already populated."""
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._boards = {99: {"id": 99, "name": "Existing Board"}}

        await connector._discover_boards()

        connector._client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_discover_boards_queries_each_project(self) -> None:
        connector = _make_connector(projects=["BACK", "ENO"])
        connector._client = AsyncMock()
        connector._client.get.return_value = {"values": []}

        await connector._discover_boards()

        assert connector._client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_discover_boards_continues_on_api_error_for_one_project(self) -> None:
        connector = _make_connector(projects=["BACK", "ENO"])
        connector._client = AsyncMock()
        connector._client.get.side_effect = [
            ConnectionError("project BACK failed"),
            {"values": [{"id": 20, "name": "ENO Board", "type": "scrum"}]},
        ]

        await connector._discover_boards()

        # ENO board still discovered despite BACK failure
        assert 20 in connector._boards

    # -----------------------------------------------------------------------
    # _fetch_board_sprints
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_board_sprints_returns_mapped_sprints(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._boards = {10: {"id": 10, "name": "BACK Board"}}

        connector._client.get.return_value = {
            "values": [_sprint_payload(sprint_id=42, state="active")],
            "isLast": True,
        }

        sprints = await connector._fetch_board_sprints(10)

        assert len(sprints) == 1
        assert sprints[0]["id"] == f"jira:JiraSprint:{CONN_ID}:42"

    @pytest.mark.asyncio
    async def test_fetch_board_sprints_pagination(self) -> None:
        """Follows offset-based pagination until isLast is True."""
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._boards = {10: {"id": 10, "name": "BACK Board"}}

        s1 = _sprint_payload(sprint_id=1)
        s2 = _sprint_payload(sprint_id=2)

        connector._client.get.side_effect = [
            {"values": [s1], "isLast": False},
            {"values": [s2], "isLast": True},
        ]

        sprints = await connector._fetch_board_sprints(10)

        assert connector._client.get.await_count == 2
        assert len(sprints) == 2

    @pytest.mark.asyncio
    async def test_fetch_board_sprints_400_returns_empty_list(self) -> None:
        """HTTP 400 means board doesn't support sprints — must NOT raise."""
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._boards = {10: {"id": 10, "name": "Kanban Board"}}
        connector._client.get.side_effect = Exception("400 Bad Request")

        sprints = await connector._fetch_board_sprints(10)

        assert sprints == []

    @pytest.mark.asyncio
    async def test_fetch_board_sprints_bad_request_string_returns_empty(self) -> None:
        """Exception message containing 'Bad Request' is treated as 400."""
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._boards = {10: {"id": 10, "name": "Kanban Board"}}
        connector._client.get.side_effect = Exception("Bad Request from server")

        sprints = await connector._fetch_board_sprints(10)

        assert sprints == []

    @pytest.mark.asyncio
    async def test_fetch_board_sprints_other_error_returns_empty_list(self) -> None:
        """Non-400 errors are logged as warnings but still return empty."""
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._boards = {10: {"id": 10, "name": "BACK Board"}}
        connector._client.get.side_effect = Exception("503 Service Unavailable")

        sprints = await connector._fetch_board_sprints(10)

        assert sprints == []

    @pytest.mark.asyncio
    async def test_fetch_board_sprints_watermark_filters_old_sprints(self) -> None:
        """Sprints that started before `since` should be excluded."""
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._boards = {10: {"id": 10, "name": "BACK Board"}}

        old_sprint = _sprint_payload(
            sprint_id=1,
            state="closed",
            start_date="2023-01-08T09:00:00.000Z",
        )
        new_sprint = _sprint_payload(
            sprint_id=2,
            state="active",
            start_date="2024-06-01T09:00:00.000Z",
        )

        connector._client.get.return_value = {
            "values": [old_sprint, new_sprint],
            "isLast": True,
        }

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sprints = await connector._fetch_board_sprints(10, since=since)

        assert len(sprints) == 1
        assert sprints[0]["id"].endswith(":2")

    @pytest.mark.asyncio
    async def test_fetch_board_sprints_watermark_includes_sprint_on_boundary(self) -> None:
        """A sprint starting exactly at the watermark boundary is not filtered."""
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._boards = {10: {"id": 10, "name": "BACK Board"}}

        boundary_sprint = _sprint_payload(
            sprint_id=5,
            state="closed",
            start_date="2024-01-01T00:00:00.000Z",
        )

        connector._client.get.return_value = {
            "values": [boundary_sprint],
            "isLast": True,
        }

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sprints = await connector._fetch_board_sprints(10, since=since)

        # Exactly at boundary (dt == since, not dt < since) → included
        assert len(sprints) == 1

    # -----------------------------------------------------------------------
    # fetch_sprints
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_sprints_calls_discover_boards_first(self) -> None:
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()

        # No boards discovered → _fetch_board_sprints never called
        connector._client.get.return_value = {"values": []}

        sprints = await connector.fetch_sprints()

        assert sprints == []

    @pytest.mark.asyncio
    async def test_fetch_sprints_aggregates_sprints_from_all_boards(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        # Pre-populate boards cache
        connector._boards = {
            10: {"id": 10, "name": "Board A"},
            20: {"id": 20, "name": "Board B"},
        }

        sprint_a = _sprint_payload(sprint_id=1)
        sprint_b = _sprint_payload(sprint_id=2)

        connector._client.get.side_effect = [
            {"values": [sprint_a], "isLast": True},
            {"values": [sprint_b], "isLast": True},
        ]

        sprints = await connector.fetch_sprints()

        assert len(sprints) == 2

    # -----------------------------------------------------------------------
    # fetch_sprint_issues
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_sprint_issues_invalid_id_returns_empty(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()

        result = await connector.fetch_sprint_issues("bad-id")

        assert result == []
        connector._client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_sprint_issues_calls_agile_sprint_issue_endpoint(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._client.get.return_value = {"issues": [], "total": 0}

        await connector.fetch_sprint_issues("jira:JiraSprint:1:42")

        call_path = connector._client.get.call_args[0][0]
        assert "/rest/agile/1.0/sprint/42/issue" in call_path

    @pytest.mark.asyncio
    async def test_fetch_sprint_issues_returns_mapped_sprint_issues(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()

        sprint_id = "jira:JiraSprint:1:42"
        raw_issue = _jira_issue(jira_id="501", key="BACK-501", status="Done")
        connector._client.get.return_value = {
            "issues": [raw_issue],
            "total": 1,
        }

        result = await connector.fetch_sprint_issues(sprint_id)

        assert len(result) == 1
        assert result[0]["id"] == f"jira:JiraIssue:{CONN_ID}:501"
        assert result[0]["issue_key"] == "BACK-501"

    @pytest.mark.asyncio
    async def test_fetch_sprint_issues_pagination_uses_start_at(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()

        sprint_id = "jira:JiraSprint:1:42"
        issue1 = _jira_issue(jira_id="601", key="BACK-601")
        issue2 = _jira_issue(jira_id="602", key="BACK-602")

        connector._client.get.side_effect = [
            {"issues": [issue1], "total": 2},
            {"issues": [issue2], "total": 2},
        ]

        result = await connector.fetch_sprint_issues(sprint_id)

        assert len(result) == 2
        assert connector._client.get.await_count == 2
        # Second call should have startAt=1
        second_params = connector._client.get.call_args_list[1][1]["params"]
        assert second_params["startAt"] == 1

    @pytest.mark.asyncio
    async def test_fetch_sprint_issues_handles_api_error_gracefully(self) -> None:
        connector = _make_connector()
        connector._client = AsyncMock()
        connector._client.get.side_effect = ConnectionError("timeout")

        result = await connector.fetch_sprint_issues("jira:JiraSprint:1:42")

        assert result == []

    # -----------------------------------------------------------------------
    # _map_sprint
    # -----------------------------------------------------------------------

    def test_map_sprint_active_state(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(sprint_id=10, state="active")
        result = connector._map_sprint(sprint, board_id=5)
        assert result["status"] == "ACTIVE"

    def test_map_sprint_closed_state(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(sprint_id=10, state="closed")
        result = connector._map_sprint(sprint, board_id=5)
        assert result["status"] == "CLOSED"

    def test_map_sprint_future_state(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(sprint_id=10, state="future")
        result = connector._map_sprint(sprint, board_id=5)
        assert result["status"] == "FUTURE"

    def test_map_sprint_unknown_state_defaults_to_future(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(sprint_id=10, state="UNKNOWN_STATE")
        result = connector._map_sprint(sprint, board_id=5)
        assert result["status"] == "FUTURE"

    def test_map_sprint_state_is_case_insensitive(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(sprint_id=10, state="ACTIVE")
        result = connector._map_sprint(sprint, board_id=5)
        assert result["status"] == "ACTIVE"

    def test_map_sprint_builds_internal_id(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(sprint_id=42)
        result = connector._map_sprint(sprint, board_id=5)
        assert result["id"] == f"jira:JiraSprint:{CONN_ID}:42"

    def test_map_sprint_maps_dates(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(
            start_date="2024-01-08T09:00:00.000Z",
            end_date="2024-01-22T18:00:00.000Z",
            complete_date="2024-01-22T18:30:00.000Z",
        )
        result = connector._map_sprint(sprint, board_id=5)
        assert result["started_date"] == "2024-01-08T09:00:00.000Z"
        assert result["ended_date"] == "2024-01-22T18:00:00.000Z"
        assert result["completed_date"] == "2024-01-22T18:30:00.000Z"

    def test_map_sprint_preserves_name(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload(name="Sprint 12")
        result = connector._map_sprint(sprint, board_id=5)
        assert result["name"] == "Sprint 12"

    def test_map_sprint_board_id_stored_as_string(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload()
        result = connector._map_sprint(sprint, board_id=10)
        assert result["original_board_id"] == "10"

    def test_map_sprint_url_is_base_url(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload()
        result = connector._map_sprint(sprint, board_id=10)
        assert result["url"] == BASE_URL

    def test_map_sprint_total_issues_defaults_to_zero(self) -> None:
        connector = _make_connector()
        sprint = _sprint_payload()
        result = connector._map_sprint(sprint, board_id=10)
        assert result["total_issues"] == 0

    # -----------------------------------------------------------------------
    # _map_sprint_issue
    # -----------------------------------------------------------------------

    def test_map_sprint_issue_builds_internal_id(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(jira_id="701", key="BACK-701")
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["id"] == f"jira:JiraIssue:{CONN_ID}:701"

    def test_map_sprint_issue_preserves_key(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(key="BACK-702")
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["issue_key"] == "BACK-702"

    def test_map_sprint_issue_status_is_lowercase(self) -> None:
        """Sprint issue status is lowercased for normalizer compatibility."""
        connector = _make_connector()
        issue = _jira_issue(status="Done")
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["status"] == "done"

    def test_map_sprint_issue_original_status_preserves_case(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(status="In Progress")
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["original_status"] == "In Progress"

    def test_map_sprint_issue_story_points_from_story_points_field(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(story_points=13.0)
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["story_point"] == 13.0

    def test_map_sprint_issue_story_points_fallback_customfield_10028(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(story_points=None)
        issue["fields"]["customfield_10028"] = 8.0
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["story_point"] == 8.0

    def test_map_sprint_issue_story_points_fallback_customfield_10016(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(story_points=None)
        issue["fields"]["customfield_10028"] = None
        issue["fields"]["customfield_10016"] = 3.0
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["story_point"] == 3.0

    def test_map_sprint_issue_maps_type(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(issue_type="Bug")
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["type"] == "Bug"

    def test_map_sprint_issue_resolution_date_when_done(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(resolution_date="2024-01-20T16:00:00.000+0000")
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["resolution_date"] == "2024-01-20T16:00:00.000+0000"

    def test_map_sprint_issue_resolution_date_none_when_open(self) -> None:
        connector = _make_connector()
        issue = _jira_issue(resolution_date=None, status="In Progress")
        result = connector._map_sprint_issue(issue, "jira:JiraSprint:1:42")
        assert result["resolution_date"] is None

    # -----------------------------------------------------------------------
    # _extract_key_from_id
    # -----------------------------------------------------------------------

    def test_extract_key_from_id_returns_fourth_part(self) -> None:
        connector = _make_connector()
        result = connector._extract_key_from_id("jira:JiraIssue:1:12345")
        assert result == "12345"

    def test_extract_key_from_id_returns_none_for_short_id(self) -> None:
        connector = _make_connector()
        result = connector._extract_key_from_id("jira:JiraIssue:1")
        assert result is None

    def test_extract_key_from_id_returns_none_for_empty_string(self) -> None:
        connector = _make_connector()
        result = connector._extract_key_from_id("")
        assert result is None

    def test_extract_key_from_id_works_with_any_id_format(self) -> None:
        """Fourth colon-separated segment is always returned, regardless of prefix."""
        connector = _make_connector()
        result = connector._extract_key_from_id("github:GithubIssue:2:99999")
        assert result == "99999"

    # -----------------------------------------------------------------------
    # _extract_numeric_id (static method)
    # -----------------------------------------------------------------------

    def test_extract_numeric_id_returns_fourth_segment(self) -> None:
        result = JiraConnector._extract_numeric_id("jira:JiraSprint:1:123")
        assert result == "123"

    def test_extract_numeric_id_returns_none_for_short_id(self) -> None:
        result = JiraConnector._extract_numeric_id("jira:JiraSprint:1")
        assert result is None

    def test_extract_numeric_id_returns_none_for_empty_string(self) -> None:
        result = JiraConnector._extract_numeric_id("")
        assert result is None

    def test_extract_numeric_id_works_for_sprint_id(self) -> None:
        result = JiraConnector._extract_numeric_id("jira:JiraSprint:1:456")
        assert result == "456"

    # -----------------------------------------------------------------------
    # Anti-surveillance: no individual developer metrics
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_issues_does_not_expose_individual_scores(self) -> None:
        """Mapped issues must not include ranking or performance score fields."""
        connector = _make_connector(projects=["BACK"])
        connector._client = AsyncMock()
        connector._client.post.return_value = {
            "issues": [_jira_issue(jira_id="801", key="BACK-801")]
        }

        results = await connector.fetch_issues()

        prohibited_keys = {
            "developer_score", "ranking", "performance_score",
            "productivity_score", "individual_rank",
        }
        for issue in results:
            assert not prohibited_keys.intersection(issue.keys()), (
                f"Issue exposes individual-level metric: {prohibited_keys.intersection(issue.keys())}"
            )

    def test_map_issue_result_does_not_contain_individual_scores(self) -> None:
        connector = _make_connector()
        result = connector._map_issue(_jira_issue())
        prohibited_keys = {
            "developer_score", "ranking", "performance_score",
            "productivity_score", "individual_rank",
        }
        assert not prohibited_keys.intersection(result.keys())

    def test_map_sprint_issue_result_does_not_contain_individual_scores(self) -> None:
        connector = _make_connector()
        result = connector._map_sprint_issue(_jira_issue(), "jira:JiraSprint:1:42")
        prohibited_keys = {
            "developer_score", "ranking", "performance_score",
            "productivity_score", "individual_rank",
        }
        assert not prohibited_keys.intersection(result.keys())
