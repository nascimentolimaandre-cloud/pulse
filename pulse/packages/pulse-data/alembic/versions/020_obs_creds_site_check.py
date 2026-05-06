"""FDD-OBS-001 PR 2 — CISO L-003 fix: site column CHECK constraint.

Adds a CHECK constraint to `tenant_observability_credentials.site`
restricting values to known Datadog/NR site domains. Without this, a
compromised admin (or a malicious-but-authenticated tenant member with
admin role) could store an arbitrary domain, causing the Datadog
adapter to issue API calls to an attacker-controlled endpoint —
classic SSRF + credential leak.

Also covers the New Relic case (`api.newrelic.com`, EU variant) so PR
2 doesn't have to revisit the constraint when NR ships in R3. Adding
sites later is a one-line ALTER (CHECK rewrite via DROP + ADD).

Revision ID: 020_obs_creds_site_check
Revises: 019_obs_metric_snapshots
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op


revision: str = "020_obs_creds_site_check"
down_revision: Union[str, None] = "019_obs_metric_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Authoritative site allowlist. Update both this constraint AND
# `connectors/observability/datadog_connector.py:_VALID_DD_SITES` (PR 2)
# in lockstep — they share the contract.
_VALID_SITES = (
    # Datadog regional endpoints
    "datadoghq.com",
    "datadoghq.eu",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "ap1.datadoghq.com",
    "ddog-gov.com",
    # New Relic — pre-registered for R3
    "api.newrelic.com",
    "api.eu.newrelic.com",
)


def upgrade() -> None:
    sites_sql = ",\n            ".join(repr(s) for s in _VALID_SITES)
    op.execute(
        f"""
        ALTER TABLE tenant_observability_credentials
            ADD CONSTRAINT ck_obs_creds_site CHECK (
                site IN (
                    {sites_sql}
                )
            )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_observability_credentials "
        "DROP CONSTRAINT IF EXISTS ck_obs_creds_site"
    )
