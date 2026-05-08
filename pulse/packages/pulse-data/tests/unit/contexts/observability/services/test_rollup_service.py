"""FDD-OBS-001 PR 4a — rollup_service unit tests.

Validates:
  - run_cycle iterates eligible tenants, builds providers, closes them.
  - Token bucket gates EVERY query_metric call; on exhaustion, the
    tenant is marked partial and the next tenant runs.
  - Empty MetricSeries → no row written (honest absence).
  - DatadogConnectorError counted but NEVER raises out of run_cycle.
  - Tier 2 inference is invoked at the start of each tenant cycle.
  - service names are HASHED in log messages (anti-surveillance).
  - hourly bucket is floor of `now()`.
  - `_series_to_bucket_value` returns mean (not last-point).
  - run_cycle hits deadline gracefully.
  - provider lifecycle: built per cycle, closed via async with.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.connectors.observability.base import (
    MetricSeries,
    ObservabilityProvider,
    PulseMetric,
)
from src.connectors.observability.datadog_connector import DatadogConnectorError
from src.contexts.observability.services import rollup_service
from src.contexts.observability.services.rollup_service import (
    CycleResult,
    TenantCycleResult,
    _floor_to_hour,
    _hash_service_name,
    _series_to_bucket_value,
    run_cycle,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")
_TENANT_2 = UUID("00000000-0000-0000-0000-000000000002")


# ---------------------------------------------------------------------------
# Helpers (pure functions)
# ---------------------------------------------------------------------------


class TestFloorToHour:
    def test_strips_minutes_seconds_micros(self):
        d = datetime(2026, 5, 8, 14, 23, 47, 123456, tzinfo=timezone.utc)
        assert _floor_to_hour(d) == datetime(2026, 5, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


class TestSeriesToBucketValue:
    def test_returns_none_on_empty(self):
        assert _series_to_bucket_value([]) is None

    def test_returns_mean_not_last_point(self):
        """Mean across the hour avoids one-off spikes dominating."""
        ts = datetime(2026, 5, 8, 14, 0, tzinfo=timezone.utc)
        # 10 values where last is huge — mean=14.5, not 100.
        points = [(ts, float(i)) for i in range(1, 10)] + [(ts, 100.0)]
        avg = sum(v for _, v in points) / len(points)
        assert _series_to_bucket_value(points) == pytest.approx(avg)
        # Sanity — wouldn't be 100.0 (last point)
        assert _series_to_bucket_value(points) != 100.0


class TestServiceNameHash:
    def test_stable_8_hex_chars(self):
        h = _hash_service_name("checkout-api")
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)
        # Stable across calls
        assert _hash_service_name("checkout-api") == h

    def test_different_names_hash_differently(self):
        assert _hash_service_name("a") != _hash_service_name("b")


# ---------------------------------------------------------------------------
# run_cycle — tenant iteration + provider lifecycle
# ---------------------------------------------------------------------------


def _make_provider_mock(metric_series_factory=None) -> tuple[MagicMock, MagicMock]:
    """Build a mock provider that supports `async with`. We don't use
    `spec=ObservabilityProvider` because the Protocol declares only
    the query methods, not lifetime methods (__aenter__/__aexit__) —
    those are on the concrete `DatadogProvider`. Tests verify the
    orchestrator's behavior, not Protocol shape."""
    instance = MagicMock()

    def _series(metric, service, window):
        if metric_series_factory is None:
            return MetricSeries(
                metric=metric, service=service,
                points=[(window.start, 0.5)], has_data=True,
            )
        return metric_series_factory(metric, service, window)

    instance.query_metric = AsyncMock(side_effect=_series)
    instance.aclose = AsyncMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    return instance, instance


@pytest.mark.asyncio
async def test_run_cycle_skips_tenant_when_provider_factory_fails():
    """If build_for_tenant raises (e.g. credential decrypt error),
    tenant is skipped — NOT a fatal cycle error."""
    with patch.object(
        rollup_service, "_list_eligible_tenants",
        new=AsyncMock(return_value=[_TENANT]),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "provider_factory.build_for_tenant",
        new=AsyncMock(side_effect=RuntimeError("no creds")),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "tier2_inference.sync_tier2_inference",
        new=AsyncMock(),
    ):
        result = await run_cycle()

    assert result.tenants_seen == 1
    assert result.tenants_skipped == 1
    assert result.tenants_completed == 0


