"""Metrics Worker.

Consumes normalized engineering data events from Kafka,
runs metric calculations (pure functions), and writes
results to the metrics_snapshots table.

Pipeline: Kafka (domain.*.normalized) -> Metrics Domain Functions -> metrics_snapshots

Triggered by MSK Event Source Mapping in Lambda,
or runs as a long-lived consumer locally.

The worker batches incoming events and recalculates affected metrics
for the relevant team and period. Calculations use pure functions from
the metrics domain layer — no DB access happens in domain code.
"""

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.config import settings
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
from src.contexts.metrics.infrastructure.snapshot_writer import (
    write_snapshot,
    write_snapshots_batch,
)
from src.database import get_session
from src.shared.kafka import (
    TOPIC_DEPLOYMENT_NORMALIZED,
    TOPIC_ISSUE_NORMALIZED,
    TOPIC_PR_NORMALIZED,
    TOPIC_SPRINT_NORMALIZED,
)
from src.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

CONSUMED_TOPICS = [
    TOPIC_PR_NORMALIZED,
    TOPIC_ISSUE_NORMALIZED,
    TOPIC_DEPLOYMENT_NORMALIZED,
    TOPIC_SPRINT_NORMALIZED,
]

# Default periods for metric calculation
_PERIODS = [
    ("7d", timedelta(days=7)),
    ("14d", timedelta(days=14)),
    ("30d", timedelta(days=30)),
    ("90d", timedelta(days=90)),
]


