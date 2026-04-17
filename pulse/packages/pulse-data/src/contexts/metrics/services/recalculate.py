"""Metrics recalculation service.

Shared orchestration used by:
  1. The metrics worker (event-driven, reacting to Kafka events)
  2. The admin recalculate endpoint (ad-hoc, forced refresh)

The service fetches entities from PULSE DB, calls pure domain functions,
and writes results to `metrics_snapshots` via snapshot_writer.

Design goals:
- Zero business logic — all math lives in `domain/*.py`
- Reusable: same entrypoints for event handlers and admin endpoint
- Safe: exceptions are captured per (metric_type, period) so one failure
  never nukes the whole run.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
    EngSprint,
)
from src.contexts.metrics.domain.cycle_time import (
    PullRequestCycleData,
    calculate_cycle_time_breakdown,
    calculate_cycle_time_trend,
)
from src.contexts.metrics.domain.dora import (
    DeploymentData,
    PullRequestData,
    calculate_dora_metrics,
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
from src.contexts.metrics.infrastructure.snapshot_writer import write_snapshot
from src.database import get_session

logger = logging.getLogger(__name__)


# Canonical period set. Must match `_VALID_PERIODS` in routes.py — otherwise
# the API will fall back to the nearest snapshot (INC-002 regression).
PERIODS: list[tuple[str, timedelta]] = [
    ("7d", timedelta(days=7)),
    ("14d", timedelta(days=14)),
    ("30d", timedelta(days=30)),
    ("60d", timedelta(days=60)),
    ("90d", timedelta(days=90)),
    ("120d", timedelta(days=120)),
]

ALL_METRIC_TYPES = ("throughput", "cycle_time", "dora", "lean", "sprint")


@dataclass
class RecalcResult:
    """Structured outcome of a recalculation run."""

    snapshots_written: int = 0
    recalculated: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    scanned: dict[str, dict[str, int]] = field(default_factory=dict)  # dry-run counts


def _resolve_periods(period: str | None) -> list[tuple[str, timedelta]]:
    if period is None or period == "all":
        return list(PERIODS)
    match = [p for p in PERIODS if p[0] == period]
    if not match:
        raise ValueError(f"Invalid period '{period}'. Use one of: {[p[0] for p in PERIODS]} or 'all'.")
    return match


def _resolve_metric_types(metric_type: str | None) -> list[str]:
    if metric_type is None or metric_type == "all":
        return list(ALL_METRIC_TYPES)
    if metric_type not in ALL_METRIC_TYPES:
        raise ValueError(f"Invalid metric_type '{metric_type}'. Use one of: {ALL_METRIC_TYPES} or 'all'.")
    return [metric_type]


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


async def _fetch_pull_requests(
    tenant_id: UUID, start: datetime, end: datetime
) -> list[EngPullRequest]:
    """Fetch PRs merged within the period (INC-001 fix: merged_at + is_merged)."""
    async with get_session(tenant_id) as session:
        stmt = (
            select(EngPullRequest)
            .where(
                EngPullRequest.tenant_id == tenant_id,
                EngPullRequest.is_merged.is_(True),
                EngPullRequest.merged_at.isnot(None),
                EngPullRequest.merged_at >= start,
                EngPullRequest.merged_at <= end,
            )
            .order_by(EngPullRequest.merged_at.desc())
            .limit(10000)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _fetch_issues_created(
    tenant_id: UUID, start: datetime, end: datetime
) -> list[EngIssue]:
    """Issues created within the period — used by CFD/WIP (flow state)."""
    async with get_session(tenant_id) as session:
        stmt = (
            select(EngIssue)
            .where(
                EngIssue.tenant_id == tenant_id,
                EngIssue.created_at >= start,
                EngIssue.created_at <= end,
            )
            .order_by(EngIssue.created_at.desc())
            .limit(10000)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _fetch_issues_completed(
    tenant_id: UUID, start: datetime, end: datetime
) -> list[EngIssue]:
    """Issues completed within the period — Throughput/Lead-Time/Scatterplot."""
    async with get_session(tenant_id) as session:
        stmt = (
            select(EngIssue)
            .where(
                EngIssue.tenant_id == tenant_id,
                EngIssue.completed_at.isnot(None),
                EngIssue.completed_at >= start,
                EngIssue.completed_at <= end,
            )
            .order_by(EngIssue.completed_at.desc())
            .limit(10000)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _fetch_deployments_production(
    tenant_id: UUID, start: datetime, end: datetime
) -> list[EngDeployment]:
    """Deployments in the period — PRODUCTION ONLY (INC-008 fix).

    DORA's Deployment Frequency and Change Failure Rate must measure
    production shipping cadence. Staging/dev/test deploys inflate DF and
    dilute CFR. Filter by `environment = 'production'`.
    """
    async with get_session(tenant_id) as session:
        stmt = (
            select(EngDeployment)
            .where(
                EngDeployment.tenant_id == tenant_id,
                EngDeployment.environment == "production",
                EngDeployment.deployed_at >= start,
                EngDeployment.deployed_at <= end,
            )
            .order_by(EngDeployment.deployed_at.desc())
            .limit(10000)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _fetch_sprints(tenant_id: UUID, limit: int = 20) -> list[EngSprint]:
    async with get_session(tenant_id) as session:
        stmt = (
            select(EngSprint)
            .where(EngSprint.tenant_id == tenant_id)
            .order_by(EngSprint.started_at.desc().nulls_last())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(reversed(result.scalars().all()))


# ---------------------------------------------------------------------------
# Per-metric-type recalculators
# ---------------------------------------------------------------------------


async def _recalc_throughput_and_cycle_time(
    tenant_id: UUID,
    team_id: UUID | None,
    period_label: str,
    period_start: datetime,
    period_end: datetime,
    result: RecalcResult,
    dry_run: bool,
    metric_types: list[str],
) -> None:
    prs = await _fetch_pull_requests(tenant_id, period_start, period_end)
    result.scanned.setdefault(period_label, {})["pull_requests"] = len(prs)

    if not prs:
        return

    cycle_data = [
        PullRequestCycleData(
            pr_id=str(pr.id),
            first_commit_at=pr.first_commit_at,
            first_review_at=pr.first_review_at,
            approved_at=pr.approved_at,
            merged_at=pr.merged_at,
            deployed_at=pr.deployed_at,
        )
        for pr in prs
    ]

    if "cycle_time" in metric_types:
        try:
            breakdown = calculate_cycle_time_breakdown(cycle_data)
            if not dry_run:
                await write_snapshot(
                    tenant_id=tenant_id,
                    team_id=team_id,
                    metric_type="cycle_time",
                    metric_name="breakdown",
                    value=asdict(breakdown),
                    period_start=period_start,
                    period_end=period_end,
                )
                result.snapshots_written += 1

            trend = calculate_cycle_time_trend(
                cycle_data, period_start.date(), period_end.date()
            )
            if not dry_run:
                await write_snapshot(
                    tenant_id=tenant_id,
                    team_id=team_id,
                    metric_type="cycle_time",
                    metric_name="trend",
                    value={"points": [asdict(p) for p in trend]},
                    period_start=period_start,
                    period_end=period_end,
                )
                result.snapshots_written += 1

            result.recalculated.setdefault("cycle_time", []).append(period_label)
        except Exception as exc:  # noqa: BLE001
            err = f"cycle_time/{period_label}: {exc}"
            logger.exception(err)
            result.errors.append(err)

    if "throughput" in metric_types:
        try:
            throughput_data = []
            for pr in prs:
                if pr.merged_at is None:
                    continue
                # INC-007 fix: compute cycle time inline so the throughput
                # trend can surface P50/P85 sparklines.
                cycle_hours: float | None = None
                if pr.first_commit_at is not None:
                    delta_seconds = (pr.merged_at - pr.first_commit_at).total_seconds()
                    if delta_seconds >= 0:
                        cycle_hours = delta_seconds / 3600.0
                throughput_data.append(
                    PullRequestThroughputData(
                        pr_id=str(pr.id),
                        repo=pr.repo,
                        merged_at=pr.merged_at,
                        additions=pr.additions,
                        deletions=pr.deletions,
                        files_changed=pr.files_changed,
                        cycle_time_hours=cycle_hours,
                        reviewer_count=len(pr.reviewers or []),
                    )
                )

            throughput_trend = calculate_throughput_trend(
                throughput_data, period_start.date(), period_end.date()
            )
            if not dry_run:
                await write_snapshot(
                    tenant_id=tenant_id,
                    team_id=team_id,
                    metric_type="throughput",
                    metric_name="trend",
                    value={"points": [asdict(p) for p in throughput_trend]},
                    period_start=period_start,
                    period_end=period_end,
                )
                result.snapshots_written += 1

            analytics = calculate_pr_analytics(throughput_data)
            if not dry_run:
                await write_snapshot(
                    tenant_id=tenant_id,
                    team_id=team_id,
                    metric_type="throughput",
                    metric_name="pr_analytics",
                    value=asdict(analytics),
                    period_start=period_start,
                    period_end=period_end,
                )
                result.snapshots_written += 1

            result.recalculated.setdefault("throughput", []).append(period_label)
        except Exception as exc:  # noqa: BLE001
            err = f"throughput/{period_label}: {exc}"
            logger.exception(err)
            result.errors.append(err)


async def _recalc_lean(
    tenant_id: UUID,
    team_id: UUID | None,
    period_label: str,
    period_start: datetime,
    period_end: datetime,
    result: RecalcResult,
    dry_run: bool,
) -> None:
    issues_created = await _fetch_issues_created(tenant_id, period_start, period_end)
    issues_completed = await _fetch_issues_completed(tenant_id, period_start, period_end)
    result.scanned.setdefault(period_label, {})["issues_created"] = len(issues_created)
    result.scanned.setdefault(period_label, {})["issues_completed"] = len(issues_completed)

    if not issues_created and not issues_completed:
        return

    def _to_flow(issue: EngIssue) -> IssueFlowData:
        return IssueFlowData(
            issue_id=str(issue.id),
            normalized_status=issue.normalized_status,
            status_transitions=issue.status_transitions or [],
            created_at=issue.created_at,
            started_at=issue.started_at,
            completed_at=issue.completed_at,
            lead_time_hours=getattr(issue, "lead_time_hours", None),
        )

    flow_created = [_to_flow(i) for i in issues_created]
    flow_completed = [_to_flow(i) for i in issues_completed]

    try:
        cfd = calculate_cfd(flow_created, period_start.date(), period_end.date())
        if not dry_run:
            await write_snapshot(
                tenant_id=tenant_id, team_id=team_id, metric_type="lean",
                metric_name="cfd",
                value={"points": [asdict(p) for p in cfd]},
                period_start=period_start, period_end=period_end,
            )
            result.snapshots_written += 1

        wip = calculate_wip(flow_created)
        if not dry_run:
            await write_snapshot(
                tenant_id=tenant_id, team_id=team_id, metric_type="lean",
                metric_name="wip",
                value={"wip_count": wip},
                period_start=period_start, period_end=period_end,
            )
            result.snapshots_written += 1

        lt_dist = calculate_lead_time_distribution(flow_completed)
        if not dry_run:
            await write_snapshot(
                tenant_id=tenant_id, team_id=team_id, metric_type="lean",
                metric_name="lead_time_distribution",
                value=asdict(lt_dist),
                period_start=period_start, period_end=period_end,
            )
            result.snapshots_written += 1

        throughput = calculate_throughput(
            flow_completed, period_start.date(), period_end.date()
        )
        if not dry_run:
            await write_snapshot(
                tenant_id=tenant_id, team_id=team_id, metric_type="lean",
                metric_name="throughput",
                value={"points": [asdict(p) for p in throughput]},
                period_start=period_start, period_end=period_end,
            )
            result.snapshots_written += 1

        scatter_points, p50, p85, p95 = calculate_lead_time_scatterplot(flow_completed)
        if not dry_run:
            await write_snapshot(
                tenant_id=tenant_id, team_id=team_id, metric_type="lean",
                metric_name="scatterplot",
                value={
                    "points": [asdict(p) for p in scatter_points],
                    "p50_hours": p50, "p85_hours": p85, "p95_hours": p95,
                },
                period_start=period_start, period_end=period_end,
            )
            result.snapshots_written += 1

        result.recalculated.setdefault("lean", []).append(period_label)
    except Exception as exc:  # noqa: BLE001
        err = f"lean/{period_label}: {exc}"
        logger.exception(err)
        result.errors.append(err)


async def _recalc_dora(
    tenant_id: UUID,
    team_id: UUID | None,
    period_label: str,
    period_start: datetime,
    period_end: datetime,
    result: RecalcResult,
    dry_run: bool,
) -> None:
    try:
        deploys = await _fetch_deployments_production(tenant_id, period_start, period_end)
        prs = await _fetch_pull_requests(tenant_id, period_start, period_end)
        result.scanned.setdefault(period_label, {})["prod_deployments"] = len(deploys)

        deploy_data = [
            DeploymentData(
                deployed_at=d.deployed_at,
                is_failure=d.is_failure,
                recovery_time_hours=d.recovery_time_hours,
            )
            for d in deploys
        ]
        pr_data = [
            PullRequestData(
                first_commit_at=pr.first_commit_at,
                merged_at=pr.merged_at,
                deployed_at=pr.deployed_at,
            )
            for pr in prs
        ]

        dora = calculate_dora_metrics(deploy_data, pr_data, period_start, period_end)
        if not dry_run:
            await write_snapshot(
                tenant_id=tenant_id, team_id=team_id, metric_type="dora",
                metric_name="all",
                value=asdict(dora),
                period_start=period_start, period_end=period_end,
            )
            result.snapshots_written += 1

        result.recalculated.setdefault("dora", []).append(period_label)
    except Exception as exc:  # noqa: BLE001
        err = f"dora/{period_label}: {exc}"
        logger.exception(err)
        result.errors.append(err)


async def _recalc_sprint(
    tenant_id: UUID,
    team_id: UUID | None,
    result: RecalcResult,
    dry_run: bool,
) -> None:
    """Sprint metrics ignore the `period` parameter — they are driven by sprint
    lifecycle timestamps. We always refresh the most recent 20 sprints."""
    try:
        sprints = await _fetch_sprints(tenant_id)
        result.scanned.setdefault("sprint", {})["sprints"] = len(sprints)
        if not sprints:
            return

        sprint_data_list = [
            SprintData(
                sprint_id=str(s.id),
                name=s.name,
                committed_items=s.committed_items,
                committed_points=s.committed_points,
                added_items=s.added_items,
                removed_items=s.removed_items,
                completed_items=s.completed_items,
                completed_points=s.completed_points,
                carried_over_items=s.carried_over_items,
            )
            for s in sprints
        ]

        now = datetime.now(timezone.utc)
        comparison = calculate_sprint_comparison(sprint_data_list)

        if not dry_run:
            await write_snapshot(
                tenant_id=tenant_id, team_id=team_id, metric_type="sprint",
                metric_name="comparison",
                value=asdict(comparison),
                period_start=now - timedelta(days=180),
                period_end=now,
            )
            result.snapshots_written += 1

        for sd in sprint_data_list:
            overview = calculate_sprint_overview(sd)
            sprint_obj = next((s for s in sprints if str(s.id) == sd.sprint_id), None)
            p_start = sprint_obj.started_at if sprint_obj and sprint_obj.started_at else now - timedelta(days=14)
            p_end = sprint_obj.completed_at if sprint_obj and sprint_obj.completed_at else now

            overview_dict = asdict(overview)
            overview_dict["sprint_name"] = sd.name
            overview_dict["started_at"] = p_start.isoformat()
            overview_dict["completed_at"] = p_end.isoformat()

            if not dry_run:
                await write_snapshot(
                    tenant_id=tenant_id, team_id=team_id, metric_type="sprint",
                    metric_name=f"overview_{sd.sprint_id}",
                    value=overview_dict,
                    period_start=p_start, period_end=p_end,
                )
                result.snapshots_written += 1

        result.recalculated.setdefault("sprint", []).append("all")
    except Exception as exc:  # noqa: BLE001
        err = f"sprint: {exc}"
        logger.exception(err)
        result.errors.append(err)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def recalculate(
    tenant_id: UUID,
    *,
    metric_type: str | None = "all",
    period: str | None = "all",
    team_id: UUID | None = None,
    dry_run: bool = False,
) -> RecalcResult:
    """Recalculate metric snapshots for a tenant.

    Args:
        tenant_id: Tenant UUID — RLS scope for all reads/writes.
        metric_type: 'throughput' | 'cycle_time' | 'dora' | 'lean' | 'sprint' | 'all'
        period: '7d' | '14d' | '30d' | '60d' | '90d' | '120d' | 'all'
        team_id: Optional team scope (None = tenant-level).
        dry_run: When True, only count how many entities would be processed —
            does NOT write snapshots.

    Returns:
        RecalcResult with snapshot count, per-type periods processed, errors.
    """
    metric_types = _resolve_metric_types(metric_type)
    periods = _resolve_periods(period)
    now = datetime.now(timezone.utc)
    result = RecalcResult()

    logger.info(
        "Recalc start tenant=%s types=%s periods=%s team=%s dry_run=%s",
        tenant_id, metric_types, [p[0] for p in periods], team_id, dry_run,
    )

    # Sprint is period-independent — run it once.
    if "sprint" in metric_types:
        await _recalc_sprint(tenant_id, team_id, result, dry_run)

    # For everything else, iterate periods.
    wants_pr_metrics = any(m in metric_types for m in ("throughput", "cycle_time"))
    wants_lean = "lean" in metric_types
    wants_dora = "dora" in metric_types

    for label, delta in periods:
        period_start = now - delta
        period_end = now

        if wants_pr_metrics:
            await _recalc_throughput_and_cycle_time(
                tenant_id, team_id, label, period_start, period_end,
                result, dry_run, metric_types,
            )
        if wants_lean:
            await _recalc_lean(
                tenant_id, team_id, label, period_start, period_end, result, dry_run,
            )
        if wants_dora:
            await _recalc_dora(
                tenant_id, team_id, label, period_start, period_end, result, dry_run,
            )

    logger.info(
        "Recalc done tenant=%s snapshots_written=%d errors=%d",
        tenant_id, result.snapshots_written, len(result.errors),
    )
    return result
