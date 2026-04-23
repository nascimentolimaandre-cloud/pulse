"""Runtime schema registry for snapshot contract validation (FDD-OPS-001 L3).

Maps (metric_type, metric_name) -> expected top-level fields in the
persisted snapshot payload. Source of truth is the metrics *domain*
dataclasses (cycle_time, dora, lean, throughput), because that is what
`asdict(...)` produces when `recalculate.py` writes to the snapshot
store. Pydantic response schemas in `contexts/metrics/schemas.py` are a
closely-related but different contract (API wire format) and are NOT
used here.

PURPOSE
-------
Detect when a running Python worker is serializing snapshots from an
*older* version of the dataclasses than what is currently on disk. When
that happens, `asdict(...)` emits a dict missing the newly-added fields,
which then silently propagates to dashboards as "null" or "—".

HOW WE FLAG DRIFT
-----------------
We compare the set of keys in the payload against the set of fields
declared on the current dataclass. If the dataclass has a field the
payload doesn't contain, that's drift: the worker is stale.

WHAT WE REGISTER
----------------
We only register tuples that write `asdict(dataclass)` directly at the
top level. Payloads that wrap a list (`{"points": [...]}`) are skipped
because the top-level shape is trivially fixed and drift there never
manifests. See `recalculate.py` for the canonical write sites.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from src.contexts.metrics.domain.cycle_time import CycleTimeBreakdown
from src.contexts.metrics.domain.dora import DoraMetrics
from src.contexts.metrics.domain.lean import LeadTimeDistribution
from src.contexts.metrics.domain.throughput import PrAnalytics

# (metric_type, metric_name) -> domain dataclass whose `asdict(...)`
# output is stored verbatim as the snapshot `value` column.
#
# Priority set for FDD-OPS-001 L3 (rationale: these are the payloads
# most commonly affected by silent drift — they are flat dataclasses
# whose field set evolves as we expand the metric surface).
_SCHEMA_MAP: dict[tuple[str, str], type[Any]] = {
    ("dora", "all"): DoraMetrics,
    ("cycle_time", "breakdown"): CycleTimeBreakdown,
    ("lean", "lead_time_distribution"): LeadTimeDistribution,
    ("throughput", "pr_analytics"): PrAnalytics,
    # NOT registered (wrapper payloads — drift here is visible in API not writer):
    #   ("cycle_time", "trend")           -> {"points": [...]}
    #   ("throughput", "trend")           -> {"points": [...]}
    #   ("lean", "cfd")                   -> {"points": [...]}
    #   ("lean", "throughput")            -> {"points": [...]}
    #   ("lean", "wip")                   -> {"wip_count": int}
    #   ("lean", "scatterplot")           -> {"points": [...], "p50_hours": ..., ...}
    #   ("sprint", "overview_*")          -> dynamic metric_name (N sprints)
    #   ("sprint", "comparison")          -> {"sprints": [...], ...}
    # If product wants drift detection on these too, extend this map with
    # TypedDict-style explicit field sets — not dataclass introspection.
}


def expected_fields(metric_type: str, metric_name: str) -> set[str] | None:
    """Return the set of expected top-level fields for a snapshot.

    Returns None when the (metric_type, metric_name) pair isn't
    registered. Callers MUST treat None as "don't validate" — new
    experimental metrics will land before they are registered here, and
    failing to validate them is safer than mis-validating them.
    """
    cls = _SCHEMA_MAP.get((metric_type, metric_name))
    if cls is None:
        return None
    if dataclasses.is_dataclass(cls):
        return {f.name for f in dataclasses.fields(cls)}
    # Future-proofing: if we ever register a Pydantic model, fall through.
    model_fields = getattr(cls, "model_fields", None)
    if model_fields is not None:
        return set(model_fields.keys())
    return None


def registered_contracts() -> list[tuple[str, str]]:
    """Return the list of (metric_type, metric_name) pairs we validate.

    Exposed for diagnostic endpoints / tests that want to enumerate the
    contracts without reaching into private state.
    """
    return sorted(_SCHEMA_MAP.keys())
