"""Cycle Time on-demand computation (INC-015).

Powers `GET /metrics/cycle-time?squad_key=...`. Returns a dict
shaped `{"breakdown": {...}, "trend": [...]}` matching the snapshot
keys the route handler expects.
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
    calculate_cycle_time_trend,
)
from src.contexts.metrics.repositories import MetricsRepository
from src.database import get_session

logger = logging.getLogger(__name__)


async def compute_cycle_time_on_demand(
    tenant_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    squad_key: str | None = None,
) -> dict[str, Any]:
    """Compute cycle-time breakdown (P50/P85/P95 per phase) + 12-week
    trend on the fly.

    Returns a dict whose keys match the snapshot value JSONB structure:
    `{"breakdown": <breakdown dict>, "trend": [<weekly points>]}`.
    """
    squad_key_upper = squad_key.upper() if squad_key else None

    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        prs = await repo.get_prs_in_window(
            tenant_id, period_start, period_end, squad_key=squad_key_upper,
        )

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

    breakdown_value: dict[str, Any] | None = None
    try:
        breakdown = calculate_cycle_time_breakdown(cycle_data)
        breakdown_value = asdict(breakdown)
    except Exception:  # noqa: BLE001
        logger.exception(
            "[on-demand] cycle_time breakdown failed tenant=%s squad=%s",
            tenant_id, squad_key,
        )

    trend_points: list[dict[str, Any]] = []
    try:
        trend = calculate_cycle_time_trend(cycle_data, period_start, period_end)
        trend_points = [asdict(p) for p in trend]
    except Exception:  # noqa: BLE001
        logger.exception(
            "[on-demand] cycle_time trend failed tenant=%s squad=%s",
            tenant_id, squad_key,
        )

    return {
        "breakdown": breakdown_value,
        "trend": trend_points,
    }
