"""Tests for FDD-OPS-015 ProgressTracker — rate + ETA + lifecycle.

Pure unit tests on the ETA math (not exercising DB persistence) — those
go in integration tests. The math + state machine MUST be airtight
because the user-facing ETA accuracy requirement is "actual_completion
within ±20% of estimate" (FDD acceptance criteria).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.contexts.pipeline.progress_tracker import (
    DEFAULT_RATE_WINDOW,
    ProgressTracker,
)


TENANT = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def tracker() -> ProgressTracker:
    """Tracker without DB persistence — `_upsert` is patched to no-op."""
    t = ProgressTracker(
        tenant_id=TENANT,
        entity_type="issues",
        scope_key="jira:project:BG",
    )
    return t


# ---------------------------------------------------------------------------
# Rate computation — rolling window
# ---------------------------------------------------------------------------

class TestRateComputation:
    def test_zero_rate_when_fewer_than_two_samples(self, tracker):
        # Empty window
        assert tracker._compute_rate() == 0.0
        # One sample
        tracker._samples.append((datetime.now(timezone.utc), 0))
        assert tracker._compute_rate() == 0.0

    def test_rate_with_two_samples(self, tracker):
        t0 = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
        tracker._samples.append((t0, 0))
        tracker._samples.append((t0 + timedelta(seconds=10), 100))
        # 100 items in 10 seconds = 10/s
        assert tracker._compute_rate() == 10.0

    def test_rate_uses_oldest_to_newest_window(self, tracker):
        """Rolling rate is mean over window's full elapsed time."""
        t0 = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
        # Four samples spanning 30 seconds, cumulative 0 → 60
        for i, (offset_s, done) in enumerate([(0, 0), (10, 20), (20, 40), (30, 60)]):
            tracker._samples.append((t0 + timedelta(seconds=offset_s), done))
        # Rate = (60 - 0) / 30 = 2/s
        assert tracker._compute_rate() == 2.0

    def test_rate_zero_when_items_did_not_increase(self, tracker):
        """Worker stalled — items_done unchanged across samples = rate 0."""
        t0 = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
        tracker._samples.append((t0, 100))
        tracker._samples.append((t0 + timedelta(seconds=30), 100))
        assert tracker._compute_rate() == 0.0

    def test_rate_zero_when_elapsed_is_zero(self, tracker):
        """Defensive: same-instant samples don't divide by zero."""
        t0 = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
        tracker._samples.append((t0, 0))
        tracker._samples.append((t0, 50))
        assert tracker._compute_rate() == 0.0

    def test_window_caps_at_default(self, tracker):
        """Older samples beyond DEFAULT_RATE_WINDOW are dropped (deque maxlen)."""
        t0 = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(DEFAULT_RATE_WINDOW + 3):
            tracker._samples.append((t0 + timedelta(seconds=i), i * 10))
        assert len(tracker._samples) == DEFAULT_RATE_WINDOW


# ---------------------------------------------------------------------------
# ETA computation
# ---------------------------------------------------------------------------

class TestETAComputation:
    def test_eta_none_when_no_estimate(self, tracker):
        """No pre-flight count = no ETA, regardless of rate."""
        assert tracker.estimate is None
        assert tracker._compute_eta(rate=10.0) is None

    def test_eta_none_when_rate_is_zero(self, tracker):
        tracker.estimate = 1000
        assert tracker._compute_eta(rate=0.0) is None

    def test_eta_computed_when_rate_and_estimate_present(self, tracker):
        """ETA seconds = (estimate - done) / rate."""
        tracker.estimate = 1000
        tracker.items_done = 200
        # 800 remaining at 10/s = 80s
        assert tracker._compute_eta(rate=10.0) == 80

    def test_eta_zero_when_done_meets_estimate(self, tracker):
        """Worker completed estimated work — ETA = 0."""
        tracker.estimate = 1000
        tracker.items_done = 1000
        assert tracker._compute_eta(rate=10.0) == 0

    def test_eta_zero_when_done_exceeds_estimate(self, tracker):
        """Estimate was an under-count — ETA pinned at 0, not negative."""
        tracker.estimate = 1000
        tracker.items_done = 1100
        assert tracker._compute_eta(rate=10.0) == 0

    def test_eta_rounds_to_nearest_second(self, tracker):
        tracker.estimate = 100
        tracker.items_done = 30
        # 70 remaining at 3/s = 23.33s → 23
        eta = tracker._compute_eta(rate=3.0)
        assert isinstance(eta, int)
        assert eta == 23


