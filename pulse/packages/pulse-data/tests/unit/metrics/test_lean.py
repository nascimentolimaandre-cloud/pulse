"""Unit tests for Lean metric calculations.

Tests pure domain functions in:
    src/contexts/metrics/domain/lean.py

Coverage targets:
- calculate_cfd: daily status counting, transition replay, fallback for no transitions
- calculate_wip: current-status mode, as_of historical mode
- calculate_lead_time_distribution: histogram buckets, P50/P85/P95, empty data
- calculate_throughput: weekly counts, moving average, zero-filled weeks
- calculate_lead_time_scatterplot: scatter points, outlier detection
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.contexts.metrics.domain.lean import (
    IssueFlowData,
    calculate_cfd,
    calculate_lead_time_distribution,
    calculate_lead_time_scatterplot,
    calculate_throughput,
    calculate_wip,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _dt_naive(year: int, month: int, day: int, hour: int = 0) -> datetime:
    """Timezone-naive datetime — required for calculate_cfd which builds naive EOD comparisons."""
    return datetime(year, month, day, hour)


def _d(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def _issue(
    issue_id: str = "ISS-1",
    normalized_status: str = "todo",
    transitions: list | None = None,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    lead_time_hours: float | None = None,
) -> IssueFlowData:
    return IssueFlowData(
        issue_id=issue_id,
        normalized_status=normalized_status,
        status_transitions=transitions or [],
        created_at=created_at or _dt(2024, 1, 1),
        started_at=started_at,
        completed_at=completed_at,
        lead_time_hours=lead_time_hours,
    )


# ---------------------------------------------------------------------------
# calculate_cfd
# ---------------------------------------------------------------------------


class TestCalculateCfd:
    """CFD tests use timezone-naive datetimes because calculate_cfd builds naive EOD timestamps."""

    def test_empty_issues_returns_empty_list(self) -> None:
        result = calculate_cfd([], _d(2024, 1, 1), _d(2024, 1, 7))
        assert result == []

    def test_start_after_end_returns_empty_list(self) -> None:
        issue = _issue(normalized_status="todo", created_at=_dt_naive(2024, 1, 1))
        result = calculate_cfd([issue], _d(2024, 1, 7), _d(2024, 1, 1))
        assert result == []

    def test_single_day_range_produces_one_data_point(self) -> None:
        issue = _issue(
            normalized_status="todo",
            transitions=[{"status": "todo", "entered_at": _dt_naive(2024, 1, 5), "exited_at": None}],
            created_at=_dt_naive(2024, 1, 5),
        )
        result = calculate_cfd([issue], _d(2024, 1, 5), _d(2024, 1, 5))
        assert len(result) == 1
        assert result[0].date == _d(2024, 1, 5)

    def test_returns_one_point_per_calendar_day(self) -> None:
        issue = _issue(created_at=_dt_naive(2024, 1, 1))
        result = calculate_cfd([issue], _d(2024, 1, 1), _d(2024, 1, 7))
        assert len(result) == 7
        assert result[0].date == _d(2024, 1, 1)
        assert result[-1].date == _d(2024, 1, 7)

    def test_issue_created_after_range_is_not_counted(self) -> None:
        issue = _issue(
            normalized_status="todo",
            transitions=[{"status": "todo", "entered_at": _dt_naive(2024, 1, 15), "exited_at": None}],
            created_at=_dt_naive(2024, 1, 15),
        )
        result = calculate_cfd([issue], _d(2024, 1, 1), _d(2024, 1, 7))
        for point in result:
            assert point.todo == 0
            assert point.in_progress == 0
            assert point.done == 0

    def test_transition_replay_reflects_status_at_each_day(self) -> None:
        """Issue transitions: todo Jan1 → in_progress Jan3 → done Jan5."""
        issue = _issue(
            issue_id="ISS-1",
            normalized_status="done",
            transitions=[
                {"status": "todo", "entered_at": _dt_naive(2024, 1, 1), "exited_at": _dt_naive(2024, 1, 3)},
                {"status": "in_progress", "entered_at": _dt_naive(2024, 1, 3), "exited_at": _dt_naive(2024, 1, 5)},
                {"status": "done", "entered_at": _dt_naive(2024, 1, 5), "exited_at": None},
            ],
            created_at=_dt_naive(2024, 1, 1),
            completed_at=_dt_naive(2024, 1, 5),
        )
        result = calculate_cfd([issue], _d(2024, 1, 1), _d(2024, 1, 7))

        day_map = {p.date: p for p in result}
        assert day_map[_d(2024, 1, 1)].todo == 1
        assert day_map[_d(2024, 1, 2)].todo == 1
        assert day_map[_d(2024, 1, 3)].in_progress == 1
        assert day_map[_d(2024, 1, 5)].done == 1
        assert day_map[_d(2024, 1, 7)].done == 1  # cumulative: stays done

    def test_issue_without_transitions_defaults_to_todo(self) -> None:
        issue = _issue(normalized_status="in_progress", transitions=[], created_at=_dt_naive(2024, 1, 2))
        result = calculate_cfd([issue], _d(2024, 1, 1), _d(2024, 1, 5))
        # Before created_at: not counted; after created_at: fallback to "todo" transition
        day_jan2 = next(p for p in result if p.date == _d(2024, 1, 2))
        assert day_jan2.todo == 1

    def test_cfd_counts_across_multiple_issues(self) -> None:
        issues = [
            _issue("ISS-1", "todo", [{"status": "todo", "entered_at": _dt_naive(2024, 1, 1), "exited_at": None}], created_at=_dt_naive(2024, 1, 1)),
            _issue("ISS-2", "in_progress", [{"status": "in_progress", "entered_at": _dt_naive(2024, 1, 1), "exited_at": None}], created_at=_dt_naive(2024, 1, 1)),
            _issue("ISS-3", "done", [{"status": "done", "entered_at": _dt_naive(2024, 1, 1), "exited_at": None}], created_at=_dt_naive(2024, 1, 1)),
        ]
        result = calculate_cfd(issues, _d(2024, 1, 1), _d(2024, 1, 1))
        assert len(result) == 1
        point = result[0]
        assert point.todo == 1
        assert point.in_progress == 1
        assert point.done == 1


# ---------------------------------------------------------------------------
# calculate_wip
# ---------------------------------------------------------------------------


class TestCalculateWip:
    def test_empty_issues_returns_zero(self) -> None:
        assert calculate_wip([]) == 0

    def test_counts_in_progress_and_in_review_as_active(self) -> None:
        issues = [
            _issue("A", "in_progress"),
            _issue("B", "in_review"),
            _issue("C", "todo"),
            _issue("D", "done"),
            _issue("E", "backlog"),
        ]
        assert calculate_wip(issues) == 2

    def test_only_in_progress_counts(self) -> None:
        issues = [_issue("A", "in_progress"), _issue("B", "todo")]
        assert calculate_wip(issues) == 1

    def test_only_in_review_counts(self) -> None:
        issues = [_issue("A", "in_review"), _issue("B", "done")]
        assert calculate_wip(issues) == 1

    def test_all_done_wip_is_zero(self) -> None:
        issues = [_issue(f"ISS-{i}", "done") for i in range(5)]
        assert calculate_wip(issues) == 0

    def test_as_of_uses_transition_history(self) -> None:
        """At Jan 5 morning, issue was in_progress; by Jan 10 it's done."""
        issue = _issue(
            "ISS-1",
            "done",
            transitions=[
                {"status": "todo", "entered_at": _dt(2024, 1, 1), "exited_at": _dt(2024, 1, 3)},
                {"status": "in_progress", "entered_at": _dt(2024, 1, 3), "exited_at": _dt(2024, 1, 8)},
                {"status": "done", "entered_at": _dt(2024, 1, 8), "exited_at": None},
            ],
            created_at=_dt(2024, 1, 1),
        )
        assert calculate_wip([issue], as_of=_dt(2024, 1, 5)) == 1
        assert calculate_wip([issue], as_of=_dt(2024, 1, 9)) == 0

    def test_as_of_before_issue_created_returns_zero(self) -> None:
        issue = _issue("ISS-1", "in_progress", created_at=_dt(2024, 1, 10))
        assert calculate_wip([issue], as_of=_dt(2024, 1, 5)) == 0

    def test_as_of_none_uses_current_normalized_status(self) -> None:
        issues = [
            _issue("A", "in_progress"),
            _issue("B", "in_review"),
        ]
        assert calculate_wip(issues, as_of=None) == 2


