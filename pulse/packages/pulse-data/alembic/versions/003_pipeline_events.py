"""Pipeline events table.

Creates the pipeline_events table for BC5 activity feed.
Enables Row-Level Security using app.current_tenant.

Revision ID: 003_pipeline_events
Revises: 002_pipeline_monitor
Create Date: 2026-04-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "003_pipeline_events"
down_revision: Union[str, None] = "002_pipeline_monitor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# All tables that this migration creates — used for RLS and downgrade
# ---------------------------------------------------------------------------
ALL_TABLES = [
    "pipeline_events",
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
    # 1. pipeline_events (BC5)
    # ------------------------------------------------------------------
    op.create_table(
        "pipeline_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("event_type", sa.String(64), nullable=False, comment="sync_completed|error|config_change|webhook"),
        sa.Column("source", sa.String(64), nullable=False, comment="github|jira|jenkins|system|metrics_worker"),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("severity", sa.String(16), server_default="info", nullable=False, comment="info|warning|error|success"),
        sa.Column("event_meta", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    op.create_index(
        "ix_pipeline_events_tenant_occurred",
        "pipeline_events",
        ["tenant_id", sa.text("occurred_at DESC")],
    )

    op.create_index(
        "ix_pipeline_events_source",
        "pipeline_events",
        ["tenant_id", "source"],
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
    op.drop_index("ix_pipeline_events_source", table_name="pipeline_events")
    op.drop_index("ix_pipeline_events_tenant_occurred", table_name="pipeline_events")

    # Drop tables
    op.drop_table("pipeline_events")