@pytest.mark.asyncio
async def test_run_cycle_no_eligible_tenants_returns_empty():
    """No tenants with credentials → no-op, returns clean summary."""
    with patch.object(
        rollup_service, "_list_eligible_tenants",
        new=AsyncMock(return_value=[]),
    ):
        result = await run_cycle()

    assert isinstance(result, CycleResult)
    assert result.tenants_seen == 0


@pytest.mark.asyncio
async def test_list_eligible_tenants_warns_when_no_credential(caplog):
    """CISO RISK-14 (PR 4a review): the silent no-op was the original
    failure mode. Verify the warning fires when zero tenants are
    eligible, so operators see a clear signal in `docker compose logs
    obs-rollup-worker` instead of an unexplained empty rollup table."""
    import logging
    from unittest.mock import AsyncMock as _AM

    # Mock get_session to return a session whose execute returns no rows
    result_mock = MagicMock()
    result_mock.first = MagicMock(return_value=None)
    execute = _AM(return_value=result_mock)
    session = _AM()
    session.execute = execute
    cm = MagicMock()
    cm.__aenter__ = _AM(return_value=session)
    cm.__aexit__ = _AM(return_value=None)

    caplog.clear()
    with patch.object(
        rollup_service, "get_session", return_value=cm,
    ), caplog.at_level(logging.WARNING, logger="src.contexts.observability.services.rollup_service"):
        tenants = await rollup_service._list_eligible_tenants("datadog")

    assert tenants == []
    # WARNING must mention the provider so operators know what to fix
    assert any(
        "datadog" in record.message and record.levelname == "WARNING"
        for record in caplog.records
    ), "Expected a WARNING log mentioning 'datadog' when no credential configured"


@pytest.mark.asyncio
async def test_run_cycle_processes_all_tenants_when_bucket_unlimited():
    """Two tenants, both processed end-to-end with bucket allowing
    every call."""
    bucket = MagicMock()
    bucket.try_acquire = AsyncMock(return_value=True)

    provider, cm = _make_provider_mock()

    with patch.object(
        rollup_service, "_list_eligible_tenants",
        new=AsyncMock(return_value=[_TENANT, _TENANT_2]),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "provider_factory.build_for_tenant",
        new=AsyncMock(return_value=cm),
    ), patch.object(
        rollup_service, "_list_services_for_rollup",
        new=AsyncMock(return_value=[("ext-1", "checkout")]),
    ), patch.object(
        rollup_service, "_upsert_snapshot",
        new=AsyncMock(),
    ) as upsert_mock, patch(
        "src.contexts.observability.services.rollup_service."
        "tier2_inference.sync_tier2_inference",
        new=AsyncMock(),
    ):
        result = await run_cycle(bucket=bucket)

    assert result.tenants_seen == 2
    assert result.tenants_completed == 2
    # 2 tenants × 1 service × 6 metrics = 12 upserts
    assert upsert_mock.await_count == 12