# ---------------------------------------------------------------------------
# calculate_lead_time_distribution
# ---------------------------------------------------------------------------


class TestLeadTimeDistribution:
    def test_empty_issues_returns_zero_counts_and_none_percentiles(self) -> None:
        result = calculate_lead_time_distribution([])
        assert result.total_issues == 0
        assert result.p50_hours is None
        assert result.p85_hours is None
        assert result.p95_hours is None
        assert all(b.count == 0 for b in result.buckets)

    def test_issues_without_completed_at_are_excluded(self) -> None:
        issue = _issue("ISS-1", "in_progress", lead_time_hours=10.0, completed_at=None)
        result = calculate_lead_time_distribution([issue])
        assert result.total_issues == 0

    def test_issues_without_lead_time_hours_are_excluded(self) -> None:
        issue = _issue("ISS-1", "done", lead_time_hours=None, completed_at=_dt(2024, 1, 10))
        result = calculate_lead_time_distribution([issue])
        assert result.total_issues == 0

    def test_single_issue_in_correct_bucket(self) -> None:
        """3-hour lead time should land in the '0-4h' bucket."""
        issue = _issue("ISS-1", "done", lead_time_hours=3.0, completed_at=_dt(2024, 1, 10))
        result = calculate_lead_time_distribution([issue])
        assert result.total_issues == 1
        first_bucket = result.buckets[0]
        assert first_bucket.range_label == "0-4h"
        assert first_bucket.count == 1
        assert first_bucket.percentage == 100.0

    def test_percentiles_correct_for_known_distribution(self) -> None:
        """5 issues at 2, 6, 20, 36, 100 hours — known P50=20h."""
        lead_times = [2.0, 6.0, 20.0, 36.0, 100.0]
        issues = [
            _issue(f"ISS-{i}", "done", lead_time_hours=lt, completed_at=_dt(2024, 1, i + 1))
            for i, lt in enumerate(lead_times)
        ]
        result = calculate_lead_time_distribution(issues)
        assert result.total_issues == 5
        assert result.p50_hours == 20.0  # median of sorted [2,6,20,36,100]

    def test_all_bucket_percentages_sum_to_100(self) -> None:
        lead_times = [3.0, 5.0, 12.0, 30.0, 60.0, 130.0, 300.0, 600.0, 800.0]
        issues = [
            _issue(f"ISS-{i}", "done", lead_time_hours=lt, completed_at=_dt(2024, 1, i + 1))
            for i, lt in enumerate(lead_times)
        ]
        result = calculate_lead_time_distribution(issues)
        total_pct = sum(b.percentage for b in result.buckets)
        assert abs(total_pct - 100.0) < 0.5  # rounding tolerance

    def test_30d_plus_bucket_captures_long_issues(self) -> None:
        issue = _issue("ISS-1", "done", lead_time_hours=750.0, completed_at=_dt(2024, 1, 31))
        result = calculate_lead_time_distribution([issue])
        last_bucket = result.buckets[-1]
        assert last_bucket.range_label == "30d+"
        assert last_bucket.count == 1

    def test_single_issue_all_percentiles_equal_its_value(self) -> None:
        issue = _issue("ISS-1", "done", lead_time_hours=48.0, completed_at=_dt(2024, 1, 10))
        result = calculate_lead_time_distribution([issue])
        assert result.p50_hours == 48.0
        assert result.p85_hours == 48.0
        assert result.p95_hours == 48.0

    def test_p95_is_at_least_as_large_as_p85_and_p50(self) -> None:
        lead_times = [float(x) for x in range(1, 21)]  # 1..20 hours
        issues = [
            _issue(f"ISS-{i}", "done", lead_time_hours=lt, completed_at=_dt(2024, 1, i + 1))
            for i, lt in enumerate(lead_times)
        ]
        result = calculate_lead_time_distribution(issues)
        assert result.p95_hours >= result.p85_hours >= result.p50_hours  # type: ignore[operator]


