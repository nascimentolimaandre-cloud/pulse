"""Normalizer — transforms source connector data into PULSE schema.

Pure functions that map connector output dicts into PULSE's
eng_pull_requests, eng_issues, eng_deployments, eng_sprints models.

Connector output format is compatible with the original DevLake domain
table structure, so this normalizer works with both DevLake and direct
API connectors (GitHub, Jira, Jenkins).

Also handles:
- Status mapping (raw Jira/GitHub statuses to normalized todo/in_progress/done)
- Issue-to-PR linking via branch name regex patterns (e.g., "PROJ-123")
- Source detection from connector IDs/URLs
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
    # Portuguese statuses (Webmotors Jira — defensive fallback)
    "refinado": "todo",
    "quebra de histórias": "todo",
    "em design": "in_progress",
    "em imersão": "in_progress",
    "em desenvolvimento": "in_progress",
    "aguardando code review": "in_review",
    "em code review": "in_review",
    "planejando testes": "in_review",
    "em teste azul": "in_review",
    "aguardando teste azul": "in_review",
    "em teste hml": "in_review",
    "aguardando deploy produção": "done",
    "concluído": "done",
    "cancelado": "done",
    "em andamento": "in_progress",
    "testando": "in_review",
    "fechado": "done",
    "product review": "in_review",
    # Kanban upstream / waiting stages
    "priorizado": "todo",
    "aguardando histórias": "todo",
    "aguardando desenvolvimento": "todo",
    "priorizado gp": "todo",
    "pronto para o gp": "todo",
    # Active work / pre-dev analysis
    "construção de hipótese": "in_progress",
    "desenvolvimento": "in_progress",
    "design": "in_progress",
    "analise": "in_progress",
    "discovery": "in_progress",
    "entendimento": "in_progress",
    # Post-deploy
    "pós-implantação": "done",
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
    if "jenkins" in row_id.lower() or "jenkins" in url.lower():
        return "jenkins"
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


def build_status_transitions(
    changelogs: list[dict[str, Any]],
    status_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert DevLake issue_changelogs into PULSE status_transitions JSONB.

    Args:
        changelogs: Sorted list of changelog dicts with keys:
            from_status, to_status, created_date
        status_mapping: Optional custom mapping for normalization.

    Returns:
        List of transition dicts:
        [{"status": "in_progress", "entered_at": "...", "exited_at": "..."}, ...]
    """
    if not changelogs:
        return []

    transitions: list[dict[str, Any]] = []
    for i, cl in enumerate(changelogs):
        entered_at = _parse_datetime(cl["created_date"])
        to_status_raw = cl.get("to_status", "")
        normalized = normalize_status(to_status_raw, status_mapping)

        # exited_at is the entered_at of the next transition, or None if current
        exited_at = None
        if i + 1 < len(changelogs):
            exited_at = _parse_datetime(changelogs[i + 1]["created_date"])

        transitions.append({
            "status": normalized,
            "entered_at": entered_at.isoformat() if entered_at else None,
            "exited_at": exited_at.isoformat() if exited_at else None,
        })

    return transitions


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

    # Enrichment fields from GitHub connector (prefixed with underscore)
    first_review_at = _parse_datetime(devlake_pr.get("_first_review_at"))
    approved_at = _parse_datetime(devlake_pr.get("_approved_at"))
    files_changed = devlake_pr.get("_files_changed", 0) or 0
    commits_count = devlake_pr.get("_commits_count", 0) or 0
    reviewers = devlake_pr.get("_reviewers", []) or []

    # is_merged: true when PR has a merged_date
    is_merged = merged_date is not None

    return {
        "external_id": str(devlake_pr["id"]),
        "tenant_id": tenant_id,
        "source": source,
        "repo": repo,
        "title": devlake_pr.get("title", ""),
        "author": devlake_pr.get("author_name", "unknown"),
        "state": state,
        "is_merged": is_merged,
        "first_commit_at": created_date,  # Use created_date as proxy for first commit
        "first_review_at": first_review_at,
        "approved_at": approved_at,
        "merged_at": merged_date,
        "deployed_at": None,  # Linked via deployment data later
        "additions": devlake_pr.get("additions", 0) or 0,
        "deletions": devlake_pr.get("deletions", 0) or 0,
        "files_changed": files_changed,
        "commits_count": commits_count,
        "reviewers": reviewers,
        "linked_issue_ids": [],
        "created_at": created_date or datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def normalize_issue(
    devlake_issue: dict[str, Any],
    tenant_id: UUID,
    status_mapping: dict[str, str] | None = None,
    changelogs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize a DevLake issue row into PULSE EngIssue fields.

    Args:
        devlake_issue: Raw dict from DevLake issues table.
        tenant_id: The PULSE tenant UUID.
        status_mapping: Optional custom status mapping.
        changelogs: Optional status transition changelogs from DevLake.

    Returns:
        Dict matching EngIssue model columns.
    """
    raw_status = devlake_issue.get("original_status") or devlake_issue.get("status", "")
    normalized = normalize_status(raw_status, status_mapping)

    issue_key = devlake_issue.get("issue_key", "")
    project_key = _extract_project_key(issue_key, devlake_issue.get("url"))

    created_date = _parse_datetime(devlake_issue.get("created_date"))
    resolution_date = _parse_datetime(devlake_issue.get("resolution_date"))

    # Build status transitions from changelog data (populated by Jira plugin)
    transitions = build_status_transitions(changelogs or [], status_mapping)

    # Derive started_at from first transition to an active state
    started_at = None
    for t in transitions:
        if t["status"] in ("in_progress", "in_review"):
            started_at = _parse_datetime(t["entered_at"])
            break
    # Fallback: if in_progress/done but no transition found, use created_date
    if started_at is None and normalized in ("in_progress", "done"):
        started_at = created_date

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

    # sprint_id from DevLake join (sprint_issues table)
    sprint_id_raw = devlake_issue.get("sprint_id")
    sprint_id = str(sprint_id_raw) if sprint_id_raw else None

    return {
        "external_id": str(devlake_issue["id"]),
        "tenant_id": tenant_id,
        "source": _detect_source(devlake_issue),
        "project_key": project_key,
        "issue_key": (issue_key or None),
        "title": devlake_issue.get("title", ""),
        "issue_type": issue_type,
        "status": raw_status,
        "normalized_status": normalized,
        "assignee": devlake_issue.get("assignee_name"),
        "story_points": devlake_issue.get("story_point"),
        "sprint_id": sprint_id,
        "status_transitions": transitions,
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

    Handles data from GitHub Actions, GitLab CI, Azure Pipelines, and Jenkins.
    DevLake's Jenkins plugin normalizes builds into the same cicd_deployment_commits
    table, so the schema is consistent — but some fields differ:

    - Jenkins: `result` can be SUCCESS/FAILURE/UNSTABLE/ABORTED/NOT_BUILT
    - Jenkins: `name` contains the job name (useful for repo/project mapping)
    - Jenkins: `environment` is derived from deploymentPattern/productionPattern
      configured in the scope (connections.yaml)

    Args:
        devlake_deploy: Raw dict from DevLake cicd_deployment_commits table.
        tenant_id: The PULSE tenant UUID.

    Returns:
        Dict matching EngDeployment model columns.
    """
    result = str(devlake_deploy.get("result", "")).upper()
    # Jenkins UNSTABLE = tests failed but build completed; treat as failure for DORA CFR
    is_failure = result in ("FAILURE", "FAILED", "ERROR", "UNSTABLE")

    finished_date = _parse_datetime(devlake_deploy.get("finished_date"))
    started_date = _parse_datetime(devlake_deploy.get("started_date"))
    deployed_at = finished_date or started_date or datetime.now(timezone.utc)

    environment = str(devlake_deploy.get("environment", "production")).lower()
    if environment not in ("production", "staging", "dev", "development", "test"):
        environment = "production"

    source = _detect_source(devlake_deploy)

    # For Jenkins, the job name (in `name` field) serves as a proxy for repo
    # since Jenkins jobs are typically mapped 1:1 to repos
    if source == "jenkins":
        repo = str(devlake_deploy.get("name", "")) or _extract_repo_from_id(
            devlake_deploy.get("repo_id"), None
        )
    else:
        repo = _extract_repo_from_id(
            devlake_deploy.get("repo_id"),
            None,
        )

    return {
        "external_id": str(devlake_deploy["id"]),
        "tenant_id": tenant_id,
        "source": source,
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
        "board_id": str(devlake_sprint.get("original_board_id", "")),
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


def build_issue_key_map(
    issue_rows: list[tuple[str | None, str]],
) -> dict[str, str]:
    """Build a dict mapping issue key (e.g. 'ANCR-1234') to external_id.

    Used by the PR linking step to avoid re-extracting keys on every batch.

    Args:
        issue_rows: List of (issue_key, external_id) tuples from eng_issues.
            issue_key may be None for legacy rows — in that case, the function
            falls back to regex-extracting a key from the external_id (works
            only for sources where external_id contains the key; Jira numeric
            IDs will be skipped).

    Returns:
        Dict {"ANCR-1234": "jira:JiraIssue:1:792543", ...} — keys uppercased.
    """
    key_map: dict[str, str] = {}
    for issue_key, ext_id in issue_rows:
        if not ext_id:
            continue
        # Prefer the explicit issue_key column (populated since migration 005)
        if issue_key:
            key_map[issue_key.upper()] = ext_id
            continue
        # Fallback: extract from external_id for non-Jira sources or legacy rows
        match = ISSUE_KEY_PATTERN.search(ext_id)
        if match:
            key_map[match.group(1).upper()] = ext_id
    return key_map


def apply_pr_issue_links(
    prs: list[dict[str, Any]],
    issue_key_map: dict[str, str],
) -> int:
    """Populate `linked_issue_ids` on each PR by scanning title/branch refs.

    Mutates PRs in place. Returns number of PRs that received at least one link.

    Scanned text: title + _head_ref + _base_ref (the last two are enrichment
    fields injected by the sync worker pre-normalization).
    """
    if not issue_key_map:
        return 0

    linked_count = 0
    for pr in prs:
        search_text = (
            f"{pr.get('title', '')} "
            f"{pr.get('_head_ref', '')} "
            f"{pr.get('_base_ref', '')}"
        )
        found_keys = ISSUE_KEY_PATTERN.findall(search_text)
        linked_ids: list[str] = []
        seen: set[str] = set()
        for key in found_keys:
            k = key.upper()
            if k in seen:
                continue
            seen.add(k)
            ext_id = issue_key_map.get(k)
            if ext_id:
                linked_ids.append(ext_id)

        if linked_ids:
            pr["linked_issue_ids"] = linked_ids
            linked_count += 1
    return linked_count


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
