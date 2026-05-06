# ADR-023: ObservabilityProvider — Multi-vendor Abstraction

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Main session + `pulse-data-engineer` + `pulse-product-director`
- **Related:** ADR-021 (credentials), ADR-024 (cache), FDD-OBS-001

---

## Context

PULSE Signals targets multiple observability providers across releases:

| Release | Providers |
|---------|-----------|
| **R2** | Datadog (only) |
| **R3** | + New Relic |
| **R4** | + Grafana / Honeycomb / Dynatrace |

Each provider has a different query model:

- **Datadog**: `Events API` (deploy markers) + `Metrics Query API`
  (timeseries) + `Service Catalog API` (entities).
- **New Relic**: `NRQL` (one query language for everything) + `Entity API`.
- **Grafana**: Prometheus query (PromQL) + datasource API.

Two abstraction options:

| Option | Pros | Cons |
|--------|------|------|
| **A — Pass-through with vendor flag** (return raw vendor JSON, business code branches) | Trivial to implement R2 (DD only) | Leaks DSL into PULSE business logic; every new provider becomes a rewrite of every consumer; tempts shipping one vendor and calling it done |
| **B — Coarse interface + PULSE-normalized schema** (3 methods, normalized dicts, vendor specifics inside adapters) | Provider-agnostic business logic; adding a vendor = 1 new file; testable with mocked provider; consistent with our connector pattern (`jira_connector` / `github_connector`) | Up-front cost of designing the normalized schema; extra "escape hatch" for genuine vendor specifics |

## Decision

**Adopt Option B.** Three coarse methods returning PULSE-normalized
dicts. Vendor-specific tagging logic lives **entirely inside each
adapter**. No business logic reads `vendor_raw` JSON.

### Interface

```python
# packages/pulse-data/src/connectors/observability/base.py

from typing import Protocol
from datetime import datetime
from dataclasses import dataclass

class PulseMetric(StrEnum):
    """Normalized metrics PULSE understands. NOT raw vendor query strings."""
    ERROR_RATE       = "error_rate"        # 0..1 ratio
    P95_LATENCY_MS   = "p95_latency_ms"
    P99_LATENCY_MS   = "p99_latency_ms"
    APDEX            = "apdex"             # 0..1
    THROUGHPUT_RPS   = "throughput_rps"
    ALERT_COUNT      = "alert_count"       # active alerts in window

@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end:   datetime
    granularity_seconds: int = 60          # bucket size

@dataclass(frozen=True)
class DeployMarker:
    """Normalized deploy event. All vendors emit this shape."""
    external_id:   str                      # provider's event id
    service:       str                      # PULSE service_name
    deployed_at:   datetime
    version:       str | None
    git_sha:       str | None
    triggered_by:  str | None               # NEVER user-identifiable; empty if vendor returns user
    vendor_raw:    dict                     # escape hatch — DO NOT read from business code

@dataclass(frozen=True)
class MetricSeries:
    metric:  PulseMetric
    service: str
    points:  list[tuple[datetime, float]]   # (timestamp, value) sorted ASC
    has_data: bool                          # False when service has no signal yet
    stale:   bool = False                   # set True by cache layer

@dataclass(frozen=True)
class ServiceEntity:
    service_name:   str                     # PULSE display + join key
    external_id:    str                     # provider-specific id (DD: name, NR: GUID)
    owner_squad:    str | None              # extracted from vendor tags by adapter
    repo_url:       str | None
    runtime:        str | None              # python, java, node, ...
    tier:           str | None              # tier-0, tier-1, tier-2 if tenant configures
    vendor_raw:     dict


class ObservabilityProvider(Protocol):
    provider_id: str                         # 'datadog' | 'newrelic' | ...

    async def list_deployments(
        self, since: datetime, until: datetime, service: str | None = None,
    ) -> list[DeployMarker]: ...

    async def query_metric(
        self, metric: PulseMetric, service: str, window: TimeWindow,
    ) -> MetricSeries: ...

    async def list_services(self) -> list[ServiceEntity]: ...

    async def health_check(self) -> bool:
        """True when credentials valid + provider reachable. Used by /validate."""
        ...
```

### Adapter responsibilities

Each `connectors/observability/<provider>_connector.py` implements:

1. **Auth**: reads encrypted credentials (ADR-021), constructs HTTP client.
2. **Query translation**: maps `PulseMetric.ERROR_RATE` to provider DSL:
   - DD: `sum:trace.servlet.request.errors{service:X}.as_rate()`
   - NR: `SELECT percentage(count(*), WHERE error IS true) FROM Transaction WHERE appName='X'`
   - Grafana: `rate(http_requests_total{status=~"5..",service="X"}[5m])`
3. **Tag normalization**: `_normalize_ownership(raw_tags) -> str | None`
   maps vendor tag taxonomy to PULSE squad keys.
4. **Pagination + rate-limit**: per-vendor concerns hidden.
5. **Schema mapping**: vendor JSON → `DeployMarker` / `MetricSeries` /
   `ServiceEntity`.

### Factory

```python
# connectors/observability/__init__.py
def get_provider(tenant_id: UUID, provider_id: str) -> ObservabilityProvider:
    """Returns a configured adapter for (tenant, provider). Reads
    credentials via ADR-021. Caches HTTP client per process."""
    ...
```

### Anti-pattern explicitly rejected

```python
# ❌ Do NOT do this in business code:
if marker.vendor_raw["custom_field_42"] == "production":
    ...
```

If business code needs `vendor_raw`, that's a signal to **add a
normalized field** to `DeployMarker` / `ServiceEntity`. The escape
hatch exists for the 5% of edge cases (debugging, vendor-specific UI
deep-links), not as a substitute for normalization work.

### What does NOT go through the abstraction

The abstraction is **read-only and signal-focused**. Out of scope:

- Alerting / monitoring config (we don't write to provider).
- Distributed tracing details (raw spans — Tier-3 in data scientist's
  taxonomy).
- RUM / session replay (anti-surveillance + no engineering value).
- Log search.

These are explicitly **deep-link only** in the UI ("Open in Datadog").

## Consequences

### Positive
- New vendor = 1 new file, ~400-600 LoC, no business logic changes.
- Test with `MockObservabilityProvider` (no HTTP, no Datadog account).
- Normalized contracts make the metric formulas (DCS, RDI, BRI from
  data-scientist's spec) provider-agnostic.
- `vendor_raw` escape hatch is auditable: grep `vendor_raw` in business
  code → CI fails (lint rule).

### Negative
- Up-front cost of designing the normalized schema for the 3 R2-R3
  providers without R3 evidence. Mitigated by data-engineer's review
  of NR query model before R2 close.
- Adding a 4th vendor (R4) may surface a normalized field we missed.
  Acceptable: ADR addendum + schema migration.

## Open questions (filed)

- **FDD-OBS-001-FU-3**: should `MetricSeries.points` be a domain
  dataclass (`MetricPoint(at, value, anomaly_score)`) instead of tuple?
  Defer until R3 anomaly detection clarifies the third coordinate.
- **FDD-OBS-001-FU-4**: how to handle providers that emit a single
  rolled-up value (e.g. `apdex` daily) vs high-cardinality timeseries?
  Defer to first NR integration.
