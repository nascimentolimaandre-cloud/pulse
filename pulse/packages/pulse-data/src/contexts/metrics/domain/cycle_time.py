"""Cycle time metrics — pure calculation functions.

All functions take data in, return results. No DB access.

Cycle time phases (per the PULSE spec):

    Coding    : first_commit_at  → first_review_at
    Pickup    : first_review_at  → approved_at        (reviewer picks up the PR)
    Review    : approved_at      → merged_at
    Deploy    : merged_at        → deployed_at

    Total cycle time = first_commit_at → deployed_at  (or merged_at as fallback)

Each phase is computed per PR, then aggregated across all PRs to produce
P50 / P85 / P95 statistics for team-level visualization.

Anti-surveillance: output is team-level aggregates (percentiles, medians).
No per-author breakdown is computed or returned.

Note on "Pickup" phase naming:
    The UI spec calls the first_review_at → approved_at window "Pickup" because
    it represents the time between the PR being posted for review and the moment
    it is picked up (approved/LGTM'd).  This differs from some industry definitions
    that call the merge→first-review gap "pickup."  The PULSE definition follows the
    frontend-design-doc stacked-bar visualization order:
        Coding | Pickup | Review | Merge/Deploy
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PullRequestCycleData:
    """Input data for PR-based cycle time breakdown.

    Mirrors relevant columns of eng_pull_requests.
    """

    pr_id: str
    first_commit_at: datetime | None
    first_review_at: datetime | None
    approved_at: datetime | None
    merged_at: datetime | None
    deployed_at: datetime | None


@dataclass(frozen=True)
class PrCycleBreakdown:
    """Cycle time breakdown for a single PR (hours per phase).

    None indicates the phase boundary timestamps were unavailable.
    """

    pr_id: str
    coding_hours: float | None      # first_commit_at → first_review_at
    pickup_hours: float | None      # first_review_at → approved_at
    review_hours: float | None      # approved_at → merged_at
    deploy_hours: float | None      # merged_at → deployed_at
    total_hours: float | None       # first_commit_at → deployed_at (merged_at fallback)


@dataclass(frozen=True)
class CycleTimeBreakdown:
    """Team-level cycle time breakdown: P50/P85/P95 per phase.

    Percentiles are computed independently per phase from all PRs that
    have valid timestamps for that phase.  total_* percentiles are computed
    from the full first_commit_at→deployed_at span.

    bottleneck_phase identifies the phase with the highest P50 duration;
    useful for the "bottleneck highlight" in the stacked-bar chart.
    """

    coding_p50: float | None
    coding_p85: float | None
    coding_p95: float | None

    pickup_p50: float | None
    pickup_p85: float | None
    pickup_p95: float | None

    review_p50: float | None
    review_p85: float | None
    review_p95: float | None

    deploy_p50: float | None
    deploy_p85: float | None
    deploy_p95: float | None

    total_p50: float | None
    total_p85: float | None
    total_p95: float | None

    bottleneck_phase: str | None    # "coding" | "pickup" | "review" | "deploy" | None
    pr_count: int


@dataclass(frozen=True)
class CycleTimeTrendPoint:
    """A single point in the cycle time trend chart (per-week bucket)."""

    week_start: date
    p50_hours: float | None
    p85_hours: float | None
    p95_hours: float | None
    pr_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delta_hours(start: datetime | None, end: datetime | None) -> float | None:
    """Return hours between two timestamps, or None if either is absent / negative."""
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds() / 3_600
    return delta if delta >= 0 else None


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile p (0–100) using linear interpolation."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    rank = (p / 100.0) * (n - 1)
    lower = int(rank)
    upper = lower + 1
    if upper >= n:
        return sorted_values[-1]
    return sorted_values[lower] + (rank - lower) * (sorted_values[upper] - sorted_values[lower])


def _stats(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """Return (P50, P85, P95) from a list; (None, None, None) if empty."""
    if not values:
        return (None, None, None)
    s = sorted(values)
    return (
        round(_percentile(s, 50), 2),
        round(_percentile(s, 85), 2),
        round(_percentile(s, 95), 2),
    )


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# Per-PR breakdown
# ---------------------------------------------------------------------------


def breakdown_single_pr(pr: PullRequestCycleData) -> PrCycleBreakdown:
    """Compute cycle time phase breakdown for a single PR.

    Args:
        pr: PR with lifecycle timestamps.

    Returns:
        PrCycleBreakdown with hours per phase (None where timestamps missing).
    """
    coding = _delta_hours(pr.first_commit_at, pr.first_review_at)
    pickup = _delta_hours(pr.first_review_at, pr.approved_at)
    review = _delta_hours(pr.approved_at, pr.merged_at)
    deploy = _delta_hours(pr.merged_at, pr.deployed_at)

    # INC-004: Cycle Time is canonically the dev-work window,
    # first_commit_at → merged_at.  Using deployed_at here would collapse
    # Cycle Time into DORA Lead Time for Changes once deployed_at is
    # populated (they should remain distinct: the difference is the
    # deploy queue time captured by the `deploy` phase above).
    total = _delta_hours(pr.first_commit_at, pr.merged_at)

    return PrCycleBreakdown(
        pr_id=pr.pr_id,
        coding_hours=coding,
        pickup_hours=pickup,
        review_hours=review,
        deploy_hours=deploy,
        total_hours=total,
    )


# ---------------------------------------------------------------------------
# Team-level aggregations
# ---------------------------------------------------------------------------


def calculate_cycle_time_breakdown(
    pull_requests: list[PullRequestCycleData],
) -> CycleTimeBreakdown:
    """Calculate team-level cycle time breakdown with P50/P85/P95 per phase.

    For each phase, only PRs with valid (non-None, non-negative) timestamps
    for that phase contribute to the percentile.  This means phase counts
    may differ — a PR missing first_review_at is excluded from the Coding
    phase percentile but may still contribute to the total if merged/deployed.

    The bottleneck_phase is the phase with the highest P50.  If all P50s are
    None (no data), bottleneck_phase is None.

    Args:
        pull_requests: PRs with lifecycle timestamps.

    Returns:
        CycleTimeBreakdown with per-phase percentiles and bottleneck annotation.
    """
    if not pull_requests:
        return CycleTimeBreakdown(
            coding_p50=None, coding_p85=None, coding_p95=None,
            pickup_p50=None, pickup_p85=None, pickup_p95=None,
            review_p50=None, review_p85=None, review_p95=None,
            deploy_p50=None, deploy_p85=None, deploy_p95=None,
            total_p50=None, total_p85=None, total_p95=None,
            bottleneck_phase=None,
            pr_count=0,
        )

    coding_vals: list[float] = []
    pickup_vals: list[float] = []
    review_vals: list[float] = []
    deploy_vals: list[float] = []
    total_vals: list[float] = []

    for pr in pull_requests:
        b = breakdown_single_pr(pr)
        if b.coding_hours is not None:
            coding_vals.append(b.coding_hours)
        if b.pickup_hours is not None:
            pickup_vals.append(b.pickup_hours)
        if b.review_hours is not None:
            review_vals.append(b.review_hours)
        if b.deploy_hours is not None:
            deploy_vals.append(b.deploy_hours)
        if b.total_hours is not None:
            total_vals.append(b.total_hours)

    coding_p50, coding_p85, coding_p95 = _stats(coding_vals)
    pickup_p50, pickup_p85, pickup_p95 = _stats(pickup_vals)
    review_p50, review_p85, review_p95 = _stats(review_vals)
    deploy_p50, deploy_p85, deploy_p95 = _stats(deploy_vals)
    total_p50, total_p85, total_p95 = _stats(total_vals)

    # Bottleneck = phase with highest P50
    phase_p50s: dict[str, float] = {}
    for phase, p50 in (
        ("coding", coding_p50),
        ("pickup", pickup_p50),
        ("review", review_p50),
        ("deploy", deploy_p50),
    ):
        if p50 is not None:
            phase_p50s[phase] = p50

    bottleneck = max(phase_p50s, key=phase_p50s.__getitem__) if phase_p50s else None

    return CycleTimeBreakdown(
        coding_p50=coding_p50, coding_p85=coding_p85, coding_p95=coding_p95,
        pickup_p50=pickup_p50, pickup_p85=pickup_p85, pickup_p95=pickup_p95,
        review_p50=review_p50, review_p85=review_p85, review_p95=review_p95,
        deploy_p50=deploy_p50, deploy_p85=deploy_p85, deploy_p95=deploy_p95,
        total_p50=total_p50, total_p85=total_p85, total_p95=total_p95,
        bottleneck_phase=bottleneck,
        pr_count=len(pull_requests),
    )


def calculate_cycle_time_trend(
    pull_requests: list[PullRequestCycleData],
    start_date: date,
    end_date: date,
    bucket: str = "week",
) -> list[CycleTimeTrendPoint]:
    """Calculate cycle time trend over time, bucketed by week.

    PRs are bucketed by their merged_at date.  Only PRs with a valid
    total_hours (first_commit_at → deployed_at or merged_at) contribute
    to a bucket's percentiles.

    Currently only "week" bucketing is supported (Monday-aligned ISO weeks).
    Day and month bucketing is reserved for R1.

    Args:
        pull_requests: PRs with lifecycle timestamps.
        start_date: Period start (inclusive).
        end_date: Period end (inclusive).
        bucket: Aggregation granularity.  Only "week" is active in MVP.

    Returns:
        List of CycleTimeTrendPoint ordered by week_start ascending.
        Zero-count weeks are included with None percentiles.
    """
    if start_date > end_date:
        return []

    # Build week buckets for the full range
    current_week = _week_start(start_date)
    end_week = _week_start(end_date)
    weeks: list[date] = []
    while current_week <= end_week:
        weeks.append(current_week)
        current_week += timedelta(weeks=1)

    bucket_totals: dict[date, list[float]] = {w: [] for w in weeks}

    for pr in pull_requests:
        if pr.merged_at is None:
            continue
        merged_date = pr.merged_at.date() if isinstance(pr.merged_at, datetime) else pr.merged_at
        if not (start_date <= merged_date <= end_date):
            continue

        b = breakdown_single_pr(pr)
        if b.total_hours is None:
            continue

        week_key = _week_start(merged_date)
        if week_key in bucket_totals:
            bucket_totals[week_key].append(b.total_hours)

    result: list[CycleTimeTrendPoint] = []
    for week in weeks:
        vals = bucket_totals[week]
        p50, p85, p95 = _stats(vals)
        result.append(
            CycleTimeTrendPoint(
                week_start=week,
                p50_hours=p50,
                p85_hours=p85,
                p95_hours=p95,
                pr_count=len(vals),
            )
        )

    return result
