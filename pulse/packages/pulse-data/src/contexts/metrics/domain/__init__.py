"""Metrics domain — pure calculation functions.

Public surface for the metrics domain layer.  All symbols below are pure
functions or dataclasses (no DB, no I/O).

DORA:
    DoraLevel, DeploymentData, PullRequestData, DoraMetrics
    calculate_deployment_frequency, calculate_lead_time,
    calculate_change_failure_rate, calculate_mttr,
    calculate_dora_metrics, classify_dora

Lean:
    IssueFlowData, CfdDataPoint, LeadTimeDistributionBucket,
    LeadTimeDistribution, ThroughputDataPoint, ScatterPoint
    calculate_cfd, calculate_wip, calculate_lead_time_distribution,
    calculate_throughput, calculate_lead_time_scatterplot

Cycle Time:
    PullRequestCycleData, PrCycleBreakdown, CycleTimeBreakdown,
    CycleTimeTrendPoint
    breakdown_single_pr, calculate_cycle_time_breakdown,
    calculate_cycle_time_trend

Sprint:
    SprintData, SprintOverview, SprintSummary, SprintComparison
    calculate_sprint_overview, calculate_sprint_comparison

Throughput:
    PullRequestThroughputData, ThroughputTrendPoint,
    PrSizeDistributionBucket, PrAnalytics
    calculate_throughput_trend, calculate_pr_analytics
"""

from .cycle_time import (
    CycleTimeBreakdown,
    CycleTimeTrendPoint,
    PrCycleBreakdown,
    PullRequestCycleData,
    breakdown_single_pr,
    calculate_cycle_time_breakdown,
    calculate_cycle_time_trend,
)
from .dora import (
    DeploymentData,
    DoraLevel,
    DoraMetrics,
    PullRequestData,
    calculate_change_failure_rate,
    calculate_deployment_frequency,
    calculate_dora_metrics,
    calculate_lead_time,
    calculate_mttr,
    classify_dora,
)
from .lean import (
    CfdDataPoint,
    IssueFlowData,
    LeadTimeDistribution,
    LeadTimeDistributionBucket,
    ScatterPoint,
    ThroughputDataPoint,
    calculate_cfd,
    calculate_lead_time_distribution,
    calculate_lead_time_scatterplot,
    calculate_throughput,
    calculate_wip,
)
from .sprint import (
    SprintComparison,
    SprintData,
    SprintOverview,
    SprintSummary,
    calculate_sprint_comparison,
    calculate_sprint_overview,
)
from .throughput import (
    PrAnalytics,
    PrSizeDistributionBucket,
    PullRequestThroughputData,
    ThroughputTrendPoint,
    calculate_pr_analytics,
    calculate_throughput_trend,
)

__all__ = [
    # DORA
    "DoraLevel",
    "DeploymentData",
    "PullRequestData",
    "DoraMetrics",
    "calculate_deployment_frequency",
    "calculate_lead_time",
    "calculate_change_failure_rate",
    "calculate_mttr",
    "calculate_dora_metrics",
    "classify_dora",
    # Lean
    "IssueFlowData",
    "CfdDataPoint",
    "LeadTimeDistributionBucket",
    "LeadTimeDistribution",
    "ThroughputDataPoint",
    "ScatterPoint",
    "calculate_cfd",
    "calculate_wip",
    "calculate_lead_time_distribution",
    "calculate_throughput",
    "calculate_lead_time_scatterplot",
    # Cycle Time
    "PullRequestCycleData",
    "PrCycleBreakdown",
    "CycleTimeBreakdown",
    "CycleTimeTrendPoint",
    "breakdown_single_pr",
    "calculate_cycle_time_breakdown",
    "calculate_cycle_time_trend",
    # Sprint
    "SprintData",
    "SprintOverview",
    "SprintSummary",
    "SprintComparison",
    "calculate_sprint_overview",
    "calculate_sprint_comparison",
    # Throughput
    "PullRequestThroughputData",
    "ThroughputTrendPoint",
    "PrSizeDistributionBucket",
    "PrAnalytics",
    "calculate_throughput_trend",
    "calculate_pr_analytics",
]
