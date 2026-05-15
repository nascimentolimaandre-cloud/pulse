# UX Implementation Spec — Service Ownership Map (FDD-OBS-001 Phase 3)

**Status:** Ready for `pulse-engineer` to implement
**Phase:** 3 of FDD-OBS-001 remediation
**Depends on:** Phase 1 + Phase 2 merged (backend integrity fixes + pulse-api proxy module live at `/api/v1/obs/*` and `/api/v1/admin/integrations/datadog/*`)
**Persona:** Bruno (Platform Engineer) — owns squad-to-service mapping; cares about coverage % and unqualified squads
**Author:** pulse-frontend (audit-only role; engineer authors implementation)
**Source:** Prototype at `pulse/pulse-ui/pages/observability-ownership/`; review at `docs/reviews/FDD-OBS-001-frontend-review.md` §D

---

## 1. Objective & scope

### 1.1 What ships
A production-ready React page at `/settings/integrations/observability/ownership` that:
- Renders ~473 services (Webmotors-scale) with their inferred-vs-override squad mapping
- Surfaces coverage % and counts of qualified / unqualified / orphan / overridden services
- Lets Bruno run inference on demand (triggers DD discovery)
- Lets Bruno set or clear a manual squad override per service
- Filters by search (debounced), squad, status, and confidence dimension
- Hits all 6 explicit UI states (loading / empty / warming-up / healthy / degraded / error / partial)
- Passes WCAG AA via axe-core

### 1.2 Out of scope (Phase 3)
- Aliases tab — Phase 4 (separate spec)
- Timeline / Deploy Health — Phase 5 (no spec yet; depends on data-scientist analysis)
- New IA / sidebar grouping — defer
- Squad multi-select — Phase 3 ships with single-squad filter; multi-select is a follow-up

---

## 2. Design rationale

The prototype review classified Ownership as the **least risky** of the three
pages (3 P0, 9 P1, 11 DONE). The shipping page must close the P0s:

- **P0**: error state must be distinct from empty state (today: both render
  "Nenhum service encontrado")
- **P0**: keyboard focus trap on the override modal (today: Tab escapes the
  modal)
- **P0**: `inferred-alias` confidence must be visually distinct from
  `inferred-tag` (today: identical rendering)

Plus the highest-leverage P1s: skeleton rows, filter by status/confidence,
degraded coverage banner, hardcoded color sweep.

---

## 3. Information architecture & routing

### 3.1 Route hierarchy

```
__root.tsx (rootRoute, wraps DashboardLayout)
  └─ /settings/integrations/observability       ← new parent route
       │   component: ObservabilitySettingsLayout
       │   redirects /settings/integrations/observability → /ownership
       │
       ├─ /ownership                            ← THIS SPEC
       │     component: OwnershipPage
       │
       └─ /aliases                              ← Phase 4 (separate spec)
             component: AliasesPage
```

### 3.2 Files to create

```
src/routes/_dashboard/settings/integrations/
  observability.tsx                              ← parent layout (new)
  observability.ownership.tsx                   ← THIS PAGE (new)
  observability.aliases.tsx                     ← Phase 4 stub OK
  _components/observability/                    ← new private folder
    ownership-kpi-banner.tsx
    ownership-table.tsx
    ownership-row.tsx
    ownership-filters.tsx
    override-modal.tsx
    squad-combobox.tsx
```

### 3.3 Sidebar entry (`components/layout/Sidebar.tsx`)

Append after the existing "Jira Settings" entry (line 37):
```ts
{
  label: 'Observability',
  path: '/settings/integrations/observability',
  icon: Radar,                            // import { Radar } from 'lucide-react'
},
```

(Reason for icon: `Radar` reads as "monitoring/observability" without
overloading `Activity` which Pipeline owns.)

### 3.4 Parent layout — mirrors `jira.tsx`

