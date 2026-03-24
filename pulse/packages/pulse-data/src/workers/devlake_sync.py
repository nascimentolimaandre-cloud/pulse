"""DevLake Sync Worker.

Reads normalized data from the DevLake PostgreSQL database,
transforms it into PULSE domain events, and publishes to Kafka.

Runs on a schedule (every 15 min via EventBridge in prod, loop in dev).
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
    create_producer,
    publish_event,
)

logger = logging.getLogger(__name__)


class DevLakeSyncWorker:
    """Syncs data from DevLake DB to Kafka topics.

    Reads from DevLake's normalized tables (pull_requests, issues,
    cicd_deployments, sprints) and publishes domain events.
    """

    def __init__(self) -> None:
        self._devlake_db_url = settings.devlake_db_url

    async def sync(self) -> dict[str, int]:
        """Run a full sync cycle.

        Returns:
            Dict with counts of synced entities, e.g. {"pull_requests": 42, "issues": 15}.
        """
        raise NotImplementedError("Phase 2: implement DevLake DB read + Kafka publish")

    async def _sync_pull_requests(self) -> int:
        """Read PRs from DevLake, publish to domain.pr.normalized topic."""
        raise NotImplementedError("Phase 2")

    async def _sync_issues(self) -> int:
        """Read issues from DevLake, publish to domain.issue.normalized topic."""
        raise NotImplementedError("Phase 2")

    async def _sync_deployments(self) -> int:
        """Read deployments from DevLake, publish to domain.deployment.normalized topic."""
        raise NotImplementedError("Phase 2")

    async def _sync_sprints(self) -> int:
        """Read sprints from DevLake, publish to domain.sprint.normalized topic."""
        raise NotImplementedError("Phase 2")


async def run_sync_loop() -> None:
    """Run sync in a loop for local development (every 15 minutes).

    Phase 1 stub: waits idle until Phase 2 implements the pipeline.
    """
    logger.warning("Sync not yet implemented — waiting for Phase 2")
    while True:
        await asyncio.sleep(900)  # 15 minutes


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run_sync_loop())
