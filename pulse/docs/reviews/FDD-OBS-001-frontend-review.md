# FDD-OBS-001 (PULSE Signals) — Frontend Review

**Reviewer:** pulse-frontend (Senior Product Design Engineer)
**Date:** 2026-05-11
**Scope:** 3 prototype pages shipped in PR 3, 3.5, 4b — Service Ownership Map,
Team Aliases, Deploy Health Timeline.
**Verdict (TL;DR):** Prototype is good enough to demo internally, **not** good
enough to put in front of a paying tenant. There is a hard production gap (zero
React code in `pulse-web/`), the timeline chart breaks anti-surveillance
neutrality on accessibility (color-only severity), and three blocking states are
missing. Detail below.

Severity legend:
- P0 — Must fix before any user sees this
- P1 — Should fix before R1
- P2 — Could be improved later
- DONE — Already good

---

## A) The production gap (most important)

**Hard fact:** none of the three pages exists in `pulse/packages/pulse-web/`.
A `grep "observability|FDD-OBS"` against the full `pulse-web/src/` tree
returns **zero hits**. The sidebar in
`pulse/packages/pulse-web/src/components/layout/Sidebar.tsx:27-38` does not
mention an Observability entry. There is no client in
`pulse/packages/pulse-web/src/lib/api/` for the obs/timeline or
admin/integrations/datadog endpoints.

The pages are working only in the static prototype on port 8080. A real Carlos
or Bruno who logs into `pulse-web` today sees nothing.

### Inventory of work to port each page

The pulse-web design system today (from inspection):
- `apiClient` (NestJS) + `dataClient` (FastAPI) in `src/lib/api/client.ts`
- TanStack Router (file-based, see `src/routes/_dashboard/`)
- TanStack Query (see `useJiraAdmin`, `useMetrics` hooks)
- Tailwind tokens (`bg-surface-primary`, `text-content-primary`, etc.) — same
  semantic names as `tokens.css` but in Tailwind form
- Shared components already available: `KpiCard`, `KpiGroup`,
  `DateRangeFilter`, `TeamCombobox`, `InfoTooltip`, `FreshnessBanner`,
  `MetricCard` (chart), `EntityDrawer`
- Jira Settings has a tab-bar pattern at
  `src/routes/_dashboard/settings/integrations/jira.tsx:50-73` that is the
  template to clone for the Observability settings shell
- No table primitive yet — Jira catalog uses a hand-rolled `<table>` in
  `_components/project-catalog-table` — reusable for our ownership table
- No modal primitive yet — Jira has confirm dialogs but no generic `<Modal>`
- No chart primitive yet (only `MetricCard` wraps Chart.js); the timeline
  needs a fresh component

#### Page 1 — Service Ownership Map (PR 3)
| Item | Reuse from pulse-web | New work |
|------|----------------------|----------|
| Route shell | `jira.tsx` tab layout (copy/paste) | `settings/integrations/observability.tsx` (parent) + `.ownership.tsx` (tab) |
| Page header + breadcrumb | Jira pattern | — |
| KPI banner (4 KPIs + action) | `KpiGroup` + `KpiCard` | None |
| Filter input | None (inline `<input>`) | New `SearchInput` primitive (could become a DS component) |
| Table | Pattern from `project-catalog-table` | `OwnershipTable.tsx` + row component |
| Status badges | Tailwind utilities; semantic via `text-status-*` | `OwnershipBadge.tsx` (qualified/warn/danger/neutral) |
| Override modal | None (no shared `Modal`) | First reusable `Modal` primitive (P1 — needed by aliases too) |
| Data layer | New `lib/api/observability.ts` calling `dataClient` for GETs, `apiClient` for PUT override | New hook `useOwnership()` + `useOverrideMutation()` |
| Loading state | `ConnectionCardSkeleton` pattern | Adapt for table rows |
| Error state | `IntegrationsPage` error block | Same |

LoC estimate: ~650 LoC TSX (route 80, table 220, modal 120, badges 60, hook 80, api 90) — **~12-14 hours** including a11y polish and tests.

#### Page 2 — Team Aliases (PR 3.5)
| Item | Reuse | New |
|------|-------|-----|
| Tab in observability shell | shared layout | `.aliases.tsx` tab |
| Suggestions banner | None — but pattern matches `SmartSuggestionsBanner` from jira | `AliasSuggestionsBanner.tsx` |
| 2-column layout | Tailwind grid utilities | None |
| Aliases table | Same `Table` as ownership | `AliasesTable.tsx` |
| Bulk-paste textarea + result | None | `BulkPasteCard.tsx` |
| Edit modal | The `Modal` shipped with page 1 | `AliasEditModal.tsx` |
| Delete confirm | `confirm()` works but bad UX — needs `ConfirmDialog` primitive | New `ConfirmDialog` (could be just `Modal` variant) |
| Data layer | `lib/api/observability.ts` (extends file from page 1) | New endpoints + hooks |