Clone `jira.tsx:24-78` near-verbatim, swapping:
- Title: "Observability Integration"
- Subtitle: "Mapeamento de serviços, aliases de equipe e auditoria. Datadog."
- Tabs: `[{ to: '.../ownership', label: 'Ownership' }, { to: '.../aliases', label: 'Aliases' }]`
- Default redirect: `/observability` → `/observability/ownership`
- Right-side status badge: replace `DiscoveryStatusBadge` with a new
  `ObservabilityConnectionBadge` that renders "Datadog conectado" / "Não
  configurado" based on a `useObservabilityHealth()` query. If the badge
  reads "Não configurado", suppress the tabs and show a CTA card "Conecte
  Datadog para começar" linking to the integration setup (out of scope —
  same place where DD API key is registered).

---

## 4. Component composition

### 4.1 Tree

```
<ObservabilitySettingsLayout>                  ← parent route
  <header>title + ObservabilityConnectionBadge</header>
  <Tabs>                                       ← NEW primitive (or factor from jira.tsx)
    <Tabs.Item to="...ownership">Ownership</Tabs.Item>
    <Tabs.Item to="...aliases">Aliases</Tabs.Item>
  </Tabs>
  <Outlet />                                   ← OwnershipPage rendered here
</ObservabilitySettingsLayout>

<OwnershipPage>
  <FreshnessBanner /> (conditional — only if rollup stale)
  <OwnershipKpiBanner />                       ← 4 KpiCards + "Run inference" button
  <OwnershipFilters />                         ← SearchInput + StatusFilter + ConfidenceFilter
  <OwnershipTable />                           ← Table primitive
  <OverrideModal />                            ← Modal primitive (renders conditionally)
</OwnershipPage>
```

### 4.2 Primitives used (see `_pulse-web-component-gap.md`)

| Primitive | New / Reused | Source |
|---|---|---|
| `Modal` | NEW | `components/ui/Modal.tsx` |
| `useFocusTrap` hook | NEW | `components/ui/useFocusTrap.ts` |
| `Table` | NEW | `components/ui/Table.tsx` |
| `StatusBadge` | NEW | `components/ui/StatusBadge.tsx` |
| `SearchInput` | NEW | `components/ui/SearchInput.tsx` |
| `Tabs` | NEW (factored from `jira.tsx`) | `components/ui/Tabs.tsx` |
| `SquadCombobox` | NEW (clone of `TeamCombobox`) | `components/dashboard/SquadCombobox.tsx` |
| `KpiCard` + `KpiGroup` | REUSE | `components/dashboard/KpiCard.tsx` |
| `KpiCardSkeleton` | REUSE | same file |
| `InfoTooltip` | REUSE | `components/dashboard/InfoTooltip.tsx` |
| `FreshnessBanner` | REUSE | `components/dashboard/FreshnessBanner.tsx` |

### 4.3 Page-private components

```
_components/observability/ownership-kpi-banner.tsx     // 4 KpiCards + run-inference btn
_components/observability/ownership-table.tsx          // wraps <Table> with column defs
_components/observability/ownership-row.tsx            // visual row content (squad badges)
_components/observability/ownership-filters.tsx        // search + 2 select chips
_components/observability/override-modal.tsx           // wraps <Modal> + form
_components/observability/squad-combobox.tsx           // moved here if not promoted to DS
```

---

## 5. Data fetching

### 5.1 API endpoints (post-Phase 2)

All routes proxied through pulse-api. Methods + paths:

| Verb | Path | Purpose | Response shape |
|---|---|---|---|
| GET | `/api/v1/obs/ownership` | List services with mapping | `{ services: Service[], coverage_pct: number, last_inference_at: string \| null, qualified_squads: Squad[] }` |
| POST | `/api/v1/admin/integrations/datadog/ownership/sync` | Trigger inference re-run | `{ run_id: string, started_at: string }` |
| PUT | `/api/v1/admin/integrations/datadog/services/{id}/override` | Set manual override | `{ service: Service }` |
| DELETE | `/api/v1/admin/integrations/datadog/services/{id}/override` | Clear override | `{ service: Service }` |
| GET | `/api/v1/admin/integrations/datadog/health` | Connection status (used by parent layout) | `{ connected: boolean, last_rollup_at: string \| null, tenant_id: string }` |

