"""pipeline_watermarks: add scope_key (FDD-OPS-014 Phase 2, Step 2.1).

Promoted from DRAFT 2026-04-28 after `docs/ingestion-v2-phase-2-plan.md`
review approval.

==============================================================================
Why this migration exists (FDD-OPS-014, Phase 2 of ingestion-architecture-v2)
==============================================================================

Today `pipeline_watermarks` has ONE row per (tenant, entity_type). Adding
a single new Jira project means resetting the watermark to bring its
historical data — but that ALSO re-fetches the existing 200k+ issues from
all other projects unnecessarily.

After this migration: rows are keyed by (tenant, entity_type, scope_key).
A new project starts with `scope_key = "jira:project:NEWKEY"` watermark
at NULL → backfills only that scope. Other scopes' watermarks unchanged.

Same pattern for repos (github), jobs (jenkins), and future sources.

==============================================================================
Migration plan (zero-downtime, multi-step)
==============================================================================

This migration is INTENTIONALLY conservative — it adds the new column
with a default WITHOUT removing the old constraint. A second migration
(011, after the worker code switches to writing per-scope rows) drops
the old global constraint.

Step 010 (this file):
  1. ADD COLUMN scope_key VARCHAR(255) NOT NULL DEFAULT '*'
     - existing rows get scope_key='*' (means "global, all scopes")
     - workers can keep reading existing rows by querying scope_key='*'
  2. CREATE INDEX on (tenant_id, entity_type, scope_key)
  3. CREATE UNIQUE CONSTRAINT uq_watermark_scope on
     (tenant_id, entity_type, scope_key)  ← coexists with old global one
  4. KEEP existing uq_watermark_entity (tenant_id, entity_type) UNTIL
     workers migrate

Step 011 (separate file, AFTER worker code is deployed):
  - DROP CONSTRAINT uq_watermark_entity
  - At this point all writes use scope_key, the global '*' rows can
    be removed too (or kept as "backwards-compat aggregate")

==============================================================================
Rollback strategy
==============================================================================

`downgrade()` removes only what `upgrade()` adds. It does NOT touch the
old constraint (since this migration didn't drop it). Safe to revert
if the new column proves problematic.

==============================================================================
What this DOES NOT change
==============================================================================

- No worker code changes (those go in Phase 2 PR).
- No queries change yet — workers still read by (tenant, entity_type)
  which now matches the global '*' row.
- No data backfill — existing rows just inherit '*' default.

Revision ID: 010_pipeline_watermarks_scope_key
Revises: 009_metrics_snapshots_tenant_latest_index
Create Date: 2026-04-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_watermarks_scope_key"
down_revision: Union[str, None] = "009_metrics_snapshots_tenant_latest_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add scope_key column + new unique constraint (coexists with old)."""

    # 1. Add the column with default '*' so existing rows get a value.
    op.add_column(
        "pipeline_watermarks",
        sa.Column(
            "scope_key",
            sa.String(length=255),
            nullable=False,
            server_default="*",
            comment=(
                "Scope identifier within an entity_type. "
                "Format: '<source>:<dimension>:<value>' "
                "(e.g., 'jira:project:BG', 'github:repo:foo/bar', "
                "'jenkins:job:deploy-X'). Value '*' means global "
                "(legacy global watermark). FDD-OPS-014."
            ),
        ),
    )

    # 2. Index for the per-scope lookup pattern. Replaces nothing yet —
    #    keeps the old (tenant, entity_type) index for backwards-compat.
    op.create_index(
        "ix_watermarks_tenant_entity_scope",
        "pipeline_watermarks",
        ["tenant_id", "entity_type", "scope_key"],
        unique=False,
    )

    # 3. New UNIQUE constraint covering scope_key. Coexists with the old
    #    `uq_watermark_entity` constraint until step 011 drops it.
    op.create_unique_constraint(
        "uq_watermark_entity_scope",
        "pipeline_watermarks",
        ["tenant_id", "entity_type", "scope_key"],
    )

    # 4. Defensive: any RLS policies on the table apply to the new column
    #    automatically (policies are at table level, not column level).
    #    No change needed.


def downgrade() -> None:
    """Reverse: drop new constraint + index + column. Old constraints stay."""
    op.drop_constraint(
        "uq_watermark_entity_scope",
        "pipeline_watermarks",
        type_="unique",
    )
    op.drop_index(
        "ix_watermarks_tenant_entity_scope",
        table_name="pipeline_watermarks",
    )
    op.drop_column("pipeline_watermarks", "scope_key")


# ============================================================================
# Companion migration that should follow (011) — KEEP IN SYNC HERE for review
# ============================================================================
#
# def upgrade():
#     # Drop the legacy global-watermark constraint now that all writes use
#     # scope_key. Safe to run only after Phase 2 worker code is deployed.
#     op.drop_constraint(
#         "uq_watermark_entity",
#         "pipeline_watermarks",
#         type_="unique",
#     )
#     op.drop_index(
#         "ix_watermarks_tenant_entity",
#         table_name="pipeline_watermarks",
#     )
#
# def downgrade():
#     op.create_unique_constraint(
#         "uq_watermark_entity",
#         "pipeline_watermarks",
#         ["tenant_id", "entity_type"],
#     )
#     op.create_index(
#         "ix_watermarks_tenant_entity",
#         "pipeline_watermarks",
#         ["tenant_id", "entity_type"],
#     )
#
# ============================================================================
