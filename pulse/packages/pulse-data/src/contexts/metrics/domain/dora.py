"""DORA metrics — pure calculation functions.

All functions take data in, return results. No DB access.

DORA four key metrics:
- Deployment Frequency (DF)
- Lead Time for Changes (LT)
- Change Failure Rate (CFR)
- Mean Time to Recovery (MTTR)

Thresholds from the 2023 Accelerate State of DevOps Report:

| Metric              | Elite       | High           | Medium          | Low        |
|---------------------|-------------|----------------|-----------------|------------|
| Deploy Frequency    | >= 1/day    | 1/week–1/day   | 1/month–1/week  | < 1/month  |
| Lead Time (hours)   | < 1         | 1–168 (1 week) | 168–720 (1 mo)  | >= 720     |
| Change Failure Rate | < 0.05      | 0.05–0.10      | 0.10–0.15       | > 0.15     |
| MTTR (hours)        | < 1         | 1–24 (1 day)   | 24–168 (1 week) | >= 168     |

Anti-surveillance: all metrics are TEAM-level aggregates. No individual
developer attribution is computed or returned.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class DoraLevel(str, Enum):
    """DORA performance classification per the 2023 State of DevOps Report."""

    ELITE = "elite"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class DeploymentData:
    """Input data representing a single deployment event.

    Maps to columns of eng_deployments:
        deployed_at, is_failure, recovery_time_hours
    """

    deployed_at: datetime
    is_failure: bool
    recovery_time_hours: float | None  # None when is_failure=False or not yet recovered


@dataclass(frozen=True)
class PullRequestData:
    """Input data for lead time calculation.

    Maps to columns of eng_pull_requests:
        first_commit_at, merged_at, deployed_at
    """

    first_commit_at: datetime | None
    merged_at: datetime | None
    deployed_at: datetime | None  # preferred endpoint; merged_at used as fallback


@dataclass(frozen=True)
class DoraMetrics:
    """Fully computed DORA metrics for a team/period.

    Fields:
        deployment_frequency_per_day: deploys per calendar day.
        deployment_frequency_per_week: convenience alias (per_day * 7).
        lead_time_for_changes_hours: median hours from first commit to deploy
            (or merge when deploy timestamp is absent).
        change_failure_rate: ratio of failed deployments to total (0.0–1.0).
        mean_time_to_recovery_hours: median recovery hours of failed deployments.
        df_level: DORA classification for Deployment Frequency.
        lt_level: DORA classification for Lead Time.
        cfr_level: DORA classification for Change Failure Rate.
        mttr_level: DORA classification for MTTR.
        overall_level: lowest (worst) classification across all four metrics.
    """

    deployment_frequency_per_day: float | None
    deployment_frequency_per_week: float | None
    lead_time_for_changes_hours: float | None
    change_failure_rate: float | None
    mean_time_to_recovery_hours: float | None
    df_level: DoraLevel | None
    lt_level: DoraLevel | None
    cfr_level: DoraLevel | None
    mttr_level: DoraLevel | None
    overall_level: DoraLevel | None
    # NEW (FDD-DSH-082): strict DORA Lead Time — only PRs with a real
    # deployed_at timestamp. Defaults keep existing call sites (and tests)
    # working unchanged; the public builder always populates them.
    lead_time_for_changes_hours_strict: float | None = None
    lead_time_strict_eligible_count: int = 0
    lead_time_strict_total_count: int = 0
    lt_strict_level: DoraLevel | None = None
    # NEW (FDD-DSH-050): MTTR sample-size visibility. Frontend renders
    # "n=49 incidents (3 still open)" subtitle so users know the median
    # weight + which failures haven't reached recovery yet.
    # `mttr_incident_count` = resolved incidents in the period (the median
    # is computed over these).
    # `mttr_open_incident_count` = failure rows in the period with
    # incident_status='open' — excluded from median, surfaced separately.
    mttr_incident_count: int = 0
    mttr_open_incident_count: int = 0


# ---------------------------------------------------------------------------
# Individual metric calculations (pure functions)
# ---------------------------------------------------------------------------


def calculate_deployment_frequency(
    deployments: list[DeploymentData],
    start_date: datetime,
    end_date: datetime,
) -> tuple[float, float] | tuple[None, None]:
    """Calculate deployment frequency as deploys per day and per week.

    Formula:
        freq_per_day = count(deployments in [start_date, end_date]) / period_days

    Only successful deployments (is_failure=False) are counted; a deployment
    that IS a failure means it went out and broke things — it still counts as
    a deploy event for frequency purposes per DORA guidance.  All deployments
    (successful or failed) count toward frequency.

    Args:
        deployments: All deployment events; filtered to period internally.
        start_date: Period start (inclusive).
        end_date: Period end (inclusive).

    Returns:
        (deploys_per_day, deploys_per_week), or (None, None) when the period
        is zero-length or no deployments exist.
    """
    if start_date > end_date:
        return (None, None)

    period_days: float = (end_date - start_date).total_seconds() / 86_400
    if period_days <= 0:
        return (None, None)

    # Count deployments that fall within the window
    count = sum(
        1
        for d in deployments
        if start_date <= d.deployed_at <= end_date
    )

    if count == 0:
        return (None, None)

    per_day = count / period_days
    per_week = per_day * 7
    return (per_day, per_week)


def calculate_lead_time(
    pull_requests: list[PullRequestData],
) -> float | None:
    """Calculate median lead time for changes in hours.

    Formula:
        lead_time_hours = deployed_at - first_commit_at
                         (merged_at substituted when deployed_at is None)

    PRs missing both deployed_at and merged_at, or missing first_commit_at,
    are excluded from the calculation.

    Args:
        pull_requests: Merged/deployed PRs in the measurement period.

    Returns:
        Median lead time in hours, or None when no measurable PRs exist.
    """
    lead_times: list[float] = []

    for pr in pull_requests:
        if pr.first_commit_at is None:
            continue

        endpoint = pr.deployed_at if pr.deployed_at is not None else pr.merged_at
        if endpoint is None:
            continue

        delta_hours = (endpoint - pr.first_commit_at).total_seconds() / 3_600
        if delta_hours >= 0:
            lead_times.append(delta_hours)

    if not lead_times:
        return None

    return statistics.median(lead_times)


# Minimum sample size for the strict variant — under this we return None to
# avoid publishing a P50 dominated by a handful of outlier deploys. Mirrors
# the convention used by lead_time_distribution (see lean.py).
_LT_STRICT_MIN_SAMPLE = 5


def calculate_lead_time_strict(
    pull_requests: list[PullRequestData],
) -> tuple[float | None, int, int]:
    """Canonical DORA lead time — only PRs with a real `deployed_at`.

    Removes the `merged_at` fallback used by `calculate_lead_time`. When
    deploy↔PR linkage coverage is partial (typical at Webmotors: ~50% on
    several squads), the fallback collapses Lead Time onto Cycle Time and
    produces a misleading aggregate. This variant excludes any PR without
    a real deploy timestamp; the caller surfaces coverage so users can
    judge representativeness.

    Returns a `(value, eligible_count, total_count)` triple so the caller
    can render coverage badges. `value` is `None` when fewer than
    `_LT_STRICT_MIN_SAMPLE` PRs have a deploy linked — small samples make
    the median noise.

    Args:
        pull_requests: Merged PRs in the measurement period.

    Returns:
        (median_hours_or_none, eligible_count, total_count)
    """
    eligible_deltas: list[float] = []
    for pr in pull_requests:
        if pr.first_commit_at is None or pr.deployed_at is None:
            continue
        delta_hours = (pr.deployed_at - pr.first_commit_at).total_seconds() / 3_600
        if delta_hours >= 0:
            eligible_deltas.append(delta_hours)

    total = len(pull_requests)
    eligible = len(eligible_deltas)

    if eligible < _LT_STRICT_MIN_SAMPLE:
        return None, eligible, total

    return statistics.median(eligible_deltas), eligible, total


def calculate_change_failure_rate(
    deployments: list[DeploymentData],
) -> float | None:
    """Calculate change failure rate as a ratio (0.0–1.0).

    Formula:
        CFR = count(deployments WHERE is_failure=True) / count(deployments)

    Args:
        deployments: All deployment events in the measurement period.

    Returns:
        Failure rate as a decimal (e.g. 0.05 = 5%), or None when no
        deployments exist.
    """
    if not deployments:
        return None

    total = len(deployments)
    failures = sum(1 for d in deployments if d.is_failure)
    return failures / total


# FDD-DSH-050 — minimum recovery time below which we treat the row as
# a flaky-test re-trigger rather than a real production incident. 5 minutes
# matches Webmotors' typical Jenkins re-trigger cadence and avoids
# inflating MTTR sample with transient test/network blips.
_MTTR_MIN_RECOVERY_HOURS = 5.0 / 60.0  # 0.0833...

# FDD-DSH-050 — minimum sample size before computing MTTR. Below this
# threshold we return None to avoid reporting unstable medians from
# tiny incident counts (e.g., single 30-day window with 2 incidents).
# Aligned with `_LT_STRICT_MIN_SAMPLE` precedent.
_MTTR_MIN_SAMPLE = 5


def calculate_mttr(
    failed_deployments: list[DeploymentData],
) -> float | None:
    """Calculate median time to recovery in hours.

    Formula (DORA 2023 State of DevOps Report):
        MTTR = median(recovery_time_hours) for resolved failure deployments

    MTTR measures how quickly the team restores service after an incident.
    Only deployments with is_failure=True AND a recorded recovery_time_hours
    contribute to the calculation.

    Filters applied (FDD-DSH-050):
      - recovery_time_hours >= 5 minutes — discards flaky-test re-triggers
        that would inflate the incident count and compress the median.
      - At least 5 resolved incidents required — below that threshold the
        median is statistically unstable; return None.

    Note: failure rows with `incident_status='superseded'` (back-to-back
    failures absorbed into an earlier anchor) carry recovery_time_hours=None
    by design and are filtered out by the None check below.

    Args:
        failed_deployments: Deployment events where is_failure=True.

    Returns:
        Median recovery time in hours, or None when sample size is too
        small or no resolved failures exist.
    """
    recovery_times: list[float] = [
        d.recovery_time_hours
        for d in failed_deployments
        if d.is_failure
        and d.recovery_time_hours is not None
        and d.recovery_time_hours >= _MTTR_MIN_RECOVERY_HOURS
    ]

    if len(recovery_times) < _MTTR_MIN_SAMPLE:
        return None

    return statistics.median(recovery_times)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

# Threshold constants mirror the DORA 2023 report exactly.
# Values are stored as (elite_upper, high_upper, medium_upper) boundaries.
# Anything above medium_upper is LOW.

# Deployment Frequency: units are deploys/day.
# Elite: >= 1/day  → per_day >= 1.0
# High:  1/week–1/day → per_day in [1/7, 1)
# Medium: 1/month–1/week → per_day in [1/30, 1/7)
# Low: < 1/month → per_day < 1/30

_DF_ELITE = 1.0        # deploys/day
_DF_HIGH = 1.0 / 7     # ~0.143 deploys/day  (1/week)
_DF_MEDIUM = 1.0 / 30  # ~0.033 deploys/day  (1/month)

# Lead Time: units are hours.
# Elite: < 1h
# High:  1h–168h (1 week)
# Medium: 168h–720h (1 month ≈ 30 days)
# Low:  >= 720h

_LT_ELITE = 1.0    # hours
_LT_HIGH = 168.0   # hours (7 days)
_LT_MEDIUM = 720.0 # hours (30 days)

# Change Failure Rate: 0.0–1.0 ratio.
# Elite: < 5%
# High:  5–10%
# Medium: 10–15%
# Low: > 15%

_CFR_ELITE = 0.05
_CFR_HIGH = 0.10
_CFR_MEDIUM = 0.15

# MTTR: units are hours.
# Elite: < 1h
# High:  1h–24h
# Medium: 24h–168h (1 week)
# Low: >= 168h

_MTTR_ELITE = 1.0    # hours
_MTTR_HIGH = 24.0    # hours (1 day)
_MTTR_MEDIUM = 168.0 # hours (7 days)


def _classify_deployment_frequency(value: float) -> DoraLevel:
    if value >= _DF_ELITE:
        return DoraLevel.ELITE
    if value >= _DF_HIGH:
        return DoraLevel.HIGH
    if value >= _DF_MEDIUM:
        return DoraLevel.MEDIUM
    return DoraLevel.LOW


def _classify_lead_time(value: float) -> DoraLevel:
    if value < _LT_ELITE:
        return DoraLevel.ELITE
    if value < _LT_HIGH:
        return DoraLevel.HIGH
    if value < _LT_MEDIUM:
        return DoraLevel.MEDIUM
    return DoraLevel.LOW


def _classify_change_failure_rate(value: float) -> DoraLevel:
    if value < _CFR_ELITE:
        return DoraLevel.ELITE
    if value < _CFR_HIGH:
        return DoraLevel.HIGH
    if value < _CFR_MEDIUM:
        return DoraLevel.MEDIUM
    return DoraLevel.LOW


def _classify_mttr(value: float) -> DoraLevel:
    if value < _MTTR_ELITE:
        return DoraLevel.ELITE
    if value < _MTTR_HIGH:
        return DoraLevel.HIGH
    if value < _MTTR_MEDIUM:
        return DoraLevel.MEDIUM
    return DoraLevel.LOW


# Ordering used to determine the worst (lowest) level.
_LEVEL_ORDER: dict[DoraLevel, int] = {
    DoraLevel.ELITE: 3,
    DoraLevel.HIGH: 2,
    DoraLevel.MEDIUM: 1,
    DoraLevel.LOW: 0,
}


def _worst_level(levels: list[DoraLevel]) -> DoraLevel:
    """Return the lowest (worst) DORA level from a list."""
    return min(levels, key=lambda lvl: _LEVEL_ORDER[lvl])


def classify_dora(metrics: DoraMetrics) -> DoraLevel:
    """Classify overall DORA performance as the worst individual metric level.

    Per DORA guidance the overall classification is the lowest (worst)
    classification across all four metrics.  A team with Elite deployment
    frequency but Low MTTR is classified as Low overall.

    Args:
        metrics: Calculated DORA metrics (output of calculate_dora_metrics).

    Returns:
        Overall DoraLevel.  Returns DoraLevel.LOW when no metrics are
        available (defensive default).
    """
    levels: list[DoraLevel] = []
    if metrics.df_level is not None:
        levels.append(metrics.df_level)
    if metrics.lt_level is not None:
        levels.append(metrics.lt_level)
    if metrics.cfr_level is not None:
        levels.append(metrics.cfr_level)
    if metrics.mttr_level is not None:
        levels.append(metrics.mttr_level)

    if not levels:
        return DoraLevel.LOW

    return _worst_level(levels)


# ---------------------------------------------------------------------------
# Composite builder
# ---------------------------------------------------------------------------


def calculate_dora_metrics(
    deployments: list[DeploymentData],
    pull_requests: list[PullRequestData],
    start_date: datetime,
    end_date: datetime,
) -> DoraMetrics:
    """Compute all four DORA metrics and their classifications for a team/period.

    This is the primary entry point for the Metrics Worker.  All inputs are
    pre-filtered to a single (tenant, team, period) slice by the caller.

    Anti-surveillance guarantee: no per-developer breakdown is returned.
    All aggregations are at team level.

    Args:
        deployments: All deployment events in the measurement window.
        pull_requests: All merged/deployed PRs in the measurement window.
        start_date: Period start (inclusive) — used for frequency calculation.
        end_date: Period end (inclusive).

    Returns:
        DoraMetrics with individual metric values, per-metric classifications,
        and an overall classification.
    """
    # --- Deployment Frequency ---
    df_per_day, df_per_week = calculate_deployment_frequency(
        deployments, start_date, end_date
    )
    df_level = _classify_deployment_frequency(df_per_day) if df_per_day is not None else None

    # --- Lead Time for Changes (inclusive — fallback uses merged_at) ---
    lt_hours = calculate_lead_time(pull_requests)
    lt_level = _classify_lead_time(lt_hours) if lt_hours is not None else None

    # --- Lead Time for Changes (STRICT — deployed_at only, FDD-DSH-082) ---
    lt_strict_hours, lt_strict_eligible, lt_strict_total = calculate_lead_time_strict(pull_requests)
    lt_strict_level = _classify_lead_time(lt_strict_hours) if lt_strict_hours is not None else None

    # --- Change Failure Rate ---
    cfr = calculate_change_failure_rate(deployments)
    cfr_level = _classify_change_failure_rate(cfr) if cfr is not None else None

    # --- MTTR ---
    failed = [d for d in deployments if d.is_failure]
    mttr_hours = calculate_mttr(failed)
    mttr_level = _classify_mttr(mttr_hours) if mttr_hours is not None else None
    # FDD-DSH-050 — sample-size visibility: count resolved (recovery_time
    # set + above flaky threshold) and open (no recovery_time, but failure)
    # so the UI can render "n=49 incidents (3 still open)".
    mttr_resolved_count = sum(
        1
        for d in failed
        if d.recovery_time_hours is not None
        and d.recovery_time_hours >= _MTTR_MIN_RECOVERY_HOURS
    )
    mttr_open_count = sum(
        1 for d in failed if d.recovery_time_hours is None
    )

    # --- Overall classification ---
    levels: list[DoraLevel] = [
        lvl
        for lvl in (df_level, lt_level, cfr_level, mttr_level)
        if lvl is not None
    ]
    overall = _worst_level(levels) if levels else None

    return DoraMetrics(
        deployment_frequency_per_day=df_per_day,
        deployment_frequency_per_week=df_per_week,
        lead_time_for_changes_hours=lt_hours,
        lead_time_for_changes_hours_strict=lt_strict_hours,
        lead_time_strict_eligible_count=lt_strict_eligible,
        lead_time_strict_total_count=lt_strict_total,
        change_failure_rate=cfr,
        mean_time_to_recovery_hours=mttr_hours,
        df_level=df_level,
        lt_level=lt_level,
        lt_strict_level=lt_strict_level,
        cfr_level=cfr_level,
        mttr_level=mttr_level,
        overall_level=overall,
        mttr_incident_count=mttr_resolved_count,
        mttr_open_incident_count=mttr_open_count,
    )
