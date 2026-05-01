# Dashboard — FDD Backlog

Feature-Driven Development cards for the PULSE Dashboard redesign.
Ordered by delivery sequence. Each card follows `<action> <result> <by/for/of> <object>`.

---

## Feature Set 1 — Foundation: Grouped KPIs & Filters

### FDD-DSH-001 · Group global KPIs into DORA and Flow pills
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P0
**Persona:** Carlos (EM), Ana (CTO)
**Owner class:** Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given Carlos opens the dashboard
 When the global metrics load successfully
 Then he sees two labeled groups "DORA Metrics" and "Flow & Management"
  And each group contains 4 KPIs with value, unit, trend % and sparkline
  And each DORA KPI shows a classification badge (Elite/High/Medium/Low)

Given the data is loading
 When the page mounts
 Then 8 KPI skeletons are shown preserving card geometry (no layout shift)

Given the global endpoint returns an error
 When the page mounts
 Then an inline error card is shown with a "Tentar novamente" button
```

**Anti-surveillance check:** PASS — all metrics are aggregate, no author fields exposed.
**Dependencies:** `GET /data/v1/metrics/global` endpoint (exists).
**Estimate:** M
**Analytics:** `dashboard_viewed`, `dashboard_loading_shown`, `dashboard_error_shown`

---

### FDD-DSH-002 · Filter dashboard by squad with searchable combobox
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P0
**Persona:** Carlos (EM), Priya (Agile Coach)
**Owner class:** Frontend (`pulse-engineer`) + API (`pulse-engineer`)

**Acceptance (BDD):**
```
Given Carlos wants to focus on one squad
 When he clicks the squad combobox
 Then he sees options grouped by tribo, with a search input at top
  And the list renders all 27 squads without scroll lag

Given Carlos types "sec" in the search
 When the list updates
 Then only squads whose name or tribo contains "sec" are shown

Given Carlos selects "SECOM"
 When the selection commits
 Then the combobox label updates to "SECOM"
  And KPI strip, ranking, and evolution all re-fetch scoped to that squad
  And an applied-filters banner shows "Exibindo SECOM · últimos 60 dias"
```

**Anti-surveillance check:** PASS — filter operates on team id only.
**Dependencies:** `GET /data/v1/pipeline/teams` (exists, returns 27 squads).
**Estimate:** M
**Analytics:** `dashboard_team_filter_changed`

---

### FDD-DSH-003 · Filter dashboard by period (30/60/90/120 days + custom)
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P0
**Persona:** Carlos, Ana, Priya
**Owner class:** Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given the dashboard is showing default period
 When Carlos clicks a period pill (30d, 60d, 90d, 120d)
 Then the selected pill highlights and aria-checked flips to true
  And all sections re-fetch with the new period

Given Carlos clicks "Personalizado…"
 When the custom range panel expands
 Then he can pick start and end dates (default: last 90 days)
  And if start > end, validation prevents submission and shows inline error
  And valid selection refetches data with ISO-formatted range

Given the period is changed
 When the new data arrives
 Then applied-filters banner reflects "últimos {N} dias" or "{start} a {end}"
```

**Anti-surveillance check:** PASS.
**Dependencies:** Extend `filterStore` to include `60d` and `120d`. Extend API query params.
**Estimate:** S
**Analytics:** `dashboard_period_changed`

---

### FDD-DSH-004 · Remove "PRs Needing Attention" from dashboard
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P0
**Persona:** Carlos (EM) — reduces clutter. Marina continues to see PRs at `/prs`.
**Owner class:** Frontend (`pulse-engineer`) + API (`pulse-engineer`)

**Acceptance (BDD):**
```
Given the dashboard is rendered
 When the page mounts
 Then the "PRs Needing Attention" section does not appear
  And no API call is made for `prsNeedingAttention`

Given the `/prs` route is accessed
 When it mounts
 Then the full PR list is still available (no regression)
```

**Anti-surveillance check:** PASS — actually REMOVES an author-surface (PR author name was shown on dashboard). Net improvement to anti-surveillance posture.
**Dependencies:** Update `useHomeMetrics` to drop `prsNeedingAttention` branch; verify `/prs` route owns its own hook.
**Estimate:** S
**Analytics:** none (deletion).

---

## Feature Set 2 — Per-Team Metric Rankings

### FDD-DSH-010 · Display per-team ranking with metric tabs
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P0
**Persona:** Carlos (EM), Priya (Agile Coach)
**Owner class:** Frontend (`pulse-engineer`) + API (`pulse-engineer`) + Metrics (`pulse-data-scientist`)

**Acceptance (BDD):**
```
Given the dashboard has loaded
 When Carlos sees the "Comparativo por squad" section
 Then 6 metric tabs are available: Deploy Frequency, Lead Time, Change Failure, Cycle Time, WIP, Throughput
  And the first tab (Deploy Frequency) is active by default
  And a horizontal bar ranking of all 27 squads is shown sorted by that metric
  And each row shows: position, squad name, tribo, bar length proportional to value, value+unit, DORA badge

Given a row classification is "low"
 When it is rendered
 Then the bar color is `--color-dora-low` AND a "Low" badge is shown (color + label, WCAG A)

Given Carlos clicks a different metric tab
 When the tab switches
 Then the sort direction flips appropriately (asc for lower-is-better, desc otherwise)
  And the chart subtitle updates to reflect the metric context
```

