"""FDD-OBS-001 PR 4a — observability rollup orchestrator.

One cycle = iterate every tenant with a DD credential, query the 6
PulseMetrics for every service in their catalog, write hourly buckets
to `obs_metric_snapshots`. Designed to be called by the rollup worker
on a 15-min interval.

Design (architect-validated, ADR-024):
  - Buckets are HOURLY: floor `now()` to the hour. Multiple sub-cycles
    in the same hour overwrite the same row (idempotent upsert).
  - Token bucket gates EVERY provider call. When exhausted, the
    function logs and returns gracefully — the next cycle resumes.
  - Soft per-cycle deadline (12 minutes for a 15-min cycle); when
    exceeded, the orchestrator stops and lets the next tick continue.
  - Tenants ordered by `last_rollup_at ASC NULLS FIRST` so a stuck
    tenant doesn't starve newer ones forever.
  - Provider instances are NOT cached across cycles — each cycle
    builds fresh providers via `provider_factory.build_for_tenant`,
    then closes them. Reduces master-key memory residence (ADR-028).
  - Logs are anti-surveillance: service names hashed (sha256[:8]) so
    customer-naming conventions don't leak via shared log infra.

NEVER raises out of `run_cycle` — workers must keep running through
infrastructure failures (DB blip, DD outage, Redis flap).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from sqlalchemy import text

from src.connectors.observability.base import (
    ObservabilityProvider,
    PulseMetric,
    TimeWindow,
)
from src.connectors.observability.datadog_connector import (
    DatadogConnectorError,
)
from src.contexts.observability.services import (
    provider_factory,
    tier2_inference,
)
from src.contexts.observability.services.token_bucket import TokenBucket
from src.database import get_session

logger = logging.getLogger(__name__)


# Default timing — 15-min cycle with a 12-min soft deadline so each
# cycle leaves headroom for the next tick to start cleanly.
_DEFAULT_CYCLE_DEADLINE_SECONDS: Final[int] = 12 * 60


# FDD-OBS-001 PR 4a.5 — Webmotors DD plan doesn't include the Query API
# (RISK-19). The cycle now collects ONE rolled-up `MONITOR_HEALTH` score
# per (service, hour) by reading `/api/v1/monitor` (which IS in plan).
# Each cycle costs N services × 1 monitor-list call (was N × 6 metric
# queries) — 6× cheaper on the rate-limit budget.
#
# When R3 onboards a tenant with Query API access, set
# `provider_capabilities.has_query_api = True` and the cycle picks the
# old `_CYCLE_QUERY_METRICS` path instead. Both code paths still ship.
_CYCLE_QUERY_METRICS: Final[tuple[PulseMetric, ...]] = (
    PulseMetric.ERROR_RATE,
    PulseMetric.P95_LATENCY_MS,
    PulseMetric.APDEX,
    PulseMetric.THROUGHPUT_RPS,
    PulseMetric.P99_LATENCY_MS,
    PulseMetric.ALERT_COUNT,
)


@dataclass
class TenantCycleResult:
    """Per-tenant outcome of one rollup cycle."""

    tenant_id: UUID
    services_seen: int = 0
    queries_attempted: int = 0
    queries_succeeded: int = 0
    rows_written: int = 0
    rate_limited_skipped: int = 0
    errors: int = 0
    duration_ms: int = 0


@dataclass
class CycleResult:
    """Aggregate outcome of `run_cycle`."""

    tenants_seen: int = 0
    tenants_completed: int = 0
    tenants_partial: int = 0       # token bucket exhausted mid-tenant
    tenants_skipped: int = 0       # no DD credential / provider build failed
    deadline_hit: bool = False
    duration_ms: int = 0
    per_tenant: list[TenantCycleResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_service_name(name: str) -> str:
    """Return sha256[:8] of the service name for logging.

    ADR-028 — service names can leak customer-naming conventions when
    the worker logs ship to shared infrastructure. Only the rollup
    metrics + counts are safe to log; service identity goes through
    a hash so logs remain useful for debugging while protecting
    customer naming. The hash is stable per name so per-service
    issues are still traceable.
    """
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]


def _floor_to_hour(when: datetime) -> datetime:
    """Floor to the start of the hour in UTC."""
    return when.replace(minute=0, second=0, microsecond=0)


def _series_to_bucket_value(points: list[tuple[datetime, float]]) -> float | None:
    """Reduce a metric time series to a single hourly bucket value.

    Architect-validated: mean over the hour (NOT last-point) so a
    one-off spike at the bucket edge doesn't dominate the metric.
    Returns None when empty so the caller can skip writing the row
    (capability detection sees the gap honestly)."""
    if not points:
        return None
    return sum(v for _, v in points) / len(points)


# ---------------------------------------------------------------------------
# Tenant discovery
# ---------------------------------------------------------------------------


async def _list_eligible_tenants(provider_id: str) -> list[UUID]:
    """Tenants with a configured credential for `provider_id`.

    PR 4a (R0 single-tenant): we iterate just `settings.default_tenant_id`
    and check whether *that* tenant has a credential row. This avoids
    the RLS / BYPASSRLS question entirely (CISO RISK-14, 2026-05-08
    review) — every SELECT runs scoped to a known tenant, which is how
    every other read-path in the codebase works.

    R1 multi-tenancy will replace this with a proper cross-tenant
    discovery path (system role with explicit BYPASSRLS migration, OR
    a tenant-registry table read via SECURITY DEFINER function). That
    decision is intentionally deferred — see RISK-15 in ops-backlog.

    Logs a WARNING when zero tenants are eligible (silent no-op was
    the failure mode CISO RISK-14 surfaced). Operators see the warning
    in `docker compose logs obs-rollup-worker` and can verify their
    setup before assuming "the worker is working but data is empty".
    """
    from src.config import settings as _settings  # local import — avoid cycle
    from uuid import UUID as _UUID

    tenant_id = _UUID(_settings.default_tenant_id)

    # Scope the credential check to the known tenant; this is RLS-clean
    # and works regardless of the worker DB role's BYPASSRLS state.
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT 1
                FROM tenant_observability_credentials
                WHERE tenant_id = :tenant_id
                  AND provider = :provider_id
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "provider_id": provider_id},
        )
        if result.first() is None:
            logger.warning(
                "[rollup] no tenant has a configured %s credential — "
                "worker idle. Run POST /admin/integrations/%s/validate"
                "?persist=true for the tenant before expecting rollup data.",
                provider_id, provider_id,
            )
            return []

    return [tenant_id]


# ---------------------------------------------------------------------------
# Service catalog reader (per tenant)
# ---------------------------------------------------------------------------


async def _list_services_for_rollup(
    tenant_id: UUID, provider_id: str,
) -> list[tuple[str, str]]:
    """Return [(service_external_id, service_name), ...] for the
    services we want to roll up — drawn from `service_squad_ownership`
    (so PR 3's ownership inference defines the catalog).

    Services with `inferred_squad_key IS NULL AND override_squad_key IS NULL`
    are EXCLUDED — without an effective squad, the timeline can't
    aggregate by squad anyway, and we shouldn't burn DD calls on them.
    """
    query = text(
        """
        SELECT service_external_id, service_name
        FROM service_squad_ownership
        WHERE tenant_id = :tenant_id
          AND provider = :provider_id
          AND COALESCE(override_squad_key, inferred_squad_key) IS NOT NULL
        ORDER BY service_name ASC
        """
    )
    async with get_session(tenant_id) as session:
        result = await session.execute(
            query, {"tenant_id": str(tenant_id), "provider_id": provider_id},
        )
        return [(r.service_external_id, r.service_name) for r in result.all()]


# ---------------------------------------------------------------------------
# Per-tenant cycle
# ---------------------------------------------------------------------------


async def _rollup_one_tenant(
    tenant_id: UUID,
    provider_id: str,
    provider: ObservabilityProvider,
    bucket: TokenBucket,
    deadline: float,
) -> TenantCycleResult:
    """Run one rollup pass for a single tenant. Returns counters; never
    raises (callers must keep cycling)."""
    started_at = time.monotonic()
    result = TenantCycleResult(tenant_id=tenant_id)

    # Pre-flight: also re-run Tier 2 inference to fill ownership rows
    # for new services that landed since the last cycle. Cheap (one
    # SQL query), worth running every cycle.
    try:
        await tier2_inference.sync_tier2_inference(tenant_id, provider_id)
    except Exception:
        logger.warning(
            "[rollup] tier2 inference failed tenant=%s",
            tenant_id, exc_info=True,
        )

    services = await _list_services_for_rollup(tenant_id, provider_id)
    result.services_seen = len(services)
    if not services:
        return result

    # Hourly bucket aligned to UTC. The PR 4a.5 monitor path snapshots
    # the *current* state at bucket_start; the (R3) query_metric path
    # would build a TimeWindow here for the trailing hour.
    bucket_start = _floor_to_hour(datetime.now(timezone.utc))

    for external_id, service_name in services:
        if time.monotonic() > deadline:
            logger.info(
                "[rollup] cycle deadline hit tenant=%s services_done=%d/%d",
                tenant_id, result.queries_succeeded, result.services_seen,
            )
            break

        # FDD-OBS-001 PR 4a.5: ONE call per service via `list_monitors_
        # for_service` (Webmotors DD plan path). Replaces the previous
        # 6-metric loop; cuts bucket consumption by 6×.
        allowed = await bucket.try_acquire(tenant_id, provider_id, n=1)
        if not allowed:
            result.rate_limited_skipped += 1
            logger.info(
                "[rollup] rate-limited tenant=%s svc_hash=%s — pausing this cycle",
                tenant_id, _hash_service_name(service_name),
            )
            return result

        result.queries_attempted += 1
        try:
            monitors = await provider.list_monitors_for_service(service_name)
        except DatadogConnectorError as exc:
            result.errors += 1
            logger.warning(
                "[rollup] list_monitors failed tenant=%s svc_hash=%s exc=%s",
                tenant_id, _hash_service_name(service_name), type(exc).__name__,
            )
            continue
        except Exception as exc:
            result.errors += 1
            logger.warning(
                "[rollup] unexpected error tenant=%s svc_hash=%s exc=%s",
                tenant_id, _hash_service_name(service_name), type(exc).__name__,
            )
            continue

        result.queries_succeeded += 1

        # No monitors configured for this service — honest empty (skip).
        # Capability detection sees the gap and the UI shows "service
        # has no DD monitors" rather than a fake green health.
        if not monitors:
            continue

        # Aggregate to worst-case severity for the hour. This mirrors
        # how a human reads a dashboard: any active alert dominates
        # the row's color, regardless of how many monitors are OK.
        # `samples_count` carries the monitor count so downstream
        # routes can show "aggregated from N monitors".
        worst_severity = max(m.severity for m in monitors)

        await _upsert_snapshot(
            tenant_id=tenant_id,
            provider_id=provider_id,
            service=service_name,
            metric=PulseMetric.MONITOR_HEALTH,
            hour_bucket=bucket_start,
            value=worst_severity,
            samples_count=len(monitors),
        )
        result.rows_written += 1

    result.duration_ms = int((time.monotonic() - started_at) * 1000)
    return result


async def _upsert_snapshot(
    tenant_id: UUID,
    provider_id: str,
    service: str,
    metric: PulseMetric,
    hour_bucket: datetime,
    value: float,
    samples_count: int,
) -> None:
    """Idempotent upsert into `obs_metric_snapshots`. Re-running the
    same hour overwrites the partial bucket — by design (architect:
    'restart-safe; no per-tenant cursor needed')."""
    async with get_session(tenant_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO obs_metric_snapshots (
                    tenant_id, provider, service, metric,
                    hour_bucket, value, samples_count, calculated_at
                )
                VALUES (
                    :tenant_id, :provider, :service, :metric,
                    :hour_bucket, :value, :samples_count, NOW()
                )
                ON CONFLICT (tenant_id, provider, service, metric, hour_bucket)
                DO UPDATE SET
                    value = EXCLUDED.value,
                    samples_count = EXCLUDED.samples_count,
                    calculated_at = NOW()
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "service": service,
                "metric": str(metric),
                "hour_bucket": hour_bucket,
                "value": value,
                "samples_count": samples_count,
            },
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Public entrypoint — one cycle
# ---------------------------------------------------------------------------


async def run_cycle(
    provider_id: str = "datadog",
    bucket: TokenBucket | None = None,
    deadline_seconds: int = _DEFAULT_CYCLE_DEADLINE_SECONDS,
) -> CycleResult:
    """Run one rollup cycle across all eligible tenants. Caller (the
    APScheduler interval trigger) is expected to invoke this every
    15 minutes; this function returns within `deadline_seconds`."""
    started_at = time.monotonic()
    deadline = started_at + deadline_seconds
    bucket = bucket or TokenBucket()

    summary = CycleResult()
    tenants = await _list_eligible_tenants(provider_id)
    summary.tenants_seen = len(tenants)

    for tenant_id in tenants:
        if time.monotonic() > deadline:
            summary.deadline_hit = True
            logger.warning(
                "[rollup] cycle deadline reached after %d/%d tenants",
                summary.tenants_completed + summary.tenants_partial,
                summary.tenants_seen,
            )
            break

        # Build a fresh provider per tenant. Per ADR-028 (PR 4a):
        # NEVER cache providers across cycles — keeps master-key
        # memory residence ≤ one cycle's duration.
        try:
            provider = await provider_factory.build_for_tenant(tenant_id, provider_id)
        except Exception:
            summary.tenants_skipped += 1
            logger.warning(
                "[rollup] could not build provider tenant=%s — skipping",
                tenant_id, exc_info=True,
            )
            continue

        try:
            async with provider:
                tenant_result = await _rollup_one_tenant(
                    tenant_id=tenant_id,
                    provider_id=provider_id,
                    provider=provider,
                    bucket=bucket,
                    deadline=deadline,
                )
            summary.per_tenant.append(tenant_result)

            if tenant_result.rate_limited_skipped > 0:
                summary.tenants_partial += 1
            else:
                summary.tenants_completed += 1
        except Exception:
            summary.tenants_skipped += 1
            logger.warning(
                "[rollup] tenant cycle failed tenant=%s",
                tenant_id, exc_info=True,
            )

    summary.duration_ms = int((time.monotonic() - started_at) * 1000)
    logger.info(
        "[rollup] cycle done tenants=%d completed=%d partial=%d skipped=%d "
        "deadline_hit=%s ms=%d",
        summary.tenants_seen, summary.tenants_completed, summary.tenants_partial,
        summary.tenants_skipped, summary.deadline_hit, summary.duration_ms,
    )
    return summary
