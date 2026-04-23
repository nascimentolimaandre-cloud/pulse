"""Operational metrics for pulse-data (FDD-OPS-001).

Prometheus counters / gauges used to surface platform health. Designed
to degrade gracefully: if `prometheus_client` is not installed (it is
NOT currently in requirements.txt), every call becomes a no-op and the
rest of the app continues to function.

Wire-up to a Prometheus scrape endpoint is a separate concern (see
`TODO: add /metrics route and add prometheus_client to requirements`).
The counters here are written defensively so adding that dependency
later is a single-line change.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Best-effort Prometheus integration
# ---------------------------------------------------------------------------
# We attempt to import prometheus_client. If it's missing, we substitute
# a no-op shim so callers don't need try/except around every .labels().inc().
# This is intentional: metrics must never break the hot path.

try:
    from prometheus_client import Counter  # type: ignore[import-not-found]

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover — tested via prometheus_available flag
    _PROMETHEUS_AVAILABLE = False

    class _NoopLabelled:
        """Object returned by `.labels(...)` when Prometheus is absent."""

        def inc(self, amount: float = 1.0) -> None:  # noqa: D401
            """No-op increment."""
            return None

        def observe(self, amount: float) -> None:  # noqa: D401
            """No-op histogram observation."""
            return None

        def set(self, value: float) -> None:  # noqa: D401
            """No-op gauge set."""
            return None

    class Counter:  # type: ignore[no-redef]  # noqa: D101
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._noop = _NoopLabelled()

        def labels(self, *args: Any, **kwargs: Any) -> _NoopLabelled:
            return self._noop

        def inc(self, amount: float = 1.0) -> None:
            return None


def prometheus_available() -> bool:
    """Return True when prometheus_client is installed. For diagnostics."""
    return _PROMETHEUS_AVAILABLE


# ---------------------------------------------------------------------------
# FDD-OPS-001 L3 — Snapshot schema drift counter
# ---------------------------------------------------------------------------

snapshot_schema_drift_total = Counter(
    "pulse_snapshot_schema_drift_total",
    (
        "Count of metric snapshots written with a payload missing "
        "fields declared on the current schema. High values indicate "
        "worker bytecode is out of sync with the code on disk — see "
        "FDD-OPS-001."
    ),
    labelnames=("metric_type", "metric_name"),
)


if not _PROMETHEUS_AVAILABLE:
    # Emit a startup log line so the FIRST time someone adds
    # prometheus_client to requirements, the counter automatically starts
    # collecting without any code change here. Until then we leave a
    # breadcrumb for operators.
    logger.info(
        "prometheus_client not installed — operational counters are no-op. "
        "See requirements.txt / FDD-OPS-001 follow-up."
    )
