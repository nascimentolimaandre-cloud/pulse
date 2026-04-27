"""Partial index for fast `latest snapshots per tenant+metric_type` lookups.

Fixes a 50× perf regression in `/data/v1/metrics/home` once the
metrics_snapshots table grew past ~5M rows (Webmotors hit it at
~2026-04-24 with 7M rows). The frontend axios client has a 30s
timeout; the endpoint was taking 50-60s on cold-path because the
8 underlying queries (4 metric types × current+previous period)
were each doing a parallel seq scan over the whole table.

Root cause:
- `_get_all_latest_snapshots` issues
  `WHERE tenant_id=? AND metric_type=? AND team_id IS NULL
   ORDER BY calculated_at DESC LIMIT 200`
- Existing index `idx_metrics_snapshots_lookup` is on
  `(tenant_id, metric_type, metric_name, period_start, period_end)`
  — usable for the WHERE prefix but the ORDER BY calculated_at
  forced a sort over the entire matched set (~5M rows for 'lean').
- Postgres B-tree treats `IS NULL` specially; a non-partial index
  including team_id was not chosen by the planner.

Solution: partial B-tree index `WHERE team_id IS NULL`, ordered
by `(tenant_id, metric_type, calculated_at DESC)`. Covers exactly
the global tenant-wide aggregation queries and is much smaller
than a full index (the team_id IS NULL slice is the dominant one,
but excluding team-scoped rows keeps the index lean).

Verified locally:
- Before: Parallel Seq Scan, 10.3s for one query, 50s+ for /home.
- After:  Index Scan, 2.4ms, 600ms total for /home.

Anti-surveillance: index is purely on metric metadata + tenant +
calculated_at; no PII.

Revision ID: 009_metrics_snapshots_tenant_latest_index
Revises: 008_eng_issues_description
Create Date: 2026-04-24
"""

from typing import Sequence, Union

from alembic import op


revision: str = "009_metrics_snapshots_tenant_latest_index"
down_revision: Union[str, None] = "008_eng_issues_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial index for the tenant-wide (team_id IS NULL) latest-snapshots
    # access pattern used by /metrics/home, /metrics/dora, /metrics/lean,
    # etc. The DESC on calculated_at lets ORDER BY ... LIMIT N use the
    # index without a sort step.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metrics_snapshots_tenant_latest
            ON metrics_snapshots (tenant_id, metric_type, calculated_at DESC)
            WHERE team_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_metrics_snapshots_tenant_latest")