LoC estimate: ~480 LoC, **~8-10 hours**.

#### Page 3 — Deploy Health Timeline (PR 4b)
| Item | Reuse | New |
|------|-------|-----|
| Route | _dashboard/observability/timeline.tsx | — |
| Filter bar (squad/window/refresh) | `TeamCombobox`, `PeriodSegmented` (existing!) | None — both already exist |
| KPI banner | `KpiGroup` | None |
| **Timeline chart** | None — `MetricCard` only wraps Chart.js bar/line | `DeployHealthTimelineChart.tsx` — see §C for the call: rewrite the SVG to Chart.js or keep it bespoke (recommended: rewrite, see §C P0) |
| Deploys table | Existing `Table` from page 1 | `DeploysTable.tsx` |
| Tooltip | New helper or use Chart.js built-in if we go with Chart.js | — |
| Data layer | `lib/api/observability.ts` (extends from pages 1-2) | `useTimeline(squad, windowHours)` hook with TanStack Query keyed correctly so window switching works |

LoC estimate: ~750 LoC (chart is the bulk), **~18-22 hours** including making the chart accessible and tooltip-perfect.

**Total: ~1,900 LoC, ~38-46 engineer-hours.**

### One PR or three?

**Three PRs**, sequenced exactly as the prototype was shipped:

1. **PR A — Observability shell + Service Ownership** (foundation: tab layout, `Modal` primitive, `observability.ts` api client). Blocks everything else. ~14h.
2. **PR B — Team Aliases** (adds on PR A, mostly UI work, no new primitives if PR A landed Modal+Table well). ~9h.
3. **PR C — Deploy Health Timeline** (lives in `/observability/timeline`, separate IA from settings; can ship in parallel with PR B but the chart deserves its own review). ~20h.

One mega-PR would be 2k+ LoC of review surface, three modal/table primitives landing together, and there is too much risk of one bug holding the whole thing up. The Carlos persona is the eventual money page; do not couple it to the Bruno admin pages.

---

## B) Prototype quality

### B.1 WCAG AA compliance

| Check | Ownership | Aliases | Timeline |
|---|---|---|---|
| `lang` attribute | DONE (`pt-BR`) | DONE | DONE |
| Semantic landmarks (`<main>`, `<nav>`, `<header>`) | DONE | DONE | DONE |
| Form labels | DONE | DONE | DONE |
| Focus rings (`:focus-visible`) | DONE (tokens.css line 87) | DONE | DONE |
| `aria-modal`, `role="dialog"` | DONE on modal | DONE on modal | n/a |
| Modal focus trap | **P0 missing** — Escape closes (good), but Tab can escape the modal into the page behind it. `_openModal()` in `app.js:259` only does `select.focus()`. No `inert` on `<main>` and no focus-loop trap. | Same P0 missing | n/a |
| Initial focus on modal open | DONE (`select.focus()`) | DONE | n/a |
| Return focus after modal close | **P1 missing** — when modal closes, focus is lost (jumps to `<body>`). Should return to the button that opened the modal. | Same P1 | n/a |
| Color contrast (4.5:1) | DONE — text-primary `#111827` on bg-surface `#FFF` ≈ 16:1; badges all use accessible bg/fg pairs from tokens | DONE | **P1** — `var(--color-text-tertiary)` `#9CA3AF` on white = 2.84:1, below AA. Used for `kpi__hint`, `axis-label`, `breadcrumb__sep`, `chart-hint`. Same issue all three pages — but most affected on Timeline because the axis labels are functional. |
| ARIA on SVG chart | **P0 missing** — `<svg>` has `aria-label` but bars/markers have no labels; the chart is a black box for screen readers. | n/a | n/a |
| Keyboard support for chart | **P0 missing** — `<rect>` and `<polygon>` are mouse-only. No `tabindex`, no `keyup` handlers, no focus styles. | n/a | n/a |
| Buttons have accessible names | DONE | DONE | DONE |
| `confirm()` for destructive | n/a | **P1** — `aliases.js:153` uses native `confirm()`. Inaccessible on some screen readers, ugly, blocks the event loop. Replace with a proper confirm modal in pulse-web. | n/a |
| Color-only meaning | DONE — badges have `::before` dot + text label | DONE | **P0** — severity bars use color only. The legend has labels but a hover gives `samples_count` not severity name. Bars need a pattern/texture fallback OR a `<title>` per bar OR a visible label per bar on focus. |
| ARIA live region for sync result | **P1** — "Última sync: agora há pouco" updates silently. Should announce via `aria-live="polite"`. | **P1** — bulk import result updates silently. `#bulk-result` already exists; needs `role="status" aria-live="polite"`. | n/a |

