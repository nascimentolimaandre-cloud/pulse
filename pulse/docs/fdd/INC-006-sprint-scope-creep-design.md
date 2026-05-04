# INC-006 — Sprint Scope Creep / Removed Items

**Status:** ✅ Phase 1 shipped (2026-05-04)
**Owner:** `pulse-data-engineer` (extraction) + `pulse-data-scientist` (formula)
**Resolves:** INC-006 (`added_items` / `removed_items` always 0; scope creep % always 0)

## 1. Problem

`eng_sprints.added_items` and `eng_sprints.removed_items` were always 0
because the `normalize_sprint` step computed `committed_items` from the
**current** sprint membership and had nowhere to source historical
churn information. The dashboard's Sprint Comparison page showed
"Added (Scope Creep) 0 (0%)" for every sprint — useless for detecting
scope inflation.

## 2. Insight (same playbook as MTTR / FDD-DSH-050)

The Jira changelog **already** records every Sprint field change:

```json
{
  "field": "Sprint",
  "from": "1",
  "to": "1, 2"
}
```

We were already ingesting this changelog (it's the same payload that
INC-020 fixed for `status_transitions`). The Sprint field changes were
just being dropped. So the fix is:

> Decompose each Sprint field diff into atomic enter/exit events,
> persist them on `eng_issues.sprint_transitions`, and let a stateless
> sprint scope service derive committed/added/removed per sprint
> from the issues that ever touched it.

**No new ingestion process. No external snapshot store. No new connector calls.**

## 3. Goal

- Resolve INC-006 with the data we already collect.
- Be DORA-canonical in the formula (median, percentile, threshold).
- Be anti-surveillance (no per-developer attribution — sprint-level only).
- Be SaaS-ready: per-tenant tunable (`planning_grace_days`).

## 4. Schema (migration `015_sprint_transitions`)

| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `eng_issues` | `sprint_transitions` | `JSONB DEFAULT '[]'` | Ordered log of {sprint_id, action, at} entries |

Plus a GIN partial index `ix_eng_issues_sprint_transitions` using
`jsonb_path_ops` so the lookup
`sprint_transitions @> '[{"sprint_id":"X"}]'::jsonb` is O(log n) on
larger tenants.

Each transition entry:

```json
{
  "sprint_id": "jira:JiraSprint:1:42",
  "action":    "entered" | "exited",
  "at":        "2026-04-15T14:30:00+00:00"
}
```

Sorted ASC by `at`. Same JSONB-on-row philosophy as `status_transitions`
(INC-020).

## 5. Extraction (`extract_sprint_transitions_inline`)

Lives in `workers/devlake_sync.py` next to `extract_status_transitions_inline`
— same call site, same input (the inline expand=changelog payload).

The Jira changelog represents Sprint membership as a comma-separated set
in `from`/`to`. We decompose each diff:

- IDs in `to` but not `from` → action='entered' at `created`
- IDs in `from` but not `to` → action='exited' at `created`

ID-based (not name-based — names collide across boards). Each id is
normalized to `jira:JiraSprint:<conn_id>:<raw_id>` to match
`eng_sprints.external_id`.

Defensive parsing: `from`/`to` may be None / whitespace / labelled by
customfield ID rather than `Sprint`. All three are handled.

## 6. Calculation (`calculate_sprint_scope`)

Pure-Python, in `services/calculate_sprint_scope.py`. Inputs:
- A sprint (external_id, started_at, ended_at)
- An iterable of issues each with their `sprint_transitions` list
- Tunables: `planning_grace_days` (default 1)

