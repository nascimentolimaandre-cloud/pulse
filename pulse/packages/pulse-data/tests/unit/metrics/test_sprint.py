"""Unit tests for Sprint metric calculations.

Tests pure domain functions in:
    src/contexts/metrics/domain/sprint.py

Coverage targets:
- calculate_sprint_overview: rates, scope creep %, carryover, final_scope clamping
- calculate_sprint_comparison: velocity trend (improving/stable/declining/insufficient_data)
- Edge cases: zero committed, zero completed, all items removed
"""

from __future__ import annotations

import pytest

from src.contexts.metrics.domain.sprint import (
    SprintData,
    calculate_sprint_comparison,
    calculate_sprint_overview,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sprint(
    sprint_id: str = "SP-1",
    name: str = "Sprint 1",
    committed_items: int = 10,
    committed_points: float = 20.0,
    added_items: int = 0,
    removed_items: int = 0,
    completed_items: int = 10,
    completed_points: float = 20.0,
    carried_over_items: int = 0,
) -> SprintData:
    return SprintData(
        sprint_id=sprint_id,
        name=name,
        committed_items=committed_items,
        committed_points=committed_points,
        added_items=added_items,
        removed_items=removed_items,
        completed_items=completed_items,
        completed_points=completed_points,
        carried_over_items=carried_over_items,
    )


# ---------------------------------------------------------------------------
# calculate_sprint_overview
# ---------------------------------------------------------------------------


class TestCalculateSprintOverview:
    def test_perfect_sprint_100_percent_completion(self) -> None:
        sprint = _sprint(committed_items=10, completed_items=10, carried_over_items=0)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate == 1.0
        assert result.carried_over_items == 0

    def test_80_percent_completion_rate(self) -> None:
        sprint = _sprint(committed_items=10, completed_items=8, carried_over_items=2)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate == 0.8

    def test_zero_committed_items_rates_are_none(self) -> None:
        sprint = _sprint(committed_items=0, committed_points=0.0, completed_items=0)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate is None
        assert result.scope_creep_pct is None
        assert result.carryover_rate is None

    def test_zero_committed_points_completion_rate_points_is_none(self) -> None:
        sprint = _sprint(committed_items=5, committed_points=0.0, completed_points=0.0)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate_points is None

    def test_scope_creep_pct_calculated_correctly(self) -> None:
        """3 items added to a 10-item sprint = 30% scope creep."""
        sprint = _sprint(committed_items=10, added_items=3, completed_items=10)
        result = calculate_sprint_overview(sprint)
        assert result.scope_creep_pct == 30.0

    def test_no_scope_creep_returns_zero_pct(self) -> None:
        sprint = _sprint(committed_items=10, added_items=0)
        result = calculate_sprint_overview(sprint)
        assert result.scope_creep_pct == 0.0

    def test_final_scope_includes_added_minus_removed(self) -> None:
        sprint = _sprint(committed_items=10, added_items=3, removed_items=2)
        result = calculate_sprint_overview(sprint)
        assert result.final_scope_items == 11  # 10 + 3 - 2

    def test_final_scope_clamped_to_zero_when_negative(self) -> None:
        """Removing more items than committed should clamp to 0, not go negative."""
        sprint = _sprint(committed_items=5, removed_items=10)
        result = calculate_sprint_overview(sprint)
        assert result.final_scope_items == 0
        assert result.completion_rate is None  # 0 final scope

    def test_carryover_rate_calculated_correctly(self) -> None:
        sprint = _sprint(committed_items=10, carried_over_items=2)
        result = calculate_sprint_overview(sprint)
        assert result.carryover_rate == 0.2

    def test_zero_carryover_returns_zero_rate(self) -> None:
        sprint = _sprint(committed_items=10, carried_over_items=0)
        result = calculate_sprint_overview(sprint)
        assert result.carryover_rate == 0.0

    def test_completion_rate_points_100_percent(self) -> None:
        sprint = _sprint(committed_points=20.0, completed_points=20.0)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate_points == 1.0

    def test_completion_rate_capped_at_1_when_over_committed(self) -> None:
        """Completing more items than committed (e.g., added items): cap at 1.0."""
        sprint = _sprint(committed_items=10, added_items=5, completed_items=15)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate == 1.0

    def test_raw_counts_passed_through_unchanged(self) -> None:
        sprint = _sprint(
            committed_items=10,
            added_items=2,
            removed_items=1,
            completed_items=8,
            carried_over_items=2,
        )
        result = calculate_sprint_overview(sprint)
        assert result.committed_items == 10
        assert result.added_items == 2
        assert result.removed_items == 1
        assert result.completed_items == 8
        assert result.carried_over_items == 2

    def test_completed_items_zero_gives_zero_completion_rate(self) -> None:
        sprint = _sprint(committed_items=10, completed_items=0, carried_over_items=10)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate == 0.0


# ---------------------------------------------------------------------------
# calculate_sprint_comparison
# ---------------------------------------------------------------------------


class TestCalculateSprintComparison:
    def test_empty_list_returns_insufficient_data(self) -> None:
        result = calculate_sprint_comparison([])
        assert result.velocity_trend == "insufficient_data"
        assert result.avg_velocity is None
        assert result.sprints == []

    def test_single_sprint_returns_insufficient_data(self) -> None:
        result = calculate_sprint_comparison([_sprint(completed_points=20.0)])
        assert result.velocity_trend == "insufficient_data"

    def test_improving_velocity_trend(self) -> None:
        """Velocity going 10 → 20 → 30 → 40 → 50 → 60: clearly improving."""
        sprints = [
            _sprint(f"SP-{i}", completed_points=float(i * 10))
            for i in range(1, 7)
        ]
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "improving"

    def test_declining_velocity_trend(self) -> None:
        """Velocity going 60 → 50 → 40 → 30 → 20 → 10: clearly declining."""
        sprints = [
            _sprint(f"SP-{i}", completed_points=float((7 - i) * 10))
            for i in range(1, 7)
        ]
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "declining"

    def test_stable_velocity_trend(self) -> None:
        """Velocity oscillating around same mean: stable."""
        sprints = [
            _sprint("SP-1", completed_points=20.0),
            _sprint("SP-2", completed_points=20.0),
            _sprint("SP-3", completed_points=20.0),
            _sprint("SP-4", completed_points=20.0),
        ]
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "stable"

    def test_average_velocity_is_mean_of_completed_points(self) -> None:
        sprints = [
            _sprint("SP-1", completed_points=10.0),
            _sprint("SP-2", completed_points=20.0),
            _sprint("SP-3", completed_points=30.0),
        ]
        result = calculate_sprint_comparison(sprints)
        assert result.avg_velocity == 20.0

    def test_summaries_ordered_same_as_input(self) -> None:
        sprints = [
            _sprint("SP-1", name="Sprint 1"),
            _sprint("SP-2", name="Sprint 2"),
            _sprint("SP-3", name="Sprint 3"),
        ]
        result = calculate_sprint_comparison(sprints)
        assert [s.sprint_id for s in result.sprints] == ["SP-1", "SP-2", "SP-3"]

    def test_summary_includes_completion_rate(self) -> None:
        sprint = _sprint("SP-1", committed_items=10, completed_items=8)
        result = calculate_sprint_comparison([sprint, sprint])
        assert result.sprints[0].completion_rate == 0.8

    def test_only_last_6_sprints_used_for_trend(self) -> None:
        """7 sprints: first 6 declining but last 6 are stable — trend is stable."""
        # velocities: 100, 10, 20, 20, 20, 20, 20 — last 6: 10,20,20,20,20,20
        velocities = [100.0, 10.0, 20.0, 20.0, 20.0, 20.0, 20.0]
        sprints = [_sprint(f"SP-{i}", completed_points=v) for i, v in enumerate(velocities)]
        result = calculate_sprint_comparison(sprints)
        # Last 6: 10, 20, 20, 20, 20, 20 → gentle positive slope = might be improving
        # What matters is the function only considers last 6
        assert result.velocity_trend in ("stable", "improving")  # last 6 exclude the 100 outlier

    def test_all_zero_velocity_is_stable(self) -> None:
        sprints = [_sprint(f"SP-{i}", completed_points=0.0) for i in range(4)]
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "stable"
        assert result.avg_velocity == 0.0
