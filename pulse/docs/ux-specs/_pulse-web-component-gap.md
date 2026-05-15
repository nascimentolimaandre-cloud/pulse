# pulse-web Component Gap — FDD-OBS-001 Phase 3 (and 4)

**Date:** 2026-05-11
**Source:** Cross-reference of
- `docs/reviews/FDD-OBS-001-frontend-review.md` (P0/P1 requirements)
- `docs/plans/FDD-OBS-001-remediation-master-plan.md` §3 Phase 3
- `_pulse-web-component-inventory.md` (what already exists)

This file enumerates **every component / token / pattern** Phase 3 and 4 need
that is **not** in pulse-web today. For each: classification (NEW / PARTIAL /
EXISTS-BUT-INCOMPLETE), LoC estimate, complexity, and the exact gap.

---

## Legend

- **NEW** — Nothing in pulse-web; build from scratch
- **PARTIAL** — A similar component exists in pulse-web but is too coupled to
  another domain; factor or rebuild
- **EXISTS** — Production-ready in pulse-web; reuse directly
- **EXISTS-BUT-INCOMPLETE** — Exists but does not meet the new requirements;
  delta documented

LoC = TypeScript/TSX lines, excluding tests.

---

## 1. Modal primitive

**Classification:** NEW (with reusable pattern from pipeline `EntityDrawer`)
**Path:** `components/ui/Modal.tsx`
**Estimate:** ~140 LoC + 60 LoC focus-trap hook + 80 LoC test

### Why we need it
- Phase 3: override modal on Ownership page (`_openModal` in
  `pulse-ui/.../app.js:259`)
- Phase 4: edit-alias modal + confirm-delete-alias modal
- The frontend review §A flags Modal absence as a P0 blocker (no focus
  trap, no return-focus); pulse-web has zero generic `<Modal>` today.

### What exists today
- `EntityDrawer.tsx:46-84` and `TeamDetailDrawer.tsx:50-90` — two hand-rolled
  side-drawers with focus trap. Both are coupled to their domain types and
  to a side-drawer layout (not a centred modal).
- `project-catalog-table.tsx:62-141` `ProjectDetailPanel` — yet another
  hand-rolled side panel; same pattern, third copy.

### Required API
```tsx
<Modal
  open={boolean}
  onClose={() => void}
  title={string | ReactNode}
  description?={string}        // for aria-describedby
  size?={'sm' | 'md' | 'lg'}   // 400 / 560 / 720 px
  initialFocusRef?={RefObject<HTMLElement>}
  returnFocusOnClose?={boolean}  // default true
>
  {children}
</Modal>
```

### Required behavior (delta vs. existing drawers)
1. **Focus trap** — Tab cycles only inside the modal. Shift+Tab also cycles.
2. **Initial focus** — first focusable element OR `initialFocusRef` if
   provided.
3. **Return focus on close** — store the trigger via `document.activeElement`
   on open; restore on close. **This is the bug flagged in frontend review
   §A.1 "P1 missing — focus return" and is missing from both existing
   drawers.** Fix it in the new primitive; backport to the drawers later
   (out of scope for FDD-OBS-001).
4. **Escape closes** — standard.
5. **Backdrop click closes** — standard, with `aria-hidden="true"` on backdrop.
6. **Inert background** — set `inert` attribute on `<main>` while modal is
   open so AT (and screen readers) don't read the background. Browser
   support: 92%+; for older browsers, polyfill via `aria-hidden="true"` on
   the sibling.
7. **Body scroll lock** — `document.body.style.overflow = 'hidden'` on
   mount, restore on unmount.

### Hook to extract
```tsx
// components/ui/useFocusTrap.ts
export function useFocusTrap(
  ref: React.RefObject<HTMLElement>,
  active: boolean,
  options?: { returnFocus?: boolean; initialFocus?: React.RefObject<HTMLElement> }
): void;
```
Behavior: while `active=true`, captures Tab/Shift+Tab and Escape.

---

## 2. Table primitive

