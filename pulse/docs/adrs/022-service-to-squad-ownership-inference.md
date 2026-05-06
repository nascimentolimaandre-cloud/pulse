# ADR-022: Service-to-Squad Ownership Inference (Hybrid)

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Main session + `pulse-data-engineer` + `pulse-product-director`
- **Related:** FDD-PIPE-001 (squad qualification), FDD-OBS-001 (observability), ADR-014 (Jira discovery)

---

## Context

Observability platforms list **services** (Datadog Service Catalog, New
Relic Entities). PULSE works with **squads** (Jira project keys, e.g.
`OKM`, `BG`). To deliver Service Ownership Map (FDD-OBS-001 Phase 1
view #2), Deploy Health Timeline (#1), and Squad Reliability Posture
(#5), each service must be mapped to **exactly one squad**.

Two failure modes drive the design:

1. **Tenant doesn't tag services**. Datadog allows `service.owner` /
   `team` tags, but in real engagements ~30% of services lack tags.
   Pure tag-based ownership map = useless coverage.
2. **Tenant tags badly** (typos, abandoned squad names, services owned
   by 2 squads). Pure tag-based + auto-trust = corrupted data on which
   board-level metrics rely.

Three pure-strategy options, each rejected:

| Option | Rejected because |
|--------|-----------------|
| **Pure tag-based** (trust DD `service.owner` / NR `team`) | Tag coverage is incomplete and drifts; no fallback for untagged |
| **Pure heuristic** (repo name → service name fuzzy match) | Brittle (`webmotors.checkout-api` ≈ `checkout-api`), false positives across squads sharing repo prefixes |
| **Pure manual** (operator types each mapping) | Doesn't scale — tenant with 142 services would abandon the feature |

## Decision

Adopt a **hybrid 3-tier inference** with operator override as the
escape hatch. Same philosophy as FDD-PIPE-001 (squad qualification):
heuristic + override.

### Tier 1 — Authoritative tag (when present)

Read provider-specific ownership tags:
- **Datadog**: `service.owner`, `team`, `squad` (configurable order)
- **New Relic**: `team` attribute, `nr.account.team` tag
- **Grafana**: TBD R4

If the tag value matches a qualified squad in `jira_project_catalog`
(case-insensitive), accept the mapping with confidence `'tag'`.

### Tier 2 — Repo-intersection heuristic

Same algorithm as `MetricsRepository.get_repos_active_for_squad`:

```sql
SELECT DISTINCT split_part(pr.repo, '/', 2) AS repo_name
FROM eng_pull_requests pr
WHERE pr.title ~* concat('\m', squad_key, '-\d+')
  AND pr.created_at >= NOW() - INTERVAL '90 days'
```

For each service in the observability catalog, find the squad whose
active repos (last 90d) include the service's repo (via `repo_url`
metadata or service name regex). Confidence: `'heuristic'`.

If multiple squads match (service touched by 2+ squads' PRs), pick the
one with the **highest pr_count_90d** intersecting that repo. Tie-break:
oldest squad (earliest first PR).

### Tier 3 — Manual override (operator UI)

`service_squad_ownership.override_squad_key` (NULLABLE). Set via admin
UI, persists across tag/heuristic refreshes. Operator override **always
wins** Tier 1 and Tier 2.

### Schema (migration `017_service_squad_ownership`)

```sql
CREATE TABLE service_squad_ownership (
    tenant_id            UUID NOT NULL,
    provider             TEXT NOT NULL,
    service_external_id  TEXT NOT NULL,         -- DD: service name; NR: entity GUID
    service_name         TEXT NOT NULL,         -- display name
    repo_url             TEXT,                  -- when available
    inferred_squad_key   TEXT,                  -- output of Tier 1 or Tier 2
    inferred_confidence  TEXT CHECK (inferred_confidence IN
                            ('tag','heuristic','none')),
    override_squad_key   TEXT,                  -- Tier 3 — operator-forced
    last_inference_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, provider, service_external_id)
);
-- RLS standard
-- Index: (tenant_id, COALESCE(override_squad_key, inferred_squad_key))
```

The **effective** squad for a service is:

```sql
COALESCE(override_squad_key, inferred_squad_key)
```

### Inference job

A nightly worker (`service_ownership_inference_job`):
1. Fetches the service catalog from each connected provider.
2. Runs Tier 1 → Tier 2 cascade.
3. UPSERT each row, only updating `inferred_*` columns (never touches
   `override_squad_key`).
4. Emits `service.ownership.refreshed` Kafka event for downstream
   invalidations.

The **operator UI** (`/settings/integrations/observability/ownership`)
shows:
- Coverage: `% services mapped (count(effective_squad IS NOT NULL) / total)`
- Per-service row: name, inferred squad + confidence, override dropdown
- Bulk action: "Confirm all heuristic-mapped" → promotes to override
- Filter by status: `tagged`, `inferred`, `override`, `unmapped`

## Consequences

### Positive
- Coverage starts high (Tier 1) and degrades gracefully to manual
  (Tier 3) — Brazilian mid-market reality of inconsistent tagging.
- Operator override is **append-only** to inference (never overwrites
  it) — tenant can go back and check "what was the heuristic guess?"
- Reuses FDD-PIPE-001 squad qualification (only qualified squads can
  own services — invalid `RELEASE`/`CVE`/`AXIOS` cannot).
- Consistent UX with squad qualification override pattern.

### Negative
- 3 tiers = more state to test. 12 boundary cases minimum
  (tag/no-tag × heuristic-match/no-match × override/no-override).
- Heuristic on repo name is fragile across monorepos and shared infra
  services. We explicitly mark these as `confidence='none'` — operator
  must override or accept "unmapped".
- The `service.owner`/`team` tag value must match `jira_project_catalog
  .project_key` exactly (case-insensitive). If tenant tags as "okm-team"
  but project key is `OKM`, Tier 1 fails. We log this mismatch as a
  warning to ease debugging.

## Open questions (filed)

- **FDD-OBS-001-FU-1**: should we normalize tag values (`okm-team` → `OKM`
  via fuzzy match)? Risks false positives. Defer to discovery interviews.
- **FDD-OBS-001-FU-2**: do we expose "shared services" (1 service ↔ 2
  squads) as a distinct concept, or force pick one? Defer.
