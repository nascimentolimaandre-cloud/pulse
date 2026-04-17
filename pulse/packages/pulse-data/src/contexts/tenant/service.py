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
CACHE_KEY_SQUAD_PREFIX = "tenant:capabilities:squad:"
CACHE_TTL_SECONDS = 300  # 5 minutes

# Regex gate for squad_key — protect against SQL patterns slipping into ILIKE.
# Jira project keys are UPPERCASE letters + digits, e.g. FID, PTURB, SECOM, BG.
import re  # noqa: E402

_SQUAD_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,31}$")


def _normalize_squad_key(raw: str) -> str | None:
    """Upper-case and validate a caller-supplied squad key. Returns None when
    the input doesn't match the expected Jira project-key shape — callers treat
    that as a missing squad (fail-open to tenant-wide response)."""
    if not raw:
        return None
    candidate = raw.strip().upper()
    return candidate if _SQUAD_KEY_RE.match(candidate) else None


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


def _cache_key(tenant_id: UUID, squad_key: str | None) -> str:
    if squad_key:
        return f"{CACHE_KEY_SQUAD_PREFIX}{tenant_id}:{squad_key}"
    return f"{CACHE_KEY_PREFIX}{tenant_id}"


async def _read_cache(tenant_id: UUID, squad_key: str | None = None) -> TenantCapabilities | None:
    redis = await _get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(_cache_key(tenant_id, squad_key))
        if raw is None:
            return None
        return TenantCapabilities.model_validate(json.loads(raw))
    except Exception:
        logger.warning("Failed to read tenant capability cache", exc_info=True)
        return None


async def _write_cache(
    tenant_id: UUID, caps: TenantCapabilities, squad_key: str | None = None
) -> None:
    redis = await _get_redis()
    if redis is None:
        return
    try:
        payload = caps.model_dump_json(by_alias=False)
        await redis.setex(_cache_key(tenant_id, squad_key), CACHE_TTL_SECONDS, payload)
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
            WHERE started_at >= NOW() - INTERVAL '{SPRINT_LOOKBACK_DAYS} days'
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
    """Count issues created in the last 30 days (informational signal)."""
    row = await session.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM eng_issues
            WHERE created_at >= NOW() - INTERVAL '30 days'
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


async def _query_squad_sprints(
    session: AsyncSession, squad_key: str
) -> tuple[int, list[str], list[str]]:
    """Primary heuristic: join eng_issues (issue_key prefix) to eng_sprints via
    external_id. Returns (sprint_count, boards, sample_sprint_names).

    The issue_key prefix is the Jira project key (e.g. 'FID-1234' -> 'FID').
    We count distinct sprints in the last SPRINT_LOOKBACK_DAYS window.

    IMPORTANT: the `sprint_id` column on eng_issues is a string (external id
    like 'jira:JiraSprint:1:2864'), matching eng_sprints.external_id — not the
    UUID primary key (a historical schema drift from migration 001).
    """
    row = await session.execute(
        text(
            f"""
            SELECT COUNT(DISTINCT s.id) AS sprint_count,
                   ARRAY_REMOVE(ARRAY_AGG(DISTINCT s.board_id), NULL) AS boards
            FROM eng_issues i
            JOIN eng_sprints s ON s.external_id = i.sprint_id
            WHERE i.issue_key IS NOT NULL
              AND SPLIT_PART(i.issue_key, '-', 1) = :squad_key
              AND s.started_at >= NOW() - INTERVAL '{SPRINT_LOOKBACK_DAYS} days'
            """
        ),
        {"squad_key": squad_key},
    )
    record = row.first()
    sprint_count = int(record[0] or 0) if record else 0
    boards_raw = list(record[1]) if record and record[1] else []
    boards = [str(b) for b in boards_raw]

    sample_sprints: list[str] = []
    if sprint_count > 0:
        sample = await session.execute(
            text(
                f"""
                SELECT DISTINCT s.name, s.started_at
                FROM eng_issues i
                JOIN eng_sprints s ON s.external_id = i.sprint_id
                WHERE i.issue_key IS NOT NULL
                  AND SPLIT_PART(i.issue_key, '-', 1) = :squad_key
                  AND s.started_at >= NOW() - INTERVAL '{SPRINT_LOOKBACK_DAYS} days'
                ORDER BY s.started_at DESC
                LIMIT 3
                """
            ),
            {"squad_key": squad_key},
        )
        sample_sprints = [str(r[0]) for r in sample.fetchall() if r[0]]

    return sprint_count, boards, sample_sprints


