"""FDD-OBS-001 PR 3.5 — tenant_team_alias (vendor_team → squad mapping).

Live test against Webmotors DD (PR 3, 2026-05-07) caught that DD
`team:` tags don't match PULSE squad keys (DD uses kebab-case product
labels like `agenda-facil`; PULSE uses Jira project keys like `FID`).
473 services with 99.8% tag coverage but 0% qualified squad mapping.

This migration adds the missing translation layer:

  Tier 1 inference flow becomes:
    DD tag `team:agenda-facil`
    → look up tenant_team_alias[(tenant, datadog, "agenda-facil")]
    → if found: inferred_squad_key='FID', inferred_confidence='alias'
    → else:     inferred_squad_key='agenda-facil',
                inferred_confidence='tag' (current behaviour, yellow
                badge in UI signals "tag fora do tenant")

  Bulk override pattern: operator pastes CSV
    agenda-facil,FID
    iazi,IAZI
    webmotors-platform,WEMOPF
  → batch upserts into tenant_team_alias.

Constraint design:
  - PK on (tenant_id, provider, vendor_team_value) keeps lookup O(log N).
  - `squad_key` validated by application service against
    jira_project_catalog (NOT a CHECK constraint — squad set is dynamic).
  - RLS standard (tenant_id = current_setting('app.current_tenant')).

Also extends the inferred_confidence CHECK on service_squad_ownership
to accept 'alias' alongside the existing 'tag'/'heuristic'/'none'.

Revision ID: 021_tenant_team_alias
Revises: 020_obs_creds_site_check
Create Date: 2026-05-08
"""

from typing import Sequence, Union

from alembic import op


revision: str = "021_tenant_team_alias"
down_revision: Union[str, None] = "020_obs_creds_site_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_team_alias (
            tenant_id          UUID         NOT NULL,
            provider           VARCHAR(32)  NOT NULL,
            vendor_team_value  VARCHAR(128) NOT NULL,
            squad_key          VARCHAR(64)  NOT NULL,
            created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, provider, vendor_team_value),
            CONSTRAINT ck_tta_provider CHECK (
                provider IN ('datadog','newrelic','grafana','honeycomb','dynatrace')
            ),
            -- vendor_team_value is normalized lowercase by the service
            -- before insert; constraint keeps the column non-empty.
            CONSTRAINT ck_tta_vendor_team_nonempty CHECK (
                length(vendor_team_value) > 0
            ),
            CONSTRAINT ck_tta_squad_nonempty CHECK (
                length(squad_key) > 0
            )
        )
        """
    )

    # Index for the reverse-lookup pattern: "which DD teams point to
    # squad FID?" — used by the alias-management UI.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tta_squad
            ON tenant_team_alias (tenant_id, provider, squad_key)
        """
    )

    # RLS standard pattern (matches every other observability table).
    op.execute("ALTER TABLE tenant_team_alias ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tta_tenant_isolation ON tenant_team_alias
            USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid)
        """
    )

    # Extend service_squad_ownership.inferred_confidence to accept 'alias'.
    op.execute(
        """
        ALTER TABLE service_squad_ownership
            DROP CONSTRAINT IF EXISTS ck_sso_inferred_confidence
        """
    )
    op.execute(
        """
        ALTER TABLE service_squad_ownership
            ADD CONSTRAINT ck_sso_inferred_confidence CHECK (
                inferred_confidence IS NULL
                OR inferred_confidence IN ('tag','alias','heuristic','none')
            )
        """
    )


def downgrade() -> None:
    # Restore the original CHECK first so we don't leave 'alias' rows
    # invalid mid-rollback.
    op.execute(
        """
        ALTER TABLE service_squad_ownership
            DROP CONSTRAINT IF EXISTS ck_sso_inferred_confidence
        """
    )
    op.execute(
        """
        ALTER TABLE service_squad_ownership
            ADD CONSTRAINT ck_sso_inferred_confidence CHECK (
                inferred_confidence IS NULL
                OR inferred_confidence IN ('tag','heuristic','none')
            )
        """
    )
    op.execute("DROP POLICY IF EXISTS tta_tenant_isolation ON tenant_team_alias")
    op.execute("DROP INDEX IF EXISTS ix_tta_squad")
    op.execute("DROP TABLE IF EXISTS tenant_team_alias")
