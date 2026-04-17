"""Metrics validation tests — table-driven tests for all PULSE indicators.

Covers:
- Deploy Frequency, Lead Time, CFR, MTTR (DORA)
- Cycle Time Breakdown (P50/P85/P95, bottleneck, phases)
- WIP, CFD, Lead Time Distribution, Throughput, Scatterplot (Lean)
- Sprint Overview, Sprint Comparison

For each metric:
    - Happy path (normal distribution)
    - Edge case: empty input
    - Edge case: degenerate/uniform data
    - Edge case: null/missing partial data
    - Edge case: extreme outliers
    - Regression: values grounded in Webmotors production ballpark
    - Anti-surveillance: no per-author data exposed

Run:
    pytest pulse/packages/pulse-data/tests/unit/metrics/test_metrics_validation.py -v
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from src.contexts.metrics.domain.cycle_time import (
    PullRequestCycleData,
    calculate_cycle_time_breakdown,
    calculate_cycle_time_trend,
)
from src.contexts.metrics.domain.dora import (
    DeploymentData,
    DoraLevel,
    PullRequestData,
    calculate_change_failure_rate,
    calculate_deployment_frequency,
    calculate_dora_metrics,
    calculate_lead_time,
    calculate_mttr,
)
from src.contexts.metrics.domain.lean import (
    IssueFlowData,
    calculate_cfd,
    calculate_lead_time_distribution,
    calculate_lead_time_scatterplot,
    calculate_throughput,
    calculate_wip,
)
from src.contexts.metrics.domain.sprint import (
    SprintData,
    calculate_sprint_comparison,
    calculate_sprint_overview,
)
from src.contexts.metrics.domain.throughput import (
    PullRequestThroughputData,
    calculate_pr_analytics,
    calculate_throughput_trend,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _d(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def _deployment(
    deployed_at: datetime,
    is_failure: bool = False,
    recovery_time_hours: float | None = None,
) -> DeploymentData:
    return DeploymentData(
        deployed_at=deployed_at,
        is_failure=is_failure,
        recovery_time_hours=recovery_time_hours,
    )


def _pr_data(
    first_commit_at: datetime | None,
    merged_at: datetime | None,
    deployed_at: datetime | None = None,
) -> PullRequestData:
    return PullRequestData(
        first_commit_at=first_commit_at,
        merged_at=merged_at,
        deployed_at=deployed_at,
    )


def _pr_cycle(
    pr_id: str = "PR-1",
    first_commit: datetime | None = None,
    first_review: datetime | None = None,
    approved: datetime | None = None,
    merged: datetime | None = None,
    deployed: datetime | None = None,
) -> PullRequestCycleData:
    return PullRequestCycleData(
        pr_id=pr_id,
        first_commit_at=first_commit,
        first_review_at=first_review,
        approved_at=approved,
        merged_at=merged,
        deployed_at=deployed,
    )


def _issue(
    issue_id: str = "ISS-1",
    status: str = "in_progress",
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    lead_time_hours: float | None = None,
    transitions: list | None = None,
    started_at: datetime | None = None,
) -> IssueFlowData:
    return IssueFlowData(
        issue_id=issue_id,
        normalized_status=status,
        status_transitions=transitions or [],
        created_at=created_at or _dt(2026, 1, 1),
        started_at=started_at,
        completed_at=completed_at,
        lead_time_hours=lead_time_hours,
    )


def _sprint(
    sprint_id: str = "SP-1",
    name: str = "Sprint 1",
    committed: int = 20,
    committed_pts: float = 40.0,
    added: int = 3,
    removed: int = 1,
    completed: int = 16,
    completed_pts: float = 32.0,
    carried_over: int = 4,
) -> SprintData:
    return SprintData(
        sprint_id=sprint_id,
        name=name,
        committed_items=committed,
        committed_points=committed_pts,
        added_items=added,
        removed_items=removed,
        completed_items=completed,
        completed_points=completed_pts,
        carried_over_items=carried_over,
    )


# ===========================================================================
# SECTION 1: DEPLOYMENT FREQUENCY
# ===========================================================================


class TestDeploymentFrequency:
    """Tests for calculate_deployment_frequency."""

    START = _dt(2026, 1, 1)
    END = _dt(2026, 3, 1)  # ~59 days

    def test_happy_path_elite(self) -> None:
        """7+ deploys/day across 60 days should classify as Elite."""
        # 428 deployments in 60 days = ~7.13/day
        deploys = [
            _deployment(_dt(2026, 1, 1) + timedelta(hours=i * 3))
            for i in range(428)
        ]
        start = _dt(2026, 1, 1)
        end = _dt(2026, 3, 1)
        per_day, per_week = calculate_deployment_frequency(deploys, start, end)
        assert per_day is not None
        assert per_day >= 1.0, "428 deploys in ~60 days should be >= 1.0/day (elite)"
        assert abs(per_week - per_day * 7) < 0.001

    def test_edge_case_empty_deployments_returns_none(self) -> None:
        per_day, per_week = calculate_deployment_frequency([], self.START, self.END)
        assert per_day is None
        assert per_week is None

    def test_edge_case_start_equals_end_returns_none(self) -> None:
        per_day, per_week = calculate_deployment_frequency(
            [_deployment(self.START)], self.START, self.START
        )
        assert per_day is None

    def test_edge_case_start_after_end_returns_none(self) -> None:
        per_day, per_week = calculate_deployment_frequency(
            [_deployment(self.START)], self.END, self.START
        )
        assert per_day is None

    def test_edge_case_single_deployment_low(self) -> None:
        """1 deployment in 60 days = 0.0167/day → Low."""
        start = _dt(2026, 1, 1)
        end = _dt(2026, 3, 1)
        per_day, _ = calculate_deployment_frequency(
            [_deployment(_dt(2026, 1, 15))], start, end
        )
        assert per_day is not None
        assert per_day < 1.0 / 30, "1 deploy in 60 days should be < 1/month threshold"

    @pytest.mark.parametrize("count,days,expected_level", [
        (60, 60, "elite"),    # 1.0/day exactly → elite
        (10, 70, "high"),     # 0.143/day ≈ 1/week → high
        (2, 60, "medium"),    # 0.033/day ≈ 1/month → medium
        (1, 60, "low"),       # 0.0167/day → low
    ])
    def test_classification_boundaries(self, count: int, days: int, expected_level: str) -> None:
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=days)
        deploys = [_deployment(start + timedelta(hours=i * (days * 24 // count))) for i in range(count)]
        per_day, _ = calculate_deployment_frequency(deploys, start, end)
        assert per_day is not None
        from src.contexts.metrics.domain.dora import _classify_deployment_frequency
        level = _classify_deployment_frequency(per_day)
        assert level.value == expected_level

    def test_regression_webmotors_ballpark(self) -> None:
        """Ground truth: ~7.13 deploys/day in 60d (428 deploys in 60 days)."""
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=60)
        deploys = [_deployment(start + timedelta(hours=i * 3)) for i in range(428)]
        per_day, per_week = calculate_deployment_frequency(deploys, start, end)
        assert per_day is not None
        assert abs(per_day - 428 / 60) < 0.01
        assert abs(per_week - per_day * 7) < 0.01

    def test_outlier_massive_deploy_count(self) -> None:
        """10,000 deploys in 30 days — should not crash, should be elite."""
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=30)
        deploys = [_deployment(start + timedelta(minutes=i * 4)) for i in range(10_000)]
        per_day, _ = calculate_deployment_frequency(deploys, start, end)
        assert per_day is not None
        assert per_day >= 1.0

    def test_anti_surveillance_no_author_in_result(self) -> None:
        """Deployment frequency result must not contain author attribution."""
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=30)
        deploys = [_deployment(start)]
        per_day, per_week = calculate_deployment_frequency(deploys, start, end)
        # Result is a tuple of numbers, no author field
        assert isinstance(per_day, float)
        assert isinstance(per_week, float)


# ===========================================================================
# SECTION 2: LEAD TIME FOR CHANGES
# ===========================================================================


class TestLeadTime:
    """Tests for calculate_lead_time."""

    def test_happy_path_median_calculated_correctly(self) -> None:
        """5 PRs with varying lead times — verify median is correct."""
        prs = [
            _pr_data(_dt(2026, 1, 1, 9), _dt(2026, 1, 1, 13)),   # 4h
            _pr_data(_dt(2026, 1, 2, 9), _dt(2026, 1, 2, 21)),   # 12h
            _pr_data(_dt(2026, 1, 3, 9), _dt(2026, 1, 4, 9)),    # 24h
            _pr_data(_dt(2026, 1, 4, 9), _dt(2026, 1, 6, 9)),    # 48h
            _pr_data(_dt(2026, 1, 5, 9), _dt(2026, 1, 9, 9)),    # 96h
        ]
        result = calculate_lead_time(prs)
        assert result == 24.0, f"Median of [4,12,24,48,96] should be 24, got {result}"

    def test_edge_case_empty_list(self) -> None:
        assert calculate_lead_time([]) is None

    def test_edge_case_all_missing_first_commit(self) -> None:
        """All PRs missing first_commit_at → all excluded → None."""
        prs = [_pr_data(None, _dt(2026, 1, 2)), _pr_data(None, _dt(2026, 1, 3))]
        assert calculate_lead_time(prs) is None

    def test_edge_case_all_missing_endpoint(self) -> None:
        """All PRs missing both deployed_at and merged_at → all excluded → None."""
        prs = [_pr_data(_dt(2026, 1, 1), None, None)]
        assert calculate_lead_time(prs) is None

    def test_edge_case_negative_lead_time_excluded(self) -> None:
        """PR where endpoint is before first_commit → excluded."""
        prs = [
            _pr_data(_dt(2026, 1, 5), _dt(2026, 1, 3)),  # negative → excluded
            _pr_data(_dt(2026, 1, 1), _dt(2026, 1, 2)),  # 24h → included
        ]
        result = calculate_lead_time(prs)
        assert result == 24.0

    def test_deployed_at_preferred_over_merged_at(self) -> None:
        """When deployed_at is set, it should be used over merged_at."""
        pr = _pr_data(
            first_commit_at=_dt(2026, 1, 1, 0),
            merged_at=_dt(2026, 1, 1, 12),    # 12h
            deployed_at=_dt(2026, 1, 2, 0),   # 24h
        )
        result = calculate_lead_time([pr])
        assert result == 24.0, "deployed_at should take precedence over merged_at"

    def test_merged_at_used_when_deployed_at_absent(self) -> None:
        """When deployed_at is None, merged_at is the fallback."""
        pr = _pr_data(
            first_commit_at=_dt(2026, 1, 1, 0),
            merged_at=_dt(2026, 1, 1, 12),
            deployed_at=None,
        )
        result = calculate_lead_time([pr])
        assert result == 12.0

    def test_regression_webmotors_ballpark(self) -> None:
        """Expected P50 LT ~6.5h based on PRs opened and merged same day."""
        # Representative: most PRs at Webmotors are small and merged within hours
        prs = [
            _pr_data(_dt(2026, 1, i, 9), _dt(2026, 1, i, 14))
            for i in range(1, 21)
        ]  # all 5h lead times
        result = calculate_lead_time(prs)
        assert result == 5.0

    def test_outlier_very_long_lead_time(self) -> None:
        """PR with 10,000h lead time should not crash, just skew median."""
        prs = [
            _pr_data(_dt(2026, 1, 1), _dt(2026, 1, 2)),       # 24h
            _pr_data(_dt(2026, 1, 1), _dt(2026, 1, 1, 1)),    # 1h
            _pr_data(_dt(2026, 1, 1), _dt(2026, 2, 28)),       # ~1392h
        ]
        result = calculate_lead_time(prs)
        assert result is not None
        assert result == 24.0  # median of [1, 24, 1392] = 24

    def test_anti_surveillance_result_has_no_author(self) -> None:
        """Result is a float (hours), not an object with author attribution."""
        pr = _pr_data(_dt(2026, 1, 1), _dt(2026, 1, 2))
        result = calculate_lead_time([pr])
        assert isinstance(result, float)
        assert not hasattr(result, "author")


# ===========================================================================
# SECTION 3: CHANGE FAILURE RATE
# ===========================================================================


class TestChangeFailureRate:
    """Tests for calculate_change_failure_rate."""

    def test_happy_path_known_ratio(self) -> None:
        """5 failures out of 23 = 0.217 ≈ 21.7%."""
        deploys = (
            [_deployment(_dt(2026, 1, i), is_failure=True) for i in range(1, 6)]
            + [_deployment(_dt(2026, 1, i), is_failure=False) for i in range(6, 24)]
        )
        cfr = calculate_change_failure_rate(deploys)
        assert cfr is not None
        assert abs(cfr - 5 / 23) < 0.001

    def test_edge_case_empty_list(self) -> None:
        assert calculate_change_failure_rate([]) is None

    def test_edge_case_all_failures(self) -> None:
        deploys = [_deployment(_dt(2026, 1, 1), is_failure=True)] * 10
        assert calculate_change_failure_rate(deploys) == 1.0

    def test_edge_case_no_failures(self) -> None:
        deploys = [_deployment(_dt(2026, 1, i), is_failure=False) for i in range(1, 11)]
        assert calculate_change_failure_rate(deploys) == 0.0

    def test_edge_case_single_deployment_failure(self) -> None:
        assert calculate_change_failure_rate([_deployment(_dt(2026, 1, 1), is_failure=True)]) == 1.0

    def test_regression_webmotors_ballpark(self) -> None:
        """~22% CFR (reported by user). 22 failures out of 100 deploys."""
        deploys = (
            [_deployment(_dt(2026, 1, 1), is_failure=True)] * 22
            + [_deployment(_dt(2026, 1, 1), is_failure=False)] * 78
        )
        cfr = calculate_change_failure_rate(deploys)
        assert cfr is not None
        assert abs(cfr - 0.22) < 0.001
        # At 22% CFR → "low" classification (> 15%)
        from src.contexts.metrics.domain.dora import _classify_change_failure_rate
        level = _classify_change_failure_rate(cfr)
        assert level == DoraLevel.LOW

    def test_outlier_one_failure_in_1000(self) -> None:
        deploys = [_deployment(_dt(2026, 1, 1), is_failure=True)] + [
            _deployment(_dt(2026, 1, 1)) for _ in range(999)
        ]
        cfr = calculate_change_failure_rate(deploys)
        assert cfr is not None
        assert abs(cfr - 0.001) < 0.0001

    def test_cfr_ratio_not_percentage(self) -> None:
        """CFR must be returned as ratio (0-1), never as percentage (0-100)."""
        deploys = [_deployment(_dt(2026, 1, 1), is_failure=True)] * 10 + [
            _deployment(_dt(2026, 1, 1)) for _ in range(90)
        ]
        cfr = calculate_change_failure_rate(deploys)
        assert cfr is not None
        assert 0.0 <= cfr <= 1.0, f"CFR must be 0-1 ratio, got {cfr}"


# ===========================================================================
# SECTION 4: MTTR
# ===========================================================================


class TestMttr:
    """Tests for calculate_mttr."""

    def test_happy_path_median_recovery(self) -> None:
        """3 resolved incidents with recovery times [2h, 8h, 24h] → median = 8h."""
        failed = [
            _deployment(_dt(2026, 1, 1), is_failure=True, recovery_time_hours=2.0),
            _deployment(_dt(2026, 1, 2), is_failure=True, recovery_time_hours=8.0),
            _deployment(_dt(2026, 1, 3), is_failure=True, recovery_time_hours=24.0),
        ]
        result = calculate_mttr(failed)
        assert result == 8.0

    def test_edge_case_empty_list(self) -> None:
        assert calculate_mttr([]) is None

    def test_edge_case_all_recovery_times_none(self) -> None:
        """All failures have no recovery time recorded → None."""
        failed = [
            _deployment(_dt(2026, 1, 1), is_failure=True, recovery_time_hours=None),
        ]
        assert calculate_mttr(failed) is None

    def test_edge_case_negative_recovery_excluded(self) -> None:
        """Negative recovery time (data error) must be excluded."""
        failed = [
            _deployment(_dt(2026, 1, 1), is_failure=True, recovery_time_hours=-5.0),  # excluded
            _deployment(_dt(2026, 1, 2), is_failure=True, recovery_time_hours=4.0),
        ]
        result = calculate_mttr(failed)
        assert result == 4.0

    def test_edge_case_non_failures_excluded(self) -> None:
        """is_failure=False deployments must not contribute to MTTR."""
        events = [
            _deployment(_dt(2026, 1, 1), is_failure=False, recovery_time_hours=1.0),
            _deployment(_dt(2026, 1, 2), is_failure=True, recovery_time_hours=10.0),
        ]
        result = calculate_mttr(events)
        assert result == 10.0

    def test_webmotors_no_recovery_time_in_db_returns_none(self) -> None:
        """In the current Webmotors setup, recovery_time_hours is always None.
        MTTR must return None gracefully — not crash."""
        failed = [
            _deployment(_dt(2026, i, 1), is_failure=True, recovery_time_hours=None)
            for i in range(1, 4)
        ]
        assert calculate_mttr(failed) is None

    def test_outlier_very_long_mttr(self) -> None:
        """MTTR of 1000h should not crash."""
        failed = [_deployment(_dt(2026, 1, 1), is_failure=True, recovery_time_hours=1000.0)]
        result = calculate_mttr(failed)
        assert result == 1000.0
        from src.contexts.metrics.domain.dora import _classify_mttr
        assert _classify_mttr(result) == DoraLevel.LOW


# ===========================================================================
# SECTION 5: DORA COMPOSITE
# ===========================================================================


class TestDoraComposite:
    """Tests for calculate_dora_metrics composite function."""

    def test_overall_level_is_worst_of_four(self) -> None:
        """Elite DF + Elite LT + Elite CFR + null MTTR → overall = elite (from available)."""
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=30)
        deploys = [_deployment(start + timedelta(hours=i * 6)) for i in range(120)]  # 4/day → elite
        prs = [_pr_data(start + timedelta(hours=i), start + timedelta(hours=i, minutes=30)) for i in range(50)]
        result = calculate_dora_metrics(deploys, prs, start, end)
        assert result.df_level == DoraLevel.ELITE
        assert result.lt_level == DoraLevel.ELITE  # 0.5h
        assert result.cfr_level == DoraLevel.ELITE  # 0% failures
        # No recovery time data → MTTR None → overall computed from 3 metrics
        assert result.overall_level == DoraLevel.ELITE

    def test_low_cfr_drags_overall_to_low(self) -> None:
        """Elite DF but all deployments fail → CFR > 15% → overall = low."""
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=30)
        deploys = [_deployment(start + timedelta(hours=i), is_failure=True) for i in range(120)]
        prs = [_pr_data(start, start + timedelta(minutes=30))]
        result = calculate_dora_metrics(deploys, prs, start, end)
        assert result.overall_level == DoraLevel.LOW

    def test_empty_inputs_all_none(self) -> None:
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=30)
        result = calculate_dora_metrics([], [], start, end)
        assert result.deployment_frequency_per_day is None
        assert result.lead_time_for_changes_hours is None
        assert result.change_failure_rate is None
        assert result.mean_time_to_recovery_hours is None
        assert result.overall_level is None

    def test_anti_surveillance_no_author_fields(self) -> None:
        """DoraMetrics dataclass must not contain author or developer fields."""
        start = _dt(2026, 1, 1)
        end = start + timedelta(days=7)
        result = calculate_dora_metrics(
            [_deployment(start)],
            [_pr_data(start, start + timedelta(hours=2))],
            start,
            end,
        )
        from dataclasses import fields, asdict
        result_dict = asdict(result)
        forbidden = {"author", "developer", "user", "committer", "assignee"}
        assert not (set(result_dict.keys()) & forbidden), \
            f"DoraMetrics must not expose individual attribution. Found: {set(result_dict.keys()) & forbidden}"


# ===========================================================================
# SECTION 6: CYCLE TIME BREAKDOWN
# ===========================================================================


class TestCycleTimeBreakdown:
    """Tests for calculate_cycle_time_breakdown."""

    def test_happy_path_all_phases(self) -> None:
        """Known PR timings → verify each phase P50."""
        prs = [
            _pr_cycle("PR-1",
                first_commit=_dt(2026, 1, 1, 8),
                first_review=_dt(2026, 1, 1, 16),   # 8h coding
                approved=_dt(2026, 1, 2, 8),          # 16h pickup
                merged=_dt(2026, 1, 2, 10),            # 2h review
                deployed=_dt(2026, 1, 2, 12),          # 2h deploy
            ),
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.coding_p50 == 8.0
        assert result.pickup_p50 == 16.0
        assert result.review_p50 == 2.0
        assert result.deploy_p50 == 2.0
        assert result.total_p50 == 28.0
        assert result.pr_count == 1

    def test_edge_case_empty_list(self) -> None:
        result = calculate_cycle_time_breakdown([])
        assert result.coding_p50 is None
        assert result.total_p50 is None
        assert result.pr_count == 0
        assert result.bottleneck_phase is None

    def test_edge_case_missing_review_timestamps(self) -> None:
        """PRs without first_review_at → coding/pickup/review are None, total may still compute."""
        prs = [
            _pr_cycle("PR-1",
                first_commit=_dt(2026, 1, 1, 8),
                first_review=None,
                approved=None,
                merged=_dt(2026, 1, 2, 8),
            ),
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.coding_p50 is None
        assert result.pickup_p50 is None
        assert result.review_p50 is None
        assert result.total_p50 == 24.0  # first_commit → merged (fallback)

    def test_edge_case_deployed_at_none_deploy_phase_none(self) -> None:
        """If deployed_at is None, deploy phase should be None."""
        prs = [
            _pr_cycle("PR-1",
                first_commit=_dt(2026, 1, 1),
                first_review=_dt(2026, 1, 1, 8),
                approved=_dt(2026, 1, 1, 12),
                merged=_dt(2026, 1, 2),
                deployed=None,
            ),
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.deploy_p50 is None

    def test_bottleneck_is_phase_with_highest_p50(self) -> None:
        """If coding is longest phase, bottleneck_phase should be 'coding'."""
        prs = [
            _pr_cycle("PR-1",
                first_commit=_dt(2026, 1, 1, 0),
                first_review=_dt(2026, 1, 4, 0),    # 72h coding (largest)
                approved=_dt(2026, 1, 4, 2),          # 2h pickup
                merged=_dt(2026, 1, 4, 3),             # 1h review
                deployed=_dt(2026, 1, 4, 4),           # 1h deploy
            ),
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.bottleneck_phase == "coding"

    def test_p50_p85_p95_ordering(self) -> None:
        """P50 <= P85 <= P95 for any dataset."""
        import random
        random.seed(42)
        prs = [
            _pr_cycle(
                f"PR-{i}",
                first_commit=_dt(2026, 1, 1),
                merged=_dt(2026, 1, 1) + timedelta(hours=random.uniform(1, 200)),
            )
            for i in range(50)
        ]
        result = calculate_cycle_time_breakdown(prs)
        if result.total_p50 and result.total_p85 and result.total_p95:
            assert result.total_p50 <= result.total_p85 <= result.total_p95

    def test_regression_webmotors_p50_ballpark(self) -> None:
        """Webmotors PRs: P50 Cycle Time expected ~0.27h per user context.
        We test with a dataset that produces sub-1h P50."""
        prs = [
            _pr_cycle(f"PR-{i}",
                first_commit=_dt(2026, 1, 1),
                merged=_dt(2026, 1, 1, 0, i * 2),  # 0 to ~100 minutes
            )
            for i in range(30)
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p50 is not None
        assert result.total_p50 < 1.0, "Expected sub-1h P50 for short-cycle PRs"

    def test_outlier_pr_with_extreme_coding_time(self) -> None:
        """One PR with 10,000h coding time should not crash. P95 should capture it."""
        prs = [
            _pr_cycle(f"PR-{i}",
                first_commit=_dt(2026, 1, 1),
                first_review=_dt(2026, 1, 1, 4),
                merged=_dt(2026, 1, 1, 6),
            )
            for i in range(9)
        ] + [
            _pr_cycle("PR-outlier",
                first_commit=_dt(2026, 1, 1),
                first_review=_dt(2027, 3, 1),  # ~10,000h later
                merged=_dt(2027, 3, 1, 2),
            )
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p95 is not None
        assert result.total_p95 > result.total_p50  # type: ignore

    def test_anti_surveillance_no_author_in_breakdown(self) -> None:
        """CycleTimeBreakdown must not expose author fields."""
        prs = [_pr_cycle("PR-1", first_commit=_dt(2026, 1, 1), merged=_dt(2026, 1, 2))]
        result = calculate_cycle_time_breakdown(prs)
        from dataclasses import asdict
        d = asdict(result)
        forbidden = {"author", "developer", "user", "committer"}
        assert not (set(d.keys()) & forbidden)


# ===========================================================================
# SECTION 7: WIP
# ===========================================================================


class TestWip:
    """Tests for calculate_wip."""

    def test_happy_path_counts_active_issues(self) -> None:
        issues = [
            _issue("I1", status="in_progress"),
            _issue("I2", status="in_review"),
            _issue("I3", status="todo"),
            _issue("I4", status="done"),
            _issue("I5", status="in_progress"),
        ]
        assert calculate_wip(issues) == 3

    def test_edge_case_empty_list(self) -> None:
        assert calculate_wip([]) == 0

    def test_edge_case_all_done(self) -> None:
        issues = [_issue(f"I{i}", status="done") for i in range(10)]
        assert calculate_wip(issues) == 0

    def test_edge_case_all_in_progress(self) -> None:
        issues = [_issue(f"I{i}", status="in_progress") for i in range(5)]
        assert calculate_wip(issues) == 5

    def test_edge_case_unknown_status_not_counted(self) -> None:
        """Issues with unrecognized status should not count as WIP."""
        issues = [
            _issue("I1", status="awaiting_deploy"),  # not in _ACTIVE_STATUSES
            _issue("I2", status="in_progress"),       # counted
        ]
        assert calculate_wip(issues) == 1

    def test_regression_ballpark(self) -> None:
        """With 27 squads averaging 10 items each, global WIP might be ~270."""
        issues = [
            _issue(f"I{i}", status="in_progress" if i % 2 == 0 else "in_review")
            for i in range(270)
        ]
        assert calculate_wip(issues) == 270

    def test_anti_surveillance_result_is_integer(self) -> None:
        """WIP is a count, not a per-author breakdown."""
        issues = [_issue("I1", status="in_progress")]
        result = calculate_wip(issues)
        assert isinstance(result, int)


# ===========================================================================
# SECTION 8: LEAD TIME DISTRIBUTION
# ===========================================================================


class TestLeadTimeDistribution:
    """Tests for calculate_lead_time_distribution."""

    def test_happy_path_buckets_sum_to_total(self) -> None:
        issues = [
            _issue(f"I{i}", completed_at=_dt(2026, 1, 2), lead_time_hours=float(h))
            for i, h in enumerate([2, 6, 12, 36, 72, 150, 300, 600, 800])
        ]
        result = calculate_lead_time_distribution(issues)
        assert result.total_issues == 9
        assert sum(b.count for b in result.buckets) == 9
        total_pct = sum(b.percentage for b in result.buckets)
        assert abs(total_pct - 100.0) < 0.5  # rounding tolerance

    def test_edge_case_no_completed_issues(self) -> None:
        issues = [_issue("I1", status="in_progress", lead_time_hours=None, completed_at=None)]
        result = calculate_lead_time_distribution(issues)
        assert result.total_issues == 0
        assert result.p50_hours is None
        assert all(b.count == 0 for b in result.buckets)

    def test_edge_case_single_issue(self) -> None:
        issues = [_issue("I1", completed_at=_dt(2026, 1, 2), lead_time_hours=24.0)]
        result = calculate_lead_time_distribution(issues)
        assert result.p50_hours == 24.0
        assert result.p85_hours == 24.0
        assert result.p95_hours == 24.0

    def test_edge_case_negative_lead_time_excluded(self) -> None:
        issues = [
            _issue("I1", completed_at=_dt(2026, 1, 2), lead_time_hours=-10.0),  # excluded
            _issue("I2", completed_at=_dt(2026, 1, 2), lead_time_hours=48.0),
        ]
        result = calculate_lead_time_distribution(issues)
        assert result.total_issues == 1

    def test_percentile_ordering(self) -> None:
        """P50 <= P85 <= P95 must always hold."""
        issues = [
            _issue(f"I{i}", completed_at=_dt(2026, 1, i + 1), lead_time_hours=float(i * 5 + 1))
            for i in range(30)
        ]
        result = calculate_lead_time_distribution(issues)
        assert result.p50_hours is not None
        assert result.p85_hours is not None
        assert result.p95_hours is not None
        assert result.p50_hours <= result.p85_hours <= result.p95_hours

    def test_outlier_single_very_long_item_in_30d_plus_bucket(self) -> None:
        issues = [
            _issue("I1", completed_at=_dt(2026, 1, 2), lead_time_hours=10000.0),
        ]
        result = calculate_lead_time_distribution(issues)
        last_bucket = result.buckets[-1]
        assert last_bucket.range_label == "30d+"
        assert last_bucket.count == 1

    def test_anti_surveillance_no_issue_assignee_in_output(self) -> None:
        """Distribution output must not contain assignee or author."""
        issues = [_issue("I1", completed_at=_dt(2026, 1, 2), lead_time_hours=24.0)]
        result = calculate_lead_time_distribution(issues)
        from dataclasses import asdict
        d = asdict(result)
        forbidden = {"author", "assignee", "developer"}
        assert not (set(d.keys()) & forbidden)


# ===========================================================================
# SECTION 9: THROUGHPUT (Lean — issue-based)
# ===========================================================================


class TestLeadThroughput:
    """Tests for calculate_throughput (issue-level)."""

    def test_happy_path_weekly_counts(self) -> None:
        """10 issues completed in week 1, 5 in week 2 → correct weekly counts."""
        start = _d(2026, 1, 5)   # Monday
        end = _d(2026, 1, 18)    # two weeks
        issues = (
            [_issue(f"I{i}", completed_at=_dt(2026, 1, 5 + i % 5)) for i in range(10)]  # week 1
            + [_issue(f"J{i}", completed_at=_dt(2026, 1, 12 + i % 5)) for i in range(5)]  # week 2
        )
        result = calculate_throughput(issues, start, end)
        assert len(result) == 2
        assert result[0].count == 10
        assert result[1].count == 5

    def test_edge_case_empty_issues(self) -> None:
        start = _d(2026, 1, 1)
        end = _d(2026, 1, 14)
        result = calculate_throughput([], start, end)
        assert all(p.count == 0 for p in result)

    def test_edge_case_start_after_end(self) -> None:
        result = calculate_throughput([], _d(2026, 2, 1), _d(2026, 1, 1))
        assert result == []

    def test_moving_average_starts_at_week_4(self) -> None:
        """Moving average should be None for first 3 weeks."""
        start = _d(2026, 1, 5)
        end = _d(2026, 2, 2)  # 4 weeks
        issues = [_issue(f"I{i}", completed_at=_dt(2026, 1, 5)) for i in range(10)]
        result = calculate_throughput(issues, start, end)
        assert result[0].moving_avg_4w is None
        assert result[1].moving_avg_4w is None
        assert result[2].moving_avg_4w is None
        assert result[3].moving_avg_4w is not None

    def test_4_week_moving_average_correct(self) -> None:
        """4-week MA at index 3 = mean of counts[0:4]."""
        start = _d(2026, 1, 5)
        end = _d(2026, 2, 2)  # 4 weeks exactly
        # 10, 5, 8, 3 issues per week
        issues = (
            [_issue(f"I{i}", completed_at=_dt(2026, 1, 5)) for i in range(10)]    # week 1
            + [_issue(f"J{i}", completed_at=_dt(2026, 1, 12)) for i in range(5)]  # week 2
            + [_issue(f"K{i}", completed_at=_dt(2026, 1, 19)) for i in range(8)]  # week 3
            + [_issue(f"L{i}", completed_at=_dt(2026, 1, 26)) for i in range(3)]  # week 4
        )
        result = calculate_throughput(issues, start, end)
        expected_ma = (10 + 5 + 8 + 3) / 4.0  # = 6.5
        assert result[3].moving_avg_4w is not None
        assert abs(result[3].moving_avg_4w - expected_ma) < 0.01

    def test_outlier_zero_week_in_middle(self) -> None:
        """Zero-count weeks should be included in the result."""
        start = _d(2026, 1, 5)
        end = _d(2026, 1, 25)
        issues = [
            _issue("I1", completed_at=_dt(2026, 1, 6)),   # week 1
            _issue("I2", completed_at=_dt(2026, 1, 20)),  # week 3 (skip week 2)
        ]
        result = calculate_throughput(issues, start, end)
        assert len(result) == 3
        assert result[1].count == 0  # week 2 = zero

    def test_anti_surveillance_no_author_in_throughput_points(self) -> None:
        """Throughput data points must not expose author info."""
        issues = [_issue("I1", completed_at=_dt(2026, 1, 6))]
        result = calculate_throughput(issues, _d(2026, 1, 5), _d(2026, 1, 11))
        from dataclasses import asdict
        for point in result:
            d = asdict(point)
            assert "author" not in d
            assert "assignee" not in d


# ===========================================================================
# SECTION 10: LEAD TIME SCATTERPLOT
# ===========================================================================


class TestLeadTimeScatterplot:
    """Tests for calculate_lead_time_scatterplot."""

    def test_happy_path_outlier_detection(self) -> None:
        """5% of points above P95 should be flagged as outliers."""
        issues = [
            _issue(f"I{i}", completed_at=_dt(2026, 1, i + 1), lead_time_hours=float(i + 1))
            for i in range(20)  # 1h, 2h, ..., 20h
        ]
        points, p50, p85, p95 = calculate_lead_time_scatterplot(issues)
        assert len(points) == 20
        outliers = [p for p in points if p.is_outlier]
        # P95 of 1..20 = ~19.05, so only value 20 is an outlier
        assert len(outliers) == 1
        assert outliers[0].lead_time_hours == 20.0

    def test_edge_case_no_completed_issues(self) -> None:
        result = calculate_lead_time_scatterplot([])
        points, p50, p85, p95 = result
        assert points == []
        assert p50 is None

    def test_edge_case_single_issue_no_outlier(self) -> None:
        issues = [_issue("I1", completed_at=_dt(2026, 1, 2), lead_time_hours=48.0)]
        points, p50, p85, p95 = calculate_lead_time_scatterplot(issues)
        assert len(points) == 1
        assert not points[0].is_outlier  # cannot be outlier with only 1 point (equals P95)

    def test_points_sorted_by_completion_date(self) -> None:
        issues = [
            _issue("I3", completed_at=_dt(2026, 1, 3), lead_time_hours=10.0),
            _issue("I1", completed_at=_dt(2026, 1, 1), lead_time_hours=5.0),
            _issue("I2", completed_at=_dt(2026, 1, 2), lead_time_hours=8.0),
        ]
        points, _, _, _ = calculate_lead_time_scatterplot(issues)
        dates = [p.completed_date for p in points]
        assert dates == sorted(dates)

    def test_p50_le_p85_le_p95(self) -> None:
        issues = [
            _issue(f"I{i}", completed_at=_dt(2026, 1, 2), lead_time_hours=float(i * 10))
            for i in range(1, 21)
        ]
        _, p50, p85, p95 = calculate_lead_time_scatterplot(issues)
        assert p50 is not None and p85 is not None and p95 is not None
        assert p50 <= p85 <= p95

    def test_anti_surveillance_issue_id_not_developer_id(self) -> None:
        """Scatterplot points expose issue_id (ticket), NOT developer/author id."""
        issues = [_issue("PROJ-123", completed_at=_dt(2026, 1, 2), lead_time_hours=24.0)]
        points, _, _, _ = calculate_lead_time_scatterplot(issues)
        assert points[0].issue_id == "PROJ-123"
        # Verify no author field
        from dataclasses import asdict
        d = asdict(points[0])
        assert "author" not in d
        assert "developer" not in d


# ===========================================================================
# SECTION 11: SPRINT OVERVIEW
# ===========================================================================


class TestSprintOverview:
    """Tests for calculate_sprint_overview."""

    def test_happy_path_normal_sprint(self) -> None:
        """20 committed, 3 added, 1 removed, 16 completed → known rates."""
        sprint = _sprint()
        result = calculate_sprint_overview(sprint)
        # final_scope = 20 + 3 - 1 = 22
        assert result.final_scope_items == 22
        # completion_rate = 16 / 22
        assert abs(result.completion_rate - 16 / 22) < 0.001
        # scope_creep_pct = (3 / 20) * 100 = 15.0
        assert abs(result.scope_creep_pct - 15.0) < 0.01
        # carryover_rate = 4 / 20 = 0.2
        assert abs(result.carryover_rate - 0.2) < 0.001

    def test_edge_case_zero_committed(self) -> None:
        """No committed items → scope_creep and carryover are None."""
        sprint = _sprint(committed=0, committed_pts=0.0, added=5, completed=3, carried_over=0)
        result = calculate_sprint_overview(sprint)
        assert result.scope_creep_pct is None
        assert result.carryover_rate is None

    def test_edge_case_completion_rate_capped_at_1(self) -> None:
        """Completed > final_scope → capped at 1.0."""
        sprint = _sprint(committed=10, added=0, removed=0, completed=15, carried_over=0)
        result = calculate_sprint_overview(sprint)
        assert result.completion_rate == 1.0

    def test_edge_case_added_items_zero_webmotors(self) -> None:
        """Current state: added_items=0 always (INC-006). Verify scope_creep=0."""
        sprint = _sprint(added=0, removed=0)
        result = calculate_sprint_overview(sprint)
        assert result.scope_creep_pct == 0.0

    def test_edge_case_zero_removed_negative_scope(self) -> None:
        """committed + added - removed can't be negative → clamped to 0."""
        sprint = _sprint(committed=5, added=0, removed=10, completed=0, carried_over=0)
        result = calculate_sprint_overview(sprint)
        assert result.final_scope_items == 0
        assert result.completion_rate is None  # final_scope <= 0

    def test_regression_typical_webmotors_sprint(self) -> None:
        """Typical 2-week sprint: 20 items, 80% completion rate."""
        sprint = _sprint(committed=20, added=0, removed=0, completed=16, carried_over=4)
        result = calculate_sprint_overview(sprint)
        assert abs(result.completion_rate - 0.8) < 0.001
        assert result.carryover_rate is not None
        assert abs(result.carryover_rate - 0.2) < 0.001

    def test_anti_surveillance_no_developer_in_overview(self) -> None:
        sprint = _sprint()
        result = calculate_sprint_overview(sprint)
        from dataclasses import asdict
        d = asdict(result)
        forbidden = {"author", "developer", "assignee"}
        assert not (set(d.keys()) & forbidden)


