# UX Implementation Spec — Team Aliases (FDD-OBS-001 Phase 4)

**Status:** Ready for `pulse-engineer` to implement **after** Phase 3 merges
**Phase:** 4 of FDD-OBS-001 remediation
**Depends on:**
- Phase 1 + Phase 2 merged (backend + pulse-api proxy live)
- **Phase 3 merged** — this spec relies on primitives that Phase 3 ships
**Persona:** Bruno (Platform Engineer) — wants 1-click way to map Datadog `team:foo` tags he can't (or won't) change at source to canonical PULSE squad keys
**Author:** pulse-frontend (audit-only role)
**Source:** Prototype at `pulse/pulse-ui/pages/observability-ownership/aliases.{html,css,js}`; review at `docs/reviews/FDD-OBS-001-frontend-review.md` §E

---

## 1. Objective & scope

### 1.1 What ships
A production-ready React page at `/settings/integrations/observability/aliases`
that:
- Lists current vendor-team → squad-key aliases with edit / delete actions
- Surfaces a banner of **unmapped vendor teams** (suggestions from rollup)
- Lets Bruno bulk-paste CSV rows (`vendor_team,squad_key`) to create/update
  many at once
- Lets Bruno edit a single alias via modal
- Lets Bruno delete an alias via inline `ConfirmDialog` (not native
  `confirm()`)
- Hits all 6 explicit UI states
- Passes WCAG AA via axe-core

### 1.2 Out of scope (Phase 4)
- Versioning / audit log of alias edits — Phase 6 if needed
- Conflict-resolution UI for two aliases pointing to different squads — the
  API enforces uniqueness on `vendor_team_value`; client just shows the
  error
- Bulk-delete checkboxes — defer (single-delete is enough for now)

---

## 2. Design rationale

The prototype review classified Aliases as **medium risk** (2 P0, 7 P1).
Phase 4 must close the P0s:

- **P0**: focus trap on edit modal (today: Tab escapes the modal)
- **P0**: `vendor.toLowerCase()` silently transforms input — document or
  remove

Plus high-leverage P1s:
- Replace native `confirm()` with accessible `ConfirmDialog`
- Per-line bulk-paste error markers
- Suggestion chips become clickable (one-click-to-map)
- Skeleton rows on initial load
- Error state distinct from empty state

The page is intentionally **simpler** than Ownership — it's a CRUD list with
a bulk-paste affordance. Most of the complexity is in the bulk paste.

---

## 3. Dependencies on Phase 3

This spec assumes Phase 3 has shipped (or will ship in parallel and merge
before Phase 4). Specifically, Phase 4 requires:

### 3.1 Primitives from `components/ui/`
- `<Modal>` + `useFocusTrap` hook → for edit modal + confirm-delete modal
- `<Table>` → for the aliases list
- `<StatusBadge>` → not strictly required, but if we surface validation
  state per row, this is the badge
- `<SearchInput>` → for filtering aliases by vendor or squad
- `<Tabs>` → the parent layout from Phase 3 (`observability.tsx`) already
  has tabs registered; Phase 4 just slots in the second tab

### 3.2 Tokens
- The 4 soft-color tokens (`--color-success-soft`, `--color-warning-soft`,
  `--color-danger-soft`, `--color-overlay`) shipped in Phase 3 — Phase 4
  reuses, adds nothing new

### 3.3 Patterns
- Page-state discriminated union pattern (see Phase 3 spec §6)
- Optimistic-update mutation pattern (from `useJiraAdmin.ts` → adopted in
  Phase 3 `useObservability.ts`)
- Filter state in URL via `useSearch` (Phase 3 establishes; Phase 4
  extends)

### 3.4 API client
- Phase 4 **extends** `src/lib/api/observability.ts` and
  `src/hooks/useObservability.ts` with alias-specific functions/hooks; does
  not create new files

### 3.5 Parent route
- `src/routes/_dashboard/settings/integrations/observability.tsx` already
  exists from Phase 3 (parent route with Tabs)
- Phase 4 adds the **child** route file: `observability.aliases.tsx`

### 3.6 Sidebar
- Phase 3 added the `Observability` entry; Phase 4 does not touch the
  sidebar

---

## 4. Information architecture & routing