### B.2 Responsive

| Breakpoint | Ownership | Aliases | Timeline |
|---|---|---|---|
| Desktop (≥1280) | DONE | DONE | DONE |
| Tablet (768-1100) | DONE — `@media (max-width: 900px)` collapses KPI grid | DONE — 2-col → 1-col at 1100 | Partial — KPI grid collapses, but the SVG `viewBox="0 0 1200 240"` with `preserveAspectRatio="none"` stretches the chart vertically. **P1** — looks distorted on portrait tablets. |
| Mobile (<768) | **P1** — Table forces horizontal scroll (`.table-wrap { overflow-x: auto }`) which works but is hostile UX. No card layout fallback. | **P1** — same | **P0** — Chart is unreadable below 700px. Filter bar wraps OK but the chart compresses every hour bucket to <2px. No mobile fallback (e.g. show last-24h aggregate KPI only, hide chart). |
| Filter input min-width | **P1** — `styles.css:120 min-width: 280px` overrides `flex: 1` on mobile only via the media query at 357. Brittle. | Same | n/a |

### B.3 Six states (loading / empty / healthy / degraded / error / partial)

| State | Ownership | Aliases | Timeline |
|---|---|---|---|
| Loading | Partial — only "Carregando…" text, no skeleton rows. `.skeleton` class exists in `tokens.css` but is **unused**. **P1**. | Same P1 | Same P1 — and worse, KPIs show `—` while chart says nothing. |
| Empty | DONE — "Nenhum service encontrado." / "Nenhum alias configurado." / "Sem deploys no período." | DONE | DONE |
| Healthy (data present) | DONE | DONE | DONE |
| Degraded (some squads unmapped) | **P1** — there is no banner. The KPIs hide it: "Coverage 60%" is shown but there is no callout urging the user to map the missing 40%. | DONE via `suggestions` banner | n/a (or P2) |
| Error (fetch failed) | **P0** — `_loadOwnership()` swallows the error and sets `services = []`. The page silently shows "Nenhum service encontrado." which is indistinguishable from a real empty state. | Same P0 | Same P0 — `_load()` catches and sets `timeline = null`; UI never says "failed to load". |
| Partial (rollup gap, stale data) | n/a (no time series) | n/a | DONE — gap rendering as thin grey strip on baseline (`app.js:131-139`). Nice touch. But no banner telling the user "rollup is X hours stale". **P1**. |

### B.4 Skeleton on load

**Missing on all three pages.** Only `tokens.css:98 .skeleton` exists. None of the three pages use it. Tables fall back to text "Carregando…" which is fine functionally but the rest of pulse-ui standard is shimmer rows (see `pulse-ui/pages/dashboard/`). **P1**.

### B.5 Tokens-only CSS — hardcoded colors audit

Hardcoded hex/rgba inventory:

| File | Line | Code | Reason | Severity |
|---|---|---|---|---|
| `observability-timeline/app.js` | 280 | `stroke = '#E5E7EB'` | SVG axis grid — should use `var(--color-border-default)` via CSS class | **P1** (also leaks the token value into JS) |
| `observability-ownership/styles.css` | 210, 216, 222 | `rgba(16, 185, 129, 0.1)` etc. | Tinted badge backgrounds — token system has no "color-success-bg-soft" yet | **P1** — add new tokens: `--color-success-soft`, `--color-warning-soft`, `--color-danger-soft` |
| `observability-ownership/styles.css` | 280 | `rgba(17, 24, 39, 0.4)` | Modal backdrop | **P1** — add `--color-overlay` token |
| `observability-ownership/styles.css` | 287 | `rgba(0, 0, 0, 0.2)` | Modal shadow | **P1** — use existing `--shadow-elevated` |
| `observability-ownership/aliases.css` | 30, 31 | `rgba(245, 158, 11, 0.08/0.25)` | Suggestions banner bg/border | Same P1 as above |
| `observability-ownership/aliases.css` | 121, 125, 157 | `rgba(...)` | Result variants + danger button hover | Same P1 |
| `observability-timeline/styles.css` | 254 | `rgba(0, 0, 0, 0.18)` | Tooltip shadow | **P1** — use `--shadow-elevated` |

