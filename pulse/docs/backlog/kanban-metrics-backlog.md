# Kanban-Native Flow Metrics — FDD Backlog

FDD cards for the Kanban Flow Metrics Suite. Companion to
`pulse/docs/product-spec-kanban-metrics.md`. Ordered by delivery sequence.

Card ID prefix: `FDD-KB-`

---

## Sequence 0 — Pre-work & foundations

### FDD-KB-001 · Add `labels JSONB` column to `eng_issues` and populate via normalizer
**Epic:** Kanban Flow Metrics · **Release:** MVP (pre-work) · **Priority:** P0
**Persona:** Enables Ana (Flow Distribution), Priya (future block reasons)
**Owner class:** Data (`pulse-data-engineer`)

**Acceptance (BDD):**
```
Given the eng_issues table exists with current columns
 When the migration runs
 Then a new JSONB column `labels` is created with default '[]' and a GIN index

Given the Jira normalizer receives an issue payload with fields.labels
 When the issue is upserted into eng_issues
 Then the labels array is stored verbatim (strings only, trimmed, lowercased)

Given an issue that had no labels arrives
 When upserted
 Then the stored value is an empty JSONB array (never null)
```
**Anti-surveillance check:** PASS — labels are issue-level metadata.
**Dependencies:** Alembic infrastructure, Jira normalizer.
**Estimate:** S
**Analytics:** none

---

### FDD-KB-002 · Persist daily CFD snapshots for historical baselines
**Epic:** Kanban Flow Metrics · **Release:** MVP (pre-work) · **Priority:** P0
**Persona:** Enables Carlos (Flow Load)
**Owner class:** Data (`pulse-data-engineer`) + Metrics (`pulse-data-scientist`)

**Acceptance (BDD):**
```
Given the metrics worker runs its daily cycle
 When CFD is computed for each tenant/squad
 Then a row per (tenant_id, squad, date, status) is written to
      metric_snapshots (or dedicated cfd_daily_snapshots) with counts

Given 90 days of CFD snapshots exist for a squad
 When a consumer queries "P85 WIP over last 90 days"
 Then the endpoint returns a single numeric value in <200ms

Given a squad with less than 90 days of history
 When baseline is requested
 Then the response flags `sufficient_history: false` and falls back to tenant-level P85
```
**Anti-surveillance check:** PASS — squad-level snapshot, no per-author dimension.
**Dependencies:** Existing `calculate_cfd`, metrics worker scheduler.
**Estimate:** M
**Analytics:** none (internal)

---

## Sequence 1 — MVP: Aging WIP + Flow Efficiency

### FDD-KB-003 · Calculate Aging WIP (Work Item Age) for active items per squad
**Epic:** Kanban Flow Metrics · **Release:** MVP · **Priority:** P0
**Persona:** Priya (Agile Coach) — PRIMARY
**Owner class:** Metrics (`pulse-data-scientist`) + Data (`pulse-data-engineer`) + Frontend (`pulse-engineer`)

**Status: FORMULAS VALIDATED** — `pulse-data-scientist` · 2026-04-17  
**SQL de referência:** `pulse/docs/metrics/kanban-formulas-v1.md` — Queries 1, 2 e 4

**Decisoes tomadas (2026-04-17):**
- `entered_current_status_at` = MAX(entered_at) em `status_transitions JSONB` para transicoes em `in_progress` ou `in_review`. Fallback: `started_at`, depois `created_at`.
- Reopen **reseta** age (usa MAX — nao a primeira entrada).
- Baseline historico: P85 do `cycle_time = completed_at - started_at` nos ultimos 90d, minimo 10 issues. Fallback: tenant-wide P85.
- Fallback absoluto de 14d quando squad nao tem nenhum historico (novas, ou sem issues fechadas).
- Status `todo` excluido do WIP. Apenas `in_progress` e `in_review`.
- Sem cap em 365d no dado — UI pode truncar exibicao mas dado bruto eh preservado.
- Payload anti-surveillance: `assignee` nunca exposto. `title` opcional (truncar 60 chars se incluido).
- Indice parcial necessario: `(tenant_id, project_key, normalized_status) WHERE normalized_status IN ('in_progress', 'in_review')`.