(Exact shapes will be authored by `pulse-engineer` in Phase 2 of the
remediation. Phase 3 should track Phase 2's PR and adjust types in
`@pulse/shared`.)

### 5.2 API client

`src/lib/api/observability.ts` — new file. Exports plain async functions
following the `jira-admin.ts` pattern:

```ts
import { apiClient } from './client';
import type {
  ObsOwnershipResponse,
  ObsServiceOverrideInput,
  ObsService,
  ObsHealthResponse,
} from '@pulse/shared';

const OBS = '/v1/obs';
const OBS_ADMIN = '/v1/admin/integrations/datadog';

export async function getOwnership(): Promise<ObsOwnershipResponse> { ... }
export async function getObservabilityHealth(): Promise<ObsHealthResponse> { ... }
export async function runOwnershipInference(): Promise<{ run_id: string }> { ... }
export async function setServiceOverride(id: string, body: ObsServiceOverrideInput): Promise<ObsService> { ... }
export async function clearServiceOverride(id: string): Promise<ObsService> { ... }
```

### 5.3 TanStack Query hooks

`src/hooks/useObservability.ts` — new file. Pattern from `useJiraAdmin.ts`:

```ts
export const obsKeys = {
  all: ['obs'] as const,
  ownership: () => [...obsKeys.all, 'ownership'] as const,
  health: () => [...obsKeys.all, 'health'] as const,
  inference: () => [...obsKeys.all, 'inference'] as const,
};

export function useOwnershipQuery() {
  return useQuery({
    queryKey: obsKeys.ownership(),
    queryFn: getOwnership,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useObservabilityHealth() {
  return useQuery({
    queryKey: obsKeys.health(),
    queryFn: getObservabilityHealth,
    staleTime: 5 * 60_000,
  });
}

export function useRunInferenceMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runOwnershipInference,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: obsKeys.ownership() });
      void qc.invalidateQueries({ queryKey: obsKeys.health() });
    },
  });
}

export function useOverrideMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ObsServiceOverrideInput }) =>
      setServiceOverride(id, body),
    onMutate: async ({ id, body }) => {
      // Optimistic: patch the service in cache
      await qc.cancelQueries({ queryKey: obsKeys.ownership() });
      const prev = qc.getQueryData<ObsOwnershipResponse>(obsKeys.ownership());
      qc.setQueryData<ObsOwnershipResponse>(obsKeys.ownership(), (old) =>
        old ? { ...old, services: old.services.map((s) =>
          s.service_external_id === id ? { ...s, override_squad_key: body.squad_key } : s
        ) } : old
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(obsKeys.ownership(), ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: obsKeys.ownership() });
    },
  });
}

export function useClearOverrideMutation() { /* same pattern, calls clearServiceOverride */ }
```

### 5.4 Refetch strategy

- `useOwnershipQuery` — `staleTime: 60s`, refetch only on explicit
  invalidation or window-focus (currently disabled at the App level)
- `useObservabilityHealth` — `staleTime: 5min`, used by parent layout
- After `useRunInferenceMutation` succeeds, optimistically set
  `last_inference_at = now()` while invalidating; the next fetch hydrates
  the rest

---

## 6. State machine — 6 explicit states

The page renders **exactly one** of these states at a time. Implement as a
discriminated union in `OwnershipPage`:

```ts
type PageState =
  | { kind: 'loading' }                              // initial fetch
  | { kind: 'empty-no-connection' }                  // health.connected === false
  | { kind: 'empty-warming-up' }                     // connected but services=[] and last_inference_at < 5min ago
  | { kind: 'healthy'; data: ObsOwnershipResponse }
  | { kind: 'degraded'; data: ObsOwnershipResponse } // coverage_pct < 0.6 OR rollup stale > 4h
  | { kind: 'error'; error: Error };
```