Net: **9 hardcoded color references** across 3 files. The fix is one PR adding ~6 soft tokens to `tokens.css` and a sweep of these files.

### B.6 Anti-surveillance enforcement

Reviewed every tooltip, table, and chart for PII/author/email leakage.

- Ownership table — no author info, no PII. Only `service_external_id`, `service_name`, `repo_url`, `inferred_squad_key`. **DONE.**
- Aliases table — `vendor_team_value` and `squad_key`. **DONE.**
- Timeline bucket tooltip — severity + samples count. **DONE.**
- Timeline deploy tooltip — `repo`, `environment`, `sha`. **P2** — the SHA is fine (commit hash, not author), but if `d.url` is a GitHub Actions URL embedded in `_renderDeployRow` we should make sure the click-through doesn't expose a PR author name to a viewer who shouldn't see it. Acceptable for now since users have GitHub auth anyway, but flag for security review.
- Deploys table — no author column. **DONE.** (If you ever add a "deployed by" column, that is anti-surveillance violation.)

All three pages **pass** the anti-surveillance check.

---

## C) Carlos persona — Deploy Health Timeline (most scrutiny)

### C.1 SVG vs Chart.js — was bespoke the right call?

**P1 — wrong call.** The rest of pulse-web uses Chart.js via `MetricCard.tsx`. Reasons to migrate:

1. **Accessibility**: Chart.js v4 has `plugins.tooltip.callbacks.label` and keyboard nav via the `legend`/`tooltip` plugins. Hand-rolled SVG starts from zero.
2. **Tooltip parity**: the rest of the app uses white-bg tooltips with shadow (PULSE convention per CLAUDE.md). Carlos's timeline tooltip is dark (`background: var(--color-text-primary)` line 247). Visually inconsistent with `MetricCard`.
3. **Maintenance**: SVG manual layout means manual responsive math, manual axis ticks. Already paying the cost — gap rendering, axis ticks, deploy markers each have bespoke code.
4. **Deploy markers**: Chart.js supports annotations via `chartjs-plugin-annotation` which is the canonical way to draw deploy markers as vertical lines. Done in 15 lines instead of 60.

**However**, Chart.js bar charts don't natively render a "severity heatmap with gap markers" — the bucket-by-hour quirks make it borderline. Compromise: use Chart.js for the bars + annotations for markers, keep the gap markers as a Chart.js dataset with opacity 0.25.

**Recommendation:** rewrite in Chart.js in the React port (PR C). Keep the SVG as a fallback only if Chart.js can't render the gap aesthetic.

### C.2 Tooltip UX

- Stale-on-leave: DONE — `_hideTooltip` on `mouseleave`.
- Follows mouse: DONE — `_showTooltip` rebinds `left/top` on every `mouseenter`. But it does **not** follow `mousemove` inside the same bar. **P2** — feels stuck. Add `mousemove` handler to reposition.
- Positioning logic: clamps to viewport (lines 206-207). **DONE.**
- Issue: tooltip uses `position: fixed` and reads `e.clientX/Y` from a SVG event. On touch devices, `clientX` is undefined → tooltip jumps to (0,0). **P1** — add `if (!Number.isFinite(e.clientX)) return;`.

### C.3 Time-window selector (24h/7d/30d)

**P0 cosmetic, not functional.** Look at `app.js:256-260`:

```js
document.getElementById('filter-window').addEventListener('change', (e) => {
  STATE.windowHours = parseInt(e.target.value, 10);
  _renderKpis();
  _renderChart();
});
```

It updates `STATE.windowHours` and re-renders. But `_renderChart()` reads `STATE.timeline.since/until` from the fixture — it never re-slices by window. So changing 7d to 24h shows the same chart. This is **misleading**: the user thinks they switched windows.

Fix is trivial for prototype (slice buckets by `Date.now() - windowHours*3600000`), but the real fix is in the React port: pass `windowHours` to a TanStack Query `useTimeline(squad, windowHours)` and trigger a refetch.

### C.4 Drill-down (squad → service)

**Not implemented.** No drill, no click handler, no link. The KPI banner says "25 services in squad" but you can't click into them. The fixture has `services_in_squad: 25` and `service: null` on every bucket (aggregated). In the React port this needs to become an interaction:

- Click a bar → drawer opens listing the services contributing to that bucket
- Click a service in drawer → navigate to `/observability/timeline?squad=ANCR&service=svc-checkout`