**Acceptance (BDD):**
```
Given a squad with 12 issues in normalized_status in {in_progress, in_review}
 When Priya opens the Flow Health section on /home
 Then she sees a horizontal scatter with 12 points
  And each point shows issue_key, column, age in days on hover
  And a vertical dashed line marks the squad's historical P85 cycle time
  And items with age > 2×P85 are painted in the risk token color
  And the KPI reads "X items em risco (Y% do WIP atual)"

Given a squad with <90 days of history (fewer than 10 completed issues)
 When Aging WIP is calculated
 Then the baseline falls back to tenant-level P85
  And the chart displays a warning chip "Baseline da empresa (histórico insuficiente do squad)"

Given a squad with zero items in WIP
 When the section loads
 Then the empty state reads "Sem trabalho em andamento neste squad"
  And no scatter is rendered

Given the endpoint returns an error
 When the section loads
 Then an inline error card with "Tentar novamente" is shown preserving layout

Given the drill-down is opened on an item
 When the payload is inspected
 Then no `assignee` field is present (anti-surveillance enforcement)

Given an issue that was reopened (Done -> In Progress)
 When Aging WIP is calculated
 Then age_days counts from the most recent entry into an active status
  And NOT from the original started_at
```
**Anti-surveillance check:** PASS — item-level, no author, deep link delegates to Jira.
**Dependencies:** `eng_issues` (exists), squad mapping via `project_key` (exists), baseline historico calculado on-demand (nao requer FDD-KB-002 para MVP — Q4 eh calculada inline).
**Estimate:** L
**Analytics events:** `flow_health_section_viewed`, `aging_wip_item_clicked`, `aging_wip_baseline_fallback_shown`

---

### FDD-KB-004 · Calculate Flow Efficiency (touch time / cycle time) per squad
**Epic:** Kanban Flow Metrics · **Release:** MVP · **Priority:** P0
**Persona:** Priya (Agile Coach), Marina (Sr Dev)
**Owner class:** Metrics (`pulse-data-scientist`) + Data (`pulse-data-engineer`) + Frontend (`pulse-engineer`)

**Status: FORMULAS VALIDATED** — `pulse-data-scientist` · 2026-04-17  
**SQL de referência:** `pulse/docs/metrics/kanban-formulas-v1.md` — Query 3

**Decisoes tomadas (2026-04-17):**
- Agregacao: **weighted sum** (`Σ touch_time / Σ cycle_time`), NAO mean-of-ratios. Confirmado.
- `cycle_time = completed_at - started_at` (nao `created_at`). Usa `cycle_time_hours` column_property do modelo.
- `touch_time = Σ duracoes de transitions com status IN ('in_progress', 'in_review')`. Derivado de `status_transitions JSONB`.
- Issues com `cycle_time < 1h`: excluidas (ruido/dado corrompido).
- Issues com `cycle_time = 0`: `flow_efficiency = NULL` (nao 0, nao 1).
- Issues sem `status_transitions`: excluidas do calculo (reportar `sample_with_transitions` separado).
- Mapa de status Webmotors: "Aguardando Code Review" e "Aguardando Teste Azul" sao normalizados para `in_review` → contam como TOUCH na v1. Aceito como simplificacao consciente.
- Sample minimo: **5 issues** (nao 10) para squadfiltrado, dado que alguns squads tem throughput baixo.
- `formula_version = "v1_simplified"` hardcoded no payload.
- `formula_disclaimer` em PT-BR no payload para exibicao no frontend.
- Janela padrao: 60d. Parametrizavel via `window_days`.
- Guard: `touch_time > cycle_time` → cap em `cycle_time` (FE = 100%). Dado de transicoes corrompido.
- Transicao com `entered_at > exited_at`: excluida do somatorio (guard na query).

