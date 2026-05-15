# pulse-web Component Inventory (Phase 3 audit)

**Date:** 2026-05-11
**Auditor:** pulse-frontend
**Scope:** Read-only audit of `pulse/packages/pulse-web/` to map what FDD-OBS-001
Phase 3 can reuse vs. what is genuinely new work. Source-of-truth: tree at HEAD
of branch `main` post PR #29.

This file is the **first** of four prep artefacts for FDD-OBS-001 Phase 3. The
others are:
- `_pulse-web-component-gap.md` — what's missing / partial
- `observability-ownership-impl-spec.md` — Phase 3 spec
- `observability-aliases-impl-spec.md` — Phase 4 spec

---

## 1. Tech stack (verified)

| Concern | Choice | Evidence |
|---|---|---|
| Framework | React 19 + Vite 6 | `package.json:29-30`, `vite.config.ts` |
| Router | **TanStack Router** (config-based, `routeTree.gen.ts` auto-generated) | `App.tsx:2-16`, `src/routes/__root.tsx` |
| Data fetching | **TanStack Query v5** (global staleTime 5min, refetchInterval 60s) | `App.tsx:5-14` |
| HTTP client | **axios** (two instances: `apiClient` for NestJS, `dataClient` for FastAPI) | `src/lib/api/client.ts:8-26` |
| State (global) | **zustand** — used sparingly (filterStore, authStore) | `src/stores/filterStore.ts:40` |
| Styling | **Tailwind v4** (config-based, NOT JIT-only) + CSS custom properties | `tailwind.config.ts`, `src/globals.css` |
| Icons | `lucide-react` | already imported across the codebase |
| Charts | **recharts** (NOT Chart.js) + `@tremor/react` available | `package.json:31-33` |
| Forms | Plain controlled inputs — no react-hook-form, no zod resolvers wired | observed in `jira.tsx`, `project-catalog-table.tsx` |
| Validation | **zod** in devDeps (v3.25) — used in `tests/setup.ts`, NOT in components yet | `package.json:62` |
| Tests | Vitest + Testing Library + Playwright + axe-core + MSW | `package.json:19-20, 36-43`, `tests/msw-server.ts` |
| TS path alias | `@/` → `src/` | `tsconfig.json` (verified via existing imports) |

**Important correction:** `pulse-web` uses **recharts**, not Chart.js. The
frontend review §C.1 recommends Chart.js for the Timeline. That conflicts with
the existing toolchain. See §10 "Conflicts" below.

---

## 2. Design tokens

### 2.1 Tokens that exist today

Source: `pulse/packages/pulse-web/src/globals.css:5-71` (CSS custom properties)
mirrored to Tailwind theme in `tailwind.config.ts:7-86`.

| Category | Tokens | Tailwind alias |
|---|---|---|
| Backgrounds | `--color-bg-primary/secondary/tertiary/surface/elevated` | `bg-surface-primary` etc. |
| Text | `--color-text-primary/secondary/tertiary/inverse` | `text-content-primary` etc. |
| Borders | `--color-border-default/subtle` | `border-border-default` |
| Brand | `--color-brand-primary/-hover/-light` | `bg-brand-primary`, `text-brand-primary` |
| Status (solid) | `--color-success/warning/danger/info` | `bg-status-success` |
| Status (soft, only in tailwind config) | hardcoded `#ECFDF5` / `#FFFBEB` / `#FEF2F2` / `#EFF6FF` / `#F9FAFB` | `bg-status-successBg`, `text-status-successText`, etc. (`tailwind.config.ts:30-45`) |
| DORA | elite/high/medium/low + `-bg` variants | `bg-dora-elite-bg`, `text-dora-elite` |
| Chart palette | `--chart-1..6` | `bg-chart-1` etc. |
| Spacing | `--space-page-padding/card-padding/section-gap` | `p-page-padding`, `gap-section-gap` |
| Radii | `--radius-card/button/badge` | `rounded-card/button/badge` |
| Shadows | `--shadow-card/elevated` | `shadow-card`, `shadow-elevated` |
| Pipeline-only | `--pipeline-bg`, `--pipeline-surface-low/lowest`, `--pipeline-inverse` | not in tailwind theme; used by pipeline page CSS only |

