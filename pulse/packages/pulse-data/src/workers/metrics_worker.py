"""Metrics Worker.

Consumes normalized engineering data events from Kafka,
runs metric calculations (pure functions), and writes
results to the PULSE database.

Triggered by MSK Event Source Mapping in Lambda,
or runs as a long-lived consumer locally.
"""

import asyncio
import logging
from typing import Any

from src.config import settings
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


class MetricsWorker(BaseWorker):
    """Consumes domain events and triggers metric recalculations."""

    def __init__(self) -> None:
        super().__init__(
            topics=CONSUMED_TOPICS,
            group_id="pulse-metrics-worker",
        )

    async def process_message(self, topic: str, key: str | None, value: dict[str, Any]) -> None:
        """Process a single normalized domain event.

        Routes to the appropriate handler based on topic.
        """
        raise NotImplementedError("Phase 2: implement metric recalculation pipeline")

    async def _handle_pr_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized PR event — recalculate cycle time, throughput."""
        raise NotImplementedError("Phase 2")

    async def _handle_issue_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized issue event — recalculate lean metrics."""
        raise NotImplementedError("Phase 2")

    async def _handle_deployment_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized deployment event — recalculate DORA metrics."""
        raise NotImplementedError("Phase 2")

    async def _handle_sprint_event(self, value: dict[str, Any]) -> None:
        """Handle a normalized sprint event — recalculate sprint metrics."""
        raise NotImplementedError("Phase 2")


async def run_worker() -> None:
    """Run the metrics worker as a long-lived consumer (local dev)."""
    worker = MetricsWorker()
    try:
        await worker.start()
    except NotImplementedError:
        logger.warning("Metrics worker not yet implemented — waiting for Phase 2")
    except KeyboardInterrupt:
        await worker.stop()


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run_worker())
