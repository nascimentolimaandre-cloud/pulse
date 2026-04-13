"""Add pipeline_ingestion_progress table for real-time ingestion tracking.

Revision ID: 004
Revises: 003
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "004"
down_revision = "003_pipeline_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_ingestion_progress",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=False),  # pull_requests | issues | deployments | sprints
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),  # idle | running | completed | failed
        sa.Column("total_sources", sa.Integer, nullable=False, server_default="0"),  # e.g. total repos
        sa.Column("sources_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_ingested", sa.Integer, nullable=False, server_default="0"),
        sa.Column("current_source", sa.String(512), nullable=True),  # e.g. "webmotors-private/buyer.ui"
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_batch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("source_details", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),  # extra metadata
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "entity_type", name="uq_ingestion_progress_entity"),
    )

    op.create_index(
        "ix_ingestion_progress_tenant_entity",
        "pipeline_ingestion_progress",
        ["tenant_id", "entity_type"],
    )


def downgrade() -> None:
    op.drop_table("pipeline_ingestion_progress")