**Anti-surveillance check:** PASS — all rows are squad-level aggregates only.
**Dependencies:** New endpoint `GET /data/v1/metrics/by-team?metric={}&period={}` (needs `pulse-data-engineer` to expose).
**Estimate:** L
**Analytics:** `dashboard_ranking_metric_changed`

---

### FDD-DSH-011 · Classify each ranking row using DORA thresholds
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P1
**Persona:** Carlos, Ana
**Owner class:** Metrics (`pulse-data-scientist`) + API (`pulse-engineer`)

**Acceptance (BDD):**
```
Given a deploy frequency value of 3.8/day
 When classified
 Then the classification is "elite" (>=1/day)

Given a change failure rate of 12%
 When classified
 Then the classification is "medium" (5-15%)

Given a flow metric without DORA threshold (WIP, Throughput)
 When classified
 Then the classification uses the quantile-based rule defined by pulse-data-scientist
  And the rule is documented in pulse/docs/metrics/classification.md
```

**Anti-surveillance check:** PASS.
**Dependencies:** Formula sign-off from `pulse-data-scientist`.
**Estimate:** M
**Analytics:** none.

---

### FDD-DSH-012 · Open team drawer from ranking row click
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P1
**Persona:** Carlos, Priya
**Owner class:** Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given the ranking is visible
 When Carlos clicks a team row (or presses Enter/Space on it with focus)
 Then a non-modal drawer slides from the right (520px desktop, full-screen mobile)
  And the drawer shows the squad name, tribo, 7 metric tiles (current values), and 2 charts: 12-week evolution + cycle-time distribution
  And the page behind remains interactive

Given the drawer is open
 When Carlos presses Escape
 Then the drawer closes
  And focus returns to the originating row

Given a screen reader user navigates the drawer
 When the drawer opens
 Then role="dialog" is announced with the squad name as accessible label
```

**Anti-surveillance check:** PASS — drawer shows only aggregate team metrics, no PR/author lists.
**Dependencies:** `GET /data/v1/teams/{id}/detail?period={}` endpoint.
**Estimate:** L
**Analytics:** `dashboard_drawer_opened`, `dashboard_drawer_closed` (with dwellMs)

---

## Feature Set 3 — Evolution Small Multiples

### FDD-DSH-020 · Display 12-week evolution per squad in small multiples
**Epic:** Dashboard Redesign · **Release:** R1 · **Priority:** P1
**Persona:** Priya (Agile Coach), Carlos
**Owner class:** Frontend (`pulse-engineer`) + API (`pulse-engineer`) + Data (`pulse-data-engineer`)

**Acceptance (BDD):**
```
Given the dashboard is loaded
 When Priya scrolls to "Evolução por squad"
 Then a grid of 27 mini line-charts is shown, one per squad
  And squads are grouped under tribo headings (PF, TEC, PI, SALES, BG, DESC, ENO, CPA)
  And each tile shows: squad name, tribo, 12-week spark, current value, delta vs 12 weeks ago

Given Priya changes the "Métrica" select
 When a new metric is selected (Deploy Freq, Lead Time, CFR, Cycle P50, WIP, Throughput)
 Then all 27 sparks re-render with the new metric
  And the value and delta update per tile

Given the data is backfilling for a specific squad
 When its tile renders
 Then the spark shows a dashed segment for the backfilling range
  And a "Backfill" badge is shown
```

**Anti-surveillance check:** PASS — tiles show team-level series only.
**Dependencies:** `GET /data/v1/metrics/by-team/evolution?metric={}&period={}` endpoint.
**Estimate:** L
**Analytics:** `dashboard_evolution_metric_changed`

---

### FDD-DSH-021 · Drill into drawer from small-multiple tile
**Epic:** Dashboard Redesign · **Release:** R1 · **Priority:** P2
**Persona:** Priya
**Owner class:** Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given the small multiples are rendered
 When Priya clicks a tile
 Then the same team drawer opens (identical to ranking drill-down)
  And analytics source is tagged "small-multiple"
```

**Anti-surveillance check:** PASS.
**Dependencies:** FDD-DSH-012.
**Estimate:** XS
**Analytics:** `dashboard_drawer_opened { source: 'small-multiple' }`

---

## Feature Set 4 — States & Polish

### FDD-DSH-030 · Show empty state when no squads are configured
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P1
**Persona:** Carlos (first-time admin)
**Owner class:** Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given no squads exist for the tenant
 When the dashboard loads
 Then an empty-state card is shown with heading "Nenhuma squad cadastrada ainda"
  And a secondary action links to /settings/sources to connect DevLake
  And no zero-value KPIs are rendered
```

**Anti-surveillance check:** PASS.
**Dependencies:** —
**Estimate:** S
**Analytics:** `dashboard_empty_shown`

---

### FDD-DSH-031 · Show degraded-data banner when sources are delayed
**Epic:** Dashboard Redesign · **Release:** R1 · **Priority:** P1
**Persona:** Carlos, Lucas (Data Platform)
**Owner class:** Frontend (`pulse-engineer`) + Data (`pulse-data-engineer`)

**Acceptance (BDD):**
```
Given one or more data sources have freshness > SLA
 When the dashboard mounts
 Then a `role="status"` banner is shown above the KPI strip with
      "{N} fonte(s) com atraso. Alguns gráficos podem estar parciais."
  And a link "Ver pipeline" deep-links to /pipeline-monitor

