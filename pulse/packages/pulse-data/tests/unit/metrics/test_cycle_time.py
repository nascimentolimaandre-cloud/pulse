"""Unit tests for Cycle Time metric calculations.

Tests pure domain functions in:
    src/contexts/metrics/domain/cycle_time.py

Coverage targets:
- breakdown_single_pr: all phases present, missing timestamps, negative deltas
- calculate_cycle_time_breakdown: aggregates, bottleneck identification, empty input
- calculate_cycle_time_trend: weekly bucketing, zero weeks, date filtering
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.contexts.metrics.domain.cycle_time import (
    PullRequestCycleData,
    breakdown_single_pr,
    calculate_cycle_time_breakdown,
    calculate_cycle_time_trend,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _d(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def _pr(
    pr_id: str = "PR-1",
    first_commit: datetime | None = None,
    first_review: datetime | None = None,
    approved: datetime | None = None,
    merged: datetime | None = None,
    deployed: datetime | None = None,
) -> PullRequestCycleData:
    return PullRequestCycleData(
        pr_id=pr_id,
        first_commit_at=first_commit,
        first_review_at=first_review,
        approved_at=approved,
        merged_at=merged,
        deployed_at=deployed,
    )


# ---------------------------------------------------------------------------
# breakdown_single_pr
# ---------------------------------------------------------------------------


class TestBreakdownSinglePr:
    def test_all_phases_present_correct_hours(self) -> None:
        pr = _pr(
            first_commit=_dt(2024, 1, 2, 9),
            first_review=_dt(2024, 1, 2, 17),   # 8h coding
            approved=_dt(2024, 1, 3, 9),          # 16h pickup
            merged=_dt(2024, 1, 3, 11),           # 2h review
            deployed=_dt(2024, 1, 3, 13),         # 2h deploy
        )
        b = breakdown_single_pr(pr)
        assert b.coding_hours == 8.0
        assert b.pickup_hours == 16.0
        assert b.review_hours == 2.0
        assert b.deploy_hours == 2.0
        assert b.total_hours == 28.0  # first_commit to deployed

    def test_missing_first_review_coding_is_none(self) -> None:
        pr = _pr(first_commit=_dt(2024, 1, 2, 9), first_review=None, merged=_dt(2024, 1, 3, 9))
        b = breakdown_single_pr(pr)
        assert b.coding_hours is None
        assert b.pickup_hours is None
        assert b.review_hours is None

    def test_missing_deployed_at_total_uses_merged_at(self) -> None:
        pr = _pr(
            first_commit=_dt(2024, 1, 5, 8),
            merged=_dt(2024, 1, 7, 8),  # 48h from commit to merge
            deployed=None,
        )
        b = breakdown_single_pr(pr)
        assert b.total_hours == 48.0

    def test_all_timestamps_none_all_phases_none(self) -> None:
        pr = _pr()
        b = breakdown_single_pr(pr)
        assert b.coding_hours is None
        assert b.pickup_hours is None
        assert b.review_hours is None
        assert b.deploy_hours is None
        assert b.total_hours is None

    def test_deploy_phase_is_merged_to_deployed(self) -> None:
        pr = _pr(
            first_commit=_dt(2024, 1, 10, 9),
            merged=_dt(2024, 1, 10, 17),    # 8h after commit
            deployed=_dt(2024, 1, 11, 9),   # 16h after merge
        )
        b = breakdown_single_pr(pr)
        assert b.deploy_hours == 16.0

    def test_negative_delta_returns_none_for_that_phase(self) -> None:
        """When endpoint < start (bad data), phase should be None."""
        pr = _pr(
            first_commit=_dt(2024, 1, 5, 12),
            first_review=_dt(2024, 1, 5, 8),  # before first_commit
        )
        b = breakdown_single_pr(pr)
        assert b.coding_hours is None

    def test_pr_id_preserved_in_breakdown(self) -> None:
        pr = _pr(pr_id="my-pr-42")
        b = breakdown_single_pr(pr)
        assert b.pr_id == "my-pr-42"

    def test_zero_duration_phase_is_valid(self) -> None:
        """Same timestamp for start and end = 0h, which is valid."""
        t = _dt(2024, 1, 10, 12)
        pr = _pr(first_commit=t, first_review=t)
        b = breakdown_single_pr(pr)
        assert b.coding_hours == 0.0


# ---------------------------------------------------------------------------
# calculate_cycle_time_breakdown
# ---------------------------------------------------------------------------


class TestCalculateCycleTimeBreakdown:
    def test_empty_list_returns_all_none_with_zero_count(self) -> None:
        result = calculate_cycle_time_breakdown([])
        assert result.coding_p50 is None
        assert result.pickup_p50 is None
        assert result.review_p50 is None
        assert result.deploy_p50 is None
        assert result.total_p50 is None
        assert result.bottleneck_phase is None
        assert result.pr_count == 0

    def test_pr_count_equals_input_length(self) -> None:
        prs = [
            _pr("PR-1", first_commit=_dt(2024, 1, 1, 9), merged=_dt(2024, 1, 2, 9)),
            _pr("PR-2", first_commit=_dt(2024, 1, 3, 9), merged=_dt(2024, 1, 4, 9)),
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.pr_count == 2

    def test_single_pr_all_percentiles_equal_its_value(self) -> None:
        pr = _pr(
            first_commit=_dt(2024, 1, 2, 8),
            first_review=_dt(2024, 1, 2, 16),  # 8h coding
            approved=_dt(2024, 1, 3, 8),        # 16h pickup
            merged=_dt(2024, 1, 3, 10),         # 2h review
            deployed=_dt(2024, 1, 3, 12),       # 2h deploy
        )
        result = calculate_cycle_time_breakdown([pr])
        assert result.coding_p50 == 8.0
        assert result.coding_p85 == 8.0
        assert result.coding_p95 == 8.0

    def test_aggregate_p50_from_multiple_prs(self) -> None:
        """3 PRs with coding times 8h, 24h, 16h → median 16h."""
        prs = [
            _pr("PR-1", first_commit=_dt(2024, 1, 1, 8), first_review=_dt(2024, 1, 1, 16)),   # 8h
            _pr("PR-2", first_commit=_dt(2024, 1, 2, 8), first_review=_dt(2024, 1, 3, 8)),     # 24h
            _pr("PR-3", first_commit=_dt(2024, 1, 3, 8), first_review=_dt(2024, 1, 4, 0)),     # 16h
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.coding_p50 == 16.0

    def test_bottleneck_is_phase_with_highest_p50(self) -> None:
        """Pickup (40h) is clearly the bottleneck vs coding (8h) and review (2h)."""
        pr = _pr(
            first_commit=_dt(2024, 1, 2, 8),
            first_review=_dt(2024, 1, 2, 16),  # 8h coding
            approved=_dt(2024, 1, 4, 8),        # 40h pickup
            merged=_dt(2024, 1, 4, 10),         # 2h review
            deployed=_dt(2024, 1, 4, 12),       # 2h deploy
        )
        result = calculate_cycle_time_breakdown([pr])
        assert result.bottleneck_phase == "pickup"

    def test_prs_with_missing_phase_timestamps_excluded_from_that_phase(self) -> None:
        """PR without first_review_at: excluded from coding P50 but contributes total."""
        prs = [
            _pr("PR-1", first_commit=_dt(2024, 1, 1, 9), first_review=None, merged=_dt(2024, 1, 2, 9)),
            _pr("PR-2", first_commit=_dt(2024, 1, 3, 9), first_review=_dt(2024, 1, 4, 9), merged=_dt(2024, 1, 5, 9)),
        ]
        result = calculate_cycle_time_breakdown(prs)
        # Only PR-2 has coding phase
        assert result.coding_p50 == 24.0
        assert result.pr_count == 2

    def test_p95_is_at_least_as_large_as_p85_for_all_phases(self) -> None:
        prs = [
            _pr(f"PR-{i}", first_commit=_dt(2024, 1, i + 1, 9), first_review=_dt(2024, 1, i + 1, 9 + i))
            for i in range(1, 11)
        ]
        result = calculate_cycle_time_breakdown(prs)
        if result.coding_p50 is not None:
            assert result.coding_p95 >= result.coding_p85 >= result.coding_p50  # type: ignore[operator]

    def test_total_hours_uses_deployed_at_when_available(self) -> None:
        pr = _pr(
            first_commit=_dt(2024, 1, 1, 8),
            merged=_dt(2024, 1, 2, 8),     # 24h if used as fallback
            deployed=_dt(2024, 1, 1, 16),  # 8h if used as endpoint
        )
        result = calculate_cycle_time_breakdown([pr])
        assert result.total_p50 == 8.0


# ---------------------------------------------------------------------------
# calculate_cycle_time_trend
# ---------------------------------------------------------------------------


class TestCalculateCycleTimeTrend:
    def test_start_after_end_returns_empty(self) -> None:
        result = calculate_cycle_time_trend([], _d(2024, 1, 7), _d(2024, 1, 1))
        assert result == []

    def test_returns_one_point_per_iso_week_in_range(self) -> None:
        # 4-week range: Jan 1 – Jan 28 → weeks Jan 1, 8, 15, 22
        result = calculate_cycle_time_trend([], _d(2024, 1, 1), _d(2024, 1, 28))
        assert len(result) == 4

    def test_prs_bucketed_by_merged_at_week(self) -> None:
        """PR merged on Jan 10 (week of Jan 8) counts in that bucket."""
        pr = _pr(
            "PR-1",
            first_commit=_dt(2024, 1, 9, 8),
            merged=_dt(2024, 1, 10, 8),
        )
        result = calculate_cycle_time_trend([pr], _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].week_start == _d(2024, 1, 8)
        assert result[0].pr_count == 1

    def test_prs_without_merged_at_excluded(self) -> None:
        pr = _pr("PR-1", first_commit=_dt(2024, 1, 8, 9), merged=None)
        result = calculate_cycle_time_trend([pr], _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].pr_count == 0

    def test_weeks_without_prs_have_none_percentiles_and_zero_count(self) -> None:
        result = calculate_cycle_time_trend([], _d(2024, 1, 1), _d(2024, 1, 28))
        for point in result:
            assert point.pr_count == 0
            assert point.p50_hours is None
            assert point.p85_hours is None
            assert point.p95_hours is None

    def test_prs_outside_range_excluded(self) -> None:
        before = _pr("PR-1", first_commit=_dt(2023, 12, 28, 9), merged=_dt(2023, 12, 29, 9))
        after = _pr("PR-2", first_commit=_dt(2024, 2, 1, 9), merged=_dt(2024, 2, 2, 9))
        result = calculate_cycle_time_trend([before, after], _d(2024, 1, 1), _d(2024, 1, 28))
        assert all(p.pr_count == 0 for p in result)

    def test_percentiles_computed_per_week(self) -> None:
        """Two PRs in same week with total 8h and 24h → P50 = 16h."""
        prs = [
            _pr("PR-1", first_commit=_dt(2024, 1, 8, 8), merged=_dt(2024, 1, 8, 16)),   # 8h
            _pr("PR-2", first_commit=_dt(2024, 1, 9, 8), merged=_dt(2024, 1, 10, 8)),   # 24h
        ]
        result = calculate_cycle_time_trend(prs, _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].pr_count == 2
        assert result[0].p50_hours == 16.0

    def test_result_ordered_ascending_by_week(self) -> None:
        prs = [
            _pr("PR-1", first_commit=_dt(2024, 1, 15, 9), merged=_dt(2024, 1, 16, 9)),
            _pr("PR-2", first_commit=_dt(2024, 1, 8, 9), merged=_dt(2024, 1, 9, 9)),
        ]
        result = calculate_cycle_time_trend(prs, _d(2024, 1, 8), _d(2024, 1, 21))
        weeks = [p.week_start for p in result]
        assert weeks == sorted(weeks)
