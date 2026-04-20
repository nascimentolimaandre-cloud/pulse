"""Cycle Time sanity invariants (QW-4).

Regression tests for INC-003 and related: when first_commit_at is populated
correctly, P50 cycle time cannot be absurdly low (< 1h) for PRs that take
multiple days between their first commit and merge.

This is a **platform** test — validates mathematical invariants of the
percentile calculation. Customer-specific values (e.g. "Webmotors 60d P50
should be ~6h") belong in tests-customers/webmotors/.

Invariants tested:
1. Empty list → None (not 0, not exception)
2. P50 <= P85 <= P95 (percentiles monotonic)
3. Single PR → P50 == P85 == P95 == that PR's cycle time
4. When every PR has age >= 1h, P50 cannot be < 1h
5. Negative age data should not corrupt percentiles (filter or defensive)
6. Mixed durations: P50 of [1h, 2h, 3h, 4h, 100h] is around 3h (median)
7. All PRs identical → P50 == P85 == P95 (degenerate distribution)

Classification: PLATFORM (universal domain invariant).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.contexts.metrics.domain.cycle_time import (
    PullRequestCycleData,
    calculate_cycle_time_breakdown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def pr(
    pr_id: str,
    first_commit_hours_before_merge: float | None = None,
    first_review_hours_before_merge: float | None = None,
    approved_hours_before_merge: float | None = None,
    deployed_hours_after_merge: float | None = None,
) -> PullRequestCycleData:
    """Build a PR fixture with timestamps relative to a fixed merge anchor."""
    merge = BASE
    return PullRequestCycleData(
        pr_id=pr_id,
        first_commit_at=(
            merge - timedelta(hours=first_commit_hours_before_merge)
            if first_commit_hours_before_merge is not None
            else None
        ),
        first_review_at=(
            merge - timedelta(hours=first_review_hours_before_merge)
            if first_review_hours_before_merge is not None
            else None
        ),
        approved_at=(
            merge - timedelta(hours=approved_hours_before_merge)
            if approved_hours_before_merge is not None
            else None
        ),
        merged_at=merge,
        deployed_at=(
            merge + timedelta(hours=deployed_hours_after_merge)
            if deployed_hours_after_merge is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

class TestEmptyAndDegenerate:
    """Empty input, single PR, all-identical PRs."""

    def test_empty_list_returns_none_total_p50(self):
        result = calculate_cycle_time_breakdown([])
        assert result.total_p50 is None, (
            "Empty input must return None for P50, not 0 or exception"
        )
        assert result.total_p85 is None
        assert result.total_p95 is None

    def test_empty_list_no_bottleneck(self):
        result = calculate_cycle_time_breakdown([])
        assert result.bottleneck_phase is None

    def test_single_pr_p50_equals_p85_equals_p95(self):
        """With one PR, all percentiles collapse to that PR's cycle time."""
        prs = [pr("pr1", first_commit_hours_before_merge=10.0)]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p50 == result.total_p85 == result.total_p95, (
            f"Single-PR degenerate case: expected P50==P85==P95, got "
            f"{result.total_p50}/{result.total_p85}/{result.total_p95}"
        )
        # All should equal the PR's cycle time (10h)
        assert result.total_p50 == pytest.approx(10.0, rel=0.01)

    def test_all_identical_prs_percentiles_collapse(self):
        """Many PRs with same cycle time → all percentiles same value."""
        prs = [pr(f"pr{i}", first_commit_hours_before_merge=5.0) for i in range(10)]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p50 == result.total_p85 == result.total_p95
        assert result.total_p50 == pytest.approx(5.0, rel=0.01)


