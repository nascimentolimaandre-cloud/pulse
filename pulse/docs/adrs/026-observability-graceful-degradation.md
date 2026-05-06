# ADR-026: Graceful Degradation When Observability Is Unavailable

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Main session + `pulse-data-scientist` + `pulse-product-director`
- **Related:** ADR-021, ADR-023, ADR-024, FDD-OBS-001
- **User-driven requirement** (2026-05-06): "lembra de deixar as
  métricas em pé caso não tenhamos a conexão com datadog (alguns
  tenants podem não ter datadog)"

---

## Context

PULSE Signals introduces observability-enhanced metrics
(MTTR Phase 2, CFR Enhanced, Deploy Confidence Score, etc.) and
observability-only views (Deploy Health Timeline, Service Ownership
Map, Squad Reliability Posture).

**Reality check for our ICP**: only ~50-60% of mid-market tenants will
have Datadog or New Relic configured at the depth required for our
enhanced metrics to produce meaningful signal:

- Some tenants run Grafana/OSS Prometheus only (R4 for us).
- Some tenants run Honeycomb only (R4).
- Some tenants run NO observability (small teams, early-stage).
- Some tenants are mid-migration (DD installed but services not tagged).
- Some tenants have DD but only on subset of services (legacy + greenfield).

If PULSE Signals features hard-depend on an active connector, we either:

- Lock out 40-50% of tenants from a flagship feature (bad for retention).
- Show errors / blank screens (worse — looks broken).
- Show inflated/wrong numbers (worst — silently lies).

## Decision

Adopt **5 explicit degradation principles** that every Signals
feature must implement. Failing to implement any of them is a release
blocker (CISO + product gate).

### Principle 1 — Capability detection, not configuration assumption

Before any Signals feature renders, the backend asks:

```python
@dataclass(frozen=True)
class ObservabilityCapabilities:
    has_provider:           bool   # at least 1 provider connected
    has_validated_creds:    bool   # last validation succeeded
    services_mapped_pct:    float  # % services with effective_squad set
    has_deploy_markers:     bool   # ≥1 deployment marker in last 30d
    has_metric_signal:      bool   # ≥1 service with metric data in last 7d
    last_rollup_at:         datetime | None
    rate_limit_remaining:   int | None  # token bucket headroom
```

Each metric / view declares its **minimum capabilities** to render
meaningfully. If unmet, the frontend renders an explicit fallback
state — never a half-broken chart.

### Principle 2 — Always-available fallback for enhanced metrics

For every metric that gains depth from observability, the
**non-observability fallback must remain shipped, working, and
mathematically sound**. The enhancement is purely additive.

| Metric | No-obs fallback (always works) | With-obs enhancement |
|--------|-------------------------------|----------------------|
| **MTTR** | Phase 1: failure→next-success deploy pairing (FDD-DSH-050, already shipped) | Phase 2: error_rate-baseline-restored anchoring |
| **CFR** | Heuristic: `is_failure` ratio (current) | Confirm via alert/error_rate spike |
| **DF** | Deploy event count (current) | Confirm with `deployment_marker` from provider |
| **Cycle Time** | 4-stage breakdown (current) | + 5th "Deploy Validation" stage (`deployed_at → error_rate_stable_at`) |
| **Throughput** | PR count (current) | Weighted by stable-deploy %; raw still shown |

The API responds with a `method` flag so the UI knows which is in use:

```json
{
  "value": 0.50,
  "method": "deploy_proxy",      // or "observability_enhanced"
  "level": "elite",
  ...
}
```

The **frontend renders both methods identically** in the happy path.
The flag drives a small "ⓘ" tooltip explaining the method, never a
visual difference. Carlos sees Elite MTTR whether or not DD is
connected — what changes is precision, not availability.

### Principle 3 — Observability-only features are NEVER on the home dashboard

Features that **require** observability (Deploy Health Timeline,
Service Ownership Map, Squad Reliability Posture, Deploy Confidence
Score in pre-merge mode) live exclusively on dedicated pages:

- `/observability/timeline`
- `/observability/ownership`
- `/observability/posture`