**Acceptance (BDD):**
```
Given a squad with ≥5 completed issues in the last 60 days (with status_transitions)
 When Flow Efficiency is calculated using the MVP simplification (wait = cycle − touch)
 Then FE = sum(touch_time) / sum(cycle_time) expressed as percentage (weighted-sum)
  And the payload includes formula_version: "v1_simplified"
  And formula_disclaimer explains the simplification in PT-BR

Given Priya opens the Flow Health section
 When the KPI renders
 Then she sees a gauge 0–100% with bands:
      red <15 / amber 15–25 / green 25–40 / elite ≥40
  And a 12-week sparkline trend
  And a tooltip explains "Flow Efficiency = tempo em trabalho ativo ÷ cycle time total"

Given she clicks the KPI
 When the drill-down opens
 Then she sees FE by squad as a horizontal bar chart, sorted desc
  And each bar is the weighted aggregate, not mean-of-ratios

Given a squad with <5 completed issues with transitions in the period
 When the endpoint is called
 Then the response returns `insufficient_data: true`
  And the UI shows "Dados insuficientes para este período"

Given an issue with cycle_time = 0
 When FE is calculated for that issue
 Then flow_efficiency for that issue = null (excluded from aggregation)

Given the payload is inspected
 When parsed
 Then no assignee/author field is present
```
**Anti-surveillance check:** PASS — squad aggregate only.
**Dependencies:** `status_transitions` in eng_issues (exists), `started_at`, `completed_at` (exists). Sem dependencias novas de schema.
**Estimate:** L
**Analytics events:** `flow_efficiency_hovered`, `flow_efficiency_drill_down_opened`, `flow_efficiency_insufficient_data_shown`

---

### FDD-KB-005 · Integrate Flow Health section into /home below DORA KPIs
**Epic:** Kanban Flow Metrics · **Release:** MVP · **Priority:** P0
**Persona:** Carlos (EM), Priya (Coach), Ana (CTO)
**Owner class:** UX (`pulse-ux-reviewer`) + Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given the /home dashboard is loaded
 When the user scrolls past the DORA + Flow KPI pills
 Then a new section titled "Flow Health" is visible
  And it contains 2 slots: Aging WIP (scatter + KPI) and Flow Efficiency (gauge)
  And the section respects the global filters (squad, period)

Given loading state
 When the section mounts
 Then two skeletons are rendered preserving geometry (no CLS)

Given all 6 states must be designed
 When the UX spec is produced
 Then there is an artefact for each: loading / empty / healthy / degraded / error / partial

Given desktop ≥1280, tablet, mobile
 When the layout is tested
 Then Aging WIP + FE stack vertically on mobile, side-by-side on desktop

Given tokens-only design rule
 When the CSS is audited
 Then no hex literals exist; only semantic tokens (--color-risk, --color-healthy, ...)
```
**Anti-surveillance check:** PASS (inherits from M1/M2).
**Dependencies:** FDD-KB-003, FDD-KB-004, existing home layout.
**Estimate:** M
**Analytics events:** `flow_health_section_viewed`, `flow_health_section_scrolled_into_view`

---

## Sequence 2 — R1: Flow Load + Flow Distribution + dedicated page

### FDD-KB-006 · Calculate Flow Load (WIP vs historical P85 baseline) per squad
**Epic:** Kanban Flow Metrics · **Release:** R1 · **Priority:** P0
**Persona:** Carlos (EM) — PRIMARY
**Owner class:** Metrics (`pulse-data-scientist`) + Data (`pulse-data-engineer`) + Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given daily CFD snapshots exist for the last 90 days (FDD-KB-002)
 When Flow Load is requested for all squads of a tenant
 Then for each squad: flow_load = wip_today / P85(wip_daily_90d)
  And the endpoint returns a ranked list desc by flow_load

Given Carlos opens the Flow Health view
 When the "Carga dos squads" panel renders
 Then he sees all squads ranked by load
  And colors: green <1.0, amber 1.0–1.2, red >1.2, deep-red >1.5
  And the KPI reads "X squads em overload (load > 1.2)"

Given a squad with <90 days of snapshots
 When computed
 Then baseline uses tenant-level P85 with `sufficient_history: false`
  And the UI shows an info chip

Given he clicks a squad row
 When drill-down opens
 Then a comparative chart shows WIP today vs baseline P50/P85/P95

Given the payload is audited
 When parsed
 Then no assignee/author field is present (squad-level only)
```
**Anti-surveillance check:** PASS — ranking is of squads, not people. Explicitly documented in spec §4-M3 as squad *protection* signal.
**Dependencies:** FDD-KB-002.
**Estimate:** M
**Analytics events:** `flow_load_viewed`, `flow_load_squad_clicked`, `flow_load_baseline_fallback_shown`