### 4.1 Route
```
/settings/integrations/observability/aliases
```
File: `src/routes/_dashboard/settings/integrations/observability.aliases.tsx`

### 4.2 New files (Phase 4 only)

```
src/routes/_dashboard/settings/integrations/
  observability.aliases.tsx                          ← THIS PAGE (new)
  _components/observability/
    aliases-suggestions-banner.tsx                   ← new
    aliases-table.tsx                                ← new
    aliases-bulk-paste.tsx                           ← new
    aliases-bulk-result.tsx                          ← new
    edit-alias-modal.tsx                             ← new
    confirm-delete-alias-dialog.tsx                  ← new (or use generic ConfirmDialog if Phase 3 shipped it)
```

### 4.3 Optional primitive — `ConfirmDialog`

If Phase 3 already shipped `ConfirmDialog` as a Modal variant (gap doc
§ Phase 4 item), reuse it. Otherwise Phase 4 ships it here:

```tsx
<ConfirmDialog
  open={boolean}
  onConfirm={() => void}
  onCancel={() => void}
  title="Remover alias?"
  message="Tem certeza que deseja remover o alias para…"
  confirmLabel="Remover"
  cancelLabel="Cancelar"
  destructive   // colors the confirm button red
/>
```

Internally just wraps `<Modal size="sm">` with focused button layout. ~60 LoC.

---

## 5. Component composition

### 5.1 Tree

```
<observability.aliases route>
  <AliasesPage>
    <FreshnessBanner />                            (conditional)
    <AliasesSuggestionsBanner />                   (conditional — only if suggestions.length > 0)
    <section grid 2-col on desktop, 1-col on mobile>
      <div>                                        (left column)
        <SearchInput placeholder="Buscar vendor ou squad…" />
        <AliasesTable />                           wraps <Table>
      </div>
      <aside>                                      (right column, sticky on desktop)
        <AliasesBulkPaste />                       textarea + parse + result
      </aside>
    </section>
    <EditAliasModal />                             (renders conditionally)
    <ConfirmDeleteAliasDialog />                   (renders conditionally)
  </AliasesPage>
</observability.aliases route>
```

### 5.2 Primitives used

| Primitive | Source | New / Reused |
|---|---|---|
| `Modal` | `components/ui/Modal.tsx` (Phase 3) | REUSE |
| `useFocusTrap` | `components/ui/useFocusTrap.ts` (Phase 3) | REUSE |
| `Table` | `components/ui/Table.tsx` (Phase 3) | REUSE |
| `SearchInput` | `components/ui/SearchInput.tsx` (Phase 3) | REUSE |
| `Tabs` | parent route in `observability.tsx` (Phase 3) | REUSE |
| `SquadCombobox` | (Phase 3) | REUSE |
| `KpiCard` | (always existed) | not used on Aliases (no KPI banner; spec page §6.3 below) |
| `InfoTooltip` | (always existed) | REUSE for "what's a vendor team?" |
| `FreshnessBanner` | (always existed) | REUSE if data stale |
| `ConfirmDialog` | NEW (this spec) OR (Phase 3 if it shipped) | maybe NEW |

---

## 6. Page sections (top to bottom)

### 6.1 Suggestions banner (top of page, conditional)

Displays when `data.suggestions.length > 0`. Soft amber background using
`--color-warning-soft`. Renders as a horizontal scrollable chip list:

```
┌─ Vendor teams sem alias ─────────────────────────────────────────────┐
│ Esses team-tags vêm do Datadog mas não têm squad mapeado.           │
│ Clique em um para começar a criar o alias.                          │
│                                                                      │
│ [agenda-facil] [arquitetura] [car10] [crm] [encontrar-oferta] [+5]  │
└──────────────────────────────────────────────────────────────────────┘
```