The home dashboard, the deep-dive `/dora`, `/lean`, `/cycle-time`,
`/throughput` pages, and the Sprint section work **identically**
without any provider connected. Adding observability deepens specific
cards; it never gates the page.

This rule is a **product non-negotiable**: PULSE-without-observability
must remain a complete product.

### Principle 4 — Honest empty states (not zeros, not fake data)

When a Signals feature is rendered but capabilities are insufficient:

| Trigger | UI state |
|---------|----------|
| No provider connected | "Conecte Datadog ou New Relic para ver Deploy Health Timeline" + 1-click flow to `/settings/integrations/observability` |
| Provider connected, validation failed | "Credenciais Datadog inválidas — atualize em Settings" + link |
| Provider OK, services 0% mapped | "Nenhum service do squad OKM mapeado. Use o Service Ownership Map para mapear." |
| Provider OK, mapped, but <30 days of data | "Coletando dados (Xd / 30d). Disponível a partir de DD/MM" |
| Rate limit exhausted | "Dados defasados há Xmin — limite de API atingido. Próxima atualização: HH:MM" |

The data API NEVER returns `0` for "data unavailable". It returns
`null` + `reason` field. The frontend interprets reason → empty state.

Same principle as MTTR Phase 1's `n<5` guard (returns `None`, not 0).

### Principle 5 — Provider-mix transparency at admin level

The `/settings/integrations/observability` page shows the tenant
admin **exactly which features are degraded** because of their
configuration:

```
✓ MTTR Phase 2          (Datadog connected, 87% services mapped)
⚠ Squad Reliability      (Datadog connected, but 31% services mapped — 
                          map more services for accurate posture)
⚠ Deploy Confidence       (Datadog connected, error_rate has 8d history; 
                          full accuracy at 14d)
✗ Cross-stack reliability (would require both Datadog + New Relic;
                           tenant has only Datadog)
```

This honest accounting prevents support tickets ("why is X showing 0?")
and turns the degradation story into an onboarding nudge.

### Implementation contract

Every observability-aware service MUST:

1. Accept an `ObservabilityCapabilities` parameter (or read it from
   the request context).
2. Return a typed result with `method: 'deploy_proxy' | 'observability_enhanced'`.
3. Pass `null` + `reason` when capabilities are insufficient — never
   throw, never return `0` as a substitute.

Every observability-aware route MUST:

1. Probe capabilities first (cheap — Redis cache 30s).
2. If unsupported → return 200 with empty-state payload (`reason` set).
3. Never return 5xx for "tenant doesn't have provider".

Every observability-aware UI page MUST:

1. Render the empty state from `reason` field (no client-side
   "unavailable, please configure X" inferred from missing data).
2. Provide actionable guidance (link to settings, link to docs).
3. Pass axe-core accessibility audit on empty states.

## Consequences

### Positive
- 100% of tenants can use PULSE day one. Observability is a
  progressive enhancement, not a gate.
- Honest fallback messaging is itself a marketing surface (admin sees
  "you'd unlock X by configuring Y").
- Aligns with our existing INC-006 / FDD-DSH-050 philosophy: when data
  is insufficient, return null + reason, never lie.

### Negative
- Every Signals feature has 2 code paths (with-obs / without-obs) plus
  N empty states. Test surface 3-4x what a "always-on" implementation
  would be.
- Mitigated by:
  - Reusing existing fallbacks (MTTR Phase 1 stays alive forever).
  - Capability detection is a single shared service, not per-feature.
  - Empty-state UI components are a single shared library
    (`<ObsRequiredEmptyState />`).

## Test gates (acceptance for each Signals feature)

A Signals feature is shippable only when:

- [ ] Renders correctly with provider DISCONNECTED (fallback / empty state).
- [ ] Renders correctly with provider CONNECTED but 0 services mapped.
- [ ] Renders correctly with provider CONNECTED + partial mapping.
- [ ] Renders correctly with provider CONNECTED + rate-limit exhausted
      (cached + stale flag visible).
- [ ] Returns 200 + `reason` payload (never 5xx) for any capability gap.
- [ ] Has copywritten empty-state guidance (PT-BR) reviewed by
      `pulse-product-director`.

These tests are gated in CI as integration tests with mocked
`ObservabilityCapabilities`.