---

### FDD-KB-007 · Calculate Flow Distribution (feature/bug/tech-debt/ops mix) per period
**Epic:** Kanban Flow Metrics · **Release:** R1 · **Priority:** P1
**Persona:** Ana (CTO) — PRIMARY
**Owner class:** Metrics (`pulse-data-scientist`) + Data (`pulse-data-engineer`) + Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given FDD-KB-001 migration has run and labels are populated
 When Flow Distribution is computed for completed issues in the period
 Then each issue is categorized:
      issue_type = "Bug" → bug
      labels ∩ {tech-debt, refactor, ...} → tech_debt
      labels ∩ {ops, infra, sre} → ops
      issue_type = "Epic" → excluded
      else → feature
  And the response sums to 100% (tolerance 0.5pp)

Given Ana opens /flow-health (R1 page)
 When the Flow Distribution panel renders
 Then a 12-week stacked bar shows the weekly mix
  And a summary pie shows the period total
  And a KPI chip reads "Bug ratio: X% (Δ Y pts vs 90d atrás)"

Given bug_pct > 35% in 4 consecutive weeks
 When the panel renders
 Then a warning banner appears "Proporção de bugs elevada por 4 semanas"

Given the canonical label taxonomy config
 When a tenant has custom labels
 Then a settings surface (R2) allows mapping — for R1 use defaults

Given the payload is audited
 When parsed
 Then no assignee/author field is present
```
**Anti-surveillance check:** PASS — issue-type aggregate, no author.
**Dependencies:** FDD-KB-001.
**Estimate:** M
**Analytics events:** `flow_distribution_viewed`, `flow_distribution_period_changed`, `flow_distribution_warning_shown`

---

### FDD-KB-008 · Dedicated /flow-health page with full drill-downs
**Epic:** Kanban Flow Metrics · **Release:** R1 · **Priority:** P1
**Persona:** Priya, Carlos, Ana
**Owner class:** UX (`pulse-ux-reviewer`) + Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given the R1 release is deployed
 When a user navigates to /flow-health
 Then the page shows 4 panels:
      Aging WIP (full scatter + per-column heatmap)
      Flow Efficiency (gauge + trend + by-squad bar)
      Flow Load (ranking + drill)
      Flow Distribution (stacked bar + pie)
  And the global filter bar (squad, period, tribo) persists

Given analytics from MVP shows >50% of Flow Health viewers clicked a drill-down
 When the decision to build /flow-health is triggered
 Then this card executes — else we postpone

Given page performance
 When the /flow-health endpoint is called
 Then all 4 panels load within p95 < 1.5s for a full tenant (27 squads)
```
**Anti-surveillance check:** PASS (inherited).
**Dependencies:** FDD-KB-003 through FDD-KB-007.
**Estimate:** L
**Analytics events:** `flow_health_page_viewed`, `flow_health_page_panel_drilled`

---

## Sequence 3 — R2: Blocked Time + workflow config