# ---------------------------------------------------------------------------
# calculate_throughput
# ---------------------------------------------------------------------------


class TestCalculateThroughput:
    def test_start_after_end_returns_empty_list(self) -> None:
        result = calculate_throughput([], _d(2024, 1, 7), _d(2024, 1, 1))
        assert result == []

    def test_no_completed_issues_all_counts_zero(self) -> None:
        issues = [_issue("ISS-1", "in_progress", completed_at=None)]
        result = calculate_throughput(issues, _d(2024, 1, 1), _d(2024, 1, 28))
        assert all(p.count == 0 for p in result)

    def test_completed_issues_counted_in_correct_week(self) -> None:
        """Issue completed Jan 10 (Wednesday week of Jan 8) → goes in week Jan 8."""
        issue = _issue("ISS-1", "done", completed_at=_dt(2024, 1, 10))
        result = calculate_throughput([issue], _d(2024, 1, 8), _d(2024, 1, 14))
        assert len(result) == 1
        assert result[0].week_start == _d(2024, 1, 8)
        assert result[0].count == 1

    def test_zero_filled_weeks_included_in_result(self) -> None:
        """4-week range with completion only in week 1 — weeks 2-4 should be zero."""
        issue = _issue("ISS-1", "done", completed_at=_dt(2024, 1, 2))
        result = calculate_throughput([issue], _d(2024, 1, 1), _d(2024, 1, 28))
        # Should have 4 data points (weeks Jan 1, 8, 15, 22)
        assert len(result) == 4
        counts = [p.count for p in result]
        assert counts[0] == 1
        assert counts[1] == 0
        assert counts[2] == 0
        assert counts[3] == 0

    def test_4_week_moving_average_starts_at_4th_data_point(self) -> None:
        """First 3 points have None for moving_avg; 4th has a value."""
        # Use timedelta to avoid day-out-of-range arithmetic
        base = _d(2024, 1, 1)
        issues = [
            _issue(f"ISS-{i}", "done", completed_at=datetime.combine(base + timedelta(weeks=i), datetime.min.time()).replace(tzinfo=timezone.utc))
            for i in range(6)
        ]
        end = base + timedelta(weeks=5, days=6)
        result = calculate_throughput(issues, base, end)
        assert result[0].moving_avg_4w is None
        assert result[1].moving_avg_4w is None
        assert result[2].moving_avg_4w is None
        assert result[3].moving_avg_4w is not None

    def test_moving_average_calculated_correctly(self) -> None:
        """4 consecutive weeks with 2, 4, 6, 8 completions — avg of last 4 = 5."""
        base = _d(2024, 1, 1)
        issues = []
        for week_offset, count in enumerate([2, 4, 6, 8]):
            for j in range(count):
                completed = datetime.combine(base + timedelta(weeks=week_offset, days=j % 3), datetime.min.time()).replace(tzinfo=timezone.utc)
                issues.append(_issue(f"ISS-{week_offset}-{j}", "done", completed_at=completed))
        result = calculate_throughput(issues, base, base + timedelta(weeks=3, days=6))
        assert result[3].moving_avg_4w == 5.0  # (2+4+6+8)/4

    def test_issues_outside_range_excluded(self) -> None:
        before = _issue("ISS-1", "done", completed_at=_dt(2023, 12, 25))
        after = _issue("ISS-2", "done", completed_at=_dt(2024, 2, 5))
        result = calculate_throughput([before, after], _d(2024, 1, 1), _d(2024, 1, 28))
        assert all(p.count == 0 for p in result)

    def test_multiple_issues_same_week_aggregated(self) -> None:
        issues = [
            _issue("ISS-1", "done", completed_at=_dt(2024, 1, 8)),
            _issue("ISS-2", "done", completed_at=_dt(2024, 1, 9)),
            _issue("ISS-3", "done", completed_at=_dt(2024, 1, 11)),
        ]
        result = calculate_throughput(issues, _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].count == 3