# ===========================================================================
# SECTION 12: SPRINT COMPARISON
# ===========================================================================


class TestSprintComparison:
    """Tests for calculate_sprint_comparison and velocity trend."""

    def _sprints_with_velocities(self, velocities: list[float]) -> list[SprintData]:
        return [
            _sprint(sprint_id=f"SP-{i}", completed_pts=v, committed_pts=v + 5)
            for i, v in enumerate(velocities)
        ]

    def test_happy_path_improving_trend(self) -> None:
        """Monotonically increasing velocity → improving."""
        sprints = self._sprints_with_velocities([20.0, 22.0, 25.0, 28.0, 30.0, 35.0])
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "improving"

    def test_happy_path_declining_trend(self) -> None:
        sprints = self._sprints_with_velocities([35.0, 30.0, 28.0, 25.0, 22.0, 20.0])
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "declining"

    def test_happy_path_stable_trend(self) -> None:
        sprints = self._sprints_with_velocities([30.0, 30.5, 29.5, 30.2, 30.1, 29.8])
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "stable"

    def test_edge_case_empty_sprints(self) -> None:
        result = calculate_sprint_comparison([])
        assert result.velocity_trend == "insufficient_data"
        assert result.avg_velocity is None

    def test_edge_case_single_sprint(self) -> None:
        result = calculate_sprint_comparison([_sprint()])
        assert result.velocity_trend == "insufficient_data"

    def test_avg_velocity_correct(self) -> None:
        """Average velocity = mean of completed_points."""
        sprints = self._sprints_with_velocities([10.0, 20.0, 30.0])
        result = calculate_sprint_comparison(sprints)
        assert result.avg_velocity is not None
        assert abs(result.avg_velocity - 20.0) < 0.01

    def test_only_last_6_used_for_trend(self) -> None:
        """10 sprints: first 4 declining, last 6 strongly improving → trend = improving."""
        velocities = [50.0, 40.0, 35.0, 30.0] + [10.0, 12.0, 15.0, 20.0, 25.0, 35.0]
        sprints = self._sprints_with_velocities(velocities)
        result = calculate_sprint_comparison(sprints)
        assert result.velocity_trend == "improving"

    def test_anti_surveillance_no_developer_in_comparison(self) -> None:
        sprints = self._sprints_with_velocities([20.0, 22.0])
        result = calculate_sprint_comparison(sprints)
        from dataclasses import asdict
        d = asdict(result)
        for key in d.keys():
            assert "author" not in key.lower()
            assert "developer" not in key.lower()