### FDD-KB-009 · Create tenant_workflow_config with blocked_statuses / taxonomy
**Epic:** Kanban Flow Metrics · **Release:** R2 · **Priority:** P1
**Persona:** Enables Priya, Marina (Blocked Time)
**Owner class:** Data (`pulse-data-engineer`) + CISO (`pulse-ciso`)

**Acceptance (BDD):**
```
Given a new migration is applied
 When the DB is inspected
 Then a new table tenant_workflow_config exists with columns:
      tenant_id (PK), blocked_statuses JSONB, tech_debt_labels JSONB,
      ops_labels JSONB, formula_version TEXT, updated_at TIMESTAMP
  And RLS policies enforce tenant_id isolation

Given a tenant admin opens Settings → Workflow
 When they add "Waiting for Review" as a blocked status and save
 Then the config persists and is validated (string length, char set)
  And Flow Efficiency / Blocked Time recalculate on next worker cycle

Given a tenant has no config
 When metrics compute
 Then sensible defaults apply:
      blocked_statuses = []  (disables M5)
      tech_debt_labels = ["tech-debt","techdebt","refactor","debt"]
      ops_labels = ["ops","infra","sre","devops"]
```
**Anti-surveillance check:** PASS — config, not behavioral.
**Dependencies:** Alembic, auth middleware for admin scope.
**Estimate:** M
**Analytics events:** `workflow_config_opened`, `workflow_config_saved`

---

### FDD-KB-010 · Calculate Blocked Time Distribution for completed issues
**Epic:** Kanban Flow Metrics · **Release:** R2 · **Priority:** P1
**Persona:** Priya, Marina
**Owner class:** Metrics (`pulse-data-scientist`) + Data (`pulse-data-engineer`) + Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given a tenant has configured blocked_statuses (FDD-KB-009)
 When an issue's status_transitions are traversed
 Then blocked_time = sum of durations in any configured blocked status

Given completed issues in the period
 When Blocked Time Distribution is computed
 Then the response includes:
      count_blocked, pct_blocked, p50_blocked_hours, p85_blocked_hours
  And a histogram (0–1d / 1–3d / 3–7d / 7–14d / 14d+)

Given the panel renders
 When thresholds evaluate
 Then classification badge is:
      Healthy: pct_blocked <10% AND P85 <48h
      Degraded: 10–25% OR 48–120h
      Risk: >25% OR >120h

Given the tenant has NOT configured blocked_statuses
 When the panel loads
 Then an educational empty state reads
      "Configure em Settings → Workflow quais status representam bloqueio"
  And a CTA links to the config page

Given Flow Efficiency is refined in R2
 When it runs
 Then wait_time is decomposed into blocked vs queued
  And formula_version is "r2_with_blocked"
```
**Anti-surveillance check:** PASS.
**Dependencies:** FDD-KB-009.
**Estimate:** L
**Analytics events:** `blocked_time_viewed`, `blocked_time_config_cta_clicked`

---

## Sequence 4 — Cross-cutting quality gates

### FDD-KB-011 · Test pyramid for Kanban metrics (unit, property, integration, E2E, perf, a11y)
**Epic:** Kanban Flow Metrics · **Release:** MVP/R1/R2 (parallel to each) · **Priority:** P0
**Persona:** All (platform trust)
**Owner class:** QA (`pulse-test-engineer`)

**Acceptance (BDD):**
```
Given TDD discipline
 When any metric module is implemented
 Then unit tests have been written BEFORE the implementation

Given property-based testing
 When metrics are tested
 Then Little's Law consistency, P50≤P85≤P95 monotonicity,
      and sum-to-100% invariants all pass

Given integration tests
 When a Webmotors-like fixture (27 squads, 373k issues) is loaded
 Then all endpoints return correct shape and respect RLS

Given E2E Playwright
 When Priya's journey runs (open home → see Flow Health → drill Aging WIP → click item → verify Jira redirect)
 Then all steps pass on Chrome, Firefox, WebKit

Given perf benchmarks (k6)
 When /metrics/flow-health is called at 50 RPS for 2 minutes
 Then p95 < 1.5s and error rate < 0.1%

