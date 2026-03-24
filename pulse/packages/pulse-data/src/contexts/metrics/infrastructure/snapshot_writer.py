"""MetricsSnapshot writer — persists calculated metrics to the database.

Handles upsert logic: if a snapshot already exists for the same
(tenant, team, metric_type, metric_name, period), it updates the value
and calculated_at timestamp. Otherwise, it inserts a new row.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.contexts.metrics.infrastructure.models import MetricsSnapshot
from src.database import get_session

logger = logging.getLogger(__name__)


async def write_snapshot(
    tenant_id: UUID,
    team_id: UUID | None,
    metric_type: str,
    metric_name: str,
    value: dict[str, Any],
    period_start: datetime,
    period_end: datetime,
) -> None:
    """Write or update a single metrics snapshot.

    Uses PostgreSQL ON CONFLICT (uq_metrics_snapshot_key) DO UPDATE
    for idempotent writes.

    Args:
        tenant_id: The tenant UUID.
        team_id: The team UUID (None for org-level metrics).
        metric_type: Category of metric (dora, lean, cycle_time, throughput, sprint).
        metric_name: Specific metric name (deployment_frequency, lead_time, etc.).
        value: The calculated metric value as JSONB-serializable dict.
        period_start: Start of the measurement period.
        period_end: End of the measurement period.
    """
    now = datetime.now(timezone.utc)

    async with get_session(tenant_id) as session:
        stmt = (
            pg_insert(MetricsSnapshot)
            .values(
                tenant_id=tenant_id,
                team_id=team_id,
                metric_type=metric_type,
                metric_name=metric_name,
                value=value,
                period_start=period_start,
                period_end=period_end,
                calculated_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_metrics_snapshot_key",
                set_={
                    "value": value,
                    "calculated_at": now,
                    "updated_at": now,
                },
            )
        )
        await session.execute(stmt)

    logger.info(
        "Wrote snapshot: type=%s name=%s team=%s period=%s..%s",
        metric_type,
        metric_name,
        team_id,
        period_start.date(),
        period_end.date(),
    )


async def write_snapshots_batch(
    snapshots: list[dict[str, Any]],
) -> int:
    """Write multiple metric snapshots in a single transaction.

    Each snapshot dict must contain:
    - tenant_id, team_id, metric_type, metric_name
    - value, period_start, period_end

    Args:
        snapshots: List of snapshot dicts.

    Returns:
        Number of snapshots written.
    """
    if not snapshots:
        return 0

    # Group by tenant for RLS efficiency
    by_tenant: dict[UUID, list[dict[str, Any]]] = {}
    for snap in snapshots:
        tid = snap["tenant_id"]
        by_tenant.setdefault(tid, []).append(snap)

    count = 0
    now = datetime.now(timezone.utc)

    for tenant_id, tenant_snaps in by_tenant.items():
        async with get_session(tenant_id) as session:
            for snap in tenant_snaps:
                stmt = (
                    pg_insert(MetricsSnapshot)
                    .values(
                        tenant_id=snap["tenant_id"],
                        team_id=snap.get("team_id"),
                        metric_type=snap["metric_type"],
                        metric_name=snap["metric_name"],
                        value=snap["value"],
                        period_start=snap["period_start"],
                        period_end=snap["period_end"],
                        calculated_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        constraint="uq_metrics_snapshot_key",
                        set_={
                            "value": snap["value"],
                            "calculated_at": now,
                            "updated_at": now,
                        },
                    )
                )
                await session.execute(stmt)
                count += 1

    logger.info("Wrote %d metric snapshots in batch", count)
    return count
