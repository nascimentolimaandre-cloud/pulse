"""Unit tests for DORA metric calculations.

Tests pure domain functions in:
    src/contexts/metrics/domain/dora.py

Coverage targets:
- calculate_deployment_frequency: 0 deploys, 1 deploy, many deploys, edge dates
- calculate_lead_time: median, missing timestamps, fallback to merged_at
- calculate_change_failure_rate: 0%, 50%, 100%, empty list
- calculate_mttr: single, multiple, no resolved failures
- Classification: each level (Elite/High/Medium/Low) per metric
- Overall classification: worst-level rule
- Composite builder: calculate_dora_metrics end-to-end
- Anti-surveillance: no per-developer data returned
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.contexts.metrics.domain.dora import (
    DeploymentData,
    DoraLevel,
    DoraMetrics,
    PullRequestData,
    calculate_change_failure_rate,
    calculate_deployment_frequency,
    calculate_dora_metrics,
    calculate_lead_time,
    calculate_lead_time_strict,
    calculate_mttr,
    classify_dora,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _deploy(deployed_at: datetime, *, is_failure: bool = False, recovery: float | None = None) -> DeploymentData:
    return DeploymentData(deployed_at=deployed_at, is_failure=is_failure, recovery_time_hours=recovery)


def _pr(
    first_commit: datetime | None = None,
    merged: datetime | None = None,
    deployed: datetime | None = None,
) -> PullRequestData:
    return PullRequestData(first_commit_at=first_commit, merged_at=merged, deployed_at=deployed)


# ---------------------------------------------------------------------------
# calculate_deployment_frequency
# ---------------------------------------------------------------------------


class TestDeploymentFrequency:
    def test_no_deployments_returns_none_tuple(self) -> None:
        result = calculate_deployment_frequency([], _dt(2024, 1, 1), _dt(2024, 1, 31))
        assert result == (None, None)

    def test_start_date_after_end_date_returns_none_tuple(self) -> None:
        deploy = _deploy(_dt(2024, 1, 15))
        result = calculate_deployment_frequency([deploy], _dt(2024, 1, 31), _dt(2024, 1, 1))
        assert result == (None, None)

    def test_start_equals_end_returns_none_tuple(self) -> None:
        deploy = _deploy(_dt(2024, 1, 15))
        result = calculate_deployment_frequency([deploy], _dt(2024, 1, 15), _dt(2024, 1, 15))
        assert result == (None, None)

    def test_single_deploy_in_7_day_window(self) -> None:
        deploy = _deploy(_dt(2024, 1, 4))
        per_day, per_week = calculate_deployment_frequency([deploy], _dt(2024, 1, 1), _dt(2024, 1, 7))
        assert per_day is not None
        assert per_week is not None
        # 1 deploy / 6 days (Jan 1–7 exclusive diff = 6)
        assert abs(per_week - per_day * 7) < 0.001

    def test_multiple_deploys_frequency_is_count_divided_by_days(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 2)),
            _deploy(_dt(2024, 1, 9)),
            _deploy(_dt(2024, 1, 16)),
            _deploy(_dt(2024, 1, 23)),
        ]
        per_day, per_week = calculate_deployment_frequency(deploys, _dt(2024, 1, 1), _dt(2024, 1, 28))
        assert per_day is not None
        # 4 deploys / 27 days
        assert abs(per_day - 4 / 27) < 0.001
        assert abs(per_week - per_day * 7) < 0.001

    def test_deployments_outside_window_are_excluded(self) -> None:
        in_window = _deploy(_dt(2024, 1, 15))
        outside_before = _deploy(_dt(2023, 12, 31))
        outside_after = _deploy(_dt(2024, 2, 1))
        per_day, _ = calculate_deployment_frequency(
            [outside_before, in_window, outside_after],
            _dt(2024, 1, 1),
            _dt(2024, 1, 31),
        )
        assert per_day is not None
        # Only 1 deploy counted
        assert abs(per_day - 1 / 30) < 0.001

    def test_failed_deployments_count_toward_frequency(self) -> None:
        """DORA includes failures in deployment frequency per spec."""
        deploys = [
            _deploy(_dt(2024, 1, 5), is_failure=True),
            _deploy(_dt(2024, 1, 12)),
        ]
        per_day, _ = calculate_deployment_frequency(deploys, _dt(2024, 1, 1), _dt(2024, 1, 28))
        assert per_day is not None
        assert abs(per_day - 2 / 27) < 0.001

    def test_boundary_dates_are_inclusive(self) -> None:
        deploy_start = _deploy(_dt(2024, 1, 1))
        deploy_end = _deploy(_dt(2024, 1, 7))
        per_day, _ = calculate_deployment_frequency([deploy_start, deploy_end], _dt(2024, 1, 1), _dt(2024, 1, 7))
        assert per_day is not None
        # 2 deploys over 6 days
        assert abs(per_day - 2 / 6) < 0.001


# ---------------------------------------------------------------------------
# calculate_lead_time
# ---------------------------------------------------------------------------


class TestLeadTime:
    def test_empty_list_returns_none(self) -> None:
        assert calculate_lead_time([]) is None

    def test_all_prs_missing_first_commit_returns_none(self) -> None:
        prs = [_pr(merged=_dt(2024, 1, 10)), _pr(merged=_dt(2024, 1, 15))]
        assert calculate_lead_time(prs) is None

    def test_all_prs_missing_endpoint_returns_none(self) -> None:
        prs = [_pr(first_commit=_dt(2024, 1, 5))]
        assert calculate_lead_time(prs) is None

    def test_single_pr_with_deployed_at_uses_deployed_at(self) -> None:
        pr = _pr(first_commit=_dt(2024, 1, 5, 8), deployed=_dt(2024, 1, 5, 16))
        result = calculate_lead_time([pr])
        assert result == 8.0  # 8 hours

    def test_single_pr_falls_back_to_merged_at_when_no_deployed_at(self) -> None:
        pr = _pr(first_commit=_dt(2024, 1, 5, 9), merged=_dt(2024, 1, 6, 9))
        result = calculate_lead_time([pr])
        assert result == 24.0  # 24 hours

    def test_deployed_at_preferred_over_merged_at(self) -> None:
        pr = _pr(
            first_commit=_dt(2024, 1, 5, 9),
            merged=_dt(2024, 1, 6, 9),       # 24h if used
            deployed=_dt(2024, 1, 5, 13),    # 4h if used
        )
        result = calculate_lead_time([pr])
        assert result == 4.0

    def test_multiple_prs_returns_median(self) -> None:
        prs = [
            _pr(first_commit=_dt(2024, 1, 1, 0), deployed=_dt(2024, 1, 1, 2)),   # 2h
            _pr(first_commit=_dt(2024, 1, 2, 0), deployed=_dt(2024, 1, 2, 8)),   # 8h
            _pr(first_commit=_dt(2024, 1, 3, 0), deployed=_dt(2024, 1, 3, 6)),   # 6h
        ]
        result = calculate_lead_time(prs)
        assert result == 6.0  # median of [2, 6, 8]

    def test_negative_delta_is_excluded(self) -> None:
        """PR where endpoint < first_commit (data error) must be excluded."""
        valid = _pr(first_commit=_dt(2024, 1, 1, 0), deployed=_dt(2024, 1, 1, 12))   # 12h
        invalid = _pr(first_commit=_dt(2024, 1, 5, 12), deployed=_dt(2024, 1, 5, 6))  # -6h
        result = calculate_lead_time([valid, invalid])
        assert result == 12.0

    def test_pr_with_none_first_commit_excluded_others_counted(self) -> None:
        prs = [
            _pr(first_commit=None, deployed=_dt(2024, 1, 10)),    # excluded
            _pr(first_commit=_dt(2024, 1, 9, 0), deployed=_dt(2024, 1, 9, 10)),  # 10h
        ]
        result = calculate_lead_time(prs)
        assert result == 10.0


# ---------------------------------------------------------------------------
# calculate_lead_time_strict (FDD-DSH-082)
# ---------------------------------------------------------------------------


class TestLeadTimeStrict:
    """Strict variant — only PRs with deployed_at, no merged_at fallback."""

    def test_empty_returns_none_with_zero_counts(self) -> None:
        assert calculate_lead_time_strict([]) == (None, 0, 0)

    def test_below_min_sample_returns_none(self) -> None:
        # 4 eligible PRs (< _LT_STRICT_MIN_SAMPLE=5) → value None but counts populated
        prs = [
            _pr(first_commit=_dt(2024, 1, 1), deployed=_dt(2024, 1, 2))
            for _ in range(4)
        ]
        value, eligible, total = calculate_lead_time_strict(prs)
        assert value is None
        assert eligible == 4
        assert total == 4

    def test_excludes_prs_without_deployed_at(self) -> None:
        # 3 with deploy + 5 without → eligible=3 < min, returns None
        eligible_prs = [
            _pr(first_commit=_dt(2024, 1, 1), deployed=_dt(2024, 1, 2))
            for _ in range(3)
        ]
        no_deploy = [
            _pr(first_commit=_dt(2024, 1, 1), merged=_dt(2024, 1, 1, 2), deployed=None)
            for _ in range(5)
        ]
        value, eligible, total = calculate_lead_time_strict(eligible_prs + no_deploy)
        assert value is None
        assert eligible == 3
        assert total == 8

    def test_returns_median_when_sample_sufficient(self) -> None:
        # 5 PRs all with deploy at +24h, +48h, +72h, +96h, +120h => median 72h
        base = _dt(2024, 1, 1)
        prs = [
            _pr(first_commit=base, deployed=base + timedelta(hours=h))
            for h in (24, 48, 72, 96, 120)
        ]
        value, eligible, total = calculate_lead_time_strict(prs)
        assert value == 72.0
        assert eligible == 5
        assert total == 5

    def test_diverges_from_inclusive_when_coverage_partial(self) -> None:
        # Mirrors the OKM bug: inclusive fallback collapses lead time onto
        # cycle time, strict surfaces the real DORA value.
        deployed_prs = [
            _pr(
                first_commit=_dt(2024, 1, 1),
                merged=_dt(2024, 1, 1, 2),
                deployed=_dt(2024, 1, 5),  # 96h
            )
            for _ in range(5)
        ]
        merged_only = [
            _pr(
                first_commit=_dt(2024, 1, 1),
                merged=_dt(2024, 1, 1, 1),  # 1h fallback
                deployed=None,
            )
            for _ in range(5)
        ]
        all_prs = deployed_prs + merged_only

        inclusive = calculate_lead_time(all_prs)
        strict_value, eligible, total = calculate_lead_time_strict(all_prs)

        # Inclusive median sits between the two clusters (closer to 1h)
        assert inclusive is not None
        # Strict reflects only the deployed cluster
        assert strict_value == 96.0
        assert eligible == 5
        assert total == 10
        assert strict_value > inclusive

    def test_negative_delta_excluded(self) -> None:
        # 4 valid + 1 with deployed_at < first_commit (clock skew)
        good = [
            _pr(first_commit=_dt(2024, 1, 1), deployed=_dt(2024, 1, 2))
            for _ in range(4)
        ]
        bad = _pr(first_commit=_dt(2024, 1, 5), deployed=_dt(2024, 1, 1))
        value, eligible, total = calculate_lead_time_strict(good + [bad])
        # Only 4 valid (negative dropped) — under min sample → None
        assert value is None
        assert eligible == 4
        assert total == 5


# ---------------------------------------------------------------------------
# calculate_change_failure_rate
# ---------------------------------------------------------------------------


class TestChangeFailureRate:
    def test_empty_list_returns_none(self) -> None:
        assert calculate_change_failure_rate([]) is None

    def test_zero_failures_returns_0(self) -> None:
        deploys = [_deploy(_dt(2024, 1, d)) for d in range(1, 6)]
        assert calculate_change_failure_rate(deploys) == 0.0

    def test_all_failures_returns_1(self) -> None:
        deploys = [_deploy(_dt(2024, 1, d), is_failure=True) for d in range(1, 6)]
        assert calculate_change_failure_rate(deploys) == 1.0

    def test_50_percent_failure_rate(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 1), is_failure=True),
            _deploy(_dt(2024, 1, 2), is_failure=False),
            _deploy(_dt(2024, 1, 3), is_failure=True),
            _deploy(_dt(2024, 1, 4), is_failure=False),
        ]
        assert calculate_change_failure_rate(deploys) == 0.5

    def test_single_failure_calculates_correctly(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 1)),
            _deploy(_dt(2024, 1, 2)),
            _deploy(_dt(2024, 1, 3)),
            _deploy(_dt(2024, 1, 4), is_failure=True),
        ]
        result = calculate_change_failure_rate(deploys)
        assert abs(result - 0.25) < 0.001


# ---------------------------------------------------------------------------
# calculate_mttr
# ---------------------------------------------------------------------------


class TestMttr:
    def test_empty_list_returns_none(self) -> None:
        assert calculate_mttr([]) is None

    def test_failures_with_no_recovery_time_returns_none(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 5), is_failure=True, recovery=None),
            _deploy(_dt(2024, 1, 6), is_failure=True, recovery=None),
        ]
        assert calculate_mttr(deploys) is None

    def test_successful_deployments_excluded_from_mttr(self) -> None:
        """Non-failures with recovery_time set should NOT contribute."""
        deploys = [
            _deploy(_dt(2024, 1, 5), is_failure=False, recovery=2.0),
        ]
        assert calculate_mttr(deploys) is None

    def test_single_failure_returns_recovery_time(self) -> None:
        deploys = [_deploy(_dt(2024, 1, 5), is_failure=True, recovery=4.5)]
        assert calculate_mttr(deploys) == 4.5

    def test_multiple_failures_returns_median(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 1), is_failure=True, recovery=1.0),
            _deploy(_dt(2024, 1, 2), is_failure=True, recovery=3.0),
            _deploy(_dt(2024, 1, 3), is_failure=True, recovery=5.0),
        ]
        assert calculate_mttr(deploys) == 3.0  # median of [1, 3, 5]

    def test_two_failures_median_is_average_of_two(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 1), is_failure=True, recovery=2.0),
            _deploy(_dt(2024, 1, 2), is_failure=True, recovery=6.0),
        ]
        assert calculate_mttr(deploys) == 4.0

    def test_zero_recovery_time_is_included(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 1), is_failure=True, recovery=0.0),
            _deploy(_dt(2024, 1, 2), is_failure=True, recovery=4.0),
        ]
        assert calculate_mttr(deploys) == 2.0

    def test_negative_recovery_time_is_excluded(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 1), is_failure=True, recovery=-1.0),  # bad data
            _deploy(_dt(2024, 1, 2), is_failure=True, recovery=6.0),
        ]
        assert calculate_mttr(deploys) == 6.0


# ---------------------------------------------------------------------------
# DORA classification — Deployment Frequency
# ---------------------------------------------------------------------------


class TestDeploymentFrequencyClassification:
    """Test _classify_deployment_frequency indirectly via calculate_dora_metrics."""

    def _dora_with_df(self, per_day: float) -> DoraMetrics:
        """Build a DoraMetrics where only df_level is set."""
        from src.contexts.metrics.domain.dora import _classify_deployment_frequency

        level = _classify_deployment_frequency(per_day)
        return DoraMetrics(
            deployment_frequency_per_day=per_day,
            deployment_frequency_per_week=per_day * 7,
            lead_time_for_changes_hours=None,
            change_failure_rate=None,
            mean_time_to_recovery_hours=None,
            df_level=level,
            lt_level=None,
            cfr_level=None,
            mttr_level=None,
            overall_level=level,
        )

    def test_elite_is_at_least_one_deploy_per_day(self) -> None:
        assert self._dora_with_df(1.0).df_level == DoraLevel.ELITE
        assert self._dora_with_df(2.5).df_level == DoraLevel.ELITE

    def test_high_is_between_one_per_week_and_one_per_day(self) -> None:
        assert self._dora_with_df(1 / 7).df_level == DoraLevel.HIGH
        assert self._dora_with_df(0.5).df_level == DoraLevel.HIGH

    def test_medium_is_between_one_per_month_and_one_per_week(self) -> None:
        assert self._dora_with_df(1 / 30).df_level == DoraLevel.MEDIUM
        assert self._dora_with_df(1 / 14).df_level == DoraLevel.MEDIUM

    def test_low_is_less_than_one_per_month(self) -> None:
        assert self._dora_with_df(1 / 60).df_level == DoraLevel.LOW
        assert self._dora_with_df(0.0001).df_level == DoraLevel.LOW


# ---------------------------------------------------------------------------
# DORA classification — Lead Time
# ---------------------------------------------------------------------------


class TestLeadTimeClassification:
    def _level(self, hours: float) -> DoraLevel:
        from src.contexts.metrics.domain.dora import _classify_lead_time
        return _classify_lead_time(hours)

    def test_elite_is_under_1_hour(self) -> None:
        assert self._level(0.5) == DoraLevel.ELITE
        assert self._level(0.0) == DoraLevel.ELITE

    def test_high_is_1h_to_168h(self) -> None:
        assert self._level(1.0) == DoraLevel.HIGH
        assert self._level(100.0) == DoraLevel.HIGH
        assert self._level(167.9) == DoraLevel.HIGH

    def test_medium_is_168h_to_720h(self) -> None:
        assert self._level(168.0) == DoraLevel.MEDIUM
        assert self._level(400.0) == DoraLevel.MEDIUM
        assert self._level(719.9) == DoraLevel.MEDIUM

    def test_low_is_720h_or_more(self) -> None:
        assert self._level(720.0) == DoraLevel.LOW
        assert self._level(1000.0) == DoraLevel.LOW


# ---------------------------------------------------------------------------
# DORA classification — Change Failure Rate
# ---------------------------------------------------------------------------


class TestCfrClassification:
    def _level(self, cfr: float) -> DoraLevel:
        from src.contexts.metrics.domain.dora import _classify_change_failure_rate
        return _classify_change_failure_rate(cfr)

    def test_elite_is_under_5_percent(self) -> None:
        assert self._level(0.0) == DoraLevel.ELITE
        assert self._level(0.04) == DoraLevel.ELITE

    def test_high_is_5_to_10_percent(self) -> None:
        assert self._level(0.05) == DoraLevel.HIGH
        assert self._level(0.08) == DoraLevel.HIGH

    def test_medium_is_10_to_15_percent(self) -> None:
        assert self._level(0.10) == DoraLevel.MEDIUM
        assert self._level(0.12) == DoraLevel.MEDIUM

    def test_low_is_above_15_percent(self) -> None:
        assert self._level(0.15) == DoraLevel.LOW
        assert self._level(0.50) == DoraLevel.LOW
        assert self._level(1.0) == DoraLevel.LOW


# ---------------------------------------------------------------------------
# DORA classification — MTTR
# ---------------------------------------------------------------------------


class TestMttrClassification:
    def _level(self, hours: float) -> DoraLevel:
        from src.contexts.metrics.domain.dora import _classify_mttr
        return _classify_mttr(hours)

    def test_elite_is_under_1_hour(self) -> None:
        assert self._level(0.0) == DoraLevel.ELITE
        assert self._level(0.9) == DoraLevel.ELITE

    def test_high_is_1h_to_24h(self) -> None:
        assert self._level(1.0) == DoraLevel.HIGH
        assert self._level(12.0) == DoraLevel.HIGH
        assert self._level(23.9) == DoraLevel.HIGH

    def test_medium_is_24h_to_168h(self) -> None:
        assert self._level(24.0) == DoraLevel.MEDIUM
        assert self._level(72.0) == DoraLevel.MEDIUM
        assert self._level(167.9) == DoraLevel.MEDIUM

    def test_low_is_168h_or_more(self) -> None:
        assert self._level(168.0) == DoraLevel.LOW
        assert self._level(500.0) == DoraLevel.LOW


# ---------------------------------------------------------------------------
# classify_dora — overall worst-level rule
# ---------------------------------------------------------------------------


class TestClassifyDora:
    def _metrics(
        self,
        df: DoraLevel | None,
        lt: DoraLevel | None,
        cfr: DoraLevel | None,
        mttr: DoraLevel | None,
    ) -> DoraMetrics:
        return DoraMetrics(
            deployment_frequency_per_day=None,
            deployment_frequency_per_week=None,
            lead_time_for_changes_hours=None,
            change_failure_rate=None,
            mean_time_to_recovery_hours=None,
            df_level=df,
            lt_level=lt,
            cfr_level=cfr,
            mttr_level=mttr,
            overall_level=None,
        )

    def test_all_elite_returns_elite(self) -> None:
        m = self._metrics(DoraLevel.ELITE, DoraLevel.ELITE, DoraLevel.ELITE, DoraLevel.ELITE)
        assert classify_dora(m) == DoraLevel.ELITE

    def test_one_low_forces_overall_low(self) -> None:
        m = self._metrics(DoraLevel.ELITE, DoraLevel.HIGH, DoraLevel.MEDIUM, DoraLevel.LOW)
        assert classify_dora(m) == DoraLevel.LOW

    def test_all_none_returns_low_defensive_default(self) -> None:
        m = self._metrics(None, None, None, None)
        assert classify_dora(m) == DoraLevel.LOW

    def test_single_metric_determines_overall(self) -> None:
        m = self._metrics(DoraLevel.HIGH, None, None, None)
        assert classify_dora(m) == DoraLevel.HIGH

    def test_medium_is_worst_when_others_are_high_or_elite(self) -> None:
        m = self._metrics(DoraLevel.ELITE, DoraLevel.HIGH, DoraLevel.MEDIUM, None)
        assert classify_dora(m) == DoraLevel.MEDIUM

    def test_all_high_returns_high(self) -> None:
        m = self._metrics(DoraLevel.HIGH, DoraLevel.HIGH, DoraLevel.HIGH, DoraLevel.HIGH)
        assert classify_dora(m) == DoraLevel.HIGH


# ---------------------------------------------------------------------------
# calculate_dora_metrics — composite builder
# ---------------------------------------------------------------------------


class TestCalculateDoraMetrics:
    def test_all_empty_inputs_returns_all_none_with_none_overall(self) -> None:
        result = calculate_dora_metrics([], [], _dt(2024, 1, 1), _dt(2024, 1, 31))
        assert result.deployment_frequency_per_day is None
        assert result.lead_time_for_changes_hours is None
        assert result.change_failure_rate is None
        assert result.mean_time_to_recovery_hours is None
        assert result.overall_level is None

    def test_elite_team_all_metrics_classify_as_elite(self) -> None:
        """Team with multiple daily deploys, sub-1h lead time, 0% CFR, sub-1h MTTR."""
        deploys = [
            _deploy(_dt(2024, 1, d)) for d in range(1, 29)  # ~1/day
        ]
        prs = [
            _pr(first_commit=_dt(2024, 1, d, 8), deployed=_dt(2024, 1, d, 8, 30))
            for d in range(1, 6)
        ]
        # No failures means MTTR is None — overall uses df/lt/cfr only
        result = calculate_dora_metrics(deploys, prs, _dt(2024, 1, 1), _dt(2024, 1, 28))
        assert result.df_level == DoraLevel.ELITE
        assert result.lt_level == DoraLevel.ELITE
        assert result.cfr_level == DoraLevel.ELITE
        assert result.mttr_level is None  # no failures to recover from
        assert result.overall_level == DoraLevel.ELITE

    def test_result_has_no_per_developer_field(self) -> None:
        """Anti-surveillance: DoraMetrics must not expose individual developer data."""
        result = calculate_dora_metrics([], [], _dt(2024, 1, 1), _dt(2024, 1, 31))
        field_names = {f.name for f in result.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        anti_surveillance_violations = {
            "author", "developer", "contributor", "user", "person", "dev",
        }
        assert not field_names.intersection(anti_surveillance_violations)

    def test_failed_deployments_feed_mttr_not_double_counted(self) -> None:
        deploys = [
            _deploy(_dt(2024, 1, 5), is_failure=True, recovery=0.5),
            _deploy(_dt(2024, 1, 10)),
        ]
        result = calculate_dora_metrics(deploys, [], _dt(2024, 1, 1), _dt(2024, 1, 31))
        assert result.change_failure_rate == 0.5  # 1 failure out of 2
        assert result.mean_time_to_recovery_hours == 0.5
        assert result.mttr_level == DoraLevel.ELITE

    def test_low_deploy_frequency_drives_overall_to_low(self) -> None:
        """Even if other metrics are elite, one low metric makes overall low."""
        # Very infrequent deployment (1 in 90 days) → LOW df
        deploys = [_deploy(_dt(2024, 1, 15))]
        prs = [_pr(first_commit=_dt(2024, 1, 15, 8), deployed=_dt(2024, 1, 15, 8, 30))]  # elite lt
        result = calculate_dora_metrics(deploys, prs, _dt(2024, 1, 1), _dt(2024, 3, 31))
        assert result.df_level == DoraLevel.LOW
        assert result.overall_level == DoraLevel.LOW
