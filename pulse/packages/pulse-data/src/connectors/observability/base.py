"""FDD-OBS-001 PR 1 — ObservabilityProvider Protocol + normalized dataclasses.

ADR-023 (multi-vendor abstraction). Three coarse methods returning
PULSE-normalized dicts. Vendor-specific tagging logic lives entirely
inside each adapter — business code never reads `vendor_raw`.

Adding a new provider (NR R3, Grafana R4) is one new file
implementing this Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class PulseMetric(StrEnum):
    """Normalized metrics PULSE understands. NOT raw vendor query strings.

    Each adapter translates these to its DSL:
      DD: ERROR_RATE → `sum:trace.servlet.request.errors{...}.as_rate()`
      NR: ERROR_RATE → `SELECT percentage(count(*), WHERE error IS true) FROM Transaction`
      Grafana: ERROR_RATE → `rate(http_requests_total{status=~"5.."}[5m])`
    """

    ERROR_RATE = "error_rate"           # 0..1 ratio
    P95_LATENCY_MS = "p95_latency_ms"
    P99_LATENCY_MS = "p99_latency_ms"
    APDEX = "apdex"                     # 0..1
    THROUGHPUT_RPS = "throughput_rps"
    ALERT_COUNT = "alert_count"         # active alerts in window


@dataclass(frozen=True)
class TimeWindow:
    """Inclusive time range for metric queries."""

    start: datetime
    end: datetime
    granularity_seconds: int = 60       # 1-minute buckets default


@dataclass(frozen=True)
class DeployMarker:
    """Normalized deploy event. All vendors emit this shape.

    `triggered_by` is intentionally NEVER user-identifiable — adapters
    set it to NULL even when the vendor returns an author email.
    Anti-surveillance principle (ADR-025) is non-negotiable.

    `vendor_raw` is the escape hatch for the 5% of edge cases. Business
    code MUST NOT read from it; CI lint enforces this (ADR-025 L4).
    """

    external_id: str                    # provider's event id
    service: str                        # PULSE-canonical service name
    deployed_at: datetime
    version: str | None = None
    git_sha: str | None = None
    triggered_by: str | None = None     # always None per anti-surveillance
    vendor_raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MetricSeries:
    """Time-series result of `query_metric`. `points` ordered ASC by ts."""

    metric: PulseMetric
    service: str
    points: list[tuple[datetime, float]]
    has_data: bool                      # False when service has no signal yet
    stale: bool = False                 # True when cache layer returns expired data


@dataclass(frozen=True)
class ServiceEntity:
    """Normalized service from the provider catalog.

    `owner_squad` is extracted from vendor tags by the adapter
    (`_normalize_ownership(raw_tags)`). When the tag is missing or
    doesn't match a qualified squad, the value is None and Tier-2
    inference takes over (ADR-022).
    """

    service_name: str                   # PULSE display + join key
    external_id: str                    # provider-specific id
    owner_squad: str | None = None
    repo_url: str | None = None
    runtime: str | None = None          # python | java | node | ...
    tier: str | None = None             # tier-0 | tier-1 | tier-2
    vendor_raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Capability detection (ADR-026 — graceful degradation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservabilityCapabilities:
    """Output of capability detection — what the tenant's observability
    setup can actually deliver right now.

    Routes inspect this BEFORE rendering Signals views. Each metric /
    view declares minimum capabilities; unmet → honest empty state
    (never a half-broken chart).
    """

    has_provider: bool                          # ≥1 provider connected
    has_validated_creds: bool                   # last validation succeeded
    services_mapped_pct: float                  # % services with effective_squad
    has_deploy_markers: bool                    # ≥1 deploy in last 30d
    has_metric_signal: bool                     # ≥1 service with metric data
    last_rollup_at: datetime | None             # freshness of obs_metric_snapshots
    rate_limit_remaining: int | None            # token-bucket headroom

    @classmethod
    def empty(cls) -> "ObservabilityCapabilities":
        """Default state: no provider connected. Used by the
        capability-detection service when there's no row in
        `tenant_observability_credentials` for this tenant."""
        return cls(
            has_provider=False,
            has_validated_creds=False,
            services_mapped_pct=0.0,
            has_deploy_markers=False,
            has_metric_signal=False,
            last_rollup_at=None,
            rate_limit_remaining=None,
        )


# ---------------------------------------------------------------------------
# The Protocol — every provider adapter must implement these 3 methods
# ---------------------------------------------------------------------------


@runtime_checkable
class ObservabilityProvider(Protocol):
    """ADR-023 multi-vendor abstraction. Three methods + identity.

    Adapter responsibilities (delegated entirely):
      - Auth: read encrypted credentials (ADR-021), construct HTTP client.
      - Query translation: PulseMetric → vendor DSL.
      - Tag normalization: vendor tag taxonomy → PULSE squad keys.
      - Pagination + rate-limit: per-vendor concerns hidden.
      - PII strip: every record passes through `strip_pii()` before return
        (ADR-025 L1).
    """

    provider_id: str

    async def list_deployments(
        self,
        since: datetime,
        until: datetime,
        service: str | None = None,
    ) -> list[DeployMarker]:
        """List deploys in the window, optionally scoped to a service."""
        ...

    async def query_metric(
        self,
        metric: PulseMetric,
        service: str,
        window: TimeWindow,
    ) -> MetricSeries:
        """Time-series query for a single metric on a single service."""
        ...

    async def list_services(self) -> list[ServiceEntity]:
        """Service catalog with vendor tags normalized to PULSE format."""
        ...

    async def health_check(self) -> bool:
        """True when credentials valid + provider reachable. Used by
        the `/v1/admin/integrations/<provider>/validate` endpoint
        (PR 2)."""
        ...