Given all sources are fresh
 When the dashboard mounts
 Then no banner is shown
```

**Anti-surveillance check:** PASS.
**Dependencies:** Freshness metadata on `GET /data/v1/metrics/global`.
**Estimate:** S
**Analytics:** `dashboard_degraded_shown`

---

### FDD-DSH-032 · Validate and cap custom date range
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P2
**Persona:** Ana, Priya
**Owner class:** Frontend (`pulse-engineer`)

**Acceptance (BDD):**
```
Given Carlos picks start=2025-04-16 and end=2026-04-16 (365 days)
 When he confirms
 Then data loads normally

Given Carlos picks start=2025-01-01 and end=2026-04-16 (>365 days)
 When he attempts to confirm
 Then inline validation shows "Período máximo: 365 dias"
  And data is not refetched

Given Carlos picks start after end
 When validation runs
 Then an inline error is shown and refetch is blocked
```

**Anti-surveillance check:** PASS.
**Dependencies:** —
**Estimate:** S
**Analytics:** `dashboard_custom_range_rejected { reason }`

---

### FDD-DSH-033 · Accessibility audit on dashboard — ✅ DONE 2026-04-24
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P0
**Persona:** All personas
**Owner class:** Test (`pulse-test-engineer`)
**Status:** ✅ Shipped — Sprint 1.2 step 4 (2026-04-23, 3 pages) + FDD-DSH-033
closure (2026-04-24, +7 pages). Full dashboard surface audited.

**Delivered — 10 routes automated with axe-core + Playwright:**

| Page | Rules passing | Spec |
|---|---|---|
| `/` (Home Dashboard)                 | 23 | `home.spec.ts` |
| `/metrics/dora`                      | 21 | `dora.spec.ts` |
| `/metrics/cycle-time`                | 21 | `cycle-time.spec.ts` |
| `/metrics/throughput`                | 21 | `throughput.spec.ts` |
| `/metrics/lean`                      | 21 | `lean.spec.ts` |
| `/metrics/sprints`                   | 21 | `sprints.spec.ts` |
| `/prs`                               | 21 | `prs.spec.ts` |
| `/pipeline-monitor`                  | 17 | `pipeline-monitor.spec.ts` |
| `/integrations`                      | 16 | `integrations.spec.ts` |
| `/settings/integrations/jira/catalog`| 21 | `jira-settings.spec.ts` |

**Result:** 10/10 specs green in 15.4s; **0 critical + 0 serious** across 203 rule-instances.
WCAG 2.1 AA gate is live in CI (tests/e2e/a11y/*.spec.ts runs via `npm run test:a11y`).
Template + runbook documented in `pulse/docs/testing-playbook.md` §8.7.

**Real bug found & fixed during the audit (Sprint 1.2 step 4):**
`SquadListCard.MetricPair` was wrapping `<dt>/<dd>` in `<span>` instead of `<div>`.
Per HTML5, `<dl>` only accepts `<dt>`, `<dd>`, or `<div>` wrappers as direct
children. 88 violations fixed by swapping one element.

**Deliberate deferrals (tracked elsewhere):**
- `color-contrast` rule disabled via `disableRules` in every spec — tracked
  as FDD-OPS-003 (design-system contrast audit, P1).
- `page-has-heading-one` (best-practice, not WCAG) surfaced that
  `/pipeline-monitor` has no h1 — added to a11y backlog for polish.
- Drawer/keyboard-only journey (second BDD scenario) is covered by the
  smoke E2E spec pattern; dedicated keyboard-nav spec to be added when
  the drawer regresses or in Sprint 2 polish.

**Anti-surveillance check:** PASS.
**Dependencies:** FDD-DSH-001..032 (delivered).
**Estimate:** M (delivered).
**Analytics:** none.

---

## Feature Set 5 — Future (R2+)

### FDD-DSH-040 · Tribo-level roll-up view
**Release:** R2 · **Priority:** P2 · **Persona:** Ana (CTO) · **Owner:** Frontend + Metrics
Aggregate 27 squads into 8 tribos and show tribo-first with expandable squads. Out of MVP scope.

### FDD-DSH-041 · Anomaly detection overlay on small multiples
**Release:** R2 · **Priority:** P2 · **Persona:** Priya · **Owner:** Data Scientist + Frontend
Highlight weeks where value crossed 2σ from 12-week baseline.

### FDD-DSH-042 · Export dashboard snapshot (PNG/PDF)
**Release:** R3 · **Priority:** P3 · **Persona:** Ana · **Owner:** Frontend
For CTO quarterly reviews. Read-only, no external trigger.

---

## Feature Set 6 — 4th DORA Metric (R1)

### FDD-DSH-050 · MTTR / Time to Restore (4ª métrica DORA) — ✅ PHASE 1 SHIPPED 2026-04-29
**Release:** R1 · **Priority:** P1 · **Persona:** Carlos (EM) · Ana (CTO)
**Owner:** Data Engineer + Data Scientist + Backend + Frontend
**Status:** Phase 1 done — see `docs/fdd/FDD-DSH-050-mttr-design.md`. Resolves INC-005.

**Phase 1 entrega (resumo):**
- Migration `013_mttr_incident_pairing` — 3 colunas em `eng_deployments`
  (`recovered_by_deploy_id`, `superseded_by_deploy_id`, `incident_status`) +
  CHECK constraint + 2 partial indexes.
- `services/backfill_mttr.py` — pareia FAILURE → next SUCCESS em
  `(repo, environment='production')` dentro de janela de 7d.
  Classifica `resolved` / `open` / `superseded` (back-to-back). Idempotente.
- Forward-hook em `_sync_deployments` mantém pairing fresh.
- Admin endpoint `POST /data/v1/admin/deployments/refresh-mttr`
  (X-Admin-Token, scope `all` | `stale` | `last-90d`, dry_run).
- `domain/dora.calculate_mttr` ganha flaky filter (≥ 5 min) + sample
  mínimo `n ≥ 5`; `DoraMetrics` expõe `mttr_incident_count` +
  `mttr_open_incident_count`.
- 16 testes unit (mediana, sample guard, flaky, open incidents,
  anti-surveillance source-grep). 183/183 regressão.
- **Live Webmotors:** 255 falhas classificadas em 1,14s → 84 resolved +
  148 superseded + 23 open; após flaky filter: 73 incidentes reais,
  **P50 = 0,50h (Elite)**, P90 = 16,58h.

**Phase 2 deferido (backlog):**
1. Jira "Bug" / "Incident" overlay (depende INC-026/INC-027).
2. GitHub label enrichment (`hotfix`, `revert`, `P0`, `P1`).
3. Webhooks PagerDuty / Opsgenie.
4. Per-team MTTR breakdown (segue FDD-DSH-060).
5. `open_window_days` configurável por team.

**Frontend follow-up pendente:** remover `pendingLabel="R1"` do card,
renderizar P50 + counts (`n=73 resolved, 3 open`). Ver §13 do design doc.

---

**Contexto original (preservado para histórico):**

O dashboard hoje renderiza o card "Time to Restore" como "—" com badge "R1"
e tooltip explicativo. O backend (`/data/v1/metrics/home`) já retorna `time_to_restore`
como `null` de forma explícita (campo existe no schema `HomeMetricCard`). Falta a fonte:
calcular MTTR exige **detectar incidentes** e medir o tempo até a resolução.

**Hipóteses de fonte (a validar com pulse-data-scientist):**
- **Deploys com rollback** — `eng_deployments.source = 'rollback'` OU deploy seguido de
  outro deploy do mesmo repo em <4h com tag `revert`/`hotfix`
- **PRs com label** — `hotfix`, `incident`, `revert`, `P0`, `P1` no título ou labels GitHub
- **Issues Jira** — `priority IN (Highest, Blocker)` com resolução ≠ null
- **Alerta externo** (futuro) — webhook PagerDuty/Opsgenie

**BDD Acceptance Criteria:**
```
Given the backend has ingested incident signals from at least one source
  When the client requests GET /data/v1/metrics/home?period=30d
  Then data.time_to_restore.value is a non-null float in hours
   And data.time_to_restore.level is one of elite | high | medium | low
   And data.time_to_restore.trend_percentage reflects previous-period comparison