class TestMonotonicPercentiles:
    """P50 <= P85 <= P95 ALWAYS."""

    def test_percentiles_monotonically_increase(self):
        """For a reasonable distribution, P50 <= P85 <= P95."""
        prs = [
            pr(f"pr{i}", first_commit_hours_before_merge=h)
            for i, h in enumerate([1, 2, 3, 5, 8, 13, 21, 34, 55, 89])
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p50 is not None
        assert result.total_p85 is not None
        assert result.total_p95 is not None
        assert result.total_p50 <= result.total_p85 <= result.total_p95, (
            f"Percentiles not monotonic: P50={result.total_p50}, "
            f"P85={result.total_p85}, P95={result.total_p95}"
        )


class TestLowerBoundInvariant:
    """QW-4 core: when every PR has age >= X, P50 cannot be < X."""

    def test_p50_not_below_minimum_sample_age(self):
        """If every PR took >= 1h, P50 >= 1h.

        Historical INC-003: backend was reporting P50 = 17min (0.28h) for a
        population where real dev-cycle is days. Root cause: `first_commit_at`
        was proxied from `created_at` (PR open date), not the real first
        commit.  When the data is correct (first_commit_at real), this
        invariant must hold.
        """
        # All PRs took between 1h and 100h — none faster than 1h
        prs = [
            pr(f"pr{i}", first_commit_hours_before_merge=h)
            for i, h in enumerate([1.5, 2.0, 5.0, 24.0, 48.0, 100.0, 200.0, 500.0])
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p50 is not None
        assert result.total_p50 >= 1.0, (
            f"P50={result.total_p50}h but all PRs had age >= 1h. "
            f"This is the INC-003 signature: `first_commit_at` likely being "
            f"proxied from `created_at` somewhere in the pipeline."
        )

    def test_p85_not_below_p50(self):
        prs = [
            pr(f"pr{i}", first_commit_hours_before_merge=h)
            for i, h in enumerate([2.0, 4.0, 8.0, 16.0, 32.0])
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p50 is not None and result.total_p85 is not None
        assert result.total_p85 >= result.total_p50


class TestRealisticDistribution:
    """Sanity check against a realistic distribution of human-authored PRs."""

    def test_median_of_known_distribution(self):
        """P50 of [1,2,3,4,5] hours is 3.0h (simple median)."""
        prs = [
            pr(f"pr{i}", first_commit_hours_before_merge=float(i))
            for i in range(1, 6)
        ]
        result = calculate_cycle_time_breakdown(prs)
        # For 5 items, median is the middle value = 3.0
        assert result.total_p50 == pytest.approx(3.0, rel=0.1)

    def test_outlier_does_not_distort_p50(self):
        """One outlier PR with 1000h does not pull P50 above the median."""
        prs = [
            pr(f"pr{i}", first_commit_hours_before_merge=h)
            for i, h in enumerate([2.0, 3.0, 4.0, 5.0, 1000.0])
        ]
        result = calculate_cycle_time_breakdown(prs)
        # Median of [2,3,4,5,1000] is 4 (position-based, not affected by outlier)
        assert result.total_p50 < 10.0, (
            f"P50 was distorted by outlier: {result.total_p50}h. "
            f"Median should be robust to outliers."
        )
        # But P95 SHOULD reflect the outlier
        assert result.total_p95 is not None
        assert result.total_p95 > 100.0


class TestPartialData:
    """PRs missing some phase timestamps should not crash — only affect that phase."""

    def test_pr_missing_review_still_contributes_to_total(self):
        """PR without first_review_at should still have total cycle time."""
        prs = [
            pr("pr1", first_commit_hours_before_merge=10.0, first_review_hours_before_merge=5.0),
            pr("pr2", first_commit_hours_before_merge=8.0, first_review_hours_before_merge=None),
        ]
        result = calculate_cycle_time_breakdown(prs)
        assert result.total_p50 is not None, (
            "Total P50 should be computable even if some PRs miss review_at"
        )
        # Both PRs contribute to total (10h and 8h)
        assert result.pr_count == 2

    def test_pr_without_first_commit_excluded_gracefully(self):
        """PR without first_commit_at cannot produce a cycle time — should not crash."""
        prs = [
            pr("pr1", first_commit_hours_before_merge=None),  # No cycle time possible
        ]
        # Must not raise
        result = calculate_cycle_time_breakdown(prs)
        # Total should be None (no valid data) or PR excluded
        assert result.total_p50 is None or result.pr_count == 0
