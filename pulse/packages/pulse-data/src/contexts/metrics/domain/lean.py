"""Lean metrics — pure calculation functions.

All functions take data in, return results. No DB access.
TDD: tests come first in Phase 2.

Lean metrics:
- Cumulative Flow Diagram (CFD) data
- Work in Progress (WIP)
- Lead Time Distribution
- Throughput
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class IssueFlowData:
    """Input data for lean flow calculations."""

    issue_id: str
    status: str
    normalized_status: str  # todo | in_progress | done
    status_transitions: list[dict[str, Any]]  # [{status, entered_at, exited_at}, ...]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    lead_time_hours: float | None
    cycle_time_hours: float | None


@dataclass(frozen=True)
class CfdDataPoint:
    """A single point in the Cumulative Flow Diagram."""

    date: date
    todo: int
    in_progress: int
    done: int


@dataclass(frozen=True)
class LeadTimeDistributionBucket:
    """A bucket in the lead time distribution histogram."""

    range_label: str  # e.g. "0-4h", "4-8h", "1-2d"
    count: int
    percentage: float


def calculate_cfd(
    issues: list[IssueFlowData],
    start_date: date,
    end_date: date,
) -> list[CfdDataPoint]:
    """Calculate Cumulative Flow Diagram data points.

    Produces daily counts of items in each status category
    (todo, in_progress, done) over the given date range.

    Args:
        issues: Issues with their status transitions.
        start_date: Period start.
        end_date: Period end.

    Returns:
        Daily CFD data points.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_wip(
    issues: list[IssueFlowData],
    as_of: datetime | None = None,
) -> int:
    """Calculate current Work in Progress count.

    WIP = number of items in 'in_progress' status.

    Args:
        issues: Current issues.
        as_of: Point in time to calculate WIP for. Defaults to now.

    Returns:
        Number of items currently in progress.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_lead_time_distribution(
    issues: list[IssueFlowData],
) -> list[LeadTimeDistributionBucket]:
    """Calculate lead time distribution as a histogram.

    Groups completed issues by lead time into buckets
    for visualization as a distribution chart.

    Args:
        issues: Completed issues with lead_time_hours set.

    Returns:
        Histogram buckets with counts and percentages.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_throughput(
    issues: list[IssueFlowData],
    start_date: date,
    end_date: date,
    bucket: str = "week",
) -> list[dict[str, Any]]:
    """Calculate throughput (items completed per period).

    Args:
        issues: Completed issues.
        start_date: Period start.
        end_date: Period end.
        bucket: Aggregation period ("day" | "week" | "month").

    Returns:
        List of {period, count} dicts.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")