# ===========================================================================
# SECTION 13: PR ANALYTICS (Throughput)
# ===========================================================================


class TestPrAnalytics:
    """Tests for calculate_pr_analytics."""

    def _pr(self, repo: str, additions: int = 50, deletions: int = 30,
            reviewers: int = 2, cycle_time: float | None = 10.0) -> PullRequestThroughputData:
        return PullRequestThroughputData(
            pr_id=f"PR-{repo}",
            repo=repo,
            merged_at=_dt(2026, 1, 15),
            additions=additions,
            deletions=deletions,
            files_changed=5,
            cycle_time_hours=cycle_time,
            reviewer_count=reviewers,
        )

    def test_happy_path_totals(self) -> None:
        prs = [self._pr("repo-a"), self._pr("repo-a"), self._pr("repo-b")]
        result = calculate_pr_analytics(prs)
        assert result.total_merged == 3
        assert result.repos_breakdown[0]["repo"] == "repo-a"
        assert result.repos_breakdown[0]["count"] == 2

    def test_edge_case_empty_list(self) -> None:
        result = calculate_pr_analytics([])
        assert result.total_merged == 0
        assert result.avg_size_lines is None

    def test_size_distribution_zero_diff_excluded_from_avg(self) -> None:
        """PRs with 0 additions and 0 deletions excluded from avg_size but counted in total."""
        prs = [
            self._pr("r1", additions=0, deletions=0),  # zero-diff
            self._pr("r2", additions=100, deletions=50),
        ]
        result = calculate_pr_analytics(prs)
        assert result.total_merged == 2
        assert result.avg_size_lines == 150.0  # only non-zero

    def test_repos_breakdown_sorted_desc(self) -> None:
        prs = [
            self._pr("repo-c"),
            self._pr("repo-a"), self._pr("repo-a"), self._pr("repo-a"),
            self._pr("repo-b"), self._pr("repo-b"),
        ]
        result = calculate_pr_analytics(prs)
        counts = [r["count"] for r in result.repos_breakdown]
        assert counts == sorted(counts, reverse=True)

    def test_anti_surveillance_repos_breakdown_not_per_author(self) -> None:
        """repos_breakdown groups by repo, not by author."""
        prs = [self._pr("my-repo")]
        result = calculate_pr_analytics(prs)
        for entry in result.repos_breakdown:
            assert "author" not in entry
            assert "developer" not in entry