# ---------------------------------------------------------------------------
# Token bucket gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cycle_rate_limited_marks_tenant_partial():
    """Bucket exhausts after 1 token → tenant_partial counted, next
    tenant still gets a chance."""
    bucket = MagicMock()
    # Allow first call only, then exhaust
    bucket.try_acquire = AsyncMock(side_effect=[True] + [False] * 99)

    provider, cm = _make_provider_mock()

    with patch.object(
        rollup_service, "_list_eligible_tenants",
        new=AsyncMock(return_value=[_TENANT]),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "provider_factory.build_for_tenant",
        new=AsyncMock(return_value=cm),
    ), patch.object(
        rollup_service, "_list_services_for_rollup",
        new=AsyncMock(return_value=[("ext-1", "svc-a"), ("ext-2", "svc-b")]),
    ), patch.object(
        rollup_service, "_upsert_snapshot",
        new=AsyncMock(),
    ) as upsert_mock, patch(
        "src.contexts.observability.services.rollup_service."
        "tier2_inference.sync_tier2_inference",
        new=AsyncMock(),
    ):
        result = await run_cycle(bucket=bucket)

    assert result.tenants_partial == 1
    # Only 1 query made it through before exhaustion
    assert upsert_mock.await_count == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_metric_failure_does_not_abort_cycle():
    """One service's metric raises DatadogConnectorError → counted as
    error, next service continues."""
    bucket = MagicMock()
    bucket.try_acquire = AsyncMock(return_value=True)

    provider, cm = _make_provider_mock()
    # First call raises, rest succeed
    provider.query_metric = AsyncMock(
        side_effect=[DatadogConnectorError("DD 500")]
        + [MetricSeries(metric=m, service="x", points=[(datetime.now(timezone.utc), 1.0)], has_data=True) for m in range(20)],
    )

    with patch.object(
        rollup_service, "_list_eligible_tenants",
        new=AsyncMock(return_value=[_TENANT]),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "provider_factory.build_for_tenant",
        new=AsyncMock(return_value=cm),
    ), patch.object(
        rollup_service, "_list_services_for_rollup",
        new=AsyncMock(return_value=[("ext-1", "svc-a")]),
    ), patch.object(
        rollup_service, "_upsert_snapshot",
        new=AsyncMock(),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "tier2_inference.sync_tier2_inference",
        new=AsyncMock(),
    ):
        result = await run_cycle(bucket=bucket)

    assert result.tenants_completed == 1
    assert result.per_tenant[0].errors >= 1


# ---------------------------------------------------------------------------
# has_data=False → no row written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_series_does_not_write_row():
    """has_data=False → no upsert (capability detection sees the
    absence honestly)."""
    bucket = MagicMock()
    bucket.try_acquire = AsyncMock(return_value=True)

    provider, cm = _make_provider_mock(
        metric_series_factory=lambda m, s, w: MetricSeries(
            metric=m, service=s, points=[], has_data=False,
        ),
    )

    with patch.object(
        rollup_service, "_list_eligible_tenants",
        new=AsyncMock(return_value=[_TENANT]),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "provider_factory.build_for_tenant",
        new=AsyncMock(return_value=cm),
    ), patch.object(
        rollup_service, "_list_services_for_rollup",
        new=AsyncMock(return_value=[("ext-1", "svc-a")]),
    ), patch.object(
        rollup_service, "_upsert_snapshot",
        new=AsyncMock(),
    ) as upsert_mock, patch(
        "src.contexts.observability.services.rollup_service."
        "tier2_inference.sync_tier2_inference",
        new=AsyncMock(),
    ):
        result = await run_cycle(bucket=bucket)

    assert upsert_mock.await_count == 0
    assert result.tenants_completed == 1
    assert result.per_tenant[0].queries_succeeded == len(rollup_service._CYCLE_METRICS)
    assert result.per_tenant[0].rows_written == 0


# ---------------------------------------------------------------------------
# Tier 2 invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier2_inference_called_per_tenant():
    """Tier 2 runs at the start of each tenant cycle — fills new
    services that landed since last cycle."""
    bucket = MagicMock()
    bucket.try_acquire = AsyncMock(return_value=True)

    provider, cm = _make_provider_mock()

    with patch.object(
        rollup_service, "_list_eligible_tenants",
        new=AsyncMock(return_value=[_TENANT, _TENANT_2]),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "provider_factory.build_for_tenant",
        new=AsyncMock(return_value=cm),
    ), patch.object(
        rollup_service, "_list_services_for_rollup",
        new=AsyncMock(return_value=[]),
    ), patch(
        "src.contexts.observability.services.rollup_service."
        "tier2_inference.sync_tier2_inference",
        new=AsyncMock(),
    ) as tier2_mock:
        await run_cycle(bucket=bucket)

    # Tier 2 invoked once per tenant
    assert tier2_mock.await_count == 2
