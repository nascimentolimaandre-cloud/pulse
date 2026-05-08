"""FDD-OBS-001 PR 4a — Redis-backed token bucket for DD rate limiting.

Why Redis (not in-memory):
  Webmotors DD has 473 services × 6 metrics = 2,838 query_metric calls
  per rollup cycle. With 1 worker pod the bucket can be in-process; with
  multiple (R1 SaaS multi-region) they MUST share state. ADR-024 chose
  Redis. Shipping Redis-backed from day 1 avoids a silent correctness
  regression the day we scale to 2 pods (architect's call).

Algorithm:
  Classic token bucket — a counter capped at `capacity` that refills at
  `refill_rate_per_second`. `try_acquire(n)` either decrements n tokens
  and returns True (allowed) or returns False (exhausted) without
  blocking. The worker scheduler treats False as "skip remaining work
  this cycle, resume next tick".

Implementation:
  Single Redis key per (tenant, provider). Lua script for atomic
  read-modify-write (avoids the classic race where two workers both
  see capacity=10 and both decrement).

Graceful degradation:
  When Redis is unreachable, `try_acquire` returns False (fail-closed) —
  the rollup worker treats it as "rate-limited, skip this cycle". This
  is the safer default; alternative (allow when Redis down) could turn
  into a runaway DD spend if Redis flaps under load.

Calibration:
  DD's documented limits vary by plan. Standard plan = 600 req/h on the
  `/api/v1/query` endpoint per organization. Conservative default in
  this module is 500 req/h to leave 17% headroom for ad-hoc admin
  calls (validate, list_services in PR 3 sync).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from src.config import settings

logger = logging.getLogger(__name__)


# Default calibration (Datadog standard plan, conservative).
_DEFAULT_CAPACITY: int = 500
_DEFAULT_REFILL_PER_HOUR: int = 500


# Lua script — atomic check + decrement. Returns 1 (allowed) or 0
# (exhausted). The script computes refilled tokens since last touch,
# caps at capacity, then decrements requested count if affordable.
#
# KEYS[1] = bucket key (e.g. "obs:tb:<tenant>:<provider>")
# ARGV[1] = capacity (max tokens)
# ARGV[2] = refill rate (tokens per second, float)
# ARGV[3] = now (unix seconds, float)
# ARGV[4] = tokens requested (integer >= 1)
#
# Hash fields: `t` = current token count, `ts` = last update unix seconds.
_LUA_TRY_ACQUIRE = """
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local need = tonumber(ARGV[4])

local data = redis.call('HMGET', KEYS[1], 't', 'ts')
local tokens = tonumber(data[1])
local last_ts = tonumber(data[2])
if tokens == nil then
    tokens = capacity
    last_ts = now
end

local elapsed = math.max(now - last_ts, 0)
tokens = math.min(capacity, tokens + (elapsed * refill))

local allowed = 0
if tokens >= need then
    tokens = tokens - need
    allowed = 1
end

redis.call('HMSET', KEYS[1], 't', tokens, 'ts', now)
-- 2h TTL is well past any plausible refill window; keys vanish for
-- inactive tenants without manual cleanup.
redis.call('EXPIRE', KEYS[1], 7200)
return allowed
"""


@dataclass(frozen=True)
class BucketConfig:
    """Per-(tenant, provider) bucket parameters. Defaults sized for DD
    standard plan; override per-tenant via env or admin endpoint when
    a paying customer has a larger plan."""

    capacity: int = _DEFAULT_CAPACITY
    refill_per_hour: int = _DEFAULT_REFILL_PER_HOUR

    @property
    def refill_per_second(self) -> float:
        return self.refill_per_hour / 3600.0


class _RedisLike(Protocol):
    """Minimal interface exercised by the token bucket — keeps the
    service layer testable with AsyncMock without pulling fakeredis."""

    async def eval(self, script: str, numkeys: int, *args) -> int: ...
    async def ping(self) -> bool: ...


async def _get_redis() -> _RedisLike | None:
    """Lazy-import the redis async client. Mirrors the pattern from
    `shared/feature_flags.py` — short connect/socket timeouts, ping
    on construction so callers know up-front if Redis is reachable.
    Returns None if Redis is unavailable; callers fail-closed."""
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
        logger.debug("Redis unavailable for token_bucket", exc_info=True)
        return None


def _bucket_key(tenant_id: UUID, provider_id: str) -> str:
    return f"obs:tb:{tenant_id}:{provider_id}"


class TokenBucket:
    """Async token bucket for per-(tenant, provider) rate limiting.

    Construction is cheap (no I/O). The first network call happens at
    `try_acquire`. Holds no per-call state — bucket state lives in Redis.

    Usage:
        bucket = TokenBucket()
        if await bucket.try_acquire(tenant_id, "datadog", n=1):
            await provider.query_metric(...)
        else:
            log skip, move on

    Inject `redis_client` for tests; in production it's None and the
    instance lazy-resolves Redis via `_get_redis`.
    """

    def __init__(
        self,
        config: BucketConfig | None = None,
        redis_client: _RedisLike | None = None,
    ) -> None:
        self._config = config or BucketConfig()
        self._redis = redis_client

    async def _client(self) -> _RedisLike | None:
        if self._redis is not None:
            return self._redis
        return await _get_redis()

    async def try_acquire(
        self,
        tenant_id: UUID,
        provider_id: str,
        n: int = 1,
    ) -> bool:
        """Atomically attempt to consume `n` tokens. Returns True if the
        bucket had enough; False if exhausted OR Redis unreachable
        (fail-closed). NEVER raises — workers must be able to call this
        thousands of times without exception handling."""
        if n < 1:
            raise ValueError("n must be >= 1")

        client = await self._client()
        if client is None:
            logger.warning(
                "[token-bucket] Redis unavailable — fail-closed (denying) "
                "tenant=%s provider=%s n=%d",
                tenant_id, provider_id, n,
            )
            return False

        try:
            allowed = await client.eval(
                _LUA_TRY_ACQUIRE,
                1,
                _bucket_key(tenant_id, provider_id),
                str(self._config.capacity),
                str(self._config.refill_per_second),
                str(time.time()),
                str(n),
            )
        except Exception:
            logger.warning(
                "[token-bucket] Redis eval failed — fail-closed "
                "tenant=%s provider=%s",
                tenant_id, provider_id, exc_info=True,
            )
            return False

        return bool(int(allowed) == 1)
