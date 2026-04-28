"""Jira Cloud connector — fetches issues, sprints, and changelogs via REST API v3.

Replaces DevLake's Jira plugin with direct API access, solving:
- Jira API v2 deprecation (HTTP 410 on /rest/api/2/search)
- 99.3% data loss in DevLake domain normalization
- Missing sprint data

Uses Jira REST API v3 (search via /rest/api/3/search/jql) and Agile API
(/rest/agile/1.0/) for boards and sprints.

Authentication: Basic auth with email + API token (Jira Cloud standard).
"""

from __future__ import annotations

import logging
import warnings
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

# Base fields to fetch in search queries (minimize payload).
# Sprint + story_points custom-field IDs are discovered dynamically per Jira
# tenant (they vary) and appended to this list at fetch time — see
# JiraConnector._discover_custom_fields().
SEARCH_FIELDS = [
    "summary", "status", "issuetype", "priority", "assignee",
    "created", "updated", "resolutiondate", "resolution",
    "parent", "labels", "components",
    # FDD-KB-013 — description surfaced in Flow Health drawer. Jira API v3
    # returns this as Atlassian Document Format (ADF) JSON; we flatten to
    # plain text in _extract_description_text() and cap at 4000 chars.
    "description",
]

# Max characters kept in eng_issues.description. Oversize descriptions
# are rare (>99% of Jira tickets are <2k chars) and storing 50k blobs
# across 400k+ issues would explode table size. Chose 4000 for parity
# with Varchar-style 4K limits — plenty of context for a drawer preview.
DESCRIPTION_MAX_CHARS = 4000

