"""Repository for BC4 -- Metrics data access.

Provides async read methods for fetching engineering data
that metrics domain functions need as input.

All queries are tenant-scoped via RLS (set by get_session).

## DDD bounded-context note (FDD-PIPE-002)

This repository deliberately reaches into the `engineering_data` bounded
context's models (`EngPullRequest`, `EngDeployment`, `EngIssue`,
`EngSprint`). It is a **consumer-side repository** — it owns the read
paths that the metrics context needs to compute KPIs.

The cleaner DDD alternative (an `EngineeringDataRepository` exposed by
the engineering_data context, composed by this one) is a defensible
refactor but out of scope for INC-015. The compromise is documented
here so future maintainers know it's intentional, not accidental.
"""

import logging
import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
    EngSprint,
)
from src.contexts.metrics.infrastructure.models import MetricsSnapshot

logger = logging.getLogger(__name__)

# INC-015 — regex matching squad project key in PR titles. Same pattern as
# /pipeline/teams uses; keeping it identical guarantees the squad list in
# the combobox matches what we resolve here.
_TITLE_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]+)-\d+")


class MetricsRepository:
    """Reads engineering data for metric calculations.

    This repository fetches raw data; the actual metric math
    happens in pure domain functions (no DB access in domain layer).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -----------------------------------------------------------------
    # INC-015 — squad-aware fetchers (used by on_demand services)
    # -----------------------------------------------------------------
    #
    # The squad concept here is a Jira project key extracted from PR
    # titles (e.g. "OKM-1234: fix login" → squad "OKM"). This mirrors
    # the /pipeline/teams convention and the home on-demand path.
    #
    # All `*_by_squad` methods accept a `squad_key=None` shortcut that
    # falls back to tenant-wide. Callers can use one method either way
    # without branching at the service layer.

    @staticmethod
    def extract_project_key(title: str | None) -> str | None:
        """Extract Jira project key from a PR title (e.g. "OKM" from "OKM-12: foo").

        Static helper — exposed so service tests can stub squad inference
        without instantiating a repository. Same regex as /pipeline/teams.
        """
        if not title:
            return None
        m = _TITLE_KEY_RE.search(title)
        return m.group(1).upper() if m else None

    async def get_prs_in_window(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        squad_key: str | None = None,
        *,
        limit: int = 10000,
    ) -> list[EngPullRequest]:
        """Fetch MERGED PRs in window (`merged_at`-based, not `created_at`).

        INC-001 alignment — uses `merged_at` so long-cycle PRs that were
        opened before the window but merged inside it are correctly
        included. The tenant-wide variant matches what the metrics worker
        wrote into snapshots; the per-squad variant filters by PR title
        regex (squad_key = Jira project key).

        Args:
            tenant_id: Tenant UUID.
            start_date / end_date: `merged_at` window (inclusive).
            squad_key: Optional Jira project key (e.g. "OKM"). None =
                tenant-wide.
            limit: Hard cap (defensive). Default 10k matches the prior
                home_on_demand behaviour.
        """
        conditions = [
            EngPullRequest.tenant_id == tenant_id,
            EngPullRequest.is_merged.is_(True),
            EngPullRequest.merged_at.isnot(None),
            EngPullRequest.merged_at >= start_date,
            EngPullRequest.merged_at <= end_date,
        ]

        if squad_key:
            # DB-side regex narrows the result set; the Python-side filter
            # in the loop below is defensive (Postgres `~*` already enforces
            # the digit boundary, but a regex match here is cheap).
            conditions.append(
                EngPullRequest.title.op("~*")(rf"\m{re.escape(squad_key)}-\d+")
            )

        stmt = (
            select(EngPullRequest)
            .where(and_(*conditions))
            .order_by(EngPullRequest.merged_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        prs = list(result.scalars().all())

        if squad_key:
            squad_key_upper = squad_key.upper()
            prs = [
                pr for pr in prs
                if self.extract_project_key(pr.title) == squad_key_upper
            ]
        return prs

    async def get_repos_active_for_squad(
        self,
        tenant_id: UUID,
        squad_key: str,
        *,
        lookback_days: int = 90,
    ) -> list[str]:
        """Bare repo names (no owner prefix) that had ≥1 PR referencing
        the squad in the lookback window.

        Used by `get_deployments_by_squad` to scope deploys to repos the
        squad actually works on. Deployments don't carry a squad label —
        we infer via PR title regex + repo intersection (same pattern as
        /pipeline/teams).
        """
        rows = await self._session.execute(
            text(r"""
                SELECT DISTINCT split_part(pr.repo, '/', 2) AS repo_name
                FROM eng_pull_requests pr
                WHERE pr.tenant_id = :tenant_id
                  AND pr.title ~* :pattern
                  AND pr.created_at >= NOW() - (:days || ' days')::interval
            """),
            {
                "tenant_id": tenant_id,
                "pattern": rf"\m{re.escape(squad_key)}-\d+",
                "days": str(lookback_days),
            },
        )
        return [r.repo_name for r in rows.fetchall() if r.repo_name]

    async def get_deployments_by_squad(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        squad_key: str | None = None,
        *,
        environment: str = "production",
        limit: int = 10000,
    ) -> list[EngDeployment]:
        """Production deployments in window, optionally scoped to repos
        active for the given squad.

        Squad scoping resolves to the set of repo names returned by
        `get_repos_active_for_squad`. If the squad has no active repos
        in the lookback window, returns an empty list (instead of all
        prod deploys — matches home_on_demand precedent).
        """
        conditions = [
            EngDeployment.tenant_id == tenant_id,
            EngDeployment.deployed_at >= start_date,
            EngDeployment.deployed_at <= end_date,
        ]
        if environment:
            conditions.append(EngDeployment.environment == environment)

        if squad_key:
            repo_names = await self.get_repos_active_for_squad(tenant_id, squad_key)
            if not repo_names:
                return []
            conditions.append(
                func.lower(EngDeployment.repo).in_([r.lower() for r in repo_names])
            )

        stmt = (
            select(EngDeployment)
            .where(and_(*conditions))
            .order_by(EngDeployment.deployed_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_issues_in_window(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        squad_key: str | None = None,
        *,
        date_field: str = "created_at",
        limit: int = 10000,
    ) -> list[EngIssue]:
        """Issues filtered by date_field (`created_at` for CFD/WIP,
        `completed_at` for Throughput/Lead-Time-Distribution per
        INC-001 / INC-010), optionally scoped to a Jira project key.

        Args:
            date_field: Which timestamp to filter on. Must be either
                `'created_at'` (default) or `'completed_at'`. Other
                fields raise ValueError so we don't accept dynamic
                column names from untrusted sources.
        """
        if date_field not in ("created_at", "completed_at"):
            raise ValueError(
                f"date_field must be 'created_at' or 'completed_at', got {date_field!r}"
            )

        column = (
            EngIssue.completed_at if date_field == "completed_at"
            else EngIssue.created_at
        )

        conditions = [
            EngIssue.tenant_id == tenant_id,
            column.isnot(None) if date_field == "completed_at" else column.is_not(None),
            column >= start_date,
            column <= end_date,
        ]
        if squad_key:
            conditions.append(EngIssue.project_key == squad_key.upper())

        stmt = (
            select(EngIssue)
            .where(and_(*conditions))
            .order_by(column.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # -----------------------------------------------------------------
    # Legacy methods (used by the snapshot writer + sprint metrics)
    # -----------------------------------------------------------------

    async def get_pull_requests(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        repo: str | None = None,
    ) -> list[EngPullRequest]:
        """Fetch pull requests within the given date range."""
        conditions = [
            EngPullRequest.tenant_id == tenant_id,
            EngPullRequest.created_at >= start_date,
            EngPullRequest.created_at <= end_date,
        ]
        if repo:
            conditions.append(EngPullRequest.repo == repo)

        stmt = (
            select(EngPullRequest)
            .where(and_(*conditions))
            .order_by(EngPullRequest.created_at.desc())
            .limit(5000)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_deployments(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        environment: str = "production",
    ) -> list[EngDeployment]:
        """Fetch deployments within the given date range."""
        conditions = [
            EngDeployment.tenant_id == tenant_id,
            EngDeployment.deployed_at >= start_date,
            EngDeployment.deployed_at <= end_date,
        ]
        if environment:
            conditions.append(EngDeployment.environment == environment)

        stmt = (
            select(EngDeployment)
            .where(and_(*conditions))
            .order_by(EngDeployment.deployed_at.desc())
            .limit(5000)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_issues(
        self,
        tenant_id: UUID,
        start_date: datetime,
        end_date: datetime,
        project_key: str | None = None,
    ) -> list[EngIssue]:
        """Fetch issues within the given date range."""
        conditions = [
            EngIssue.tenant_id == tenant_id,
            EngIssue.created_at >= start_date,
            EngIssue.created_at <= end_date,
        ]
        if project_key:
            conditions.append(EngIssue.project_key == project_key)

        stmt = (
            select(EngIssue)
            .where(and_(*conditions))
            .order_by(EngIssue.created_at.desc())
            .limit(5000)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_sprints(
        self,
        tenant_id: UUID,
        board_id: str | None = None,
        limit: int = 10,
    ) -> list[EngSprint]:
        """Fetch recent sprints, optionally filtered by board."""
        conditions = [EngSprint.tenant_id == tenant_id]
        if board_id:
            conditions.append(EngSprint.board_id == board_id)

        stmt = (
            select(EngSprint)
            .where(and_(*conditions))
            .order_by(EngSprint.started_at.desc().nulls_last())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_snapshot(
        self,
        tenant_id: UUID,
        metric_type: str,
        metric_name: str,
        period_start: datetime,
        period_end: datetime,
        team_id: UUID | None = None,
    ) -> MetricsSnapshot | None:
        """Fetch a specific metrics snapshot."""
        conditions = [
            MetricsSnapshot.tenant_id == tenant_id,
            MetricsSnapshot.metric_type == metric_type,
            MetricsSnapshot.metric_name == metric_name,
            MetricsSnapshot.period_start == period_start,
            MetricsSnapshot.period_end == period_end,
        ]
        if team_id:
            conditions.append(MetricsSnapshot.team_id == team_id)
        else:
            conditions.append(MetricsSnapshot.team_id.is_(None))

        stmt = select(MetricsSnapshot).where(and_(*conditions))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_snapshots(
        self,
        tenant_id: UUID,
        metric_type: str,
        team_id: UUID | None = None,
        limit: int = 10,
    ) -> list[MetricsSnapshot]:
        """Fetch the most recent snapshots for a metric type."""
        conditions = [
            MetricsSnapshot.tenant_id == tenant_id,
            MetricsSnapshot.metric_type == metric_type,
        ]
        if team_id:
            conditions.append(MetricsSnapshot.team_id == team_id)
        else:
            conditions.append(MetricsSnapshot.team_id.is_(None))

        stmt = (
            select(MetricsSnapshot)
            .where(and_(*conditions))
            .order_by(MetricsSnapshot.calculated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_snapshots_before_date(
        self,
        tenant_id: UUID,
        metric_type: str,
        before_date: datetime,
        team_id: UUID | None = None,
        limit: int = 20,
    ) -> list[MetricsSnapshot]:
        """Fetch most recent snapshots for a metric type calculated before a date.

        Used for period-over-period comparison: e.g. to get the "previous 30d"
        snapshot, pass before_date = now - 30 days.
        """
        conditions = [
            MetricsSnapshot.tenant_id == tenant_id,
            MetricsSnapshot.metric_type == metric_type,
            MetricsSnapshot.calculated_at < before_date,
        ]
        if team_id:
            conditions.append(MetricsSnapshot.team_id == team_id)
        else:
            conditions.append(MetricsSnapshot.team_id.is_(None))

        stmt = (
            select(MetricsSnapshot)
            .where(and_(*conditions))
            .order_by(MetricsSnapshot.calculated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