**Classification:** PARTIAL (extract from `project-catalog-table.tsx`)
**Path:** `components/ui/Table.tsx` (+ `TableSortHeader.tsx`)
**Estimate:** ~220 LoC + 100 LoC test

### Why we need it
- Phase 3: Ownership table with 4 cols (service, inferred, override,
  effective, status, actions) over 473 rows
- Phase 4: Aliases table (vendor → squad + actions)
- Phase 5: Deploys table (sha, repo, env, time)
- Master plan §3 Phase 3 task T3.3 lists this as a primitive

### What exists today
- `project-catalog-table.tsx:382-441` — fully-functional sortable table with:
  - Sticky header (well, just `<thead>` with bottom border; not actually
    `position: sticky` — see delta below)
  - `SortableHeader` (lines 511-541) — clickable column header with
    ArrowUpDown icon
  - Hover row with action button reveal on `:hover`
  - Bulk select via checkbox column
  - Mobile card fallback below `md:`

The shape is tightly coupled to `JiraProjectCatalogEntry`. The primitive
should be generic.

### Required API
```tsx
<Table<TRow>
  rows={TRow[]}
  columns={ColumnDef<TRow>[]}    // { id, header, accessor, sortable, align?, width? }
  sortBy={string}
  sortDir={'asc' | 'desc'}
  onSort={(col, dir) => void}
  onRowClick?={(row) => void}    // optional — row navigation
  rowKey={(row) => string}
  // Optional features:
  selectable?={boolean}
  selectedKeys?={Set<string>}
  onToggleSelect?={(key) => void}
  onToggleSelectAll?={() => void}
  // Render slots:
  emptyState?={ReactNode}
  loadingRowCount?={number}      // shows skeleton rows when truthy
  mobileFallback?={(row) => ReactNode}  // optional card layout
/>
```

### Delta vs. existing
- **Make `<thead>` actually sticky** — frontend review notes the existing
  table is not sticky-headed; ours needs to be for 473-row Ownership.
  CSS: `position: sticky; top: 0;` on thead, plus a `z-index` and
  background.
- **Generic over `TRow`** — the existing is hardcoded for Jira projects.
- **Decouple from bulk-select** — make it opt-in via `selectable` prop.
  Ownership table doesn't need bulk select; Aliases might want bulk-delete
  later.
