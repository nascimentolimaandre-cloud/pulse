# ADR-027: Observability Bounded Context Placement

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Main session + `pulse-engineer`
- **Related:** ADR-001 (modular monolith), ADR-021..026 (FDD-OBS-001), FDD-OBS-001

---

## Context

FDD-OBS-001 introduces a substantial new feature surface (PULSE Signals
— Datadog/NR/Grafana integration) with its own aggregate roots:

- `ObservabilityCredentials` (per-tenant, per-provider keys)
- `ServiceSquadOwnership` (the service ↔ squad mapping graph)
- `ObsMetricSnapshot` (rollup data)

Two competing placements were considered:

| Option | Pros | Cons |
|--------|------|------|
| **A — `contexts/integrations/observability/`** sub-context, peer to `contexts/integrations/jira/discovery/` | Mirrors existing Jira-discovery structure; signals integration semantics | Wrong granularity: `integrations/jira/discovery/` is purely ingestion-side glue, while observability has read-side aggregation logic (rollups, capability detection, ownership inference) that doesn't fit "integration plumbing" |
| **B — `contexts/observability/`** as a peer bounded context to `engineering_data/`, `metrics/`, `pipeline/`, `tenant/` | Reflects that observability has its own aggregate root + domain logic; cleanly separates from integration adapters (which live in `connectors/observability/`) | One more top-level BC to onboard; precedent forces a position on whether future integrations earn their own BC too |

## Decision

**Adopt Option B.** Place the new code at `contexts/observability/`,
peer to the existing 5 BCs. Adapters stay at `connectors/observability/`
(matches the existing split: `connectors/jira/` + `contexts/integrations/jira/`).

```
packages/pulse-data/src/
├── connectors/
│   ├── github_connector.py
│   ├── jira_connector.py
│   ├── jenkins_connector.py
│   └── observability/                    ← NEW (FDD-OBS-001)
│       ├── __init__.py
│       ├── base.py                       ← Protocol + dataclasses
│       ├── _anti_surveillance.py         ← strip_pii utility (ADR-025 L1)
│       ├── datadog_connector.py          ← PR 2
│       └── newrelic_connector.py         ← PR future (R3)
└── contexts/
    ├── engineering_data/
    ├── integrations/                     ← stays Jira-only for now
    ├── metrics/
    ├── observability/                    ← NEW BC (FDD-OBS-001)
    │   ├── __init__.py
    │   ├── models.py                     ← ORM (TenantObservabilityCredentials, ServiceSquadOwnership, ObsMetricSnapshot)
    │   ├── repositories.py               ← ObservabilityRepository
    │   ├── routes.py                     ← /v1/obs/* endpoints (PR 2+)
    │   └── services/
    │       ├── __init__.py
    │       ├── capability_detection.py   ← ADR-026 capabilities
    │       ├── credential_service.py     ← ADR-021 encrypt/decrypt (PR 2)
    │       ├── ownership_inference.py    ← ADR-022 Tier 1+2+3 (PR 3-4)
    │       └── rollup_worker.py          ← ADR-024 (PR 4)
    ├── pipeline/
    └── tenant/
```

## Rationale

1. **Aggregate root test.** A bounded context owns at least one
   aggregate root with consistency boundaries. Observability has three
   (`ObservabilityCredentials`, `ServiceSquadOwnership`, `ObsMetricSnapshot`).
   In contrast, `integrations/jira/discovery/` owns no aggregate of its
   own — it manipulates `jira_project_catalog` (which logically belongs
   to a Jira-integration sub-context, but is a rollup of operator
   choices, not a domain aggregate).

2. **Read-side logic.** `contexts/integrations/jira/discovery/` is
   pure ingestion glue (mode resolver, smart prioritizer, audit). The
   observability work has substantial read-side logic (capability
   detection, rollup queries, ownership inference, Carlos's timeline
   composition). Placing it under `integrations/` would mix concerns.

3. **Adapter/domain split.** `connectors/observability/` owns the
   adapter layer (HTTP, vendor DSL translation, rate-limit, strip_pii).
   `contexts/observability/` owns the domain (aggregates, business
   rules, repositories). Same split as Jira: `connectors/jira_connector.py`
   (HTTP) + `contexts/integrations/jira/discovery/` (domain rules). The
   only difference for observability is the **size** of the domain layer
   warrants peer-BC placement.

4. **Future integrations precedent.** This decision sets the rule:
   an integration earns its own peer BC when it has its own aggregate
   roots and substantial read-side logic. Otherwise it lives under
   `contexts/integrations/<vendor>/`. This is intentional gatekeeping —
   not every connector justifies a BC.

## Consequences

### Positive
- Clean separation: adapters stay thin in `connectors/`, domain stays
  rich in `contexts/observability/`.
- Independent test surface (`tests/unit/contexts/observability/`).
- Easier to extract to its own service later if the modular monolith
  splits — the BC is the natural fault line.

### Negative
- Future engineers must justify whether a new integration deserves a
  peer BC or sits under `integrations/`. The criterion (aggregate root
  + read-side logic) is documented here for them.
- `contexts/observability/` may seem redundant with `connectors/observability/`
  at first glance. The naming is explicit about the layer (adapter vs
  domain) — same as `connectors/jira_connector.py` vs
  `contexts/integrations/jira/`.

## Anti-pattern explicitly rejected

```python
# ❌ Do NOT do this:
from src.connectors.observability.datadog_connector import DatadogProvider
# ... in business logic, calling provider directly without going through repo
```

Business logic in `contexts/observability/services/` always goes
through `ObservabilityRepository` for persistence and through the
`ObservabilityProvider` Protocol (not concrete adapters) for live
queries. Adapters are a concern of the factory inside
`connectors/observability/__init__.py`.

## References

- Existing peer BCs: `engineering_data/`, `metrics/`, `pipeline/`,
  `tenant/`, `integrations/`.
- Existing adapter convention: `connectors/{github,jira,jenkins}_connector.py`.
- INC-015's `MetricsRepository` pattern (post-FDD-DSH-060) is the model
  for `ObservabilityRepository`.
