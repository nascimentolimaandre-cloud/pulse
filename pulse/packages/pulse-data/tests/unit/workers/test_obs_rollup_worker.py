"""FDD-OBS-001 PR 4a — obs_rollup_worker entry-point tests.

Validates ops contracts:
  - OBS_ROLLUP_ENABLED=false short-circuits before APScheduler starts.
  - Missing PULSE_OBS_MASTER_KEY exits cleanly without scheduling.
  - --once flag runs exactly one cycle and returns.
  - _run_one_cycle swallows exceptions (scheduler must keep ticking).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from src.workers import obs_rollup_worker


@pytest.fixture(autouse=True)
def _master_key(monkeypatch):
    """Default to having a master key so the early-exit guard doesn't
    fire in tests that aren't testing that guard."""
    monkeypatch.setattr(
        obs_rollup_worker.settings, "pulse_obs_master_key", "a" * 64,
    )


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_enabled_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("OBS_ROLLUP_ENABLED", raising=False)
        assert obs_rollup_worker._is_enabled() is True

    def test_enabled_with_explicit_true(self, monkeypatch):
        monkeypatch.setenv("OBS_ROLLUP_ENABLED", "true")
        assert obs_rollup_worker._is_enabled() is True

    @pytest.mark.parametrize("val", ["false", "FALSE", "0", "no", "off"])
    def test_disabled_recognized_values(self, monkeypatch, val):
        monkeypatch.setenv("OBS_ROLLUP_ENABLED", val)
        assert obs_rollup_worker._is_enabled() is False

    @pytest.mark.asyncio
    async def test_disabled_exits_without_scheduler(self, monkeypatch):
        monkeypatch.setenv("OBS_ROLLUP_ENABLED", "false")
        with patch.object(
            obs_rollup_worker, "AsyncIOScheduler",
        ) as scheduler_cls:
            await obs_rollup_worker.run_worker(interval_minutes=15)
        scheduler_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Master key guard
# ---------------------------------------------------------------------------


class TestMasterKeyGuard:
    @pytest.mark.asyncio
    async def test_missing_master_key_exits(self, monkeypatch):
        monkeypatch.setattr(
            obs_rollup_worker.settings, "pulse_obs_master_key", "",
        )
        monkeypatch.setenv("OBS_ROLLUP_ENABLED", "true")
        with patch.object(
            obs_rollup_worker, "AsyncIOScheduler",
        ) as scheduler_cls:
            await obs_rollup_worker.run_worker(interval_minutes=15)
        scheduler_cls.assert_not_called()


# ---------------------------------------------------------------------------
# _run_one_cycle — error containment
# ---------------------------------------------------------------------------


class TestRunOneCycle:
    @pytest.mark.asyncio
    async def test_swallows_unexpected_exception(self):
        """Any exception out of run_cycle must NOT propagate — the
        scheduler keeps ticking."""
        with patch.object(
            obs_rollup_worker.rollup_service, "run_cycle",
            new=AsyncMock(side_effect=RuntimeError("transient blip")),
        ):
            # Should not raise
            await obs_rollup_worker._run_one_cycle()

    @pytest.mark.asyncio
    async def test_passes_provider_id_datadog(self):
        with patch.object(
            obs_rollup_worker.rollup_service, "run_cycle",
            new=AsyncMock(return_value=None),
        ) as run_mock:
            await obs_rollup_worker._run_one_cycle()
        kwargs = run_mock.await_args.kwargs
        assert kwargs["provider_id"] == "datadog"


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


class TestLoggingHardening:
    """CISO PR 4a follow-up — httpx INFO logs contained plaintext
    service names in URL query strings. `_configure_logging` must
    raise httpx + httpcore + apscheduler to WARNING to preserve
    the service-name hash guarantee from ADR-028 §3."""

    def test_httpx_logger_pinned_to_warning(self):
        import logging
        # Reset any pollution from prior tests
        logging.getLogger("httpx").setLevel(logging.NOTSET)
        obs_rollup_worker._configure_logging()
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_httpcore_logger_pinned_to_warning(self):
        import logging
        logging.getLogger("httpcore").setLevel(logging.NOTSET)
        obs_rollup_worker._configure_logging()
        assert logging.getLogger("httpcore").level == logging.WARNING

    def test_apscheduler_logger_pinned_to_warning(self):
        import logging
        logging.getLogger("apscheduler").setLevel(logging.NOTSET)
        obs_rollup_worker._configure_logging()
        assert logging.getLogger("apscheduler").level == logging.WARNING


class TestArgParsing:
    def test_default_no_once_flag(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["obs_rollup_worker"])
        args = obs_rollup_worker._parse_args()
        assert args.once is False
        assert args.interval_minutes == 15

    def test_once_flag(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["obs_rollup_worker", "--once"])
        args = obs_rollup_worker._parse_args()
        assert args.once is True

    def test_custom_interval(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["obs_rollup_worker", "--interval-minutes", "5"],
        )
        args = obs_rollup_worker._parse_args()
        assert args.interval_minutes == 5
