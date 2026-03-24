"""Unit tests for Throughput metric calculations.

Tests pure domain functions in:
    src/contexts/metrics/domain/throughput.py

Coverage targets:
- calculate_throughput_trend: weekly PR merge counts, P50/P85 cycle time, zero weeks
- calculate_pr_analytics: size histogram, averages, repos breakdown, empty data
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.contexts.metrics.domain.throughput import (
    PullRequestThroughputData,
    calculate_pr_analytics,
    calculate_throughput_trend,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _d(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def _pr(
    pr_id: str = "PR-1",
    repo: str = "org/backend",
    merged_at: datetime | None = None,
    additions: int = 50,
    deletions: int = 10,
    files_changed: int = 3,
    cycle_time_hours: float | None = 24.0,
    reviewer_count: int = 1,
) -> PullRequestThroughputData:
    return PullRequestThroughputData(
        pr_id=pr_id,
        repo=repo,
        merged_at=merged_at,
        additions=additions,
        deletions=deletions,
        files_changed=files_changed,
        cycle_time_hours=cycle_time_hours,
        reviewer_count=reviewer_count,
    )


# ---------------------------------------------------------------------------
# calculate_throughput_trend
# ---------------------------------------------------------------------------


class TestCalculateThroughputTrend:
    def test_start_after_end_returns_empty(self) -> None:
        result = calculate_throughput_trend([], _d(2024, 1, 7), _d(2024, 1, 1))
        assert result == []

    def test_no_merged_prs_all_counts_zero(self) -> None:
        result = calculate_throughput_trend([], _d(2024, 1, 1), _d(2024, 1, 28))
        assert all(p.merged_count == 0 for p in result)

    def test_returns_one_point_per_week(self) -> None:
        result = calculate_throughput_trend([], _d(2024, 1, 1), _d(2024, 1, 28))
        assert len(result) == 4

    def test_pr_counted_in_correct_week(self) -> None:
        pr = _pr("PR-1", merged_at=_dt(2024, 1, 10))
        result = calculate_throughput_trend([pr], _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].week_start == _d(2024, 1, 8)
        assert result[0].merged_count == 1

    def test_pr_without_merged_at_excluded(self) -> None:
        pr = _pr("PR-1", merged_at=None)
        result = calculate_throughput_trend([pr], _d(2024, 1, 1), _d(2024, 1, 7))
        assert result[0].merged_count == 0

    def test_prs_outside_range_excluded(self) -> None:
        before = _pr("PR-1", merged_at=_dt(2023, 12, 25))
        after = _pr("PR-2", merged_at=_dt(2024, 2, 5))
        result = calculate_throughput_trend([before, after], _d(2024, 1, 1), _d(2024, 1, 28))
        assert all(p.merged_count == 0 for p in result)

    def test_cycle_time_percentiles_computed_for_week(self) -> None:
        """Two PRs with 8h and 24h cycle time in same week → P50 = 16h."""
        prs = [
            _pr("PR-1", merged_at=_dt(2024, 1, 8), cycle_time_hours=8.0),
            _pr("PR-2", merged_at=_dt(2024, 1, 9), cycle_time_hours=24.0),
        ]
        result = calculate_throughput_trend(prs, _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].p50_cycle_time_hours == 16.0

    def test_no_cycle_times_in_week_gives_none_percentiles(self) -> None:
        pr = _pr("PR-1", merged_at=_dt(2024, 1, 8), cycle_time_hours=None)
        result = calculate_throughput_trend([pr], _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].p50_cycle_time_hours is None
        assert result[0].p85_cycle_time_hours is None

    def test_additions_and_deletions_summed_per_week(self) -> None:
        prs = [
            _pr("PR-1", merged_at=_dt(2024, 1, 8), additions=100, deletions=20),
            _pr("PR-2", merged_at=_dt(2024, 1, 9), additions=50, deletions=10),
        ]
        result = calculate_throughput_trend(prs, _d(2024, 1, 8), _d(2024, 1, 14))
        assert result[0].total_additions == 150
        assert result[0].total_deletions == 30

    def test_result_ordered_ascending_by_week(self) -> None:
        prs = [
            _pr("PR-1", merged_at=_dt(2024, 1, 15)),
            _pr("PR-2", merged_at=_dt(2024, 1, 8)),
        ]
        result = calculate_throughput_trend(prs, _d(2024, 1, 8), _d(2024, 1, 21))
        weeks = [p.week_start for p in result]
        assert weeks == sorted(weeks)

    def test_zero_weeks_included_with_empty_counts(self) -> None:
        # Jan 1–Feb 4 = weeks Jan 1, 8, 15, 22, 29 → 5 weeks; PR only in week Jan 8
        pr = _pr("PR-1", merged_at=_dt(2024, 1, 8))
        result = calculate_throughput_trend([pr], _d(2024, 1, 1), _d(2024, 2, 4))
        assert len(result) >= 4
        # The PR lands in index 1 (week Jan 8); the rest are empty
        assert result[1].merged_count == 1
        assert result[0].merged_count == 0
        assert result[2].merged_count == 0
        assert result[3].merged_count == 0


# ---------------------------------------------------------------------------
# calculate_pr_analytics
# ---------------------------------------------------------------------------


class TestCalculatePrAnalytics:
    def test_empty_list_returns_all_none_averages(self) -> None:
        result = calculate_pr_analytics([])
        assert result.total_merged == 0
        assert result.avg_size_lines is None
        assert result.avg_files_changed is None
        assert result.avg_reviewer_count is None
        assert result.avg_cycle_time_hours is None
        assert result.median_cycle_time_hours is None

    def test_empty_list_has_empty_repos_breakdown(self) -> None:
        result = calculate_pr_analytics([])
        assert result.repos_breakdown == []

    def test_empty_list_has_zero_count_buckets(self) -> None:
        result = calculate_pr_analytics([])
        assert all(b.count == 0 for b in result.size_distribution)

    def test_total_merged_counts_all_prs(self) -> None:
        prs = [_pr(f"PR-{i}") for i in range(5)]
        result = calculate_pr_analytics(prs)
        assert result.total_merged == 5

    def test_avg_size_excludes_zero_size_prs(self) -> None:
        """PRs with 0 additions+deletions are excluded from avg_size."""
        prs = [
            _pr("PR-1", additions=0, deletions=0),   # zero-size, excluded
            _pr("PR-2", additions=100, deletions=20), # 120 lines
        ]
        result = calculate_pr_analytics(prs)
        assert result.avg_size_lines == 120.0

    def test_avg_size_none_when_all_zero_size(self) -> None:
        prs = [_pr("PR-1", additions=0, deletions=0)]
        result = calculate_pr_analytics(prs)
        assert result.avg_size_lines is None

    def test_size_correctly_classified_into_xs_bucket(self) -> None:
        """PR with 5 lines total → XS bucket."""
        pr = _pr("PR-1", additions=3, deletions=2)
        result = calculate_pr_analytics([pr])
        xs_bucket = next(b for b in result.size_distribution if b.range_label.startswith("XS"))
        assert xs_bucket.count == 1
        assert xs_bucket.percentage == 100.0

    def test_xxl_bucket_captures_very_large_prs(self) -> None:
        pr = _pr("PR-1", additions=1500, deletions=500)  # 2000 lines
        result = calculate_pr_analytics([pr])
        xxl_bucket = next(b for b in result.size_distribution if b.range_label.startswith("XXL"))
        assert xxl_bucket.count == 1

    def test_all_buckets_present_in_size_distribution(self) -> None:
        result = calculate_pr_analytics([_pr("PR-1")])
        labels = [b.range_label for b in result.size_distribution]
        assert "XS (1-10)" in labels
        assert "XXL (1000+)" in labels
        assert len(labels) == 6

    def test_bucket_percentages_sum_to_100(self) -> None:
        prs = [
            _pr("PR-1", additions=5, deletions=0),     # XS
            _pr("PR-2", additions=30, deletions=10),    # S
            _pr("PR-3", additions=150, deletions=50),   # M
            _pr("PR-4", additions=400, deletions=100),  # L
        ]
        result = calculate_pr_analytics(prs)
        total_pct = sum(b.percentage for b in result.size_distribution)
        assert abs(total_pct - 100.0) < 0.5

    def test_repos_breakdown_sorted_descending_by_count(self) -> None:
        prs = [
            _pr("PR-1", repo="org/backend"),
            _pr("PR-2", repo="org/backend"),
            _pr("PR-3", repo="org/frontend"),
            _pr("PR-4", repo="org/backend"),
            _pr("PR-5", repo="org/infra"),
        ]
        result = calculate_pr_analytics(prs)
        counts = [r["count"] for r in result.repos_breakdown]
        assert counts == sorted(counts, reverse=True)
        assert result.repos_breakdown[0]["repo"] == "org/backend"
        assert result.repos_breakdown[0]["count"] == 3

    def test_repos_breakdown_includes_percentage(self) -> None:
        prs = [_pr("PR-1", repo="org/backend"), _pr("PR-2", repo="org/frontend")]
        result = calculate_pr_analytics(prs)
        backend = next(r for r in result.repos_breakdown if r["repo"] == "org/backend")
        assert backend["pct"] == 50.0

    def test_avg_reviewer_count_calculated(self) -> None:
        prs = [
            _pr("PR-1", reviewer_count=1),
            _pr("PR-2", reviewer_count=3),
        ]
        result = calculate_pr_analytics(prs)
        assert result.avg_reviewer_count == 2.0

    def test_median_cycle_time_differs_from_average_for_skewed_data(self) -> None:
        prs = [
            _pr("PR-1", cycle_time_hours=1.0),
            _pr("PR-2", cycle_time_hours=1.0),
            _pr("PR-3", cycle_time_hours=100.0),
        ]
        result = calculate_pr_analytics(prs)
        assert result.median_cycle_time_hours < result.avg_cycle_time_hours  # type: ignore[operator]

    def test_prs_without_cycle_time_excluded_from_averages(self) -> None:
        prs = [
            _pr("PR-1", cycle_time_hours=None),
            _pr("PR-2", cycle_time_hours=12.0),
        ]
        result = calculate_pr_analytics(prs)
        assert result.avg_cycle_time_hours == 12.0
        assert result.median_cycle_time_hours == 12.0

    def test_no_per_developer_ranking_in_result(self) -> None:
        """Anti-surveillance: PrAnalytics must not expose individual developer rankings."""
        prs = [_pr(f"PR-{i}") for i in range(3)]
        result = calculate_pr_analytics(prs)
        field_names = {f.name for f in result.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        forbidden = {"top_contributors", "author_ranking", "developer_leaderboard", "author_scores"}
        assert not field_names.intersection(forbidden)