**Behavior delta vs. prototype (frontend review §E.3 P1):**
- Chips are `<button>` elements, **not** `<li>` — keyboard focusable
- Clicking a chip prepends `vendor_team,` (the chip's text + comma) into the
  bulk-paste textarea **and** scrolls/focuses the textarea
- After alias is created, the chip disappears from the banner (or the whole
  banner collapses if list goes empty) via TanStack Query invalidation

### 6.2 No KPI banner

Unlike Ownership, Aliases doesn't need a 4-KPI banner — the suggestions
banner already surfaces the most useful counter ("X unmapped teams"). Add
a single inline counter above the table: "Aliases configurados: N".

### 6.3 Aliases table

Columns:
| Column | Width | Sortable | Renders |
|---|---|---|---|
| Vendor team | flex | yes | `<code>` monospace of `vendor_team_value` |
| → | 24px | no | arrow glyph |
| Squad | 120px | yes | `<StatusBadge variant="qualified">` of `squad_key` |
| Atualizado | 120px | yes | relative time of `updated_at` |
| Ações | 80px | no | Edit + Delete buttons |

Action buttons: `Edit` opens edit modal; `Delete` opens
`ConfirmDeleteAliasDialog`. Both inherit Phase 3 focus-return behavior from
`<Modal>`.

Empty-state row: "Nenhum alias configurado. Cole linhas no painel ao
lado para começar."

### 6.4 Bulk paste panel (right column, desktop)

```
┌─ Importar em massa ─────────────────────────────┐
│ Cole uma linha por alias: `vendor_team,squad_key`│
│                                                  │
│ ┌────────────────────────────────────────────┐  │
│ │ agenda-facil,FACIL                          │  │
│ │ crm,CRMC                                    │  │
│ │ estoque,ESTQ                                │  │
│ │                                             │  │
│ └────────────────────────────────────────────┘  │
│ Total: 3 linhas · 3 válidas · 0 inválidas        │
│ [ Limpar ]                    [ Importar 3 ]    │
└──────────────────────────────────────────────────┘
```

#### 6.4.1 Live preview

As the user types (debounced 300ms), parse the textarea and update the
counter line:

```ts
type ParseResult = {
  total: number;
  valid: ParsedRow[];
  invalid: { line: number; raw: string; reason: 'empty' | 'malformed' | 'unknown_squad' | 'duplicate' }[];
};
```

Validation rules:
- Empty line → skip silently (don't count)
- Line with !=1 comma → `malformed`
- Squad not in `qualified_squads` → `unknown_squad`
- Vendor already in textarea on a different line → `duplicate`

Case-handling (resolves frontend review §E.1 P0): **make it explicit**.
The textarea preserves user case. The API call sends the value verbatim.
**Add a checkbox below the textarea**: "[ ] Lowercase vendor (compat com
DD)". Default checked. Document in the placeholder.

#### 6.4.2 Per-line error markers

Use a CSS Grid layout: line numbers in a left gutter colored according to
parse status:

```
1 ✓  agenda-facil,FACIL
2 ✗  crm                         ← red gutter
3 !  estoque,UNKNOWN             ← amber gutter
4 ✓  car10,CAR
```

Implementation hint: render the textarea as a controlled component with a
"shadow" div positioned absolutely behind it that paints the per-line
markers. Or simpler: render the markers as a flexbox column **next to** the
textarea, with each marker's height pinned to the textarea's line-height
(`1.5em`). Both work; pick the simpler.

#### 6.4.3 Submit

On click "Importar N":
- Call `useBulkImportAliasesMutation` with the array of valid rows
- During mutation: disable both buttons, show inline spinner on Import
- On success: render result panel below buttons:
  ```
  ✓ 2 inseridas, 1 atualizada
  ```
- On partial fail (server returns 207 multi-status or similar): list which
  failed and why:
  ```
  ✓ 2 inseridas, 0 atualizadas
  ✗ 1 rejeitada: 'crm' já existe com outra squad (CRMC)
  ```
- Offer "[ Download relatório CSV ]" if 5+ rejected (frontend review §E.1)
  P1)
- Auto-clear textarea on full success; preserve on partial fail

#### 6.4.4 Mobile layout

Below 1100px the panel **stacks below** the table, not to the side.

---

## 7. Edit alias modal

### 7.1 Trigger

Row's "Editar" action button.

### 7.2 Modal contents

```
┌────────────────────────────────────────────────┐
│ Editar alias                               [×]  │
├────────────────────────────────────────────────┤
│ Vendor team                                     │
│ {vendor_team_value} (read-only)                 │
│                                                 │
│ Squad                                           │
│ [ SquadCombobox value={alias.squad_key} ▾  ]   │
├────────────────────────────────────────────────┤
│              [ Cancelar ]  [ Salvar alteração ] │
└────────────────────────────────────────────────┘
```

