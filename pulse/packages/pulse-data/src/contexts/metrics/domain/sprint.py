"""Sprint metrics — pure calculation functions.

All functions take data in, return results. No DB access.

Sprint metrics computed here:
- Sprint Overview: committed, added, completed, removed, carryover, rates.
- Sprint Comparison: velocity trend across multiple sprints.

Definitions (aligned with the PULSE product spec):

    Committed items   : items in the sprint at start_date (baseline).
    Added items       : items added AFTER the sprint started (scope creep).
    Removed items     : items removed after the sprint started.
    Completed items   : items in done state by end_date.
    Carryover items   : committed items NOT completed (carried to next sprint).

    Scope creep %     : (added_items / committed_items) * 100
                        Represents unplanned work added mid-sprint.

    Completion rate   : completed_items / (committed_items + added_items - removed_items)
                        Denominator is the "final scope" of the sprint.

    Velocity          : completed_points (story points delivered).

    Velocity trend    : computed by linear regression slope over the last N sprints.
                        "improving"  → positive slope
                        "stable"     → slope near zero (within ±10% of mean velocity)
                        "declining"  → negative slope

Anti-surveillance: no per-developer attribution is computed or returned.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SprintData:
    """Input data for a single sprint.

    Mirrors relevant columns of eng_sprints + aggregated issue counts
    pre-computed by the Metrics Worker from eng_issues.
    """

    sprint_id: str
    name: str
    committed_items: int        # items at sprint start
    committed_points: float     # story points at sprint start
    added_items: int            # items added mid-sprint (scope creep)
    removed_items: int          # items removed mid-sprint
    completed_items: int        # items in done state by end
    completed_points: float     # story points delivered
    carried_over_items: int     # committed items not completed


@dataclass(frozen=True)
class SprintOverview:
    """Computed overview metrics for a single sprint.

    All rates are 0.0–1.0 (e.g., 0.85 = 85%).
    None indicates insufficient data (e.g., committed_items == 0).
    """

    # Raw counts (passed through for convenience)
    committed_items: int
    added_items: int
    removed_items: int
    completed_items: int
    carried_over_items: int
    final_scope_items: int      # committed + added - removed

    # Rates
    completion_rate: float | None       # completed / final_scope
    scope_creep_pct: float | None       # (added / committed) * 100  — % not a ratio
    carryover_rate: float | None        # carried_over / committed

    # Points
    committed_points: float
    completed_points: float
    completion_rate_points: float | None  # completed_points / committed_points


@dataclass(frozen=True)
class SprintSummary:
    """Per-sprint summary row used in comparison charts."""

    sprint_id: str
    name: str
    committed_items: int
    completed_items: int
    velocity_points: float
    completion_rate: float | None
    scope_creep_pct: float | None


@dataclass(frozen=True)
class SprintComparison:
    """Comparison of multiple sprints for trend visualization.

    sprints is ordered oldest → newest (same order as input).
    avg_velocity is the mean of velocity_points across all sprints.
    velocity_trend reflects whether velocity is improving, stable, or declining
    based on a simple linear slope of the last N sprint velocities.
    """

    sprints: list[SprintSummary]
    avg_velocity: float | None
    velocity_trend: str     # "improving" | "stable" | "declining" | "insufficient_data"


# ---------------------------------------------------------------------------
# Single sprint overview
# ---------------------------------------------------------------------------


def calculate_sprint_overview(sprint: SprintData) -> SprintOverview:
    """Calculate overview metrics for a single sprint.

    Formula:
        final_scope = committed_items + added_items - removed_items
        completion_rate = completed_items / final_scope  (None if final_scope <= 0)
        scope_creep_pct = (added_items / committed_items) * 100  (None if committed == 0)
        carryover_rate = carried_over_items / committed_items  (None if committed == 0)
        completion_rate_points = completed_points / committed_points  (None if committed == 0)

    Args:
        sprint: Sprint data with raw counts and points.

    Returns:
        SprintOverview with computed rates.
    """
    final_scope = max(sprint.committed_items + sprint.added_items - sprint.removed_items, 0)

    completion_rate: float | None = None
    if final_scope > 0:
        completion_rate = min(sprint.completed_items / final_scope, 1.0)

    scope_creep_pct: float | None = None
    carryover_rate: float | None = None
    completion_rate_points: float | None = None

    if sprint.committed_items > 0:
        scope_creep_pct = round((sprint.added_items / sprint.committed_items) * 100, 1)
        carryover_rate = round(sprint.carried_over_items / sprint.committed_items, 4)

    if sprint.committed_points > 0:
        completion_rate_points = round(
            min(sprint.completed_points / sprint.committed_points, 1.0), 4
        )

    return SprintOverview(
        committed_items=sprint.committed_items,
        added_items=sprint.added_items,
        removed_items=sprint.removed_items,
        completed_items=sprint.completed_items,
        carried_over_items=sprint.carried_over_items,
        final_scope_items=final_scope,
        completion_rate=round(completion_rate, 4) if completion_rate is not None else None,
        scope_creep_pct=scope_creep_pct,
        carryover_rate=carryover_rate,
        committed_points=sprint.committed_points,
        completed_points=sprint.completed_points,
        completion_rate_points=completion_rate_points,
    )


# ---------------------------------------------------------------------------
# Multi-sprint comparison
# ---------------------------------------------------------------------------


def _linear_slope(values: list[float]) -> float:
    """Compute the slope of a simple linear regression y = a + b*x.

    x is the index (0, 1, 2 ...).  Returns 0.0 for single-element lists.
    """
    n = len(values)
    if n < 2:
        return 0.0

    x_mean = (n - 1) / 2.0
    y_mean = statistics.mean(values)

    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return 0.0
    return numerator / denominator


def _velocity_trend(velocities: list[float]) -> str:
    """Classify velocity trend from an ordered list of sprint velocities.

    Trend is determined by the linear slope of the last 6 sprints (or all
    if fewer):
        slope > +5% of mean  → "improving"
        slope < -5% of mean  → "declining"
        otherwise            → "stable"

    Returns "insufficient_data" when fewer than 2 sprints are available.
    """
    if len(velocities) < 2:
        return "insufficient_data"

    recent = velocities[-6:]  # cap to last 6 sprints
    slope = _linear_slope(recent)
    mean_v = statistics.mean(recent)

    if mean_v == 0:
        return "stable"

    threshold = abs(mean_v) * 0.05  # 5% of mean velocity
    if slope > threshold:
        return "improving"
    if slope < -threshold:
        return "declining"
    return "stable"


def calculate_sprint_comparison(sprints: list[SprintData]) -> SprintComparison:
    """Compare multiple sprints to identify velocity trends.

    Args:
        sprints: Sprint data ordered oldest → newest.

    Returns:
        SprintComparison with per-sprint summaries and overall trend.
    """
    if not sprints:
        return SprintComparison(sprints=[], avg_velocity=None, velocity_trend="insufficient_data")

    summaries: list[SprintSummary] = []
    velocities: list[float] = []

    for sprint in sprints:
        overview = calculate_sprint_overview(sprint)
        summaries.append(
            SprintSummary(
                sprint_id=sprint.sprint_id,
                name=sprint.name,
                committed_items=sprint.committed_items,
                completed_items=sprint.completed_items,
                velocity_points=sprint.completed_points,
                completion_rate=overview.completion_rate,
                scope_creep_pct=overview.scope_creep_pct,
            )
        )
        velocities.append(sprint.completed_points)

    avg_velocity = round(statistics.mean(velocities), 2) if velocities else None
    trend = _velocity_trend(velocities)

    return SprintComparison(
        sprints=summaries,
        avg_velocity=avg_velocity,
        velocity_trend=trend,
    )
