"""Jira Cloud connector — fetches issues, sprints, and changelogs via REST API v3.

Replaces DevLake's Jira plugin with direct API access, solving:
- Jira API v2 deprecation (HTTP 410 on /rest/api/2/search)
- 99.3% data loss in DevLake domain normalization
- Missing sprint data

Uses Jira REST API v3 (search via /rest/api/3/search) and Agile API
(/rest/agile/1.0/) for boards and sprints.

Authentication: Basic auth with email + API token (Jira Cloud standard).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.config import settings
from src.connectors.base import BaseConnector
from src.shared.http_client import ResilientHTTPClient

logger = logging.getLogger(__name__)

# Jira Agile API base (different from REST API)
AGILE_API = "/rest/agile/1.0"
REST_API = "/rest/api/3"

# Maximum results per page (Jira caps at 100 for search, 50 for agile)
SEARCH_PAGE_SIZE = 100
AGILE_PAGE_SIZE = 50

# Fields to fetch in search queries (minimize payload)
SEARCH_FIELDS = [
    "summary", "status", "issuetype", "priority", "assignee",
    "created", "updated", "resolutiondate", "resolution",
    "sprint", "story_points", "customfield_10028",  # story points field
    "parent", "labels", "components",
]


class JiraConnector(BaseConnector):
    """Fetches issues, sprints, and changelogs from Jira Cloud REST API v3.

    Configuration (from settings):
        - jira_base_url: Jira instance URL (e.g., https://webmotors.atlassian.net)
        - jira_email: Service account email
        - jira_api_token: API token
        - jira_projects: Comma-separated project keys (e.g., "DESC,ENO,ANCR")
    """

    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        projects: list[str] | None = None,
        connection_id: int = 1,
    ) -> None:
        self._base_url = (base_url or settings.jira_base_url).rstrip("/")
        self._email = email or settings.jira_email
        self._api_token = api_token or settings.jira_api_token
        self._projects = projects or settings.jira_project_list
        self._connection_id = connection_id

        if not self._base_url or not self._api_token:
            raise ValueError(
                "Jira connector requires JIRA_BASE_URL and JIRA_API_TOKEN. "
                "Set them in environment variables or .env file."
            )

        self._client = ResilientHTTPClient(
            base_url=self._base_url,
            auth={"basic": (self._email, self._api_token)},
            timeout=60.0,
            max_retries=3,
        )

        # Cache: board_id -> board info (discovered lazily)
        self._boards: dict[int, dict] = {}

    @property
    def source_type(self) -> str:
        return "jira"

    async def test_connection(self) -> dict[str, Any]:
        """Test Jira connectivity by fetching current user."""
        try:
            data = await self._client.get(f"{REST_API}/myself")
            return {
                "status": "healthy",
                "message": f"Connected as {data.get('displayName', 'unknown')}",
                "details": {
                    "email": data.get("emailAddress"),
                    "account_id": data.get("accountId"),
                    "projects": self._projects,
                },
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def fetch_issues(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch issues from Jira using JQL search with expand=changelog.

        Uses API v3 search endpoint. Includes changelogs inline to avoid
        separate API calls per issue (major efficiency gain over DevLake).
        """
        if not self._projects:
            logger.warning("No Jira projects configured — skipping issue fetch")
            return []

        project_list = ", ".join(self._projects)
        jql = f"project IN ({project_list})"
        if since:
            since_str = since.strftime("%Y-%m-%d %H:%M")
            jql += f' AND updated >= "{since_str}"'
        jql += " ORDER BY updated DESC"

        logger.info("Fetching Jira issues with JQL: %s", jql)

        all_issues: list[dict[str, Any]] = []
        start_at = 0

        while True:
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": SEARCH_PAGE_SIZE,
                "fields": ",".join(SEARCH_FIELDS),
                "expand": "changelog",
            }
            data = await self._client.get(f"{REST_API}/search", params=params)

            issues = data.get("issues", [])
            for issue in issues:
                mapped = self._map_issue(issue)
                all_issues.append(mapped)

            total = data.get("total", 0)
            start_at += len(issues)

            if start_at >= total or not issues:
                break

        logger.info("Fetched %d issues from Jira (%d projects)", len(all_issues), len(self._projects))
        return all_issues

    async def fetch_issue_changelogs(
        self, issue_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Return changelogs for given issue_ids.

        Since fetch_issues already includes changelogs via expand=changelog,
        this method is used for issues fetched WITHOUT expand (e.g., sprint issues).
        For those, we fetch changelogs individually.
        """
        if not issue_ids:
            return {}

        changelogs: dict[str, list[dict[str, Any]]] = {}

        # Extract Jira issue keys from our internal IDs
        for issue_id in issue_ids:
            jira_key = self._extract_key_from_id(issue_id)
            if not jira_key:
                continue

            try:
                data = await self._client.get(
                    f"{REST_API}/issue/{jira_key}",
                    params={"expand": "changelog", "fields": "status"},
                )
                transitions = self._extract_changelogs(issue_id, data)
                if transitions:
                    changelogs[issue_id] = transitions
            except Exception:
                logger.warning("Failed to fetch changelog for %s", jira_key)

        logger.info(
            "Fetched changelogs for %d/%d issues",
            len(changelogs), len(issue_ids),
        )
        return changelogs

    # ------------------------------------------------------------------
    # Sprints
    # ------------------------------------------------------------------

    async def fetch_sprints(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch sprints from all boards in configured projects."""
        await self._discover_boards()

        all_sprints: list[dict[str, Any]] = []
        for board_id, board_info in self._boards.items():
            try:
                sprints = await self._fetch_board_sprints(board_id, since)
                all_sprints.extend(sprints)
            except Exception:
                logger.exception("Failed to fetch sprints for board %d", board_id)

        logger.info("Fetched %d sprints from %d boards", len(all_sprints), len(self._boards))
        return all_sprints

    async def fetch_sprint_issues(
        self, sprint_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch all issues in a specific sprint."""
        # Extract numeric sprint ID from our internal format
        numeric_id = self._extract_numeric_id(sprint_id)
        if not numeric_id:
            return []

        all_issues: list[dict[str, Any]] = []
        start_at = 0

        while True:
            params = {"startAt": start_at, "maxResults": AGILE_PAGE_SIZE}
            try:
                data = await self._client.get(
                    f"{AGILE_API}/sprint/{numeric_id}/issue", params=params,
                )
            except Exception:
                logger.warning("Failed to fetch issues for sprint %s", sprint_id)
                break

            issues = data.get("issues", [])
            for issue in issues:
                mapped = self._map_sprint_issue(issue, sprint_id)
                all_issues.append(mapped)

            total = data.get("total", 0)
            start_at += len(issues)

            if start_at >= total or not issues:
                break

        logger.info("Fetched %d issues for sprint %s", len(all_issues), sprint_id)
        return all_issues

    # ------------------------------------------------------------------
    # PRs and Deployments — not applicable for Jira
    # ------------------------------------------------------------------

    async def fetch_pull_requests(self, since: datetime | None = None) -> list[dict[str, Any]]:
        return await self._not_supported("pull_requests")

    async def fetch_deployments(self, since: datetime | None = None) -> list[dict[str, Any]]:
        return await self._not_supported("deployments")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.close()
        logger.info("Jira connector closed")

    # ------------------------------------------------------------------
    # Internal: Mapping Jira API → Normalizer format
    # ------------------------------------------------------------------

    def _map_issue(self, jira_issue: dict[str, Any]) -> dict[str, Any]:
        """Map a Jira API issue response to the normalizer-expected format.

        Preserves the same dict keys that DevLake's `issues` domain table had,
        so the normalizer works unchanged.
        """
        fields = jira_issue.get("fields", {})
        key = jira_issue.get("key", "")
        jira_id = jira_issue.get("id", "")

        # Build our internal ID (same prefix format as DevLake for compatibility)
        internal_id = f"jira:JiraIssue:{self._connection_id}:{jira_id}"

        # Story points — try standard field first, then common custom fields
        story_points = (
            fields.get("story_points")
            or fields.get("customfield_10028")  # common SP field
            or fields.get("customfield_10016")  # another common SP field
            or None
        )

        # Sprint info from the sprint field (Jira includes active sprint)
        sprint_field = fields.get("sprint")
        sprint_id = None
        if sprint_field and isinstance(sprint_field, dict):
            raw_sprint_id = sprint_field.get("id")
            if raw_sprint_id:
                sprint_id = f"jira:JiraSprint:{self._connection_id}:{raw_sprint_id}"

        status_name = (fields.get("status") or {}).get("name", "")

        # Store changelogs inline (extracted separately for the sync worker)
        self._last_changelogs = self._last_changelogs if hasattr(self, "_last_changelogs") else {}
        changelogs = self._extract_changelogs(internal_id, jira_issue)
        if changelogs:
            self._last_changelogs[internal_id] = changelogs

        return {
            "id": internal_id,
            "url": f"{self._base_url}/browse/{key}",
            "issue_key": key,
            "title": fields.get("summary", ""),
            "status": status_name,
            "original_status": status_name,
            "story_point": story_points,
            "priority": (fields.get("priority") or {}).get("name", ""),
            "created_date": fields.get("created"),
            "updated_date": fields.get("updated"),
            "resolution_date": fields.get("resolutiondate"),
            "lead_time_minutes": None,  # Calculated by PULSE normalizer
            "assignee_name": (fields.get("assignee") or {}).get("displayName"),
            "type": (fields.get("issuetype") or {}).get("name", "Task"),
            "sprint_id": sprint_id,
        }

    def _map_sprint_issue(
        self, jira_issue: dict[str, Any], sprint_id: str,
    ) -> dict[str, Any]:
        """Map a Jira sprint issue to the format expected by normalize_sprint."""
        fields = jira_issue.get("fields", {})
        key = jira_issue.get("key", "")
        jira_id = jira_issue.get("id", "")

        status_name = (fields.get("status") or {}).get("name", "")
        story_points = (
            fields.get("story_points")
            or fields.get("customfield_10028")
            or fields.get("customfield_10016")
            or None
        )

        return {
            "id": f"jira:JiraIssue:{self._connection_id}:{jira_id}",
            "issue_key": key,
            "status": status_name.lower(),
            "original_status": status_name,
            "story_point": story_points,
            "type": (fields.get("issuetype") or {}).get("name", "Task"),
            "resolution_date": fields.get("resolutiondate"),
        }

    def _extract_changelogs(
        self, internal_id: str, jira_issue: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract status transition changelogs from a Jira issue response.

        Jira includes changelog in the response when expand=changelog is used.
        Returns list in the format the normalizer's build_status_transitions() expects.
        """
        transitions: list[dict[str, Any]] = []
        changelog = jira_issue.get("changelog", {})

        for history in changelog.get("histories", []):
            created = history.get("created")
            for item in history.get("items", []):
                if item.get("field", "").lower() == "status":
                    transitions.append({
                        "issue_id": internal_id,
                        "from_status": item.get("fromString", ""),
                        "to_status": item.get("toString", ""),
                        "created_date": created,
                    })

        # Sort chronologically
        transitions.sort(key=lambda t: t.get("created_date") or "")
        return transitions

    # ------------------------------------------------------------------
    # Internal: Board and Sprint discovery
    # ------------------------------------------------------------------

    async def _discover_boards(self) -> None:
        """Discover all Scrum/Kanban boards for configured projects."""
        if self._boards:
            return  # Already discovered

        for project_key in self._projects:
            try:
                data = await self._client.get(
                    f"{AGILE_API}/board",
                    params={"projectKeyOrId": project_key, "maxResults": 50},
                )
                for board in data.get("values", []):
                    board_id = board["id"]
                    self._boards[board_id] = {
                        "id": board_id,
                        "name": board.get("name", ""),
                        "type": board.get("type", ""),
                        "project_key": project_key,
                    }
                    logger.info(
                        "Discovered board: %s (%s) for project %s",
                        board.get("name"), board_id, project_key,
                    )
            except Exception:
                logger.exception("Failed to discover boards for project %s", project_key)

    async def _fetch_board_sprints(
        self, board_id: int, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all sprints for a board via the Agile API."""
        all_sprints: list[dict[str, Any]] = []
        start_at = 0

        while True:
            params: dict[str, Any] = {
                "startAt": start_at,
                "maxResults": AGILE_PAGE_SIZE,
            }
            data = await self._client.get(
                f"{AGILE_API}/board/{board_id}/sprint", params=params,
            )

            sprints = data.get("values", [])
            for sprint in sprints:
                mapped = self._map_sprint(sprint, board_id)

                # Apply watermark filter
                if since:
                    start_date = mapped.get("started_date")
                    if start_date and isinstance(start_date, str):
                        try:
                            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                            if dt < since:
                                continue
                        except ValueError:
                            pass

                all_sprints.append(mapped)

            if data.get("isLast", True) or not sprints:
                break
            start_at += len(sprints)

        return all_sprints

    def _map_sprint(self, sprint: dict[str, Any], board_id: int) -> dict[str, Any]:
        """Map a Jira Agile sprint to the normalizer-expected format."""
        sprint_id = sprint.get("id", "")
        state = str(sprint.get("state", "")).lower()

        # Map Jira sprint state to normalized status
        if state == "active":
            status = "ACTIVE"
        elif state == "closed":
            status = "CLOSED"
        else:
            status = "FUTURE"

        return {
            "id": f"jira:JiraSprint:{self._connection_id}:{sprint_id}",
            "original_board_id": str(board_id),
            "name": sprint.get("name", ""),
            "url": self._base_url,
            "status": status,
            "started_date": sprint.get("startDate"),
            "ended_date": sprint.get("endDate"),
            "completed_date": sprint.get("completeDate"),
            "total_issues": 0,  # Filled by fetch_sprint_issues if needed
        }

    # ------------------------------------------------------------------
    # Internal: ID helpers
    # ------------------------------------------------------------------

    def _extract_key_from_id(self, internal_id: str) -> str | None:
        """Extract Jira issue key from internal ID like 'jira:JiraIssue:1:12345'.

        We need to do a lookup since the internal ID contains the numeric Jira ID,
        not the key. For now, return None and let the caller handle it.
        """
        # For issues fetched with expand=changelog, changelogs are already inline
        # This method is only called for issues fetched without changelog
        parts = internal_id.split(":")
        if len(parts) >= 4:
            return parts[3]  # numeric ID — caller uses GET /issue/{id}
        return None

    @staticmethod
    def _extract_numeric_id(internal_id: str) -> str | None:
        """Extract the numeric ID from internal format 'jira:JiraSprint:1:123'."""
        parts = internal_id.split(":")
        if len(parts) >= 4:
            return parts[3]
        return None

    def get_cached_changelogs(self) -> dict[str, list[dict[str, Any]]]:
        """Return changelogs cached during fetch_issues (expand=changelog).

        This avoids making separate API calls for changelogs when issues
        were already fetched with expand=changelog.
        """
        result = getattr(self, "_last_changelogs", {})
        self._last_changelogs = {}  # Clear cache after read
        return result