### 2.2 What's missing for FDD-OBS-001

| Token | Used in prototype | Status |
|---|---|---|
| `--color-success-soft` | `aliases.css`, `observability-ownership/styles.css` line 210 | **MISSING** in both pulse-ui/tokens.css **and** pulse-web/globals.css |
| `--color-warning-soft` | same | **MISSING** |
| `--color-danger-soft` | same | **MISSING** |
| `--color-overlay` | modal backdrop (`rgba(17, 24, 39, 0.4)`) | **MISSING** — should be `color-mix(in srgb, var(--color-text-primary) 25%, transparent)` or a fixed token |

**Partial overlap:** `tailwind.config.ts:30-45` defines `status.successBg/warningBg/dangerBg` with hex literals (`#ECFDF5` etc.). These are usable as "soft" tokens via Tailwind class, but they are NOT exposed as CSS variables — i.e. the prototype tokens (`pulse-ui/tokens.css`) cannot reference them. Phase 3 should:
- Add the 4 new tokens to **both** `pulse-ui/tokens.css` and `pulse-web/src/globals.css`
- Either (a) refactor `tailwind.config.ts` to point `successBg` etc. at `var(--color-success-soft)` so the two systems converge, or (b) keep the dual system and document the divergence. Recommend (a).

### 2.3 Hardcoded hex audit in existing pulse-web

Run `grep -nE "#[0-9A-Fa-f]{3,8}" pulse-web/src/**/*.tsx` returns:
- `globals.css:7-79` — token definitions (expected)
- `tailwind.config.ts:31-44` — soft status hex (expected; documented as a gap above)
- `globals.css:107` — `linear-gradient(... #6366F1 ...)` — same as `--chart-1`; minor
- `globals.css:114-115` — `rgba(99, 102, 241, ...)` for node-glow animation — minor
- `globals.css:132` — `linear-gradient(135deg, #4648d4 0%, #6063ee 100%)` — `.pulse-gradient` utility, used by Pipeline only
- `KpiCard.tsx:56-64` — uses tokens via `var(--color-dora-*)` properly
- `Sidebar.tsx`, `Modal-ish` drawer code — clean, uses Tailwind tokens

**Verdict:** pulse-web body is clean. Tokens.css duplication is minor (gradients + animation rgba), nothing to fix for Phase 3.

---

## 3. Routing

### 3.1 Pattern

TanStack Router with **config-based** route definitions. Each route file
exports a `Route` object created via `createRoute({ getParentRoute, path,
component })`. The aggregator `routeTree.gen.ts` is **auto-generated** by the
TanStack Router Vite plugin (do NOT edit).

**Important:** the codebase uses the **config-based** API, not file-based path
auto-detection. Each new route must explicitly call `createRoute({ getParentRoute, ... })`.

### 3.2 Reference example — nested settings with tabs

`pulse-web/src/routes/_dashboard/settings/integrations/jira.tsx:7-78` is the
canonical pattern for a parent layout with a tab bar:

```tsx
export const jiraSettingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings/integrations/jira',
  component: JiraSettingsLayout,
});
```

- The component renders a header, a horizontal tab bar (`<Link to={...}>` with
  active state via `useMatchRoute({ to, fuzzy: true })`), and `<Outlet />`.
- Sub-tab routes (`jira.catalog.tsx`, `jira.config.tsx`, `jira.audit.tsx`)
  declare `getParentRoute: () => jiraSettingsRoute`.
- Default redirect from `/settings/integrations/jira` to `/catalog` uses
  `useEffect` + `useNavigate({ to, replace: true })` (lines 30-36).

