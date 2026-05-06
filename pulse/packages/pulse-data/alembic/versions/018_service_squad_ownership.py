"""FDD-OBS-001 PR 1 — Service ↔ Squad ownership (ADR-022 + ADR-025 L2).

Maps each observability `service` to a PULSE squad via 3-tier inference:
  - Tier 1: vendor tag (e.g. `service.owner` in Datadog).
  - Tier 2: repo-intersection heuristic (PR titles + repo metadata).
  - Tier 3: operator override (admin UI).

The effective squad is `COALESCE(override_squad_key, inferred_squad_key)`.

ADR-025 Layer 2 (anti-surveillance enforcement at DB level):
  - `metadata` JSONB MUST NOT contain known-PII keys (user.email,
    deployment.author, etc.). A trigger blocks INSERT/UPDATE that
    would store such keys, raising at the DB layer (scream test).
  - This is a belt-and-suspenders defense in depth — adapters MUST
    strip PII at ingestion (Layer 1), but if a bug slips through, the
    trigger catches it before it touches storage.

Revision ID: 018_service_squad_ownership
Revises: 017_observability_credentials
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op


revision: str = "018_service_squad_ownership"
down_revision: Union[str, None] = "017_observability_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE service_squad_ownership (
            tenant_id            UUID NOT NULL,
            provider             VARCHAR(32) NOT NULL,
            service_external_id  VARCHAR(256) NOT NULL,
            service_name         VARCHAR(256) NOT NULL,
            repo_url             TEXT,
            inferred_squad_key   VARCHAR(64),
            inferred_confidence  VARCHAR(16),
            override_squad_key   VARCHAR(64),
            last_inference_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, provider, service_external_id),
            CONSTRAINT ck_sso_provider CHECK (
                provider IN ('datadog','newrelic','grafana','honeycomb','dynatrace')
            ),
            CONSTRAINT ck_sso_inferred_confidence CHECK (
                inferred_confidence IS NULL
                OR inferred_confidence IN ('tag','heuristic','none')
            )
        )
        """
    )

    # Index for the effective-squad lookup pattern (Carlos's Timeline,
    # Squad Reliability Posture, etc. — all read by COALESCE).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sso_effective_squad
            ON service_squad_ownership (
                tenant_id,
                COALESCE(override_squad_key, inferred_squad_key)
            )
        """
    )

    # ADR-025 Layer 2 — DB trigger blocking known-PII keys in metadata.
    # Forbidden list mirrors connectors/observability/_anti_surveillance.py;
    # this is duplication on purpose (defense in depth) so a bug in the
    # adapter strip can't smuggle PII into storage.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION obs_no_pii_in_metadata()
        RETURNS trigger AS $$
        DECLARE
            forbidden_keys TEXT[] := ARRAY[
                'user', 'user_id', 'user.id', 'user.email',
                'deployment.author', 'alert.assignee', 'incident.assignee',
                'owner.email', 'ack_by', 'resolved_by', 'creator',
                'modified_by', 'trace.user_id', 'rum.user_id', 'usr.email'
            ];
            k TEXT;
        BEGIN
            IF NEW.metadata IS NULL THEN
                RETURN NEW;
            END IF;
            FOREACH k IN ARRAY forbidden_keys LOOP
                IF NEW.metadata ? k THEN
                    RAISE EXCEPTION 'PII key % blocked in obs metadata (ADR-025 Layer 2)', k
                        USING ERRCODE = 'check_violation';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE TRIGGER service_squad_ownership_pii_guard
            BEFORE INSERT OR UPDATE ON service_squad_ownership
            FOR EACH ROW EXECUTE FUNCTION obs_no_pii_in_metadata()
        """
    )

    # RLS standard pattern.
    op.execute('ALTER TABLE service_squad_ownership ENABLE ROW LEVEL SECURITY')
    for action, clause in [
        ("SELECT", "USING"),
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ]:
        op.execute(
            f"""
            CREATE POLICY "service_squad_ownership_{action.lower()}_tenant"
                ON service_squad_ownership
                FOR {action} {clause} (
                    tenant_id = current_setting('app.current_tenant')::uuid
                );
            """
        )


def downgrade() -> None:
    for action in ("select", "insert", "update", "delete"):
        op.execute(
            f'DROP POLICY IF EXISTS "service_squad_ownership_{action}_tenant" '
            f'ON service_squad_ownership'
        )
    op.execute(
        "DROP TRIGGER IF EXISTS service_squad_ownership_pii_guard "
        "ON service_squad_ownership"
    )
    # Keep the function — it's reused by the next migration's rollup table.
    # If both tables go away, drop manually via psql.
    op.execute("DROP INDEX IF EXISTS ix_sso_effective_squad")
    op.execute("DROP TABLE IF EXISTS service_squad_ownership")
