"""Throughput on-demand computation (INC-015).

Powers `GET /metrics/throughput?squad_key=...`. Returns a dict shaped
`{"trend": [...], "pr_analytics": {...}}` matching the snapshot keys.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from src.contexts.metrics.domain.throughput import (
    PullRequestThroughputData,
    calculate_pr_analytics,
    calculate_throughput_trend,
)
from src.contexts.metrics.repositories import MetricsRepository
from src.database import get_session

logger = logging.getLogger(__name__)


async def compute_throughput_on_demand(
    tenant_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    squad_key: str | None = None,
) -> dict[str, Any]:
    """Compute throughput trend + PR analytics on the fly.

    Returns a dict whose keys match the snapshot value JSONB:
    `{"trend": [<weekly points>], "pr_analytics": {...}}`.
    """
    squad_key_upper = squad_key.upper() if squad_key else None

    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        prs = await repo.get_prs_in_window(
            tenant_id, period_start, period_end, squad_key=squad_key_upper,
        )

    throughput_data: list[PullRequestThroughputData] = []
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

    trend_points: list[dict[str, Any]] = []
    try:
        trend = calculate_throughput_trend(throughput_data, period_start, period_end)
        trend_points = [asdict(p) for p in trend]
    except Exception:  # noqa: BLE001
        logger.exception(
            "[on-demand] throughput trend failed tenant=%s squad=%s",
            tenant_id, squad_key,
        )

    analytics_value: dict[str, Any] = {}
    try:
        analytics = calculate_pr_analytics(throughput_data)
        analytics_value = asdict(analytics)
    except Exception:  # noqa: BLE001
        logger.exception(
            "[on-demand] throughput pr_analytics failed tenant=%s squad=%s",
            tenant_id, squad_key,
        )

    return {
        "trend": trend_points,
        "pr_analytics": analytics_value,
    }
