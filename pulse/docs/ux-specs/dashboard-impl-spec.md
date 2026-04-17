# Dashboard — Implementation Spec

**Audience:** `pulse-engineer` (React + Vite + Tailwind port)
**Source prototype:** `pulse/pulse-ui/pages/dashboard/` (Concept C — Diagnostic-first)
**Target route:** `pulse/packages/pulse-web/src/routes/_dashboard/home.tsx`
**Date:** 2026-04-16
**Status:** Ready for handoff

---

## 1. Objective & Scope

Rebuild the PULSE Dashboard home (`/`) to answer the **3-layer JTBD of Carlos (EM)**:

1. **10s:** "Como estamos em DORA e em Flow?" → grouped KPI strip
2. **60s:** "Quem são os outliers por métrica?" → per-team ranking with DORA classification
3. **5min:** "Como cada métrica evoluiu por squad?" → small multiples over 12 weeks + drill-down drawer

### Files to create / modify
- **Modify:** `pulse/packages/pulse-web/src/routes/_dashboard/home.tsx` (full rewrite)
- **Create:** `src/components/dashboard/KpiGroup.tsx`, `KpiCard.tsx`, `TeamRankingBar.tsx`, `TeamRankingRow.tsx`, `MetricEvolutionGrid.tsx`, `TeamDetailDrawer.tsx`, `TeamCombobox.tsx`, `DateRangeFilter.tsx`
- **Extend:** `src/hooks/useMetrics.ts` to add `useGlobalMetrics()`, `useTeamsRanking(metric, period)`, `useTeamsEvolution(metric, period)`, `useTeamDetail(teamId)`
- **Extend:** `src/stores/filterStore.ts` to support `period: '30d' | '60d' | '90d' | '120d' | 'custom'` (already supports `'7d'|'30d'|'90d'|'custom'`; add `60d`, `120d`, remove `7d` or keep).
- **Delete:** `PRs Needing Attention` block (and the entire `prsNeedingAttention` branch of `useHomeMetrics`).

### Out of scope
- New DORA/Flow metric formulas (handled by `pulse-data-scientist`).
- Author-level visualisations (blocked by anti-surveillance).
- Real-time push updates (use 60s polling + manual refresh on filter change).

---

## 2. Design Rationale

**Concept C (Diagnostic-first) wins** because it satisfies Carlos' dominant JTBD without sacrificing Ana's executive scan:

- Group pattern (DORA + Flow as two pills) gives 10s clarity without losing depth.
- Per-metric **tabs + horizontal bar ranking** is the most scalable visual for 27 squads (a 27-row matrix à la Concept B is great for Priya but overwhelming for Carlos; cards would collapse at scale).
- **Non-modal drawer** preserves context during investigation (user can cross-reference KPI strip while reading team detail).
- **Small multiples** for evolution leverage pattern-matching ("which tribe has a rising WIP?") faster than overlaid line charts.

Rejected trade-offs:
- Overlaid multi-line chart (27 lines) → unreadable.
- 27 individual metric cards → fails at scale and hides comparisons.
- Modal dialog for drill-down → blocks investigation.

---

## 3. Information Architecture (reading order)

| Order | Section | Role | Data needed |
|---|---|---|---|
| 1 | Topbar | Brand, breadcrumb, last sync timestamp | `lastSyncAt` |
| 2 | Page head + Filters | Team combobox, period segmented, custom date range, reset | `TEAMS[]`, `filterStore` |
| 3 | Applied filters strip | Echoes active scope in prose | filter state |
| 4 | KPI Group · DORA | 4 KPIs (Deploy Freq, Lead Time, CFR, Time to Restore) + sparklines + classification | `GET /data/v1/metrics/global?period={}&teamId={}` |
| 5 | KPI Group · Flow | 4 KPIs (Cycle P50, Cycle P85, WIP, Throughput) + sparklines | same endpoint |
| 6 | Per-team ranking | Tab-selected metric + horizontal bars for 27 squads + DORA thresholds | `GET /data/v1/metrics/by-team?metric={}&period={}` |
| 7 | Evolution small multiples | 12-week spark per squad, grouped by tribo | `GET /data/v1/metrics/by-team/evolution?metric={}&period={}` |
| 8 | Drawer (lazy) | Team detail on demand | `GET /data/v1/teams/{id}/detail?period={}` |

---

## 4. Component Breakdown