Given the dashboard renders with time_to_restore.value populated
  When the user opens the DORA Metrics group
  Then the Time to Restore card shows the numeric value with DORA classification badge
   And the "R1" pending badge is hidden
   And the info tooltip is removed
```

**Classification thresholds (DORA 2023):**
- Elite: `< 1h`
- High: `1h ≤ x < 24h`
- Medium: `24h ≤ x < 168h` (1 semana)
- Low: `≥ 168h`

**Hand-off plan:**
1. `pulse-data-scientist` → define sinal de incidente + fórmula MTTR + validação anti-surveillance
2. `pulse-data-engineer` → cria tabela `eng_incidents` + connector/filter + snapshot worker
3. `pulse-engineer` → endpoint calcula MTTR a partir de `eng_incidents`, remove `pendingLabel="R1"` do frontend
4. `pulse-test-engineer` → testes de fórmula + regressão

**Anti-surveillance check:** PASS — incidentes agregados por time/repo, nunca por autor.
**Dependencies:** FDD-DSH-001 (home endpoint já expõe o campo como `null`).
**Estimate:** L (envolve 4 agentes).
**Analytics events:** `mttr_card_viewed { has_data }`, `mttr_tooltip_hovered`.

---

## Feature Set 7 — Test Coverage (dívida técnica, alta prioridade)

### FDD-DSH-060 · Mapeamento squad → team UUID no backend — RESOLVIDO (2026-04-17)
**Release:** R1 · **Priority:** P1 · **Persona:** Carlos (EM)
**Owner:** Data Engineer + Backend · **Status:** DONE

**Resolução aplicada:** em vez de mapear squad key → team UUID via
`teams.board_config`, optamos por aceitar `squad_key` como query param nativo no
endpoint `/metrics/home` e computar as métricas on-demand via
`compute_home_metrics_on_demand`. Essa rota filtra PRs via regex de título
(mesmo padrão de `/pipeline/teams`), faz join de deploys via repo derivado e
filtra issues por `project_key`. Trade-off: on-demand por request (não há
snapshot pré-calculado por squad × período), mas o volume atual (27 squads,
~600 PRs em 60d) roda em <500ms.

**Deep-dive pages** (`/dora`, `/cycle-time`, `/throughput`, `/lean`) aceitam
`squad_key` como query param mas ainda caem pra tenant-level (documentado em
código — `_ = squad_key  # See FDD-DSH-060`). Próximo passo: estender o
on-demand service para cada tipo de métrica quando o usuário pedir.

