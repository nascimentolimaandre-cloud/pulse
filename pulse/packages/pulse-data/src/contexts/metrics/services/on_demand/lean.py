"""Lean on-demand computation (INC-015).

Powers `GET /metrics/lean?squad_key=...`. Returns a dict with all 5
sub-metrics matching the snapshot key layout the metrics worker
produces:

  {
    "cfd":                   {"points": [...]},
    "wip":                   {"wip_count": int},
    "lead_time_distribution": {<distribution dataclass shape>},
    "throughput":            {"points": [<weekly throughput>]},
    "scatterplot":           {<scatterplot dict>},
  }

The route handler then extracts each value the same way it extracts
from snapshots — see `routes.get_lean_metrics`.

INC-001 / INC-010 alignment: the issue fetches use the right
`date_field` per sub-metric — `created_at` for CFD/WIP (need open
items in window), `completed_at` for Throughput / Lead-Time-Distribution
/ Scatterplot (only finished items contribute).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from src.contexts.metrics.domain.lean import (
    IssueFlowData,
    calculate_cfd,
    calculate_lead_time_distribution,
    calculate_lead_time_scatterplot,
    calculate_throughput,
    calculate_wip,
)
from src.contexts.metrics.repositories import MetricsRepository
from src.database import get_session

logger = logging.getLogger(__name__)


def _to_flow_data(issues) -> list[IssueFlowData]:
    """Map ORM rows → domain dataclass."""
    return [
        IssueFlowData(
            issue_id=str(i.id),
            normalized_status=i.normalized_status,
            status_transitions=i.status_transitions or [],
            created_at=i.created_at,
            started_at=i.started_at,
            completed_at=i.completed_at,
            lead_time_hours=getattr(i, "lead_time_hours", None),
        )
        for i in issues
    ]


async def compute_lean_on_demand(
    tenant_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    squad_key: str | None = None,
) -> dict[str, Any]:
    """Compute all 5 Lean sub-metrics for a squad / window.

    Returns a dict keyed by snapshot metric_name (`cfd`, `wip`,
    `lead_time_distribution`, `throughput`, `scatterplot`) with
    each value matching the JSONB shape the worker writes.
    """
    squad_key_upper = squad_key.upper() if squad_key else None

    async with get_session(tenant_id) as session:
        repo = MetricsRepository(session)
        # CFD + WIP need issues open IN the window, regardless of when they
        # close → fetch by created_at (INC-001 fix).
        issues_for_flow = await repo.get_issues_in_window(
            tenant_id, period_start, period_end,
            squad_key=squad_key_upper, date_field="created_at",
        )
        # Throughput + Lead-Time-Distribution + Scatterplot count only
        # what FINISHED in the window (INC-010 fix).
        issues_completed = await repo.get_issues_in_window(
            tenant_id, period_start, period_end,
            squad_key=squad_key_upper, date_field="completed_at",
        )

    flow_data = _to_flow_data(issues_for_flow)
    completed_data = _to_flow_data(issues_completed)

    # ── CFD (cumulative-flow over window) ──
    cfd_value: dict[str, Any] = {"points": []}
    try:
        cfd_points = calculate_cfd(flow_data, period_start.date(), period_end.date())
        cfd_value = {"points": [asdict(p) for p in cfd_points]}
    except Exception:  # noqa: BLE001
        logger.exception("[on-demand] lean cfd failed squad=%s", squad_key)

    # ── WIP (snapshot at end of window) ──
    wip_value: dict[str, Any] = {"wip_count": 0}
    try:
        wip_count = calculate_wip(flow_data)
        wip_value = {"wip_count": wip_count}
    except Exception:  # noqa: BLE001
        logger.exception("[on-demand] lean wip failed squad=%s", squad_key)

    # ── Lead Time Distribution (over completed issues) ──
    lt_value: dict[str, Any] = {}
    try:
        lt_dist = calculate_lead_time_distribution(completed_data)
        lt_value = asdict(lt_dist)
    except Exception:  # noqa: BLE001
        logger.exception("[on-demand] lean lead_time_distribution failed squad=%s", squad_key)

    # ── Throughput (issue-based — count items completed per week) ──
    tp_value: dict[str, Any] = {"points": []}
    try:
        tp_points = calculate_throughput(
            completed_data, period_start.date(), period_end.date(),
        )
        tp_value = {"points": [asdict(p) for p in tp_points]}
    except Exception:  # noqa: BLE001
        logger.exception("[on-demand] lean throughput failed squad=%s", squad_key)

    # ── Scatterplot (lead time vs completion date) ──
    scatter_value: dict[str, Any] = {}
    try:
        points, p50, p85, p95 = calculate_lead_time_scatterplot(completed_data)
        scatter_value = {
            "points": [asdict(p) for p in points],
            "p50_hours": p50,
            "p85_hours": p85,
            "p95_hours": p95,
        }
    except Exception:  # noqa: BLE001
        logger.exception("[on-demand] lean scatterplot failed squad=%s", squad_key)

    return {
        "cfd": cfd_value,
        "wip": wip_value,
        "lead_time_distribution": lt_value,
        "throughput": tp_value,
        "scatterplot": scatter_value,
    }