| Visual block | Existing component | New component (proposed) | Primitives / tokens |
|---|---|---|---|
| KPI card | `MetricCard.tsx` (extend) | `KpiCard` (compact variant, 24px value) | `bg-surface-secondary`, `rounded-[10px]`, `shadow-card` |
| KPI group | — | `KpiGroup` (title + 4 slots + hint) | `section-gap`, `card-padding` |
| Team combobox | — | `TeamCombobox` (search + tribe grouping) | Radix `Popover` + `Command` |
| Period segmented | — | `PeriodSegmented` | `rounded-button`, tokens segmented |
| Date range | — | `DateRangeFilter` | native `input[type=date]` + mono font |
| Metric tab bar | — | `MetricTabs` | Radix `Tabs` |
| Ranking row | — | `TeamRankingRow` (position · team · bar · value · badge) | Grid, `bg-dora-*`, threshold overlay |
| Ranking container | — | `TeamRankingBar` (manages sort, virtualisation via `react-window`) | — |
| Small multiples tile | — | `MetricSparkTile` (Chart.js/Recharts `LineChart` minimal) | Recharts primitives |
| Small multiples grid | — | `MetricEvolutionGrid` (tribe groups + grid) | — |
| Drawer | — | `TeamDetailDrawer` | Radix `Dialog` non-modal OR custom slide-over |
| Drawer KPI tile | — | `DrawerMetric` | — |

### Virtualisation
- Ranking rows: **not virtualised** at 27 — plain DOM render; if scale grows >60 squads, switch to `react-window`.
- Small multiples: 27 mini-charts — Recharts is fine; memoise each tile (`React.memo`) and use `<ResponsiveContainer>` only at chart level.

---

## 5. Design Tokens Used

All token names match `pulse/packages/pulse-web/src/globals.css`. No hardcoded hex.

- **Colors:** `--color-bg-surface`, `--color-bg-secondary`, `--color-bg-tertiary`, `--color-text-primary`, `--color-text-secondary`, `--color-text-tertiary`, `--color-border-default`, `--color-border-subtle`, `--color-brand-primary`, `--color-brand-light`, `--color-dora-elite|high|medium|low` (+ new `--color-dora-*-bg` in tokens.css — add to globals.css if missing).
- **Typography:** Inter 14/400 body; Inter 24/600 H1; Inter 16/600 H2; Inter 13/600 H3; Inter 11/500 eyebrow; JetBrains Mono 13/500 for all numeric values and timestamps.
- **Spacing:** `--space-page-padding` 24px, `--space-card-padding` 20px, `--space-section-gap` 24px, KPI card padding 14px.
- **Radii:** `--radius-card` 12px, `--radius-button` 8px, `--radius-badge` 9999px.
- **Shadows:** `--shadow-card` (default card), `--shadow-elevated` (drawer, combobox panel).
- **Motion:** 150ms ease-out hover; 200ms ease-out drawer open; wrapped in `prefers-reduced-motion`.

**New tokens to add to `globals.css`:**
```css
--color-dora-elite-bg:  #D1FAE5;
--color-dora-high-bg:   #DBEAFE;
--color-dora-medium-bg: #FEF3C7;
--color-dora-low-bg:    #FEE2E2;
```

---

## 6. States Matrix

| State | Visual | Trigger | Data | Analytics |
|---|---|---|---|---|
| Loading | Skeletons preserving geometry: 8 KPI tiles, 10 ranking rows, 27 small-multiple tiles (dimmed) | `isLoading` | none | `dashboard_loading_shown` |
| Empty | Centered empty-state card with CTA "Conectar DevLake" (inert — read-only, just deep-links to `/settings/sources`) | `data.teams.length === 0` | — | `dashboard_empty_shown` |
| Healthy | Default rendering | `isSuccess && data.teams.length > 0` | full | `dashboard_viewed` |
| Degraded | Banner `role="status"` above KPI strip: "3 fontes com atraso (Jenkins · SECOM squad). Alguns gráficos podem estar parciais." | `data.freshness.sourcesDelayed > 0` | `data.freshness` | `dashboard_degraded_shown` |
| Error | Inline error card w/ retry: "Não foi possível carregar o dashboard. Tentar novamente." | `isError` | — | `dashboard_error_shown` |
| Partial (backfilling) | Specific squads marked with `badge--neutral` "Backfill" on ranking rows; evolution tile shows partial spark with dashed segment | `team.status === 'backfilling'` | per-team status | `dashboard_partial_shown` |

---