- **No pagination built-in** — pagination is a layout concern, not a table
  concern. Caller wraps with their own paginator. (The existing project
  table has it inline — that's a layout coupling we want to avoid.)

---

## 3. StatusBadge primitive

**Classification:** NEW (similar to pipeline `Badge`, but different vocab)
**Path:** `components/ui/StatusBadge.tsx`
**Estimate:** ~80 LoC + 40 LoC test

### Why we need it
- Frontend review §G lists this as a "must promote to DS"
- Frontend review §D.1 explicitly flags `inferred-alias` vs. `inferred-tag`
  as a **P0** distinction that the prototype gets wrong (identical visual)
- Phase 4 (Aliases) will reuse the same badge

### What exists today
- `pipeline/shared/Badge.tsx:18-35` — exists but reads from
  `getStatusConfig(StatusKey)` where `StatusKey` is the Pipeline vocabulary
  (running, healthy, degraded, error, idle, ...). Not applicable.
- `project-catalog-table.tsx:15-32` `StatusChip` — Jira-domain status
  (discovered, active, paused, blocked, archived). Not applicable.
- `globals.css` / `tailwind.config.ts` — soft status colors exist as
  `bg-status-successBg` etc., usable but not packaged.

### Required API
```tsx
<StatusBadge
  variant={
    | 'qualified'        // green dot + "qualificado"
    | 'inferred-tag'     // brand-light bg + "via tag"
    | 'inferred-alias'   // amber-soft bg + "via alias"    ← MUST be visually distinct from inferred-tag
    | 'override'         // indigo solid + "override"
    | 'orphan'           // grey neutral + "sem dono"
    | 'unqualified'      // warn-soft + "tag fora do tenant"
  }
  size?={'xs' | 'sm'}
  withIcon?={boolean}
/>
```

### Required behavior (delta vs. prototype P0)
- **Color is NOT the only signal** — every variant has a unique label string
  + a unique leading symbol (dot color OR icon shape).
- **Inferred-tag** uses indigo brand color + `Tag` icon (lucide).
- **Inferred-alias** uses amber + `Link2` icon (lucide), per frontend
  review §D.1 P0.
- **Override** uses solid brand-primary + `Pencil` icon to read as "manual
  intervention applied".
- **Tooltips** — each variant optionally renders `<InfoTooltip>` explaining
  the state.

### Map to tokens
| Variant | Background | Foreground | Icon |
|---|---|---|---|
| qualified | `bg-status-successBg` (or new `--color-success-soft`) | `text-status-successText` | `<Check>` |
| inferred-tag | `bg-brand-light` | `text-brand-primary-hover` | `<Tag>` |
| inferred-alias | `bg-status-warningBg` (or new `--color-warning-soft`) | `text-status-warningText` | `<Link2>` |
| override | `bg-brand-primary` | `text-content-inverse` | `<Pencil>` |
| orphan | `bg-surface-tertiary` | `text-content-tertiary` | `<MinusCircle>` |
| unqualified | `bg-status-warningBg` | `text-status-warningText` | `<AlertTriangle>` |

---

## 4. SearchInput primitive

**Classification:** PARTIAL (exists ad-hoc in 3 places)
**Path:** `components/ui/SearchInput.tsx`
**Estimate:** ~60 LoC + 30 LoC test

### Why we need it
- Phase 3, 4, 5 all need a search input
- 3 hand-rolled versions exist already (see below) — time to consolidate

### What exists today (all ad-hoc, duplicated)
- `project-catalog-table.tsx:286-300` — search-icon prefix + uncontrolled
  reset
- `TeamCombobox.tsx:121-135` — search inside dropdown
- `jira.audit.tsx` (probable; not read in this audit)

### Required API
```tsx
<SearchInput
  value={string}
  onChange={(value: string) => void}
  placeholder?={string}
  ariaLabel={string}
  debounceMs?={number}     // default 300
  size?={'sm' | 'md'}
  autoFocus?={boolean}
  onClear?={() => void}    // shows × button when truthy
/>
```

### Required behavior
- Search icon prefix (`lucide-react/Search`)
- Optional clear button (`lucide-react/X`)
- Debounced `onChange` — pass `debounceMs={0}` for instant
- `aria-label` required (search inputs are notoriously bad for AT)
- Focus ring via `focus:ring-2 focus:ring-brand-primary`

The debounce is the only "new" capability — but Ownership table over 473
rows needs it. Without debounce, re-render storm on every keystroke.

---

## 5. Tabs primitive

**Classification:** PARTIAL (factor out of `jira.tsx`)
**Path:** `components/ui/Tabs.tsx`
**Estimate:** ~60 LoC + 30 LoC test

### Why we need it
- Phase 3: Ownership / Aliases tabs under Observability Settings
- Future: more settings tab pages will land

### What exists today
- `jira.tsx:50-73` — inline JSX for tab bar with active state via
  `useMatchRoute`. Works perfectly, but not extracted.

### Required API
```tsx
<Tabs>
  <Tabs.Item to="/settings/integrations/observability/ownership">Ownership</Tabs.Item>
  <Tabs.Item to="/settings/integrations/observability/aliases">Aliases</Tabs.Item>
</Tabs>
```

Internally uses TanStack Router's `<Link>` and `useMatchRoute({ to,
fuzzy: true })` to compute active state. The visual style matches `jira.tsx`
exactly.

### Delta vs. inline
- Extract for reuse across `jira.tsx`, new `observability.tsx`, and any
  future settings pages
- Take `<Tabs.Item to={...}>` children OR an array prop — either works
- Keep the visual identical (no design change)

---

## 6. Soft-color tokens

**Classification:** NEW (tokens layer)
**Path:** `pulse/pulse-ui/tokens.css` + `pulse/packages/pulse-web/src/globals.css`
**Estimate:** ~8 lines per file + Tailwind theme wiring

### What we add
```css
:root {
  /* Soft status backgrounds — for inline tinted areas (badges, banners) */
  --color-success-soft: #ECFDF5;   /* emerald-50 */
  --color-warning-soft: #FFFBEB;   /* amber-50 */
  --color-danger-soft:  #FEF2F2;   /* red-50 */
  --color-info-soft:    #EFF6FF;   /* blue-50, bonus — used by suggestions banner */

  /* Modal/drawer scrim */
  --color-overlay:      rgba(17, 24, 39, 0.4);  /* gray-900 @ 40% */
}
```

(Add `--color-info-soft` opportunistically — `SmartSuggestionsBanner` and
the alias suggestions banner both want it.)

### Tailwind theme wiring
In `tailwind.config.ts`, replace the hex literals at lines 31-44 with
`var(--color-*)` references. This unifies the two systems.

```ts
status: {
  // ...
  success: 'var(--color-success)',
  successBg: 'var(--color-success-soft)',   // was '#ECFDF5'
  successText: '#065F46',                    // unchanged — text colors are darker, not tokenized yet
  // same pattern for warning/danger/info
  // idle stays as-is
}
```

Backward-compatible: existing usages of `bg-status-successBg` keep working
because the Tailwind class resolves to the new variable.

---

## 7. Squad combobox

**Classification:** PARTIAL (refactor or duplicate `TeamCombobox`)
**Path:** TBD — see decision below
**Estimate:** ~150 LoC (refactor) or ~180 LoC (duplicate)

### Why we need it
- Phase 3 override modal: pick from `qualified_squads`
- Phase 4 edit-alias modal: pick from `qualified_squads`
- (Possibly Phase 5 filter bar: filter timeline by squad)

### What exists today
- `TeamCombobox.tsx:11-196` — production combobox with tribe grouping,
  search filter, tier badges. Reads `TeamHealth` (Pipeline domain).

### Decision required
- **Option A (refactor):** generalize `TeamCombobox<TItem>` with prop-driven
  rendering. Higher upfront cost (touches Pipeline page), but no duplication.
- **Option B (duplicate):** copy as `SquadCombobox` for obs domain. Faster
  but creates lint debt.

**Recommendation:** Option B for Phase 3 (ship faster); Option A as a
follow-up tech-debt PR after Phase 5 lands. Document this in the impl spec.

---

## 8. BulkPasteForm (Phase 4 only)

**Classification:** NEW
**Path:** `components/ui/BulkPasteForm.tsx` (or page-private)
**Estimate:** ~120 LoC + 80 LoC test

### Why
- Phase 4 needs the bulk-paste textarea + parse + result panel
- Frontend review §E.1 flags multiple P0/P1: per-line error markers,
  documented case-sensitivity, downloadable error report

### Required behavior delta vs. prototype
- **Per-line error markers** — render the textarea with line-numbered
  error pills beside it. On parse, mark line 3 as "squad inválido".
- **Live preview** — as the user types, show count of valid / invalid /
  duplicate rows in a side panel. Don't wait for submit.
- **Case-handling documented** — `vendor.toLowerCase()` either stays
  (documented as automatic) or is removed (documented as case-preserving).
  Phase 4 spec must pick.
- **Download-on-error** — if 5+ lines fail, offer "Download rejection
  report" button that emits a CSV with original line + reason.

This is genuinely new UX. Estimate is conservative.

---

## 9. Things to REUSE from the prototype (no rewrite)

Frontend review §F.1 listed prototype-side code duplication. **None of it
needs to be ported.** The React port erases this via TanStack Query +
React idioms. Specifically:

- `_escape()` — React auto-escapes JSX expressions; trash this
- `_formatRelative()` — already exists in pulse-web as a utility (search
  `formatDuration.ts` / `formatters.ts` in FlowHealth); reuse or extract
- `_formatHour()` / `_formatTick()` — chart axis formatting; use
  `date-fns` (already a transitive dep of tremor) or `Intl.DateTimeFormat`
- DOMContentLoaded → fetch → render scaffold — React lifecycle handles
  this; nothing to port
- Modal open/close logic — replaced by `<Modal>` primitive (item 1)

### Things that DO map to React but need adaptation:
- **Coverage % calculation** in `_renderKpis()` of
  `pulse-ui/.../app.js:60-76` — keep the formula, move to a `useMemo` in
  the React page (or even server-side in the API response). Simple.
- **Squad-resolution priority** (override > inferred-alias > inferred-tag
  > none) — already encoded in the API response as `effective_squad_key`,
  so the React page just reads it.

---

## 10. Summary table

| Item | New / Partial / Exists | LoC | Phase | Complexity |
|---|---|---|---|---|
| `Modal` primitive + `useFocusTrap` hook | NEW | 200 | 3 | Medium (focus trap is fiddly) |
| `Table` primitive | PARTIAL | 220 | 3 | Medium (generic over TRow) |
| `StatusBadge` primitive | NEW | 80 | 3 | Low |
| `SearchInput` primitive | PARTIAL | 60 | 3 | Low |
| `Tabs` primitive | PARTIAL | 60 | 3 | Low |
| 4 soft-color tokens | NEW | 8 | 3 | Trivial |
| Tailwind theme rewire | Refactor | 20 | 3 | Trivial |
| `SquadCombobox` | PARTIAL | 180 | 3 | Low (clone TeamCombobox) |
| `OwnershipTable` (page-private) | NEW | 200 | 3 | Low (uses primitives) |
| `OverrideModal` (page-private) | NEW | 120 | 3 | Low |
| `ownership.ts` API client | NEW | 140 | 3 | Low |
| `useOwnership` / `useOverrideMutation` hooks | NEW | 120 | 3 | Low (clones Jira pattern) |
| Sidebar nav extension | Edit | 4 | 3 | Trivial |
| `BulkPasteForm` (page-private) | NEW | 120 | 4 | Medium |
| `AliasesTable` (page-private) | NEW | 150 | 4 | Low |
| `EditAliasModal` (page-private) | NEW | 80 | 4 | Low |
| `AliasSuggestionsBanner` (page-private) | NEW | 80 | 4 | Low |
| `ConfirmDialog` (variant of Modal) | NEW | 60 | 4 | Low |
| Alias hooks / API client extension | NEW | 120 | 4 | Low |

**Phase 3 total: ~1,400 LoC code + ~600 LoC tests = ~2,000 LoC**
**Phase 4 total: ~610 LoC code + ~300 LoC tests = ~910 LoC**

Aligns with the master plan's ~16h Phase 3 + ~10h Phase 4 estimate at
production velocity.

---

## 11. Risks and unknowns

1. **TanStack Router `Tabs` linking strategy** — current `jira.tsx`
   pattern uses string `to` props. TanStack Router's stricter typing
   prefers route objects. The primitive should accept either; verify in
   Phase 3 spike.
2. **Bundle size for new icons** — `Tag`, `Link2`, `Pencil`, `MinusCircle`
   are all in `lucide-react` already imported in other files; no new
   import cost. (Tree-shaken per icon.)
3. **`inert` attribute browser support** — Chrome 102+, Safari 15.5+,
   Firefox 112+. As of 2026-05 should be ~96%+. If not, fallback to
   `aria-hidden="true"` on siblings + focus trap.
4. **Recharts vs. Chart.js for Phase 5** — flagged in inventory §10.
   Not a Phase 3 blocker. Resolve before Phase 5 starts.
5. **Sidebar IA refactor** — adding 2 obs nav items extends the flat list
   to 12 items. Approaching the threshold where grouping becomes useful.
   Not a Phase 3 blocker but flag for IA pass.

---

End of gap list.
