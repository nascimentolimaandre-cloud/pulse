"""MetricsSnapshot writer — persists calculated metrics to the database.

Handles upsert logic: if a snapshot already exists for the same
(tenant, team, metric_type, metric_name, period), it updates the value
and calculated_at timestamp. Otherwise, it inserts a new row.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.contexts.metrics.infrastructure.models import MetricsSnapshot
from src.contexts.metrics.infrastructure.schema_registry import expected_fields
from src.database import get_session
from src.shared.metrics import snapshot_schema_drift_total

logger = logging.getLogger(__name__)


def _detect_schema_drift(
    metric_type: str,
    metric_name: str,
    value: dict[str, Any] | Any,
) -> list[str]:
    """Compare payload keys against registered schema; mutate payload on drift.

    When the payload is a dict AND the (metric_type, metric_name) pair is
    registered, compute the set of fields declared on the current
    dataclass but missing from the payload. If any are missing:

    1. Log a structured warning (picked up by json log shipping).
    2. Increment the Prometheus counter (best-effort; no-op when the
       client is absent).
    3. Annotate the payload with `_schema_drift` so the Pipeline Monitor
       can surface affected rows via GET /pipeline/schema-drift.

    Drift is NEVER a hard error — the snapshot still gets written. A
    partial record is strictly better than no record (or an exception).

    Returns the sorted list of missing fields (empty when no drift).
    """
    if not isinstance(value, dict):
        return []

    expected = expected_fields(metric_type, metric_name)
    if expected is None:
        return []

    actual = set(value.keys())
    # Ignore our own annotation — it's appended by this very function.
    actual.discard("_schema_drift")
    missing = sorted(expected - actual)
    if not missing:
        return []

    logger.warning(
        "snapshot_schema_drift",
        extra={
            "metric_type": metric_type,
            "metric_name": metric_name,
            "missing_fields": missing,
            "remedy": (
                "Worker bytecode out of sync — "
                "`docker compose restart <worker>` or POST /admin/metrics/recalculate"
            ),
            "tag": "FDD-OPS-001/L3",
        },
    )
    try:
        snapshot_schema_drift_total.labels(
            metric_type=metric_type,
            metric_name=metric_name,
        ).inc()
    except Exception:  # noqa: BLE001 — metrics must never raise
        pass

    # Annotate in-place so downstream readers (Pipeline Monitor) can find it.
    value["_schema_drift"] = {
        "missing_fields": missing,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    return missing


def _json_safe(obj: Any) -> Any:
    """Recursively convert date/datetime objects to ISO strings for JSONB storage."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(item) for item in obj]
    return obj


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
    # FDD-OPS-001 L3: detect drift BEFORE serializing. Mutates `value`
    # in-place to add the `_schema_drift` annotation when applicable.
    _detect_schema_drift(metric_type, metric_name, value)
    safe_value = _json_safe(value)

    async with get_session(tenant_id) as session:
        stmt = (
            pg_insert(MetricsSnapshot)
            .values(
                tenant_id=tenant_id,
                team_id=team_id,
                metric_type=metric_type,
                metric_name=metric_name,
                value=safe_value,
                period_start=period_start,
                period_end=period_end,
                calculated_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "team_id", "metric_type", "metric_name", "period_start", "period_end"],
                set_={
                    "value": safe_value,
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
                # FDD-OPS-001 L3: same drift check as write_snapshot.
                _detect_schema_drift(snap["metric_type"], snap["metric_name"], snap["value"])
                safe_value = _json_safe(snap["value"])
                stmt = (
                    pg_insert(MetricsSnapshot)
                    .values(
                        tenant_id=snap["tenant_id"],
                        team_id=snap.get("team_id"),
                        metric_type=snap["metric_type"],
                        metric_name=snap["metric_name"],
                        value=safe_value,
                        period_start=snap["period_start"],
                        period_end=snap["period_end"],
                        calculated_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "team_id", "metric_type", "metric_name", "period_start", "period_end"],
                        set_={
                            "value": safe_value,
                            "calculated_at": now,
                            "updated_at": now,
                        },
                    )
                )
                await session.execute(stmt)
                count += 1

    logger.info("Wrote %d metric snapshots in batch", count)
    return count
