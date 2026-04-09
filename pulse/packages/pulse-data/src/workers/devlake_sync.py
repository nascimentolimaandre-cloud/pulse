"""DevLake Sync Worker.

Reads normalized data from the DevLake PostgreSQL database,
transforms it into PULSE domain events, and publishes to Kafka.

Pipeline: DevLake DB -> DevLakeReader -> Normalizer -> PULSE DB (upsert) -> Kafka

Runs on a schedule (every 15 min via EventBridge in prod, loop in dev).
Uses watermark-based incremental sync to avoid full table scans.
Watermarks are persisted in pipeline_watermarks table (survives restarts).
Sync cycles are recorded in pipeline_sync_log for observability.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import settings
from src.contexts.engineering_data.devlake_reader import DevLakeReader
from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
    EngSprint,
)
from src.contexts.engineering_data.normalizer import (
    link_issues_to_prs,
    normalize_deployment,
    normalize_issue,
    normalize_pull_request,
    normalize_sprint,
)
from src.contexts.pipeline.models import PipelineSyncLog, PipelineWatermark
from src.database import get_session
from src.shared.kafka import (
    TOPIC_DEPLOYMENT_NORMALIZED,
    TOPIC_ISSUE_NORMALIZED,
    TOPIC_PR_NORMALIZED,
    TOPIC_SPRINT_NORMALIZED,
    create_producer,
    publish_batch,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Watermark helpers — persistent DB storage via pipeline_watermarks
# ---------------------------------------------------------------------------

async def _get_watermark(session, tenant_id: UUID, entity: str) -> datetime | None:
    """Get the last sync timestamp for an entity type from the DB."""
    result = await session.execute(
        select(PipelineWatermark.last_synced_at)
        .where(PipelineWatermark.entity_type == entity)
    )
    row = result.scalar_one_or_none()
    return row


async def _set_watermark(
    session, tenant_id: UUID, entity: str, ts: datetime, count: int,
) -> None:
    """Upsert the watermark for an entity type using ON CONFLICT."""
    stmt = (
        pg_insert(PipelineWatermark)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            entity_type=entity,
            last_synced_at=ts,
            records_synced=count,
        )
        .on_conflict_do_update(
            constraint="uq_watermark_entity",
            set_={
                "last_synced_at": ts,
                "records_synced": count,
                "updated_at": func.now(),
            },
        )
    )
    await session.execute(stmt)
    logger.debug("Updated watermark for %s to %s (count=%d)", entity, ts, count)


class DevLakeSyncWorker:
    """Syncs data from DevLake DB to PULSE DB and Kafka topics.

    Reads from DevLake's normalized tables (pull_requests, issues,
    cicd_deployment_commits, sprints), transforms via normalizer,
    upserts into PULSE DB, and publishes domain events to Kafka.

    Each sync cycle is recorded in pipeline_sync_log for observability.
    Watermarks are persisted in pipeline_watermarks for crash recovery.
    """

    def __init__(
        self,
        tenant_id: UUID | None = None,
        status_mapping: dict[str, str] | None = None,
    ) -> None:
        self._tenant_id = tenant_id or UUID(settings.default_tenant_id)
        self._status_mapping = status_mapping
        self._reader = DevLakeReader()
        self._producer = None
        self._running = False

    async def _ensure_producer(self):
        """Lazily create the Kafka producer."""
        if self._producer is None:
            self._producer = await create_producer()

    async def close(self) -> None:
        """Clean up resources."""
        self._running = False
        if self._producer:
            await self._producer.stop()
            self._producer = None
        await self._reader.close()
        logger.info("DevLakeSyncWorker resources cleaned up")

    async def sync(self) -> dict[str, int]:
        """Run a full sync cycle.

        Syncs all entity types (PRs, issues, deployments, sprints),
        links issues to PRs, and publishes events to Kafka.
        Records the cycle in pipeline_sync_log with status tracking.

        Returns:
            Dict with counts of synced entities.
        """
        await self._ensure_producer()
        logger.info("Starting sync cycle for tenant %s", self._tenant_id)

        started_at = datetime.now(timezone.utc)
        results: dict[str, int] = {}
        errors: list[dict[str, str]] = []

        # Create sync log entry with status="running"
        async with get_session(self._tenant_id) as session:
            log_entry = PipelineSyncLog(
                tenant_id=self._tenant_id,
                started_at=started_at,
                status="running",
                trigger="scheduled",
                records_processed={},
                errors=[],
                error_count=0,
            )
            session.add(log_entry)
            await session.flush()
            log_id = log_entry.id

        # Run each entity sync, collecting results and errors
        for entity, sync_fn in [
            ("pull_requests", self._sync_pull_requests),
            ("issues", self._sync_issues),
            ("deployments", self._sync_deployments),
            ("sprints", self._sync_sprints),
        ]:
            try:
                results[entity] = await sync_fn()
            except Exception as exc:
                logger.exception("Error syncing %s", entity)
                results[entity] = 0
                errors.append({
                    "stage": entity,
                    "message": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        # Determine final status
        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()

        if errors and all(results[e] == 0 for e in results):
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "completed"

        total = sum(results.values())

        # Update the sync log entry
        async with get_session(self._tenant_id) as session:
            log_entry = await session.get(PipelineSyncLog, log_id)
            if log_entry:
                log_entry.finished_at = finished_at
                log_entry.status = status
                log_entry.duration_seconds = duration
                log_entry.records_processed = results
                log_entry.errors = errors
                log_entry.error_count = len(errors)

        logger.info(
            "Sync cycle %s: %d total entities synced in %.1fs — %s",
            status,
            total,
            duration,
            results,
        )

        # Re-raise if all entities failed (preserves existing error behavior)
        if status == "failed" and errors:
            raise RuntimeError(
                f"Sync cycle failed: {len(errors)} entity types errored — "
                f"{[e['stage'] for e in errors]}"
            )

        return results

    async def _sync_pull_requests(self) -> int:
        """Read PRs from DevLake, upsert to PULSE DB, publish to Kafka."""
        async with get_session(self._tenant_id) as session:
            since = await _get_watermark(session, self._tenant_id, "pull_requests")

        raw_prs = await self._reader.fetch_pull_requests(since=since)
        if not raw_prs:
            logger.info("No new pull requests to sync")
            return 0

        # Normalize
        normalized = []
        for raw in raw_prs:
            try:
                pr_data = normalize_pull_request(raw, self._tenant_id)
                # Stash branch refs for issue linking (not persisted)
                pr_data["_head_ref"] = raw.get("head_ref", "")
                pr_data["_base_ref"] = raw.get("base_ref", "")
                normalized.append(pr_data)
            except Exception:
                logger.exception("Error normalizing PR: %s", raw.get("id"))

        # Upsert to PULSE DB
        count = await self._upsert_pull_requests(normalized)

        # Publish to Kafka
        events = []
        for pr in normalized:
            # Strip internal fields before publishing
            event = {k: v for k, v in pr.items() if not k.startswith("_")}
            events.append((str(pr["external_id"]), event))
        await publish_batch(self._producer, TOPIC_PR_NORMALIZED, events)

        # Update watermark in DB
        async with get_session(self._tenant_id) as session:
            await _set_watermark(
                session, self._tenant_id, "pull_requests",
                datetime.now(timezone.utc), count,
            )
        return count

    async def _sync_issues(self) -> int:
        """Read issues from DevLake, upsert to PULSE DB, publish to Kafka."""
        async with get_session(self._tenant_id) as session:
            since = await _get_watermark(session, self._tenant_id, "issues")

        raw_issues = await self._reader.fetch_issues(since=since)
        if not raw_issues:
            logger.info("No new issues to sync")
            return 0

        # Fetch status changelogs for all issues in this batch (Jira only)
        issue_ids = [str(raw["id"]) for raw in raw_issues]
        changelogs_by_issue = await self._reader.fetch_issue_changelogs(issue_ids)

        # Normalize
        normalized = []
        for raw in raw_issues:
            try:
                issue_id = str(raw["id"])
                issue_changelogs = changelogs_by_issue.get(issue_id, [])
                issue_data = normalize_issue(
                    raw,
                    self._tenant_id,
                    self._status_mapping,
                    changelogs=issue_changelogs,
                )
                normalized.append(issue_data)
            except Exception:
                logger.exception("Error normalizing issue: %s", raw.get("id"))

        # Upsert to PULSE DB
        count = await self._upsert_issues(normalized)

        # Publish to Kafka
        events = []
        for issue in normalized:
            events.append((str(issue["external_id"]), issue))
        await publish_batch(self._producer, TOPIC_ISSUE_NORMALIZED, events)

        # Update watermark in DB
        async with get_session(self._tenant_id) as session:
            await _set_watermark(
                session, self._tenant_id, "issues",
                datetime.now(timezone.utc), count,
            )
        return count

    async def _sync_deployments(self) -> int:
        """Read deployments from DevLake, upsert to PULSE DB, publish to Kafka."""
        async with get_session(self._tenant_id) as session:
            since = await _get_watermark(session, self._tenant_id, "deployments")

        raw_deployments = await self._reader.fetch_deployments(since=since)
        if not raw_deployments:
            logger.info("No new deployments to sync")
            return 0

        # Normalize
        normalized = []
        for raw in raw_deployments:
            try:
                deploy_data = normalize_deployment(raw, self._tenant_id)
                normalized.append(deploy_data)
            except Exception:
                logger.exception("Error normalizing deployment: %s", raw.get("id"))

        # Upsert to PULSE DB
        count = await self._upsert_deployments(normalized)

        # Publish to Kafka
        events = []
        for deploy in normalized:
            events.append((str(deploy["external_id"]), deploy))
        await publish_batch(self._producer, TOPIC_DEPLOYMENT_NORMALIZED, events)

        # Update watermark in DB
        async with get_session(self._tenant_id) as session:
            await _set_watermark(
                session, self._tenant_id, "deployments",
                datetime.now(timezone.utc), count,
            )
        return count

    async def _sync_sprints(self) -> int:
        """Read sprints from DevLake, upsert to PULSE DB, publish to Kafka."""
        async with get_session(self._tenant_id) as session:
            since = await _get_watermark(session, self._tenant_id, "sprints")

        raw_sprints = await self._reader.fetch_sprints(since=since)
        if not raw_sprints:
            logger.info("No new sprints to sync")
            return 0

        # Normalize — includes fetching sprint issues for counts
        normalized = []
        for raw in raw_sprints:
            try:
                sprint_issues = await self._reader.fetch_sprint_issues(str(raw["id"]))
                sprint_data = normalize_sprint(raw, self._tenant_id, sprint_issues)
                normalized.append(sprint_data)
            except Exception:
                logger.exception("Error normalizing sprint: %s", raw.get("id"))

        # Upsert to PULSE DB
        count = await self._upsert_sprints(normalized)

        # Publish to Kafka
        events = []
        for sprint in normalized:
            events.append((str(sprint["external_id"]), sprint))
        await publish_batch(self._producer, TOPIC_SPRINT_NORMALIZED, events)

        # Update watermark in DB
        async with get_session(self._tenant_id) as session:
            await _set_watermark(
                session, self._tenant_id, "sprints",
                datetime.now(timezone.utc), count,
            )
        return count

    # ---------------------------------------------------------------
    # Upsert helpers — ON CONFLICT (tenant_id, external_id) DO UPDATE
    # ---------------------------------------------------------------

    async def _upsert_pull_requests(self, prs: list[dict[str, Any]]) -> int:
        """Upsert normalized PRs into eng_pull_requests."""
        if not prs:
            return 0

        async with get_session(self._tenant_id) as session:
            count = 0
            for pr_data in prs:
                # Strip internal fields
                data = {k: v for k, v in pr_data.items() if not k.startswith("_")}
                stmt = (
                    pg_insert(EngPullRequest)
                    .values(**data)
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "external_id"],
                        set_={
                            "state": data["state"],
                            "title": data["title"],
                            "author": data["author"],
                            "merged_at": data["merged_at"],
                            "additions": data["additions"],
                            "deletions": data["deletions"],
                            "linked_issue_ids": data["linked_issue_ids"],
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await session.execute(stmt)
                count += 1
            logger.info("Upserted %d pull requests to PULSE DB", count)
            return count

    async def _upsert_issues(self, issues: list[dict[str, Any]]) -> int:
        """Upsert normalized issues into eng_issues."""
        if not issues:
            return 0

        async with get_session(self._tenant_id) as session:
            count = 0
            for issue_data in issues:
                stmt = (
                    pg_insert(EngIssue)
                    .values(**issue_data)
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "external_id"],
                        set_={
                            "issue_type": issue_data["issue_type"],
                            "status": issue_data["status"],
                            "normalized_status": issue_data["normalized_status"],
                            "assignee": issue_data["assignee"],
                            "story_points": issue_data["story_points"],
                            "sprint_id": issue_data["sprint_id"],
                            "status_transitions": issue_data["status_transitions"],
                            "started_at": issue_data["started_at"],
                            "completed_at": issue_data["completed_at"],
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await session.execute(stmt)
                count += 1
            logger.info("Upserted %d issues to PULSE DB", count)
            return count

    async def _upsert_deployments(self, deployments: list[dict[str, Any]]) -> int:
        """Upsert normalized deployments into eng_deployments."""
        if not deployments:
            return 0

        async with get_session(self._tenant_id) as session:
            count = 0
            for deploy_data in deployments:
                stmt = (
                    pg_insert(EngDeployment)
                    .values(**deploy_data)
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "external_id"],
                        set_={
                            "is_failure": deploy_data["is_failure"],
                            "environment": deploy_data["environment"],
                            "deployed_at": deploy_data["deployed_at"],
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await session.execute(stmt)
                count += 1
            logger.info("Upserted %d deployments to PULSE DB", count)
            return count

    async def _upsert_sprints(self, sprints: list[dict[str, Any]]) -> int:
        """Upsert normalized sprints into eng_sprints."""
        if not sprints:
            return 0

        async with get_session(self._tenant_id) as session:
            count = 0
            for sprint_data in sprints:
                stmt = (
                    pg_insert(EngSprint)
                    .values(**sprint_data)
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "external_id"],
                        set_={
                            "name": sprint_data["name"],
                            "started_at": sprint_data["started_at"],
                            "completed_at": sprint_data["completed_at"],
                            "committed_items": sprint_data["committed_items"],
                            "committed_points": sprint_data["committed_points"],
                            "completed_items": sprint_data["completed_items"],
                            "completed_points": sprint_data["completed_points"],
                            "carried_over_items": sprint_data["carried_over_items"],
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await session.execute(stmt)
                count += 1
            logger.info("Upserted %d sprints to PULSE DB", count)
            return count


async def run_sync_loop() -> None:
    """Run sync in a loop for local development (every 15 minutes).

    Handles SIGTERM/SIGINT for graceful shutdown.
    """
    worker = DevLakeSyncWorker()
    running = True

    def _handle_signal():
        nonlocal running
        running = False
        logger.info("Received shutdown signal, stopping sync loop")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info("DevLake sync loop started (interval=900s)")

    try:
        while running:
            try:
                results = await worker.sync()
                logger.info("Sync cycle results: %s", results)
            except Exception:
                logger.exception("Sync cycle failed, will retry in 15 minutes")

            # Wait 15 minutes, but check running flag every second
            for _ in range(900):
                if not running:
                    break
                await asyncio.sleep(1)
    finally:
        await worker.close()
        logger.info("DevLake sync loop stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run_sync_loop())
