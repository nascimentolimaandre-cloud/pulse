"""FDD-OBS-001 PR 0 — Per-tenant feature flags table.

Adds the foundation for shipping features dark to specific tenants — the
PULSE Signals integration (R2) and any future cross-cutting feature
gated by `is_enabled(tenant_id, flag_key)`.

Design (architect-validated):
  - One row per (tenant_id, flag_key); default is `enabled=False` when
    no row exists. UPSERT on update.
  - RLS standard pattern (`tenant_id = current_setting('app.current_tenant')`).
  - Helper service `src/shared/feature_flags.py` encapsulates the read
    path with a 60s Redis cache (graceful degradation when Redis
    unavailable, mirroring the tenant capabilities pattern in
    `contexts/tenant/service.py`).

Why a real table, not env-var:
  - Per-tenant toggles are a SaaS requirement (some tenants get R2 dark,
    some after GA, some with timing chosen by ops).
  - Audit trail comes for free via `updated_at` (pair with future audit
    log if compliance demands it).

Revision ID: 016_tenant_feature_flags
Revises: 015_sprint_transitions
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op


# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision: str = "016_tenant_feature_flags"
down_revision: Union[str, None] = "015_sprint_transitions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_feature_flags (
            tenant_id   UUID NOT NULL,
            flag_key    VARCHAR(64) NOT NULL,
            enabled     BOOLEAN NOT NULL DEFAULT FALSE,
            metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, flag_key)
        )
        """
    )

    # RLS standard pattern (mirrors all other multi-tenant tables in PULSE).
    op.execute('ALTER TABLE tenant_feature_flags ENABLE ROW LEVEL SECURITY')
    for action, clause in [
        ("SELECT", "USING"),
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ]:
        op.execute(
            f"""
            CREATE POLICY "tenant_feature_flags_{action.lower()}_tenant"
                ON tenant_feature_flags
                FOR {action} {clause} (
                    tenant_id = current_setting('app.current_tenant')::uuid
                );
            """
        )

    # Lookup index — feature flag reads are on the request-handling hot path,
    # so worth a dedicated index even though the PK already covers the common
    # access pattern. Documented here in case someone wonders why both exist.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_feature_flags_lookup
            ON tenant_feature_flags (tenant_id, flag_key)
            WHERE enabled = TRUE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenant_feature_flags_lookup")
    for action in ("select", "insert", "update", "delete"):
        op.execute(
            f'DROP POLICY IF EXISTS "tenant_feature_flags_{action}_tenant" ON tenant_feature_flags'
        )
    op.execute("DROP TABLE IF EXISTS tenant_feature_flags")
