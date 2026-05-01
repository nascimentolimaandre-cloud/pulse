"""Data Sync Worker.

Reads data from source connectors (GitHub, Jira, Jenkins),
transforms it into PULSE domain events, and publishes to Kafka.

Pipeline: Source APIs -> Connectors -> Normalizer -> PULSE DB (upsert) -> Kafka

Runs on a schedule (every 15 min via EventBridge in prod, loop in dev).
Uses watermark-based incremental sync to avoid full table scans.
Watermarks are persisted in pipeline_watermarks table (survives restarts).
Sync cycles are recorded in pipeline_sync_log for observability.

History: Originally read from DevLake domain tables (DevLakeReader).
         Migrated to direct API access via ConnectorAggregator (ADR-005).
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import settings
from src.connectors import ConnectorAggregator
from src.connectors.github_connector import GitHubConnector
from src.connectors.jira_connector import JiraConnector
from src.connectors.jenkins_connector import JenkinsConnector
from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver
from src.contexts.integrations.jira.discovery.guardrails import Guardrails
from src.contexts.engineering_data.models import (
    EngDeployment,
    EngIssue,
    EngPullRequest,
    EngSprint,
)
from src.contexts.engineering_data.services.backfill_deployed_at import (
    link_recent_deploys_to_prs,
)
from src.contexts.engineering_data.services.backfill_mttr import (
    pair_recent_incidents,
)
from src.contexts.engineering_data.normalizer import (
    apply_pr_issue_links,
    build_issue_key_map,
    link_issues_to_prs,
    normalize_deployment,
    normalize_issue,
    normalize_pull_request,
    normalize_sprint,
)
from src.contexts.pipeline.models import PipelineIngestionProgress, PipelineSyncLog, PipelineWatermark
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
# Changelog helpers
# ---------------------------------------------------------------------------

def extract_status_transitions_inline(raw_issue: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract status transitions from a Jira issue's INLINE changelog.

    FDD-OPS-013 — replaces the previous round-trip to
    `fetch_issue_changelogs(issue_ids)` which made one HTTP GET per issue.
    The JQL search uses `expand=changelog`, so the changelog is already
    present in the response payload.

    Always returns a list (possibly empty for issues with no status changes
    in their history). The empty-list case is what fixed the 24h hang in
    production: previously the cache lookup on `_last_changelogs` skipped
    entries with empty transitions, causing a downstream cache-miss that
    triggered the redundant individual GET.

    Output shape mirrors `JiraConnector._extract_changelogs` so that
    `normalize_issue(..., changelogs=...)` doesn't need to change.
    """
    issue_id = str(raw_issue["id"])
    transitions: list[dict[str, Any]] = []
    for history in raw_issue.get("changelog", {}).get("histories", []):
        created = history.get("created")
        for item in history.get("items", []):
            if item.get("field", "").lower() == "status":
                transitions.append({
                    "issue_id": issue_id,
                    "from_status": item.get("fromString", ""),
                    "to_status": item.get("toString", ""),
                    "created_date": created,
                })
    transitions.sort(key=lambda t: t.get("created_date") or "")
    return transitions


# ---------------------------------------------------------------------------
# Watermark helpers — persistent DB storage via pipeline_watermarks
#
# FDD-OPS-014 (migration 010): watermarks are keyed by (tenant, entity, scope).
# `scope_key='*'` is the legacy "global" key — kept as default for backwards
# compatibility during the rollout. Per-source workers (steps 2.3-2.5) will
# pass explicit scope_keys like 'jira:project:BG' or 'github:repo:foo/bar'.
# ---------------------------------------------------------------------------

# Scope-key conventions (free-form string per Q2 of phase-2 plan, but helpers
# enforce shape). Format: '<source>:<dimension>:<value>'.
GLOBAL_SCOPE = "*"


def make_scope_key(source: str, dimension: str, value: str) -> str:
    """Build a canonical scope_key. Convention enforced via helper, not DB.

    Examples:
        make_scope_key("jira", "project", "BG")     -> "jira:project:BG"
        make_scope_key("github", "repo", "foo/bar") -> "github:repo:foo/bar"
    """
    return f"{source}:{dimension}:{value}"


async def _get_watermark(
    session, tenant_id: UUID, entity: str, scope_key: str = GLOBAL_SCOPE,
) -> datetime | None:
    """Get the last sync timestamp for (entity_type, scope_key) from the DB.

    Default scope_key='*' preserves legacy callers (one global row per
    entity_type). Per-source workers pass an explicit scope_key.
    """
    result = await session.execute(
        select(PipelineWatermark.last_synced_at)
        .where(
            PipelineWatermark.entity_type == entity,
            PipelineWatermark.scope_key == scope_key,
        )
    )
    row = result.scalar_one_or_none()
    return row


