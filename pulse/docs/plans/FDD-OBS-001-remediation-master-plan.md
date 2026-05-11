# FDD-OBS-001 — Remediation Master Plan

**Status:** LOCKED 2026-05-10 night. All 4 decisions taken. Tomorrow = execution start.
**Decisions:** D1=PARALLEL · D2=stage gate after P2=YES · D3=Webmotors waits for Phase 5 · D4=R3 features OUT of scope
**Effective timeline:** ~8 days (compressed from ~10-14 by parallel tracks)
**Goal:** Take FDD-OBS-001 R2 from "internal pilot ready" to **"friendly-tenant ready"**
**Source of truth:** `docs/reviews/FDD-OBS-001-engineering-review.md` + `docs/reviews/FDD-OBS-001-frontend-review.md`
**Owner:** main session (orchestrator) — delegates per-phase to specialized agents
**Estimated effort:** ~60–70h spread across 5 phases + 2 review gates (~10–14 calendar days at single-engineer pace)

---

## 0. Why this exists

After the deep reviews (2026-05-10), two material gaps surfaced:

1. **Production frontend was never built.** All 3 UI pages (Ownership Map, Aliases, Timeline) live only in `pulse-ui/` prototype. `pulse-web/` (React, production) has zero observability code. Result: a friendly tenant cannot see Carlos's Deploy Health Timeline.
2. **Several backend integrity gaps** that the CISO reviews missed (Protocol leak, fictional rotation runbook, f-string SQL, hide_parameters incomplete, etc.).

User chose **Opção A** — close everything before exposing to paying customers. Plan must:

