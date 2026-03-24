"""Normalizer — transforms DevLake domain data into PULSE schema.

Pure functions that map DevLake's table structures into PULSE's
eng_pull_requests, eng_issues, eng_deployments, eng_sprints models.

Also handles:
- Status mapping (raw Jira/GitHub statuses to normalized todo/in_progress/done)
- Issue-to-PR linking via branch name regex patterns (e.g., "PROJ-123")
- Source detection from DevLake IDs/URLs
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Default status mapping when no custom mapping is provided
DEFAULT_STATUS_MAPPING: dict[str, str] = {
    # Common Jira statuses
    "to do": "todo",
    "todo": "todo",
    "backlog": "todo",
    "open": "todo",
    "new": "todo",
    "created": "todo",
    "ready": "todo",
    "selected for development": "todo",
    # In progress
    "in progress": "in_progress",
    "in development": "in_progress",
    "in review": "in_progress",
    "in testing": "in_progress",
    "code review": "in_progress",
    "review": "in_progress",
    "testing": "in_progress",
    "qa": "in_progress",
    "active": "in_progress",
    "doing": "in_progress",
    # Done
    "done": "done",
    "closed": "done",
    "resolved": "done",
    "complete": "done",
    "completed": "done",
    "released": "done",
    "deployed": "done",
    "verified": "done",
    # Cancelled / won't do
    "cancelled": "done",
    "canceled": "done",
    "won't do": "done",
    "wont do": "done",
    "duplicate": "done",
    "rejected": "done",
}

# Regex to find issue keys in branch names (e.g., "feature/BACK-123-add-login")
ISSUE_KEY_PATTERN = re.compile(r"([A-Z][A-Z0-9]+-\d+)", re.IGNORECASE)


def _detect_source(devlake_row: dict[str, Any]) -> str:
    """Detect the source system from DevLake data.

    DevLake prefixes IDs with the plugin name (e.g., "github:GithubPullRequest:1:123").
    Falls back to examining URL patterns.
    """
    row_id = str(devlake_row.get("id", ""))
    url = str(devlake_row.get("url", ""))

    if "github" in row_id.lower() or "github.com" in url.lower():
        return "github"
    if "gitlab" in row_id.lower() or "gitlab" in url.lower():
        return "gitlab"
    if "jira" in row_id.lower() or "atlassian.net" in url.lower():
        return "jira"
    if "azure" in row_id.lower() or "dev.azure.com" in url.lower():
        return "azure"
    return "unknown"


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a datetime value from DevLake, which may be string or datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
    return None


def _extract_repo_from_id(repo_id: str | None, url: str | None) -> str:
    """Extract a human-readable repo name from DevLake repo_id or URL."""
    if url:
        # Try to extract owner/repo from GitHub/GitLab URL
        match = re.search(r"(?:github\.com|gitlab\.com)/([^/]+/[^/]+?)(?:\.git)?(?:/|$)", url)
        if match:
            return match.group(1)
    if repo_id:
        # DevLake repo_id format: "github:GithubRepo:1:123" or similar
        return str(repo_id)
    return "unknown"


def _extract_project_key(issue_key: str | None, url: str | None) -> str:
    """Extract the project key from an issue key like 'BACK-123'."""
    if issue_key:
        parts = issue_key.split("-")
        if len(parts) >= 2:
            return parts[0].upper()
    if url and "atlassian.net" in url:
        match = re.search(r"/browse/([A-Z]+)-", url)
        if match:
            return match.group(1)
    return "UNKNOWN"


def normalize_status(raw_status: str, status_mapping: dict[str, str] | None = None) -> str:
    """Normalize a raw issue status to one of: todo, in_progress, done.

    Args:
        raw_status: The original status string from the source system.
        status_mapping: Optional custom mapping overriding defaults.

    Returns:
        Normalized status string.
    """
    mapping = {**DEFAULT_STATUS_MAPPING}
    if status_mapping:
        mapping.update({k.lower(): v for k, v in status_mapping.items()})

    normalized = mapping.get(raw_status.lower().strip())
    if normalized:
        return normalized

    logger.warning("Unknown status '%s' — defaulting to 'todo'", raw_status)
    return "todo"


def normalize_pull_request(
    devlake_pr: dict[str, Any],
    tenant_id: UUID,
) -> dict[str, Any]:
    """Normalize a DevLake pull_request row into PULSE EngPullRequest fields.

    Args:
        devlake_pr: Raw dict from DevLake pull_requests table.
        tenant_id: The PULSE tenant UUID.

    Returns:
        Dict matching EngPullRequest model columns.
    """
    source = _detect_source(devlake_pr)
    repo = _extract_repo_from_id(
        devlake_pr.get("base_repo_id"),
        devlake_pr.get("url"),
    )

    status = str(devlake_pr.get("status", "")).upper()
    if status == "MERGED":
        state = "merged"
    elif status == "CLOSED":
        state = "closed"
    elif status == "OPEN":
        state = "open"
    else:
        state = status.lower() if status else "open"

    created_date = _parse_datetime(devlake_pr.get("created_date"))
    merged_date = _parse_datetime(devlake_pr.get("merged_date"))

    return {
        "external_id": str(devlake_pr["id"]),
        "tenant_id": tenant_id,
        "source": source,
        "repo": repo,
        "title": devlake_pr.get("title", ""),
        "author": devlake_pr.get("author_name", "unknown"),
        "state": state,
        "first_commit_at": created_date,  # DevLake doesn't have first_commit; use created_date
        "first_review_at": None,  # Not available from DevLake domain table
        "approved_at": None,
        "merged_at": merged_date,
        "deployed_at": None,  # Linked via deployment data later
        "additions": devlake_pr.get("additions", 0) or 0,
        "deletions": devlake_pr.get("deletions", 0) or 0,
        "files_changed": 0,  # Not in DevLake domain table
        "reviewers": [],
        "linked_issue_ids": [],
        "created_at": created_date or datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def normalize_issue(
    devlake_issue: dict[str, Any],
    tenant_id: UUID,
    status_mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize a DevLake issue row into PULSE EngIssue fields.

    Args:
        devlake_issue: Raw dict from DevLake issues table.
        tenant_id: The PULSE tenant UUID.
        status_mapping: Optional custom status mapping.

    Returns:
        Dict matching EngIssue model columns.
    """
    raw_status = devlake_issue.get("original_status") or devlake_issue.get("status", "")
    normalized = normalize_status(raw_status, status_mapping)

    issue_key = devlake_issue.get("issue_key", "")
    project_key = _extract_project_key(issue_key, devlake_issue.get("url"))

    created_date = _parse_datetime(devlake_issue.get("created_date"))
    resolution_date = _parse_datetime(devlake_issue.get("resolution_date"))

    # Determine started_at: if in_progress or done, use created_date as fallback
    started_at = None
    if normalized in ("in_progress", "done"):
        started_at = created_date  # Best approximation without transition history

    completed_at = resolution_date if normalized == "done" else None

    # Determine issue type
    raw_type = str(devlake_issue.get("type", "task")).lower()
    if "bug" in raw_type:
        issue_type = "bug"
    elif "story" in raw_type or "user story" in raw_type:
        issue_type = "story"
    elif "epic" in raw_type:
        issue_type = "epic"
    elif "sub" in raw_type:
        issue_type = "subtask"
    else:
        issue_type = "task"

    return {
        "external_id": str(devlake_issue["id"]),
        "tenant_id": tenant_id,
        "source": _detect_source(devlake_issue),
        "project_key": project_key,
        "title": devlake_issue.get("title", ""),
        "type": issue_type,
        "status": raw_status,
        "normalized_status": normalized,
        "assignee": devlake_issue.get("assignee_name"),
        "labels": [],
        "story_points": devlake_issue.get("story_point"),
        "sprint_id": None,  # Linked separately via sprint_issues
        "status_transitions": [],  # DevLake domain table doesn't have transitions
        "started_at": started_at,
        "completed_at": completed_at,
        "created_at": created_date or datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def normalize_deployment(
    devlake_deploy: dict[str, Any],
    tenant_id: UUID,
) -> dict[str, Any]:
    """Normalize a DevLake cicd_deployment_commit row into PULSE EngDeployment fields.

    Args:
        devlake_deploy: Raw dict from DevLake cicd_deployment_commits table.
        tenant_id: The PULSE tenant UUID.

    Returns:
        Dict matching EngDeployment model columns.
    """
    result = str(devlake_deploy.get("result", "")).upper()
    is_failure = result in ("FAILURE", "FAILED", "ERROR")

    finished_date = _parse_datetime(devlake_deploy.get("finished_date"))
    started_date = _parse_datetime(devlake_deploy.get("started_date"))
    deployed_at = finished_date or started_date or datetime.now(timezone.utc)

    environment = str(devlake_deploy.get("environment", "production")).lower()
    if environment not in ("production", "staging", "dev", "development", "test"):
        environment = "production"

    repo = _extract_repo_from_id(
        devlake_deploy.get("repo_id"),
        None,
    )

    return {
        "external_id": str(devlake_deploy["id"]),
        "tenant_id": tenant_id,
        "source": _detect_source(devlake_deploy),
        "repo": repo,
        "environment": environment,
        "sha": devlake_deploy.get("merge_commit_sha", devlake_deploy.get("id", "unknown")),
        "author": "",  # Not directly in deployment_commits
        "is_failure": is_failure,
        "deployed_at": deployed_at,
        "recovery_time_hours": None,  # Calculated by metrics worker
        "created_at": deployed_at,
        "updated_at": datetime.now(timezone.utc),
    }


def normalize_sprint(
    devlake_sprint: dict[str, Any],
    tenant_id: UUID,
    sprint_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize a DevLake sprint row into PULSE EngSprint fields.

    Args:
        devlake_sprint: Raw dict from DevLake sprints table.
        tenant_id: The PULSE tenant UUID.
        sprint_issues: Optional list of issues in the sprint for calculating counts.

    Returns:
        Dict matching EngSprint model columns.
    """
    started_date = _parse_datetime(devlake_sprint.get("started_date"))
    ended_date = _parse_datetime(devlake_sprint.get("ended_date"))

    # Calculate sprint metrics from issues if available
    committed_items = 0
    committed_points = 0.0
    completed_items = 0
    completed_points = 0.0
    carried_over_items = 0

    if sprint_issues:
        committed_items = len(sprint_issues)
        for issue in sprint_issues:
            points = issue.get("story_point") or 0
            committed_points += float(points)
            resolution = issue.get("resolution_date")
            status = str(issue.get("status", "")).lower()
            if resolution or status in ("done", "closed", "resolved"):
                completed_items += 1
                completed_points += float(points)

        # Carryover: items not completed when sprint has ended
        if ended_date and ended_date < datetime.now(timezone.utc):
            carried_over_items = committed_items - completed_items
            if carried_over_items < 0:
                carried_over_items = 0

    return {
        "external_id": str(devlake_sprint["id"]),
        "tenant_id": tenant_id,
        "source": _detect_source(devlake_sprint),
        "name": devlake_sprint.get("name", ""),
        "board_id": str(devlake_sprint.get("board_id", "")),
        "started_at": started_date,
        "completed_at": ended_date,
        "goal": None,  # Not in DevLake domain table
        "committed_items": committed_items,
        "committed_points": committed_points,
        "added_items": 0,  # Requires tracking scope changes over time
        "removed_items": 0,
        "completed_items": completed_items,
        "completed_points": completed_points,
        "carried_over_items": carried_over_items,
        "created_at": started_date or datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def link_issues_to_prs(
    prs: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Link issues to PRs by matching issue keys in branch names.

    Scans PR branch names (head_ref or title) for patterns like "PROJ-123"
    and links them to matching issues via their external_id/issue_key.

    Args:
        prs: List of normalized PR dicts (with head_ref from DevLake).
        issues: List of normalized issue dicts (with external_id containing issue key).

    Returns:
        Updated PR dicts with linked_issue_ids populated.
    """
    # Build issue key -> issue external_id lookup
    issue_key_map: dict[str, str] = {}
    for issue in issues:
        ext_id = issue.get("external_id", "")
        # Try to extract issue key from the external_id
        match = ISSUE_KEY_PATTERN.search(ext_id)
        if match:
            issue_key_map[match.group(1).upper()] = ext_id

        # Also try project_key + number if available
        project_key = issue.get("project_key", "")
        if project_key and project_key != "UNKNOWN":
            # The issue_key would be like "BACK-123"
            key_match = ISSUE_KEY_PATTERN.search(ext_id)
            if key_match:
                issue_key_map[key_match.group(1).upper()] = ext_id

    if not issue_key_map:
        return prs

    linked_count = 0
    for pr in prs:
        linked_ids: list[str] = []
        # Search in title and branch name
        search_text = f"{pr.get('title', '')} {pr.get('_head_ref', '')} {pr.get('_base_ref', '')}"
        found_keys = ISSUE_KEY_PATTERN.findall(search_text)
        for key in found_keys:
            ext_id = issue_key_map.get(key.upper())
            if ext_id and ext_id not in linked_ids:
                linked_ids.append(ext_id)

        if linked_ids:
            pr["linked_issue_ids"] = linked_ids
            linked_count += 1

    logger.info("Linked %d PRs to issues via branch/title patterns", linked_count)
    return prs
