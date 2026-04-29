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

# ---------------------------------------------------------------------------
# Effort estimation fallback chain (FDD-OPS-016)
#
# Webmotors and many enterprise tenants do NOT use story points (validated
# 2026-04-28: 0% population across all 69 active Jira projects). Different
# squads use different estimation methods, or none at all. We discover and
# extract from a fallback chain in priority order:
#
#   1. Story Points  (numeric)  → use raw value
#   2. Story point estimate     → use raw value
#   3. T-Shirt Size  (option)   → map P/M/G... to Fibonacci scale
#   4. Tamanho/Impacto (option) → map PP/P/M/G... to Fibonacci scale
#   5. Original Estimate (sec)  → bucket hours into Fibonacci-aligned points
#   6. None                     → consumer falls back to count-of-items
#                                 (Kanban-pure mode)
#
# When `story_points` lands as None, downstream metrics (Lean throughput,
# velocity) MUST count items rather than sum points. The decision to count
# vs sum lives in the metric layer, not here.
#
# Future (codename "dev-metrics"): admin UI to opt into a specific method
# per source/squad + proprietary forecasting model. See FDD-DEV-METRICS-001
# in ops-backlog.md.
# ---------------------------------------------------------------------------

# Field-name keywords used by `_discover_effort_fields` (case-insensitive,
# matched against Jira `fields` API "name" property).
EFFORT_NAME_PATTERNS_TSHIRT = ("t-shirt size", "tshirt size", "tamanho/impacto")
EFFORT_NAME_PATTERNS_TIME = ("original estimate",)  # core field, not custom

# Fibonacci-like mapping for option-typed effort fields. Covers the values
# observed in Webmotors data + common defaults (XS/S/M/L/XL/XXL).
TSHIRT_TO_POINTS: dict[str, float] = {
    # Portuguese sizes
    "PP": 1.0, "P": 2.0, "M": 3.0, "G": 5.0, "GG": 8.0, "GGG": 13.0,
    # English sizes
    "XS": 1.0, "S": 2.0, "L": 5.0, "XL": 8.0, "XXL": 13.0,
}

