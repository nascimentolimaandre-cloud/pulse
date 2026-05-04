"""Home dashboard on-demand metrics computation.

Was the only on-demand service before INC-015. Now lives next to its
deep-dive siblings (`dora.py`, `lean.py`, `cycle_time.py`, `throughput.py`)
in the `on_demand/` package.

Refactored INC-015: all DB access now goes through `MetricsRepository`.
The previous module-level `_fetch_*` helpers were lifted into repo
methods so each on-demand service shares the same data path.

The shape of the returned dict is unchanged — `routes._build_home_response`
still consumes it as before.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from src.contexts.metrics.domain.cycle_time import (
    PullRequestCycleData,
    calculate_cycle_time_breakdown,
)
from src.contexts.metrics.domain.dora import (
    DeploymentData,
    PullRequestData,
    calculate_dora_metrics,
)
from src.contexts.metrics.domain.lean import (
    IssueFlowData,
    calculate_wip,
)
from src.contexts.metrics.domain.throughput import (
    PullRequestThroughputData,
    calculate_pr_analytics,
)
from src.contexts.metrics.repositories import MetricsRepository
from src.database import get_session

logger = logging.getLogger(__name__)


async def compute_home_metrics_on_demand(
    tenant_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    squad_key: str | None = None,
) -> dict[str, Any]:
    """Compute all 8 home KPI values + overall DORA level on the fly.

    Returns a dict shaped so `routes.get_home_metrics` can consume it
    exactly the way it consumes the snapshot dicts. Keys match the
    worker's snapshot layout so the same extraction code works.
    """
    squad_key_upper = squad_key.upper() if squad_key else None

    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)

        # ── PRs (merged in window, optionally squad-filtered) ──
        prs = await repo.get_prs_in_window(
            tenant_id, period_start, period_end, squad_key=squad_key_upper,
        )

        # ── Deployments (prod, squad-scoped via repo intersection) ──
        deploys = await repo.get_deployments_by_squad(
            tenant_id, period_start, period_end, squad_key=squad_key_upper,
        )

        # ── Issues created in window (used for WIP) ──
        issues_created = await repo.get_issues_in_window(
            tenant_id, period_start, period_end,
            squad_key=squad_key_upper, date_field="created_at",
        )

    # ── Cycle-time breakdown (P50/P85) ──
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
    try:
        cycle_breakdown = calculate_cycle_time_breakdown(cycle_data)
        cycle_breakdown_value = asdict(cycle_breakdown)
    except Exception:  # noqa: BLE001
        logger.exception("cycle_time_breakdown failed in on-demand compute")
        cycle_breakdown_value = {}

    # ── Throughput PR analytics ──
    throughput_data = []
    for pr in prs:
        if pr.merged_at is None:
            continue
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
    try:
        pr_analytics = calculate_pr_analytics(throughput_data)
        pr_analytics_value = asdict(pr_analytics)
    except Exception:  # noqa: BLE001
        logger.exception("pr_analytics failed in on-demand compute")
        pr_analytics_value = {}

    # ── DORA ──
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
    try:
        dora = calculate_dora_metrics(deploy_data, pr_data, period_start, period_end)
        dora_value = asdict(dora)
    except Exception:  # noqa: BLE001
        logger.exception("dora failed in on-demand compute")
        dora_value = {}

    # ── WIP ──
    flow_data = [
        IssueFlowData(
            issue_id=str(i.id),
            normalized_status=i.normalized_status,
            status_transitions=i.status_transitions or [],
            created_at=i.created_at,
            started_at=i.started_at,
            completed_at=i.completed_at,
            lead_time_hours=getattr(i, "lead_time_hours", None),
        )
        for i in issues_created
    ]
    try:
        wip_count = calculate_wip(flow_data)
    except Exception:  # noqa: BLE001
        logger.exception("wip failed in on-demand compute")
        wip_count = 0

    return {
        "dora_all": dora_value,
        "cycle_time_breakdown": cycle_breakdown_value,
        "throughput_pr_analytics": pr_analytics_value,
        "lean_wip": {"wip_count": wip_count},
        "pr_count_in_window": len(prs),
        "deploy_count_in_window": len(deploys),
    }


async def compute_previous_period(
    tenant_id: UUID,
    *,
    current_start: datetime,
    current_end: datetime,
    squad_key: str | None = None,
) -> dict[str, Any]:
    """Previous-period snapshot (same length, immediately before current).
    Used for home trend arrows."""
    window = current_end - current_start
    prev_end = current_start
    prev_start = prev_end - window
    return await compute_home_metrics_on_demand(
        tenant_id,
        period_start=prev_start,
        period_end=prev_end,
        squad_key=squad_key,
    )