This is the pattern Phase 3 should clone for `/settings/integrations/observability`.

### 3.3 File layout convention

```
src/routes/
  __root.tsx                              ← rootRoute, wraps in DashboardLayout
  _dashboard/
    home.tsx, prs.tsx, integrations.tsx   ← top-level dashboard pages
    pipeline-monitor.tsx
    metrics/{dora,cycle-time,throughput,lean,sprints}.tsx
    settings/
      integrations/
        jira.tsx                          ← parent route
        jira.catalog.tsx                  ← child tab
        jira.config.tsx
        jira.audit.tsx
        _components/                      ← page-private components (underscore prefix)
          discovery-status-badge.tsx
          project-catalog-table.tsx
          ...
```

**Convention:** route files use kebab-case for the URL part; sibling
`_components/` folders hold page-private components. The underscore prefix
keeps them out of the route tree.

---

## 4. State management

| Need | Pattern | Example |
|---|---|---|
| Server state (lists, queries, mutations) | TanStack Query | `useJiraAdmin.ts:51-256` |
| Global UI filters | zustand | `filterStore.ts:40` (teamId, period, activeMetric) |
| Auth (stub) | zustand | `authStore.ts` |
| Local form state | `useState` | every page |
| URL state | NOT systematized | filters live in the zustand store, **not** in URL params — this is a gap that the timeline window selector should fix |

**Decision implied:** Phase 3 timeline window selector should sync to URL
search-params (e.g. `?window=24h`) so a Carlos can deep-link. The current
filter store doesn't model URL-state; will need to be added or built ad-hoc
with TanStack Router's `useSearch`/`Navigate`.

---

## 5. API client pattern

### 5.1 Two axios instances

`src/lib/api/client.ts`:
- `apiClient` → `/api` → NestJS (`pulse-api`)
- `dataClient` → `/data/v1` → FastAPI (`pulse-data`)

Both have:
- 15s / 30s timeouts respectively
- A stub auth interceptor (`attachAuthHeader`) — MVP no-op
- A response error handler that logs and rejects (no toasts yet)

### 5.2 Module pattern

Each domain has `src/lib/api/<domain>.ts` exporting **plain async functions**
(no class wrappers). Example: `jira-admin.ts`:
```ts
export async function getJiraConfig(): Promise<TenantJiraConfig> {
  const response = await apiClient.get<TenantJiraConfig>(`${BASE}/config`);
  return response.data;
}
```

### 5.3 Hooks pattern

`src/hooks/<useDomain>.ts` exports:
- A `queryKeys` object (hierarchical, e.g. `jiraAdminKeys.projectList(query)`)
- `useXQuery` hooks wrapping `useQuery`
- `useXMutation` hooks wrapping `useMutation` with optimistic updates via
  `onMutate` / `onError` / `onSettled`

**Excellent reference for Phase 3/4** — `useJiraAdmin.ts:126-176`
(`useProjectActionMutation`) shows the full optimistic-update pattern with
rollback that we want for `useOverrideMutation`, `useUpdateAliasMutation`, etc.

### 5.4 Shared types

Types come from `@pulse/shared` (workspace package, see imports like
`import type { JiraProjectStatus } from '@pulse/shared';`). Phase 2 will add
new obs types here; Phase 3 just consumes them.

---

## 6. Accessibility patterns already in use

| Pattern | Where | Reusable for obs pages? |
|---|---|---|
| Hand-rolled focus trap on Tab + Esc | `EntityDrawer.tsx:46-84`, `TeamDetailDrawer.tsx:50-90` | **YES — but it's duplicated. Time to promote to a `useFocusTrap` hook.** |
| Skeleton shimmer via `animate-pulse` tailwind class | `project-catalog-table.tsx:164-181`, `KpiCard.tsx:224-233` | **YES** — drop-in pattern |
| `role="dialog" aria-modal="true" aria-label` on drawers/modals | `EntityDrawer.tsx:98-100`, `project-catalog-table.tsx:72-77` | **YES** |
| `aria-live="polite"` for status updates | `FreshnessBanner.tsx:42` (`role="status"`) | **YES** — pattern to copy for "Run inference" feedback |
| `sr-only` label for sort-order/icon-only buttons | `project-catalog-table.tsx:537`, `SortableHeader` pattern | **YES** |
| Focus ring via `focus-visible:ring-2 focus-visible:ring-brand-primary` | everywhere | **YES** |
| Reduced motion respected | `globals.css:152-159` blocks custom animations under `prefers-reduced-motion` | **YES** — already covered |