Should be in the impl spec. P1 for R2 launch.

### C.5 Deploy markers

- Dashed vertical line + triangle: visually nice and distinct from severity bars. DONE.
- Color-coded for failures (red vs brand): DONE for color users.
- **P0 accessible-by-color-alone**: failed deploys differ only by color. Add a shape change (e.g. triangle pointing up = success, X marker = failure) or a redundant cue (border thickness, hatching).
- Triangle at top with `dataset.deploy` JSON-encoded — works, but in React this should be `<DeployMarker deploy={d} />` with proper props.

### C.6 PT-BR copy consistency

Mixed languages flag:

- "Hour buckets" (label) — **English**. Should be "Buckets de hora" or "Janelas horárias".
- "Severidade média" — PT, good.
- "OK / Warn / Alert / No Data" — mixed; rest of app uses status badges in EN, but the page title is PT. Recommend keep status labels EN (they match Datadog vendor labels) but add a small footnote.
- "▼ deploy / ▼ failed" — EN. Make it "▼ deploy / ▼ falhou" or "▼ sucesso / ▼ falha".
- "Atualizar" button — PT, good.
- "Aggregated from N monitor(s)" — **English** in tooltip line 183. Should be "Agregado de N monitor(es)".

**P1** — copy sweep before launch.

---

## D) Service Ownership Map (PR 3)

### D.1 Visualization states for the 6 personas

The spec mentions: qualified squad, unqualified, orphan, overridden, inferred-tag, inferred-alias. What renders today:

| State | Visual | Distinct? | Color-blind safe? |
|---|---|---|---|
| Qualified | green dot + "qualificado" | yes | yes (label + dot) |
| Tag fora do tenant (~unqualified) | yellow dot + "tag fora do tenant" | yes | yes |
| Orphan (no inferred, no override) | grey neutral + "sem dono" | yes | yes |
| Override active | indigo bg badge on Override column | yes | yes (different column + style) |
| Inferred from tag | grey monospace badge | partially | label + monospace cue |
| Inferred from alias | **missing** — no visual distinction from "inferred from tag" | **P0 missing** |

The `_renderRow` function at `app.js:118-161` reads `svc.inferred_confidence` but only branches on `'tag'` and `'none'`. The alias confidence path (`'alias'`) renders identically to `'tag'`. **P0** — add a small "via alias" indicator or use `--chart-2` purple to differentiate.

### D.2 Filter UX

- Search by service name: DONE
- Filter by squad: **missing**. P1 — Webmotors has 27 squads × ~17 services each = a search-only UI is painful. Add a multi-select for squad.
- Filter by confidence (tag/alias/override/none): **missing**. P1 — Bruno's first task is "show me everything not qualified" and the current UI forces him to scroll.
- Filter by status (qualified/unqualified/orphan): **missing**. Same P1.

### D.3 Override modal

- Clean: yes.
- Confirms before save: no, but for a single-field override the click-to-save is correct UX. **DONE.**
- Edge case: "Manter inferência" is the first option but if the user picks it on a service with an existing override, that means "clear override". The hint text explains this (line 126) — **DONE**.

### D.4 Scale (473 rows)

- `_renderTable` does `STATE.services.filter(...).map(_renderRow).join('')` and assigns to `innerHTML`. For 473 rows, this is ~6000 DOM nodes (13 nodes per row). Empirically fine in Chrome at the prototype scale, but **P2** — for 2-3k row tenants (post-R2), virtualization needed.
- Filter is O(n) on every keystroke — also fine for 473, problematic for 5000+. **P2** — debounce + virtualize in React port (TanStack Virtual).

---

## E) Team Aliases (PR 3.5)

### E.1 Bulk paste

- Instructions: clear (`vendor_team,squad_key`, one per line).
- Placeholder example: useful — `agenda-facil,FACIL\ncrm,CRMC\nestoque,ESTQ`.
- Error states: differentiated (`ok` vs `warn` classes). DONE.
- Success feedback: `bulk__result` shows counts. DONE.
- **P1** — the result message doesn't list **which** lines failed. If the user pastes 50 lines and 5 are wrong squad keys, they get "5 squad inválido" but no idea which 5. Needs a downloadable error report or an inline marker beside each failed line.
- **P0** — `aliases.js:213 const lower = vendor.toLowerCase();` silently lowercases the user's input. If the live API is case-sensitive this is a bug; if it's case-insensitive this is fine but undocumented. Document or remove.

### E.2 Edit modal

