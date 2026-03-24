"""Cycle time metrics — pure calculation functions.

All functions take data in, return results. No DB access.
TDD: tests come first in Phase 2.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PullRequestCycleData:
    """Input data for PR-based cycle time breakdown."""

    pr_id: str
    first_commit_at: datetime | None
    first_review_at: datetime | None
    approved_at: datetime | None
    merged_at: datetime | None
    deployed_at: datetime | None


@dataclass(frozen=True)
class CycleTimeBreakdown:
    """Cycle time broken down by phase (median hours)."""

    coding_time_hours: float | None  # first_commit -> first_review
    review_time_hours: float | None  # first_review -> approved
    merge_time_hours: float | None  # approved -> merged
    deploy_time_hours: float | None  # merged -> deployed
    total_hours: float | None


@dataclass(frozen=True)
class CycleTimeTrendPoint:
    """A single point in the cycle time trend chart."""

    date: date
    median_hours: float
    p75_hours: float
    p95_hours: float
    count: int


def calculate_cycle_time_breakdown(
    pull_requests: list[PullRequestCycleData],
) -> CycleTimeBreakdown:
    """Calculate median cycle time broken down by phase.

    Phases: Coding -> Review -> Merge -> Deploy.
    Each phase is the median time between its boundary timestamps.

    Args:
        pull_requests: PRs with lifecycle timestamps.

    Returns:
        Breakdown with median hours per phase.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_cycle_time_trend(
    pull_requests: list[PullRequestCycleData],
    start_date: date,
    end_date: date,
    bucket: str = "week",
) -> list[CycleTimeTrendPoint]:
    """Calculate cycle time trend over the given period.

    Groups PRs by merge date into buckets and computes
    median, p75, and p95 cycle times per bucket.

    Args:
        pull_requests: PRs with lifecycle timestamps.
        start_date: Period start.
        end_date: Period end.
        bucket: Aggregation period ("day" | "week" | "month").

    Returns:
        Trend data points with percentile cycle times.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")
