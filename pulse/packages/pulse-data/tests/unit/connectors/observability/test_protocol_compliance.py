"""FDD-OBS-001 Phase 1 T1.1 — ObservabilityProvider Protocol surface lock.

Regression guard for the PR 4a.5 drift: `list_monitors_for_service` was
implemented on `DatadogProvider` and called from `rollup_service` via a
Protocol-typed argument, but never declared on the Protocol itself.
A second adapter (NR R3) without that method would have raised
AttributeError at runtime — only a missing line in `base.py` separated
ADR-023 from a sharp edge.

These tests:
  1. Lock the full Protocol method surface so future drift is caught.
  2. Verify `DatadogProvider` satisfies `isinstance(...)` thanks to
     `@runtime_checkable`.
  3. Verify a `MagicMock(spec=ObservabilityProvider)` exposes each
     required method (the conftest fixture relies on this).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.connectors.observability.base import (
    MonitorState,
    ObservabilityProvider,
)
from src.connectors.observability.datadog_connector import DatadogProvider


# The contract — every method `ObservabilityProvider` declares MUST be
# in this set. Adding to the Protocol without updating this list is a
# deliberate signal to update tests + every adapter.
REQUIRED_METHODS: frozenset[str] = frozenset({
    "list_deployments",
    "query_metric",
    "list_services",
    "list_monitors_for_service",  # added in T1.1 (2026-05-11)
    "health_check",
})


class TestProtocolSurface:
    """The Protocol surface itself — assertions about base.py."""

    @pytest.mark.parametrize("method_name", sorted(REQUIRED_METHODS))
    def test_every_required_method_on_protocol(self, method_name: str) -> None:
        """If a method is in REQUIRED_METHODS it must be a Protocol member.

        Catches the inverse of the PR 4a.5 leak: future engineer removes
        a method from the Protocol without realizing rollup_service
        depends on it.
        """
        # MagicMock(spec=...) exposes exactly the spec's members + nothing else
        spec_mock = MagicMock(spec=ObservabilityProvider)
        assert hasattr(spec_mock, method_name), (
            f"ObservabilityProvider Protocol missing method {method_name!r}. "
            f"Either restore it to base.py or remove from REQUIRED_METHODS "
            f"(and remove every adapter's implementation)."
        )

    def test_protocol_has_provider_id_attribute(self) -> None:
        """ADR-023 also requires `provider_id: str` as a class-level attr.

        Note: `MagicMock(spec=Protocol)` does NOT expose annotation-only
        class attributes; we check directly on the Protocol class.
        """
        # __annotations__ carries `provider_id: str` from the Protocol def.
        assert "provider_id" in getattr(
            ObservabilityProvider, "__annotations__", {}
        )


class TestDatadogProviderIsProtocolCompliant:
    """The R2 adapter — must satisfy isinstance() at runtime since the
    Protocol is `@runtime_checkable`."""

    def test_datadog_provider_is_observability_provider(self) -> None:
        """`DatadogProvider` must pass `isinstance(x, ObservabilityProvider)`.

        Validates that the @runtime_checkable Protocol actually catches
        a missing method on the concrete adapter at runtime (not just
        at type-check time).
        """
        provider = DatadogProvider(api_key="test", site="datadoghq.com")
        try:
            assert isinstance(provider, ObservabilityProvider)
        finally:
            # Best-effort cleanup — the constructor opens an httpx client.
            # Sync test body, so close synchronously via the internal handle.
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(provider.aclose())
            finally:
                loop.close()

    @pytest.mark.parametrize("method_name", sorted(REQUIRED_METHODS))
    def test_datadog_provider_implements_every_method(
        self, method_name: str,
    ) -> None:
        """Each Protocol method must be a real callable on the adapter."""
        provider = DatadogProvider(api_key="test", site="datadoghq.com")
        try:
            method = getattr(provider, method_name, None)
            assert method is not None, (
                f"DatadogProvider missing {method_name!r} — "
                f"violates ObservabilityProvider Protocol (ADR-023)"
            )
            assert callable(method), (
                f"DatadogProvider.{method_name} is not callable"
            )
        finally:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(provider.aclose())
            finally:
                loop.close()


class TestMonitorStateExportedFromBase:
    """`MonitorState` is re-exported from base.py so adapters and tests
    have one canonical import path."""

    def test_monitor_state_importable_from_base(self) -> None:
        # Direct import works
        from src.connectors.observability.base import MonitorState as MS

        assert MS is MonitorState

    def test_monitor_state_fields(self) -> None:
        """The dataclass shape that the Protocol contract returns."""
        ms = MonitorState(
            monitor_id=1,
            name="checkout error rate",
            service="checkout",
            severity=2.0,
            state="Alert",
        )
        assert ms.monitor_id == 1
        assert ms.severity == 2.0
        assert ms.vendor_raw == {}
