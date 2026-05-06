"""FDD-OBS-001 PR 1 — Observability metric snapshots (ADR-024).

Hourly rollup of metrics pulled from observability providers
(Datadog, New Relic, ...). Carlos's Deploy Health Timeline reads
exclusively from this table — zero live API calls per page load.

Schema:
  - PK (tenant_id, provider, service, metric, hour_bucket).
  - hour_bucket = `date_trunc('hour', deployed_at)`.
  - value = metric average for the bucket.
  - samples_count = # of underlying data points (transparency for
    sparse signals).

Index optimised for the timeline query pattern: latest N hours for
a given (tenant, service, metric).

Revision ID: 019_obs_metric_snapshots
Revises: 018_service_squad_ownership
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op


revision: str = "019_obs_metric_snapshots"
down_revision: Union[str, None] = "018_service_squad_ownership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE obs_metric_snapshots (
            tenant_id      UUID NOT NULL,
            provider       VARCHAR(32) NOT NULL,
            service        VARCHAR(256) NOT NULL,
            metric         VARCHAR(64) NOT NULL,
            hour_bucket    TIMESTAMPTZ NOT NULL,
            value          DOUBLE PRECISION,
            samples_count  INTEGER NOT NULL DEFAULT 0,
            calculated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (tenant_id, provider, service, metric, hour_bucket),
            CONSTRAINT ck_oms_provider CHECK (
                provider IN ('datadog','newrelic','grafana','honeycomb','dynatrace')
            ),
            CONSTRAINT ck_oms_metric CHECK (
                metric IN (
                    'error_rate','p95_latency_ms','p99_latency_ms',
                    'apdex','throughput_rps','alert_count'
                )
            )
        )
        """
    )

    # Carlos's Timeline read pattern: latest N hours per (service, metric).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_oms_timeline
            ON obs_metric_snapshots (
                tenant_id, service, metric, hour_bucket DESC
            )
        """
    )

    # Apply the same PII guard trigger from migration 018 (function
    # already exists; just attach to this table).
    op.execute(
        """
        CREATE TRIGGER obs_metric_snapshots_pii_guard
            BEFORE INSERT OR UPDATE ON obs_metric_snapshots
            FOR EACH ROW EXECUTE FUNCTION obs_no_pii_in_metadata()
        """
    )

    # RLS standard pattern.
    op.execute('ALTER TABLE obs_metric_snapshots ENABLE ROW LEVEL SECURITY')
    for action, clause in [
        ("SELECT", "USING"),
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ]:
        op.execute(
            f"""
            CREATE POLICY "obs_metric_snapshots_{action.lower()}_tenant"
                ON obs_metric_snapshots
                FOR {action} {clause} (
                    tenant_id = current_setting('app.current_tenant')::uuid
                );
            """
        )


def downgrade() -> None:
    for action in ("select", "insert", "update", "delete"):
        op.execute(
            f'DROP POLICY IF EXISTS "obs_metric_snapshots_{action}_tenant" '
            f'ON obs_metric_snapshots'
        )
    op.execute(
        "DROP TRIGGER IF EXISTS obs_metric_snapshots_pii_guard "
        "ON obs_metric_snapshots"
    )
    op.execute("DROP INDEX IF EXISTS ix_oms_timeline")
    op.execute("DROP TABLE IF EXISTS obs_metric_snapshots")