Given a11y audit (axe-core)
 When the Flow Health section is scanned
 Then zero critical/serious violations
  And WCAG AA color contrast holds for all gauge bands

Given anti-surveillance contract
 When any metric endpoint is response-validated
 Then the automated contract test FAILS if field `assignee` or `author`
      appears at any nesting level
```
**Anti-surveillance check:** Meta — enforces the contract.
**Dependencies:** Prior cards.
**Estimate:** L (spread across sequences)
**Analytics events:** N/A

---

## Card index

| ID | Title | Release | Priority | Est. |
|---|---|---|---|---|
| FDD-KB-001 | Add labels JSONB + normalizer populate | MVP pre | P0 | S |
| FDD-KB-002 | Persist daily CFD snapshots | MVP pre | P0 | M |
| FDD-KB-003 | Aging WIP calculation + UI | MVP | P0 | L |
| FDD-KB-004 | Flow Efficiency calculation + UI | MVP | P0 | L |
| FDD-KB-005 | Flow Health section on /home | MVP | P0 | M |
| FDD-KB-006 | Flow Load calculation + ranking | R1 | P0 | M |
| FDD-KB-007 | Flow Distribution calculation + UI | R1 | P1 | M |
| FDD-KB-008 | Dedicated /flow-health page | R1 | P1 | L |
| FDD-KB-009 | tenant_workflow_config + settings | R2 | P1 | M |
| FDD-KB-010 | Blocked Time Distribution | R2 | P1 | L |
| FDD-KB-011 | Test pyramid cross-cut | All | P0 | L |
| FDD-KB-012 | Flow Health snapshot persistence (deferred) | R1 | P2 | M |

Total estimate: MVP ≈ 2 L + 2 M + 1 S = ~4 sprints (2 devs, 2 weeks).

---

### FDD-KB-012 · Flow Health snapshot persistence (deferred from MVP)
**Epic:** Kanban Flow Metrics · **Release:** R1 · **Priority:** P2
**Persona:** Operator (pipeline reliability) — NOT user-facing
**Owner class:** Data (`pulse-data-engineer`)

**Status:** DEFERRED — opened by `pulse-data-engineer` 2026-04-17 during
FDD-KB-005 implementation. Current endpoint computes Aging WIP + Flow
Efficiency on-demand; measured p95 with partial + GIN indexes:
- tenant-wide: 247ms (target: 800ms) — 3x headroom
- squad FID: 45ms — 17x headroom

**Acceptance (BDD):**
```
Given the metrics worker runs its scheduled cycle
 When Flow Efficiency is computed per (tenant, squad, period)
 Then a row is written to metrics_snapshots with metric_type='kanban',
      metric_name='flow_efficiency', period matching the window, and
      value containing sample_size + formula_version

Given the /flow-health endpoint is called with squad_key+period matching
      an available snapshot
 When the snapshot is newer than 60 minutes
 Then the endpoint returns the snapshot value (fast path) instead of
      recomputing

Given observability shows p95 > 1s on /flow-health for N tenants
 When ops triggers the priority escalation
 Then this card moves from P2 to P0 and is pulled into the next sprint
```

**Trigger to resurface:** p95 latency > 1s on any tenant (Grafana alert)
OR tenant count > 10 (multi-tenant compounding) OR on-demand query plan
degrades (JSONB parse time > 2s on 800+ issues).

**Scope notes:**
- Aging WIP stays on-demand (WIP changes by the minute).
- Only Flow Efficiency persists (retrospective, stable).
- Grain: (tenant, squad, period_days) × (7,14,30,60,90,120) × 27 squads
  = 162 rows per worker cycle. Minimal table pressure.
- TTL: not required (latest-wins upsert).

**Anti-surveillance check:** PASS — no per-item snapshot, squad-level aggregate only.
**Dependencies:** Existing `metrics_snapshots` infra; metrics worker scheduler.
**Estimate:** M
