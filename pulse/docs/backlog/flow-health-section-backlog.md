# Flow Health Section — FDD Backlog

**Referência:** impl spec em `pulse/docs/ux-specs/flow-health-section-impl-spec.md`.
**Hand-off:** cards endereçados a `pulse-engineer` (frontend), `pulse-data-engineer` (dados), `pulse-test-engineer` (QA), `pulse-ciso` (anti-surveillance).
**Release:** MVP (cards F-01 a F-06) · R1 (F-07, F-08) · R2 (F-09).
**Ordem de entrega:** F-01 → F-02 → F-03 → F-04 → F-05 → F-06 → (F-07, F-08 em R1).

---

## F-01 · Render Flow Health section shell on home

**Feature:** Display the Flow Health section container between KPI groups and Team Rankings on the dashboard home.

- **Epic:** Kanban-native Metrics MVP
- **Release:** MVP
- **Persona:** Priya (primary), Carlos (secondary)
- **Priority:** P0
- **Owner class:** Frontend (`pulse-engineer`)

**Acceptance criteria (BDD):**
```
Given the user is on /dashboard
When  the page loads with any filter context
Then  a section titled "Flow Health" appears between KPI groups and "Comparativo por squad"
And   the section contains two cards ("Aging WIP", "Flow Efficiency")
And   the section height stays between 500px and 600px at ≥ 1280px viewport
And   on viewports < 1100px the cards stack vertically

Given reduced motion is enabled (prefers-reduced-motion)
When  the section renders
Then  no skeleton shimmer animation plays
```

- **Anti-surveillance check:** Pass — chrome only, no identity fields.
- **Dependencies:** none
- **Estimate:** S
- **Analytics events:** `flow_health_viewed`

---

## F-02 · Implement Aging WIP card with outlier-first top-8 table

**Feature:** Display top 8 at_risk items ranked by age in a scannable table inside the Aging WIP card.

- **Epic:** Kanban-native Metrics MVP
- **Release:** MVP
- **Persona:** Priya
- **Priority:** P0
- **Owner class:** Frontend (`pulse-engineer`), API (`pulse-engineer` backend), Metrics (`pulse-data-scientist` — formula already validated in FDD-KB-003)

**Acceptance criteria (BDD):**
```
Given aging_wip data is available
When  the card renders
Then  the subtitle shows "{count} itens em progresso · P50 {p50}d · P85 {p85}d"
And   a table displays the top 8 items sorted by age_days desc
And   each row shows: issue_key (mono), squad_key, status (dot + label), relative age bar, age in days
And   the assignee field is NEVER rendered nor present in the fetched payload
And   clicking a row opens the drawer

Given at_risk_count > 0
When  the card renders
Then  a danger-tone callout strip displays "{count} itens em risco (idade > {threshold}, 2× P85 histórico 90d)"
And   the callout has a "Ver lista →" CTA that opens the drawer

Given at_risk_count === 0
When  the card renders
Then  the callout is hidden
And   the table shows top 8 items with warn-tone (not danger)

Given the endpoint returns 5xx or times out
When  the card attempts to render
Then  an error state with a retry button replaces the viewport
And   the card header remains visible
```

- **Anti-surveillance check:** Pass — confirmar com `pulse-ciso` que backend response do endpoint `GET /metrics/kanban/aging-wip` **não contém `assignee`**.
- **Dependencies:** FDD-KB-003 (backend API), F-01
- **Estimate:** M
- **Analytics events:** `flow_health_viewed`, `aging_wip_item_clicked`, `flow_health_error`, `flow_health_retry_clicked`

---

## F-03 · Implement Flow Efficiency card with gauge + inline v1 disclaimer

**Feature:** Display Flow Efficiency as a ring gauge with explicit v1-simplified disclaimer.

- **Epic:** Kanban-native Metrics MVP
- **Release:** MVP
- **Persona:** Priya, Ana, Carlos
- **Priority:** P0
- **Owner class:** Frontend (`pulse-engineer`), Metrics (`pulse-data-scientist`)