**Contexto original:** Hoje o combobox da home usa 27 squad keys dinâmicos
vindos de `/pipeline/teams` (derivados de PR title regex), mas `/metrics/home`
só aceita `team_id: UUID` da tabela `teams`.

**BDD:**
```
Given the user selects squad "okm" in the home combobox
 When the dashboard queries /metrics/home
 Then the response returns KPIs filtered to that squad
  And the client sends squad_key=okm as the query param
  And no UUID translation is needed on the client
```

**Anti-surveillance:** PASS — squad-level, nunca por autor.
**Dependencies:** FDD-DSH-002.
**Estimate:** M.

---

### FDD-DSH-070 · Pirâmide de testes do dashboard (dívida técnica crítica) — ✅ DONE 2026-04-24
**Release:** MVP (retroativo) · **Priority:** P0 · **Persona:** Toda a equipe (quality gate)
**Owner:** Test Engineer (principal) + Frontend + Backend (contract tests)
**Status:** ✅ Shipped — Sprint 1.2 (steps 1-6) + FDD-DSH-070 fechamento (2026-04-24)

**Delivered:**
- ✅ Unit tests (Vitest): `formatDuration` (18), `buildParams` (10) + component tests
- ✅ Component tests (@testing-library/react): `KpiCard`, `ModeSelector`, `ProjectCatalogTable`, `ProjectRowActions`
- ✅ Hook/integration tests (MSW): `useHomeMetrics` incl. 422-regression
- ✅ Contract tests (Zod): 6 endpoints + anti-surveillance meta-test (74 tests)
- ✅ E2E smoke (Playwright): home dashboard journey
- ✅ A11y tests (axe-core): home + DORA + cycle-time, WCAG 2.1 AA gate
- ✅ CI quality gates: 4 jobs root-level, all blocking (gitleaks, lint+tsc, vitest, build)
- ✅ Coverage thresholds: no-regression gate in vitest.config.ts (see playbook §8.10)
- ✅ Retroactive regression tests:
  - `buildParams omits team_id for non-UUID squad keys` (covers DSH-060 fix)
  - `useHomeMetrics never sends team_id for non-UUID — backend returns 422` (covers reported bug)
  - `test_pipeline_fontes_integrity.py` (backend, covers Pipeline Monitor repo-name bug)

Total: 150 Vitest tests + 1 E2E smoke + 3 a11y specs, ~40s CI wall-clock.

See: `pulse/docs/testing-playbook.md` (sections 1-8) for the full strategy.

**Contexto:** O redesign do dashboard (DSH-001..033) foi entregue **sem testes
automatizados**. Dois bugs passaram despercebidos em produção local:
1. Coluna FONTES zerada no Pipeline Monitor (mismatch `split_part` em repo name)
2. Filtro por squad quebra com HTTP 422 (UUID regex não validado no client)

Ambos teriam sido pegos por testes de contrato/integração simples. É um débito
técnico que precisa ser pago **antes** de R1 para não amplificar.

**Escopo:**

1. **Unit tests** (`vitest`) em `pulse/packages/pulse-web/tests/unit/`:
   - `buildParams()` — input UUID preserva; squad key omite; empty omite
   - `transformHomeMetrics()` — null fields viram `HomeMetricItem` com `value=null`
   - `classifyMetric()` — thresholds DORA 2023 + heurísticas Flow
   - `formatValue()` em `KpiCard` — null/NaN/Infinity → "—"

2. **Component tests** (`@testing-library/react`):
   - `KpiCard` com `value=null` renderiza "—" + pendingLabel + tooltip
   - `TeamCombobox` — busca filtra, agrupa por tribo, anti-surveillance (sem autor)
   - `FreshnessBanner` — exibe quando health ≠ healthy, oculta em healthy
   - `TeamRankingSection` — troca métrica via tab sincroniza estado
   - `TeamDetailDrawer` — Esc fecha, trap-focus, a11y

3. **Hook/integration tests** (MSW):
   - `useHomeMetrics` com `teamId='okm'` não envia `team_id` na query
   - `usePipelineTeamsList` retorna 27 squads ordenados por tribo
   - `useMetricsByTeam` fallback pro derive quando endpoint 404

4. **Contract tests** (Zod):
   - Schema Zod por endpoint (`/metrics/home`, `/pipeline/teams`, `/pipeline/health`)
   - Falha o build se shape do backend mudar sem atualizar o schema

5. **E2E tests** (Playwright) em `pulse/e2e/dashboard.spec.ts`:
   - "Home → selecionar squad → dashboard carrega sem erro 422"
   - "Trocar período 30→60→90→120d atualiza KPIs"
   - "Custom date range inválido mostra erro inline"
   - "Clicar em bar do ranking abre drawer; Esc fecha; foco volta"
   - "Troca de tab métrica sincroniza com seção de evolução"

6. **A11y tests** (`@axe-core/playwright`):
   - Zero violations `serious` ou `critical` na home
   - Focus order segue ordem visual
   - Reduced motion respeitado

7. **CI quality gates** em `pulse/.github/workflows/`:
   - `npm run test` bloqueia merge se coverage dashboard <80%
   - `npm run e2e` bloqueia merge se E2E falhar
   - `npm run lint:a11y` bloqueia violações sérias

