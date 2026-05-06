"""FDD-OBS-001 PR 1 — Capability detection (ADR-026 Principle 1).

Inspects the tenant's observability setup and returns
`ObservabilityCapabilities` describing what the Signals features can
deliver right now. Routes call this BEFORE rendering Signals views;
unmet capabilities → honest empty state (not 500, not zero).

PR 1 ships the **always-empty** path: there's no provider connected
yet (PR 2 introduces credentials + DD adapter). The service still
queries the DB to detect rows in `tenant_observability_credentials`
and returns the appropriate capabilities object — so when PR 2 lands,
this service starts returning real values without code changes.

Reads:
  - `tenant_observability_credentials` → has_provider, has_validated_creds
  - `service_squad_ownership` → services_mapped_pct
  - `obs_metric_snapshots` → has_metric_signal, last_rollup_at
  - (TODO PR 4) Redis token bucket → rate_limit_remaining

Writes: nothing. Pure read.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.connectors.observability.base import ObservabilityCapabilities
from src.database import get_session

logger = logging.getLogger(__name__)


async def get_capabilities(tenant_id: UUID) -> ObservabilityCapabilities:
    """Return the tenant's current observability capabilities.

    Always returns — never raises. On DB failure, returns
    `ObservabilityCapabilities.empty()` (graceful degradation per
    ADR-026 Principle 4).
    """
    try:
        async with get_session(tenant_id) as session:
            # 1. Provider connected + validated?
            creds_row = await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS provider_count,
                        COUNT(*) FILTER (WHERE validated_at IS NOT NULL) AS validated_count
                    FROM tenant_observability_credentials
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
            creds = creds_row.first()
            has_provider = bool(creds and (creds.provider_count or 0) > 0)
            has_validated_creds = bool(creds and (creds.validated_count or 0) > 0)

            if not has_provider:
                # Short-circuit: nothing else can have data.
                return ObservabilityCapabilities.empty()

            # 2. Service ownership coverage
            ownership_row = await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS total_services,
                        COUNT(*) FILTER (
                            WHERE COALESCE(override_squad_key, inferred_squad_key) IS NOT NULL
                        ) AS mapped_services
                    FROM service_squad_ownership
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
            ownership = ownership_row.first()
            total = (ownership.total_services if ownership else 0) or 0
            mapped = (ownership.mapped_services if ownership else 0) or 0
            services_mapped_pct = round(mapped / total, 4) if total > 0 else 0.0

            # 3. Metric signal + rollup freshness
            since_30d = datetime.now(timezone.utc) - timedelta(days=30)
            rollup_row = await session.execute(
                text(
                    """
                    SELECT
                        MAX(calculated_at) AS last_calc,
                        COUNT(*) FILTER (WHERE hour_bucket >= :since_30d) AS recent_buckets
                    FROM obs_metric_snapshots
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": str(tenant_id), "since_30d": since_30d},
            )
            rollup = rollup_row.first()
            last_rollup_at = rollup.last_calc if rollup else None
            has_metric_signal = bool(rollup and (rollup.recent_buckets or 0) > 0)

            # has_deploy_markers — same source (deploys are stored as a
            # specific metric series for each service). Approximate with
            # has_metric_signal until PR 2 introduces deploy ingestion.
            has_deploy_markers = has_metric_signal

            return ObservabilityCapabilities(
                has_provider=has_provider,
                has_validated_creds=has_validated_creds,
                services_mapped_pct=services_mapped_pct,
                has_deploy_markers=has_deploy_markers,
                has_metric_signal=has_metric_signal,
                last_rollup_at=last_rollup_at,
                # TODO PR 4: read from Redis token bucket. None for now
                # signals "not yet measured" rather than zero.
                rate_limit_remaining=None,
            )
    except Exception:
        logger.warning(
            "capability_detection failed — returning empty (graceful degradation)",
            extra={"tenant_id": str(tenant_id)},
            exc_info=True,
        )
        return ObservabilityCapabilities.empty()
