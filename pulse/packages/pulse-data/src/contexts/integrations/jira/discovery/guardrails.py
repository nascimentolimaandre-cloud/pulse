"""Guardrails — project cap enforcement, rate budgeting, auto-pause.

Protects tenants from over-ingestion and cascading failures.

Invariant: ``blocked`` projects are NEVER modified by guardrails.
"""

from __future__ import annotations

import logging
import time
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.contexts.integrations.jira.discovery.repository import (
    DiscoveryRepository,
    jira_project_catalog,
)

logger = logging.getLogger(__name__)


def _get_redis_client() -> aioredis.Redis:
    """Create an async Redis client from settings."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


class Guardrails:
    """Enforces safety constraints on Jira project ingestion."""

    def __init__(
        self,
        session: AsyncSession,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        self._session = session
        self._repo = DiscoveryRepository(session)
        self._redis = redis_client

    async def _get_redis(self) -> aioredis.Redis:
        """Lazily initialize Redis client."""
        if self._redis is None:
            self._redis = _get_redis_client()
        return self._redis

    # ------------------------------------------------------------------
    # Project cap enforcement
    # ------------------------------------------------------------------

    async def enforce_project_cap(self, tenant_id: UUID) -> int:
        """If active project count exceeds max, pause lowest-scoring projects.

        Returns count of projects paused.
        """
        config = await self._repo.get_tenant_config(tenant_id)
        if not config:
            return 0

        max_active = config.get("max_active_projects", 100)

        # Count active non-blocked projects
        result = await self._session.execute(
            select(func.count()).select_from(jira_project_catalog).where(
                and_(
                    jira_project_catalog.c.tenant_id == tenant_id,
                    jira_project_catalog.c.status == "active",
                )
            )
        )
        active_count = result.scalar() or 0

        if active_count <= max_active:
            return 0

        excess = active_count - max_active
        logger.warning(
            "Tenant %s has %d active projects (cap=%d), pausing %d lowest-scoring",
            tenant_id, active_count, max_active, excess,
        )

        # Select lowest pr_reference_count active projects (non-blocked)
        to_pause = await self._session.execute(
            select(jira_project_catalog.c.project_key).where(
                and_(
                    jira_project_catalog.c.tenant_id == tenant_id,
                    jira_project_catalog.c.status == "active",
                )
            )
            .order_by(jira_project_catalog.c.pr_reference_count.asc())
            .limit(excess)
        )
        keys_to_pause = [row[0] for row in to_pause.all()]

        paused = 0
        for key in keys_to_pause:
            await self._repo.update_project_status(
                tenant_id, key,
                status="paused",
                actor="system",
                reason=f"Project cap enforced: {active_count} > {max_active}",
            )
            await self._repo.append_audit(
                tenant_id,
                event_type="project_cap_enforced",
                project_key=key,
                actor="system",
                after={"status": "paused"},
                reason=f"Active count {active_count} exceeded cap {max_active}",
            )
            paused += 1

        return paused

    # ------------------------------------------------------------------
    # Rate budget (Redis token bucket)
    # ------------------------------------------------------------------

    async def enforce_rate_budget(self, tenant_id: UUID, issues_to_fetch: int) -> bool:
        """Check if the tenant has rate budget for the requested issue count.

        Uses a Redis token bucket keyed ``jira:ratebudget:{tenant_id}``.
        Bucket size = max_issues_per_hour, refill = max_issues_per_hour / 3600 per second.

        Returns True if budget is available (tokens consumed), False otherwise.
        """
        config = await self._repo.get_tenant_config(tenant_id)
        if not config:
            return True  # No config = no guardrails = allow

        max_per_hour = config.get("max_issues_per_hour", 20000)
        refill_rate = max_per_hour / 3600.0

        redis = await self._get_redis()
        bucket_key = f"jira:ratebudget:{tenant_id}"
        now = time.time()

        # Atomic token bucket via Lua script
        lua_script = """
        local key = KEYS[1]
        local requested = tonumber(ARGV[1])
        local max_tokens = tonumber(ARGV[2])
        local refill_rate = tonumber(ARGV[3])
        local now = tonumber(ARGV[4])

        local data = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(data[1])
        local last_refill = tonumber(data[2])

        if tokens == nil then
            tokens = max_tokens
            last_refill = now
        end

        -- Refill
        local elapsed = now - last_refill
        tokens = math.min(max_tokens, tokens + elapsed * refill_rate)
        last_refill = now

        if tokens >= requested then
            tokens = tokens - requested
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
            redis.call('EXPIRE', key, 7200)
            return 1
        else
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
            redis.call('EXPIRE', key, 7200)
            return 0
        end
        """
        result = await redis.eval(
            lua_script, 1, bucket_key,
            str(issues_to_fetch), str(max_per_hour), str(refill_rate), str(now),
        )
        allowed = bool(int(result))

        if not allowed:
            logger.warning(
                "Rate budget exhausted for tenant %s: requested %d issues",
                tenant_id, issues_to_fetch,
            )
        return allowed

    # ------------------------------------------------------------------
    # Sync outcome tracking + auto-pause
    # ------------------------------------------------------------------

    async def record_sync_outcome(
        self,
        tenant_id: UUID,
        project_key: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Record sync outcome. Auto-pauses after 5 consecutive failures.

        Invariant: blocked projects are never modified.
        """
        project = await self._repo.get_project(tenant_id, project_key)
        if not project:
            logger.warning(
                "record_sync_outcome: project %s not found for tenant %s",
                project_key, tenant_id,
            )
            return

        # Never modify blocked projects
        if project["status"] == "blocked":
            logger.debug(
                "Skipping sync outcome for blocked project %s", project_key,
            )
            return

        current_failures = project.get("consecutive_failures", 0) or 0

        if success:
            await self._repo.upsert_project(
                tenant_id, project_key,
                consecutive_failures=0,
                last_sync_status="success",
                last_error=None,
            )
        else:
            new_failures = current_failures + 1
            update_fields = {
                "consecutive_failures": new_failures,
                "last_sync_status": "failed",
                "last_error": error,
            }
            await self._repo.upsert_project(tenant_id, project_key, **update_fields)

            if new_failures >= 5 and project["status"] != "paused":
                await self._repo.update_project_status(
                    tenant_id, project_key,
                    status="paused",
                    actor="system",
                    reason=f"Auto-paused after {new_failures} consecutive sync failures",
                )
                await self._repo.append_audit(
                    tenant_id,
                    event_type="project_auto_paused",
                    project_key=project_key,
                    actor="system",
                    after={"status": "paused", "consecutive_failures": new_failures},
                    reason=f"Auto-paused after {new_failures} consecutive failures",
                )
                logger.warning(
                    "Auto-paused project %s for tenant %s after %d failures",
                    project_key, tenant_id, new_failures,
                )
