"""FDD-OBS-001 PR 1 — capability_detection unit tests.

Validates ADR-026 Principle 1 + Principle 4 contracts:
  - Always returns ObservabilityCapabilities (never raises).
  - Empty when no provider connected.
  - DB error → ObservabilityCapabilities.empty() (graceful degradation).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.connectors.observability.base import ObservabilityCapabilities
from src.contexts.observability.services import capability_detection

_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session_cm(execute_mock: AsyncMock) -> MagicMock:
    """Build an async-context-manager that yields a session whose
    `execute` method delegates to the supplied mock.

    Mirrors the AsyncMock pattern used by tests in INC-015's
    `test_dora_on_demand.py`.
    """
    session = AsyncMock()
    session.execute = execute_mock
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _row(**kwargs) -> MagicMock:
    """Build a mock row with the given attribute values."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


class TestEmptyState:
    @pytest.mark.asyncio
    async def test_no_provider_returns_empty(self):
        """No row in tenant_observability_credentials → empty."""
        mock_result = MagicMock()
        mock_result.first.return_value = _row(provider_count=0, validated_count=0)
        execute = AsyncMock(return_value=mock_result)

        with patch.object(
            capability_detection, "get_session", return_value=_mock_session_cm(execute),
        ):
            caps = await capability_detection.get_capabilities(_TENANT)

        assert caps == ObservabilityCapabilities.empty()

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        """DB error → caller never sees the exception, gets empty."""
        with patch.object(
            capability_detection, "get_session", side_effect=RuntimeError("db down"),
        ):
            caps = await capability_detection.get_capabilities(_TENANT)

        # Empty state — never raises (ADR-026 Principle 4).
        assert caps == ObservabilityCapabilities.empty()


class TestProviderConnected:
    @pytest.mark.asyncio
    async def test_provider_validated_no_services(self):
        """Provider connected + validated, but no services mapped → has_provider True,
        services_mapped_pct = 0.0."""
        # Three sequential SELECTs: creds, ownership, rollup
        mock_result_creds = MagicMock()
        mock_result_creds.first.return_value = _row(provider_count=1, validated_count=1)

        mock_result_ownership = MagicMock()
        mock_result_ownership.first.return_value = _row(total_services=0, mapped_services=0)

        mock_result_rollup = MagicMock()
        mock_result_rollup.first.return_value = _row(last_calc=None, recent_buckets=0)

        execute = AsyncMock(side_effect=[
            mock_result_creds, mock_result_ownership, mock_result_rollup,
        ])

        with patch.object(
            capability_detection, "get_session", return_value=_mock_session_cm(execute),
        ):
            caps = await capability_detection.get_capabilities(_TENANT)

        assert caps.has_provider is True
        assert caps.has_validated_creds is True
        assert caps.services_mapped_pct == 0.0
        assert caps.has_metric_signal is False
        assert caps.last_rollup_at is None

    @pytest.mark.asyncio
    async def test_partial_ownership_coverage(self):
        """8 of 10 services mapped → 80% coverage."""
        mock_result_creds = MagicMock()
        mock_result_creds.first.return_value = _row(provider_count=1, validated_count=1)

        mock_result_ownership = MagicMock()
        mock_result_ownership.first.return_value = _row(total_services=10, mapped_services=8)

        mock_result_rollup = MagicMock()
        mock_result_rollup.first.return_value = _row(last_calc=None, recent_buckets=0)

        execute = AsyncMock(side_effect=[
            mock_result_creds, mock_result_ownership, mock_result_rollup,
        ])

        with patch.object(
            capability_detection, "get_session", return_value=_mock_session_cm(execute),
        ):
            caps = await capability_detection.get_capabilities(_TENANT)

        assert caps.services_mapped_pct == 0.8

    @pytest.mark.asyncio
    async def test_metric_signal_present(self):
        """When recent_buckets > 0, has_metric_signal must be True."""
        from datetime import datetime, timezone

        mock_result_creds = MagicMock()
        mock_result_creds.first.return_value = _row(provider_count=1, validated_count=1)

        mock_result_ownership = MagicMock()
        mock_result_ownership.first.return_value = _row(total_services=2, mapped_services=2)

        last_calc = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
        mock_result_rollup = MagicMock()
        mock_result_rollup.first.return_value = _row(last_calc=last_calc, recent_buckets=42)

        execute = AsyncMock(side_effect=[
            mock_result_creds, mock_result_ownership, mock_result_rollup,
        ])

        with patch.object(
            capability_detection, "get_session", return_value=_mock_session_cm(execute),
        ):
            caps = await capability_detection.get_capabilities(_TENANT)

        assert caps.has_metric_signal is True
        assert caps.has_deploy_markers is True  # PR 1 stub: same as has_metric_signal
        assert caps.last_rollup_at == last_calc


class TestCapabilitiesShape:
    def test_empty_factory_returns_safe_zero_state(self):
        """ObservabilityCapabilities.empty() is the canonical no-provider state."""
        empty = ObservabilityCapabilities.empty()
        assert empty.has_provider is False
        assert empty.has_validated_creds is False
        assert empty.services_mapped_pct == 0.0
        assert empty.has_deploy_markers is False
        assert empty.has_metric_signal is False
        assert empty.last_rollup_at is None
        assert empty.rate_limit_remaining is None