Vendor field is read-only (key is immutable; to change it, delete + create).

### 7.3 Behavior

- On open: focus on SquadCombobox
- On save: `useUpdateAliasMutation({ vendor, body: { squad_key } })` —
  optimistic update; on error, revert + show inline error
- On cancel / Escape / backdrop: close, no mutation

---

## 8. Delete confirmation

Frontend review §E + §A list native `confirm()` as P1 to replace. Phase 4
uses a `<ConfirmDialog>` (small Modal variant).

```
┌────────────────────────────────────────────────┐
│ Remover alias?                            [×]  │
├────────────────────────────────────────────────┤
│ Tem certeza que deseja remover o alias para     │
│ "{vendor_team_value}" → {squad_key}?           │
│                                                 │
│ Isso fará com que serviços com este team-tag    │
│ voltem a ser inferidos sem alias.               │
├────────────────────────────────────────────────┤
│              [ Cancelar ]   [ Remover ]        │
└────────────────────────────────────────────────┘
```

`Remover` button uses `bg-status-danger text-content-inverse` (NOT just
`bg-red-600` — must use tokens).

---

## 9. Data fetching

### 9.1 API endpoints (post-Phase 2)

| Verb | Path | Purpose |
|---|---|---|
| GET | `/api/v1/admin/integrations/datadog/aliases` | List + suggestions |
| POST | `/api/v1/admin/integrations/datadog/aliases/bulk` | Bulk insert/update |
| PUT | `/api/v1/admin/integrations/datadog/aliases/{vendor_team_value}` | Update single |
| DELETE | `/api/v1/admin/integrations/datadog/aliases/{vendor_team_value}` | Delete single |
| GET | `/api/v1/admin/integrations/datadog/aliases/suggestions` | (optional separate endpoint) |

Response shape for GET:
```ts
{
  aliases: { vendor_team_value: string; squad_key: string; created_at: string; updated_at: string }[];
  suggestions: string[];                  // unmapped vendor teams from rollup
  qualified_squads: { key: string; name: string }[];
}
```

### 9.2 API client (extends `lib/api/observability.ts`)

Add to the existing file:
```ts
export async function listAliases(): Promise<ObsAliasesResponse> { ... }
export async function bulkImportAliases(rows: ObsAliasBulkRow[]): Promise<ObsAliasBulkResult> { ... }
export async function updateAlias(vendor: string, body: { squad_key: string }): Promise<ObsAlias> { ... }
export async function deleteAlias(vendor: string): Promise<void> { ... }
```

### 9.3 Hooks (extends `hooks/useObservability.ts`)

Add query keys + hooks:
```ts
obsKeys.aliases = () => [...obsKeys.all, 'aliases'] as const;

export function useAliasesQuery() { ... staleTime: 60_000 }
export function useUpdateAliasMutation() {
  // optimistic pattern, identical to override mutation
}
export function useDeleteAliasMutation() {
  // optimistic: remove row from list, on error restore
}
export function useBulkImportAliasesMutation() {
  // NOT optimistic — too many rows; show inline result instead
  // On settled, invalidate aliases query
}
```

### 9.4 Cross-page invalidation

After any alias mutation, **also invalidate** the Ownership query
(`obsKeys.ownership()`). Reason: changing an alias affects which squad a
service resolves to (alias → effective squad). Bruno expects to see the
coverage % update after saving an alias.

---

## 10. State machine

```ts
type PageState =
  | { kind: 'loading' }
  | { kind: 'empty-no-aliases'; suggestions: string[] }   // first-time: render hero CTA
  | { kind: 'healthy'; data: ObsAliasesResponse }
  | { kind: 'degraded'; data: ObsAliasesResponse }        // suggestions.length > aliases.length * 0.5
  | { kind: 'error'; error: Error };
```

(No "warming-up" state — aliases are user-curated, not worker-generated.)
(No "partial" state — atomic CRUD.)