**Observation:** there is **no `useFocusTrap` hook** today. Two files
re-implement identical logic (`EntityDrawer.tsx` and `TeamDetailDrawer.tsx`,
~30 LoC each). Phase 3's new `<Modal>` is the perfect moment to extract it.
Adding it does not require a library — `tabbable` is already in node_modules
as a transitive of MSW (`node_modules/tabbable/index.d.ts`) but is not
imported anywhere; recommend pure-DOM `querySelectorAll` approach for
consistency with existing code.

---

## 7. Existing component primitives — full inventory

### 7.1 Layout (production-ready, reuse for obs)

| Component | Path | API surface | Notes |
|---|---|---|---|
| `DashboardLayout` | `components/layout/DashboardLayout.tsx:1-23` | `children` | Wraps everything with sidebar + topbar; obs pages will be children automatically via `__root.tsx` |
| `Sidebar` | `components/layout/Sidebar.tsx:40-132` | self-contained, reads route + capabilities | **MODIFY** — add "Observability" entry, decide placement |
| `TopBar` | `components/layout/TopBar.tsx` | unread but referenced | Likely no changes needed |

### 7.2 Charts / data viz

| Component | Path | Notes |
|---|---|---|
| `MetricCard` | `components/charts/MetricCard.tsx` | Wraps **recharts**. Used by metrics pages. Not directly reusable for obs timeline. |
| `AtRiskSparkline` | `components/dashboard/FlowHealth/AtRiskSparkline.tsx` | Inline SVG sparkline. Small scale only. |
| Sparkline inside KpiCard | `KpiCard.tsx:44-77` | Inline SVG, 60×20. Good reference for the obs KPI banner. |

**No bar chart, no annotation, no axis primitive.** Phase 5 will need to
build the timeline chart fresh.

### 7.3 Dashboard widgets (production-ready)

| Component | Path | Reusable for obs? |
|---|---|---|
| `KpiCard` + `KpiCardSkeleton` | `components/dashboard/KpiCard.tsx:103-233` | **YES** — exact fit for the 4-KPI banner on Ownership/Timeline. Already supports tooltip, pending state, sparkline, dora classification badge. |
| `KpiGroup` | `components/dashboard/KpiGroup.tsx` | **YES** — grid wrapper for KpiCards |
| `DateRangeFilter` | `components/dashboard/DateRangeFilter.tsx` | Maybe — depends on whether timeline uses calendar date picker (no — uses window selector) |
| `PeriodSegmented` | `components/dashboard/PeriodSegmented.tsx:1-52` | **Pattern reuse, but not direct.** Existing options are 30/60/90/120d. Timeline needs 24h/7d/30d. Same component shape with different props. Either parameterize the existing component or clone it as `WindowSegmented`. Recommend parameterize. |
| `TeamCombobox` | `components/dashboard/TeamCombobox.tsx:11-196` | **YES — but reads `TeamHealth` (Pipeline type), not "Squad".** For obs, we need a similar combobox over `qualified_squads`. Either (a) generalize TeamCombobox via a generic item-type prop, or (b) build `SquadCombobox` for obs. Recommend (a) but it's a refactor — see Phase 3 spec §6. |
| `InfoTooltip` | `components/dashboard/InfoTooltip.tsx:27-63` | **YES** — drop-in for "what is coverage?" tooltips |
| `FreshnessBanner` | `components/dashboard/FreshnessBanner.tsx:30-69` | **YES** — perfect for "rollup is stale" warning on timeline |
| `TeamDetailDrawer` | `components/dashboard/TeamDetailDrawer.tsx:47-?` | **Reference for focus trap pattern.** Not directly reusable; new drawer for ownership "view services in squad" drill-down. |
| `MetricEvolutionGrid` | `components/dashboard/MetricEvolutionGrid.tsx` | Not applicable to obs |
| `FlowHealth/*` | `components/dashboard/FlowHealth/` | Not applicable to obs |
| `TeamRankingSection` | `components/dashboard/TeamRankingSection.tsx` | Not applicable |

