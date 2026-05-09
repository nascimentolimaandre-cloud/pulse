"""FDD-OBS-001 PR 4b — Deploy Health Timeline service (Carlos persona).

Builds a unified timeline by intercalating:

  1. Deploy markers from `eng_deployments` (existing pipeline data,
     filtered to the squad's repos via `service_squad_ownership.repo_url`).
  2. Hourly health buckets from `obs_metric_snapshots`
     (currently MONITOR_HEALTH severity 0..3 per service, per hour).

Two granularities:

  - **Squad-level** (default): aggregates over all services owned by
    the squad. The bucket value is the WORST severity across the
    squad's services in that hour — same aggregation principle as the
    rollup_service per-service step. Deploy markers list every deploy
    that touched any of the squad's repos in the window.

  - **Service-level** (`?service=...`): no aggregation; raw per-service
    buckets + deploys for that one service's repo.

Anti-surveillance (ADR-025):
  - Deploy markers NEVER include `author` (eng_deployments column
    contains author handle/email — explicitly omitted from SELECT).
  - Service names are SAFE in the response because the timeline is
    served to authenticated tenant users; the rollup-worker logging
    redaction (ADR-028) was about cross-customer log aggregation, not
    about hiding service names from the tenant's own UI.

Read-only — never writes. Designed to be called many times per minute
when Carlos's UI is open; queries are PK-friendly (tenant + squad +
hour bucket range index).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.connectors.observability.base import PulseMetric
from src.database import get_session

logger = logging.getLogger(__name__)


# Default lookback if caller omits `since`. 7 days matches the
# product spec for Carlos's "did this deploy break anything?" workflow
# — long enough to catch slow regressions, short enough that the
# chart isn't too dense to scan.
_DEFAULT_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class HealthBucket:
    """One hourly aggregation point on the timeline."""

    hour_bucket: datetime
    severity: float            # 0..3, see MONITOR_SEVERITY_MAP
    samples_count: int         # # monitors / # services aggregated
    metric: str                # 'monitor_health' (today) — extensible
    service: str | None = None  # None on squad-aggregated rows


@dataclass(frozen=True)
class DeployMarkerDTO:
    """One deploy event for the timeline. Anti-surveillance: NEVER
    carries `author` — eng_deployments column is explicitly excluded
    from the SELECT statement upstream."""

    deployed_at: datetime
    repo: str
    environment: str | None
    sha: str | None
    is_failure: bool
    url: str | None
    service: str | None = None  # filled when narrowed to a single service


@dataclass(frozen=True)
class TimelineResponse:
    scope: str                          # 'squad' | 'service'
    squad_key: str | None
    service: str | None
    since: datetime
    until: datetime
    buckets: list[HealthBucket]
    deploys: list[DeployMarkerDTO]
    services_in_squad: int              # 0 when scope='service'
    has_data: bool                       # any buckets OR deploys present


# ---------------------------------------------------------------------------
# Helpers — repo extraction from ownership
# ---------------------------------------------------------------------------


async def _resolve_squad_repos(
    tenant_id: UUID, provider_id: str, squad_key: str,
) -> tuple[set[str], int]:
    """Return (set_of_repo_org_name, services_count) for the squad.

    Repo is parsed from `service_squad_ownership.repo_url` — same
    `org/name` shape used in `eng_deployments.repo`. Services without
    a repo URL are still counted (services_count) but contribute no
    deploys to the timeline.
    """
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT service_name, repo_url
                FROM service_squad_ownership
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND COALESCE(override_squad_key, inferred_squad_key) = :squad
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "squad": squad_key,
            },
        )
        rows = result.all()

    repos: set[str] = set()
    for row in rows:
        repo_norm = _normalize_repo(row.repo_url)
        if repo_norm:
            repos.add(repo_norm)
    return repos, len(rows)


def _normalize_repo(url: str | None) -> str | None:
    """Match the same logic as `tier2_inference.normalize_repo` so a
    deploy's `eng_deployments.repo` column lines up with the repo URL
    we extracted from DD."""
    if not url:
        return None
    from src.contexts.observability.services.tier2_inference import (
        normalize_repo as _norm,
    )
    return _norm(url)


# ---------------------------------------------------------------------------
# Squad-level timeline (Carlos default view)
# ---------------------------------------------------------------------------


async def get_squad_timeline(
    tenant_id: UUID,
    squad_key: str,
    since: datetime | None = None,
    until: datetime | None = None,
    provider_id: str = "datadog",
) -> TimelineResponse:
    """Aggregate timeline for one squad: WORST severity per hour across
    all the squad's services, plus every deploy touching the squad's
    repos in the window."""
    until = until or datetime.now(timezone.utc)
    since = since or until - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    repos, services_count = await _resolve_squad_repos(
        tenant_id, provider_id, squad_key,
    )

    # ---- buckets ----
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT
                    hour_bucket,
                    MAX(value) AS severity,
                    SUM(samples_count)::int AS samples_count,
                    metric
                FROM obs_metric_snapshots s
                JOIN service_squad_ownership o
                    ON o.tenant_id = s.tenant_id
                   AND o.provider = s.provider
                   AND o.service_name = s.service
                WHERE s.tenant_id = :tenant_id
                  AND s.provider = :provider
                  AND COALESCE(o.override_squad_key, o.inferred_squad_key) = :squad
                  AND s.hour_bucket >= :since
                  AND s.hour_bucket < :until
                GROUP BY hour_bucket, metric
                ORDER BY hour_bucket ASC
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "squad": squad_key,
                "since": since,
                "until": until,
            },
        )
        buckets = [
            HealthBucket(
                hour_bucket=row.hour_bucket,
                severity=float(row.severity),
                samples_count=int(row.samples_count or 0),
                metric=str(row.metric),
            )
            for row in result.all()
        ]

    # ---- deploys ----
    deploys: list[DeployMarkerDTO] = []
    if repos:
        async with get_session(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        deployed_at, repo, environment, sha,
                        is_failure, url
                    FROM eng_deployments
                    WHERE tenant_id = :tenant_id
                      AND lower(repo) = ANY(:repos)
                      AND deployed_at >= :since
                      AND deployed_at < :until
                    ORDER BY deployed_at ASC
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "repos": list(repos),
                    "since": since,
                    "until": until,
                },
            )
            deploys = [
                DeployMarkerDTO(
                    deployed_at=r.deployed_at,
                    repo=str(r.repo or ""),
                    environment=r.environment,
                    sha=r.sha,
                    is_failure=bool(r.is_failure),
                    url=r.url,
                )
                for r in result.all()
            ]

    logger.info(
        "[obs-timeline] squad=%s buckets=%d deploys=%d services=%d "
        "repos=%d window=[%s,%s)",
        squad_key, len(buckets), len(deploys), services_count, len(repos),
        since.isoformat(), until.isoformat(),
    )
    return TimelineResponse(
        scope="squad",
        squad_key=squad_key,
        service=None,
        since=since,
        until=until,
        buckets=buckets,
        deploys=deploys,
        services_in_squad=services_count,
        has_data=bool(buckets or deploys),
    )


# ---------------------------------------------------------------------------
# Service-level timeline (drill-down)
# ---------------------------------------------------------------------------


async def get_service_timeline(
    tenant_id: UUID,
    service: str,
    since: datetime | None = None,
    until: datetime | None = None,
    provider_id: str = "datadog",
) -> TimelineResponse:
    """Per-service timeline. No aggregation. Deploys filtered to the
    service's own repo (via service_squad_ownership lookup)."""
    until = until or datetime.now(timezone.utc)
    since = since or until - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    # Resolve repo + squad for this service (single row)
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT
                    service_name, repo_url,
                    COALESCE(override_squad_key, inferred_squad_key) AS squad_key
                FROM service_squad_ownership
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND service_name = :service
                LIMIT 1
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "service": service,
            },
        )
        row = result.first()
    repo = _normalize_repo(row.repo_url) if row else None
    squad_key = row.squad_key if row else None

    # ---- buckets (raw per-hour, no aggregation) ----
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT hour_bucket, value, samples_count, metric
                FROM obs_metric_snapshots
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND service = :service
                  AND hour_bucket >= :since
                  AND hour_bucket < :until
                ORDER BY hour_bucket ASC
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "service": service,
                "since": since,
                "until": until,
            },
        )
        buckets = [
            HealthBucket(
                hour_bucket=r.hour_bucket,
                severity=float(r.value or 0),
                samples_count=int(r.samples_count or 0),
                metric=str(r.metric),
                service=service,
            )
            for r in result.all()
        ]

    # ---- deploys for this service's repo ----
    deploys: list[DeployMarkerDTO] = []
    if repo:
        async with get_session(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT deployed_at, repo, environment, sha,
                           is_failure, url
                    FROM eng_deployments
                    WHERE tenant_id = :tenant_id
                      AND lower(repo) = :repo
                      AND deployed_at >= :since
                      AND deployed_at < :until
                    ORDER BY deployed_at ASC
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "repo": repo,
                    "since": since,
                    "until": until,
                },
            )
            deploys = [
                DeployMarkerDTO(
                    deployed_at=r.deployed_at,
                    repo=str(r.repo or ""),
                    environment=r.environment,
                    sha=r.sha,
                    is_failure=bool(r.is_failure),
                    url=r.url,
                    service=service,
                )
                for r in result.all()
            ]

    logger.info(
        "[obs-timeline] service=%s squad=%s buckets=%d deploys=%d "
        "window=[%s,%s)",
        service, squad_key, len(buckets), len(deploys),
        since.isoformat(), until.isoformat(),
    )
    return TimelineResponse(
        scope="service",
        squad_key=squad_key,
        service=service,
        since=since,
        until=until,
        buckets=buckets,
        deploys=deploys,
        services_in_squad=0,
        has_data=bool(buckets or deploys),
    )