async def _query_squad_sprints_fallback(
    session: AsyncSession, squad_key: str
) -> tuple[int, list[str], list[str]]:
    """Fallback heuristic used only when the primary returned zero sprints:
    match squad_key against sprint name (case-insensitive). Frail — sprints
    named 'Sprint 147 (+fidelidade)' should map to FID, 'Motor VN - Sprint N'
    to PTURB. We only trust this when it also clears SPRINT_THRESHOLD.
    """
    # Hand-tuned aliases for well-known cases; extend as squads self-identify.
    aliases = {"FID": ["fidelidade"], "PTURB": ["motor vn", "pturb"]}
    tokens = [squad_key.lower(), *aliases.get(squad_key, [])]

    ilike_clause = " OR ".join(
        f"LOWER(s.name) ILIKE :tok{i}" for i in range(len(tokens))
    )
    params = {f"tok{i}": f"%{tok}%" for i, tok in enumerate(tokens)}

    row = await session.execute(
        text(
            f"""
            SELECT COUNT(DISTINCT s.id) AS sprint_count,
                   ARRAY_REMOVE(ARRAY_AGG(DISTINCT s.board_id), NULL) AS boards
            FROM eng_sprints s
            WHERE ({ilike_clause})
              AND s.started_at >= NOW() - INTERVAL '{SPRINT_LOOKBACK_DAYS} days'
            """
        ),
        params,
    )
    record = row.first()
    sprint_count = int(record[0] or 0) if record else 0
    boards_raw = list(record[1]) if record and record[1] else []
    boards = [str(b) for b in boards_raw]
    return sprint_count, boards, []


async def compute_squad_capabilities(
    tenant_id: UUID, squad_key: str
) -> TenantCapabilities:
    """Compute capabilities for a single squad.

    Strategy:
      1) Primary: join issue_key prefix -> sprint (via eng_issues.sprint_id =
         eng_sprints.external_id). This is deterministic and wins for Webmotors.
      2) Fallback: match squad_key / known alias against sprint NAME. Used only
         if primary returned 0 — and even then the result is still gated by
         SPRINT_THRESHOLD.
      3) Fail-open safety: any unexpected error -> has_sprints=False, boards=[].

    has_kanban is reused from the tenant-wide flag (kanban is tenant-level;
    Webmotors' whole flow is kanban regardless of which squad is selected).
    """
    sprint_count = 0
    boards: list[str] = []
    sample_sprints: list[str] = []

    try:
        async with get_session(tenant_id) as session:
            sprint_count, boards, sample_sprints = await _query_squad_sprints(
                session, squad_key
            )
            if sprint_count == 0:
                # Try fallback only when primary returned nothing
                fb_count, fb_boards, _ = await _query_squad_sprints_fallback(
                    session, squad_key
                )
                if fb_count >= SPRINT_THRESHOLD:
                    sprint_count, boards = fb_count, fb_boards
    except Exception:
        logger.warning(
            "Error computing squad capabilities for %s — returning safe defaults",
            squad_key,
            exc_info=True,
        )

    # Reuse tenant-wide kanban + issue_count signal (squad-scoped kanban is
    # out of scope for this iteration; dashboards use tenant-wide has_kanban).
    tenant_caps = await compute_capabilities(tenant_id)

    return TenantCapabilities(
        tenant_id=tenant_id,
        squad_key=squad_key,
        has_sprints=evaluate_has_sprints(sprint_count),
        has_kanban=tenant_caps.has_kanban,
        sprint_count=sprint_count,
        issue_count_30d=tenant_caps.issue_count_30d,
        boards=boards,
        sample_sprints=sample_sprints,
        last_evaluated_at=datetime.now(timezone.utc),
        sources=_source_connection_flags(),
    )


async def get_capabilities(
    tenant_id: UUID,
    *,
    squad_key: str | None = None,
    use_cache: bool = True,
) -> TenantCapabilities:
    """Return cached capabilities or compute + cache if missing/expired.

    When `squad_key` is provided and valid, returns squad-scoped capabilities
    (cached under `tenant:capabilities:squad:<tid>:<key>`). Invalid squad_key
    input (doesn't match project-key shape) is silently dropped — the caller
    falls back to tenant-wide capabilities. This keeps the endpoint resilient
    to malformed query params without exposing 400s to the UI.
    """
    normalized = _normalize_squad_key(squad_key) if squad_key else None

    if use_cache:
        cached = await _read_cache(tenant_id, normalized)
        if cached is not None:
            return cached

    if normalized is not None:
        fresh = await compute_squad_capabilities(tenant_id, normalized)
    else:
        fresh = await compute_capabilities(tenant_id)

    if use_cache:
        await _write_cache(tenant_id, fresh, normalized)
    return fresh