async def _set_watermark(
    session, tenant_id: UUID, entity: str, ts: datetime, count: int,
    scope_key: str = GLOBAL_SCOPE,
) -> None:
    """Upsert the watermark for (entity_type, scope_key) using ON CONFLICT.

    Default scope_key='*' upserts the legacy global row.
    """
    stmt = (
        pg_insert(PipelineWatermark)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            entity_type=entity,
            scope_key=scope_key,
            last_synced_at=ts,
            records_synced=count,
        )
        .on_conflict_do_update(
            constraint="uq_watermark_entity_scope",
            set_={
                "last_synced_at": ts,
                "records_synced": count,
                "updated_at": func.now(),
            },
        )
    )
    await session.execute(stmt)
    logger.debug(
        "Updated watermark for %s/%s to %s (count=%d)",
        entity, scope_key, ts, count,
    )


async def _list_watermarks_by_scope(
    session, tenant_id: UUID, entity: str, scope_keys: list[str],
) -> dict[str, datetime | None]:
    """Bulk-fetch watermarks for a list of scopes. Returns {scope_key: ts}.

    Missing scopes return None (no watermark = full backfill on first sync).
    Used by per-source workers (Phase 2 step 2.3+) to feed
    `since_by_project={...}` into batched fetchers.
    """
    if not scope_keys:
        return {}

    result = await session.execute(
        select(PipelineWatermark.scope_key, PipelineWatermark.last_synced_at)
        .where(
            PipelineWatermark.entity_type == entity,
            PipelineWatermark.scope_key.in_(scope_keys),
        )
    )
    found = {row[0]: row[1] for row in result.all()}
    return {scope: found.get(scope) for scope in scope_keys}


# ---------------------------------------------------------------------------
# Ingestion progress helpers — real-time tracking per batch
# ---------------------------------------------------------------------------