# Fallback custom-field IDs tried if discovery fails — these are the most
# common defaults on Jira Cloud instances.
FALLBACK_STORY_POINTS_FIELDS = ("customfield_10016", "customfield_10028")
FALLBACK_SPRINT_FIELDS = ("customfield_10020", "customfield_10010")


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

        # Discovered custom field IDs (vary per Jira tenant). Populated by
        # _discover_custom_fields() on first fetch_issues() call.
        self._sprint_field_id: str | None = None
        self._story_points_field_id: str | None = None
        self._custom_fields_discovered: bool = False

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
    # Project Discovery (ADR-014)
    # ------------------------------------------------------------------

    async def fetch_all_accessible_projects(self) -> list[dict[str, Any]]:
        """Fetch all Jira projects accessible to the service account.

        Uses GET /rest/api/3/project/search with pagination (startAt/maxResults).
        Returns list of dicts with keys: project_key, project_id, name,
        project_type, lead_account_id.
        """
        all_projects: list[dict[str, Any]] = []
        start_at = 0
        page_size = 50

        while True:
            params = {
                "startAt": start_at,
                "maxResults": page_size,
                "expand": "lead,description",
            }
            data = await self._client.get(f"{REST_API}/project/search", params=params)

            values = data.get("values", [])
            for proj in values:
                lead = proj.get("lead") or {}
                all_projects.append({
                    "project_key": proj.get("key", ""),
                    "project_id": str(proj.get("id", "")),
                    "name": proj.get("name", ""),
                    "project_type": proj.get("projectTypeKey", ""),
                    "lead_account_id": lead.get("accountId"),
                })

            total = data.get("total", 0)
            start_at += len(values)

            if start_at >= total or not values:
                break

        logger.info("Discovered %d accessible Jira projects", len(all_projects))
        return all_projects

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def fetch_issues(
        self,
        since: datetime | None = None,
        project_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch issues from Jira using JQL search with expand=changelog.

        Uses the new POST /rest/api/3/search/jql endpoint (Atlassian deprecated
        GET /rest/api/3/search with HTTP 410 Gone in 2025).

        Includes changelogs inline to avoid separate API calls per issue.

        Args:
            since: Watermark — only issues updated after this timestamp.
            project_keys: Explicit list of project keys to fetch. If None,
                falls back to self._projects (from env var) with a deprecation
                warning. Pass explicitly when using dynamic discovery.
        """
        if project_keys is not None:
            effective_projects = project_keys
        else:
            warnings.warn(
                "Calling fetch_issues() without explicit project_keys is deprecated. "
                "Pass project_keys explicitly or use ModeResolver.",
                DeprecationWarning,
                stacklevel=2,
            )
            effective_projects = self._projects

        if not effective_projects:
            logger.warning("No Jira projects configured — skipping issue fetch")
            return []

        # Discover tenant-specific custom field IDs (sprint, story points)
        await self._discover_custom_fields()

        # Quote each project key in JQL — some keys like "DESC" are reserved words
        quoted_projects = ", ".join(f'"{p}"' for p in effective_projects)
        jql = f"project IN ({quoted_projects})"
        if since:
            since_str = since.strftime("%Y-%m-%d %H:%M")
            jql += f' AND updated >= "{since_str}"'
        jql += " ORDER BY updated DESC"

        logger.info("Fetching Jira issues with JQL: %s", jql)

        # Build fields list: base + discovered custom fields + fallbacks
        fields_to_fetch = list(SEARCH_FIELDS)
        if self._sprint_field_id:
            fields_to_fetch.append(self._sprint_field_id)
        if self._story_points_field_id:
            fields_to_fetch.append(self._story_points_field_id)
        # Always include fallbacks to survive mis-discovery
        for f in FALLBACK_SPRINT_FIELDS + FALLBACK_STORY_POINTS_FIELDS:
            if f not in fields_to_fetch:
                fields_to_fetch.append(f)

        all_issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        page = 0

        while True:
            body: dict[str, Any] = {
                "jql": jql,
                "maxResults": SEARCH_PAGE_SIZE,
                "fields": fields_to_fetch,
                "expand": "changelog",  # Must be string, not array
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token

            data = await self._client.post(f"{REST_API}/search/jql", json_body=body)

            issues = data.get("issues", [])
            for issue in issues:
                mapped = self._map_issue(issue)
                all_issues.append(mapped)

            page += 1

            # New API uses nextPageToken for cursor-based pagination
            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break

        logger.info("Fetched %d issues from Jira (%d projects, %d pages)", len(all_issues), len(effective_projects), page)
        return all_issues

    async def fetch_issues_batched(
        self,
        project_keys: list[str],
        since_by_project: dict[str, datetime | None] | None = None,
    ):
        """Stream issues PER PROJECT, yielding (project_key, batch) per page.

        FDD-OPS-012 — replaces the bulk-fetch-all-then-persist pattern of
        fetch_issues(). Yields each page (~50 issues) as it arrives, so the
        caller can normalize → upsert → emit_event → advance_watermark
        immediately. Memory bound: ~one page in flight; crash recovery loses
        at most one page of work.

        Per-project pagination (one JQL per project) instead of `project IN
        (...)` makes per-scope watermarks possible (each project advances
        its own last_synced_at independently — see FDD-OPS-014). It also
        means failure on one project doesn't lose progress on others.

        Args:
            project_keys: Projects to sync. Must be explicit; no fallback
                to env var (caller MUST resolve via ModeResolver).
            since_by_project: Optional per-project watermark. Missing keys
                default to None (full backfill for that project).

        Yields:
            (project_key, list_of_normalized_raw_issues) tuples.
            Each list has SEARCH_PAGE_SIZE items (50 by default), except
            the last page of each project which may be smaller.
        """
        if not project_keys:
            logger.warning("fetch_issues_batched: empty project_keys, nothing to do")
            return

        # Discover tenant-specific custom field IDs once (cached for reuse).
        await self._discover_custom_fields()

        # Build fields list: base + discovered custom fields + fallbacks.
        fields_to_fetch = list(SEARCH_FIELDS)
        if self._sprint_field_id:
            fields_to_fetch.append(self._sprint_field_id)
        if self._story_points_field_id:
            fields_to_fetch.append(self._story_points_field_id)
        for f in FALLBACK_SPRINT_FIELDS + FALLBACK_STORY_POINTS_FIELDS:
            if f not in fields_to_fetch:
                fields_to_fetch.append(f)

        since_by_project = since_by_project or {}

        for project_key in project_keys:
            since = since_by_project.get(project_key)
            # Keys like "DESC" collide with SQL reserved words — quote always.
            jql = f'project = "{project_key}"'
            if since:
                since_str = since.strftime("%Y-%m-%d %H:%M")
                jql += f' AND updated >= "{since_str}"'
            jql += " ORDER BY updated DESC"

            logger.info(
                "[batched] %s: starting JQL fetch (since=%s)",
                project_key, since.isoformat() if since else "full-history",
            )

            next_page_token: str | None = None
            page = 0
            total_yielded = 0

            while True:
                body: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": SEARCH_PAGE_SIZE,
                    "fields": fields_to_fetch,
                    "expand": "changelog",  # critical: keeps changelog inline (FDD-OPS-013)
                }
                if next_page_token:
                    body["nextPageToken"] = next_page_token

                data = await self._client.post(
                    f"{REST_API}/search/jql", json_body=body,
                )

                issues = data.get("issues", [])
                if issues:
                    mapped_batch = [self._map_issue(issue) for issue in issues]
                    yield project_key, mapped_batch
                    total_yielded += len(mapped_batch)

                page += 1
                next_page_token = data.get("nextPageToken")
                if not next_page_token or not issues:
                    break

            logger.info(
                "[batched] %s: complete (%d issues, %d pages)",
                project_key, total_yielded, page,
            )

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
            sprints = await self._fetch_board_sprints(board_id, since)
            all_sprints.extend(sprints)

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

        # Story points — prefer dynamically-discovered field, with fallbacks
        story_points = self._extract_story_points(fields)

        # Sprint — Jira Cloud returns the sprint custom field as an ARRAY of
        # sprints (issue history). We pick the active one, or the most recent.
        sprint_id = self._extract_sprint_id(fields)

        status_name = (fields.get("status") or {}).get("name", "")

        # Store changelogs inline (extracted separately for the sync worker)
        self._last_changelogs = self._last_changelogs if hasattr(self, "_last_changelogs") else {}
        changelogs = self._extract_changelogs(internal_id, jira_issue)
        if changelogs:
            self._last_changelogs[internal_id] = changelogs

        # FDD-KB-013 — extract plain-text description (handles ADF JSON + v2 str).
        description_text = self._extract_description_text(fields.get("description"))

        return {
            "id": internal_id,
            "url": f"{self._base_url}/browse/{key}",
            "issue_key": key,
            "title": fields.get("summary", ""),
            "description": description_text,
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
        story_points = self._extract_story_points(fields)

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
    # Internal: Custom field discovery + extraction helpers
    # ------------------------------------------------------------------

    async def _discover_custom_fields(self) -> None:
        """Discover tenant-specific custom field IDs for sprint + story points.

        Jira Cloud stores these as custom fields whose IDs vary per instance
        (commonly customfield_10016/10020 but not guaranteed). We call
        GET /rest/api/3/field once and match by field *name*, which is stable.

        Results are cached on the instance — subsequent calls are no-ops.
        """
        if self._custom_fields_discovered:
            return

        try:
            data = await self._client.get(f"{REST_API}/field")
        except Exception:
            logger.exception("Failed to discover Jira custom fields — falling back to defaults")
            self._custom_fields_discovered = True
            return

        fields_list = data if isinstance(data, list) else data.get("values", [])
        for f in fields_list:
            fid = f.get("id", "")
            if not fid.startswith("customfield_"):
                continue
            name = (f.get("name") or "").strip().lower()
            if name == "sprint" and not self._sprint_field_id:
                self._sprint_field_id = fid
            elif name in ("story points", "story point estimate") and not self._story_points_field_id:
                self._story_points_field_id = fid

        self._custom_fields_discovered = True
        logger.info(
            "Discovered Jira custom fields — sprint=%s, story_points=%s",
            self._sprint_field_id or "(none — using fallback)",
            self._story_points_field_id or "(none — using fallback)",
        )

    def _extract_sprint_id(self, fields: dict[str, Any]) -> str | None:
        """Extract the sprint external_id from a Jira issue fields dict.

        The sprint custom field is an ARRAY of sprint objects reflecting the
        issue's sprint history. Priority:
          1. Active sprint (state='active')
          2. Most recent sprint by startDate (falls back to last element)

        Also handles the legacy dict-shaped response for robustness.
        """
        candidates: list[str] = []
        if self._sprint_field_id:
            candidates.append(self._sprint_field_id)
        candidates.extend(FALLBACK_SPRINT_FIELDS)
        candidates.append("sprint")

        raw = None
        for c in candidates:
            value = fields.get(c)
            if value:
                raw = value
                break

        if not raw:
            return None

        chosen: dict[str, Any] | None = None
        if isinstance(raw, list):
            if not raw:
                return None
            # Prefer active; else take last (most recent) — Jira returns
            # chronologically ordered.
            active = [s for s in raw if isinstance(s, dict) and s.get("state") == "active"]
            chosen = active[0] if active else (raw[-1] if isinstance(raw[-1], dict) else None)
        elif isinstance(raw, dict):
            chosen = raw

        if not chosen:
            return None

        raw_id = chosen.get("id")
        if not raw_id:
            return None
        return f"jira:JiraSprint:{self._connection_id}:{raw_id}"

    @staticmethod
    def _extract_description_text(raw: Any) -> str | None:
        """Flatten a Jira description into plain text, capped at DESCRIPTION_MAX_CHARS.

        Jira Cloud REST API v3 returns `fields.description` as Atlassian
        Document Format (ADF) — nested JSON with `content[].content[].text`.
        REST API v2 returns a plain string. Legacy issues or explicit blanks
        return None.

        Implementation is intentionally simple (not a full ADF parser): walk
        the tree, collect every `text` leaf, join paragraphs with blank
        lines. Good enough for a drawer preview; R1 can swap in a proper
        ADF→Markdown converter if product wants formatted output.

        Anti-surveillance note: we never log the extracted text. Description
        bodies may contain PII typed by humans; treat as sensitive.
        """
        if raw is None:
            return None

        # REST API v2 or legacy string — use directly.
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            return text[:DESCRIPTION_MAX_CHARS] + ("..." if len(text) > DESCRIPTION_MAX_CHARS else "")

        # ADF — walk the tree and collect text leaves per block.
        if not isinstance(raw, dict):
            return None

        # Each top-level block (paragraph, heading, bulletList, ...) becomes
        # a line; joined with double newlines to preserve visual separation.
        block_texts: list[str] = []

        def _collect_leaf_texts(node: Any) -> list[str]:
            """DFS: return every `text` leaf under this node."""
            leaves: list[str] = []
            if isinstance(node, dict):
                # ADF text node
                if node.get("type") == "text" and isinstance(node.get("text"), str):
                    leaves.append(node["text"])
                # ADF hardBreak inside paragraphs — preserve as newline
                elif node.get("type") == "hardBreak":
                    leaves.append("\n")
                # Recurse
                for child in node.get("content") or []:
                    leaves.extend(_collect_leaf_texts(child))
            elif isinstance(node, list):
                for child in node:
                    leaves.extend(_collect_leaf_texts(child))
            return leaves

        for block in raw.get("content") or []:
            leaves = _collect_leaf_texts(block)
            if leaves:
                block_texts.append("".join(leaves).strip())

        flat = "\n\n".join(t for t in block_texts if t).strip()
        if not flat:
            return None

        if len(flat) > DESCRIPTION_MAX_CHARS:
            return flat[:DESCRIPTION_MAX_CHARS].rstrip() + "..."
        return flat

    def _extract_story_points(self, fields: dict[str, Any]) -> float | None:
        """Extract story points, preferring the discovered custom field."""
        candidates: list[str] = []
        if self._story_points_field_id:
            candidates.append(self._story_points_field_id)
        candidates.extend(FALLBACK_STORY_POINTS_FIELDS)
        candidates.append("story_points")

        for c in candidates:
            value = fields.get(c)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    # ------------------------------------------------------------------
    # Internal: Board and Sprint discovery
    # ------------------------------------------------------------------

    async def _discover_boards(self) -> None:
        """Discover Scrum boards for configured projects.

        Only Scrum boards support sprints. Kanban boards return 400 on the
        sprint endpoint, so we filter them out during discovery.
        """
        if self._boards:
            return  # Already discovered

        for project_key in self._projects:
            try:
                data = await self._client.get(
                    f"{AGILE_API}/board",
                    params={"projectKeyOrId": project_key, "type": "scrum", "maxResults": 50},
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
                        "Discovered scrum board: %s (%s) for project %s",
                        board.get("name"), board_id, project_key,
                    )
            except Exception:
                logger.exception("Failed to discover boards for project %s", project_key)

    async def _fetch_board_sprints(
        self, board_id: int, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all sprints for a board via the Agile API.

        Returns empty list if the board doesn't support sprints (e.g., Kanban
        boards that slipped through discovery, or boards with sprints disabled).
        """
        all_sprints: list[dict[str, Any]] = []
        start_at = 0

        while True:
            params: dict[str, Any] = {
                "startAt": start_at,
                "maxResults": AGILE_PAGE_SIZE,
            }
            try:
                data = await self._client.get(
                    f"{AGILE_API}/board/{board_id}/sprint", params=params,
                )
            except Exception as exc:
                # 400 = board doesn't support sprints (Kanban, simple, etc.)
                exc_str = str(exc)
                if "400" in exc_str or "Bad Request" in exc_str:
                    board_info = self._boards.get(board_id, {})
                    logger.debug(
                        "Board %d (%s) doesn't support sprints — skipping",
                        board_id, board_info.get("name", "unknown"),
                    )
                else:
                    logger.warning(
                        "Error fetching sprints for board %d: %s", board_id, exc_str,
                    )
                return []

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
