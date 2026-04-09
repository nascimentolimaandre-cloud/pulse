"""Pipeline monitor tables — watermarks and sync log.

Creates tables for BC5 (pipeline_watermarks, pipeline_sync_log).
Enables Row-Level Security on both tables using app.current_tenant.

Revision ID: 002_pipeline_monitor
Revises: 001_initial_eng
Create Date: 2026-04-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "002_pipeline_monitor"
down_revision: Union[str, None] = "001_initial_eng"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# All tables that this migration creates — used for RLS and downgrade
# ---------------------------------------------------------------------------
ALL_TABLES = [
    "pipeline_watermarks",
    "pipeline_sync_log",
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
    # 1. pipeline_watermarks (BC5)
    # ------------------------------------------------------------------
    op.create_table(
        "pipeline_watermarks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=False, comment="pull_requests|issues|deployments|sprints"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("records_synced", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Unique constraint for upsert: one watermark per tenant + entity
    op.create_unique_constraint(
        "uq_watermark_entity",
        "pipeline_watermarks",
        ["tenant_id", "entity_type"],
    )

    # ------------------------------------------------------------------
    # 2. pipeline_sync_log (BC5)
    # ------------------------------------------------------------------
    op.create_table(
        "pipeline_sync_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, comment="running|completed|failed|partial"),
        sa.Column("trigger", sa.String(32), nullable=False, server_default="scheduled", comment="scheduled|manual|bootstrap"),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("records_processed", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("errors", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("error_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    op.create_index(
        "ix_watermarks_tenant_entity",
        "pipeline_watermarks",
        ["tenant_id", "entity_type"],
    )

    op.create_index(
        "ix_sync_log_tenant_started",
        "pipeline_sync_log",
        ["tenant_id", sa.text("started_at DESC")],
    )

    # ------------------------------------------------------------------
    # Row-Level Security policies
    # ------------------------------------------------------------------
    for table in ALL_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    # Drop RLS policies first
    for table in reversed(ALL_TABLES):
        _drop_rls(table)

    # Drop indexes
    op.drop_index("ix_sync_log_tenant_started", table_name="pipeline_sync_log")
    op.drop_index("ix_watermarks_tenant_entity", table_name="pipeline_watermarks")
    op.drop_constraint("uq_watermark_entity", "pipeline_watermarks")

    # Drop tables in reverse order
    op.drop_table("pipeline_sync_log")
    op.drop_table("pipeline_watermarks")