- Confirms before save: yes, two-step (open modal, click Save). DONE.
- Squad select pre-populated with current value: DONE (`select.value = alias.squad_key`).
- No validation that the squad is still qualified at save time (relies on the fixture being current): P2.

### E.3 Suggestions panel

- Discoverable: yes — sticky banner at top with amber backdrop. The `<ul>` of unmapped vendor teams is in a chip grid. DONE.
- Action: the user has to manually retype each vendor name in bulk-paste. **P1** — clicking a suggestion chip should prepend `vendor_team,` to the textarea (or open an inline create form). One-click-to-map missing.

### E.4 "Tabs" between Ownership and Aliases

`aliases.css:6-26` defines `.tabs` and `.tab` as `<a>` links with `role="tab"` and `aria-selected`. Issues:

- Semantic mismatch: `role="tab"` should be inside a `role="tablist"` (DONE, line 32) but real tabs should be `<button>` with `aria-controls`, not full-page navigations. **P1** — for a prototype this is fine; in pulse-web port use TanStack Router with proper `<Link>` + the visual tab pattern from `jira.tsx:50` (which already does this correctly).
- Keyboard: a tab user can hit Enter on the focused tab and it navigates. Works. DONE.
- Focus indication: relies on global `:focus-visible` from tokens.css. DONE.

---

## F) Cross-cutting issues

### F.1 Code duplication

The three `app.js` files duplicate:

- `_escape()` function (identical in all three)
- `_formatRelative()` (ownership + aliases — identical)
- `_formatHour()` / `_formatTick()` (timeline only, but the same pattern)
- DOMContentLoaded → load fixture → render pattern (identical scaffolding)
- Modal open/close/Escape logic (ownership + aliases — nearly identical)

**P1** — extract to `pulse-ui/lib/` shared module:

```
pulse-ui/lib/
  escape.js       // _escape, _stripHtml
  format.js       // formatRelative, formatHour, formatTick
  modal.js        // openModal(modalEl, opts), closeModal(modalEl)
  fetchJson.js    // fetchJson(url) with error UI hook
```

The React port doesn't carry this debt — TanStack Query + React idioms erase the duplication. But for the prototype this is dead weight.

### F.2 Fixtures vs live API drift

The fixture at `observability-timeline/fixtures/timeline.json:10` has `"metric": "monitor_health"` which matches the worker pivot from PR #28 (FDD-OBS-001 PR 4a.5). Good — recent.

The ownership fixture, however, hardcodes squad keys like `OKM`, `FID`, `PTURB`. PR 3.5 (Team Aliases) shipped after PR 3 and changed the canonical squad-resolution path. **P1** — verify these fixtures still mirror the API response shape after PR 4a.5/4b. Two options:

- (Cheap) Document in the fixture filename which API/PR generated it.
- (Right) Add a `make refresh-prototype-fixtures` target that calls the live `/data/v1/admin/integrations/datadog/ownership` etc. against the dev tenant and writes JSON files. Mention in the impl spec so pulse-engineer adds it as a make target during PR A.

### F.3 Page-to-page navigation

The three pages are **orphaned** from the prototype's main IA. There is no top-level nav linking to them. They are reachable only by direct URL:

- `localhost:8080/pages/observability-ownership/index.html`
- `localhost:8080/pages/observability-ownership/aliases.html`
- `localhost:8080/pages/observability-timeline/index.html`

The breadcrumb on each page says "Settings / Integrations / Observability / ..." but those breadcrumb links go to `#` (line 14-21 of each html). **P1** — wire them, or at least add an entry in the prototype's index page (if one exists).

The React port will fix this via the Sidebar — but make sure to add the Sidebar entry in PR A.

---

## G) Design system maturity check

Did the new pages need anything not already in the design system? Tally:

| Component | Was in DS? | Now needed by 2+ pages |
|---|---|---|
| KPI banner | yes (`KpiCard` / `KpiGroup` in pulse-web; not in pulse-ui) | yes — promote to pulse-ui? |
| Modal | **no** | yes (ownership + aliases) — **promote to DS**, P1 |
| Tabs | **no** in pulse-ui (jira.tsx has it in pulse-web) | yes — **promote**, P1 |
| Badge with leading dot | partial (tokens.css `.badge--*` for DORA only) | yes — extend to status (ok/warn/danger/neutral) **promote**, P1 |
| Table with hover row + actions col | **no** | yes (ownership + aliases + deploys) — **promote**, P1 |
| Search input | partial (`.input`) | yes — extract |
| Suggestions banner (amber) | **no** | reused by aliases only for now, P2 |
| Filter bar | **no** in pulse-ui | timeline only — could become `FilterBar` primitive in pulse-web (already partially exists via TeamCombobox + PeriodSegmented) |
| SVG chart | **no** | only timeline; **don't promote**, replace with Chart.js |
| Tooltip floating | partial | yes — needs primitive |

