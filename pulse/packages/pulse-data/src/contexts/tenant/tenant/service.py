"""Tenant capability evaluation service.

Pure functions that compute capability flags from DB counts, plus a cached
resolver that wraps the heuristics in Redis with a 5-minute TTL.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.contexts.tenant.schemas import CapabilitySources, TenantCapabilities
from src.database import get_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds — single source of truth, exported so tests can import them
# ---------------------------------------------------------------------------

SPRINT_THRESHOLD = 3  # >= 3 sprints in last 180d = tenant uses sprints
KANBAN_THRESHOLD = 10  # >= 10 issues in_progress = tenant has active flow
SPRINT_LOOKBACK_DAYS = 180

CACHE_KEY_PREFIX = "tenant:capabilities:"
CACHE_TTL_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Pure heuristic helpers (unit-tested)
# ---------------------------------------------------------------------------


def evaluate_has_sprints(sprint_count: int) -> bool:
    """Tenant has sprints when >= SPRINT_THRESHOLD sprints in the lookback window."""
    return sprint_count >= SPRINT_THRESHOLD


def evaluate_has_kanban(in_progress_count: int) -> bool:
    """Tenant has active kanban flow when >= KANBAN_THRESHOLD in-progress issues."""
    return in_progress_count >= KANBAN_THRESHOLD


# ---------------------------------------------------------------------------
# Redis cache wrapper (optional — graceful when Redis is unavailable)
# ---------------------------------------------------------------------------


class _RedisLike(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...


async def _get_redis() -> _RedisLike | None:
    """Return an async Redis client or None if unavailable.

    We import redis.asyncio lazily so the module can still be imported in
    environments without the redis package installed. Any connection failure
    is swallowed — the endpoint stays responsive with a DB-only path.
    """
    try:
        from redis import asyncio as aioredis  # type: ignore[import-not-found]

        client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        await client.ping()
        return client
    except Exception:
        logger.debug("Redis unavailable for tenant capabilities cache", exc_info=True)
        return None


async def _read_cache(tenant_id: UUID) -> TenantCapabilities | None:
    redis = await _get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(f"{CACHE_KEY_PREFIX}{tenant_id}")
        if raw is None:
            return None
        return TenantCapabilities.model_validate(json.loads(raw))
    except Exception:
        logger.warning("Failed to read tenant capability cache", exc_info=True)
        return None


async def _write_cache(tenant_id: UUID, caps: TenantCapabilities) -> None:
    redis = await _get_redis()
    if redis is None:
        return
    try:
        payload = caps.model_dump_json(by_alias=False)
        await redis.setex(f"{CACHE_KEY_PREFIX}{tenant_id}", CACHE_TTL_SECONDS, payload)
    except Exception:
        logger.warning("Failed to write tenant capability cache", exc_info=True)


# ---------------------------------------------------------------------------
# DB query — the "fresh" compute path
# ---------------------------------------------------------------------------


async def _count_sprints(session: AsyncSession) -> int:
    """Count sprints started within the last SPRINT_LOOKBACK_DAYS."""
    row = await session.execute(
        text(
            f"""
            SELECT COUNT(*) AS cnt
            FROM eng_sprints
            WHERE start_date >= NOW() - INTERVAL '{SPRINT_LOOKBACK_DAYS} days'
            """
        )
    )
    return int(row.scalar() or 0)


async def _count_in_progress_issues(session: AsyncSession) -> int:
    """Count issues currently in an in-progress or in-review flow state."""
    row = await session.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM eng_issues
            WHERE normalized_status IN ('in_progress', 'in_review')
            """
        )
    )
    return int(row.scalar() or 0)


async def _count_issues_30d(session: AsyncSession) -> int:
    """Count issues created or updated in the last 30 days (informational)."""
    row = await session.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM eng_issues
            WHERE created_at >= NOW() - INTERVAL '30 days'
               OR updated_at >= NOW() - INTERVAL '30 days'
            """
        )
    )
    return int(row.scalar() or 0)


def _source_connection_flags() -> CapabilitySources:
    """Connector-level connectivity flags — based on configured tokens."""
    return CapabilitySources(
        jira_connected=bool(settings.jira_api_token),
        github_connected=bool(settings.github_token),
        jenkins_connected=bool(settings.jenkins_api_token),
    )


async def compute_capabilities(tenant_id: UUID) -> TenantCapabilities:
    """Compute capabilities freshly from the database (no cache)."""
    sprint_count = 0
    in_progress_count = 0
    issues_30d = 0

    try:
        async with get_session(tenant_id) as session:
            sprint_count = await _count_sprints(session)
            in_progress_count = await _count_in_progress_issues(session)
            issues_30d = await _count_issues_30d(session)
    except Exception:
        logger.warning("Error computing tenant capabilities — returning safe defaults", exc_info=True)

    return TenantCapabilities(
        tenant_id=tenant_id,
        has_sprints=evaluate_has_sprints(sprint_count),
        has_kanban=evaluate_has_kanban(in_progress_count),
        sprint_count=sprint_count,
        issue_count_30d=issues_30d,
        last_evaluated_at=datetime.now(timezone.utc),
        sources=_source_connection_flags(),
    )


async def get_capabilities(tenant_id: UUID, *, use_cache: bool = True) -> TenantCapabilities:
    """Return cached capabilities or compute + cache if missing/expired."""
    if use_cache:
        cached = await _read_cache(tenant_id)
        if cached is not None:
            return cached

    fresh = await compute_capabilities(tenant_id)
    if use_cache:
        await _write_cache(tenant_id, fresh)
    return fresh
