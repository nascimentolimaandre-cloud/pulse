"""Metrics Worker.

Consumes normalized engineering data events from Kafka and delegates the
actual metric recalculation to `contexts.metrics.services.recalculate`.

Pipeline: Kafka (domain.*.normalized) -> recalculate service -> metrics_snapshots

The worker owns only the Kafka plumbing + routing. All fetching, calculation
and snapshot writing logic lives in the recalculate service so that the admin
endpoint (`POST /data/v1/admin/metrics/recalculate`) and the event-driven
path share one implementation — a single source of truth for:
  - which periods exist (must match routes._VALID_PERIODS)
  - INC-001 fetch semantics (merged_at / completed_at vs created_at)
  - INC-007 cycle time population in throughput data
  - INC-008 production-only deployment filter for DORA
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from src.config import settings
from src.contexts.metrics.services.recalculate import recalculate
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

# Topic → which metric_type(s) the recalculate service should refresh.
# Using "all" for period keeps behavior identical to the previous hand-rolled
# loop (recalc every window on every event). Event volume is low enough in
# practice that this is acceptable.
_TOPIC_TO_METRIC_TYPE: dict[str, str] = {
    TOPIC_PR_NORMALIZED: "throughput",       # also triggers cycle_time below
    TOPIC_ISSUE_NORMALIZED: "lean",
    TOPIC_DEPLOYMENT_NORMALIZED: "dora",
    TOPIC_SPRINT_NORMALIZED: "sprint",
}


class MetricsWorker(BaseWorker):
    """Consumes domain events and triggers metric recalculations."""

    def __init__(self) -> None:
        super().__init__(
            topics=CONSUMED_TOPICS,
            group_id="pulse-metrics-worker",
        )
        self._tenant_id = UUID(settings.default_tenant_id)

    async def process_message(self, topic: str, key: str | None, value: dict[str, Any]) -> None:
        """Process a single normalized domain event."""
        logger.debug("Processing message from %s key=%s", topic, key)

        tenant_id = UUID(value.get("tenant_id", str(self._tenant_id)))

        try:
            if topic == TOPIC_PR_NORMALIZED:
                # PR events affect both throughput and cycle_time metrics.
                result_tp = await recalculate(
                    tenant_id, metric_type="throughput", period="all",
                )
                result_ct = await recalculate(
                    tenant_id, metric_type="cycle_time", period="all",
                )
                logger.info(
                    "PR event: recalculated throughput (%d snaps) + cycle_time (%d snaps)",
                    result_tp.snapshots_written, result_ct.snapshots_written,
                )
            elif topic in _TOPIC_TO_METRIC_TYPE:
                metric = _TOPIC_TO_METRIC_TYPE[topic]
                result = await recalculate(
                    tenant_id, metric_type=metric, period="all",
                )
                logger.info(
                    "%s event: recalculated %s (%d snaps, %d errors)",
                    topic, metric, result.snapshots_written, len(result.errors),
                )
            else:
                logger.warning("Unknown topic: %s", topic)
        except Exception:
            logger.exception("Error processing %s event key=%s", topic, key)


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
