"""DORA metrics — pure calculation functions.

All functions take data in, return results. No DB access.
TDD: tests come first in Phase 2.

DORA four key metrics:
- Deployment Frequency (DF)
- Lead Time for Changes (LT)
- Change Failure Rate (CFR)
- Mean Time to Recovery (MTTR)
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class DoraLevel(str, Enum):
    """DORA performance classification per the 2023 State of DevOps Report."""

    ELITE = "elite"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class DoraMetrics:
    """Result of DORA metric calculations."""

    deployment_frequency: float | None  # deploys per day
    lead_time_for_changes_hours: float | None  # median hours from commit to deploy
    change_failure_rate: float | None  # percentage (0.0 - 1.0)
    mean_time_to_recovery_hours: float | None  # median hours to recover from failure
    classification: DoraLevel | None


@dataclass(frozen=True)
class DeploymentData:
    """Input data representing a single deployment."""

    deployed_at: datetime
    is_failure: bool
    recovery_time_hours: float | None


@dataclass(frozen=True)
class PullRequestData:
    """Input data representing a pull request for lead time calculation."""

    first_commit_at: datetime | None
    merged_at: datetime | None
    deployed_at: datetime | None


def calculate_deployment_frequency(
    deployments: list[DeploymentData],
    start_date: datetime,
    end_date: datetime,
) -> float | None:
    """Calculate deployment frequency as deploys per day.

    Args:
        deployments: List of deployment events in the period.
        start_date: Period start (inclusive).
        end_date: Period end (inclusive).

    Returns:
        Deploys per day, or None if no data.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_lead_time(
    pull_requests: list[PullRequestData],
) -> float | None:
    """Calculate median lead time for changes in hours.

    Lead time = first commit -> deploy (or merge as fallback).

    Args:
        pull_requests: List of merged/deployed PRs in the period.

    Returns:
        Median lead time in hours, or None if no data.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_change_failure_rate(
    deployments: list[DeploymentData],
) -> float | None:
    """Calculate change failure rate as a ratio (0.0 - 1.0).

    CFR = failed deployments / total deployments.

    Args:
        deployments: List of deployments in the period.

    Returns:
        Failure rate ratio, or None if no deployments.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def calculate_mttr(
    failed_deployments: list[DeploymentData],
) -> float | None:
    """Calculate mean time to recovery in hours.

    MTTR = median recovery_time_hours of failed deployments.

    Args:
        failed_deployments: Deployments where is_failure=True and recovery_time_hours is set.

    Returns:
        Median MTTR in hours, or None if no failures.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")


def classify_dora(metrics: DoraMetrics) -> DoraLevel:
    """Classify DORA performance level based on the four metrics.

    Uses thresholds from the 2023 Accelerate State of DevOps Report:
    - Elite: DF >= 1/day, LT < 1h, CFR < 5%, MTTR < 1h
    - High: DF >= 1/week, LT < 1 day, CFR < 10%, MTTR < 1 day
    - Medium: DF >= 1/month, LT < 1 week, CFR < 15%, MTTR < 1 week
    - Low: everything else

    Args:
        metrics: Calculated DORA metrics.

    Returns:
        DoraLevel classification.
    """
    raise NotImplementedError("Phase 2: TDD — write tests first")
