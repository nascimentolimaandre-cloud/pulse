"""Initial engineering data schema.

Creates tables for BC2 (integration_connections), BC3 (eng_pull_requests,
eng_issues, eng_deployments, eng_sprints), and BC4 (metrics_snapshots).
Enables Row-Level Security on all tables using app.current_tenant.

Revision ID: 001_initial_eng
Revises: None
Create Date: 2026-03-24

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "001_initial_eng"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# All tables that this migration creates — used for RLS and downgrade
# ---------------------------------------------------------------------------
ALL_TABLES = [
    "integration_connections",
    "eng_pull_requests",
    "eng_issues",
    "eng_deployments",
    "eng_sprints",
    "metrics_snapshots",
]


def _enable_rls(table: str) -> None:
    """Enable RLS and create SELECT / INSERT / UPDATE / DELETE policies."""
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')

    for action, clause in [
        ("SELECT", "USING"),
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ]:
        op.execute(
            f"""
            CREATE POLICY "{table}_{action.lower()}_tenant" ON "{table}"
                FOR {action} {clause} (
                    "tenant_id" = current_setting('app.current_tenant')::uuid
                );
            """
        )


def _drop_rls(table: str) -> None:
    """Drop all RLS policies and disable RLS for a table."""
    for action in ("select", "insert", "update", "delete"):
        op.execute(f'DROP POLICY IF EXISTS "{table}_{action}_tenant" ON "{table}"')
    op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. integration_connections (BC2)
    # ------------------------------------------------------------------
    op.create_table(
        "integration_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False, comment="github|gitlab|jira|azure_devops"),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("devlake_connection_id", sa.String(256), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ------------------------------------------------------------------
    # 2. eng_pull_requests (BC3)
    # ------------------------------------------------------------------
    op.create_table(
        "eng_pull_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("repo", sa.String(512), nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("author", sa.String(256), nullable=True),
        sa.Column("state", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("first_commit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("additions", sa.Integer, server_default="0"),
        sa.Column("deletions", sa.Integer, server_default="0"),
        sa.Column("files_changed", sa.Integer, server_default="0"),
        sa.Column("reviewers", JSONB, server_default="'[]'"),
        sa.Column("linked_issue_ids", JSONB, server_default="'[]'"),
        sa.Column("team_id", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Generated columns for PR lead time and cycle time
    op.execute("""
        ALTER TABLE "eng_pull_requests"
            ADD COLUMN "lead_time_hours" double precision
                GENERATED ALWAYS AS (
                    EXTRACT(EPOCH FROM ("deployed_at" - "first_commit_at")) / 3600
                ) STORED;
    """)
    op.execute("""
        ALTER TABLE "eng_pull_requests"
            ADD COLUMN "cycle_time_hours" double precision
                GENERATED ALWAYS AS (
                    EXTRACT(EPOCH FROM ("merged_at" - "first_commit_at")) / 3600
                ) STORED;
    """)

    # ------------------------------------------------------------------
    # 3. eng_issues (BC3)
    # ------------------------------------------------------------------
    op.create_table(
        "eng_issues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("project_key", sa.String(128), nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("type", sa.String(64), nullable=True),
        sa.Column("status", sa.String(128), nullable=True),
        sa.Column("normalized_status", sa.String(32), nullable=True),
        sa.Column("assignee", sa.String(256), nullable=True),
        sa.Column("labels", JSONB, server_default="'[]'"),
        sa.Column("story_points", sa.Float, nullable=True),
        sa.Column("sprint_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status_transitions", JSONB, server_default="'[]'"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Generated columns for issue lead time and cycle time
    op.execute("""
        ALTER TABLE "eng_issues"
            ADD COLUMN "lead_time_hours" double precision
                GENERATED ALWAYS AS (
                    EXTRACT(EPOCH FROM ("completed_at" - "created_at")) / 3600
                ) STORED;
    """)
    op.execute("""
        ALTER TABLE "eng_issues"
            ADD COLUMN "cycle_time_hours" double precision
                GENERATED ALWAYS AS (
                    EXTRACT(EPOCH FROM ("completed_at" - "started_at")) / 3600
                ) STORED;
    """)

    # ------------------------------------------------------------------
    # 4. eng_deployments (BC3)
    # ------------------------------------------------------------------
    op.create_table(
        "eng_deployments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("repo", sa.String(512), nullable=True),
        sa.Column("environment", sa.String(64), server_default="'production'"),
        sa.Column("sha", sa.String(64), nullable=True),
        sa.Column("author", sa.String(256), nullable=True),
        sa.Column("is_failure", sa.Boolean, server_default="false"),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovery_time_hours", sa.Float, nullable=True),
        sa.Column("team_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ------------------------------------------------------------------
    # 5. eng_sprints (BC3)
    # ------------------------------------------------------------------
    op.create_table(
        "eng_sprints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("board_id", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("goal", sa.Text, nullable=True),
        sa.Column("committed_items", sa.Integer, server_default="0"),
        sa.Column("committed_points", sa.Float, server_default="0"),
        sa.Column("added_items", sa.Integer, server_default="0"),
        sa.Column("removed_items", sa.Integer, server_default="0"),
        sa.Column("completed_items", sa.Integer, server_default="0"),
        sa.Column("completed_points", sa.Float, server_default="0"),
        sa.Column("carried_over_items", sa.Integer, server_default="0"),
        sa.Column("team_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ------------------------------------------------------------------
    # 6. metrics_snapshots (BC4)
    # ------------------------------------------------------------------
    op.create_table(
        "metrics_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("team_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metric_type", sa.String(32), nullable=False, comment="dora|lean|cycle_time|throughput|sprint"),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("granularity", sa.String(16), nullable=True, comment="daily|weekly|monthly"),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # UNIQUE constraint on metrics_snapshots
    op.create_unique_constraint(
        "uq_metrics_snapshots_tenant_team_type_period_gran",
        "metrics_snapshots",
        ["tenant_id", "team_id", "metric_type", "period_start", "granularity"],
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    # Unique composite indexes for deduplication on external sources
    op.create_index(
        "ix_eng_pull_requests_tenant_source_ext",
        "eng_pull_requests",
        ["tenant_id", "source", "external_id"],
        unique=True,
    )
    op.create_index(
        "ix_eng_issues_tenant_source_ext",
        "eng_issues",
        ["tenant_id", "source", "external_id"],
        unique=True,
    )

    # Composite index on metrics_snapshots for query performance
    op.create_index(
        "ix_metrics_snapshots_tenant_team_type_period",
        "metrics_snapshots",
        ["tenant_id", "team_id", "metric_type", "period_start"],
    )

    # Timestamp indexes for range queries
    op.create_index("ix_eng_pull_requests_merged_at", "eng_pull_requests", ["merged_at"])
    op.create_index("ix_eng_issues_completed_at", "eng_issues", ["completed_at"])
    op.create_index("ix_eng_deployments_deployed_at", "eng_deployments", ["deployed_at"])

    # ------------------------------------------------------------------
    # Row-Level Security policies (same pattern as IAM tables)
    # ------------------------------------------------------------------
    for table in ALL_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    # Drop RLS policies first
    for table in reversed(ALL_TABLES):
        _drop_rls(table)

    # Drop indexes (non-default ones created explicitly)
    op.drop_index("ix_eng_deployments_deployed_at", table_name="eng_deployments")
    op.drop_index("ix_eng_issues_completed_at", table_name="eng_issues")
    op.drop_index("ix_eng_pull_requests_merged_at", table_name="eng_pull_requests")
    op.drop_index("ix_metrics_snapshots_tenant_team_type_period", table_name="metrics_snapshots")
    op.drop_index("ix_eng_issues_tenant_source_ext", table_name="eng_issues")
    op.drop_index("ix_eng_pull_requests_tenant_source_ext", table_name="eng_pull_requests")
    op.drop_constraint("uq_metrics_snapshots_tenant_team_type_period_gran", "metrics_snapshots")

    # Drop tables in reverse dependency order
    op.drop_table("metrics_snapshots")
    op.drop_table("eng_sprints")
    op.drop_table("eng_deployments")
    op.drop_table("eng_issues")
    op.drop_table("eng_pull_requests")
    op.drop_table("integration_connections")