### 6.1 Loading
- KpiBanner renders 4× `<KpiCardSkeleton>`
- Table renders `loadingRowCount={10}` skeleton rows (from new Table prop)
- Filters render disabled
- aria-busy="true" on `<main>`

### 6.2 Empty — no connection
- Single full-width card: "Conecte Datadog para começar"
- Body: short paragraph + CTA button → links to existing DD integration
  setup page (out of scope; same path used by "Jira Settings" pattern)
- No KPIs, no table, no filters

### 6.3 Empty — warming up
- KpiBanner renders with 0 / 0% / 0 / 0 values
- Table renders empty state row with copy:
  > "Inferência iniciada há X min. Os primeiros serviços aparecem dentro de
  > ~2 minutos. **Atualizar agora**"
- "Atualizar agora" is a button that re-fetches the ownership query

### 6.4 Healthy
- Full render: KpiBanner with real values, table with rows, filters active
- No banner

### 6.5 Degraded
- `<FreshnessBanner severity="degraded">` at top with message tailored:
  - If `coverage_pct < 0.6`: "Apenas X% dos serviços têm squad qualificado.
    Configure aliases ou defina overrides para chegar a 80%+."
    `linkTo="/settings/integrations/observability/aliases"`
  - If rollup stale > 4h: "Última inferência há Yh. Worker pode estar
    parado." `linkTo="/pipeline-monitor"`
- KpiBanner + Table render normally
- If both apply, render both banners stacked

### 6.6 Error
- Replace KpiBanner + filters + table with single error card:
  - Icon `<AlertCircle>` red
  - Title "Falha ao carregar"
  - Message: `error.message`
  - Two buttons: "Tentar novamente" (refetch) and "Ver pipeline"
    (`linkTo="/pipeline-monitor"`)
- aria-live="assertive" on the card

### 6.7 Partial (not applicable here)
The 6th state from the master plan ("partial") doesn't naturally apply to
Ownership — services either exist or they don't; the worker doesn't report
partial coverage at the service level. We model "degraded" (above) as the
analog.

---

## 7. Filters

### 7.1 Filter bar layout

Single horizontal row, wraps on tablet, stacks on mobile.

```
[ SearchInput "Buscar service…"           ] [ Squad ▾ ] [ Status ▾ ] [ Confidence ▾ ] [ Limpar filtros ]
```

### 7.2 Filter definitions

| Filter | Type | Options | URL param |
|---|---|---|---|
| Search | debounced text | free text | `?q=` |
| Squad | single-select combobox (SquadCombobox) | `[Todas, ...qualified_squads.map(name)]` | `?squad=` |
| Status | chip group | All / Qualificado / Tag fora do tenant / Sem dono | `?status=` |
| Confidence | chip group | All / Override / Via tag / Via alias / Nenhum | `?confidence=` |

### 7.3 URL state