**BDD macro:**
```
Given a PR modifies any file inside src/components/dashboard/ or src/routes/_dashboard/home.tsx
 When CI runs
 Then unit + component + integration tests execute in <60s
  And E2E tests execute in <3min
  And coverage report is posted as PR comment
  And merge is blocked if any gate fails

Given the backend changes the shape of /metrics/home
 When the frontend build runs
 Then the Zod contract test fails at compile/CI time
  And a clear diff is shown between expected and actual shape
```

**Testes retroativos dos bugs já caçados (prioridade máxima):**
- `test('buildParams omits team_id for non-UUID squad key', ...)` — cobre DSH-060 fix
- `test('home renders without 422 when squad is selected', ...)` — cobre o bug reportado
- `test('deploy count per team uses normalized repo format', ...)` — cobre bug do Pipeline Monitor

**Anti-surveillance check:** PASS.
**Dependencies:** FDD-DSH-001..033 (código testável já existe).
**Estimate:** L (4–6h test engineer dedicado).
**Analytics:** `test_suite_failed { suite, reason }` (monitorar flakiness).

**Risco de não fazer:** cada novo bug custa mais — cascata de regressões, refactors
bloqueados por medo de quebrar algo, CI torna-se decorativo. O backlog tem **27
squads × 6 métricas = 162 combinações de dados**; sem contrato de teste é questão de
tempo até a próxima 422 em produção.

---

### FDD-DSH-080 · Filtros globais no TopBar — DONE (2026-04-17)
**Release:** MVP · **Priority:** P0 · **Persona:** Carlos, Ana, Priya
**Owner:** Frontend (`pulse-engineer`) · **Status:** DONE

**Contexto:** os filtros Squad + Período existiam apenas no `home.tsx`. Ao
navegar para `/dora`, `/cycle-time`, `/throughput`, `/lean`, `/sprints`, `/prs`
o usuário não conseguia re-aplicar o mesmo escopo — o `TopBar.tsx` original
tinha apenas um select "All Teams" vazio e um select de período com só 3 opções.

**Resolução:** `TopBar.tsx` agora hospeda `TeamCombobox` + `PeriodSegmented` +
`DateRangeFilter` + botão Limpar. Todas as rotas `/_dashboard/*` reagem aos
filtros via `useFilterStore`. Rotas exemptas (real-time ou catálogo) escondem
a barra: `/pipeline-monitor`, `/settings/integrations*`, `/integrations`.
`home.tsx` removeu as ~25 linhas de filter bar duplicada, mantendo apenas o
chip "Exibindo … · últimos 60 dias" como feedback do escopo aplicado.

**Anti-surveillance:** PASS.

---

### FDD-DSH-081 · Custom date range (period=custom) — DONE (2026-04-17)
**Release:** MVP · **Priority:** P0 · **Persona:** Carlos, Priya
**Owner:** Backend (`pulse-engineer`) · **Status:** DONE

**Bug original:** frontend enviava `?period=custom&start_date=…&end_date=…`,
backend validava `period ∈ {7d,14d,30d,60d,90d,120d}` e respondia HTTP 400.

**Resolução:**
- `"custom"` adicionado a `_VALID_PERIODS`.
- `_parse_period(period, start_date, end_date)` aceita `custom` com validações:
  ambas as datas obrigatórias, ISO válido, `start < end`, duração ≤ 365 dias.
- Endpoints `/home`, `/dora`, `/lean`, `/cycle-time`, `/throughput`, `/sprints`
  agora aceitam `start_date` e `end_date` opcionais.
- `/home` computa on-demand via `compute_home_metrics_on_demand` quando
  `period=custom` (não há snapshot pré-calculado pra janela arbitrária).
- Deep-dive pages usam o snapshot de melhor aproximação (documentado).

**UI:** `DateRangeFilter` já validava `start < end` e `max 365 dias` antes de
chamar API. `buildParams()` só envia `start_date`/`end_date` quando
`period=custom` e ambas as datas presentes.

**Anti-surveillance:** PASS.

---

### FDD-DSH-082 · Lead Time strict vs inclusive — DONE (2026-04-17)
**Release:** MVP · **Priority:** P0 · **Persona:** Carlos, Priya
**Owner:** Backend + Frontend (`pulse-engineer`) · **Status:** DONE

**Bug diagnosticado** (pelo `pulse-data-scientist`, 2026-04-17): Lead Time DORA
calculava `COALESCE(deployed_at, merged_at) − first_commit_at`. Em squads com
cobertura parcial de deploy (ex.: OKM tem 50%), o fallback colapsa o Lead
Time sobre o Cycle Time e produz uma mediana enganosa.

Evidência (OKM 60d): Cycle Time P50 = 1,20h · Lead Time inclusive (155 PRs)
= 119,65h · Lead Time **strict** (78 PRs com deploy) = 404,69h.

**Resolução:**
- Nova função pura `calculate_lead_time_strict(prs)` em `domain/dora.py` que
  exige `deployed_at` real, com guarda-corpo `_LT_STRICT_MIN_SAMPLE = 5`
  (retorna `None` quando há menos de 5 PRs elegíveis).
- `DoraMetrics` ganhou campos `lead_time_for_changes_hours_strict`,
  `lead_time_strict_eligible_count`, `lead_time_strict_total_count`,
  `lt_strict_level` (com defaults — não quebra call sites antigos).
- `HomeMetricsData` ganhou `lead_time_strict: HomeMetricCard` e
  `LeadTimeCoverage { covered, total, pct }` exposto como `coverage` no card.