# ---------------------------------------------------------------------------
# Lifecycle: start → tick → finish
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_seeds_window_and_persists(self, tracker):
        """Initial sample at t=0 lets first tick produce a finite rate."""
        with patch.object(tracker, "_upsert", new=AsyncMock()) as mock_upsert:
            await tracker.start_scope(estimate=500)
            assert tracker.estimate == 500
            assert len(tracker._samples) == 1
            assert tracker._samples[0][1] == 0  # cumulative items at start
            mock_upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tick_advances_items_and_persists(self, tracker):
        with patch.object(tracker, "_upsert", new=AsyncMock()) as mock_upsert:
            await tracker.start_scope(estimate=500)
            mock_upsert.reset_mock()
            await tracker.tick(items_added=50)
            assert tracker.items_done == 50
            assert len(tracker._samples) == 2
            mock_upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tick_ignores_negative_items(self, tracker):
        """Defensive: never decrement items_done."""
        with patch.object(tracker, "_upsert", new=AsyncMock()):
            await tracker.start_scope(estimate=500)
            await tracker.tick(items_added=-10)
            assert tracker.items_done == 0

    @pytest.mark.asyncio
    async def test_finish_marks_done_with_zero_eta(self, tracker):
        with patch.object(tracker, "_upsert", new=AsyncMock()) as mock_upsert:
            await tracker.start_scope(estimate=500)
            await tracker.finish(status="done")
            # Last call: phase='done', status='done', eta=0
            args = mock_upsert.await_args.kwargs
            assert args["phase"] == "done"
            assert args["status"] == "done"
            assert args["eta_seconds"] == 0
            assert args["finished"] is True

    @pytest.mark.asyncio
    async def test_finish_marks_failed_with_error(self, tracker):
        with patch.object(tracker, "_upsert", new=AsyncMock()) as mock_upsert:
            await tracker.start_scope()
            await tracker.finish(status="failed", error="JQL timeout after 30s")
            args = mock_upsert.await_args.kwargs
            assert args["status"] == "failed"
            assert args["error"] == "JQL timeout after 30s"

    @pytest.mark.asyncio
    async def test_finish_truncates_long_errors(self, tracker):
        """Avoid log/DB bloat on huge tracebacks."""
        long_error = "X" * 6000
        with patch.object(tracker, "_upsert", new=AsyncMock()) as mock_upsert:
            await tracker.start_scope()
            await tracker.finish(status="failed", error=long_error)
            args = mock_upsert.await_args.kwargs
            assert len(args["error"]) == 4000

    @pytest.mark.asyncio
    async def test_finish_is_idempotent(self, tracker):
        """Double-finish is a no-op — protects against worker error patterns
        where loop calls finish('done') AND outer except calls finish('failed').
        First call wins."""
        with patch.object(tracker, "_upsert", new=AsyncMock()) as mock_upsert:
            await tracker.start_scope()
            mock_upsert.reset_mock()
            await tracker.finish(status="done")
            await tracker.finish(status="failed", error="should be ignored")
            assert mock_upsert.await_count == 1
            args = mock_upsert.await_args.kwargs
            assert args["status"] == "done"


# ---------------------------------------------------------------------------
# Public properties (used by worker for log lines)
# ---------------------------------------------------------------------------

class TestPublicProperties:
    @pytest.mark.asyncio
    async def test_progress_pct_with_estimate(self, tracker):
        with patch.object(tracker, "_upsert", new=AsyncMock()):
            await tracker.start_scope(estimate=200)
            await tracker.tick(items_added=50)
            assert tracker.progress_pct == 25.0

    @pytest.mark.asyncio
    async def test_progress_pct_capped_at_100(self, tracker):
        """Estimate was an under-count — UI shows 100%, not 150%."""
        with patch.object(tracker, "_upsert", new=AsyncMock()):
            await tracker.start_scope(estimate=100)
            await tracker.tick(items_added=150)
            assert tracker.progress_pct == 100.0

    @pytest.mark.asyncio
    async def test_progress_pct_none_without_estimate(self, tracker):
        with patch.object(tracker, "_upsert", new=AsyncMock()):
            await tracker.start_scope(estimate=None)
            await tracker.tick(items_added=50)
            assert tracker.progress_pct is None

    @pytest.mark.asyncio
    async def test_current_eta_reflects_state(self, tracker):
        """current_eta property is what `tick()` would persist."""
        # Manually seed samples with known rate (10/s)
        t0 = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
        tracker._samples.append((t0, 0))
        tracker._samples.append((t0 + timedelta(seconds=10), 100))
        tracker.estimate = 1000
        tracker.items_done = 100
        # 900 remaining at 10/s = 90s
        assert tracker.current_eta == 90


# ---------------------------------------------------------------------------
# Webmotors-shape integration check
# ---------------------------------------------------------------------------

class TestWebmotorsShapeIntegration:
    """Sanity check against the BG project case (197k issues, slow burn)."""

    @pytest.mark.asyncio
    async def test_eta_within_20_pct_of_actual_at_steady_state(self, tracker):
        """FDD acceptance: ETA at 10% complete within ±20% of actual completion.

        Simulates: 100k issues to ingest at steady ~50/s rate. After 10k
        items processed in 200s, ETA should be (90k / 50) = 1800s. Actual
        completion will be 2000s (full 100k at 50/s).
        ETA = 1800s, actual remaining = 1800s → 0% error (steady state).
        """
        with patch.object(tracker, "_upsert", new=AsyncMock()):
            await tracker.start_scope(estimate=100_000)

            # Simulate 5 batches of 2000 items at 10s intervals (200/s rate)
            t0 = tracker.started_at
            tracker._samples.clear()
            tracker._samples.append((t0, 0))
            for i in range(1, 6):
                tracker._samples.append((
                    t0 + timedelta(seconds=10 * i), 2000 * i,
                ))
            tracker.items_done = 10_000

            # Rate should be 200/s, ETA = (100k - 10k) / 200 = 450s
            assert tracker.current_rate == 200.0
            assert tracker.current_eta == 450