Use TanStack Router `useSearch()` + `Navigate({ search: ... })` for all four
params. This:
- Enables deep-linking ("Bruno send Carlos a link to all unqualified
  services")
- Survives browser refresh
- Is the convention we want to establish for filter-heavy pages going forward

If the impl finds this overkill, fall back to local `useState` and add a
follow-up task.

### 7.4 Filter logic (client-side)

```ts
const filtered = useMemo(() => {
  return data.services.filter((s) => {
    if (q && !s.service_name.toLowerCase().includes(q.toLowerCase())) return false;
    if (squad && s.effective_squad_key !== squad) return false;
    if (status === 'qualified' && !s.is_qualified_squad) return false;
    if (status === 'unqualified' && (s.is_qualified_squad || !s.effective_squad_key)) return false;
    if (status === 'orphan' && s.effective_squad_key) return false;
    if (confidence === 'override' && !s.override_squad_key) return false;
    if (confidence === 'tag' && s.inferred_confidence !== 'tag') return false;
    if (confidence === 'alias' && s.inferred_confidence !== 'alias') return false;
    if (confidence === 'none' && s.inferred_confidence !== 'none') return false;
    return true;
  });
}, [data.services, q, squad, status, confidence]);
```

All client-side — 473 rows × 4 predicates is microseconds. For
post-R2 scale-out (1k+ rows), revisit (see open question Q3 below).

---

## 8. Override modal

### 8.1 Trigger

In each row's actions column, a `<button>` reads "Definir" if no override,
"Editar" if override exists. Clicking calls `onOpenOverride(service)`.

### 8.2 Modal contents

```
┌────────────────────────────────────────────────┐
│ Override de squad — {service_name}        [×]  │
├────────────────────────────────────────────────┤
│                                                │
│ Inferido por DD: {inferred_squad_key or '—'}   │
│                                                │
│ Definir squad efetiva                          │
│ [ SquadCombobox value={current} ▾           ]  │
│                                                │
│ Manter inferência = limpa o override.          │
│                                                │
├────────────────────────────────────────────────┤
│              [ Cancelar ]  [ Salvar override ] │
└────────────────────────────────────────────────┘
```

### 8.3 Behavior

- On open: focus moves to the SquadCombobox button
- On save with squad selected: call `useOverrideMutation` with `{ id,
  body: { squad_key } }`. Modal closes; optimistic update + invalidation.
- On save with "Manter inferência" / null: call `useClearOverrideMutation`.
  Modal closes.
- On close (X / Escape / backdrop): no mutation; focus returns to the
  trigger button.

---

## 9. Accessibility checklist (WCAG AA)

| Requirement | How met |
|---|---|
| **1.1.1** Non-text content has text alternatives | All icons have `aria-hidden="true"` + accompanying text; squad badges have both color + label + icon |
| **1.3.1** Info & relationships | Semantic HTML: `<main>`, `<section>`, `<table>` with `<th scope="col">`, `<button>` (not `<div onClick>`) |
| **1.4.3** Contrast (text) ≥ 4.5:1 | All token-based; **except** `text-content-tertiary` (#9CA3AF on white = 2.84). Phase 3 forbids using it for body text — only for icons and decorative dots. Filter labels use `text-content-secondary` (#6B7280 = 4.83:1) ✓ |
| **1.4.11** Non-text contrast ≥ 3:1 | Focus rings, button borders all use `--color-brand-primary` (#6366F1 on white = 4.21:1) ✓ |
| **2.1.1** Keyboard | Every interactive element reachable + actionable via keyboard (Tab, Shift+Tab, Enter, Space, Escape, Arrows where applicable) |
| **2.1.2** No keyboard trap (except modal) | Focus trap active **only** while modal is open; Escape exits |
| **2.4.3** Focus order | Logical: header → filters → table headers → first row actions → next row… |
| **2.4.7** Focus visible | `focus-visible:ring-2 focus-visible:ring-brand-primary` on every interactive element |
| **3.2.2** On input | Filter inputs don't trigger navigation on input; only Search triggers re-filter (debounced 300ms) |
| **3.3.1** Error identification | Error state has icon + colored card + text message + retry CTA |
| **4.1.2** Name, role, value | `aria-label` on icon-only buttons; `aria-expanded` on combobox trigger; `role="dialog" aria-modal="true"` on Modal; `aria-live="polite"` on inference-status announcer |
| **WCAG: inert background while modal open** | Set `inert` attribute on `<main>` parent when modal opens |
| **Status announcer** | "Inferência iniciada", "Override salvo", "Override removido" — announce via a single `<span role="status" aria-live="polite" className="sr-only">` near the top of the page |

### 9.1 Specific things to test in axe-core

- Color contrast pass on all text
- `aria-required-children` — no orphan tab-like elements (the prototype had
  this issue per frontend review §H)
- `dialog-name` — modal has accessible name via `aria-labelledby` pointing
  to title
- `button-name` — all buttons have accessible names
- `link-name` — Sidebar links have visible text

### 9.2 Keyboard test plan (in E2E)

1. Tab from page top: lands on first filter (SearchInput)
2. Continue Tab: each filter → "Run inference" → first column header (if
   sortable) → first row's "Definir" button → next row's button → …
3. Enter on "Definir": modal opens, focus on SquadCombobox button
4. Tab inside modal: combobox → Cancelar → Salvar → (loops back to
   combobox; **never escapes the modal**)
5. Escape: modal closes, focus returns to the "Definir" button that
   triggered it
6. Verify with screen reader: "Override de squad, dialog" announced on
   open; "Override salvo" announced on success

---

## 10. Analytics events

Following the conventions in `src/lib/analytics.ts`:

| Event | Properties |
|---|---|
| `obs_ownership_viewed` | `{ services_count, coverage_pct, qualified_count, unqualified_count }` |
| `obs_run_inference_clicked` | `{}` |
| `obs_override_set` | `{ service_id, squad_key, was_previously_overridden: boolean }` |
| `obs_override_cleared` | `{ service_id }` |
| `obs_filter_applied` | `{ field: 'q' \| 'squad' \| 'status' \| 'confidence', value }` |
| `obs_error_shown` | `{ error_message }` (truncated to 200 chars, no PII) |

Anti-surveillance check: never log `service_name`, `repo_url`, or any
free-text the user might type into search. Only enumerated values.

---

## 11. Responsive rules

| Breakpoint | Layout |
|---|---|
| Desktop ≥ 1280 | KPI grid 4-up, filter bar single row, table full-width |
| Tablet 768-1280 | KPI grid 2×2, filter bar wraps, table horizontal scroll |
| Mobile < 768 | KPI grid 1-col stack, filters stack vertically, table converts to card list (one card per service with all data + actions) |

Use Tailwind's `md:` / `lg:` breakpoints. The card fallback already exists
in `project-catalog-table.tsx:610-664` and can be cloned.

---

## 12. Test plan

### 12.1 Vitest (unit)

| File | Tests |
|---|---|
| `components/ui/Modal.test.tsx` | open/close, focus trap, Escape, backdrop click, return focus, body scroll lock |
| `components/ui/useFocusTrap.test.ts` | initial focus, Tab cycle, Shift+Tab, ignored when inactive |
| `components/ui/Table.test.tsx` | renders rows, sortable header toggle, empty state, loading state, row click handler |
| `components/ui/StatusBadge.test.tsx` | renders 6 variants, accessible label, icon present |
| `components/ui/SearchInput.test.tsx` | debounce, clear button, controlled value, aria-label required |
| `components/ui/Tabs.test.tsx` | active state via mock route, link targets |
| `hooks/useObservability.test.ts` (MSW) | useOwnershipQuery success/error, override mutation optimistic + rollback |
| `_components/observability/override-modal.test.tsx` | renders inferred value, save calls mutation, "Manter inferência" calls clear |

### 12.2 Playwright (E2E)

| Test | Description |
|---|---|
| `e2e/observability-ownership-happy.spec.ts` | Load page → see KPIs → click row → set override → verify badge updates |
| `e2e/observability-ownership-empty.spec.ts` | DD not connected → see empty-no-connection card → CTA link works |
| `e2e/observability-ownership-error.spec.ts` | API 500 → see error card → click retry → API succeeds → see data |
| `e2e/observability-ownership-keyboard.spec.ts` | Full keyboard-only journey (open modal, set override, return focus) |
| `e2e/observability-ownership-a11y.spec.ts` | axe-core scan on all 6 states |

### 12.3 Storybook (optional but recommended)

If a Storybook setup lands as a side-quest, write stories for each primitive
and each state of `OwnershipPage`. Not blocking.

---

## 13. Open questions

1. **Q1: Squad multi-select?** Frontend review §D.2 P1 asks for multi-select
   squad filter. Phase 3 ships with single-select. **Decision: defer to a
   follow-up task** unless `pulse-engineer` finds it cheaper to do now.
2. **Q2: Default squad sort order in combobox?** Prototype has tribe
   grouping. For obs, we don't have tribes mapped to squads — fall back to
   alphabetical, or do we want "qualified first" ordering? **Recommend
   alphabetical** because Bruno is using this for assignment, not for
   ranking.
3. **Q3: Client-side filter scale ceiling?** 473 services × 4 predicates =
   trivial. At 2-3k services (post-R2 enterprise tenants), the input
   debounce + memoization should still hold; need to revisit if axe-core
   reports re-render storm.
4. **Q4: Should the override modal allow free-text squad input?** Today's
   prototype constrains to `qualified_squads` only. **Keep this** — free
   text would create new orphan states. If Bruno needs to type a non-
   qualified squad, that's a signal he needs to create it elsewhere first.
5. **Q5: When the user clears an override, should the modal stay open
   showing "back to inferred" state, or close?** Recommend **close** —
   matches "set override" UX. The page re-render shows the new state.
6. **Q6: i18n strategy?** Existing pulse-web strings are PT-BR hardcoded
   in JSX. Stay consistent — PT-BR-only for Phase 3. Add i18n in a separate
   sweep.
7. **Q7: Optimistic update collision** — if Bruno clicks "Run inference"
   while an override mutation is in flight, what wins? Current pattern
   (TanStack Query) handles this: the mutation's `onSettled` invalidation
   triggers re-fetch; the inference response will arrive later and
   re-overwrite. **No special handling needed.**
8. **Q8: Recharts vs. Chart.js?** Not relevant to Ownership (no chart) but
   flagged for Phase 5. Resolve before Phase 5 starts.

---

## 14. Sequencing inside Phase 3

Recommended PR breakdown (engineer's call to merge as one or split):

1. **Sub-PR A — Primitives + tokens** (~6h): `Modal`, `useFocusTrap`,
   `Table`, `StatusBadge`, `SearchInput`, `Tabs`, 4 new tokens.
   All in `components/ui/` + globals.css. Vitest + axe coverage.
2. **Sub-PR B — API client + hooks** (~2h): `observability.ts` +
   `useObservability.ts`. MSW tests.
3. **Sub-PR C — Page** (~6h): parent layout, ownership page, all 6 states.
   Playwright + axe E2E.
4. **Sub-PR D — Sidebar + impl spec backport** (~1h): wire the nav entry +
   commit any tweaks discovered.

Single-PR alternative: ~16h target from master plan §3 Phase 3, all in one.
Review surface ~1,500 LoC.

---

## 15. Acceptance criteria (must all be checked)

- [ ] Page loads in <500ms on cold cache with 473 services
- [ ] All 6 state cases render correctly (verified via MSW-driven tests)
- [ ] axe-core scan = 0 critical/serious findings on all 6 states
- [ ] Keyboard-only journey works end-to-end (E2E test green)
- [ ] Focus returns to the trigger button after modal closes
- [ ] Inferred-alias visually distinct from inferred-tag (manual
      color-blind simulator check OK)
- [ ] Error state distinct from empty state (different copy, icon, color)
- [ ] Coverage % matches backend response exactly (no client math drift)
- [ ] No hardcoded hex in any new file (verified via `grep`)
- [ ] All new primitives have a Vitest unit test
- [ ] pulse-ux-reviewer signs off
- [ ] pulse-test-engineer signs off
- [ ] pulse-ciso signs off (if any new endpoints touched — Phase 2 covers
      most of this; Phase 3 is read-only on existing endpoints)

---

End of spec.
