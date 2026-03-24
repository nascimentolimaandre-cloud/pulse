"""Pytest fixtures for pulse-data tests.

Provides test DB session, FastAPI test client, and sample data factories.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing FastAPI routes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def default_tenant_id() -> uuid.UUID:
    """The default tenant UUID used in MVP."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


class PullRequestFactory:
    """Factory for creating sample pull request dicts."""

    @staticmethod
    def create(
        *,
        external_id: str = "pr-1",
        source: str = "github",
        repo: str = "org/repo",
        title: str = "feat: add feature",
        author: str = "dev1",
        state: str = "merged",
        first_commit_at: datetime | None = None,
        merged_at: datetime | None = None,
        deployed_at: datetime | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "external_id": external_id,
            "source": source,
            "repo": repo,
            "title": title,
            "author": author,
            "state": state,
            "first_commit_at": first_commit_at or now,
            "merged_at": merged_at or now,
            "deployed_at": deployed_at,
            "additions": 50,
            "deletions": 10,
            "files_changed": 3,
            "reviewers": ["reviewer1"],
            "linked_issue_ids": [],
        }


class DeploymentFactory:
    """Factory for creating sample deployment dicts."""

    @staticmethod
    def create(
        *,
        external_id: str = "deploy-1",
        source: str = "github",
        repo: str = "org/repo",
        environment: str = "production",
        is_failure: bool = False,
        deployed_at: datetime | None = None,
        recovery_time_hours: float | None = None,
    ) -> dict:
        return {
            "external_id": external_id,
            "source": source,
            "repo": repo,
            "environment": environment,
            "sha": "abc123def456",
            "author": "dev1",
            "is_failure": is_failure,
            "deployed_at": deployed_at or datetime.now(timezone.utc),
            "recovery_time_hours": recovery_time_hours,
        }


class IssueFactory:
    """Factory for creating sample issue dicts."""

    @staticmethod
    def create(
        *,
        external_id: str = "PROJ-1",
        source: str = "jira",
        project_key: str = "PROJ",
        title: str = "Implement feature X",
        type: str = "story",
        status: str = "Done",
        normalized_status: str = "done",
    ) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "external_id": external_id,
            "source": source,
            "project_key": project_key,
            "title": title,
            "type": type,
            "status": status,
            "normalized_status": normalized_status,
            "assignee": "dev1",
            "labels": ["backend"],
            "story_points": 3.0,
            "sprint_id": None,
            "status_transitions": [],
            "created_at": now,
            "started_at": now,
            "completed_at": now,
        }


class SprintFactory:
    """Factory for creating sample sprint dicts."""

    @staticmethod
    def create(
        *,
        external_id: str = "sprint-1",
        name: str = "Sprint 1",
        committed_items: int = 10,
        completed_items: int = 8,
        committed_points: float = 20.0,
        completed_points: float = 16.0,
    ) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "external_id": external_id,
            "source": "jira",
            "name": name,
            "board_id": "board-1",
            "started_at": now,
            "completed_at": now,
            "goal": "Deliver feature X",
            "committed_items": committed_items,
            "committed_points": committed_points,
            "added_items": 2,
            "removed_items": 1,
            "completed_items": completed_items,
            "completed_points": completed_points,
            "carried_over_items": 1,
        }


@pytest.fixture
def pr_factory() -> type[PullRequestFactory]:
    return PullRequestFactory


@pytest.fixture
def deployment_factory() -> type[DeploymentFactory]:
    return DeploymentFactory


@pytest.fixture
def issue_factory() -> type[IssueFactory]:
    return IssueFactory


@pytest.fixture
def sprint_factory() -> type[SprintFactory]:
    return SprintFactory