- Sequence work to avoid rework (e.g. don't build React UI before pulse-api proxy exists).
- Schedule **agent reviews at the right moments** (CISO after security-touching code, pulse-frontend after UI changes, pulse-test-engineer after E2E flows).
- Anticipate analyses that aren't obvious now but will block later (e.g. pulse-data-scientist on whether MONITOR_HEALTH severity is the right product signal before we lock the UI on it).
- Surface decisions the user must take vs. those the agents can take.

---

## 1. Current state recap (what's done)

| PR | What shipped | Tests | Status |
|----|---|---|---|
| #21 | Feature flag infra (PR 0) | 5 | ✅ merged |
| #23 | BC skeleton + Protocol + anti-surveillance (PR 1) | 60 | ✅ merged |
| #24 | DD connector + admin /validate (PR 2) | 46 | ✅ merged |
| #25 | Service Ownership Map (PR 3) — **prototype only** | 33 | ✅ merged |
| #26 | Team aliases (PR 3.5) — **prototype only** | 40 | ✅ merged |
| #27 | Rollup worker + Tier 2 + token bucket (PR 4a) | 64 | ✅ merged |
| #28 | Pivot to Monitors API (PR 4a.5) | +13 | ✅ merged |
| #29 | Deploy Health Timeline (PR 4b) — **prototype only** | +13 | ✅ merged |

**Total: ~5,660 LoC, 274 unit tests passing, 6 ADRs, 2 CISO reviews, 20 RISK items in backlog.**

Worker is running live against Webmotors DD, accumulating `monitor_health` snapshots every 15 min. Anchor partner validated for 90.9% squad coverage.

---

## 2. Goal & acceptance criteria

**Goal:** "Friendly-tenant ready" = a real Webmotors user (Carlos persona) can use Deploy Health Timeline + Service Ownership + Team Aliases via the production React app at `app.pulse.dev/...`, with the same data quality and security guarantees as PULSE's existing DORA dashboard.

**Done means:**

- [ ] All 3 obs pages exist in `packages/pulse-web/` with full design system adherence
- [ ] `pulse-api` (NestJS) proxies all obs endpoints — React talks to pulse-api, not pulse-data
- [ ] Backend integrity gaps closed (Protocol, rotation, f-string SQL, exception leak)
- [ ] End-to-end integration test exists for: worker → DB → pulse-data API → pulse-api proxy → React fetcher
- [ ] CISO final review signs off with 0 must-fix findings
- [ ] pulse-ux-reviewer signs off on all 3 production pages (WCAG AA + 6 states + responsive)
- [ ] pulse-product-director signs off on Carlos persona acceptance (timeline answers the persona's questions)
- [ ] Operator runbook exists for "onboarding a new DD tenant" including master-key rotation
- [ ] Webmotors customer test extended to cover the new UI invariants

---

## 3. Phase breakdown

### Pre-flight check (before Phase 1 starts — 30 min)

**Owner:** main session
**What:** Read both reviews carefully + this plan. Confirm phase order with user. Decide: do we want all 5 phases in one continuous push, or stage with checkpoints (e.g. after Phase 2)?

**User decisions needed:**
- (D1) Continue 100% solo or invite a 2nd engineer for parallel UI build?
- (D2) Stage gate at end of Phase 2 (backend done, no UI) — show CISO + decide React go/no-go?
- (D3) Anchor partner expectations: when does Webmotors see something? Now (prototype) or post-Phase 5 (React)?
- (D4) Do we add any **R3 features** (NewRelic adapter, sub-hourly buckets, query-API tenant path) to this scope? My recommendation: **NO** — keep R2 honest, R3 separate.

---

### Phase 1 — Backend integrity fixes (1.5 days, ~12h)

**Owner agent:** `pulse-engineer`
**Review gate:** `pulse-ciso` after, before merging the PR

**Scope** (atomic — 1 PR):

| Fix | Severity | Source | File(s) | Estimate |
|---|---|---|---|---|
| Add `list_monitors_for_service` + `MonitorState` to `ObservabilityProvider` Protocol | 🚨 P0 (engineer finding C) | `connectors/observability/base.py` | 1h |
| Master key rotation: write `scripts/rotate_obs_master_key.py` + `docs/runbooks/obs-master-key-rotation.md` + smoke test fixture | 🚨 P0 (engineer finding A) | new files | 5h |
| Replace f-string in `_set_tenant` SQL with bound parameter | ⚠️ P1 NEW (engineer finding D2) | `src/database.py:49` | 0.5h + audit other call sites |
| Extend `hide_parameters` mitigation to cover driver-level exceptions (custom exception handler middleware in FastAPI) | ⚠️ P1 NEW (engineer finding D2) | `src/main.py` + helper | 2h |
| RISK-7 Layer 2 PII trigger upgrade — recursive jsonb check, not just top-level `?` | ⚠️ P1 (RISK-7) | alembic migration 023 | 2h |
| RISK-12 Layer 4 source-grep scan widen to include `src/workers/obs_*.py` | 💡 P2 (RISK-12) | `tests/unit/test_obs_anti_surveillance.py` | 30min |
| RISK-13 extend `FORBIDDEN_REFS` with PR-author column identifiers | 💡 P2 (RISK-13) | same file | 30min |
| RISK-17 nested PII trigger — `creator.email` Datadog pattern | 💡 P2 (RISK-17) | `_anti_surveillance.py` + test | 30min |

**Tests:** every fix gets a regression test in the same PR.

**Acceptance:**
- All Phase 1 fixes in one PR with 0 regressions in 274 existing obs tests
- CISO sign-off on the PR before merge
- New tests pass

**Review schedule:**
- After code is ready: `pulse-ciso` reviews 🚨 + ⚠️ items
- After merge: smoke test rotation script against Webmotors stack (you run it locally)

**Sub-tasks the orchestrator will plan in detail when Phase 1 starts:**
- T1.1: Protocol fix (10 min code, 30 min tests, 10 min ADR-023 amendment)
- T1.2: Rotation runbook + script (3h script, 1h runbook, 1h smoke fixture)
- T1.3: SQL hardening (1h: audit + fix + test)
- T1.4: hide_parameters middleware (1h: middleware + test)
- T1.5: Layer 2 trigger upgrade (1.5h: migration + test)
- T1.6: Layer 4 scan widen + Layer 1 nested PII (1h combined)

---

### Phase 2 — `pulse-api` proxy module (1 day, ~8h)

**Owner agent:** `pulse-engineer`
**Review gate:** `pulse-ciso` (proxy is the auth surface for R1)

**Scope** (atomic — 1 PR):

- New NestJS module `packages/pulse-api/src/modules/observability/`:
  - `observability.controller.ts` — proxies these routes to pulse-data:
    - `GET /api/v1/obs/timeline`
    - `GET /api/v1/obs/ownership`
    - `POST /api/v1/admin/integrations/datadog/validate`
    - `GET /api/v1/admin/integrations/{provider}/metadata`
    - All alias CRUD endpoints
  - `observability.service.ts` — thin httpx-style pass-through to pulse-data (port 8000)
  - `observability.module.ts` — registers controller + service
- DTO mirror in pulse-shared types package
- Integration test that proves end-to-end: pulse-api → pulse-data → DB
- ADR-029: "Why pulse-api proxies pulse-data for observability" (auth surface, contract stability)

**Why this is its own PR:** pulse-api is where R1 auth + RBAC will plug in. Doing this now lets the React UI talk to pulse-api directly (the right architecture) instead of having to refactor later. Also gives ops a single TLS termination point.

**Acceptance:**
- All obs endpoints reachable via `localhost:3000/api/v1/obs/*` and `localhost:3000/api/v1/admin/integrations/*`
- Integration test green
- CISO review of the proxy boundary (no plaintext logging, auth-ready)

**Sub-tasks at planning time:**
- T2.1: NestJS module scaffold
- T2.2: 11 proxied endpoints (~30 LoC each, similar pattern to existing modules)
- T2.3: Shared DTOs in pulse-shared
- T2.4: Integration test using supertest
- T2.5: ADR-029 + sequence diagram

---

### Phase 3 — React UI **PR A**: Shell + Service Ownership Map (~2 days, ~16h)

**Owner agents:**
- `pulse-engineer` — React code, hooks, API client, design system primitives
- `pulse-frontend` — design system review, tokens audit
- `pulse-ux-reviewer` — final UX pass at end

**Review gates:**
- `pulse-ux-reviewer` after the page renders
- `pulse-test-engineer` after the code is ready (E2E + a11y axe-core)

**Scope** (atomic — 1 PR):

- **Design system additions** (4 new soft-color tokens in `tokens.css` — frontend review §11):
  - `--color-success-soft`, `--color-warning-soft`, `--color-danger-soft`, `--color-overlay`
- **New design system primitives** in `pulse-web/src/components/ui/`:
  - `<Modal>` with proper focus trap + return-focus
  - `<Table>` with sticky header + sort
  - `<StatusBadge>` with 6 confidence variants (alias variant **visually distinct** from tag)
  - `<SearchInput>` with debounce
  - `<Tabs>` for the Ownership / Aliases switch
- **Route shell** `/settings/integrations/observability/{ownership,aliases}` mirroring `jira.tsx` tab pattern
- **API client** `lib/api/observability.ts` + React Query hooks (`useOwnership`, `useTimeline`, `useAliases`, `useSuggestions`)
- **Ownership Map page** in `pulse-web/src/routes/_dashboard/settings/integrations/observability/ownership.tsx`
- **Sidebar entry** — link to Observability section
- **Impl spec** committed to `docs/ux-specs/observability-ownership-impl-spec.md` (frontend review provides exact contents)

**Acceptance:**
- All 4 primitives have Storybook entries + Vitest unit tests
- Ownership Map renders 473 services (real Webmotors data) without lag
- All 6 confidence states visually distinct + color-blind safe
- WCAG AA pass via axe-core in test suite
- Keyboard-only test: can open the override modal, edit, save, and return focus to the row
- pulse-ux-reviewer signs off (no editorial concerns)

**Sub-tasks at planning time:** (detailed when Phase 3 starts)
- T3.1: 4 tokens + sweep prototype for hardcoded hex
- T3.2: `<Modal>` primitive (1.5h — focus trap is the tricky part)
- T3.3: `<Table>` primitive (1.5h)
- T3.4: `<StatusBadge>` + `<SearchInput>` + `<Tabs>` (2h combined)
- T3.5: Route + API client + hooks (2h)
- T3.6: Ownership page componentization from prototype (4h)
- T3.7: Vitest + Storybook + axe (2h)
- T3.8: ux-reviewer pass + impl spec (1h)
- T3.9: Sidebar wiring + nav e2e (1h)

---

### Phase 4 — React UI **PR B**: Team Aliases (~1.5 days, ~10h)

**Owner agents:**
- `pulse-engineer` — page implementation reusing PR A primitives
- `pulse-frontend` — bulk paste UX pattern review
- `pulse-test-engineer` — E2E bulk import flow

**Review gate:** `pulse-ux-reviewer` for the bulk paste / suggestions UX

**Scope** (atomic — 1 PR, depends on PR A merged):

- Aliases page at `routes/_dashboard/settings/integrations/observability/aliases.tsx`
- Reuses `<Modal>`, `<Table>`, `<Tabs>` from PR A
- Bulk paste textarea + parse + preview + confirm flow (proper modal, not native `confirm()`)
- Suggestions panel (unaliased vendor teams from `/aliases/suggestions`)
- Optimistic updates via React Query mutations
- Impl spec at `docs/ux-specs/observability-aliases-impl-spec.md`

**Acceptance:**
- Bulk paste handles all error cases visually (empty rows, invalid squads, duplicates)
- Suggestions panel collapses when empty
- Round-trip from CSV paste → table refresh happens optimistically

**Sub-tasks at planning time:**
- T4.1: Aliases page route + table
- T4.2: Bulk paste modal + CSV parser
- T4.3: Suggestions panel
- T4.4: Mutations + optimistic updates
- T4.5: Vitest + axe + E2E

---

### Phase 5 — React UI **PR C**: Deploy Health Timeline (Carlos page) (~2.5 days, ~16–20h)

**Owner agents:**
- `pulse-engineer` — page implementation + Chart.js integration
- `pulse-frontend` — chart UX, tooltip design, deploy marker semantics
- `pulse-data-scientist` — **pre-Phase 5 review** (see below)
- `pulse-ux-reviewer` — editorial pass on the chart at the end
- `pulse-test-engineer` — accessibility audit (this is the riskiest page)

**🔍 Pre-Phase 5 analysis** (needed before code starts, ~2h):

Schedule before T5.1: a **`pulse-data-scientist` review** answering:
- Is "MONITOR_HEALTH severity 0..3" the right primary signal for Carlos's "did this deploy break anything?" workflow, or do we need to surface other dimensions (deploy_frequency_change, alert_count_delta_pre_post)?
- Should the chart aggregate severity across services by **MAX** (current) or by **count_at_severity** (richer)?
- Visualization recommendation: bar chart vs. heatmap vs. swimlane per service?
- Statistical concern: are 7 days enough sample size for a Carlos-meaningful trend, or do we anchor on rolling 30-day baseline?

This analysis WILL change the data model on the chart side. Better to know before we write the React component.

**Scope** (atomic — 1 PR):

- Timeline page at `routes/_dashboard/observability/timeline.tsx`
- **Replace SVG with Chart.js** (rest of app uses Chart.js — design consistency)
- Severity bands per hour with deploy markers as Chart.js annotations
- Tooltips on hover (Chart.js native + accessible)
- **Functional time-window selector** (24h / 7d / 30d that actually re-slices data — fix the prototype's cosmetic-only bug)
- **All 6 states**: loading skeleton, empty (no data yet), warming-up (worker has cycled <2h), healthy, degraded (partial data), error
- **Drill-down**: clicking a service in the legend filters to per-service view
- **Color-blind safe palette** — severity differentiated by shape + color, not color alone
- **Keyboard nav**: chart bars are `<button>` elements with `aria-label` describing the bucket
- **Screen reader**: chart has a hidden `<table>` with the same data for AT users
- Impl spec at `docs/ux-specs/observability-timeline-impl-spec.md`

**Acceptance:**
- pulse-test-engineer: axe-core passes, keyboard nav works end-to-end, screen reader reads all data
- pulse-data-scientist: chart matches the recommended visualization from pre-phase review
- pulse-ux-reviewer: 3 concepts pass + final recommendation matches what shipped
- Carlos persona: pulse-product-director runs a hallway test (or simulated) to confirm the page answers the persona's questions

**Sub-tasks at planning time:**
- T5.0: Data scientist analysis (2h)
- T5.1: Chart.js setup + severity bar config (3h)
- T5.2: Deploy markers as annotations + click handlers (2h)
- T5.3: Functional time window + URL state sync (2h)
- T5.4: 6-state rendering with skeleton + warming-up empty (2h)
- T5.5: Service drill-down route + filter (2h)
- T5.6: Accessibility layer (3h — table + aria + keyboard)
- T5.7: Vitest + axe + E2E (3h)
- T5.8: ux-reviewer pass (1h)

---

### Phase 6 — Customer test extension + CISO final + ops runbook (~1 day, ~6h)

**Owner agents:**
- `pulse-test-engineer` — extend Webmotors customer test with UI invariants
- `pulse-ciso` — final security review across all 5 phases
- `pulse-engineer` — operator runbook for tenant onboarding

**Scope** (atomic — 1 PR):

- Extend `tests-customers/webmotors/test_webmotors_obs_ownership.py` with timeline + ownership + alias data invariants
- New E2E test: full journey (validate DD key → see ownership → set alias → re-sync → see timeline)
- `docs/runbooks/obs-tenant-onboarding.md` — operator-facing onboarding doc with all the checklists
- CISO produces 3rd security review: `docs/security-reviews/FDD-OBS-001-final-review.md` covering Phases 1–5 combined
- Update ADR-028 with anything that changed during remediation
- Tag release `obs-001-v1.0` after CISO sign-off

**Acceptance:**
- CISO 0 must-fix findings
- Webmotors customer test covers ownership + alias + timeline invariants
- Runbook walks a junior operator through a fresh tenant in under 30 min

---

### Phase 7 — Anchor partner walkthrough (Optional, not in scope) 

After Phase 6 ships and the React app is up at `app.pulse.dev`, a real Webmotors stakeholder (Carlos persona) does a guided walkthrough. **NOT counted in the friendly-tenant readiness gate** — but scheduled here as a reminder.

---

## 4. Scheduled agent analyses (anticipate the right moments)

| When | Agent | Question | Why it matters |
|---|---|---|---|
| Start of Phase 1 | `pulse-ciso` | Re-validate rotation script against AWS Secrets Manager R4 migration path | Don't lock in rotation patterns that contradict R4 |
| Start of Phase 3 | `pulse-frontend` | Design system audit — what primitives already exist, what's missing | Avoid building duplicates |
| Pre-Phase 5 (BLOCKING) | `pulse-data-scientist` | Right primary signal + visualization for Carlos? | Without this, Phase 5 UI may need a costly rewrite |
| Mid-Phase 5 | `pulse-ux-reviewer` | 3 concepts for the timeline chart + recommendation | Carlos persona is the highest-leverage UX in R2 |
| End of Phase 5 | `pulse-product-director` | Acceptance criteria check vs. Carlos persona BDD | Avoids "looks good but doesn't answer the question" |
| Start of Phase 6 | `pulse-ciso` | Final review across all 5 phases | Last gate before friendly-tenant |
| End of Phase 6 | `pulse-test-engineer` | Test pyramid health (still right balance unit / integration / E2E?) | Prevents test debt from compounding into R3 |

---

## 5. Risks for the remediation itself

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pre-Phase 5 data-scientist review changes the data model on the chart side | High | Medium | Schedule early; fail fast |
| Design system primitives clash with existing pulse-web components | Medium | Low | Phase 3 starts with a pulse-frontend audit |
| pulse-api proxy auth-readiness conflicts with R1 SSO design | Medium | Medium | Phase 2 ADR-029 must explicitly state the auth contract |
| Chart.js bundle size impact on pulse-web | Low | Low | Already shipped elsewhere in the app per CLAUDE.md |
| Webmotors anchor expectations drift during the 2 weeks | Medium | High | User-to-decide (D3): show prototype or wait for Phase 5? |
| Rate-limit calibration changes (RISK-16) require Phase 5 re-test | Medium | Low | Test against worker after each phase |
| Agent context loss between sessions (multi-day plan) | Medium | Medium | This document; agent prompts in next-steps include phase context |

---

## 6. What's deliberately **out of scope**

To keep this honest, R2 remediation does NOT include:

- ❌ NewRelic adapter (R3)
- ❌ Multi-tenant cross-tenant discovery (RISK-15 → R1 SaaS, separate work)
- ❌ Service Account migration in DD (RISK-19 follow-up, deferred)
- ❌ KMS migration (RISK-1, R4)
- ❌ Per-tenant rate-limit overrides (RISK-16)
- ❌ MTTR Phase 2 (depends on 7+ days of rollup data — separate PR 5 after this remediation)

If user wants any of these in scope, decision (D4) above.

---

## 7. Tomorrow's first action (when you wake up)

1. **Open this file.** Read sections 2 (acceptance), 3 (phase order), 4 (scheduled analyses), and 5 (risks).
2. **Make 4 decisions** (D1–D4) from section 0.
3. **Tell main session:** "ok, vamos começar pela Phase 1" (or your preferred deviation).
4. Main session will then enter detailed planning for Phase 1 (the sub-task breakdown sketched in section 3 under each phase) and start dispatching to `pulse-engineer`.

### Suggested sequence after wake-up (if you say "GO"):

```
DAY 1 (Phase 1 — backend critical fixes)
  AM: T1.1 Protocol fix, T1.3 SQL hardening, T1.4 hide_parameters
  PM: T1.2 Rotation runbook + script
  EOD: PR up, pulse-ciso review requested

DAY 2 (Phase 1 finish + Phase 2 start)
  AM: T1.5 + T1.6 (Layer 2/4 fixes), CISO async review
  PM: Phase 1 merge, Phase 2 T2.1 + T2.2 start (NestJS proxy scaffold)

DAY 3 (Phase 2 finish, Phase 3 prep)
  AM: T2.3 + T2.4 (DTOs + integration test)
  PM: ADR-029, CISO review of proxy, Phase 3 pulse-frontend audit kickoff

DAY 4-5 (Phase 3 — Ownership Map in React)
  Full days on UI primitives + page componentization

DAY 6 (Phase 4 — Aliases in React)

DAY 7 (Pre-Phase 5 data-scientist + Phase 5 start)
  AM: pulse-data-scientist review (BLOCKING)
  PM: T5.1 + T5.2 Chart.js setup

DAY 8-9 (Phase 5 finish — Timeline in React)

DAY 10 (Phase 6 — final reviews + customer test + runbook + tag)
```

If you want to parallelize, the **only natural split** is:
- Engineer A: Phases 1+2 (backend), then 5 (Timeline — most complex UI)
- Engineer B: Starts Phase 3 in parallel with Engineer A's Phase 2, then Phase 4

But for solo, the linear sequence above is right.

---

## 8. Communication plan during the remediation

- **Each phase starts with main session writing a detailed sub-task plan** (the "at planning time" lists become full task breakdowns with file:line specificity).
- **Each phase ends with a 5-bullet summary in chat** (what shipped, tests added, any new RISK items, what surprised us, next phase blockers).
- **CISO reviews are async** — main session requests, agent writes report, main session reads + applies fixes before merge.
- **The 3 React UI PRs each get their own PR + ux-reviewer pass + CI green before merge.** No stacking.

---

## 9. Definition of "remediation complete"

- [ ] All 6 phases shipped and merged
- [ ] CISO final review = 0 must-fix
- [ ] Webmotors customer test covers all new UI flows
- [ ] React app at `app.pulse.dev` shows Ownership / Aliases / Timeline correctly
- [ ] Operator runbook lets a fresh engineer onboard a new tenant in <30 min
- [ ] Tag `obs-001-v1.0` created
- [ ] Memory in `~/.claude/.../MEMORY.md` updated: "FDD-OBS-001 R2 — friendly-tenant ready, anchor: Webmotors"

After that → MTTR Phase 2 (PR 5) becomes the next thing, requires 7+ days of rollup data accumulated which already started.

---

## Appendix A — Files touched by remediation (preview)

**New files:**
- `pulse/scripts/rotate_obs_master_key.py`
- `pulse/docs/runbooks/obs-master-key-rotation.md`
- `pulse/docs/runbooks/obs-tenant-onboarding.md`
- `pulse/docs/adrs/029-pulse-api-observability-proxy.md`
- `pulse/docs/ux-specs/observability-ownership-impl-spec.md`
- `pulse/docs/ux-specs/observability-aliases-impl-spec.md`
- `pulse/docs/ux-specs/observability-timeline-impl-spec.md`
- `pulse/docs/security-reviews/FDD-OBS-001-final-review.md`
- `pulse/packages/pulse-data/alembic/versions/023_obs_pii_trigger_recursive.py`
- `pulse/packages/pulse-api/src/modules/observability/` (new module)
- `pulse/packages/pulse-web/src/components/ui/{Modal,Table,StatusBadge,SearchInput,Tabs}.tsx`
- `pulse/packages/pulse-web/src/lib/api/observability.ts`
- `pulse/packages/pulse-web/src/routes/_dashboard/observability/timeline.tsx`
- `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/observability/{ownership,aliases}.tsx`

**Modified files:**
- `pulse/packages/pulse-data/src/connectors/observability/base.py` (Protocol)
- `pulse/packages/pulse-data/src/database.py` (f-string fix)
- `pulse/packages/pulse-data/src/main.py` (exception handler)
- `pulse/packages/pulse-data/tests/unit/test_obs_anti_surveillance.py` (scan widen)
- `pulse/packages/pulse-data/src/connectors/observability/_anti_surveillance.py` (nested PII)
- `pulse/packages/pulse-data/alembic/versions/018_service_squad_ownership.py` (trigger upgrade)
- `pulse/packages/pulse-web/src/components/layout/Sidebar.tsx` (nav)
- `pulse/pulse-ui/tokens.css` (4 new soft-color tokens, propagate to pulse-web)

---

## Appendix B — Open questions to revisit

- **Q1**: When pulse-api auth lands (R1), the obs proxy is the natural place. Should we stub a passthrough auth guard now (matching the existing TenantInterceptor pattern) so R1 has less to refactor?
- **Q2**: The rollup worker currently does 1 call per service per cycle = 473/h Webmotors. At R1 scale (10 tenants × 500 services = 5,000/h), are we sure DD's standard token bucket scales? Should we add per-tenant capacity overrides now or accept it as RISK-16?
- **Q3**: Do we want the Timeline page to support comparing two squads side-by-side? (Not in the original spec, but pulse-product-director might want it after seeing Carlos use it.)
- **Q4**: Is there appetite to extract `pulse-ui/` prototype work into Storybook stories that auto-generate React component stubs? Long-term might save 30% on future prototype → production cycles.