## 7. Responsive Rules

| Breakpoint | Layout changes |
|---|---|
| Desktop ≥1280px | KPI groups 2 cols · KPI grid 4 cols · Small multiples 4 cols · Drawer 520px |
| Tablet 900–1279px | KPI groups 1 col (stacked) · KPI grid 4 cols · Small multiples 3 cols · Ranking grid tightened |
| Tablet 640–899px | KPI grid 2 cols · Small multiples 2 cols · Filters wrap · Drawer 100vw |
| Mobile <640px | KPI grid 2 cols · Small multiples 1 col · Ranking row becomes 2-row (team + bar / value on line 2) · Metric tabs horizontal scroll |

All breakpoints tested against 27 squads in ranking and small multiples sections.

---

## 8. Accessibility Checklist (WCAG AA floor)

- [ ] Skip link to `#main` visible on focus
- [ ] All interactive controls keyboard reachable; focus ring 2px `--color-brand-primary`, offset 2px
- [ ] Combobox: `aria-haspopup="listbox"`, `aria-expanded`, search input `aria-label="Buscar squad"`, options have `aria-selected`
- [ ] Period segmented: `role="radiogroup"` + `role="radio"` + `aria-checked` per option
- [ ] Metric tabs: `role="tablist"` + `aria-selected`
- [ ] KPI groups: `<article aria-labelledby>` with group heading
- [ ] Status = color + glyph (badge pill) + text label (never color alone)
- [ ] Ranking rows: `role="button" tabindex="0"` + `aria-label="{team}: {value} {unit}"` + Enter/Space to open drawer
- [ ] Drawer: `role="dialog"` non-modal; Esc closes; autofocus on close button; focus returns to origin row on close
- [ ] `aria-live="polite"` on last-sync and applied-filters text
- [ ] Contrast: `content-primary` on `bg-surface` = 15.3:1; `content-secondary` on `bg-surface` = 4.6:1 ✓
- [ ] Reduced motion: all CSS animations gated by `prefers-reduced-motion: reduce`

---

## 9. Analytics Events (AARRR: Activation + Retention)

| Event | Payload | When |
|---|---|---|
| `dashboard_viewed` | `{ period, teamId }` | On mount |
| `dashboard_team_filter_changed` | `{ teamId, tribe }` | Team combobox selection |
| `dashboard_period_changed` | `{ period, customStart?, customEnd? }` | Segmented click |
| `dashboard_ranking_metric_changed` | `{ metric }` | Tab click |
| `dashboard_evolution_metric_changed` | `{ metric }` | Select change |
| `dashboard_drawer_opened` | `{ teamId, source: 'ranking'\|'small-multiple' }` | Row/tile click |
| `dashboard_drawer_closed` | `{ teamId, dwellMs }` | Esc / close |
| `dashboard_reset_filters` | `{}` | Limpar button |
| `dashboard_empty_shown` | `{ reason }` | Empty state |
| `dashboard_error_shown` | `{ code, message }` | Error |

Hypothesis: drawer open rate > 25% after W2 = Carlos engages in investigation; evolution-metric-changed > 2 events per session = trend hypothesis is used.

---

## 10. Open Questions / Risks

1. **Endpoint contracts:** `GET /data/v1/metrics/by-team?metric={}&period={}` and `.../evolution` do not yet exist. `pulse-engineer` + `pulse-data-engineer` must agree on response shape before porting. Proposed:
   ```ts
   type TeamRanking = { teamId: string; name: string; tribe: string; value: number; classification: 'elite'|'high'|'medium'|'low' }[]
   type TeamEvolution = { teamId: string; name: string; tribe: string; points: { weekStart: string; value: number }[] }[]
   ```
2. **Custom date range sanity:** enforce `start < end`, cap at 365 days, show validation inline.
3. **Flow classification thresholds:** Cycle Time / WIP / Throughput thresholds are heuristic in the mock. `pulse-data-scientist` must validate with Webmotors baseline before R1.
4. **27 → 60 squads:** layout holds at 60; beyond that, paginate ranking (top 20 / remaining) and lazy-render small multiples per tribe accordion.
5. **Anti-surveillance re-validation:** no endpoint/field must expose `author`, `login`, or user-specific fields in dashboard context. `pulse-ciso` to review API contract before merge.
6. **Remove old `prsNeedingAttention`:** coordinate with any other consumers (check `useHomeMetrics` usages) before deleting the field — otherwise deprecate first, remove later.