async def _update_ingestion_progress(
    tenant_id: UUID,
    entity_type: str,
    *,
    status: str = "running",
    total_sources: int | None = None,
    sources_done: int | None = None,
    records_ingested: int | None = None,
    current_source: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_message: str | None = None,
) -> None:
    """Upsert ingestion progress for an entity type."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "entity_type": entity_type,
        "status": status,
        "updated_at": func.now(),
    }
    update_set: dict[str, Any] = {
        "status": status,
        "updated_at": func.now(),
    }

    if total_sources is not None:
        values["total_sources"] = total_sources
        update_set["total_sources"] = total_sources
    if sources_done is not None:
        values["sources_done"] = sources_done
        update_set["sources_done"] = sources_done
    if records_ingested is not None:
        values["records_ingested"] = records_ingested
        update_set["records_ingested"] = records_ingested
    if current_source is not None:
        values["current_source"] = current_source
        update_set["current_source"] = current_source
    if started_at is not None:
        values["started_at"] = started_at
        update_set["started_at"] = started_at
    if finished_at is not None:
        values["finished_at"] = finished_at
        update_set["finished_at"] = finished_at
    if error_message is not None:
        values["error_message"] = error_message
        update_set["error_message"] = error_message

    # Always update last_batch_at when running
    if status == "running":
        now = datetime.now(timezone.utc)
        values["last_batch_at"] = now
        update_set["last_batch_at"] = now

    async with get_session(tenant_id) as session:
        stmt = (
            pg_insert(PipelineIngestionProgress)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_ingestion_progress_entity",
                set_=update_set,
            )
        )
        await session.execute(stmt)


class DataSyncWorker:
    """Syncs data from source APIs to PULSE DB and Kafka topics.

    Reads from source connectors (GitHub, Jira, Jenkins) via
    ConnectorAggregator, transforms via normalizer, upserts into
    PULSE DB, and publishes domain events to Kafka.

    Each sync cycle is recorded in pipeline_sync_log for observability.
    Watermarks are persisted in pipeline_watermarks for crash recovery.
    """

    def __init__(
        self,
        tenant_id: UUID | None = None,
        status_mapping: dict[str, str] | None = None,
        reader: ConnectorAggregator | None = None,
    ) -> None:
        self._tenant_id = tenant_id or UUID(settings.default_tenant_id)
        self._status_mapping = status_mapping
        self._reader = reader or self._create_default_aggregator()
        self._producer = None
        self._running = False

    @staticmethod
    def _create_default_aggregator() -> ConnectorAggregator:
        """Create the default ConnectorAggregator from settings.

        Only initializes connectors whose credentials are configured.
        Connectors without credentials are silently skipped.
        """
        connectors = []

        # GitHub
        if settings.github_token:
            try:
                connectors.append(GitHubConnector())
                logger.info("GitHub connector initialized (org: %s)", settings.github_org)
            except Exception:
                logger.warning("Failed to initialize GitHub connector", exc_info=True)

        # Jira
        if settings.jira_api_token and settings.jira_base_url:
            try:
                connectors.append(JiraConnector())
                logger.info("Jira connector initialized (projects: %s)", settings.jira_projects)
            except Exception:
                logger.warning("Failed to initialize Jira connector", exc_info=True)

        # Jenkins
        if settings.jenkins_api_token and settings.jenkins_base_url:
            try:
                jenkins_jobs = settings.jenkins_jobs
                job_to_repo = settings.jenkins_job_to_repo
                connectors.append(JenkinsConnector(
                    jobs=jenkins_jobs,
                    job_to_repo=job_to_repo,
                ))
                logger.info(
                    "Jenkins connector initialized (url: %s, jobs: %d, repo-map: %d)",
                    settings.jenkins_base_url, len(jenkins_jobs), len(job_to_repo),
                )
            except Exception:
                logger.warning("Failed to initialize Jenkins connector", exc_info=True)

        if not connectors:
            logger.warning(
                "No source connectors configured! Set GITHUB_TOKEN, "
                "JIRA_API_TOKEN, or JENKINS_API_TOKEN in environment."
            )

        return ConnectorAggregator(connectors)

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
        logger.info("DataSyncWorker resources cleaned up")

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

        # Run each entity sync, collecting results and errors.
        # Order matters: issues run BEFORE pull_requests so that the PR
        # linking step has a fresh issue-key index to work with.
        for entity, sync_fn in [
            ("issues", self._sync_issues),
            ("pull_requests", self._sync_pull_requests),
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

        # Refresh jira_project_catalog counters so Pipeline Monitor and
        # Jira Settings always show fresh issue_count + pr_reference_count.
        try:
            await self._refresh_catalog_counters()
        except Exception:
            logger.warning("Catalog counter refresh failed (non-fatal)", exc_info=True)

        # Re-raise if all entities failed (preserves existing error behavior)
        if status == "failed" and errors:
            raise RuntimeError(
                f"Sync cycle failed: {len(errors)} entity types errored — "
                f"{[e['stage'] for e in errors]}"
            )

        return results

    async def _refresh_catalog_counters(self) -> None:
        """Refresh issue_count, pr_reference_count, and last_sync_at in jira_project_catalog.

        Called after every sync cycle so the Pipeline Monitor /teams endpoint
        and the Jira Settings > Projetos tab always show fresh numbers.

        This is fast (<500ms) — 2 UPDATE queries against existing data.
        """
        async with get_session(self._tenant_id) as session:
            # 1. issue_count from eng_issues.project_key
            await session.execute(text("""
                UPDATE jira_project_catalog jpc
                SET issue_count = COALESCE(sub.cnt, 0),
                    updated_at = NOW()
                FROM (
                    SELECT project_key, COUNT(*) AS cnt
                    FROM eng_issues
                    WHERE project_key IS NOT NULL
                    GROUP BY project_key
                ) sub
                WHERE jpc.project_key = sub.project_key
                  AND jpc.tenant_id = :tid
            """), {"tid": str(self._tenant_id)})

            # 2. pr_reference_count from PR title regex (90d window)
            await session.execute(text(r"""
                WITH pr_refs AS (
                    SELECT
                        UPPER((regexp_match(title, '\m([A-Za-z][A-Za-z0-9]+)-\d+'))[1]) AS pk,
                        COUNT(DISTINCT id) AS cnt
                    FROM eng_pull_requests
                    WHERE created_at >= NOW() - INTERVAL '90 days'
                      AND title IS NOT NULL
                    GROUP BY 1
                )
                UPDATE jira_project_catalog jpc
                SET pr_reference_count = pr_refs.cnt,
                    last_sync_at = NOW(),
                    last_sync_status = 'success',
                    updated_at = NOW()
                FROM pr_refs
                WHERE jpc.project_key = pr_refs.pk
                  AND jpc.tenant_id = :tid
            """), {"tid": str(self._tenant_id)})

            # 3. For projects with issues but no PR refs, still update last_sync_at
            await session.execute(text("""
                UPDATE jira_project_catalog
                SET last_sync_at = NOW(),
                    last_sync_status = 'success',
                    updated_at = NOW()
                WHERE tenant_id = :tid
                  AND status IN ('active', 'discovered')
                  AND (last_sync_at IS NULL OR last_sync_at < NOW() - INTERVAL '1 hour')
            """), {"tid": str(self._tenant_id)})

        logger.info("Refreshed jira_project_catalog counters for tenant %s", self._tenant_id)

    async def _sync_pull_requests(self) -> int:
        """Read PRs from source connectors, upsert to PULSE DB, publish to Kafka.

        Uses batch persistence: each repo's PRs are normalized, upserted, and
        published to Kafka immediately — no accumulation in memory. If the
        process crashes mid-sync, all previously persisted repos are safe.

        FDD-OPS-014 step 2.4-B: PER-REPO watermarks now READ + WRITTEN.
        Each repo has scope_key='github:repo:<owner>/<name>'. Adding a new
        repo = backfill ONLY that scope. Existing repos continue from their
        own last_synced_at, not the global '*' value.

        The global '*' watermark is still updated at end-of-cycle for any
        remaining legacy reads (Pipeline Monitor UI etc.). Migration 011
        already dropped the legacy unique constraint that conflicted with
        per-scope inserts.

        Progress is tracked in pipeline_ingestion_progress for real-time
        visibility in the Pipeline Monitor dashboard.
        """
        # Load ALL existing per-repo watermarks for pull_requests. We don't
        # know which repos the connector will emit yet, so fetch the full
        # set keyed by scope_key. The connector will look up each repo's
        # since via since_by_repo[repo] (None = backfill on first sync).
        async with get_session(self._tenant_id) as session:
            global_since = await _get_watermark(
                session, self._tenant_id, "pull_requests",
            )
            # Returns rows where scope_key starts with 'github:repo:'.
            from sqlalchemy import select as _select
            result = await session.execute(
                _select(
                    PipelineWatermark.scope_key,
                    PipelineWatermark.last_synced_at,
                ).where(
                    PipelineWatermark.entity_type == "pull_requests",
                    PipelineWatermark.scope_key.like("github:repo:%"),
                )
            )
            since_by_repo: dict[str, datetime | None] = {}
            for scope_key_str, last_synced in result.all():
                # 'github:repo:owner/name' → 'owner/name'
                repo = scope_key_str[len("github:repo:"):]
                since_by_repo[repo] = last_synced

        logger.info(
            "[prs] watermark plan: %d repos with per-scope rows, global '*' fallback=%s",
            len(since_by_repo),
            global_since.isoformat() if global_since else "None (full backfill)",
        )
        # Pass single fallback for compatibility — repos not in
        # since_by_repo (newly discovered) inherit it.
        since = global_since

        # Build issue-key lookup for PR linking. Loading all issue external_ids
        # from the tenant is cheap (~30k strings) and lets us link each batch
        # without re-querying per PR. Assumes _sync_issues() ran earlier in the
        # cycle — if not, linking falls back to an empty map (no-op).
        async with get_session(self._tenant_id) as session:
            result = await session.execute(
                select(EngIssue.issue_key, EngIssue.external_id)
                .where(EngIssue.tenant_id == self._tenant_id)
            )
            issue_rows = [(row[0], row[1]) for row in result.all()]
        issue_key_map = build_issue_key_map(issue_rows)
        logger.info(
            "PR linking enabled with %d issue keys indexed", len(issue_key_map),
        )

        # Discover total sources (repos) for progress tracking
        total_sources = 0
        try:
            total_sources = await self._reader.get_pull_request_source_count()
        except Exception:
            logger.exception("Could not get source count for progress tracking")

        started_at = datetime.now(timezone.utc)

        # Mark ingestion as running
        await _update_ingestion_progress(
            self._tenant_id, "pull_requests",
            status="running",
            total_sources=total_sources,
            sources_done=0,
            records_ingested=0,
            current_source="discovering repos...",
            started_at=started_at,
        )

        total_count = 0
        repos_done = 0

        # FDD-OPS-015 — per-repo progress trackers, lazily created.
        from src.contexts.pipeline.progress_tracker import ProgressTracker
        pr_trackers: dict[str, ProgressTracker] = {}
        github_conn = self._reader.get_connector("github")

        async def _start_pr_scope_tracker(repo_name: str) -> None:
            if repo_name in pr_trackers:
                return
            scope_key = make_scope_key("github", "repo", repo_name)
            tracker = ProgressTracker(
                tenant_id=self._tenant_id,
                entity_type="pull_requests",
                scope_key=scope_key,
            )
            estimate: int | None = None
            if github_conn is not None and hasattr(github_conn, "count_prs_for_repo"):
                try:
                    estimate = await github_conn.count_prs_for_repo(
                        repo_name, since=since_by_repo.get(repo_name) or since,
                    )
                except Exception:
                    logger.exception(
                        "[progress] %s: count_prs_for_repo raised — "
                        "tracker without estimate",
                        repo_name,
                    )
                    estimate = None
            await tracker.start_scope(estimate=estimate, phase="fetching")
            pr_trackers[repo_name] = tracker

        try:
            async for repo_name, raw_prs in self._reader.fetch_pull_requests_batched(
                since=since,
                since_by_repo=since_by_repo,
            ):
                # "Starting" signal: connector emits (repo_name, None) before
                # any API calls so the UI can show progress immediately.
                if raw_prs is None:
                    # If the initial source-count call failed (total_sources=0)
                    # retry now — the connector's repo cache is warm after the
                    # first yield, so this will succeed.
                    if total_sources == 0:
                        try:
                            total_sources = await self._reader.get_pull_request_source_count()
                        except Exception:
                            logger.exception("Retry of source count failed")

                    await _update_ingestion_progress(
                        self._tenant_id, "pull_requests",
                        status="running",
                        total_sources=total_sources or None,
                        sources_done=repos_done,
                        records_ingested=total_count,
                        current_source=repo_name,
                    )
                    # FDD-OPS-015 — start tracker on the "starting" signal
                    await _start_pr_scope_tracker(repo_name)
                    continue

                # Normalize this repo's batch
                normalized = []
                for raw in raw_prs:
                    try:
                        pr_data = normalize_pull_request(raw, self._tenant_id)
                        pr_data["_head_ref"] = raw.get("head_ref", "")
                        pr_data["_base_ref"] = raw.get("base_ref", "")
                        normalized.append(pr_data)
                    except Exception:
                        logger.exception("Error normalizing PR: %s", raw.get("id"))

                if not normalized:
                    repos_done += 1
                    continue

                # Populate linked_issue_ids by scanning title + branch refs
                # against the tenant's issue-key index.
                apply_pr_issue_links(normalized, issue_key_map)

                # Upsert this batch to DB immediately
                batch_count = await self._upsert_pull_requests(normalized)
                total_count += batch_count
                repos_done += 1

                # Publish this batch to Kafka
                events = []
                for pr in normalized:
                    event = {k: v for k, v in pr.items() if not k.startswith("_")}
                    events.append((str(pr["external_id"]), event))
                await publish_batch(self._producer, TOPIC_PR_NORMALIZED, events)

                # FDD-OPS-014 step 2.4: advance this repo's scope watermark.
                # Writes accumulate even though reads are still global '*';
                # follow-up commit changes the connector to read this dict
                # via since_by_repo.
                if batch_count > 0:
                    repo_scope = make_scope_key("github", "repo", repo_name)
                    async with get_session(self._tenant_id) as session:
                        await _set_watermark(
                            session, self._tenant_id, "pull_requests",
                            started_at, batch_count,
                            scope_key=repo_scope,
                        )

                # Update progress in DB (queryable by API)
                await _update_ingestion_progress(
                    self._tenant_id, "pull_requests",
                    status="running",
                    sources_done=repos_done,
                    records_ingested=total_count,
                    current_source=repo_name,
                )

                # FDD-OPS-015 — tick + finish (one batch == repo done in PR flow)
                if repo_name in pr_trackers:
                    await pr_trackers[repo_name].tick(
                        items_added=batch_count, phase="persisting",
                    )
                    # PR connector yields one batch per repo (not paginated
                    # within a repo at this layer), so we mark done here.
                    await pr_trackers[repo_name].finish(status="done")

                logger.info(
                    "Batch persisted: %d PRs from %s (total: %d PRs, %d/%d repos)",
                    batch_count, repo_name, total_count, repos_done, total_sources,
                )

        except Exception as exc:
            await _update_ingestion_progress(
                self._tenant_id, "pull_requests",
                status="failed",
                sources_done=repos_done,
                records_ingested=total_count,
                error_message=str(exc),
                finished_at=datetime.now(timezone.utc),
            )
            # FDD-OPS-015 — mark any in-flight tracker as failed.
            # finish() is idempotent (no-op on already-done trackers).
            for tr in pr_trackers.values():
                try:
                    await tr.finish(status="failed", error=str(exc))
                except Exception:
                    logger.exception(
                        "[progress] failed to mark PR tracker as failed",
                    )
            raise

        # Mark ingestion as completed
        await _update_ingestion_progress(
            self._tenant_id, "pull_requests",
            status="completed" if total_count > 0 else "idle",
            sources_done=repos_done,
            records_ingested=total_count,
            current_source=None,
            finished_at=datetime.now(timezone.utc),
        )

        if total_count == 0:
            logger.info("No new pull requests to sync")
            return 0

        # Update watermark after all batches complete
        async with get_session(self._tenant_id) as session:
            await _set_watermark(
                session, self._tenant_id, "pull_requests",
                datetime.now(timezone.utc), total_count,
            )

        logger.info(
            "PR sync complete: %d PRs from %d repos persisted",
            total_count, repos_done,
        )
        return total_count

    async def _sync_issues(self) -> int:
        """Stream issues from Jira PER PROJECT, persisting each batch immediately.

        FDD-OPS-012 — replaces the previous bulk-fetch-then-persist pattern
        (everything in RAM until JQL pagination + ALL changelog HTTP calls
        complete, then single upsert) with per-page streaming. Mirrors the
        pattern that PRs adopted in commit 7f9f339.

        FDD-OPS-014 step 2.3 — uses PER-PROJECT watermarks. Each project has
        its own scope_key='jira:project:<KEY>' row in pipeline_watermarks.
        Adding a new project = backfill ONLY that scope. Per-project failures
        don't reset other projects' watermarks. The legacy global '*'
        watermark is also updated at end-of-cycle for backwards compat.

        Properties:
        - Time-to-first-row: < 10s
        - Memory: ~one page in flight, not all-projects
        - Crash recovery: lose ≤ 1 batch of work
        - Per-project incremental sync: only fetch new since last project run
        """
        # Resolve project keys via dynamic discovery (kill-switch via env var).
        # No fallback to a static env var list — that path was deprecated when
        # we landed discovery-only (ingestion-spec §2.3). Empty list = nothing
        # to sync this cycle.
        project_keys: list[str] = []
        if settings.dynamic_jira_discovery_enabled:
            try:
                async with get_session(self._tenant_id) as session:
                    resolver = ModeResolver(session)
                    project_keys = await resolver.resolve_active_projects(self._tenant_id)
                logger.info(
                    "[issues] resolved %d active Jira projects for tenant %s",
                    len(project_keys), self._tenant_id,
                )
            except Exception:
                logger.exception(
                    "[issues] ModeResolver failed for tenant %s — skipping cycle",
                    self._tenant_id,
                )
                return 0

        if not project_keys:
            logger.info("[issues] no active projects, nothing to sync")
            return 0

        # FDD-OPS-014 step 2.3: load per-project watermarks (scope_key per
        # project). Missing rows return None = full backfill for that scope.
        project_scopes = [
            make_scope_key("jira", "project", pk) for pk in project_keys
        ]
        async with get_session(self._tenant_id) as session:
            scope_to_wm = await _list_watermarks_by_scope(
                session, self._tenant_id, "issues", project_scopes,
            )
        since_by_project: dict[str, datetime | None] = {
            pk: scope_to_wm[make_scope_key("jira", "project", pk)]
            for pk in project_keys
        }

        # Log which projects need backfill vs which have an existing watermark
        backfill_count = sum(1 for v in since_by_project.values() if v is None)
        incremental_count = len(project_keys) - backfill_count
        logger.info(
            "[issues] watermark plan: %d projects backfill (no scope), "
            "%d projects incremental",
            backfill_count, incremental_count,
        )

        # FDD-OPS-015 lite: pre-flight progress signal so operators see the
        # scope BEFORE we start hammering the API.
        started_at = datetime.now(timezone.utc)
        await _update_ingestion_progress(
            self._tenant_id, "issues",
            status="running",
            total_sources=len(project_keys),
            sources_done=0,
            records_ingested=0,
            current_source=None,
            started_at=started_at,
        )

        total_count = 0
        projects_done: set[str] = set()
        current_project: str | None = None
        per_project_count: dict[str, int] = {pk: 0 for pk in project_keys}

        # FDD-OPS-015 — per-scope progress trackers, lazily created on
        # first sight of a project_key in the iterator. Each tracker
        # owns its own ETA computation and persists to pipeline_progress.
        from src.contexts.pipeline.progress_tracker import ProgressTracker
        trackers: dict[str, ProgressTracker] = {}

        # Get the underlying Jira connector for pre-flight count calls.
        # None when Jira isn't configured (then trackers run without estimates).
        jira_conn = self._reader.get_connector("jira")

        async def _start_scope_tracker(project_key: str) -> None:
            """Create + start a tracker for a project, with pre-flight count."""
            if project_key in trackers:
                return
            scope_key = make_scope_key("jira", "project", project_key)
            tracker = ProgressTracker(
                tenant_id=self._tenant_id,
                entity_type="issues",
                scope_key=scope_key,
            )
            # Best-effort estimate. None on failure/timeout — UI shows "?"
            estimate: int | None = None
            if jira_conn is not None and hasattr(jira_conn, "count_issues_for_project"):
                try:
                    estimate = await jira_conn.count_issues_for_project(
                        project_key,
                        since=since_by_project.get(project_key),
                    )
                except Exception:
                    logger.exception(
                        "[progress] %s: count_issues_for_project raised — "
                        "tracker will run without estimate",
                        project_key,
                    )
                    estimate = None
            await tracker.start_scope(estimate=estimate, phase="fetching")
            trackers[project_key] = tracker

        async def _advance_project_watermark(project_key: str) -> None:
            """Update watermark for `jira:project:<KEY>` after that project finishes.

            Only advances when count > 0 — empty syncs (incremental with no
            changes) leave the watermark unchanged so a subsequent failed
            cycle doesn't accidentally claim "synced through now()".
            """
            count_for_project = per_project_count.get(project_key, 0)
            if count_for_project == 0:
                return
            scope_key = make_scope_key("jira", "project", project_key)
            async with get_session(self._tenant_id) as session:
                await _set_watermark(
                    session, self._tenant_id, "issues",
                    started_at, count_for_project, scope_key=scope_key,
                )
            logger.info(
                "[issues] watermark advanced: %s → %s (%d issues this cycle)",
                scope_key, started_at.isoformat(), count_for_project,
            )

        try:
            async for project_key, raw_batch in self._reader.fetch_issues_batched(
                project_keys=project_keys,
                since_by_project=since_by_project,
            ):
                # Project change marker for ingestion progress + watermark advance
                if project_key != current_project:
                    if current_project is not None:
                        # Previous project finished — advance its scope watermark
                        await _advance_project_watermark(current_project)
                        projects_done.add(current_project)
                        # FDD-OPS-015 — finish previous tracker (status='done')
                        if current_project in trackers:
                            await trackers[current_project].finish(status="done")
                    current_project = project_key
                    # FDD-OPS-015 — pre-flight count + start tracker for new scope
                    await _start_scope_tracker(project_key)
                    await _update_ingestion_progress(
                        self._tenant_id, "issues",
                        status="running",
                        sources_done=len(projects_done),
                        records_ingested=total_count,
                        current_source=project_key,
                    )

                # FDD-OPS-013: changelogs are INLINE from JQL expand=changelog.
                # No extra HTTP round-trip per issue.
                normalized: list[dict[str, Any]] = []
                for raw in raw_batch:
                    try:
                        issue_changelogs = extract_status_transitions_inline(raw)
                        issue_data = normalize_issue(
                            raw,
                            self._tenant_id,
                            self._status_mapping,
                            changelogs=issue_changelogs,
                        )
                        normalized.append(issue_data)
                    except Exception:
                        logger.exception(
                            "[issues] normalize error in project %s: id=%s",
                            project_key, raw.get("id"),
                        )

                if not normalized:
                    continue

                # Persist this batch immediately (FDD-OPS-012)
                batch_count = await self._upsert_issues(normalized)
                total_count += batch_count
                per_project_count[project_key] = per_project_count.get(project_key, 0) + batch_count

                # Emit Kafka events for this batch only
                events = [
                    (str(issue["external_id"]), issue)
                    for issue in normalized
                ]
                await publish_batch(
                    self._producer, TOPIC_ISSUE_NORMALIZED, events,
                )

                # FDD-OPS-015 — tick the tracker for live ETA on this scope
                if project_key in trackers:
                    await trackers[project_key].tick(
                        items_added=batch_count, phase="persisting",
                    )

                # Per-batch progress update (operator can grep the log to
                # confirm forward progress)
                tracker_eta = trackers[project_key].current_eta if project_key in trackers else None
                tracker_rate = trackers[project_key].current_rate if project_key in trackers else 0
                logger.info(
                    "[issues] batch persisted: %s +%d (project total: %d, "
                    "tenant total: %d, rate=%.1f/s, eta=%ss)",
                    project_key, batch_count,
                    per_project_count[project_key], total_count,
                    tracker_rate,
                    tracker_eta if tracker_eta is not None else "?",
                )

                await _update_ingestion_progress(
                    self._tenant_id, "issues",
                    records_ingested=total_count,
                    current_source=project_key,
                )

            # Final project after the loop: advance its watermark + mark done
            if current_project is not None:
                await _advance_project_watermark(current_project)
                projects_done.add(current_project)
                # FDD-OPS-015 — finish the last tracker (status='done')
                if current_project in trackers:
                    await trackers[current_project].finish(status="done")

            logger.info(
                "[issues] sync complete: %d issues across %d projects "
                "(per-project counts: %s)",
                total_count, len(projects_done),
                {k: v for k, v in per_project_count.items() if v > 0},
            )

            # Update legacy global '*' watermark for backwards compat. Some
            # monitoring queries / Pipeline Monitor still read by entity
            # without scope. Migration 011 (FDD-OPS-014 step 2.7) will drop
            # the legacy unique constraint after a successful per-source
            # cycle; until then both keep updating.
            if total_count > 0:
                async with get_session(self._tenant_id) as session:
                    await _set_watermark(
                        session, self._tenant_id, "issues",
                        started_at, total_count,
                        # default scope_key='*' — legacy global row
                    )

            # Record per-project sync outcome for guardrails (success only —
            # batches that errored mid-stream are logged but don't block)
            if settings.dynamic_jira_discovery_enabled and projects_done:
                try:
                    async with get_session(self._tenant_id) as session:
                        guardrails = Guardrails(session)
                        for pk in projects_done:
                            await guardrails.record_sync_outcome(
                                self._tenant_id, pk, success=True,
                            )
                except Exception:
                    logger.exception(
                        "[issues] failed to record guardrail outcomes",
                    )

            await _update_ingestion_progress(
                self._tenant_id, "issues",
                status="completed",
                sources_done=len(projects_done),
                records_ingested=total_count,
                current_source=None,
                finished_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            await _update_ingestion_progress(
                self._tenant_id, "issues",
                status="failed",
                sources_done=len(projects_done),
                records_ingested=total_count,
                current_source=current_project,
                finished_at=datetime.now(timezone.utc),
                error_message=str(exc)[:500],
            )
            # FDD-OPS-015 — mark the in-flight tracker as failed so operators
            # see WHICH scope died (not just an aggregate "issues failed").
            if current_project and current_project in trackers:
                try:
                    await trackers[current_project].finish(
                        status="failed", error=str(exc),
                    )
                except Exception:
                    logger.exception(
                        "[progress] failed to mark tracker as failed",
                    )
            logger.exception("[issues] sync cycle failed")
            raise

        return total_count

    async def _sync_deployments(self) -> int:
        """Read deployments from source connectors, upsert to PULSE DB, publish to Kafka.

        FDD-OPS-014 step 2.5 — writes per-repo scope watermarks alongside
        the legacy global '*' row. Per-repo READ + per-job streaming are
        follow-ups; this commit accumulates the rows so they're available
        when the connector refactor lands.

        Granularity choice (Q2 of phase-2-plan): repo-level scope rather
        than per-job. Volume is low (~1.4k deploys at Webmotors scale); the
        repo dimension matches the cross-source linking model (PR↔deploy
        is by repo+sha) and avoids an explosion of scope rows for
        ephemeral Jenkins jobs.
        """
        started_at = datetime.now(timezone.utc)
        # FDD-OPS-014 step 2.5-B: read per-repo watermarks for deployments.
        # Pre-load all rows where scope_key starts with 'jenkins:repo:' so
        # the connector can resolve each job's `since` via job→repo mapping.
        async with get_session(self._tenant_id) as session:
            since = await _get_watermark(session, self._tenant_id, "deployments")
            from sqlalchemy import select as _select
            result = await session.execute(
                _select(
                    PipelineWatermark.scope_key,
                    PipelineWatermark.last_synced_at,
                ).where(
                    PipelineWatermark.entity_type == "deployments",
                    PipelineWatermark.scope_key.like("jenkins:repo:%"),
                )
            )
            since_by_repo: dict[str, datetime | None] = {}
            for scope_key_str, last_synced in result.all():
                # 'jenkins:repo:owner/name' → 'owner/name'
                repo = scope_key_str[len("jenkins:repo:"):]
                since_by_repo[repo] = last_synced

        logger.info(
            "[deployments] watermark plan: %d repos with per-scope rows, "
            "global '*' fallback=%s",
            len(since_by_repo),
            since.isoformat() if since else "None (full backfill)",
        )

        raw_deployments = await self._reader.fetch_deployments(
            since=since, since_by_repo=since_by_repo,
        )
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

        # Group per repo to track per-scope counts for watermark writes.
        per_repo_count: dict[str, int] = {}
        for d in normalized:
            repo = d.get("repo") or "unknown"
            per_repo_count[repo] = per_repo_count.get(repo, 0) + 1

        # Upsert to PULSE DB
        count = await self._upsert_deployments(normalized)

        # FDD-OPS-014 step 2.5: advance per-repo deploy watermarks. Reads
        # still use global '*' until the fetcher refactor lands.
        async with get_session(self._tenant_id) as session:
            for repo, repo_count in per_repo_count.items():
                if repo_count == 0:
                    continue
                repo_scope = make_scope_key("jenkins", "repo", repo)
                await _set_watermark(
                    session, self._tenant_id, "deployments",
                    started_at, repo_count, scope_key=repo_scope,
                )
        logger.info(
            "[deployments] advanced %d per-repo watermarks (jenkins:repo:*)",
            len([c for c in per_repo_count.values() if c > 0]),
        )

        # INC-004 — forward-path linker: bind newly ingested deploys back to
        # any merged PRs in the same repo that were still missing
        # `deployed_at`. Scoped to the min deployed_at in this batch so the
        # UPDATE does not scan the whole table.
        try:
            deploy_timestamps = [
                d.get("deployed_at") for d in normalized if d.get("deployed_at")
            ]
            if deploy_timestamps:
                since_at = min(deploy_timestamps)
                linked = await link_recent_deploys_to_prs(
                    tenant_id=self._tenant_id,
                    since_at=since_at,
                )
                if linked:
                    logger.info(
                        "INC-004 linked %d PRs to %d newly ingested deploys",
                        linked, len(deploy_timestamps),
                    )
        except Exception:
            # Never fail the sync cycle because of the linker — it's a
            # DB-only UPDATE that we can always reapply via the admin endpoint.
            logger.exception("INC-004 forward-path linker failed (non-fatal)")

        # FDD-DSH-050 forward hook: pair newly-arrived deploys with their
        # incident anchors. Re-classifies failures whose state may have
        # changed because a new success ingested closed an open incident.
        # Same non-fatal pattern as INC-004 — never breaks the sync cycle.
        try:
            mttr_updated = await pair_recent_incidents(
                tenant_id=self._tenant_id,
                since_at=datetime.now(timezone.utc),
            )
            if mttr_updated:
                logger.info(
                    "INC-005/MTTR forward-pair: %d failure rows reclassified",
                    mttr_updated,
                )
        except Exception:
            logger.exception(
                "INC-005/MTTR forward-pair failed (non-fatal) — admin "
                "backfill endpoint can always reapply",
            )

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
        """Read sprints from source connectors, upsert to PULSE DB, publish to Kafka."""
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
                            "is_merged": data.get("is_merged", False),
                            "merged_at": data["merged_at"],
                            "first_review_at": data.get("first_review_at"),
                            "approved_at": data.get("approved_at"),
                            "additions": data["additions"],
                            "deletions": data["deletions"],
                            "files_changed": data.get("files_changed", 0),
                            "commits_count": data.get("commits_count", 0),
                            "reviewers": data.get("reviewers", []),
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
                            "issue_key": issue_data.get("issue_key"),
                            # FDD-KB-013 — keep description fresh on every sync.
                            # Falls back to existing value when connector returns
                            # None (e.g. transient Jira fetch omitted the field).
                            "description": issue_data.get("description"),
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
                            # FDD-OPS-018 — status + goal were missing from
                            # this ON CONFLICT set, so existing sprints kept
                            # their stale (empty) status forever. Active
                            # sprints transitioning to closed never updated.
                            "status": sprint_data.get("status"),
                            "goal": sprint_data.get("goal"),
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




# Backward-compatible alias (referenced in some scripts/tests)
DevLakeSyncWorker = DataSyncWorker


async def run_sync_loop() -> None:
    """Run sync in a loop for local development (every 15 minutes).

    Handles SIGTERM/SIGINT for graceful shutdown.
    """
    worker = DataSyncWorker()
    running = True

    def _handle_signal():
        nonlocal running
        running = False
        logger.info("Received shutdown signal, stopping sync loop")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info("Data sync loop started (interval=900s)")

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
        logger.info("Data sync loop stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run_sync_loop())
