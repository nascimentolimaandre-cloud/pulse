"""FDD-OBS-001 PR 4a — token_bucket unit tests.

Validates:
  - `try_acquire(n)` calls Redis eval with the Lua script + correct args.
  - Returns True when Redis returns 1, False when 0.
  - Fail-closed: returns False (NOT raises) when Redis unavailable.
  - Fail-closed: returns False when eval raises.
  - n < 1 raises ValueError.
  - BucketConfig.refill_per_second math.
  - The bucket key follows the documented pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.contexts.observability.services import token_bucket
from src.contexts.observability.services.token_bucket import (
    BucketConfig,
    TokenBucket,
    _bucket_key,
)

_TENANT = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# BucketConfig
# ---------------------------------------------------------------------------


class TestBucketConfig:
    def test_defaults_match_dd_standard_plan(self):
        cfg = BucketConfig()
        # Conservative defaults — below DD's 600/hr documented limit.
        assert cfg.capacity == 500
        assert cfg.refill_per_hour == 500

    def test_refill_per_second_is_hourly_rate_over_3600(self):
        cfg = BucketConfig(refill_per_hour=3600)
        assert cfg.refill_per_second == pytest.approx(1.0)

        cfg = BucketConfig(refill_per_hour=500)
        assert cfg.refill_per_second == pytest.approx(500 / 3600.0)


# ---------------------------------------------------------------------------
# Bucket key
# ---------------------------------------------------------------------------


class TestBucketKey:
    def test_key_includes_tenant_and_provider(self):
        key = _bucket_key(_TENANT, "datadog")
        assert str(_TENANT) in key
        assert "datadog" in key
        # Namespace prefix lets us scan/clean tenant buckets in admin tools.
        assert key.startswith("obs:tb:")


# ---------------------------------------------------------------------------
# try_acquire — happy path
# ---------------------------------------------------------------------------


class TestTryAcquire:
    @pytest.mark.asyncio
    async def test_returns_true_when_redis_returns_1(self):
        redis = AsyncMock()
        redis.eval = AsyncMock(return_value=1)

        bucket = TokenBucket(redis_client=redis)
        allowed = await bucket.try_acquire(_TENANT, "datadog", n=1)

        assert allowed is True
        redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_redis_returns_0(self):
        redis = AsyncMock()
        redis.eval = AsyncMock(return_value=0)

        bucket = TokenBucket(redis_client=redis)
        allowed = await bucket.try_acquire(_TENANT, "datadog", n=1)

        assert allowed is False

    @pytest.mark.asyncio
    async def test_passes_correct_lua_args(self):
        """Lua script needs: KEYS[1]=key, ARGV[1]=capacity, ARGV[2]=refill,
        ARGV[3]=now, ARGV[4]=needed."""
        redis = AsyncMock()
        redis.eval = AsyncMock(return_value=1)
        cfg = BucketConfig(capacity=600, refill_per_hour=600)

        bucket = TokenBucket(config=cfg, redis_client=redis)
        await bucket.try_acquire(_TENANT, "datadog", n=3)

        call = redis.eval.await_args
        # eval(script, numkeys, key, capacity, refill_per_sec, now, n)
        args = call.args
        assert args[1] == 1  # numkeys
        assert args[2] == _bucket_key(_TENANT, "datadog")
        assert args[3] == "600"  # capacity
        assert float(args[4]) == pytest.approx(600 / 3600.0)  # refill_per_sec
        # args[5] = now — just check it's a parseable float
        assert float(args[5]) > 0
        assert args[6] == "3"  # needed


# ---------------------------------------------------------------------------
# try_acquire — fail-closed paths
# ---------------------------------------------------------------------------


class TestFailClosed:
    @pytest.mark.asyncio
    async def test_redis_unavailable_returns_false_not_raise(self):
        """When _get_redis returns None (connection failed), try_acquire
        must return False (fail-closed) — NOT raise. The worker
        treats False as 'skip cycle, retry next tick'."""
        with patch.object(
            token_bucket, "_get_redis", new=AsyncMock(return_value=None),
        ):
            bucket = TokenBucket()
            allowed = await bucket.try_acquire(_TENANT, "datadog")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_eval_exception_returns_false_not_raise(self):
        """If Redis is reachable but eval blows up (script error,
        timeout), still fail-closed. Worker must keep running."""
        redis = AsyncMock()
        redis.eval = AsyncMock(side_effect=RuntimeError("redis exploded"))

        bucket = TokenBucket(redis_client=redis)
        allowed = await bucket.try_acquire(_TENANT, "datadog")
        assert allowed is False


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_zero_tokens_rejected(self):
        bucket = TokenBucket(redis_client=AsyncMock())
        with pytest.raises(ValueError, match=">= 1"):
            await bucket.try_acquire(_TENANT, "datadog", n=0)

    @pytest.mark.asyncio
    async def test_negative_tokens_rejected(self):
        bucket = TokenBucket(redis_client=AsyncMock())
        with pytest.raises(ValueError, match=">= 1"):
            await bucket.try_acquire(_TENANT, "datadog", n=-1)


# ---------------------------------------------------------------------------
# Lua script — sanity check that it includes the expected operations
# ---------------------------------------------------------------------------


class TestLuaScript:
    def test_script_uses_hmget_hmset_for_atomic_state(self):
        """The Lua script must read AND write state atomically — single
        HMGET + HMSET pair inside the script keeps it transactional.
        If a future refactor splits these into separate redis calls,
        the bucket loses its race-safety guarantee."""
        from src.contexts.observability.services.token_bucket import (
            _LUA_TRY_ACQUIRE,
        )
        assert "HMGET" in _LUA_TRY_ACQUIRE
        assert "HMSET" in _LUA_TRY_ACQUIRE
        # EXPIRE keeps inactive-tenant keys from accumulating forever.
        assert "EXPIRE" in _LUA_TRY_ACQUIRE
