"""FDD-OBS-001 PR 1 — Per-tenant observability credentials (ADR-021).

Per-tenant DD/NR API keys stored encrypted via `pgcrypto`. Mirrors the
`tenant_jira_config` pattern but with a key/app_key pair (Datadog
requires both) and a fingerprint for audit.

Schema:
  - PK (tenant_id, provider) — 1 row per tenant per provider.
  - api_key_encrypted: bytea, encrypted via `pgp_sym_encrypt(plain,
    PULSE_OBS_MASTER_KEY)`.
  - app_key_encrypted: bytea, DD only — NULL for NR / Grafana.
  - site: TEXT for region-specific endpoints
    (datadoghq.com / datadoghq.eu / etc.).
  - validated_at: last successful `/validate` call.
  - last_rotated_at: rotation timestamp for audit.
  - key_fingerprint: sha256(key)[:16] — audit/diff without exposing key.

Migration enables `pgcrypto` extension first (required for
`pgp_sym_encrypt`). Postgres 13+ ships it; CREATE EXTENSION IF NOT
EXISTS makes this idempotent.

Revision ID: 017_observability_credentials
Revises: 016_tenant_feature_flags
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op


revision: str = "017_observability_credentials"
down_revision: Union[str, None] = "016_tenant_feature_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE tenant_observability_credentials (
            tenant_id           UUID NOT NULL,
            provider            VARCHAR(32) NOT NULL,
            api_key_encrypted   BYTEA NOT NULL,
            app_key_encrypted   BYTEA,
            site                VARCHAR(64) NOT NULL DEFAULT 'datadoghq.com',
            validated_at        TIMESTAMPTZ,
            last_rotated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            key_fingerprint     VARCHAR(32) NOT NULL,
            metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, provider),
            CONSTRAINT ck_obs_creds_provider
                CHECK (provider IN ('datadog','newrelic','grafana','honeycomb','dynatrace'))
        )
        """
    )

    # RLS standard pattern.
    op.execute('ALTER TABLE tenant_observability_credentials ENABLE ROW LEVEL SECURITY')
    for action, clause in [
        ("SELECT", "USING"),
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ]:
        op.execute(
            f"""
            CREATE POLICY "tenant_obs_creds_{action.lower()}_tenant"
                ON tenant_observability_credentials
                FOR {action} {clause} (
                    tenant_id = current_setting('app.current_tenant')::uuid
                );
            """
        )


def downgrade() -> None:
    for action in ("select", "insert", "update", "delete"):
        op.execute(
            f'DROP POLICY IF EXISTS "tenant_obs_creds_{action}_tenant" '
            f'ON tenant_observability_credentials'
        )
    op.execute("DROP TABLE IF EXISTS tenant_observability_credentials")
    # NOTE: do NOT drop pgcrypto extension on downgrade — other features
    # might depend on it in the future. Extensions are global; removing
    # one we created here would be reversible vandalism.