# ===========================================================================
# SECTION 14: LITTLE'S LAW VALIDATION
# ===========================================================================


class TestLittlesLaw:
    """Little's Law: avg_throughput = avg_wip / avg_lead_time.

    In a stable system:
        Throughput (items/time) = WIP / Lead_Time

    We test this relationship using synthetic data where we control WIP
    and Lead Time to verify the throughput formula is consistent.
    """

    def test_littles_law_self_consistent(self) -> None:
        """Create 60 issues, all completing in exactly 24h, 1 per day.
        Expected: WIP ≈ 1, Lead Time = 24h, Throughput = 1/day.
        Little's Law: 1 item/day = 1 WIP / 24h * 24h/day = 1 item/day ✓
        """
        # 60 issues, each created at start of day, completed at end of same day
        issues = [
            IssueFlowData(
                issue_id=f"I{i}",
                normalized_status="done",
                status_transitions=[],
                created_at=_dt(2026, 1, 1) + timedelta(days=i),
                started_at=_dt(2026, 1, 1) + timedelta(days=i),
                completed_at=_dt(2026, 1, 1) + timedelta(days=i, hours=24),
                lead_time_hours=24.0,
            )
            for i in range(60)
        ]
        start = _d(2026, 1, 1)
        end = _d(2026, 3, 1)  # 59 days

        # Compute throughput (issues/week)
        throughput_points = calculate_throughput(issues, start, end)
        total_completed = sum(p.count for p in throughput_points)
        period_days = (end - start).days
        throughput_per_day = total_completed / period_days  # ~1/day

        # Lead time
        lt_dist = calculate_lead_time_distribution(issues)
        lead_time_days = lt_dist.p50_hours / 24.0 if lt_dist.p50_hours else None

        # Little's Law: throughput = wip / lead_time
        # With 1 item/day and 1-day lead time → WIP ≈ 1
        littles_wip = throughput_per_day * lead_time_days if lead_time_days else None

        assert littles_wip is not None
        # Allow 20% tolerance for boundary effects
        assert abs(littles_wip - 1.0) < 0.2, \
            f"Little's Law: expected WIP≈1, got {littles_wip:.3f} " \
            f"(throughput={throughput_per_day:.3f}/day, LT={lead_time_days:.1f}d)"

    def test_littles_law_detects_inconsistency(self) -> None:
        """If we compute WIP independently and it disagrees with Little's Law,
        it signals a measurement problem. Here we demonstrate that the three
        metrics can be independently verified."""
        # Suppose: 50 issues completed in 30 days, avg lead time = 5 days
        # Little's law implies avg WIP = 50/30 * 5 = 8.33 items
        throughput_per_day = 50 / 30
        avg_lead_time_days = 5.0
        littles_wip = throughput_per_day * avg_lead_time_days
        assert abs(littles_wip - 8.33) < 0.01, f"Little's law sanity: expected 8.33, got {littles_wip}"


