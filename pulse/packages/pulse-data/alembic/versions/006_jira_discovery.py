"""Dynamic Jira project discovery tables (ADR-014).

Creates tenant_jira_config, jira_project_catalog, jira_discovery_audit.
Enables RLS on all three. Bootstraps existing tenants from JIRA_PROJECTS env var.

Revision ID: 006_jira_discovery
Revises: 005
Create Date: 2026-04-13
"""

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "006_jira_discovery"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Tables created by this migration
# ---------------------------------------------------------------------------
ALL_TABLES = [
    "tenant_jira_config",
    "jira_project_catalog",
    "jira_discovery_audit",
]


# ---------------------------------------------------------------------------
# RLS helpers — identical pattern to 001_initial_engineering_schema
# ---------------------------------------------------------------------------
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
    # 1. tenant_jira_config — per-tenant discovery configuration
    # ------------------------------------------------------------------
    op.create_table(
        "tenant_jira_config",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "mode",
            sa.String(16),
            nullable=False,
            server_default="allowlist",
        ),
        sa.Column("discovery_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "discovery_schedule_cron",
            sa.String(64),
            nullable=False,
            server_default="0 3 * * *",
        ),
        sa.Column("max_active_projects", sa.Integer, nullable=False, server_default="100"),
        sa.Column("max_issues_per_hour", sa.Integer, nullable=False, server_default="20000"),
        sa.Column("smart_pr_scan_days", sa.Integer, nullable=False, server_default="90"),
        sa.Column("smart_min_pr_references", sa.Integer, nullable=False, server_default="3"),
        sa.Column("last_discovery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_discovery_status", sa.String(16), nullable=True),
        sa.Column("last_discovery_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('auto','allowlist','blocklist','smart')",
            name="ck_tenant_jira_config_mode",
        ),
    )

    # ------------------------------------------------------------------
    # 2. jira_project_catalog — discovered / active projects per tenant
    # ------------------------------------------------------------------
    op.create_table(
        "jira_project_catalog",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_key", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("project_type", sa.String(32), nullable=True),
        sa.Column("lead_account_id", sa.String(128), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="discovered",
        ),
        sa.Column("activation_source", sa.String(32), nullable=True),
        sa.Column("issue_count", sa.Integer, server_default="0"),
        sa.Column("pr_reference_count", sa.Integer, server_default="0"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(16), nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('discovered','active','paused','blocked','archived')",
            name="ck_jira_project_catalog_status",
        ),
    )

    # Named unique constraint so ON CONFLICT ON CONSTRAINT works reliably
    op.create_unique_constraint(
        "uq_jira_catalog_tenant_key",
        "jira_project_catalog",
        ["tenant_id", "project_key"],
    )

    op.create_index(
        "ix_jira_catalog_tenant_status",
        "jira_project_catalog",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_jira_catalog_tenant_prrefs",
        "jira_project_catalog",
        ["tenant_id", sa.text("pr_reference_count DESC")],
    )

    # ------------------------------------------------------------------
    # 3. jira_discovery_audit — append-only audit log
    # ------------------------------------------------------------------
    op.create_table(
        "jira_discovery_audit",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("project_key", sa.String(64), nullable=True),
        sa.Column("actor", sa.String(128), nullable=True),
        sa.Column("before_value", JSONB, nullable=True),
        sa.Column("after_value", JSONB, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_jira_audit_tenant_time",
        "jira_discovery_audit",
        ["tenant_id", sa.text("created_at DESC")],
    )

    # Append-only enforcement via PostgreSQL RULEs.
    # RULEs are simpler than BEFORE triggers for this case: they silently
    # discard the operation (DO INSTEAD NOTHING) with zero function overhead.
    # A trigger that raises an exception would be equally correct but adds
    # a PL/pgSQL function dependency. Chose RULEs for minimalism.
    op.execute(
        'CREATE RULE no_update_audit AS ON UPDATE TO "jira_discovery_audit" DO INSTEAD NOTHING;'
    )
    op.execute(
        'CREATE RULE no_delete_audit AS ON DELETE TO "jira_discovery_audit" DO INSTEAD NOTHING;'
    )

    # ------------------------------------------------------------------
    # 4. Row-Level Security on all three tables
    # ------------------------------------------------------------------
    for table in ALL_TABLES:
        _enable_rls(table)

    # ------------------------------------------------------------------
    # 5. Bootstrap: seed config + catalog rows for existing tenants
    #
    # Reads JIRA_PROJECTS env var at migration time (Python-side) and
    # renders the project list into the SQL block. If the env var is
    # empty or unset, only tenant_jira_config rows are created (no
    # catalog entries). This is safe for re-runs because:
    #   - tenant_jira_config PK is tenant_id (ON CONFLICT DO NOTHING)
    #   - jira_project_catalog has UNIQUE (tenant_id, project_key)
    # ------------------------------------------------------------------
    jira_projects_raw = os.environ.get("JIRA_PROJECTS", "")
    project_keys = [
        k.strip() for k in jira_projects_raw.split(",") if k.strip()
    ]

    # Build the VALUES clause for catalog inserts.
    # Each entry becomes a (project_key) literal used in a cross join.
    if project_keys:
        # Escape single quotes in project keys (defensive)
        escaped = [pk.replace("'", "''") for pk in project_keys]
        values_list = ", ".join(f"('{pk}')" for pk in escaped)
        catalog_insert = f"""
            INSERT INTO jira_project_catalog (
                tenant_id, project_key, status, activation_source, activated_at
            )
            SELECT
                t.tenant_id,
                p.project_key,
                'active',
                'env_bootstrap',
                now()
            FROM tenant_ids t
            CROSS JOIN (VALUES {values_list}) AS p(project_key)
            ON CONFLICT ON CONSTRAINT uq_jira_catalog_tenant_key DO NOTHING;
        """
    else:
        catalog_insert = "-- No JIRA_PROJECTS env var set; skipping catalog bootstrap."

    # Discover tenants from multiple sources. The monorepo doesn't have a
    # canonical `tenants` table in every env (single-tenant dev uses a fixed
    # UUID seeded into domain tables). Union DISTINCT tenant_id from every
    # known tenant-aware table; use to_regclass to guard against missing tables
    # so the migration is portable across envs that have evolved differently.
    bootstrap_sql = f"""
    DO $$
    DECLARE
        _has_tenants       bool := to_regclass('public.tenants') IS NOT NULL;
        _has_integrations  bool := to_regclass('public.integration_connections') IS NOT NULL;
        _has_iam_orgs      bool := to_regclass('public.iam_organizations') IS NOT NULL;
        _has_eng_issues    bool := to_regclass('public.eng_issues') IS NOT NULL;
    BEGIN
        -- Build a temp view of tenants from whichever sources exist.
        CREATE TEMP TABLE tenant_ids (tenant_id uuid PRIMARY KEY) ON COMMIT DROP;

        IF _has_tenants THEN
            EXECUTE 'INSERT INTO tenant_ids SELECT id FROM tenants ON CONFLICT DO NOTHING';
        END IF;
        IF _has_integrations THEN
            EXECUTE 'INSERT INTO tenant_ids SELECT DISTINCT tenant_id FROM integration_connections WHERE tenant_id IS NOT NULL ON CONFLICT DO NOTHING';
        END IF;
        IF _has_iam_orgs THEN
            EXECUTE 'INSERT INTO tenant_ids SELECT DISTINCT tenant_id FROM iam_organizations WHERE tenant_id IS NOT NULL ON CONFLICT DO NOTHING';
        END IF;
        IF _has_eng_issues THEN
            EXECUTE 'INSERT INTO tenant_ids SELECT DISTINCT tenant_id FROM eng_issues WHERE tenant_id IS NOT NULL ON CONFLICT DO NOTHING';
        END IF;

        -- Fallback: if no tenants discovered (brand-new install), seed the
        -- canonical single-tenant dev UUID so bootstrap still populates the
        -- catalog. Production multi-tenant installs will hit one of the
        -- branches above and skip this.
        IF NOT EXISTS (SELECT 1 FROM tenant_ids) THEN
            INSERT INTO tenant_ids VALUES ('00000000-0000-0000-0000-000000000001');
        END IF;

        -- Seed a tenant_jira_config row (mode=allowlist) for every tenant.
        INSERT INTO tenant_jira_config (tenant_id)
        SELECT tenant_id FROM tenant_ids
        ON CONFLICT (tenant_id) DO NOTHING;

        -- Seed catalog rows for projects from JIRA_PROJECTS env var.
        {catalog_insert}
    END $$;
    """

    op.execute(bootstrap_sql)


def downgrade() -> None:
    # Drop RLS policies first
    for table in reversed(ALL_TABLES):
        _drop_rls(table)

    # Drop audit rules before dropping the table
    op.execute('DROP RULE IF EXISTS no_delete_audit ON "jira_discovery_audit"')
    op.execute('DROP RULE IF EXISTS no_update_audit ON "jira_discovery_audit"')

    # Drop indexes
    op.drop_index("ix_jira_audit_tenant_time", table_name="jira_discovery_audit")
    op.drop_index("ix_jira_catalog_tenant_prrefs", table_name="jira_project_catalog")
    op.drop_index("ix_jira_catalog_tenant_status", table_name="jira_project_catalog")
    op.drop_constraint("uq_jira_catalog_tenant_key", "jira_project_catalog")

    # Drop tables in reverse order
    op.drop_table("jira_discovery_audit")
    op.drop_table("jira_project_catalog")
    op.drop_table("tenant_jira_config")
