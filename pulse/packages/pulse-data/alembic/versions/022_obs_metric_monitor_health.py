"""FDD-OBS-001 PR 4a.5 — extend obs_metric_snapshots metric whitelist.

Adds 'monitor_health' to the `ck_oms_metric` CHECK constraint so the
rollup worker can write the per-service monitor severity score
introduced when Webmotors's DD plan turned out to lack the Query API
(see RISK-19, ops-backlog).

The constraint is extended (not removed) so the existing 6 PulseMetric
values (error_rate, p95_latency_ms, p99_latency_ms, apdex, throughput_rps,
alert_count) remain accepted — the worker can fall back to them if a
future tenant has Query API access.

Revision ID: 022_obs_metric_monitor_health
Revises: 021_tenant_team_alias
Create Date: 2026-05-09
"""

from typing import Sequence, Union

from alembic import op


revision: str = "022_obs_metric_monitor_health"
down_revision: Union[str, None] = "021_tenant_team_alias"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ALLOWED_METRICS_AFTER = (
    "error_rate",
    "p95_latency_ms",
    "p99_latency_ms",
    "apdex",
    "throughput_rps",
    "alert_count",
    "monitor_health",   # NEW — PR 4a.5
)


_ALLOWED_METRICS_BEFORE = (
    "error_rate",
    "p95_latency_ms",
    "p99_latency_ms",
    "apdex",
    "throughput_rps",
    "alert_count",
)


def upgrade() -> None:
    op.execute("ALTER TABLE obs_metric_snapshots DROP CONSTRAINT IF EXISTS ck_oms_metric")
    metric_list_sql = ", ".join(repr(m) for m in _ALLOWED_METRICS_AFTER)
    op.execute(
        f"""
        ALTER TABLE obs_metric_snapshots
            ADD CONSTRAINT ck_oms_metric CHECK (
                metric IN ({metric_list_sql})
            )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE obs_metric_snapshots DROP CONSTRAINT IF EXISTS ck_oms_metric")
    metric_list_sql = ", ".join(repr(m) for m in _ALLOWED_METRICS_BEFORE)
    op.execute(
        f"""
        ALTER TABLE obs_metric_snapshots
            ADD CONSTRAINT ck_oms_metric CHECK (
                metric IN ({metric_list_sql})
            )
        """
    )
