"""FDD-PIPE-001 — Squad qualification + activity tier.

Adds two new fields:

  jira_project_catalog.qualification_override (VARCHAR(16)):
    NULL          = automatic qualification (the default — heuristic decides)
    'qualified'   = operator forced this squad into the dropdown / lists
    'excluded'    = operator forced this squad out

  tenant_jira_config.squad_qualification_config (JSONB):
    Per-tenant tunables for the heuristic. Defaults to:
      {
        "min_prs_90d_active_tier": 5,
        "include_data_only_squads": true,
        "qualification_requires_metadata": true,
        "qualification_requires_any_activity": true
      }

The qualification rule itself lives in the application layer (SQL CTE in
`pipeline/routes.py:get_teams()`) so changing the rule never requires a
migration. This migration only stores the *override* + *tunables*.

Why columns instead of a separate table:
  qualification_override is 1:1 with catalog row (no entity life of its own)
  squad_qualification_config is 1:1 with tenant_jira_config (already 1:1)
  Both are < 50 bytes — negligible storage, no normalization win.

Why not Postgres ENUM for qualification_override:
  Same reason as `incident_status` (FDD-DSH-050): ENUM type changes are
  heavyweight; CHECK + VARCHAR(16) reads identical and evolves freely.

Revision ID: 014_squad_qualification
Revises: 013_mttr_incident_pairing
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op


# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision: str = "014_squad_qualification"
down_revision: Union[str, None] = "013_mttr_incident_pairing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Default config payload — kept here so `upgrade()` and the application
# default share the same source of truth. If you change defaults here,
# update `pipeline/routes.py:_DEFAULT_QUALIFICATION_CONFIG` to match.
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG_JSON = """{
  "min_prs_90d_active_tier": 5,
  "include_data_only_squads": true,
  "qualification_requires_metadata": true,
  "qualification_requires_any_activity": true
}"""


def upgrade() -> None:
    # ── jira_project_catalog.qualification_override ────────────────────────
    op.execute(
        """
        ALTER TABLE jira_project_catalog
            ADD COLUMN qualification_override VARCHAR(16)
        """
    )
    op.execute(
        """
        ALTER TABLE jira_project_catalog
            ADD CONSTRAINT ck_jira_project_catalog_qualification_override
            CHECK (
                qualification_override IS NULL
                OR qualification_override IN ('qualified', 'excluded')
            )
        """
    )

    # ── tenant_jira_config.squad_qualification_config ──────────────────────
    op.execute(
        f"""
        ALTER TABLE tenant_jira_config
            ADD COLUMN squad_qualification_config JSONB
            NOT NULL DEFAULT '{_DEFAULT_CONFIG_JSON}'::jsonb
        """
    )

    # ── Backfill existing rows — DEFAULT covers new rows but Postgres does
    #    apply defaults retroactively when ADD COLUMN with DEFAULT, so this
    #    is just a safety belt that also documents intent.
    op.execute(
        """
        UPDATE tenant_jira_config
            SET squad_qualification_config = COALESCE(
                squad_qualification_config,
                '{_DEFAULT_CONFIG_JSON}'::jsonb
            )
        """.replace("{_DEFAULT_CONFIG_JSON}", _DEFAULT_CONFIG_JSON)
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_jira_config
            DROP COLUMN IF EXISTS squad_qualification_config
        """
    )
    op.execute(
        """
        ALTER TABLE jira_project_catalog
            DROP CONSTRAINT IF EXISTS ck_jira_project_catalog_qualification_override
        """
    )
    op.execute(
        """
        ALTER TABLE jira_project_catalog
            DROP COLUMN IF EXISTS qualification_override
        """
    )