**Acceptance criteria (BDD):**
```
Given flow_efficiency data is available and insufficient_data === false
When  the card renders
Then  the value is shown as a percentage (0–100%) above the gauge
And   the trend "{±X}pp vs 60d anteriores" is shown with up/down arrow
And   a ring gauge fills proportionally to the value
And   the inline disclaimer is ALWAYS visible (never tooltip-only) and reads
      "Métrica v1 simplificada. Estados 'Aguardando' contam como trabalho ativo.
       Refinamento com mapeamento de status por squad em R2."
And   the badge "v1" appears in the card header

Given insufficient_data === true (sample_size < 30)
When  the card renders
Then  the value shows "—"
And   the trend shows "dados insuficientes"
And   the stats row shows the actual sample_size
And   analytics event fe_insufficient_data_shown is emitted

Given hover dwell ≥ 500ms on the disclaimer
Then  fe_disclaimer_hovered is emitted with dwell_ms
```

- **Anti-surveillance check:** Pass — métrica agregada, nenhum author-level.
- **Dependencies:** FDD-KB-004 (backend API), F-01
- **Estimate:** M
- **Analytics events:** `fe_disclaimer_hovered`, `fe_insufficient_data_shown`

---

## F-04 · Implement shared drawer with full at_risk list + filters

**Feature:** Open a non-modal drawer showing the complete list of at_risk items with search and squad/status filters.

- **Epic:** Kanban-native Metrics MVP
- **Release:** MVP
- **Persona:** Priya
- **Priority:** P1
- **Owner class:** Frontend (`pulse-engineer`)

**Acceptance criteria (BDD):**
```
Given at_risk_count > 0
When  the user clicks the callout "Ver lista →" CTA
Then  a 520px right-side drawer opens
And   the drawer focus traps to its close button first
And   the Escape key closes the drawer
And   the drawer shows issue_key, squad_key, status, age_days (sorted desc)
And   the drawer provides: search input, squad select, status select
And   at counts > 100 items, rows are virtualised (react-window)
And   the assignee field is NEVER rendered

Given the drawer is open
When  the user types in search
Then  the list filters on issue_key OR squad_key (case-insensitive)

Given the drawer is open
When  the user clicks the close button or presses Esc
Then  the drawer closes
And   focus returns to the element that opened the drawer
```

- **Anti-surveillance check:** Pass.
- **Dependencies:** F-02
- **Estimate:** M
- **Analytics events:** `aging_wip_drawer_opened`

---

## F-05 · Implement loading, empty, partial and error states

**Feature:** Render the six required states consistently across Aging WIP and Flow Efficiency cards.

- **Epic:** Kanban-native Metrics MVP
- **Release:** MVP
- **Persona:** all
- **Priority:** P1
- **Owner class:** Frontend (`pulse-engineer`), Test (`pulse-test-engineer`)

**Acceptance criteria (BDD):**
```
Given the fetch is in flight
When  the card renders
Then  skeleton rows replace the viewport (6 rows, 14px height)
And   the gauge shows an empty arc
And   no layout shift occurs when data arrives

Given aging_wip.count === 0 AND fe.insufficient_data === true
When  the card renders
Then  an empty-state hero appears with "Nenhum item em progresso no momento."
And   the gauge shows "—"
And   no zeros are rendered in place of real values

Given fe.insufficient_data === true but aging_wip.count > 0
When  the section renders
Then  only the FE card shows partial state; Aging WIP renders healthy state

Given the API returns 5xx
When  the card attempts to render
Then  an error-state replaces the viewport with a retry button
And   the card header chrome is preserved
```

- **Anti-surveillance check:** Pass.
- **Dependencies:** F-02, F-03
- **Estimate:** S
- **Analytics events:** `flow_health_empty_shown`, `flow_health_error`, `flow_health_retry_clicked`, `fe_insufficient_data_shown`

---

## F-06 · Responsive + a11y audit

**Feature:** Ensure the section passes axe-core (zero critical), works on 375px–2560px, and respects reduced-motion.

- **Epic:** Kanban-native Metrics MVP
- **Release:** MVP
- **Persona:** all
- **Priority:** P1
- **Owner class:** Test (`pulse-test-engineer`)

**Acceptance criteria (BDD):**
```
Given the Flow Health section is rendered
When  axe-core runs against the page
Then  zero critical or serious violations are reported

Given viewport width is 375px
When  the section renders
Then  cards stack vertically
And   the outlier table hides the progress-bar column
And   the drawer opens full-screen
And   all interactive elements are reachable via keyboard in logical order

Given prefers-reduced-motion: reduce
When  any transition/animation would occur
Then  motion is disabled (drawer open, skeleton shimmer, hover transitions)

Given a screen reader navigates the callout
When  the at_risk count changes (filter applied)
Then  the new value is announced via role="status"
```