# Hour-based estimation buckets → SP equivalent.
# Aligned with "1 ideal day = ~6h productive, 1 SP ≈ small task < 0.5d" so
# the steps stay roughly Fibonacci. Calibrated against Webmotors observed
# values (2h–124h, multiples of 4) so each common value lands in a sensible
# bucket. Rounded to the SP scale that downstream metrics already speak.
def _hours_to_points(hours: float) -> float:
    if hours <= 4:    return 1.0
    if hours <= 8:    return 2.0
    if hours <= 16:   return 3.0
    if hours <= 24:   return 5.0
    if hours <= 40:   return 8.0
    if hours <= 80:   return 13.0
    return 21.0


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
        # FDD-OPS-016: discovered effort-fallback field IDs (T-shirt size,
        # Tamanho/Impacto). Many tenants don't use story points at all.
        self._tshirt_field_ids: list[str] = []
        self._custom_fields_discovered: bool = False
        # Telemetry for `_extract_effort` — counts how often each strategy
        # was the one that produced a value, plus how many issues fell
        # through to None. Logged at end of each batched fetch so operators
        # can spot estimation mode shifts without combing through traces.
        self._effort_source_counts: dict[str, int] = {}
        # FDD-OPS-017 — status→category map cached from /rest/api/3/status.
        # Keys are lowercased status names (e.g., "fechado em prod"); values
        # are statusCategory.key ("new" | "indeterminate" | "done"). Used
        # by the normalizer as the authoritative fallback when a textual
        # mapping isn't found. Populated by `_discover_status_categories()`
        # on first fetch.
        self._status_categories: dict[str, str] = {}
        self._status_categories_discovered: bool = False

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
        await self._discover_status_categories()

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
        # FDD-OPS-016: include effort fallback fields (T-shirt size,
        # Tamanho/Impacto, original estimate)
        for f in self._tshirt_field_ids:
            if f not in fields_to_fetch:
                fields_to_fetch.append(f)
        if "timeoriginalestimate" not in fields_to_fetch:
            fields_to_fetch.append("timeoriginalestimate")
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
        await self._discover_status_categories()

        # Build fields list: base + discovered custom fields + fallbacks.
        fields_to_fetch = list(SEARCH_FIELDS)
        if self._sprint_field_id:
            fields_to_fetch.append(self._sprint_field_id)
        if self._story_points_field_id:
            fields_to_fetch.append(self._story_points_field_id)
        # FDD-OPS-016: effort fallback fields
        for f in self._tshirt_field_ids:
            if f not in fields_to_fetch:
                fields_to_fetch.append(f)
        if "timeoriginalestimate" not in fields_to_fetch:
            fields_to_fetch.append("timeoriginalestimate")
        for f in FALLBACK_SPRINT_FIELDS + FALLBACK_STORY_POINTS_FIELDS:
            if f not in fields_to_fetch:
                fields_to_fetch.append(f)

        since_by_project = since_by_project or {}
        # FDD-OPS-016: reset effort telemetry per batched call so the
        # summary log reflects only this run.
        self._effort_source_counts = {}

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

        # FDD-OPS-016 — log effort-source distribution so operators can spot
        # which fields the squad uses (or that they don't estimate at all).
        if self._effort_source_counts:
            total = sum(self._effort_source_counts.values())
            breakdown = ", ".join(
                f"{src}={cnt} ({100.0*cnt/total:.1f}%)"
                for src, cnt in sorted(
                    self._effort_source_counts.items(),
                    key=lambda kv: -kv[1],
                )
            )
            logger.info(
                "[batched] effort source distribution (%d issues): %s",
                total, breakdown,
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
        # FDD-OPS-017 — read statusCategory from Jira's own `status` field
        # (always inline in the issue response, no extra HTTP). Fallback to
        # the cached `name → category` map if the issue payload lacks it
        # (older Jira REST APIs / odd workflows).
        status_cat_inline = (
            ((fields.get("status") or {}).get("statusCategory") or {}).get("key")
        )
        status_category = (
            status_cat_inline.lower() if isinstance(status_cat_inline, str)
            else self._status_categories.get(status_name.strip().lower())
        )

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
            # FDD-OPS-017 — Jira's authoritative classification of THIS issue's
            # current status. The normalizer uses it as the fallback when the
            # textual DEFAULT_STATUS_MAPPING doesn't recognize the status name.
            "status_category": status_category,
            # FDD-OPS-017 — full name→category map so build_status_transitions
            # can classify each historical to_status, not just the current one.
            # Same dict reference for every issue (cached on the connector);
            # downstream upsert ignores extra keys.
            "status_categories_map": self._status_categories,
            # FDD-OPS-013 — preserve raw changelog from `expand=changelog` so
            # `extract_status_transitions_inline()` in the sync worker can read
            # it. Without this, mapped dict drops the changelog and ALL issues
            # land with status_transitions=[] in eng_issues.
            "changelog": jira_issue.get("changelog", {}),
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

    async def _discover_status_categories(self) -> None:
        """FDD-OPS-017 — fetch all status definitions and cache name→category.

        Jira's `/rest/api/3/status` returns every status defined in the
        tenant, each tagged with a `statusCategory.key` of "new",
        "indeterminate", or "done". This is the AUTHORITATIVE classification
        of "is this status considered finished by the workflow author".

        Used by the normalizer as the fallback when our textual
        DEFAULT_STATUS_MAPPING doesn't recognize a status name. Without
        this, exotic Webmotors statuses like "FECHADO EM PROD" silently
        defaulted to "todo", catastrophically polluting flow metrics
        (Cycle Time, Throughput, WIP, CFD all read from `normalized_status`).

        Discovery is one HTTP call per connector lifetime — cached on
        instance. Failures degrade gracefully: we just lose the fallback.
        """
        if self._status_categories_discovered:
            return

        try:
            data = await self._client.get(f"{REST_API}/status")
        except Exception:
            logger.exception(
                "Failed to fetch Jira status catalog — normalization will "
                "rely solely on textual DEFAULT_STATUS_MAPPING"
            )
            self._status_categories_discovered = True
            return

        statuses = data if isinstance(data, list) else data.get("values", [])
        for s in statuses:
            name = (s.get("name") or "").strip().lower()
            cat = ((s.get("statusCategory") or {}).get("key") or "").strip().lower()
            if name and cat in ("new", "indeterminate", "done"):
                self._status_categories[name] = cat

        self._status_categories_discovered = True
        logger.info(
            "Discovered %d Jira status definitions (new=%d, indeterminate=%d, done=%d)",
            len(self._status_categories),
            sum(1 for v in self._status_categories.values() if v == "new"),
            sum(1 for v in self._status_categories.values() if v == "indeterminate"),
            sum(1 for v in self._status_categories.values() if v == "done"),
        )

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
            elif any(p in name for p in EFFORT_NAME_PATTERNS_TSHIRT):
                # FDD-OPS-016 — option-typed effort fallback (P/M/G…)
                if fid not in self._tshirt_field_ids:
                    self._tshirt_field_ids.append(fid)

        self._custom_fields_discovered = True
        logger.info(
            "Discovered Jira custom fields — sprint=%s, story_points=%s, "
            "effort_tshirt_fields=%s",
            self._sprint_field_id or "(none — using fallback)",
            self._story_points_field_id or "(none — using fallback)",
            self._tshirt_field_ids or "(none)",
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
        """Extract effort estimate, falling back through Story Points →
        T-shirt size → Original Estimate hours → None.

        Returns a float on the SP scale so downstream metrics (velocity,
        throughput) can sum it. Returns None when the issue is genuinely
        unestimated; the metric layer must then count items rather than
        sum points (Kanban-pure mode). See FDD-OPS-016.

        Side effect: increments `self._effort_source_counts[source]` so
        `fetch_issues_batched` can log the distribution per run. The source
        label is recorded even on None ("unestimated") so coverage can be
        observed end-to-end.
        """
        # 1+2. Native numeric story-point fields (preferred — no conversion).
        sp_candidates: list[str] = []
        if self._story_points_field_id:
            sp_candidates.append(self._story_points_field_id)
        sp_candidates.extend(FALLBACK_STORY_POINTS_FIELDS)
        sp_candidates.append("story_points")
        for c in sp_candidates:
            value = fields.get(c)
            if value is None or value == "":
                continue
            try:
                points = float(value)
            except (TypeError, ValueError):
                continue
            if points > 0:
                self._effort_source_counts["story_points"] = (
                    self._effort_source_counts.get("story_points", 0) + 1
                )
                return points

        # 3+4. T-shirt sized fields → map P/M/G… to Fibonacci scale.
        for fid in self._tshirt_field_ids:
            raw = fields.get(fid)
            label = self._unwrap_option(raw)
            if not label:
                continue
            mapped = TSHIRT_TO_POINTS.get(label.upper())
            if mapped is not None:
                self._effort_source_counts["tshirt_to_sp"] = (
                    self._effort_source_counts.get("tshirt_to_sp", 0) + 1
                )
                return mapped
            # Unknown size value — don't silently mis-map; fall through.

        # 5. Original Estimate (hours) → SP equivalent buckets.
        secs = fields.get("timeoriginalestimate")
        if secs:
            try:
                hours = float(secs) / 3600.0
                if hours > 0:
                    self._effort_source_counts["hours_to_sp"] = (
                        self._effort_source_counts.get("hours_to_sp", 0) + 1
                    )
                    return _hours_to_points(hours)
            except (TypeError, ValueError):
                pass

        # 6. Genuinely unestimated. Track for telemetry; metric layer counts items.
        self._effort_source_counts["unestimated"] = (
            self._effort_source_counts.get("unestimated", 0) + 1
        )
        return None

    @staticmethod
    def _unwrap_option(raw: Any) -> str | None:
        """Extract the string label from a Jira option-typed field.

        Jira returns option fields as `{"value": "P", "id": "..."}` but
        legacy/edge cases sometimes use "name" or a bare string. Be lenient.
        """
        if raw is None:
            return None
        if isinstance(raw, str):
            label = raw.strip()
            return label or None
        if isinstance(raw, dict):
            for key in ("value", "name", "displayName"):
                v = raw.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
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

                # FDD-OPS-018 — DELIBERATELY NOT applying a `since` watermark
                # filter here. Sprint state transitions (future→active→closed)
                # happen on `endDate`, not `startDate`. The previous filter
                # `if started_date < since: continue` meant a sprint that
                # started in March and closed in May would never have its
                # status updated past March's snapshot — every Webmotors
                # sprint landed with empty status because the watermark was
                # advanced past their start date.
                #
                # Volume is bounded (~216 total, ~5 active at any time across
                # 27 squads), so always re-fetching every sprint per cycle
                # is cheap and correct.
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
            # FDD-OPS-018 — sprint goal (free-text, set by squad lead).
            # Jira returns this as a string; pass through for normalizer.
            "goal": sprint.get("goal"),
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