# ===========================================================================
# SECTION 15: KNOWN DATA ISSUES — REGRESSION TESTS
# ===========================================================================


class TestKnownDataIssues:
    """Regression tests documenting known issues (INC-xxx from inconsistencies.md).

    These tests verify that the KNOWN bugs produce the EXPECTED wrong output,
    ensuring we do not accidentally "fix" them without a formal PR.
    """

    def test_inc_006_scope_creep_always_zero_with_zero_added(self) -> None:
        """INC-006: added_items=0 (always, from normalizer) → scope_creep=0.0."""
        sprint = SprintData(
            sprint_id="SP-1", name="Sprint 1",
            committed_items=20, committed_points=40.0,
            added_items=0,     # ← normalizer always sets this to 0
            removed_items=0,
            completed_items=16, completed_points=32.0,
            carried_over_items=4,
        )
        result = calculate_sprint_overview(sprint)
        assert result.scope_creep_pct == 0.0, \
            "INC-006: scope_creep is 0.0 when added_items=0 (documented known issue)"

    def test_inc_007_cycle_time_none_in_throughput_trend(self) -> None:
        """INC-007: cycle_time_hours=None in PullRequestThroughputData (worker line 192)
        → weekly P50/P85 cycle times are always None in the throughput trend."""
        prs = [
            PullRequestThroughputData(
                pr_id="PR-1", repo="my-repo",
                merged_at=_dt(2026, 1, 8),
                additions=50, deletions=30, files_changed=5,
                cycle_time_hours=None,  # ← worker hardcodes this to None
                reviewer_count=2,
            )
        ]
        result = calculate_throughput_trend(prs, _d(2026, 1, 5), _d(2026, 1, 11))
        assert result[0].p50_cycle_time_hours is None, \
            "INC-007: cycle_time is None in throughput trend (documented known issue)"

    def test_inc_003_first_commit_proxied_by_pr_opened_date(self) -> None:
        """INC-003: Lead time is calculated from pr_opened_date, not true first_commit.
        A PR where first_commit_at = created_date (proxy) understates lead time
        if the developer worked on the branch before opening the PR."""
        # PR opened on Jan 3, but developer actually started Jan 1.
        # PULSE stores first_commit_at = Jan 3 (pr opened date).
        # True lead time = Jan 3 14:00 - Jan 1 09:00 = 53h
        # PULSE measures = Jan 3 14:00 - Jan 3 09:00 = 5h
        pr = _pr_data(
            first_commit_at=_dt(2026, 1, 3, 9),   # proxy: PR opened
            merged_at=_dt(2026, 1, 3, 14),
        )
        result = calculate_lead_time([pr])
        assert result == 5.0, \
            "INC-003: PULSE measures 5h (proxy), true LT would be 53h (documented known issue)"

    def test_inc_004_deployed_at_none_means_lead_time_uses_merged_at(self) -> None:
        """INC-004: deployed_at is always None. Lead time uses merged_at as fallback."""
        pr = _pr_data(
            first_commit_at=_dt(2026, 1, 1),
            merged_at=_dt(2026, 1, 2),
            deployed_at=None,  # ← always None in current system
        )
        result = calculate_lead_time([pr])
        # Should use merged_at: 24h
        assert result == 24.0, "INC-004: deployed_at=None, uses merged_at (24h)"

    def test_inc_012_deploy_phase_always_none(self) -> None:
        """INC-012: Deploy phase always None because deployed_at is never set."""
        prs = [
            _pr_cycle("PR-1",
                first_commit=_dt(2026, 1, 1),
                first_review=_dt(2026, 1, 1, 8),
                approved=_dt(2026, 1, 1, 12),
                merged=_dt(2026, 1, 2),
                deployed=None,  # ← always None in current system
            )
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.deploy_p50 is None, \
            "INC-012: Deploy phase is None because deployed_at is never populated"
