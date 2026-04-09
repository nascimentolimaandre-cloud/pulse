"""Lean metrics — pure calculation functions.

All functions take data in, return results. No DB access.

Lean metrics computed here:
- Cumulative Flow Diagram (CFD): daily counts per normalized status stage.
- Work in Progress (WIP): count of items currently in active states.
- Lead Time Distribution: histogram + P50/P85/P95 percentiles.
- Throughput Run Chart: items completed per week + 4-week moving average.
- Lead Time Scatterplot: per-issue completion date vs lead time data points.

Anti-surveillance: all outputs are team-level aggregates. Individual issue
data used only to build aggregate visualizations — no developer attribution.

Status model (normalized_status values):
    backlog | todo | in_progress | in_review | done

"Active" states for WIP: in_progress + in_review.

Lead time histogram bins (hours):
    0-4h, 4-8h, 8-24h (1d), 1-2d, 2-4d (1 week), 1-2w, 2-4w (1 month), 1m+
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = frozenset({"in_progress", "in_review"})

# Histogram bucket definitions: (label, lower_bound_hours, upper_bound_hours)
# upper_bound is exclusive; None means open-ended.
_LEAD_TIME_BUCKETS: list[tuple[str, float, float | None]] = [
    ("0-4h",   0.0,    4.0),
    ("4-8h",   4.0,    8.0),
    ("8-24h",  8.0,    24.0),
    ("1-2d",   24.0,   48.0),
    ("2-5d",   48.0,   120.0),
    ("5-10d",  120.0,  240.0),
    ("10-20d", 240.0,  480.0),
    ("20-30d", 480.0,  720.0),
    ("30d+",   720.0,  None),
]


@dataclass(frozen=True)
class IssueFlowData:
    """Input data for lean flow calculations.

    Mirrors eng_issues columns used in metric calculations.
    status_transitions is a list of dicts:
        [{"status": str, "entered_at": datetime, "exited_at": datetime | None}, ...]
    """

    issue_id: str
    normalized_status: str           # current normalized status
    status_transitions: list[dict[str, Any]]
    created_at: datetime
    started_at: datetime | None      # first entry into in_progress/in_review
    completed_at: datetime | None    # entry into done
    lead_time_hours: float | None    # created_at → completed_at in hours


@dataclass(frozen=True)
class CfdDataPoint:
    """A single daily snapshot in the Cumulative Flow Diagram.

    The CFD tracks cumulative item counts, meaning each status count
    increases monotonically.  `done` is the cumulative number of items
    that reached done on or before this date.  `in_progress` + `in_review`
    is the WIP band width.  Parallel bands = stable flow.
    """

    date: date
    backlog: int
    todo: int
    in_progress: int
    in_review: int
    done: int


@dataclass(frozen=True)
class LeadTimeDistributionBucket:
    """A bucket in the lead time distribution histogram."""

    range_label: str    # e.g. "1-2d"
    lower_hours: float
    upper_hours: float | None   # None = open-ended (30d+)
    count: int
    percentage: float   # 0.0–100.0


@dataclass(frozen=True)
class LeadTimeDistribution:
    """Lead time distribution result for a team/period."""

    buckets: list[LeadTimeDistributionBucket]
    p50_hours: float | None
    p85_hours: float | None
    p95_hours: float | None
    total_issues: int


@dataclass(frozen=True)
class ThroughputDataPoint:
    """Items completed in a single week bucket."""

    week_start: date
    count: int
    moving_avg_4w: float | None   # 4-week moving average; None for first 3 weeks


@dataclass(frozen=True)
class ScatterPoint:
    """A single issue plotted on the lead time scatterplot."""

    issue_id: str
    completed_date: date
    lead_time_hours: float
    is_outlier: bool        # True when lead_time_hours > p95_hours


# ---------------------------------------------------------------------------
# CFD
# ---------------------------------------------------------------------------


def calculate_cfd(
    issues: list[IssueFlowData],
    start_date: date,
    end_date: date,
) -> list[CfdDataPoint]:
    """Calculate Cumulative Flow Diagram data points.

    For each calendar day in [start_date, end_date] we record how many issues
    were in each normalized status stage AT THE END of that day, based on
    status_transitions.  If an issue has no transition data we use its current
    normalized_status for all days after created_at.

    The CFD is additive: items that entered 'done' are counted in the done band
    for all subsequent days (cumulative).  Items still in earlier stages are
    counted there.

    Algorithm:
        For each day D:
          For each issue I:
            Determine which normalized_status I was in at end of day D by
            finding the latest transition whose entered_at <= end-of-day(D).
            Increment the band counter for that status.

    Args:
        issues: Issues with status_transitions.
        start_date: First day of the range (inclusive).
        end_date: Last day of the range (inclusive).

    Returns:
        List of CfdDataPoint, one per calendar day, sorted ascending.
        Returns empty list when start_date > end_date or no issues.
    """
    if start_date > end_date or not issues:
        return []

    # Pre-compute per-issue sorted transitions once.
    # Each entry: (entered_at_datetime, normalized_status_for_that_transition)
    issue_transitions: list[list[tuple[datetime, str]]] = []

    for issue in issues:
        sorted_trans: list[tuple[datetime, str]] = []

        if issue.status_transitions:
            for t in issue.status_transitions:
                entered_raw = t.get("entered_at")
                status_raw = t.get("status") or t.get("normalized_status")
                if entered_raw is None or status_raw is None:
                    continue

                entered_dt = (
                    entered_raw
                    if isinstance(entered_raw, datetime)
                    else datetime.fromisoformat(str(entered_raw))
                )
                # We need the normalized form — if the transition carries raw status,
                # use it as-is (the caller is responsible for normalization).
                sorted_trans.append((entered_dt, str(status_raw)))

        sorted_trans.sort(key=lambda x: x[0])
        # Fallback: treat created_at as initial "todo" entry
        if not sorted_trans:
            sorted_trans = [(issue.created_at, "todo")]

        issue_transitions.append(sorted_trans)

    days: list[CfdDataPoint] = []
    current_day = start_date

    while current_day <= end_date:
        # End-of-day threshold: 23:59:59 on current_day (timezone-aware UTC)
        eod = datetime(current_day.year, current_day.month, current_day.day, 23, 59, 59, tzinfo=timezone.utc)

        counts: dict[str, int] = {
            "backlog": 0,
            "todo": 0,
            "in_progress": 0,
            "in_review": 0,
            "done": 0,
        }

        for i, issue in enumerate(issues):
            trans = issue_transitions[i]

            # Skip issues created after this day
            if issue.created_at > eod:
                continue

            # Find the last transition that started on or before end-of-day
            current_status: str | None = None
            for entered_dt, status_str in trans:
                if entered_dt <= eod:
                    current_status = status_str
                else:
                    break

            if current_status is None:
                # Issue existed but no transition recorded yet; default to backlog
                current_status = "backlog"

            if current_status in counts:
                counts[current_status] += 1
            # Unknown statuses are silently skipped (normalization responsibility of caller)

        days.append(
            CfdDataPoint(
                date=current_day,
                backlog=counts["backlog"],
                todo=counts["todo"],
                in_progress=counts["in_progress"],
                in_review=counts["in_review"],
                done=counts["done"],
            )
        )
        current_day += timedelta(days=1)

    return days


# ---------------------------------------------------------------------------
# WIP
# ---------------------------------------------------------------------------


def calculate_wip(
    issues: list[IssueFlowData],
    as_of: datetime | None = None,
) -> int:
    """Calculate Work in Progress count at a point in time.

    WIP = count of issues in active states (in_progress OR in_review).

    When as_of is provided, the status is inferred from status_transitions
    (using the last transition entered_at <= as_of).  When as_of is None,
    the current normalized_status field is used directly.

    Args:
        issues: Issues to evaluate.
        as_of: Point in time for historical WIP.  None = use current status.

    Returns:
        Integer WIP count.
    """
    if as_of is None:
        return sum(1 for issue in issues if issue.normalized_status in _ACTIVE_STATUSES)

    count = 0
    for issue in issues:
        if issue.created_at > as_of:
            continue  # issue didn't exist yet

        if not issue.status_transitions:
            # Fall back to current status as best approximation
            if issue.normalized_status in _ACTIVE_STATUSES:
                count += 1
            continue

        # Find last transition at or before as_of
        active_status: str = "todo"  # default if issue created but no transitions yet
        for t in sorted(issue.status_transitions, key=lambda x: (
            x["entered_at"]
            if isinstance(x["entered_at"], datetime)
            else datetime.fromisoformat(str(x["entered_at"]))
        )):
            entered_raw = t.get("entered_at")
            if entered_raw is None:
                continue
            entered_dt = (
                entered_raw
                if isinstance(entered_raw, datetime)
                else datetime.fromisoformat(str(entered_raw))
            )
            if entered_dt <= as_of:
                active_status = str(t.get("status") or t.get("normalized_status", "todo"))

        if active_status in _ACTIVE_STATUSES:
            count += 1

    return count


# ---------------------------------------------------------------------------
# Lead Time Distribution
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile p (0–100) from a pre-sorted list using linear interpolation."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    rank = (p / 100.0) * (n - 1)
    lower = int(rank)
    upper = lower + 1
    if upper >= n:
        return sorted_values[-1]

    fraction = rank - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def calculate_lead_time_distribution(
    issues: list[IssueFlowData],
) -> LeadTimeDistribution:
    """Calculate lead time distribution as a histogram with percentile markers.

    Only completed issues (completed_at is not None, lead_time_hours is not None
    and >= 0) are included.

    Histogram bins (hours):
        0-4h, 4-8h, 8-24h, 1-2d, 2-5d, 5-10d, 10-20d, 20-30d, 30d+

    Percentiles: P50 (median), P85, P95.

    Args:
        issues: Issues with lead_time_hours set.

    Returns:
        LeadTimeDistribution with histogram buckets and P50/P85/P95.
        All counts are zero and percentiles are None when no completed issues.
    """
    completed_times: list[float] = [
        issue.lead_time_hours
        for issue in issues
        if issue.lead_time_hours is not None
        and issue.lead_time_hours >= 0
        and issue.completed_at is not None
    ]

    total = len(completed_times)

    if total == 0:
        buckets = [
            LeadTimeDistributionBucket(
                range_label=label,
                lower_hours=lo,
                upper_hours=hi,
                count=0,
                percentage=0.0,
            )
            for label, lo, hi in _LEAD_TIME_BUCKETS
        ]
        return LeadTimeDistribution(
            buckets=buckets, p50_hours=None, p85_hours=None, p95_hours=None, total_issues=0
        )

    # Build histogram
    bucket_counts: list[int] = [0] * len(_LEAD_TIME_BUCKETS)
    for lt in completed_times:
        for idx, (_, lo, hi) in enumerate(_LEAD_TIME_BUCKETS):
            if hi is None:
                if lt >= lo:
                    bucket_counts[idx] += 1
                    break
            elif lo <= lt < hi:
                bucket_counts[idx] += 1
                break

    buckets = [
        LeadTimeDistributionBucket(
            range_label=label,
            lower_hours=lo,
            upper_hours=hi,
            count=bucket_counts[idx],
            percentage=round(bucket_counts[idx] / total * 100, 1),
        )
        for idx, (label, lo, hi) in enumerate(_LEAD_TIME_BUCKETS)
    ]

    sorted_times = sorted(completed_times)
    return LeadTimeDistribution(
        buckets=buckets,
        p50_hours=round(_percentile(sorted_times, 50), 2),
        p85_hours=round(_percentile(sorted_times, 85), 2),
        p95_hours=round(_percentile(sorted_times, 95), 2),
        total_issues=total,
    )


# ---------------------------------------------------------------------------
# Throughput Run Chart
# ---------------------------------------------------------------------------


def _week_start(d: date) -> date:
    """Return the Monday of the ISO week containing `d`."""
    return d - timedelta(days=d.weekday())


def calculate_throughput(
    issues: list[IssueFlowData],
    start_date: date,
    end_date: date,
) -> list[ThroughputDataPoint]:
    """Calculate throughput (items completed per week) with 4-week moving average.

    Only issues with completed_at within [start_date, end_date] are counted.
    Weeks are ISO weeks (Monday–Sunday).

    4-week moving average is applied from the 4th data point onward:
        moving_avg_4w[i] = mean(count[i-3], count[i-2], count[i-1], count[i])

    Args:
        issues: Issues to count (completed_at is the relevant timestamp).
        start_date: Period start.
        end_date: Period end.

    Returns:
        List of ThroughputDataPoint ordered by week_start ascending.
        Includes zero-count weeks within the range.
    """
    if start_date > end_date:
        return []

    # Build weekly buckets covering the full range
    current_week = _week_start(start_date)
    range_end_week = _week_start(end_date)

    weeks: list[date] = []
    while current_week <= range_end_week:
        weeks.append(current_week)
        current_week += timedelta(weeks=1)

    week_counts: dict[date, int] = {w: 0 for w in weeks}

    for issue in issues:
        if issue.completed_at is None:
            continue
        comp_date = issue.completed_at.date() if isinstance(issue.completed_at, datetime) else issue.completed_at
        if start_date <= comp_date <= end_date:
            week_key = _week_start(comp_date)
            if week_key in week_counts:
                week_counts[week_key] += 1

    result: list[ThroughputDataPoint] = []
    counts_list = [week_counts[w] for w in weeks]

    for i, week in enumerate(weeks):
        if i >= 3:
            moving_avg: float | None = sum(counts_list[i - 3: i + 1]) / 4.0
        else:
            moving_avg = None

        result.append(
            ThroughputDataPoint(
                week_start=week,
                count=week_counts[week],
                moving_avg_4w=round(moving_avg, 2) if moving_avg is not None else None,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Lead Time Scatterplot
# ---------------------------------------------------------------------------


def calculate_lead_time_scatterplot(
    issues: list[IssueFlowData],
) -> tuple[list[ScatterPoint], float | None, float | None, float | None]:
    """Build scatterplot data: completion date vs lead time per issue.

    Each completed issue with a valid lead_time_hours becomes one point.
    Points above the P95 line are flagged as outliers.

    Returns:
        (points, p50_hours, p85_hours, p95_hours)

        points: list of ScatterPoint ordered by completed_date ascending.
        p50/p85/p95: horizontal percentile lines to render on the chart.
        All values are None / empty when no completed issues exist.
    """
    completed = [
        issue
        for issue in issues
        if issue.completed_at is not None
        and issue.lead_time_hours is not None
        and issue.lead_time_hours >= 0
    ]

    if not completed:
        return ([], None, None, None)

    lead_times = sorted(issue.lead_time_hours for issue in completed)  # type: ignore[misc]
    p50 = round(_percentile(lead_times, 50), 2)
    p85 = round(_percentile(lead_times, 85), 2)
    p95 = round(_percentile(lead_times, 95), 2)

    points: list[ScatterPoint] = []
    for issue in sorted(completed, key=lambda x: x.completed_at):  # type: ignore[arg-type]
        comp_date = (
            issue.completed_at.date()
            if isinstance(issue.completed_at, datetime)
            else issue.completed_at
        )
        points.append(
            ScatterPoint(
                issue_id=issue.issue_id,
                completed_date=comp_date,  # type: ignore[arg-type]
                lead_time_hours=issue.lead_time_hours,  # type: ignore[arg-type]
                is_outlier=issue.lead_time_hours > p95,  # type: ignore[operator]
            )
        )

    return (points, p50, p85, p95)