### 7.4 Pipeline components (reference patterns, generally not reused)

`components/pipeline/` is its own design language built for the Pipeline
Monitor page. Most components there assume "Source / Entity / Step" data
shapes. **Two are useful as patterns**:

- `pipeline/shared/Badge.tsx:18-35` — small status badge with icon + label,
  built on `getStatusConfig` lookup. **Pattern reuse for obs `StatusBadge`,
  but not direct reuse** (obs badges have a different status vocabulary).
- `pipeline/EntityDrawer.tsx:40-269` — full drawer with focus trap, step
  progress, error banner, rate-limit bar. The drawer scaffold + focus-trap
  logic is the model for our new `<Modal>` primitive.

### 7.5 Page-private components (NOT design-system)

Each route's `_components/` folder is private. None of them are
re-exportable. The closest to "reusable" is `project-catalog-table.tsx` —
but it's tightly coupled to Jira types. Phase 3 should **extract the table
scaffold** (sortable headers, row hover, pagination, bulk selection) into a
generic `<Table>` primitive in `components/ui/`.

### 7.6 `components/ui/` — currently EMPTY

```
$ ls pulse-web/src/components/ui/
(empty)
```

The folder exists but is empty. The master plan §3 Phase 3 sets this folder
as the destination for all 5 new primitives. **This is the right starting
point.**

---

## 8. Testing patterns

| Layer | Tool | Reference test | Coverage today |
|---|---|---|---|
| Unit (utils, hooks) | Vitest + Testing Library | `lib/dashboard/__tests__/formatDuration.test.ts`, `lib/api/__tests__/jira-admin.test.ts` | Spotty; new code expected to test |
| Component unit | RTL + Vitest | `_components/__tests__/project-row-actions.test.tsx`, `mode-selector.test.tsx`, `project-catalog-table.test.tsx` | Settings/integrations tested; others not |
| MSW (mock API for tests) | `msw@2.13` | `tests/msw-server.ts` | Wired but most tests don't use it yet |
| E2E | Playwright | `tests/e2e/*` (presumed; `playwright.config.ts` exists) | Coverage unknown |
| Accessibility | `@axe-core/playwright` | `npm run test:a11y` script | Wired |
| Visual regression | None | — | Not set up; documented gap in FDD-DSH-070 |

**Implication for Phase 3:** every new `ui/` primitive needs a Vitest unit
test + an axe-core check via Playwright. The primitives are exactly the kind
of code that benefits most from this (small, well-scoped, high reuse).

---

## 9. Sidebar nav structure

`Sidebar.tsx:27-38` is the source of truth:

```ts
const NAV_ITEMS: NavItem[] = [
  { label: 'Home', path: '/', icon: Home },
  { label: 'DORA', path: '/metrics/dora', icon: Activity },
  { label: 'Cycle Time', path: '/metrics/cycle-time', icon: Clock },
  { label: 'Throughput', path: '/metrics/throughput', icon: BarChart3 },
  { label: 'Lean & Flow', path: '/metrics/lean', icon: Workflow },
  { label: 'Sprints', path: '/metrics/sprints', icon: Zap, requiresCapability: 'sprints' },
  { label: 'Open PRs', path: '/prs', icon: GitPullRequest },
  { label: 'Integrations', path: '/integrations', icon: Cable },
  { label: 'Pipeline', path: '/pipeline-monitor', icon: Activity },
  { label: 'Jira Settings', path: '/settings/integrations/jira', icon: Settings },
];
```

