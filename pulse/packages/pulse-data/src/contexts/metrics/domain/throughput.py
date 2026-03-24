"""Throughput metrics — pure calculation functions.

All functions take data in, return results. No DB access.
TDD: tests come first in Phase 2.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PullRequestThroughputData:
    """Input data for PR throughput analytics."""

    pr_id: str
    repo: str
    author: str
    merged_at: datetime | None
    additions: int
    deletions: int
    files_changed: int
    cycle_time_hours: float | None
    reviewers: list[str]


@dataclass(frozen=True)
class ThroughputTrendPoint:
    """A data point in the throughput trend chart."""

    date: date
    merged_count: int
    avg_cycle_time_hours: float | None
    total_additions: int
    total_deletions: int


@dataclass(frozen=True)
class PrAnalytics:
    """Aggregated PR analytics for a period."""

    total_merged: int
    avg_size_lines: float  # additions + deletions
    avg_files_changed: float
    avg_reviewers: float
    avg_cycle_time_hours: float | None
    top_contributors: list[dict[str, Any]]  # [{author, count}, ...]
    repos_breakdown: list[dict[str, Any]]  # [{repo, count}, ...]


def calculate_throughput_trend(
    pull_requests: list[PullRequestThroughputData],
    start_date: date,
    end_date: date,
    bucket: str = "week",
) -> list[ThroughputTrendPoint]:
    """Calculate PR merge throughput trend over time.

    Args:
        pull_requests: Merged PRs in the period.
        start_date: Period start.
        end_date: Period end.
        bucket: Aggregation period ("day" | "week" | "month").

    Returns:
        Trend data points.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_pr_analytics(
    pull_requests: list[PullRequestThroughputData],
) -> PrAnalytics:
    """Calculate aggregated PR analytics for a period.

    Args:
        pull_requests: Merged PRs to analyze.

    Returns:
        Aggregated analytics including size, reviewers, top contributors.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")