### Renderings
- **Loading**: 4 skeleton rows + skeleton bulk-paste panel
- **Empty-no-aliases**: empty-state hero "Comece criando seu primeiro
  alias" + the bulk-paste panel front and center (no table)
- **Healthy**: full layout
- **Degraded**: full layout + persistent suggestions banner; the banner
  itself does the work of "tell Bruno he has cleanup to do"
- **Error**: error card with "Tentar novamente"

---

## 11. Accessibility checklist (WCAG AA)

Same baseline as Phase 3 spec §9, plus aliases-specific:

| Requirement | How met |
|---|---|
| Bulk paste textarea labeled | `<label>` linked to `<textarea>` via `htmlFor` |
| Bulk paste counter announced | `<span role="status" aria-live="polite">3 válidas, 0 inválidas</span>` — updates with debounce |
| Bulk paste result announced | Same pattern, separate region after submit |
| Per-line error markers accessible to AT | Either (a) render line markers with `aria-label="Linha 3: squad inválido"` on each, OR (b) keep markers visual-only and the `aria-live` summary above is sufficient. Recommend (b) — simpler, AT users get the summary |
| Confirm dialog has accessible name | `aria-labelledby` pointing to title |
| Confirm dialog destructive button | Visible label "Remover" + color cue + dialog message explains consequence |
| Suggestion chips focusable | `<button>` not `<li>` (closes frontend review §H finding) |
| Suggestion chip click feedback | `aria-live="polite"` announces "Vendor team 'crm' adicionado ao paste" |
| Read-only vendor field in edit modal | `<input readonly>` or just `<dd>` text — read-only widgets need correct semantic markup |

### 11.1 Color-blind check

- Per-line markers use 3 colors (green ✓ / red ✗ / amber !) — **also use
  shape**: ✓ vs ✗ vs ! glyph. Color is redundant cue.
- Result banner uses bg color + icon — same redundancy

---

## 12. Analytics events

| Event | Properties |
|---|---|
| `obs_aliases_viewed` | `{ aliases_count, suggestions_count }` |
| `obs_alias_bulk_imported` | `{ inserted, updated, rejected, lowercase: boolean }` |
| `obs_alias_edited` | `{ vendor_team_hash, squad_key, was_squad_key }` (hash vendor — could be PII-ish) |
| `obs_alias_deleted` | `{ vendor_team_hash }` |
| `obs_alias_suggestion_clicked` | `{ vendor_team_hash }` |
| `obs_alias_bulk_paste_parse_error` | `{ reason }` (one of empty / malformed / unknown_squad / duplicate; aggregated counts) |

**Anti-surveillance:** never log the raw vendor team value or squad key.
Hash `vendor_team_value` with a stable hash (SHA-1 first 8 chars) — never
log full values. Squad key is a tenant config concept, OK to log
enumerated value.

---

## 13. Responsive rules

| Breakpoint | Layout |
|---|---|
| Desktop ≥ 1100 | 2-column (table left, bulk paste right, panel sticky) |
| Tablet 768-1100 | Single column, bulk paste below table, suggestions banner still horizontal scroll |
| Mobile < 768 | Single column, suggestions chips wrap to multi-row, table converts to cards |

---

## 14. Test plan

### 14.1 Vitest (unit)

| File | Tests |
|---|---|
| `_components/observability/aliases-bulk-paste.test.tsx` | parse empty, parse malformed, parse with unknown squad, parse duplicates, lowercase toggle, submit success/partial/fail |
| `_components/observability/edit-alias-modal.test.tsx` | open/close, save calls mutation with right params, vendor field is read-only |
| `_components/observability/confirm-delete-alias-dialog.test.tsx` | open/close, confirm calls onConfirm |
| `_components/observability/aliases-suggestions-banner.test.tsx` | renders chips, click fills textarea, hides when empty |
| `_components/observability/aliases-table.test.tsx` | renders rows, sort by squad, sort by updated_at |
| `hooks/useObservability.aliases.test.ts` (MSW) | list, bulk, update, delete + optimistic |

### 14.2 Playwright (E2E)

