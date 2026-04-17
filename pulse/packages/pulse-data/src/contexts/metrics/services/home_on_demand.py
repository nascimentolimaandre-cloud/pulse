"""On-demand home-metrics computation.

The snapshot-based path (metrics_snapshots) is fine for standard (squad_key=None,
team_id=None, period ∈ {7d,14d,30d,60d,90d,120d}) lookups — pre-calculated by the
metrics worker. But two cases break it:

1. **Squad-level filtering** (BUG 1): the Home combobox uses 27 dynamic squad keys
   derived from PR title regex (e.g. "okm", "sdi"). These are NOT team UUIDs, so
   the snapshot writer has never written per-squad snapshots. We compute on the
   fly by filtering PRs whose title matches the project key.

2. **Custom date range** (BUG 3): the user can pick arbitrary start/end dates.
   No pre-calculated snapshot exists for those windows. Compute on the fly.

This module is deliberately narrow — it only covers the Home KPI surface
(the 8 cards + overall DORA level). Deep-dive pages (/dora, /cycle-time, etc.)
still use the snapshot path; they gain custom-period support separately via
_compute_period_on_demand but do not yet support squad_key. See FDD-DSH-060.

Anti-surveillance: this service never groups by author or reviewer. All
aggregates are PR-title-based (squad granularity = project key), which is
the same granularity the pipeline-monitor uses.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
)
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
from src.database import get_session

logger = logging.getLogger(__name__)

# PR title project-key extraction — same pattern used by /pipeline/teams.
# e.g. "OKM-123: fix login" -> project_key="OKM"
_TITLE_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]+)-\d+")


def _extract_project_key(title: str | None) -> str | None:
    if not title:
        return None
    m = _TITLE_KEY_RE.search(title)
    return m.group(1).upper() if m else None


async def _fetch_prs_by_squad(
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    squad_key: str,
) -> list[EngPullRequest]:
    """Fetch merged PRs whose title references the given squad's project key."""
    async with get_session(tenant_id) as session:
        # Filter at the DB layer via ILIKE to avoid pulling 10k PRs and filtering
        # in Python. We still verify with the regex in Python afterwards because
        # ILIKE 'OKM-%' also matches 'OKM-SOMETHING' (no digit boundary). This
        # keeps network traffic tight while preserving the same semantics as
        # the /pipeline/teams regex.
        stmt = (
            select(EngPullRequest)
            .where(
                EngPullRequest.tenant_id == tenant_id,
                EngPullRequest.is_merged.is_(True),
                EngPullRequest.merged_at.isnot(None),
                EngPullRequest.merged_at >= start,
                EngPullRequest.merged_at <= end,
                EngPullRequest.title.op("~*")(rf"\m{re.escape(squad_key)}-\d+"),
            )
            .order_by(EngPullRequest.merged_at.desc())
            .limit(10000)
        )
        result = await session.execute(stmt)
        prs = list(result.scalars().all())

    # Extra Python-side filter (defensive — regex already did the work).
    return [pr for pr in prs if _extract_project_key(pr.title) == squad_key]


async def _fetch_prs_all(
    tenant_id: UUID, start: datetime, end: datetime
) -> list[EngPullRequest]:
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


async def _fetch_deployments_by_squad(
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    squad_key: str | None,
) -> list[EngDeployment]:
    """Production deployments, optionally scoped to repos that are active for
    the given squad. Squad → repo mapping is derived via PR title + repo join
    (same pattern as /pipeline/teams).
    """
    async with get_session(tenant_id) as session:
        if squad_key is None:
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

        # Squad-scoped: intersect with repos that had ≥1 PR referencing the
        # squad in the last 90d (same window /pipeline/teams uses for the
        # active-squad list). We compare against split_part(repo,'/',2) because
        # eng_deployments.repo is stored as a bare repo name while
        # eng_pull_requests.repo includes the owner prefix.
        from sqlalchemy import func, text

        # Discover repos active for this squad in the last 90d.
        repo_rows = await session.execute(
            text(r"""
                SELECT DISTINCT split_part(pr.repo, '/', 2) AS repo_name
                FROM eng_pull_requests pr
                WHERE pr.tenant_id = :tenant_id
                  AND pr.title ~* :pattern
                  AND pr.created_at >= NOW() - INTERVAL '90 days'
            """),
            {
                "tenant_id": tenant_id,
                "pattern": rf"\m{re.escape(squad_key)}-\d+",
            },
        )
        repo_names = [r.repo_name for r in repo_rows.fetchall() if r.repo_name]
        if not repo_names:
            return []

        stmt = (
            select(EngDeployment)
            .where(
                EngDeployment.tenant_id == tenant_id,
                EngDeployment.environment == "production",
                EngDeployment.deployed_at >= start,
                EngDeployment.deployed_at <= end,
                func.lower(EngDeployment.repo).in_([r.lower() for r in repo_names]),
            )
            .order_by(EngDeployment.deployed_at.desc())
            .limit(10000)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _fetch_issues_created(
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    squad_key: str | None,
) -> list[EngIssue]:
    """Issues created in the window — scoped by Jira project_key when the
    squad key equals a Jira project (which is the common case — the 27 squad
    keys are Jira project keys)."""
    async with get_session(tenant_id) as session:
        stmt = select(EngIssue).where(
            EngIssue.tenant_id == tenant_id,
            EngIssue.created_at >= start,
            EngIssue.created_at <= end,
        )
        if squad_key is not None:
            stmt = stmt.where(EngIssue.project_key == squad_key.upper())
        stmt = stmt.order_by(EngIssue.created_at.desc()).limit(10000)
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def compute_home_metrics_on_demand(
    tenant_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    squad_key: str | None = None,
) -> dict[str, Any]:
    """Compute all 8 home KPI values + overall DORA level on the fly.

    Returns a dict shaped so `routes.get_home_metrics` can consume it exactly
    the way it consumes the snapshot dicts. Keys match the worker's snapshot
    layout so the same extraction code works.

    Args:
        tenant_id: Tenant scope (RLS).
        period_start, period_end: The measurement window (any length).
        squad_key: Optional squad/project key (e.g. "OKM"). None = tenant-wide.

    Returns: dict with keys: dora_all, cycle_time_breakdown, throughput_pr_analytics,
             lean_wip — shapes matching the snapshot `.value` fields.
    """
    squad_key_upper = squad_key.upper() if squad_key else None

    # ── Pull Requests (merged, in window, optionally squad-filtered) ──
    if squad_key_upper:
        prs = await _fetch_prs_by_squad(tenant_id, period_start, period_end, squad_key_upper)
    else:
        prs = await _fetch_prs_all(tenant_id, period_start, period_end)

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
    deploys = await _fetch_deployments_by_squad(
        tenant_id, period_start, period_end, squad_key_upper
    )
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

    # ── WIP (open issues right now for the squad) ──
    issues_created = await _fetch_issues_created(
        tenant_id, period_start, period_end, squad_key_upper
    )
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
