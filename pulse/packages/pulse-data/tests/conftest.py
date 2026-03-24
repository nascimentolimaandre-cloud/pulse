"""Pytest fixtures for pulse-data unit tests.

Provides reusable fixtures of domain dataclasses and raw DevLake dicts.
These fixtures are pure data — no IO, no DB, no Kafka.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.contexts.metrics.domain.dora import DeploymentData, PullRequestData
from src.contexts.metrics.domain.lean import IssueFlowData
from src.contexts.metrics.domain.cycle_time import PullRequestCycleData
from src.contexts.metrics.domain.sprint import SprintData
from src.contexts.metrics.domain.throughput import PullRequestThroughputData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Convenience: build a UTC-aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DORA domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_deployments() -> list[DeploymentData]:
    """Mix of successful and failed deployments across an 8-week window."""
    return [
        DeploymentData(deployed_at=_dt(2024, 1, 2), is_failure=False, recovery_time_hours=None),
        DeploymentData(deployed_at=_dt(2024, 1, 5), is_failure=True, recovery_time_hours=2.0),
        DeploymentData(deployed_at=_dt(2024, 1, 9), is_failure=False, recovery_time_hours=None),
        DeploymentData(deployed_at=_dt(2024, 1, 15), is_failure=False, recovery_time_hours=None),
        DeploymentData(deployed_at=_dt(2024, 1, 22), is_failure=True, recovery_time_hours=6.0),
        DeploymentData(deployed_at=_dt(2024, 1, 29), is_failure=False, recovery_time_hours=None),
        DeploymentData(deployed_at=_dt(2024, 2, 5), is_failure=False, recovery_time_hours=None),
        DeploymentData(deployed_at=_dt(2024, 2, 12), is_failure=True, recovery_time_hours=0.5),
        DeploymentData(deployed_at=_dt(2024, 2, 19), is_failure=False, recovery_time_hours=None),
        DeploymentData(deployed_at=_dt(2024, 2, 26), is_failure=False, recovery_time_hours=None),
    ]


@pytest.fixture
def sample_pull_requests() -> list[PullRequestData]:
    """PRs with various lead times: some with deployed_at, some without."""
    return [
        # 4-hour lead time (ELITE)
        PullRequestData(
            first_commit_at=_dt(2024, 1, 2, 8),
            merged_at=_dt(2024, 1, 2, 10),
            deployed_at=_dt(2024, 1, 2, 12),
        ),
        # 48-hour lead time (HIGH)
        PullRequestData(
            first_commit_at=_dt(2024, 1, 8, 9),
            merged_at=_dt(2024, 1, 9, 11),
            deployed_at=_dt(2024, 1, 10, 9),
        ),
        # ~240-hour lead time (MEDIUM) — uses merged_at as fallback (no deployed_at)
        PullRequestData(
            first_commit_at=_dt(2024, 1, 15, 10),
            merged_at=_dt(2024, 1, 25, 10),
            deployed_at=None,
        ),
        # Missing first_commit_at — should be excluded
        PullRequestData(
            first_commit_at=None,
            merged_at=_dt(2024, 1, 20, 12),
            deployed_at=_dt(2024, 1, 21, 12),
        ),
        # Missing both endpoints — should be excluded
        PullRequestData(
            first_commit_at=_dt(2024, 1, 25, 8),
            merged_at=None,
            deployed_at=None,
        ),
    ]


# ---------------------------------------------------------------------------
# Lean domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_issues() -> list[IssueFlowData]:
    """Issues with status transitions covering all normalized statuses."""
    return [
        IssueFlowData(
            issue_id="ISS-1",
            normalized_status="done",
            status_transitions=[
                {"status": "todo", "entered_at": _dt(2024, 1, 2), "exited_at": _dt(2024, 1, 3)},
                {"status": "in_progress", "entered_at": _dt(2024, 1, 3), "exited_at": _dt(2024, 1, 6)},
                {"status": "in_review", "entered_at": _dt(2024, 1, 6), "exited_at": _dt(2024, 1, 7)},
                {"status": "done", "entered_at": _dt(2024, 1, 7), "exited_at": None},
            ],
            created_at=_dt(2024, 1, 2),
            started_at=_dt(2024, 1, 3),
            completed_at=_dt(2024, 1, 7),
            lead_time_hours=120.0,  # 5 days
        ),
        IssueFlowData(
            issue_id="ISS-2",
            normalized_status="done",
            status_transitions=[
                {"status": "todo", "entered_at": _dt(2024, 1, 3), "exited_at": _dt(2024, 1, 5)},
                {"status": "in_progress", "entered_at": _dt(2024, 1, 5), "exited_at": _dt(2024, 1, 9)},
                {"status": "done", "entered_at": _dt(2024, 1, 9), "exited_at": None},
            ],
            created_at=_dt(2024, 1, 3),
            started_at=_dt(2024, 1, 5),
            completed_at=_dt(2024, 1, 9),
            lead_time_hours=144.0,  # 6 days
        ),
        IssueFlowData(
            issue_id="ISS-3",
            normalized_status="in_progress",
            status_transitions=[
                {"status": "todo", "entered_at": _dt(2024, 1, 8), "exited_at": _dt(2024, 1, 10)},
                {"status": "in_progress", "entered_at": _dt(2024, 1, 10), "exited_at": None},
            ],
            created_at=_dt(2024, 1, 8),
            started_at=_dt(2024, 1, 10),
            completed_at=None,
            lead_time_hours=None,
        ),
        IssueFlowData(
            issue_id="ISS-4",
            normalized_status="in_review",
            status_transitions=[
                {"status": "todo", "entered_at": _dt(2024, 1, 9), "exited_at": _dt(2024, 1, 11)},
                {"status": "in_progress", "entered_at": _dt(2024, 1, 11), "exited_at": _dt(2024, 1, 12)},
                {"status": "in_review", "entered_at": _dt(2024, 1, 12), "exited_at": None},
            ],
            created_at=_dt(2024, 1, 9),
            started_at=_dt(2024, 1, 11),
            completed_at=None,
            lead_time_hours=None,
        ),
        IssueFlowData(
            issue_id="ISS-5",
            normalized_status="todo",
            status_transitions=[],
            created_at=_dt(2024, 1, 10),
            started_at=None,
            completed_at=None,
            lead_time_hours=None,
        ),
    ]


# ---------------------------------------------------------------------------
# Cycle time domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_cycle_prs() -> list[PullRequestCycleData]:
    """PRs with complete lifecycle timestamps for cycle time breakdown tests."""
    return [
        PullRequestCycleData(
            pr_id="PR-1",
            first_commit_at=_dt(2024, 1, 2, 9),
            first_review_at=_dt(2024, 1, 2, 17),   # 8h coding
            approved_at=_dt(2024, 1, 3, 9),          # 16h pickup
            merged_at=_dt(2024, 1, 3, 11),           # 2h review
            deployed_at=_dt(2024, 1, 3, 13),         # 2h deploy
        ),
        PullRequestCycleData(
            pr_id="PR-2",
            first_commit_at=_dt(2024, 1, 8, 10),
            first_review_at=_dt(2024, 1, 9, 10),    # 24h coding
            approved_at=_dt(2024, 1, 9, 14),         # 4h pickup
            merged_at=_dt(2024, 1, 9, 16),           # 2h review
            deployed_at=_dt(2024, 1, 10, 10),        # 18h deploy
        ),
        PullRequestCycleData(
            pr_id="PR-3",
            first_commit_at=_dt(2024, 1, 15, 8),
            first_review_at=_dt(2024, 1, 15, 16),   # 8h coding
            approved_at=_dt(2024, 1, 16, 10),        # 18h pickup
            merged_at=_dt(2024, 1, 16, 12),          # 2h review
            deployed_at=None,                         # no deploy timestamp
        ),
        # PR missing first_review_at — only total is calculable (via merged_at fallback)
        PullRequestCycleData(
            pr_id="PR-4",
            first_commit_at=_dt(2024, 1, 22, 9),
            first_review_at=None,
            approved_at=None,
            merged_at=_dt(2024, 1, 24, 9),          # 48h total
            deployed_at=None,
        ),
    ]


# ---------------------------------------------------------------------------
# Sprint domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_sprints() -> list[SprintData]:
    """Three sprints ordered oldest to newest — velocity improving."""
    return [
        SprintData(
            sprint_id="SP-1",
            name="Sprint 1",
            committed_items=10,
            committed_points=20.0,
            added_items=1,
            removed_items=0,
            completed_items=8,
            completed_points=16.0,
            carried_over_items=2,
        ),
        SprintData(
            sprint_id="SP-2",
            name="Sprint 2",
            committed_items=10,
            committed_points=20.0,
            added_items=2,
            removed_items=1,
            completed_items=9,
            completed_points=18.0,
            carried_over_items=1,
        ),
        SprintData(
            sprint_id="SP-3",
            name="Sprint 3",
            committed_items=12,
            committed_points=24.0,
            added_items=0,
            removed_items=0,
            completed_items=12,
            completed_points=24.0,
            carried_over_items=0,
        ),
    ]


# ---------------------------------------------------------------------------
# Throughput domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_throughput_prs() -> list[PullRequestThroughputData]:
    """PRs with size and cycle time data for throughput analytics tests."""
    return [
        PullRequestThroughputData(
            pr_id="PR-1",
            repo="org/backend",
            merged_at=_dt(2024, 1, 3),
            additions=5,
            deletions=2,
            files_changed=2,
            cycle_time_hours=8.0,
            reviewer_count=1,
        ),
        PullRequestThroughputData(
            pr_id="PR-2",
            repo="org/backend",
            merged_at=_dt(2024, 1, 4),
            additions=30,
            deletions=10,
            files_changed=5,
            cycle_time_hours=24.0,
            reviewer_count=2,
        ),
        PullRequestThroughputData(
            pr_id="PR-3",
            repo="org/frontend",
            merged_at=_dt(2024, 1, 10),
            additions=120,
            deletions=40,
            files_changed=10,
            cycle_time_hours=48.0,
            reviewer_count=1,
        ),
        PullRequestThroughputData(
            pr_id="PR-4",
            repo="org/backend",
            merged_at=_dt(2024, 1, 11),
            additions=300,
            deletions=100,
            files_changed=20,
            cycle_time_hours=72.0,
            reviewer_count=3,
        ),
        PullRequestThroughputData(
            pr_id="PR-5",
            repo="org/infra",
            merged_at=_dt(2024, 1, 17),
            additions=600,
            deletions=200,
            files_changed=30,
            cycle_time_hours=None,
            reviewer_count=2,
        ),
        PullRequestThroughputData(
            pr_id="PR-6",
            repo="org/backend",
            merged_at=_dt(2024, 1, 18),
            additions=1200,
            deletions=400,
            files_changed=50,
            cycle_time_hours=96.0,
            reviewer_count=4,
        ),
    ]


# ---------------------------------------------------------------------------
# Raw DevLake dict fixtures (for normalizer tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_devlake_pr() -> dict:
    """A realistic raw DevLake pull_request row (dict from DB)."""
    return {
        "id": "github:GithubPullRequest:1:42",
        "base_repo_id": "github:GithubRepo:1:99",
        "head_repo_id": "github:GithubRepo:1:99",
        "status": "MERGED",
        "title": "feat(BACK-123): add user authentication",
        "url": "https://github.com/org/backend/pull/42",
        "author_name": "alice",
        "created_date": "2024-01-10T09:00:00Z",
        "merged_date": "2024-01-11T15:30:00Z",
        "closed_date": None,
        "merge_commit_sha": "abc123def456789",
        "base_ref": "main",
        "head_ref": "feature/BACK-123-user-auth",
        "additions": 150,
        "deletions": 30,
    }


@pytest.fixture
def sample_devlake_issue() -> dict:
    """A realistic raw DevLake issue row (dict from DB)."""
    return {
        "id": "BACK-456",
        "url": "https://mycompany.atlassian.net/browse/BACK-456",
        "issue_key": "BACK-456",
        "title": "Implement JWT token refresh",
        "status": "Done",
        "original_status": "Done",
        "story_point": 5,
        "priority": "High",
        "created_date": "2024-01-08T10:00:00Z",
        "resolution_date": "2024-01-12T16:00:00Z",
        "lead_time_minutes": 5760,
        "assignee_name": "bob",
        "type": "Story",
    }


@pytest.fixture
def sample_devlake_deployment() -> dict:
    """A realistic raw DevLake cicd_deployment_commit row."""
    return {
        "id": "github:GithubRun:1:789",
        "cicd_deployment_id": "github:GithubDeployment:1:789",
        "repo_id": "github:GithubRepo:1:99",
        "name": "deploy-production",
        "result": "SUCCESS",
        "status": "DONE",
        "environment": "production",
        "created_date": "2024-01-11T15:00:00Z",
        "started_date": "2024-01-11T15:10:00Z",
        "finished_date": "2024-01-11T15:25:00Z",
    }


@pytest.fixture
def sample_devlake_sprint() -> dict:
    """A realistic raw DevLake sprint row."""
    return {
        "id": "jira:Sprint:1:42",
        "board_id": "jira:Board:1:10",
        "name": "Sprint 5",
        "url": "https://mycompany.atlassian.net/jira/software/projects/BACK/boards/10/sprint/42",
        "status": "CLOSED",
        "started_date": "2024-01-08T09:00:00Z",
        "ended_date": "2024-01-22T18:00:00Z",
    }


# ---------------------------------------------------------------------------
# Tenant ID fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def default_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")