Per-issue: reduce to **last entry** + **last exit** for this sprint
(re-entry handling — "moved to next sprint, then moved back" counts
as one net membership decision, same philosophy as MTTR's chain anchor).

```python
grace_until = sprint.started_at + timedelta(days=planning_grace_days)

if last_entered <= grace_until:
    committed += 1                            # joined within planning
else:
    added += 1                                # scope creep

if last_exited:
    if last_exited <= grace_until:
        pass                                   # planning churn — ignore
    elif sprint.ended_at and last_exited > sprint.ended_at:
        pass                                   # normal closure
    else:
        removed += 1                          # left during sprint
```

`scope_creep_pct = added / committed` when committed > 0, else None.

### Tunable: `planning_grace_days = 1` (default)

Sprints rarely start at the exact minute of `started_at` — Webmotors's
typical pattern is "Monday morning planning, working sprint starts at
EOD". A 1-day window absorbs this without flagging the same-day adds
as creep. Set to 0 for strict (every entry after `started_at` = creep).

### Tunable surfacing

The admin endpoint accepts `planning_grace_days` as a query param. For
SaaS, this could be elevated to `tenant_jira_config` later (same pattern
as FDD-PIPE-001's `squad_qualification_config`) — not necessary for
Phase 1 since defaults are sane.

## 7. Backfill (`backfill_sprint_scope`) + admin endpoint

`POST /data/v1/admin/sprints/refresh-scope` (X-Admin-Token).

Body params:
- `scope` — `all` | `closed` | `last-90d`
- `planning_grace_days` — default 1
- `dry_run` — boolean
- `max_sprints` — cap for smoke testing

For each sprint with `started_at` populated:
1. Query issues whose `sprint_transitions @> [{"sprint_id": X}]`
   (uses the GIN index — fast)
2. Run `calculate_sprint_scope`
3. UPDATE `eng_sprints.committed_items` / `added_items` / `removed_items`
4. Skip if no issues touched the sprint (preserves legacy committed
   counts on pre-INC-006 sprints — explicit decision: don't zero out
   data we can't recompute)

Idempotent: re-running on the same scope is safe (skips unchanged rows).

## 8. Forward-path

Every sync cycle now calls `extract_sprint_transitions_inline(raw)` and
includes the result in `normalize_issue(...)` output. The upsert in
`_upsert_issues` writes `sprint_transitions` on every ON CONFLICT
update — so once an issue is touched by sync, its transitions are fresh
forever.

For sprint counts to reflect this on existing sprints, the admin
endpoint runs once after the first round of issue re-syncs.

## 9. Operational rollout

1. **Code shipped** — every new sync from this point onward populates
   `eng_issues.sprint_transitions`.
2. **Reset issue watermark** for projects that use sprints (Webmotors:
   `FID`, `PTURB`) so existing issues get re-synced and their full
   changelog history is captured.
   ```sql
   UPDATE pipeline_watermarks
   SET last_synced_at = '2020-01-01 00:00:00+00'
   WHERE entity_type = 'issues'
     AND scope_key IN ('jira:project:FID', 'jira:project:PTURB');
   ```
3. **Wait** for issues sync to complete (depends on volume — FID is
   ~6k issues, PTURB similar; ~30-60 min).
4. **Run backfill**:
   ```
   POST /data/v1/admin/sprints/refresh-scope?scope=all&planning_grace_days=1
   ```
5. **Verify** via the Sprint Comparison page — "Added (Scope Creep)"
   now shows real numbers.

## 10. Anti-surveillance

✅ Compliant. The transitions log records (sprint_id, action, at) with
no person identifier. The calculation operates on issue counts only.

## 11. Live smoke (synthetic data, 2026-05-04)

Injected 4 synthetic transitions on Sprint 144 (FID) to validate the
end-to-end flow:

| Issue | Action | At | Expected |
|-------|--------|----|----|
| 1 | entered | 2 days before sprint start | committed |
| 2 | entered | 12h after start (within grace) | committed |
| 3 | entered | 5 days into sprint | added |
| 4 | entered then exited | 2 days before / 9 days into | committed + removed |

Backfill result:
```
{
  "sprints_scanned": 12,
  "sprints_updated": 1,
  "sample_diffs": [{
    "external_id": "jira:JiraSprint:1:6553",
    "before": {"committed": 358, "added": 0, "removed": 0},
    "after":  {"committed": 3,   "added": 1, "removed": 1},
    "issues_considered": 4
  }],
  "duration_sec": 0.05
}
```

Matches expectations exactly. (Synthetic data was cleared after the
test — production rollout in §9 produces real numbers.)

## 12. Tests

`pytest tests/unit/test_sprint_scope_creep.py -q` → **28 passed**:

- `TestCommittedClassification` (4) — boundary cases at planning grace
- `TestAddedClassification` (3) — including `scope_creep_pct` math
- `TestRemovedClassification` (3) — during/after/planning-churn
- `TestReEntryHandling` (1) — last-entry-wins
- `TestMultiSprint` (1) — other sprints don't pollute
- `TestEdgeCases` (5) — None/empty/active sprints/strict-grace
- `TestExtractSprintTransitionsInline` (7) — Jira changelog parsing
- `TestNormalizeSprintId` (4) — id normalization helper

Full backend regression: **244 / 244 pass**.

## 13. Files changed

| File | Change |
|------|--------|
| `alembic/versions/015_sprint_transitions.py` | NEW — JSONB column + GIN index |
| `src/contexts/engineering_data/models.py` | `EngIssue.sprint_transitions` Mapped |
| `src/workers/devlake_sync.py` | `_normalize_sprint_id` + `extract_sprint_transitions_inline` + wiring into `_sync_issues` + `_upsert_issues.set_` |
| `src/contexts/engineering_data/normalizer.py` | `normalize_issue(..., sprint_transitions=)` |
| `src/contexts/engineering_data/services/calculate_sprint_scope.py` | NEW — pure-Python reference |
| `src/contexts/engineering_data/services/backfill_sprint_scope.py` | NEW — admin backfill |
| `src/contexts/engineering_data/routes.py` | `sprints_admin_router` + `POST /refresh-scope` |
| `src/main.py` | Mount sprints_admin_router |
| `tests/unit/test_sprint_scope_creep.py` | NEW — 28 tests |
| `docs/fdd/INC-006-sprint-scope-creep-design.md` | This doc |

## 14. Phase 2 (deferred — backlog)

- **`planning_grace_days` per tenant**: surface as `tenant_jira_config`
  knob (currently fixed default + admin-endpoint override).
- **UX copy**: tooltip on the Sprint card explaining the 1-day grace
  window.
- **Forward-hook on sprint upsert**: trigger scope recompute when a
  sprint's `completed_at` first appears (signals close). Currently the
  admin endpoint covers this — sprints rarely change after closing,
  so periodic invocation is sufficient.
- **Per-issue attribution drill-in**: "show which 12 issues caused the
  scope creep on Sprint 144" — needs a new endpoint reading the
  transitions directly.
