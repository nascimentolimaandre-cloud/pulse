"""Sprint metrics — pure calculation functions.

All functions take data in, return results. No DB access.
TDD: tests come first in Phase 2.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SprintData:
    """Input data for sprint calculations."""

    sprint_id: str
    name: str
    committed_items: int
    committed_points: float
    added_items: int
    removed_items: int
    completed_items: int
    completed_points: float
    carried_over_items: int


@dataclass(frozen=True)
class SprintOverview:
    """Computed sprint overview metrics."""

    completion_rate_items: float | None  # completed / committed (0.0 - 1.0)
    completion_rate_points: float | None
    scope_change_rate: float | None  # (added + removed) / committed
    carry_over_rate: float | None  # carried_over / committed
    velocity_points: float  # completed_points


@dataclass(frozen=True)
class SprintComparison:
    """Comparison of multiple sprints for trend visualization."""

    sprints: list[dict[str, Any]]  # [{name, committed, completed, velocity, ...}, ...]
    avg_velocity: float
    velocity_trend: str  # "improving" | "stable" | "declining"


def calculate_sprint_overview(
    sprint: SprintData,
) -> SprintOverview:
    """Calculate overview metrics for a single sprint.

    Args:
        sprint: Sprint data with committed/completed counts.

    Returns:
        Computed rates and velocity.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_sprint_comparison(
    sprints: list[SprintData],
) -> SprintComparison:
    """Compare multiple sprints to identify velocity trends.

    Args:
        sprints: List of sprint data ordered by date (oldest first).

    Returns:
        Comparison with average velocity and trend direction.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")
