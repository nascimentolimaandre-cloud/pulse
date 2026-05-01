"""SQLAlchemy models for BC3 — Engineering Data.

Tables: eng_pull_requests, eng_issues, eng_deployments, eng_sprints.
All tables enforce tenant_id (NOT NULL) for RLS.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, Uuid
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

    # FDD-OPS-001 L5 — sizes aligned with migration 002 schema.
    external_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # github | gitlab | azure
    repo: Mapped[str] = mapped_column(String(255), nullable=False)
    # FDD-OPS-001 L5 — `url` exists in DB schema (TEXT) but ORM lacked it.
    # Surfaced by the schema drift guard (INC-023#4 class).
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # FDD-OPS-001 L5 — DB has VARCHAR(255); ORM previously declared String(256)
    # which would cause INSERT failures for boundary-length authors.
    # Aligned to DB.
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    # FDD-OPS-001 L5 — DB has VARCHAR(50); aligned ORM up.
    state: Mapped[str] = mapped_column(String(50), nullable=False)  # open | merged | closed | declined

    # Timestamps for cycle/lead time calculation
    first_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # FDD-OPS-001 L5 — `closed_at` exists in DB but ORM lacked it.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Size metrics
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    commits_count: Mapped[int] = mapped_column(Integer, default=0)
    is_merged: Mapped[bool] = mapped_column(Boolean, default=False)

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

    # FDD-OPS-001 L5 — sizes aligned with migration 002 schema.
    external_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # jira | linear | azure
    project_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Human-readable issue key (e.g. "SECOM-1441"). Distinct from external_id,
    # which is the internal source ID (numeric for Jira). Used by PR linker
    # to match title/branch references back to issues.
    issue_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # FDD-OPS-001 L5 — `url` exists in DB but ORM lacked it.
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Plain-text description extracted from Jira ADF (Atlassian Document
    # Format) at ingestion. Capped at 4000 chars in the normalizer — see
    # jira_connector._extract_description_text() + backfill service.
    # NULL for legacy rows; API truncates to 300 chars before exposing.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FDD-OPS-001 L5 — sizes aligned with migration 002 schema.
    issue_type: Mapped[str] = mapped_column(String(100), nullable=False)  # bug | story | task | epic
    status: Mapped[str] = mapped_column(String(100), nullable=False)  # raw status from source
    normalized_status: Mapped[str] = mapped_column(String(50), nullable=False)  # todo | in_progress | done
    # FDD-OPS-001 L5 — `priority` exists in DB but ORM lacked it.
    priority: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)

    story_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)

    # Status transition log for CFD / flow metrics
    status_transitions: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # FDD-OPS-001 L5 — `linked_pr_ids` exists in DB but ORM lacked it.
    # Reverse of `eng_pull_requests.linked_issue_ids`: lists PR external_ids
    # that reference this issue. Populated by the PR linker.
    linked_pr_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

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

    # FDD-OPS-001 L5 — sizes aligned with actual DB schema.
    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # github | gitlab | azure | jenkins
    repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(100), nullable=True)  # production | staging | dev
    sha: Mapped[str | None] = mapped_column(String(512), nullable=True, default="")
    author: Mapped[str | None] = mapped_column(String(256), nullable=True, default="")
    is_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    # FDD-OPS-001 L5 — these columns exist in DB but ORM lacked them.
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trigger_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    # FDD-DSH-050 (INC-005) — MTTR incident pairing columns.
    # `recovered_by_deploy_id` points at the eng_deployments row whose
    # is_failure=false success resolved THIS failure (set on failure rows).
    # `superseded_by_deploy_id` is set when this row is a back-to-back
    # failure absorbed into an earlier incident anchor (avoids inflating
    # MTTR sample with multiple failures during one outage).
    # `incident_status` lifecycle: open → resolved | superseded.
    # NULL on success-only rows or rows that are not failure-anchors yet.
    recovered_by_deploy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    superseded_by_deploy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    incident_status: Mapped[str | None] = mapped_column(String(16), nullable=True)


class EngSprint(TenantModel):
    """Normalized sprint data from Jira, Linear, Azure DevOps."""

    __tablename__ = "eng_sprints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_eng_sprint_tenant_external"),
    )

    # FDD-OPS-001 L5 — sizes aligned with migration 002 schema:
    # external_id VARCHAR(500), source VARCHAR(50), name VARCHAR(255),
    # board_id VARCHAR(500). Previously ORM declared (512/32/256/128)
    # which would either reject INSERTs (when ORM larger than DB) or
    # cause type drift (when ORM stricter than DB). Surfaced by the
    # schema drift guard.
    external_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    board_id: Mapped[str] = mapped_column(String(500), nullable=False)
    # FDD-OPS-018 — sprint lifecycle: active | closed | future | NULL.
    # Was missing from the ORM model despite existing in the DB schema
    # (schema drift). Without this Mapped column, every attempt to upsert
    # `status` raised "Unconsumed column names: status" and the field
    # silently stayed empty for all 216 Webmotors sprints.
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
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