- `lead_time` (inclusive) **mantido** para back-compat com clientes legados.
- Frontend: card "Lead Time" no grupo DORA agora consome `leadTimeStrict`;
  tooltip mostra cobertura ("78 de 155 PRs (50% têm deploy linkado)") e,
  quando `value=null`, exibe orientação ("Aumente o período / aguarde mais
  ingestão"). Inclusive ainda disponível em `homeMetrics.leadTimeForChanges`
  para futuros drawers/comparações.
- Recálculo automático: `recalculate.py` e `home_on_demand.py` chamam
  `calculate_dora_metrics` que agora popula os novos campos via `asdict()`.
  Snapshots novos terão os campos; snapshots antigos retornam `None`
  graciosamente (frontend trata).

**Testes:** 6 novos casos em `tests/unit/test_dora.py::TestLeadTimeStrict`
cobrindo lista vazia, sample <5, exclusão de PRs sem deploy, mediana correta,
divergência inclusive vs strict (cenário OKM), e delta negativo (clock skew).
63/63 testes DORA passam.

**Anti-surveillance:** PASS — agregado por squad/tenant, sem dados de autor.

---

### FDD-DSH-083 · Tooltips explicativos em todos os 8 KPI cards — DONE (2026-04-17)
**Release:** MVP · **Priority:** P1 · **Persona:** todos
**Owner:** Frontend (`pulse-engineer`) · **Status:** DONE

**Problema:** usuários novos não sabem como cada métrica é calculada nem
quais dados a alimentam. O ícone `ⓘ` introduzido no MTTR (FDD-DSH-050)
ficou solitário; precisa cobrir todos os cards.

**Resolução:**
- Novo componente `<InfoTooltip>` em `components/dashboard/InfoTooltip.tsx`
  — popover acessível (focus + hover + tap-to-toggle, `role="tooltip"`,
  `aria-describedby`, `aria-label` na trigger), suporta multi-linha
  (`whitespace-pre-line`), `max-width 320px`, sombra+border via tokens.
  **Sem nova dependência** — descartado Radix Tooltip pra manter o bundle
  enxuto; revisitar quando outros componentes precisarem de popover.
- `KpiCard` migrado: prop `infoTooltip` agora delega ao `InfoTooltip`
  (substitui o antigo `title` HTML nativo, que não permitia multi-linha).
- 8 tooltips adicionados em `routes/_dashboard/home.tsx`, formato
  consistente: linha 1 = descrição, depois Fórmula, Dados, e (DORA)
  classificação. Lead Time tem cobertura dinâmica injetada.
- Tooltip do card MTTR ("Time to Restore") atualizado pra incluir fórmula
  + status R1 + classificação DORA (mantém o `pendingLabel="R1"`).

**Acessibilidade:**
- Trigger é `<button>` reachable por Tab.
- `aria-describedby` aponta pro id da bubble; bubble usa `hidden` quando
  fechado pra não poluir leitura sequencial.
- `focus-visible:ring-2` segue o anel global.

**Constraints atendidas:**
- PT-BR, sem emoji.
- Tokens-only (`bg-surface-primary`, `text-content-secondary`, etc.).
- Build do `pulse-web`: nenhum erro novo introduzido (erros pré-existentes
  em `jira.audit.tsx` e `project-catalog-table.tsx` ficam fora deste PR).

**Próximo nice-to-have:** "Exemplo dinâmico" — puxar valor atual da
métrica pro tooltip ("Último cálculo: 5,95/dia = Elite"). Hoje tooltip
é estático. Endereçar quando valor de exemplo trouxer ROI claro.

---

### FDD-DSH-084 · Normalização de unidades horas/dias nos cards de tempo
**Release:** MVP · **Priority:** P1 · **Persona:** Carlos (EM), Ana (CTO)
**Owner:** Frontend (`pulse-engineer`)
**Status:** ✅ DONE — 2026-04-17

**Contexto:** Cards de tempo (Lead Time, Cycle Time P50/P85, Time to Restore)
exibiam valores em horas mesmo quando a magnitude pedia dias (ex: `404,7h` em
vez de `16,9 dias`). Carlos fazia aritmética mental pra comparar durações
percebidas; leitura de KPI de 2 segundos ficava comprometida.

**Implementado (validado pelo pulse-ux-reviewer antes do código):**
- Helper `formatDuration(hours)` com 3 thresholds:
  - `< 1h` → `"Xmin"` + secondary `"(0,75h)"`
  - `1h ≤ v < 24h` → `"X,Xh"` (sem secondary — redundante)
  - `≥ 24h` → `"X,X dias"` + secondary `"(404,7h)"`
- Props opcionais `valueSecondary`, `coveragePct`, `extraNote` no `KpiCard`
- Card Lead Time restruturado (ordem: DORA strict → cobertura → inclusive)
- Responsivo mobile (<640px): esconde secondary, primary 24→20px
- Cards não-tempo (DF, CFR, WIP, Throughput) mantêm unidades nativas
- 18 testes unitários em `formatDuration.test.ts` (55/55 passando)

**Anti-pattern evitado:** primary e secondary nunca na mesma linha.
**Benchmarks:** Vercel, Datadog APM, Linear.

---

## Delivery Sequence Summary

1. **Sprint 1 (MVP foundation):** DSH-001, DSH-002, DSH-003, DSH-004
2. **Sprint 2 (Rankings):** DSH-010, DSH-011, DSH-012
3. **Sprint 3 (Evolution):** DSH-020, DSH-021
4. **Sprint 4 (States & Polish):** DSH-030, DSH-031, DSH-032, DSH-033, DSH-082, DSH-083, DSH-084
5. **Sprint 5 (Quality — CRÍTICO):** DSH-070 (test pyramid + CI gate)
6. **R1 iteration:** DSH-050 (MTTR), DSH-060 (squad→team UUID)
7. **R2+ iteration:** DSH-040, DSH-041, DSH-042

---

### FDD-DSH-091 · Capability-aware UI (hide sprint/kanban sections per tenant)
**Epic:** Dashboard Redesign · **Release:** MVP · **Priority:** P1
**Persona:** Ana (CTO), Carlos (EM)
**Owner class:** Full-stack (`pulse-engineer`)

**Status:** Phase 1 delivered (2026-04-17). Phase 2 (squad-level) delivered (2026-04-17) — DONE.

**Motivation:**
A Webmotors opera em fluxo contínuo e historicamente não ingeria sprints, porém
a UI exibia a aba `/metrics/sprints` vazia e cards sprint-dependentes zerados.
O guard condiciona exibição via *capability flag* persistida por tenant, sem
remover código — apenas esconde quando o tenant não usa sprint / kanban.

**Acceptance (BDD):**
```
Given um tenant cujo backend retorna has_sprints=false
 When o usuário acessa o dashboard
 Then o item "Sprints" não aparece no menu lateral
  And a rota /metrics/sprints mostra empty state com CTA para /metrics/lean
  And nenhum card sprint-específico é renderizado na Home

Given um tenant cujo backend retorna has_kanban=false (futuro R2+)
 When o usuário acessa o dashboard
 Then cards dependentes de kanban (Aging WIP, Flow Efficiency) não aparecem

Given o endpoint /tenant/capabilities está lento ou indisponível
 When a sidebar é renderizada
 Then TODOS os itens permanecem visíveis (fail-open, zero flicker)
```

**Phase 1 scope (delivered):**
- Endpoint `GET /data/v1/tenant/capabilities` (Redis cache 5min)
- Heurística: has_sprints = `COUNT(eng_sprints.started_at >= now() - 180d) >= 3`
- Heurística: has_kanban = `COUNT(eng_issues in in_progress/in_review) >= 10`
- Hook `useTenantCapabilities` + componente `CapabilityGuard`
- Sidebar esconde item "Sprints" quando `hasSprints=false`
- Rota `/metrics/sprints` com empty state em PT-BR

**Phase 2 scope (delivered 2026-04-17):**
- Endpoint `GET /data/v1/tenant/capabilities?squad_key=<KEY>` retorna flags
  escopadas por squad (Jira project key). Sem `squad_key` → comportamento
  tenant-wide (backward-compat).
- Heurística primária: join `eng_issues (issue_key prefix = squad_key) →
  eng_sprints (via external_id)` com janela de 180d. Exemplo real Webmotors:
  FID → 14 sprints / board 549; PTURB → 6 sprints / board 872; BG/OKM/SECOM → 0.
- Heurística fallback (apenas quando a primária retorna 0): `LOWER(sprint.name)
  ILIKE '%<token>%'` com aliases hand-tuned (FID→fidelidade, PTURB→motor vn).
  Ainda gate pelo `SPRINT_THRESHOLD`.
- Fail-open: squad_key inválido ou query quebrada → retorna tenant-wide /
  `has_sprints=false` (conservador).
- Cache Redis separado: chave `tenant:capabilities:squad:<tid>:<KEY>`, TTL 5min.
- Regex gate para squad_key (evita injection: `[A-Z][A-Z0-9]{1,31}`).
- Hook `useTenantCapabilities(squadKey?)` com cache key por-squad.
- `CapabilityGuard` aceita prop `squadKey?`.
- Rota `/metrics/sprints` lê `teamId` do `filterStore`, consulta capability
  squad-específica e mostra empty state dedicado: *"A squad <Nome> trabalha
  com fluxo contínuo."*
- Sidebar **mantém** comportamento tenant-wide (não esconde "Sprints" por
  squad — selecionar "Todas as squads" ainda precisa do item visível).

**Phase 3 backlog (pendente):**
- Aplicar guard em cards sprint-específicos na Home (quando "Scope Creep" for
  adicionado — ver INC-006), passando `squadKey={activeSquadKey}`.
- Aplicar guard simétrico em cards kanban-específicos (Aging WIP, Flow
  Efficiency) quando forem construídos.
- Telemetria: instrumentar quantos tenants/squads caem em cada combinação.
- Thresholds configuráveis via tabela `tenant_settings`.
- Endpoint admin para forçar `has_sprints=false` (override manual).
- Mapeamento squad→board persistido (hoje derivado on-the-fly).

**Files:**
- `packages/pulse-data/src/contexts/tenant/{routes,service,schemas}.py`
- `packages/pulse-web/src/hooks/useTenantCapabilities.ts`
- `packages/pulse-web/src/components/CapabilityGuard.tsx`
- `packages/pulse-web/src/types/tenant.ts`
- `packages/pulse-web/src/routes/_dashboard/metrics/sprints.tsx`

**Tests:** 18 unit tests (pure heuristics + compute path with mocked DB +
squad_key normalizer / injection guard).