# ---------------------------------------------------------------------------
# calculate_lead_time_scatterplot
# ---------------------------------------------------------------------------


class TestLeadTimeScatterplot:
    def test_empty_issues_returns_empty_points_and_none_percentiles(self) -> None:
        points, p50, p85, p95 = calculate_lead_time_scatterplot([])
        assert points == []
        assert p50 is None
        assert p85 is None
        assert p95 is None

    def test_issues_without_completed_at_excluded(self) -> None:
        issue = _issue("ISS-1", "in_progress", lead_time_hours=10.0, completed_at=None)
        points, p50, _, _ = calculate_lead_time_scatterplot([issue])
        assert points == []
        assert p50 is None

    def test_single_issue_produces_one_point(self) -> None:
        issue = _issue("ISS-1", "done", lead_time_hours=24.0, completed_at=_dt(2024, 1, 10))
        points, p50, p85, p95 = calculate_lead_time_scatterplot([issue])
        assert len(points) == 1
        assert points[0].issue_id == "ISS-1"
        assert points[0].lead_time_hours == 24.0
        assert points[0].is_outlier is False  # single item cannot exceed its own P95

    def test_outlier_flagged_when_above_p95(self) -> None:
        lead_times = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 500.0]
        issues = [
            _issue(f"ISS-{i}", "done", lead_time_hours=lt, completed_at=_dt(2024, 1, i + 1))
            for i, lt in enumerate(lead_times)
        ]
        points, _, _, p95 = calculate_lead_time_scatterplot(issues)
        assert p95 is not None
        outliers = [p for p in points if p.is_outlier]
        assert len(outliers) == 1
        assert outliers[0].lead_time_hours == 500.0

    def test_points_ordered_by_completed_date_ascending(self) -> None:
        issues = [
            _issue("ISS-A", "done", lead_time_hours=5.0, completed_at=_dt(2024, 1, 5)),
            _issue("ISS-B", "done", lead_time_hours=3.0, completed_at=_dt(2024, 1, 2)),
            _issue("ISS-C", "done", lead_time_hours=8.0, completed_at=_dt(2024, 1, 8)),
        ]
        points, _, _, _ = calculate_lead_time_scatterplot(issues)
        dates = [p.completed_date for p in points]
        assert dates == sorted(dates)

    def test_p50_p85_p95_are_ascending(self) -> None:
        lead_times = [float(x) for x in range(1, 11)]
        issues = [
            _issue(f"ISS-{i}", "done", lead_time_hours=lt, completed_at=_dt(2024, 1, i + 1))
            for i, lt in enumerate(lead_times)
        ]
        _, p50, p85, p95 = calculate_lead_time_scatterplot(issues)
        assert p50 <= p85 <= p95  # type: ignore[operator]