**Bottom line**: at least 4 components rolled by hand here (`Modal`, `Tabs`, status `Badge`, `Table`) deserve to become DS components. The right place is `pulse/packages/pulse-web/src/components/ui/` (currently **empty** — see directory listing earlier). PR A is the natural moment to start this folder.

---

## H) Accessibility deep-dive (mental axe-core + lighthouse)

Per-page expected failures:

### Service Ownership
- **axe**: `aria-required-children` — `role="tablist"` contains a `<span>` separator that is not a `tab`. **P1** — mark the separator `role="presentation"` or use the proper `<nav>`.
- **axe**: pass on contrast, semantic markup, labels.
- **lighthouse**: ~95 (one orange flag on `.kpi__hint` contrast).
- **Keyboard nav**: tab through breadcrumb → tablist → sync button → filter input → table actions. Modal opens, Tab cycles **OUTSIDE** the modal (no focus trap). **P0**.

### Team Aliases
- Same `aria-required-children` issue as Ownership.
- **axe**: `confirm()` dialog cannot be axe-tested (browser-native).
- **lighthouse**: ~93.
- **Keyboard nav**: similar — modal focus escape, plus the suggestion chips are not focusable (`<li>` with no `tabindex`), so a keyboard user cannot click them once we add the "click-to-fill-textarea" interaction.

### Deploy Health Timeline
- **axe**: `image-alt`-equivalent fail on `<svg>`. While the SVG has `aria-label`, the children (`<rect>`, `<polygon>`) carry data and are interactive (hover) but invisible to AT.
- **axe**: contrast on axis labels (text-tertiary on white).
- **lighthouse**: ~85 due to the chart.
- **Keyboard nav**: filter bar OK. **The chart is fully inaccessible by keyboard.** No way for a screen-reader user to read severity over time, no way for a keyboard-only user to inspect a deploy marker.
  - Fix in React port: render an accessible `<table>` clone of the data with `aria-describedby` linking to the chart, OR add `tabindex="0"` + key handlers to every bar/marker, OR provide a "View as table" toggle.

Concrete keyboard-test answers to the prompt's question:

- Open the override modal: yes, Tab to "Definir" button → Enter → modal opens, Escape closes. **Bug: focus does not return to the trigger button.** P1.
- Edit the alias: same as above. **Bug: focus return.** P1.
- Refresh the timeline: yes, Tab to "Atualizar" button, Enter triggers refresh. DONE.

---

## Summary scorecard

| Page | P0 | P1 | P2 | DONE |
|---|---|---|---|---|
| Ownership | 3 | 9 | 3 | 11 |
| Aliases | 2 | 7 | 2 | 10 |
| Timeline | 5 | 11 | 2 | 9 |

**The Timeline is the riskiest of the three.** Five P0s (chart is inaccessible by keyboard, color-only severity, window selector is cosmetic, error state silent, deploy-fail visual is color-only) make it a no-go for a paying customer demo without rework.

---

## Implementation specs to write

For `pulse-engineer` handoff, write one impl-spec per page in `pulse/docs/ux-specs/`:

### `pulse/docs/ux-specs/observability-ownership-impl-spec.md`

Must include:
- Route: `/settings/integrations/observability/ownership` under TanStack Router file-based routing
- Parent layout: new `observability.tsx` mimicking `jira.tsx` tab pattern, tabs: Ownership / Aliases
- Component breakdown: 
  - DS-new: `Modal.tsx`, `Table.tsx` (with sortable headers + actions column), `StatusBadge.tsx`, `SearchInput.tsx` — all under `components/ui/`
  - Page: `OwnershipPage.tsx`, `OwnershipKpiBanner.tsx`, `OwnershipTable.tsx`, `OverrideModal.tsx`
- API client: `lib/api/observability.ts` with `getOwnership`, `runInference`, `setOverride`, `clearOverride`
- Hooks: `useOwnership()`, `useRunInferenceMutation()`, `useOverrideMutation()`
- States matrix all 6 (with skeleton rows on loading, distinct error state, degraded banner when coverage < 80%)
- Add new tokens to globals.css: `--color-success-soft`, `--color-warning-soft`, `--color-danger-soft`, `--color-overlay`
- A11y: focus trap on modal (use `focus-trap-react`), return focus on close, ARIA live on Run-inference status
- Filters spec for: search, squad multi-select, status, confidence (with corresponding API query params)
- Add 6th confidence state visualization: `inferred-alias` distinct from `inferred-tag`
- Sidebar entry in `Sidebar.tsx`: `{ label: 'Observability', path: '/settings/integrations/observability', icon: Activity }` or similar — under a Settings cluster
- Analytics events: `obs_ownership_viewed`, `obs_override_set { service_id, squad_key }`, `obs_override_cleared`, `obs_run_inference_clicked`, `obs_filter_applied { field }`