class MetricsWorker(BaseWorker):
    """Consumes domain events and triggers metric recalculations.

    On each normalized event, the worker:
    1. Identifies the affected tenant
    2. Queries PULSE DB for all relevant data in the period
    3. Runs pure metric functions
    4. Writes results to metrics_snapshots via upsert
    """

    def __init__(self) -> None:
        super().__init__(
            topics=CONSUMED_TOPICS,
            group_id="pulse-metrics-worker",
        )
        self._tenant_id = UUID(settings.default_tenant_id)

    async def process_message(self, topic: str, key: str | None, value: dict[str, Any]) -> None:
        """Process a single normalized domain event.

        Routes to the appropriate handler based on topic.
        Each handler recalculates metrics affected by this event type.
        """
        logger.debug("Processing message from %s key=%s", topic, key)

        try:
            if topic == TOPIC_PR_NORMALIZED:
                await self._handle_pr_event(value)
            elif topic == TOPIC_ISSUE_NORMALIZED:
                await self._handle_issue_event(value)
            elif topic == TOPIC_DEPLOYMENT_NORMALIZED:
                await self._handle_deployment_event(value)
            elif topic == TOPIC_SPRINT_NORMALIZED:
                await self._handle_sprint_event(value)
            else:
                logger.warning("Unknown topic: %s", topic)
        except Exception:
            logger.exception("Error processing %s event key=%s", topic, key)

    async def _handle_pr_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized PR event -- recalculate cycle time, throughput, DORA lead time."""
        tenant_id = UUID(value.get("tenant_id", str(self._tenant_id)))
        now = datetime.now(timezone.utc)

        for label, delta in _PERIODS:
            period_start = now - delta
            period_end = now

            # Fetch all PRs for the period
            prs = await self._fetch_pull_requests(tenant_id, period_start, period_end)

            if not prs:
                continue

            # Cycle Time Breakdown
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
            breakdown = calculate_cycle_time_breakdown(cycle_data)
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="cycle_time",
                metric_name="breakdown",
                value=asdict(breakdown),
                period_start=period_start,
                period_end=period_end,
            )

            # Cycle Time Trend
            trend = calculate_cycle_time_trend(
                cycle_data, period_start.date(), period_end.date()
            )
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="cycle_time",
                metric_name="trend",
                value={"points": [asdict(p) for p in trend]},
                period_start=period_start,
                period_end=period_end,
            )

            # Throughput Trend
            throughput_data = [
                PullRequestThroughputData(
                    pr_id=str(pr.id),
                    repo=pr.repo,
                    merged_at=pr.merged_at,
                    additions=pr.additions,
                    deletions=pr.deletions,
                    files_changed=pr.files_changed,
                    cycle_time_hours=None,  # Computed inline
                    reviewer_count=len(pr.reviewers or []),
                )
                for pr in prs
                if pr.merged_at is not None
            ]
            throughput_trend = calculate_throughput_trend(
                throughput_data, period_start.date(), period_end.date()
            )
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="throughput",
                metric_name="trend",
                value={"points": [asdict(p) for p in throughput_trend]},
                period_start=period_start,
                period_end=period_end,
            )

            # PR Analytics
            analytics = calculate_pr_analytics(throughput_data)
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="throughput",
                metric_name="pr_analytics",
                value=asdict(analytics),
                period_start=period_start,
                period_end=period_end,
            )

        logger.info("Recalculated PR-related metrics for all periods")

    async def _handle_issue_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized issue event -- recalculate lean metrics."""
        tenant_id = UUID(value.get("tenant_id", str(self._tenant_id)))
        now = datetime.now(timezone.utc)

        for label, delta in _PERIODS:
            period_start = now - delta
            period_end = now

            issues = await self._fetch_issues(tenant_id, period_start, period_end)
            if not issues:
                continue

            flow_data = [
                IssueFlowData(
                    issue_id=str(issue.id),
                    normalized_status=issue.normalized_status,
                    status_transitions=issue.status_transitions or [],
                    created_at=issue.created_at,
                    started_at=issue.started_at,
                    completed_at=issue.completed_at,
                    lead_time_hours=getattr(issue, "lead_time_hours", None),
                )
                for issue in issues
            ]

            # CFD
            cfd = calculate_cfd(flow_data, period_start.date(), period_end.date())
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="lean",
                metric_name="cfd",
                value={"points": [asdict(p) for p in cfd]},
                period_start=period_start,
                period_end=period_end,
            )

            # WIP
            wip = calculate_wip(flow_data)
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="lean",
                metric_name="wip",
                value={"wip_count": wip},
                period_start=period_start,
                period_end=period_end,
            )

            # Lead Time Distribution
            lt_dist = calculate_lead_time_distribution(flow_data)
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="lean",
                metric_name="lead_time_distribution",
                value=asdict(lt_dist),
                period_start=period_start,
                period_end=period_end,
            )

            # Throughput (issue-based)
            throughput = calculate_throughput(
                flow_data, period_start.date(), period_end.date()
            )
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="lean",
                metric_name="throughput",
                value={"points": [asdict(p) for p in throughput]},
                period_start=period_start,
                period_end=period_end,
            )

            # Lead Time Scatterplot
            scatter_points, scatter_p50, scatter_p85, scatter_p95 = (
                calculate_lead_time_scatterplot(flow_data)
            )
            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="lean",
                metric_name="scatterplot",
                value={
                    "points": [asdict(p) for p in scatter_points],
                    "p50_hours": scatter_p50,
                    "p85_hours": scatter_p85,
                    "p95_hours": scatter_p95,
                },
                period_start=period_start,
                period_end=period_end,
            )

        logger.info("Recalculated issue-related lean metrics for all periods")

    async def _handle_deployment_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized deployment event -- recalculate DORA metrics."""
        tenant_id = UUID(value.get("tenant_id", str(self._tenant_id)))
        now = datetime.now(timezone.utc)

        for label, delta in _PERIODS:
            period_start = now - delta
            period_end = now

            deploys = await self._fetch_deployments(tenant_id, period_start, period_end)
            prs = await self._fetch_pull_requests(tenant_id, period_start, period_end)

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

            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="dora",
                metric_name="all",
                value=asdict(dora),
                period_start=period_start,
                period_end=period_end,
            )

        logger.info("Recalculated DORA metrics for all periods")

    async def _handle_sprint_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized sprint event -- recalculate sprint metrics."""
        tenant_id = UUID(value.get("tenant_id", str(self._tenant_id)))

        sprints = await self._fetch_sprints(tenant_id)
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

        # Sprint comparison (across all recent sprints)
        comparison = calculate_sprint_comparison(sprint_data_list)
        now = datetime.now(timezone.utc)

        await write_snapshot(
            tenant_id=tenant_id,
            team_id=None,
            metric_type="sprint",
            metric_name="comparison",
            value=asdict(comparison),
            period_start=now - timedelta(days=180),
            period_end=now,
        )

        # Individual sprint overviews (enriched with sprint metadata)
        for sd in sprint_data_list:
            overview = calculate_sprint_overview(sd)
            # Use a synthetic period based on sprint data
            sprint_obj = next(
                (s for s in sprints if str(s.id) == sd.sprint_id), None
            )
            p_start = sprint_obj.started_at if sprint_obj and sprint_obj.started_at else now - timedelta(days=14)
            p_end = sprint_obj.completed_at if sprint_obj and sprint_obj.completed_at else now

            # Enrich with sprint metadata for the frontend
            overview_dict = asdict(overview)
            overview_dict["sprint_name"] = sd.name
            overview_dict["started_at"] = p_start.isoformat()
            overview_dict["completed_at"] = p_end.isoformat()

            await write_snapshot(
                tenant_id=tenant_id,
                team_id=None,
                metric_type="sprint",
                metric_name=f"overview_{sd.sprint_id}",
                value=overview_dict,
                period_start=p_start,
                period_end=p_end,
            )

        logger.info("Recalculated sprint metrics for %d sprints", len(sprints))

    # ---------------------------------------------------------------
    # Data fetchers — read from PULSE DB for metric recalculation
    # ---------------------------------------------------------------

    async def _fetch_pull_requests(
        self, tenant_id: UUID, start: datetime, end: datetime
    ) -> list[EngPullRequest]:
        """Fetch PRs from PULSE DB for the given period."""
        async with get_session(tenant_id) as session:
            stmt = (
                select(EngPullRequest)
                .where(
                    EngPullRequest.tenant_id == tenant_id,
                    EngPullRequest.created_at >= start,
                    EngPullRequest.created_at <= end,
                )
                .order_by(EngPullRequest.created_at.desc())
                .limit(5000)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _fetch_issues(
        self, tenant_id: UUID, start: datetime, end: datetime
    ) -> list[EngIssue]:
        """Fetch issues from PULSE DB for the given period."""
        async with get_session(tenant_id) as session:
            stmt = (
                select(EngIssue)
                .where(
                    EngIssue.tenant_id == tenant_id,
                    EngIssue.created_at >= start,
                    EngIssue.created_at <= end,
                )
                .order_by(EngIssue.created_at.desc())
                .limit(5000)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _fetch_deployments(
        self, tenant_id: UUID, start: datetime, end: datetime
    ) -> list[EngDeployment]:
        """Fetch deployments from PULSE DB for the given period."""
        async with get_session(tenant_id) as session:
            stmt = (
                select(EngDeployment)
                .where(
                    EngDeployment.tenant_id == tenant_id,
                    EngDeployment.deployed_at >= start,
                    EngDeployment.deployed_at <= end,
                )
                .order_by(EngDeployment.deployed_at.desc())
                .limit(5000)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _fetch_sprints(
        self, tenant_id: UUID, limit: int = 20
    ) -> list[EngSprint]:
        """Fetch recent sprints from PULSE DB."""
        async with get_session(tenant_id) as session:
            stmt = (
                select(EngSprint)
                .where(EngSprint.tenant_id == tenant_id)
                .order_by(EngSprint.started_at.desc().nulls_last())
                .limit(limit)
            )
            result = await session.execute(stmt)
            # Reverse to get oldest-first order for comparison
            return list(reversed(result.scalars().all()))


async def run_worker() -> None:
    """Run the metrics worker as a long-lived consumer (local dev)."""
    worker = MetricsWorker()
    logger.info("Starting metrics worker...")
    try:
        await worker.start()
    except asyncio.CancelledError:
        logger.info("Metrics worker cancelled")
    finally:
        await worker.stop()
        logger.info("Metrics worker stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run_worker())
