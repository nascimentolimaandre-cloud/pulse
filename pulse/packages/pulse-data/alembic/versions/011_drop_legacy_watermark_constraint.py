"""Drop legacy uq_watermark_entity constraint (FDD-OPS-014, Phase 2 step 2.7).

Promoted earlier than originally planned because the assumption in
migration 010 ("legacy and new UNIQUE constraints coexist harmlessly")
was wrong: Postgres enforces ALL UniqueConstraints on every INSERT.
Trying to insert a per-scope row like (tenant, 'issues',
'jira:project:OKM', ...) failed with:

    UniqueViolationError: duplicate key value violates unique
    constraint "uq_watermark_entity"
    DETAIL: Key (tenant_id, entity_type)=(..., issues) already exists.

The legacy constraint treats (tenant, entity_type) as the unique key
regardless of scope_key, so the existing '*' row blocked every
attempt to insert a scoped row.

Resolution: drop the legacy constraint. The new
`uq_watermark_entity_scope` (tenant, entity_type, scope_key)
correctly handles both '*' and scoped rows.

This was discovered immediately after Phase 2-A deployment (Steps
2.1-2.5) when sync cycles started failing with "status=failed" on the
first scope advance attempt. Documenting the root cause here so
future migrations don't repeat the dual-constraint assumption.

Revision ID: 011_drop_legacy_watermark
Revises: 010_watermarks_scope_key
Create Date: 2026-04-28
"""

from typing import Sequence, Union

from alembic import op


revision: str = "011_drop_legacy_watermark"
down_revision: Union[str, None] = "010_watermarks_scope_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop legacy unique-on-(tenant, entity) constraint and index."""
    # Use IF EXISTS for safety — this migration was applied via raw SQL
    # before the file existed, so the actual DROP may have already run.
    op.execute(
        "ALTER TABLE pipeline_watermarks "
        "DROP CONSTRAINT IF EXISTS uq_watermark_entity"
    )
    op.execute("DROP INDEX IF EXISTS ix_watermarks_tenant_entity")


def downgrade() -> None:
    """Restore legacy constraint + index.

    WARNING: this only works if no two rows have the same
    (tenant_id, entity_type) — i.e., either you're back to a single '*'
    row per tenant+entity, or you've collapsed scope rows first.
    """
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_watermarks_tenant_entity "
        "ON pipeline_watermarks (tenant_id, entity_type)"
    )
    op.execute(
        "ALTER TABLE pipeline_watermarks "
        "ADD CONSTRAINT uq_watermark_entity "
        "UNIQUE (tenant_id, entity_type)"
    )