It's a **flat list** today (no grouping, no collapsible sections). For Phase
3, we need at minimum:

1. **Observability** entry (Carlos's page) — top-level, peer to "Pipeline"
2. **Observability Settings** OR a nested "Settings → Integrations →
   Observability" entry — Bruno's pages

The current sidebar can't render a Settings sub-cluster cleanly. **Decision
needed:** either (a) add a sibling "Observability" entry at top + lean on
the existing "Jira Settings" pattern by adding "Observability Settings", or
(b) refactor the sidebar to support an inline section/group concept.

Recommend (a) for Phase 3, defer (b) to a separate IA pass. See
ownership impl-spec §3.

---

## 10. Conflicts between frontend review and existing system

The frontend review at `docs/reviews/FDD-OBS-001-frontend-review.md`
recommends **Chart.js** for the timeline chart (§C.1). The existing pulse-web
uses **recharts** (everywhere — `MetricCard.tsx`, `TeamDetailDrawer.tsx`).
Adopting Chart.js would:

- Add ~70 KB gzip (Chart.js 4 + `chartjs-plugin-annotation`) to the bundle
- Diverge from the rest of the app's charting library
- Require new tooltip styling glue to match recharts' look
- Not improve a11y meaningfully — recharts has its own a11y story; both are
  weak by default and need manual work

**Recommendation (raised to main session for resolution):** stay with
**recharts** + manually-rendered SVG layer for deploy markers. Recharts
supports `<Bar>`, `<XAxis>`, custom tooltips via the `<Tooltip
content={...}>` API, and a `<ReferenceLine>` for vertical deploy lines. The
"severity heatmap" is a stacked bar chart with custom colors.

This conflicts with the frontend review §C.1 — flagged. The Phase 5 impl
spec (not in this task) should resolve definitively, possibly with a
spike-PR.

The CLAUDE.md frontmatter says "Chart.js via CDN for all charts" but that
refers to the **prototype** (pulse-ui/). The React app has standardized on
recharts. The CLAUDE.md note is stale for pulse-web.

---

## 11. Summary — what Phase 3 can lean on

**Use directly, no changes:**
- `KpiCard`, `KpiCardSkeleton`, `KpiGroup`
- `InfoTooltip`
- `FreshnessBanner`
- `DashboardLayout` (automatic via root route)
- `apiClient` (NestJS — for write endpoints after Phase 2)
- `dataClient` (FastAPI — direct reads before Phase 2 if needed)
- TanStack Query patterns from `useJiraAdmin`
- Tailwind tokens (`bg-surface-primary`, `text-content-primary`, ...)
- Skeleton pattern (`animate-pulse` on `bg-surface-tertiary` div)

**Use as pattern reference, write fresh:**
- Tab layout from `jira.tsx:50-73`
- Sortable table from `project-catalog-table.tsx:382-441`
- Focus trap from `EntityDrawer.tsx:46-84` (and extract to a hook)
- Optimistic mutations from `useJiraAdmin.ts:126-176`

**Must build new (in `components/ui/`):**
- `<Modal>` (with `useFocusTrap` hook)
- `<Table>` (sortable headers, generic over row type)
- `<StatusBadge>` (with 6 confidence variants)
- `<SearchInput>` (debounced)
- `<Tabs>` (mostly already done in `jira.tsx` — just factor out)

**Must add to tokens:**
- 4 soft-color tokens (`--color-success-soft`, `--color-warning-soft`,
  `--color-danger-soft`, `--color-overlay`)
- Mirror in both `pulse-ui/tokens.css` and `pulse-web/src/globals.css`

**Must extend Sidebar:**
- 2 new nav items (Observability dashboard + Observability Settings)

---

End of inventory.
