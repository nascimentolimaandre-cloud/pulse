# ADR-024: Observability Cache Strategy (Hybrid)

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Main session + `pulse-data-engineer`
- **Related:** ADR-021 (credentials), ADR-023 (provider abstraction), FDD-OBS-001

---

## Context

Datadog has a **hard rate limit of 300 requests/hour per organization
API key**. New Relic NRQL is much higher (3000 req/min). Grafana
varies. The binding constraint for R2 is **DD's 300/hr**.

Three concrete use cases drive the cache design:

| Use case | Naive call volume | Frequency |
|----------|------------------|-----------|
| **Deploy Health Timeline** (Carlos's view: 4 weeks × ~50 deploys/squad × per-service queries) | ~200 queries per page load | Tens of page loads/day |
| **Service Ownership Map** (Ana's view: 1 service inventory query) | 1 query per refresh | Few per day |
| **MTTR Phase 2 backfill** (admin: N incidents × 2 queries for spike start/end) | 1000s per run | Ad-hoc, ops-driven |

A naive "always live" approach exhausts DD's budget on a single Carlos
visit. A naive "always cache" approach makes Ana's ownership refresh
hours stale.

## Decision

**Adopt a hybrid 3-layer cache**:

1. **Rollups** (worker pre-aggregates, stores in `obs_metric_snapshots`).
2. **Per-request Redis cache** (TTL 5min for metrics, 1h for inventory).
3. **Token-bucket rate-limit** + circuit breaker per `(tenant, provider)`.

Plus explicit policy: **MTTR backfill never goes through live API** —
reads exclusively from rollups.

### Layer 1 — Rollup worker (`obs_metric_snapshots`)

A new worker `obs_rollup_worker` runs every **15 minutes per tenant**:

```
For each tenant with active observability connector:
  For each provider connected:
    For each service in service_squad_ownership where last_deploy_at >= now() - 30d:
      Batch-query metrics (error_rate, p95_latency, alert_count, throughput) for last 15min
      → upsert (tenant, provider, service, metric, hour_bucket, value, last_calc)
```

**Schema (migration `018_obs_metric_snapshots`):**

```sql
CREATE TABLE obs_metric_snapshots (
    tenant_id      UUID NOT NULL,
    provider       TEXT NOT NULL,
    service        TEXT NOT NULL,
    metric         TEXT NOT NULL,           -- PulseMetric value
    hour_bucket    TIMESTAMPTZ NOT NULL,    -- truncated to hour
    value          DOUBLE PRECISION,
    samples_count  INTEGER NOT NULL,        -- # data points underlying value
    calculated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, provider, service, metric, hour_bucket)
);
-- RLS standard
-- Index for the Carlos timeline query: (tenant_id, service, metric, hour_bucket DESC)
```

**Rate budget for rollups:**

- 50 active services/tenant × 4 metrics × 4 polls/hr = 800 req/hr (over budget!)
- **Mitigation:** DD's `MultiQuery` endpoint returns N series in 1 call.
  Real budget: ~50 req/hr per tenant. Well under 300/hr ceiling.
- NR is unconstrained; same logic with `NRQL` `FACET` clause.

**What rollups serve:**
- Deploy Health Timeline (always — Carlos sees ZERO live API calls).
- Squad Reliability Posture (composite over 30d window — same source).
- MTTR Phase 2 backfill (admin endpoint — read-only against rollups).

### Layer 2 — Per-request Redis cache

For requests **not** covered by rollups (mostly Ana's inventory + drill-downs):

| Cache key | TTL | Notes |
|-----------|-----|-------|
| `obs:{tenant}:{provider}:services` | **1 hour** | Service inventory; refreshes on `service.ownership.refreshed` event |
| `obs:{tenant}:{provider}:metric:{service}:{metric}:{window_hash}` | **5 minutes** | Ad-hoc drill-down |
| `obs:{tenant}:{provider}:health` | **30 seconds** | Validation pings |
| Validation calls `/validate` | **NO CACHE** | security — always live |

### Layer 3 — Token-bucket + circuit breaker

Per `(tenant, provider)` bucket in Redis:

```
key: obs:{tenant}:{provider}:bucket
capacity: 250 tokens (50 req/hr headroom under DD's 300/hr)
refill: 250 / 3600s = ~0.07 tokens/sec
```

**On 429 / token exhausted:**

1. Exponential backoff: 2s, 4s, 8s (jittered ±50%), max 60s.
2. After 3 retries: return cached value with `stale=true` flag.
3. UI surface: toast "Dados de observabilidade defasados há Xmin —
   limite de API atingido. Próxima atualização: HH:MM."
4. **Never** queue user-facing requests for >10s. The queue exists only
   for the rollup worker (which can wait).

### Invalidation triggers

| Event | Action |
|-------|--------|
| Deploy event arrives on Kafka (`domain.deploy.normalized`) | Invalidate `obs:{tenant}:{provider}:metric:{service}:*` 5-min cache |
| Credentials rotated (ADR-021 emits `obs.credentials.rotated`) | Flush all `obs:{tenant}:*` keys + retry token bucket |
| Service inventory refreshed (`service.ownership.refreshed`) | Invalidate `obs:{tenant}:{provider}:services` |
| Tenant disconnects provider | Flush all `obs:{tenant}:{provider}:*` |

### Rollup gap policy

If the rollup worker has a gap (>15min since last calc) for a service
the request needs:

- Carlos's timeline: render from existing rollups, mark gap with grey
  band ("Sem dados — rollup stale há Xmin").
- MTTR backfill: incident is tagged `mttr_status='insufficient_obs_data'`
  rather than firing 1000s of live queries.
- Ad-hoc drill-down: falls back to Layer 2 (live with rate budget).

## Consequences

### Positive
- Carlos's Deploy Health Timeline page = 1 SQL query (rollup read), zero
  DD API calls. Sub-second on a 4-week timeline.
- 250 req/hr token cap per tenant leaves headroom for ad-hoc drill-downs.
- Rate-limit exhaustion degrades gracefully (cached + stale flag, not
  500 errors).
- Token bucket per `(tenant, provider)` is fair: one tenant going
  rogue doesn't starve others.

### Negative
- Rollups are **15min stale** at worst. Deploy Health Timeline shows
  "as of HH:MM" timestamp prominently. Carlos must understand this.
- A new `obs_rollup_worker` process (deploy + monitor). Fits the
  existing worker pattern (sync-worker, metrics-worker).
- `obs_metric_snapshots` grows ~50 services × 4 metrics × 24 buckets/day
  = 4,800 rows/day/tenant. 100 tenants × 365 days = 175M rows/yr.
  Mitigation: monthly rollup compaction (R3 follow-up) or partitioning
  by `hour_bucket`.

### Cost guardrails

- **Tenant cost transparency**: `/settings/integrations/observability`
  shows "API calls today: X / 300 (Y%)" so admin sees their consumption.
- **Default conservative**: 5min granularity, 7-day query window for
  ad-hoc drill-down. Power users can request longer via UI knob (with
  warning).
- **Cost surprise prevention**: rollup worker has hard cap of N requests
  per cycle; if budget exhausted, skip that cycle (next 15min retry).

## Open questions (filed)

- **FDD-OBS-001-FU-5**: should we expose tenant-tunable rollup interval
  (5min/15min/1h) for power users? Defer.
- **FDD-OBS-001-FU-6**: should circular `(tenant, provider)` buckets
  share a global cap to prevent platform-wide DDoS? Currently no global
  cap. Defer.
