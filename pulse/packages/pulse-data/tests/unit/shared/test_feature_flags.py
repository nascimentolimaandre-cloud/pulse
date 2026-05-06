"""FDD-OBS-001 PR 0 — unit tests for src.shared.feature_flags.

Validates the contract:
  - Default behaviour is fail-closed (False) when row absent / Redis
    unavailable / DB error.
  - Cache hit returns cached value without DB hit.
  - Cache miss reads DB, then writes cache.
  - set_flag invalidates cache.
  - Empty flag_key returns False (defensive).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.shared import feature_flags


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Fail-closed defaults
# ---------------------------------------------------------------------------


class TestFailClosedDefaults:
    @pytest.mark.asyncio
    async def test_empty_flag_key_returns_false(self):
        """Defensive: empty/None flag_key never queries DB or cache."""
        with patch.object(feature_flags, "_read_cache", new=AsyncMock()) as cache_mock, \
             patch.object(feature_flags, "_read_db", new=AsyncMock()) as db_mock:
            assert await feature_flags.is_enabled(_TENANT, "") is False
            cache_mock.assert_not_awaited()
            db_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_db_error_returns_false_not_raise(self):
        """Fail-closed: DB exception → False, NOT bubbling."""
        with patch.object(feature_flags, "_read_cache", new=AsyncMock(return_value=None)), \
             patch.object(feature_flags, "_read_db", new=AsyncMock(side_effect=RuntimeError("db down"))):
            result = await feature_flags.is_enabled(_TENANT, "obs.signals.enabled")
            assert result is False

    @pytest.mark.asyncio
    async def test_row_absent_returns_false(self):
        """No row in DB for this (tenant, flag) → False (per ADR-026 graceful degradation)."""
        with patch.object(feature_flags, "_read_cache", new=AsyncMock(return_value=None)), \
             patch.object(feature_flags, "_read_db", new=AsyncMock(return_value=False)) as db_mock, \
             patch.object(feature_flags, "_write_cache", new=AsyncMock()):
            result = await feature_flags.is_enabled(_TENANT, "obs.signals.enabled")
            assert result is False
            db_mock.assert_awaited_once_with(_TENANT, "obs.signals.enabled")


# ---------------------------------------------------------------------------
# Happy path + cache behaviour
# ---------------------------------------------------------------------------


class TestCacheBehaviour:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self):
        """Cache returns True → DB never read."""
        with patch.object(feature_flags, "_read_cache", new=AsyncMock(return_value=True)), \
             patch.object(feature_flags, "_read_db", new=AsyncMock()) as db_mock, \
             patch.object(feature_flags, "_write_cache", new=AsyncMock()) as write_mock:
            result = await feature_flags.is_enabled(_TENANT, "obs.signals.enabled")
            assert result is True
            db_mock.assert_not_awaited()
            write_mock.assert_not_awaited()  # no need to re-cache a hit

    @pytest.mark.asyncio
    async def test_cache_miss_reads_db_and_writes_cache(self):
        with patch.object(feature_flags, "_read_cache", new=AsyncMock(return_value=None)), \
             patch.object(feature_flags, "_read_db", new=AsyncMock(return_value=True)), \
             patch.object(feature_flags, "_write_cache", new=AsyncMock()) as write_mock:
            result = await feature_flags.is_enabled(_TENANT, "obs.signals.enabled")
            assert result is True
            write_mock.assert_awaited_once_with(_TENANT, "obs.signals.enabled", True)

    @pytest.mark.asyncio
    async def test_cache_unavailable_falls_through_to_db(self):
        """Redis down → cache returns None → still goes to DB."""
        with patch.object(feature_flags, "_read_cache", new=AsyncMock(return_value=None)), \
             patch.object(feature_flags, "_read_db", new=AsyncMock(return_value=False)) as db_mock, \
             patch.object(feature_flags, "_write_cache", new=AsyncMock()):
            result = await feature_flags.is_enabled(_TENANT, "any_flag")
            assert result is False
            db_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# set_flag → invalidate cache
# ---------------------------------------------------------------------------


class TestSetFlag:
    @pytest.mark.asyncio
    async def test_empty_key_raises(self):
        with pytest.raises(ValueError):
            await feature_flags.set_flag(_TENANT, "", True)

    @pytest.mark.asyncio
    async def test_invalidates_cache_after_write(self):
        """After UPSERT, cache key must be deleted so next read sees fresh value."""
        with patch.object(feature_flags, "get_session") as session_cm, \
             patch.object(feature_flags, "_invalidate_cache", new=AsyncMock()) as inv_mock:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            session_cm.return_value = mock_session

            await feature_flags.set_flag(_TENANT, "obs.signals.enabled", True)
            inv_mock.assert_awaited_once_with(_TENANT, "obs.signals.enabled")