| Test | Description |
|---|---|
| `e2e/observability-aliases-happy.spec.ts` | Load → see banner → click chip → bulk-paste fills → import → row appears |
| `e2e/observability-aliases-bulk-error.spec.ts` | Paste 5 rows where 2 have bad squad → see counter "3 válidas, 2 inválidas" → import → see partial result + CSV download offer |
| `e2e/observability-aliases-edit.spec.ts` | Edit alias → change squad → save → row updates → focus returns to edit button |
| `e2e/observability-aliases-delete.spec.ts` | Delete alias → confirm dialog → confirm → row gone → focus returns to next row |
| `e2e/observability-aliases-keyboard.spec.ts` | Full keyboard-only journey including suggestion chip activation |
| `e2e/observability-aliases-a11y.spec.ts` | axe-core scan on all 4 states |

### 14.3 Important integration test

After alias creation, navigate to `/settings/integrations/observability/ownership`
and verify that a service whose `team:` tag matches the new vendor now
shows the correct `effective_squad_key`. This validates the cross-page
invalidation (see §9.4).

---

## 15. Open questions

1. **Q1: Lowercase toggle default?** Phase 4 ships with "[x] Lowercase
   vendor (compat com DD)" default-checked. Rationale: DD historically
   lowercases tags. **Verify with `pulse-data-engineer`** that the actual
   stored vendor team values are lowercased on the rollup side. If yes,
   the toggle is informational; if no, it's functional. Phase 4 ships
   either way — the toggle clarifies intent.
2. **Q2: Bulk paste max rows?** Prototype has no limit. Recommend
   client-side warning at 500+ rows, hard-stop at 5000 (server-enforced
   in pulse-data). Document with `pulse-data-engineer`.
3. **Q3: Should "no aliases yet" state hide the table entirely or render
   it with just an empty-state row?** Recommend hide; render bulk-paste
   panel as the hero (matches the "Comece criando seu primeiro alias"
   call to action).
4. **Q4: Optimistic update on bulk import?** Recommend NO. Too risky
   with 50+ rows; the server response is the source of truth. Bulk imports
   show inline progress / result instead.
5. **Q5: Suggestion chips show how many services would be affected?**
   E.g. "[crm (8 services)]". This is helpful but requires the API to
   return that count. **Open** — depends on backend; if cheap, do it; if
   expensive, defer.
6. **Q6: Conflict resolution on PUT?** If Bruno edits an alias's
   squad while another tab has just changed it, the optimistic update
   may show stale data. Recommend `If-Match` headers (ETag) — beyond
   Phase 4 scope, file as follow-up.
7. **Q7: Confirm dialog reused across PULSE?** Worth promoting to
   `components/ui/ConfirmDialog.tsx` if Phase 3 didn't ship it. Easy
   call.
8. **Q8: Where does `obs_alias_bulk_paste_parse_error` get logged?** The
   debounced parse on textarea input runs many times per session — don't
   emit one event per parse, emit one **batched** event on Import-click
   summarizing the final parse state. (Otherwise analytics will be
   flooded.)

---

## 16. Sequencing inside Phase 4

Single-PR delivery (~10h target per master plan):

1. **Sub-task A** — API client + hooks extension (~1.5h)
2. **Sub-task B** — Aliases table + page shell (~2h)
3. **Sub-task C** — Edit modal + delete confirm (~2h)
4. **Sub-task D** — Bulk paste with live preview + per-line markers (~3h)
5. **Sub-task E** — Suggestions banner with click-to-fill (~1h)
6. **Sub-task F** — Tests + ux-reviewer pass (~2h)

---

## 17. Acceptance criteria

- [ ] Page loads in <500ms on cold cache with 50 aliases
- [ ] All 5 state cases render correctly (verified via MSW)
- [ ] axe-core scan = 0 critical/serious findings on all states
- [ ] Keyboard-only journey works for: create-via-chip, edit, delete
- [ ] Focus returns to trigger button after every modal closes
- [ ] Bulk paste: per-line markers update live; submit shows accurate
      result; partial-fail downloads CSV (5+ rejected)
- [ ] Native `confirm()` removed everywhere on this page
- [ ] Lowercase toggle persisted in form state, sent in API call
- [ ] Cross-page invalidation works: Ownership coverage updates after
      alias save
- [ ] No hardcoded hex
- [ ] pulse-ux-reviewer signs off
- [ ] pulse-test-engineer signs off

---

End of spec.