### `pulse/docs/ux-specs/observability-aliases-impl-spec.md`

Must include:
- Route: `/settings/integrations/observability/aliases`
- Reuses parent layout from ownership spec
- Components:
  - Reuse: `Modal`, `Table`, `SearchInput`, `Tabs`, `StatusBadge`
  - DS-new: `BulkPasteForm.tsx`, `SuggestionsBanner.tsx`, `ConfirmDialog.tsx` (variant of Modal)
  - Page: `AliasesPage.tsx`, `AliasesTable.tsx`, `EditAliasModal.tsx`
- API client extends `observability.ts` with `listAliases`, `bulkImportAliases`, `updateAlias`, `deleteAlias`, `getSuggestions`
- Bulk paste UX upgrade: per-line error markers + downloadable rejection report
- Suggestion chips become clickable: click prepends `vendor,` to textarea AND focuses textarea at end of inserted line
- Lowercase normalization: document or remove the `vendor.toLowerCase()` behavior, align with API spec
- All 6 states, skeleton rows, error state distinct from empty
- Replace native `confirm()` with `ConfirmDialog` primitive
- A11y: focus trap, return focus, suggestion chips focusable with `<button>` not `<li>`
- Analytics: `obs_alias_bulk_imported { inserted, updated, rejected }`, `obs_alias_edited`, `obs_alias_deleted`, `obs_suggestion_clicked { vendor_team }`

### `pulse/docs/ux-specs/observability-timeline-impl-spec.md`

Must include:
- Route: `/observability/timeline` (top-level, NOT under settings — this is Carlos's read-only page)
- Sidebar entry: `{ label: 'Deploy Health', path: '/observability/timeline', icon: Activity }`
- Components:
  - Reuse: `KpiGroup`, `KpiCard`, `TeamCombobox` (already exists), `PeriodSegmented` (already exists — 24h/7d/30d), `Table`, `FreshnessBanner`
  - DS-new: `DeployHealthTimelineChart.tsx` — **Chart.js implementation, not SVG**:
    - Stacked bar chart of severity per hour bucket
    - Annotations plugin for deploy markers (vertical line + custom point)
    - Custom tooltip plugin with white-bg + shadow (PULSE convention)
    - Accessible data table fallback (`role="table"` with same data, visually hidden until user toggles "View data")
  - Page: `DeployHealthTimelinePage.tsx`, `DeploysTable.tsx`
- API client extends `observability.ts` with `getTimeline(squadKey, windowHours, since, until)` → uses `dataClient`
- Hooks: `useTimeline(squadKey, windowHours)` with TanStack Query key `['obs','timeline',squadKey,windowHours]` so window switching triggers refetch
- Drill-down spec: clicking a bar opens a drawer (`EntityDrawer`) listing services contributing to that bucket with link to per-service timeline
- Deploy-fail visual: in addition to color, use a distinct marker shape (e.g. filled square vs filled triangle, or X overlay)
- All 6 states:
  - Loading: skeleton chart + skeleton KPIs
  - Empty: "Nenhuma observabilidade configurada para esta squad" with CTA link to /settings/integrations/observability/ownership
  - Healthy: data
  - Degraded: rollup gap > 4h ago → FreshnessBanner "Última rollup há Xh"
  - Error: distinct from empty, with retry button
  - Partial: gap rendering visible in chart + tooltip explains
- Mobile: hide chart, show "Past 24h: severity 0.3 (1 alert, 2 warns)" KPI summary
- Time-window selector wired to TanStack Query refetch (not cosmetic)
- A11y: chart accessible by keyboard (arrow keys move between bars; Enter opens drawer); accompanying `<table>` fallback; ARIA labels on every bar `Severity OK on May 8, 03:00 UTC`
- PT-BR copy sweep: "Buckets de hora", "Agregado de N monitor(es)", "deploy / falha"
- Analytics: `obs_timeline_viewed { squad_key, window_h }`, `obs_window_changed`, `obs_bucket_inspected`, `obs_deploy_inspected`, `obs_drilldown_opened`

---

End of review.
