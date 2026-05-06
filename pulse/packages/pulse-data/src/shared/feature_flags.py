"""FDD-OBS-001 PR 0 — Per-tenant feature flags.

Cross-cutting helper that any context/route can call to gate features
behind a per-tenant toggle. Default is **fail-closed**: when a flag row
doesn't exist or Redis/DB are unreachable, returns `False`.

Usage:
    from src.shared.feature_flags import is_enabled

    if await is_enabled(tenant_id, "obs.signals.enabled"):
        return await observability_path(...)
    return await fallback_path(...)

Design (architect-validated):
  - Reads `tenant_feature_flags` table (migration 016) under RLS.
  - 60s Redis cache (faster than the existing tenant-capabilities 5min
    TTL because feature flags are toggled by ops more frequently).
  - Lazy Redis import — same pattern as `contexts/tenant/service.py`.
  - Graceful degradation when Redis unavailable: falls back to direct DB
    read; never raises on infra failure.
  - Default `False` when row absent or any error happens — fail-closed
    for safety (a missing config never accidentally enables a paid
    feature).

Why a separate module (not in `contexts/`):
  - Feature flags are infrastructure, not a bounded context. Pattern
    matches `src/shared/{kafka,http_client,metrics,tenant}.py` —
    cross-cutting concerns live here.
  - Used by routes across all bounded contexts (metrics, observability,
    pipeline, etc.) — putting it under any single context creates
    awkward dependencies.

Cache invalidation:
  - On write (set_flag), invalidate the cache key immediately.
  - 60s TTL caps staleness for ops-driven toggles.
  - No cross-process broadcast — accept up to 60s drift between
    pulse-data instances (acceptable for ops-controlled toggles).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text

from src.config import settings
from src.database import get_session

logger = logging.getLogger(__name__)

# Cache key + TTL — short enough that ops toggles take effect quickly.
_CACHE_KEY_PREFIX = "ff:"
_CACHE_TTL_SECONDS = 60


class _RedisLike(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...
    async def delete(self, key: str) -> int: ...


async def _get_redis() -> _RedisLike | None:
    """Return an async Redis client or None if unavailable.

    Mirrors the lazy-import pattern in `contexts/tenant/service.py`.
    Connection failures are swallowed — feature-flag reads always
    have a DB fallback path.
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
        logger.debug("Redis unavailable for feature_flags cache", exc_info=True)
        return None


def _cache_key(tenant_id: UUID, flag_key: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{tenant_id}:{flag_key}"


async def _read_cache(tenant_id: UUID, flag_key: str) -> bool | None:
    """Return cached enabled value, or None on cache miss / error."""
    redis = await _get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(_cache_key(tenant_id, flag_key))
        if raw is None:
            return None
        # Stored as JSON to allow future expansion (metadata, etc.).
        return bool(json.loads(raw))
    except Exception:
        logger.debug("Feature flag cache read failed", exc_info=True)
        return None


async def _write_cache(tenant_id: UUID, flag_key: str, value: bool) -> None:
    redis = await _get_redis()
    if redis is None:
        return
    try:
        await redis.setex(
            _cache_key(tenant_id, flag_key), _CACHE_TTL_SECONDS, json.dumps(value)
        )
    except Exception:
        logger.debug("Feature flag cache write failed", exc_info=True)


async def _invalidate_cache(tenant_id: UUID, flag_key: str) -> None:
    redis = await _get_redis()
    if redis is None:
        return
    try:
        await redis.delete(_cache_key(tenant_id, flag_key))
    except Exception:
        logger.debug("Feature flag cache invalidate failed", exc_info=True)


async def _read_db(tenant_id: UUID, flag_key: str) -> bool:
    """Direct DB read under RLS. Default False when row absent."""
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT enabled
                FROM tenant_feature_flags
                WHERE tenant_id = :tenant_id AND flag_key = :flag_key
                """
            ),
            {"tenant_id": str(tenant_id), "flag_key": flag_key},
        )
        row = result.first()
        return bool(row[0]) if row else False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def is_enabled(tenant_id: UUID, flag_key: str) -> bool:
    """Check whether a feature flag is enabled for the tenant.

    Returns False when:
      - The flag has never been set for this tenant (no row).
      - The DB / Redis are unavailable (fail-closed).
      - Any unexpected error occurs.

    Args:
        tenant_id: Tenant UUID (RLS scope).
        flag_key: Stable identifier for the feature, e.g.
            "obs.signals.enabled", "kanban.aging_alerts.enabled".
    """
    if not flag_key:
        return False

    cached = await _read_cache(tenant_id, flag_key)
    if cached is not None:
        return cached

    try:
        value = await _read_db(tenant_id, flag_key)
    except Exception:
        logger.warning(
            "feature_flags DB read failed — failing closed",
            extra={"tenant_id": str(tenant_id), "flag_key": flag_key},
            exc_info=True,
        )
        return False

    await _write_cache(tenant_id, flag_key, value)
    return value


async def set_flag(
    tenant_id: UUID, flag_key: str, enabled: bool, *, metadata: dict[str, Any] | None = None,
) -> None:
    """Set / upsert a feature flag for a tenant. Invalidates cache.

    Intended for admin endpoints + bootstrap scripts. RLS context must
    be set on the session (managed by `get_session`).
    """
    if not flag_key:
        raise ValueError("flag_key cannot be empty")
    metadata_json = json.dumps(metadata or {})

    async with get_session(tenant_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO tenant_feature_flags (tenant_id, flag_key, enabled, metadata)
                VALUES (:tenant_id, :flag_key, :enabled, CAST(:metadata AS jsonb))
                ON CONFLICT (tenant_id, flag_key)
                DO UPDATE SET
                    enabled    = EXCLUDED.enabled,
                    metadata   = EXCLUDED.metadata,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "flag_key": flag_key,
                "enabled": enabled,
                "metadata": metadata_json,
            },
        )
        await session.commit()

    await _invalidate_cache(tenant_id, flag_key)
