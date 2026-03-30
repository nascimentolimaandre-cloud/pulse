"""SQLAlchemy models for BC3 — Engineering Data.

Tables: eng_pull_requests, eng_issues, eng_deployments, eng_sprints.
All tables enforce tenant_id (NOT NULL) for RLS.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, Uuid, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, column_property
from sqlalchemy import case, extract

from src.shared.models import TenantModel


class EngPullRequest(TenantModel):
    """Normalized pull request data from GitHub, GitLab, or Azure DevOps."""

    __tablename__ = "eng_pull_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_eng_pr_tenant_external"),
    )

    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # github | gitlab | azure
    repo: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)  # open | merged | closed | declined

    # Timestamps for cycle/lead time calculation
    first_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Size metrics
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships (stored as JSONB for flexibility)
    reviewers: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    linked_issue_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)


# Generated column properties — computed from timestamps, not stored
# lead_time_hours: first_commit_at -> deployed_at (or merged_at as fallback)
EngPullRequest.lead_time_hours = column_property(
    case(
        (
            EngPullRequest.deployed_at.isnot(None) & EngPullRequest.first_commit_at.isnot(None),
            extract("epoch", EngPullRequest.deployed_at - EngPullRequest.first_commit_at) / 3600.0,
        ),
        (
            EngPullRequest.merged_at.isnot(None) & EngPullRequest.first_commit_at.isnot(None),
            extract("epoch", EngPullRequest.merged_at - EngPullRequest.first_commit_at) / 3600.0,
        ),
        else_=None,
    )
)

# cycle_time_hours: first_commit_at -> merged_at
EngPullRequest.cycle_time_hours = column_property(
    case(
        (
            EngPullRequest.merged_at.isnot(None) & EngPullRequest.first_commit_at.isnot(None),
            extract("epoch", EngPullRequest.merged_at - EngPullRequest.first_commit_at) / 3600.0,
        ),
        else_=None,
    )
)


class EngIssue(TenantModel):
    """Normalized issue/work item from Jira, Linear, Azure DevOps Boards, etc."""

    __tablename__ = "eng_issues"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_eng_issue_tenant_external"),
    )

    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # jira | linear | azure
    project_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # bug | story | task | epic
    status: Mapped[str] = mapped_column(String(128), nullable=False)  # raw status from source
    normalized_status: Mapped[str] = mapped_column(String(32), nullable=False)  # todo | in_progress | done
    assignee: Mapped[str | None] = mapped_column(String(256), nullable=True)

    labels: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    story_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)

    # Status transition log for CFD / flow metrics
    status_transitions: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Generated column properties
# lead_time_hours: created_at -> completed_at
EngIssue.lead_time_hours = column_property(
    case(
        (
            EngIssue.completed_at.isnot(None),
            extract("epoch", EngIssue.completed_at - EngIssue.created_at) / 3600.0,
        ),
        else_=None,
    )
)

# cycle_time_hours: started_at -> completed_at
EngIssue.cycle_time_hours = column_property(
    case(
        (
            EngIssue.completed_at.isnot(None) & EngIssue.started_at.isnot(None),
            extract("epoch", EngIssue.completed_at - EngIssue.started_at) / 3600.0,
        ),
        else_=None,
    )
)


class EngDeployment(TenantModel):
    """Normalized deployment event from CI/CD pipelines."""

    __tablename__ = "eng_deployments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_eng_deploy_tenant_external"),
    )

    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # github | gitlab | azure | jenkins
    repo: Mapped[str] = mapped_column(String(512), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)  # production | staging | dev
    sha: Mapped[str] = mapped_column(String(512), nullable=True, default="")
    author: Mapped[str] = mapped_column(String(256), nullable=True, default="")
    is_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)


class EngSprint(TenantModel):
    """Normalized sprint data from Jira, Linear, Azure DevOps."""

    __tablename__ = "eng_sprints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_eng_sprint_tenant_external"),
    )

    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    board_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sprint metrics (populated by sync worker)
    committed_items: Mapped[int] = mapped_column(Integer, default=0)
    committed_points: Mapped[float] = mapped_column(Float, default=0.0)
    added_items: Mapped[int] = mapped_column(Integer, default=0)
    removed_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_points: Mapped[float] = mapped_column(Float, default=0.0)
    carried_over_items: Mapped[int] = mapped_column(Integer, default=0)
