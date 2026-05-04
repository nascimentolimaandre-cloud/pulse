"""DORA on-demand computation (INC-015).

Powers `GET /metrics/dora?squad_key=...` and any custom-period request.
Returns a dict with the same shape the snapshot path produces, so
`routes.get_dora_metrics` can consume either source.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from src.contexts.metrics.domain.dora import (
    DeploymentData,
    PullRequestData,
    calculate_dora_metrics,
)
from src.contexts.metrics.repositories import MetricsRepository
from src.database import get_session

logger = logging.getLogger(__name__)


async def compute_dora_on_demand(
    tenant_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    squad_key: str | None = None,
) -> dict[str, Any]:
    """Compute DORA (DF, LT, CFR, MTTR) on the fly for a squad / window.

    Returns a dict whose keys match the snapshot value JSONB written by
    the metrics worker — the route handler maps it to `DoraMetricsData`
    the same way it maps a snapshot.
    """
    squad_key_upper = squad_key.upper() if squad_key else None

    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        prs = await repo.get_prs_in_window(
            tenant_id, period_start, period_end, squad_key=squad_key_upper,
        )
        deploys = await repo.get_deployments_by_squad(
            tenant_id, period_start, period_end, squad_key=squad_key_upper,
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
        return asdict(dora)
    except Exception:  # noqa: BLE001
        logger.exception(
            "[on-demand] dora compute failed tenant=%s squad=%s",
            tenant_id, squad_key,
        )
        return {}
