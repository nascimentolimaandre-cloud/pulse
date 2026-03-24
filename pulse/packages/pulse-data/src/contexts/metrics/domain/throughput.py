"""Throughput metrics — pure calculation functions.

All functions take data in, return results. No DB access.

Throughput metrics computed here:
- Throughput Trend: PR merge count per week with per-week cycle time stats.
- PR Analytics: aggregated size, reviewer, and repo breakdown.

Anti-surveillance: `top_contributors` and `repos_breakdown` aggregate counts
by repository and reviewer slot count respectively — never by individual
developer identity for performance ranking.  Author data is aggregated at
the repository/team level only.

Note on author field: the `author` field on PullRequestThroughputData is
included solely so the caller can compute repo-level breakdowns.  PULSE does
NOT expose per-author rankings on any dashboard.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PullRequestThroughputData:
    """Input data for PR throughput analytics.

    Mirrors eng_pull_requests columns used in metric calculations.
    """

    pr_id: str
    repo: str
    merged_at: datetime | None
    additions: int
    deletions: int
    files_changed: int
    cycle_time_hours: float | None
    reviewer_count: int     # number of unique reviewers (not their identities)


@dataclass(frozen=True)
class ThroughputTrendPoint:
    """Throughput and cycle time data for a single week bucket."""

    week_start: date
    merged_count: int
    p50_cycle_time_hours: float | None
    p85_cycle_time_hours: float | None
    total_additions: int
    total_deletions: int


@dataclass(frozen=True)
class PrSizeDistributionBucket:
    """Histogram bucket for PR size (lines changed)."""

    range_label: str        # e.g. "XS (1-10)", "S (11-50)"
    lower_lines: int
    upper_lines: int | None
    count: int
    percentage: float


@dataclass(frozen=True)
class PrAnalytics:
    """Aggregated PR analytics for a period.

    All metrics are team-level aggregates.  No per-developer ranking.
    """

    total_merged: int
    avg_size_lines: float | None        # mean(additions + deletions)
    avg_files_changed: float | None
    avg_reviewer_count: float | None
    avg_cycle_time_hours: float | None
    median_cycle_time_hours: float | None
    size_distribution: list[PrSizeDistributionBucket]
    repos_breakdown: list[dict[str, Any]]   # [{repo, count, pct}, ...] sorted desc


# PR size buckets: (label, lower_lines, upper_lines)
_PR_SIZE_BUCKETS: list[tuple[str, int, int | None]] = [
    ("XS (1-10)",     1,     10),
    ("S (11-50)",     11,    50),
    ("M (51-200)",    51,    200),
    ("L (201-500)",   201,   500),
    ("XL (501-1000)", 501,   1000),
    ("XXL (1000+)",   1001,  None),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _week_start(d: date) -> date:
    """Return the Monday of the ISO week containing `d`."""
    return d - timedelta(days=d.weekday())


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile p (0–100) using linear interpolation."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    rank = (p / 100.0) * (n - 1)
    lower = int(rank)
    upper = lower + 1
    if upper >= n:
        return sorted_values[-1]
    return sorted_values[lower] + (rank - lower) * (sorted_values[upper] - sorted_values[lower])


# ---------------------------------------------------------------------------
# Throughput trend
# ---------------------------------------------------------------------------


def calculate_throughput_trend(
    pull_requests: list[PullRequestThroughputData],
    start_date: date,
    end_date: date,
    bucket: str = "week",
) -> list[ThroughputTrendPoint]:
    """Calculate PR merge throughput trend over time.

    PRs are bucketed by merged_at date.  Zero-count weeks within the range
    are included.  Only "week" bucketing is active in MVP.

    For each week:
        merged_count = number of PRs with merged_at in that week
        p50/p85_cycle_time_hours = percentiles of cycle_time_hours for that week
        total_additions / total_deletions = sum of code churn

    Args:
        pull_requests: Merged PRs (merged_at must be set).
        start_date: Period start.
        end_date: Period end.
        bucket: Aggregation granularity; only "week" is active in MVP.

    Returns:
        List of ThroughputTrendPoint ordered by week_start ascending.
    """
    if start_date > end_date:
        return []

    # Build week buckets for the full range
    current_week = _week_start(start_date)
    end_week = _week_start(end_date)
    weeks: list[date] = []
    while current_week <= end_week:
        weeks.append(current_week)
        current_week += timedelta(weeks=1)

    # Per-week accumulators
    week_prs: dict[date, list[PullRequestThroughputData]] = {w: [] for w in weeks}

    for pr in pull_requests:
        if pr.merged_at is None:
            continue
        merged_date = pr.merged_at.date() if isinstance(pr.merged_at, datetime) else pr.merged_at
        if not (start_date <= merged_date <= end_date):
            continue
        week_key = _week_start(merged_date)
        if week_key in week_prs:
            week_prs[week_key].append(pr)

    result: list[ThroughputTrendPoint] = []
    for week in weeks:
        prs = week_prs[week]
        cycle_times = sorted(
            pr.cycle_time_hours for pr in prs if pr.cycle_time_hours is not None
        )

        p50 = round(_percentile(cycle_times, 50), 2) if cycle_times else None
        p85 = round(_percentile(cycle_times, 85), 2) if cycle_times else None

        result.append(
            ThroughputTrendPoint(
                week_start=week,
                merged_count=len(prs),
                p50_cycle_time_hours=p50,
                p85_cycle_time_hours=p85,
                total_additions=sum(pr.additions for pr in prs),
                total_deletions=sum(pr.deletions for pr in prs),
            )
        )

    return result


# ---------------------------------------------------------------------------
# PR Analytics
# ---------------------------------------------------------------------------


def calculate_pr_analytics(
    pull_requests: list[PullRequestThroughputData],
) -> PrAnalytics:
    """Calculate aggregated PR analytics for a period.

    Size is defined as additions + deletions (total lines changed).
    PRs with additions=0 and deletions=0 (e.g., pure reverts recorded as
    zero-diff) are included in the count but excluded from avg_size calculation.

    Repos breakdown is sorted descending by count and includes percentage of
    total PRs.

    Args:
        pull_requests: Merged PRs to analyze.

    Returns:
        Aggregated analytics.  All averages are None when total_merged == 0.
    """
    total = len(pull_requests)

    if total == 0:
        empty_buckets = [
            PrSizeDistributionBucket(
                range_label=label, lower_lines=lo, upper_lines=hi, count=0, percentage=0.0
            )
            for label, lo, hi in _PR_SIZE_BUCKETS
        ]
        return PrAnalytics(
            total_merged=0,
            avg_size_lines=None,
            avg_files_changed=None,
            avg_reviewer_count=None,
            avg_cycle_time_hours=None,
            median_cycle_time_hours=None,
            size_distribution=empty_buckets,
            repos_breakdown=[],
        )

    # Size stats
    sizes = [pr.additions + pr.deletions for pr in pull_requests]
    non_zero_sizes = [s for s in sizes if s > 0]
    avg_size = round(statistics.mean(non_zero_sizes), 1) if non_zero_sizes else None

    # File count
    files = [pr.files_changed for pr in pull_requests]
    avg_files = round(statistics.mean(files), 1) if files else None

    # Reviewer count
    reviewer_counts = [pr.reviewer_count for pr in pull_requests]
    avg_reviewers = round(statistics.mean(reviewer_counts), 2) if reviewer_counts else None

    # Cycle time
    cycle_times = [pr.cycle_time_hours for pr in pull_requests if pr.cycle_time_hours is not None]
    avg_ct = round(statistics.mean(cycle_times), 2) if cycle_times else None
    med_ct = round(statistics.median(cycle_times), 2) if cycle_times else None

    # Size distribution histogram
    bucket_counts: list[int] = [0] * len(_PR_SIZE_BUCKETS)
    for size in sizes:
        for idx, (_, lo, hi) in enumerate(_PR_SIZE_BUCKETS):
            if hi is None:
                if size >= lo:
                    bucket_counts[idx] += 1
                    break
            elif lo <= size <= hi:
                bucket_counts[idx] += 1
                break

    size_distribution = [
        PrSizeDistributionBucket(
            range_label=label,
            lower_lines=lo,
            upper_lines=hi,
            count=bucket_counts[idx],
            percentage=round(bucket_counts[idx] / total * 100, 1),
        )
        for idx, (label, lo, hi) in enumerate(_PR_SIZE_BUCKETS)
    ]

    # Repos breakdown
    repo_counts: dict[str, int] = defaultdict(int)
    for pr in pull_requests:
        repo_counts[pr.repo] += 1

    repos_breakdown = [
        {"repo": repo, "count": count, "pct": round(count / total * 100, 1)}
        for repo, count in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return PrAnalytics(
        total_merged=total,
        avg_size_lines=avg_size,
        avg_files_changed=avg_files,
        avg_reviewer_count=avg_reviewers,
        avg_cycle_time_hours=avg_ct,
        median_cycle_time_hours=med_ct,
        size_distribution=size_distribution,
        repos_breakdown=repos_breakdown,
    )
