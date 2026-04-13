# ADR-014: Dynamic Jira Project Discovery (Hybrid 4-Mode)

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Main session (orchestrator) + pulse-data-engineer + pulse-ciso + pulse-product-director
- **Supersedes:** Static `JIRA_PROJECTS` env-var scope configuration
- **Related:** ADR-005 (DevLake vs custom), ADR-011 (metadata-only security), ADR-002 (RLS multi-tenancy)

---

## Context

PULSE currently scopes Jira ingestion via a static `JIRA_PROJECTS` env var (comma-separated project keys). This was acceptable during single-tenant bootstrap but has become a hard blocker for:

1. **SaaS onboarding velocity.** Every new tenant requires manual project list curation, re-deploy of `.env`, and operator coordination. This breaks the "connect and see data in minutes" value proposition.
2. **Link-rate ceiling on PR↔Issue correlation.** Analysis of Webmotors data (63,447 PRs) showed 15,475 PRs (24.4%) reference Jira keys in titles, but only 3,220 (5.1%) linked successfully — because ~20 referenced projects (CKP, SECOM, BG, OKM, ESTQ, PF, SALES, APPJ, CRW, SDI, DSP, CRMC, INTG, AFDEV, MONEY, PJUN, FACIL, ENO…) were never in the static list. Keeping the list updated is ops toil that will never converge.
3. **Governance drift.** Teams create new Jira projects continuously; operators lack visibility into what's missing without querying Jira manually.
4. **Product positioning.** Competitors (LinearB, Jellyfish) require explicit project configuration. A "self-discovering engineering platform" is a clear differentiator.

## Decision

Adopt a **hybrid dynamic project discovery model** with 4 operational modes, persisted per tenant, with guardrails and admin UI.

### Modes

| Mode | Behavior | Use case |
|---|---|---|
| `auto` | All discovered projects are active by default; blocklist overrides | SMB self-serve, low-friction onboarding |
| `allowlist` | Only explicitly approved projects sync; discovery populates catalog as `discovered` requiring human approval | Regulated industries, enterprise with governance |
| `blocklist` | All discovered projects active except those explicitly blocked | Mid-market, operator-driven |
| `smart` | Auto-activates projects referenced by ≥N PRs in lookback window; remainder stays `discovered` | Default recommendation for engineering-centric teams |

### Architecture

- **New tables:** `tenant_jira_config`, `jira_project_catalog`, `jira_discovery_audit` (RLS-enforced, audit immutable).
- **New worker:** `discovery-worker` runs scheduled `ProjectDiscoveryService` per tenant, populates catalog.
- **New resolver:** `ModeResolver.resolve_active_projects(tenant_id)` replaces all reads of `settings.jira_project_list` in sync paths.
- **Guardrails:** rate budget per tenant (Redis token bucket), hard cap on active projects, auto-pause after 5 consecutive failures, blocklist precedence.
- **Admin API + UI:** `/api/v1/admin/integrations/jira/*` + `/settings/integrations/jira` route, RBAC-gated to `tenant_admin` role.
- **Feature flag** `DYNAMIC_JIRA_DISCOVERY_ENABLED` enables blue-green rollout; env var remains as bootstrap fallback for 2 releases.

## Consequences

### Positive
- Self-serve SaaS onboarding unlocked (competitive moat).
- PR↔Issue link rate projected to rise from 5% → 25-30% at steady state by covering all referenced projects.
- Auto-adapts to org changes (new projects, team splits, mergers).
- Governance-grade audit trail (SOC 2 ready).
- Architectural pattern reusable for GitHub repos, Jenkins jobs, GitLab projects (next iterations).

### Negative / Costs
- Added complexity: 3 new tables, 1 new worker, new service layer, new UI surface.
- Privacy risk in `auto` mode if tenant has sensitive Jira projects (HR, legal, finance) — mitigated by default `allowlist`, PII regex warnings on discovery, explicit blocklist.
- Variable ingestion cost per tenant (harder to quote pricing upfront) — mitigated by `max_active_projects` hard cap and admin-visible metrics.
- Additional Jira API surface (`/rest/api/3/project/search`) — mitigated by rate-limited discovery schedule (default daily 03:00 UTC).

### Rollback plan
Feature flag `DYNAMIC_JIRA_DISCOVERY_ENABLED=false` reverts sync workers to reading `JIRA_PROJECTS` env var. Catalog data persists harmlessly; no data migration required for rollback.

## Alternatives Considered

### A1 — Keep static list, expand manually (Option 1 in plan)
**Rejected.** Ops toil, drift-prone, doesn't scale in multi-tenant SaaS. Works for 1 tenant, breaks at 10.

### A2 — Pure auto-discovery (no modes, no governance)
**Rejected.** Ignores privacy/compliance requirements. A bank client would not tolerate automatic ingestion of an "HR-Confidential" Jira project. Governance is non-negotiable.

### A3 — DevLake-native project discovery
**Rejected per ADR-005.** We migrated off DevLake for Jira ingestion; adding a DevLake dependency back contradicts that decision.

### A4 — Per-project cron configs (config file)
**Rejected.** Still requires ops intervention, doesn't solve multi-tenant, doesn't solve drift.

## Implementation

Detailed phased plan tracked in: `packages/pulse-data/src/contexts/integrations/jira/discovery/` + branch `feat/jira-dynamic-discovery`.

**Phases:**
0. Foundation (migration, shared types, this ADR)
1. Backend core (discovery service, mode resolver, guardrails, scheduler)
2. API + UI (admin endpoints, settings page)
3. Security + QA (CISO review, integration/E2E/load tests)
4. Rollout (shadow → cutover → deprecate env var)

## Acceptance Gates

- Migration 006 preserves existing tenant state (bootstrap from env var).
- `SmartPrioritizer` identifies ≥18 candidate projects from current Webmotors PR scan.
- RLS + RBAC verified by pulse-ciso.
- Link rate measured before/after cutover; target ≥20% improvement.
- Feature flag tested in staging for minimum 7 days before prod cutover.
