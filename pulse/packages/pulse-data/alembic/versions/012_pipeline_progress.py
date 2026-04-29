"""FDD-OPS-015 — pipeline_progress table for per-scope ingestion observability.

Per-scope progress tracking, separate from `pipeline_ingestion_progress`
(which is per-`entity_type` aggregate, 4 rows total). This table holds
~32+ rows during a backfill cycle (one per active scope: per Jira project,
per GitHub repo, per Jenkins job).

Schema choices:
- (tenant_id, entity_type, scope_key) is the natural primary index for
  upsert-on-progress-tick. Using a UNIQUE constraint instead of PK to keep
  `id UUID` for cross-table joins (consistent with other pipeline tables).
- `started_at` + `last_progress_at` allow the API to compute "stalled":
  `last_progress_at < now() - interval '60 seconds'` while `status='running'`
- `status` enum (not actual SQL enum to avoid alter-type pain):
    running | done | failed | paused | cancelled
- `last_error` is text — full traceback or short message, decided by emitter
- `items_per_second` is the rolling rate (worker computes via window)
- `eta_seconds` is computed: max(0, (estimate - done) / rate) when rate > 0

Retention: live tracking + historical (no auto-truncate). Recommended
external cron: `DELETE WHERE status IN ('done','failed') AND last_progress_at
< now() - interval '7 days'` to bound table size.

Revision ID: 012_pipeline_progress
Revises: 011_drop_legacy_watermark
Create Date: 2026-04-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "012_pipeline_progress"
down_revision: Union[str, None] = "011_drop_legacy_watermark"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create pipeline_progress table with per-scope tracking."""
    op.create_table(
        "pipeline_progress",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # FDD-OPS-014 — scope_key follows the same convention used in
        # pipeline_watermarks: '<source>:<dimension>:<value>' (e.g.,
        # 'jira:project:BG', 'github:repo:foo/bar', 'jenkins:job:deploy-X').
        sa.Column("scope_key", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        # Phase within the per-scope job lifecycle. The connector and worker
        # together transition: pre_flight → fetching → normalizing →
        # persisting → done (or → failed). 'pre_flight' is the count call;
        # 'persisting' covers both upsert and Kafka emit.
        sa.Column("phase", sa.String(32), nullable=False, server_default="pre_flight"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("items_done", sa.Integer, nullable=False, server_default="0"),
        # NULLABLE: estimate may not be available (count call too expensive,
        # or source doesn't expose it). Worker falls back to heuristic
        # 'items_done × historical_rate'.
        sa.Column("items_estimate", sa.Integer, nullable=True),
        sa.Column("items_per_second", sa.Float, nullable=False, server_default="0.0"),
        # ETA in seconds remaining. -1 sentinel = unknown (no estimate yet).
        sa.Column("eta_seconds", sa.Integer, nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_progress_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        # TenantModel base columns (mirror other pipeline_* tables).
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_type",
            "scope_key",
            name="uq_pipeline_progress_scope",
        ),
    )
    # Composite index for the "show me running jobs" query.
    op.create_index(
        "ix_pipeline_progress_tenant_status",
        "pipeline_progress",
        ["tenant_id", "status"],
    )
    # Index for "stalled" detection — partial index on running jobs.
    op.execute(
        "CREATE INDEX ix_pipeline_progress_running_last_progress "
        "ON pipeline_progress (last_progress_at) "
        "WHERE status = 'running'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pipeline_progress_running_last_progress")
    op.drop_index("ix_pipeline_progress_tenant_status", table_name="pipeline_progress")
    op.drop_table("pipeline_progress")