- **Anti-surveillance check:** Pass.
- **Dependencies:** F-01–F-05
- **Estimate:** S
- **Analytics events:** —

---

## F-07 · [R1] Add toggle "item | squad" on Aging WIP card (pre-dev adjustment #1)

**Feature:** Let Priya switch the Aging WIP table between item-level and squad-level aggregation.

- **Epic:** Kanban-native Metrics Refinement
- **Release:** R1
- **Persona:** Priya
- **Priority:** P1
- **Owner class:** Frontend (`pulse-engineer`), API (`pulse-engineer`)

**Acceptance criteria (BDD):**
```
Given the Aging WIP card is rendered
When  the user clicks the "squad" option in the segmented toggle
Then  the table switches to rows per squad
And   columns become: squad_key, WIP total, at_risk count, % in risk, P85 of squad
And   rows are sorted by at_risk count desc
And   clicking a squad row opens the drawer filtered by that squad

Given the toggle is set to "squad"
When  the user reloads the page
Then  the previous choice is persisted in the filter store
```

- **Anti-surveillance check:** Pass — squad aggregation only.
- **Dependencies:** F-02; new API parameter `?group_by=squad`
- **Estimate:** M
- **Analytics events:** `aging_wip_toggle_grouping`

---

## F-08 · [R1] Add sparkline of at_risk trend in danger callout (pre-dev adjustment #2)

**Feature:** Display a 30-day sparkline of at_risk_count to the right of the callout text.

- **Epic:** Kanban-native Metrics Refinement
- **Release:** R1
- **Persona:** Priya, Carlos
- **Priority:** P1
- **Owner class:** Frontend (`pulse-engineer`), Data (`pulse-data-engineer`)

**Acceptance criteria (BDD):**
```
Given at_risk_count > 0 AND the API returns at_risk_trend_30d series
When  the callout renders
Then  a 60×16 sparkline displays inline to the right of the CTA
And   the sparkline uses --color-danger stroke with no fill
And   hovering the sparkline shows a tooltip "há Xd: {count} itens"

Given at_risk_trend_30d is missing
When  the callout renders
Then  the callout renders without the sparkline (graceful degradation)
```

- **Anti-surveillance check:** Pass.
- **Dependencies:** New endpoint field `at_risk_trend_30d: number[]`
- **Estimate:** S
- **Analytics events:** —

---

## F-09 · [R2] Refine FE formula with per-squad status mapping

**Feature:** Replace v1_simplified FE with per-squad status-category mapping to separate "Aguardando" from active work.

- **Epic:** Kanban-native Metrics v2
- **Release:** R2
- **Persona:** Priya, Ana
- **Priority:** P1
- **Owner class:** Metrics (`pulse-data-scientist`), Data (`pulse-data-engineer`), API (`pulse-engineer`), Frontend (`pulse-engineer`)

**Acceptance criteria (BDD):**
```
Given a tenant has configured status mapping per squad
When  the FE endpoint is called
Then  it returns formula_version = "v2_status_mapped"
And   the FE card replaces the "v1" badge with "v2" (neutral tone)
And   the disclaimer adapts to "Métrica refinada com mapeamento por squad."
And   the classification field returns Elite/High/Medium/Low with threshold

Given no status mapping is configured
When  the FE endpoint is called
Then  it still returns v1_simplified (backward compat)
```

- **Anti-surveillance check:** Pass.
- **Dependencies:** Status mapping admin UI (separate epic)
- **Estimate:** L
- **Analytics events:** `fe_version_served` (payload: `v1_simplified | v2_status_mapped`)

---

## Summary of delivery order

| Sprint | Cards | Deliverable |
|---|---|---|
| Sprint N (MVP) | F-01 → F-02 → F-03 | Section + both cards live with top-8 table and FE gauge |
| Sprint N (MVP) | F-04 → F-05 → F-06 | Drawer, all states, a11y sign-off |
| Sprint N+1 (R1) | F-07, F-08 | Item/squad toggle + at_risk sparkline |
| Sprint N+3 (R2) | F-09 | FE v2 with per-squad status mapping |
