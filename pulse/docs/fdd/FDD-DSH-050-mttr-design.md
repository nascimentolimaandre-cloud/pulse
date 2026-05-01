# FDD-DSH-050 — MTTR / Time to Restore (Phase 1)

**Status:** ✅ Phase 1 shipped (2026-04-29)
**Owner:** `pulse-data-scientist` (formula) + `pulse-data-engineer` (pairing pipeline) + `pulse-engineer` (admin endpoint)
**Resolves:** INC-005 (MTTR sempre `null`)
**Related:** INC-008 (production-only filter), INC-004 (deployed_at temporal linking — same forward-hook pattern reused)

## 1. Problem

`eng_deployments.recovery_time_hours` was always `NULL`. The normalizer never
populated it, no downstream worker computed it, and `calculate_mttr()` had
correct math but no data to operate on. Result: **MTTR rendered as "—"** in
the dashboard and the **DORA overall level was computed from only 3 of 4
canonical metrics**.

## 2. Goal

Resolve INC-005 **without creating a new ingestion process** — pure
PULSE-side derivation from the data we already collect (Jenkins
deployments, INC-004 production filter, INC-008 environment tagging). MTTR
must:

1. Be DORA-canonical (median recovery time, classified Elite/High/Medium/Low).
2. Be anti-surveillance (no per-author attribution).
3. Be self-healing (forward-path hook keeps it fresh; admin backfill for
   the historical window).
4. Survive flaky tests (recoveries < 5 min are noise) and small samples
   (require `n ≥ 5` resolved incidents per period to publish a number).

## 3. Source decision — pair failures with the next success on (repo, env)

We **already** classify each Jenkins deploy as `is_failure=true|false`
(INC-008). The MTTR signal is therefore a **temporal pairing** within
`eng_deployments`:

> A FAILURE deploy on (repo, environment='production') is paired with
> the **next SUCCESS** on the same (repo, environment) within an
> open-incident window (default 7 days). The delta in hours is written
> to `recovery_time_hours` on the FAILURE row.

Why this source vs alternatives explored:

| Source | Decision | Reason |
|--------|----------|--------|
| Jenkins failure → next Jenkins success on same repo | **CHOSEN** | Already ingested; pairs are (repo, env) deterministic; no new connector |
| `eng_deployments.source = 'rollback'` | Rejected | Webmotors uses neither a `rollback` job naming convention nor a tag |
| Jira `priority IN (Highest, Blocker)` | Rejected for Phase 1 | Per-issue resolution times correlate poorly with deploy recovery; no consistent "incident → resolution" workflow across 27 squads |
| GitHub PR labels `hotfix`/`incident`/`revert` | Backlog (Phase 2) | Sparse usage — would miss most incidents; useful as enrichment, not source |
| External webhook (PagerDuty/Opsgenie) | Backlog (Phase 2+) | Webmotors not yet integrated; out of scope |

The **failure row owns** `recovery_time_hours` (anchor model). The recovery
row stays untouched — no `is_recovery` flag — to keep the update site
single-row and idempotent.

## 4. Schema (migration `013_mttr_incident_pairing`)

Three new columns on `eng_deployments`:

| Column | Type | Purpose |
|--------|------|---------|
| `recovered_by_deploy_id` | `UUID` (FK self → `eng_deployments.id`, ON DELETE SET NULL) | Points to the deploy that closed the incident |
| `superseded_by_deploy_id` | `UUID` (FK self) | Back-to-back failure absorbed into an earlier anchor |
| `incident_status` | `VARCHAR(16)` | `'open'` \| `'resolved'` \| `'superseded'` \| `NULL` |

Plus a `CHECK` constraint enforcing the four allowed values, and two
partial indexes:

- `ix_eng_deploy_mttr_pairing` — `(tenant_id, repo, deployed_at)
  WHERE environment IN ('production','prod')` — speeds the LATERAL
  next-success lookup.
- `ix_eng_deploy_open_incidents` — `(tenant_id, deployed_at)
  WHERE incident_status='open'` — supports the `mttr_open_incident_count`
  aggregation.

ORM: `EngDeployment` Mapped[] columns added in
`packages/pulse-data/src/contexts/engineering_data/models.py`.

## 5. Pairing algorithm

Single CTE in `services/backfill_mttr.py::_PAIRING_SQL`:

1. **`prod`** — restrict to production deploys with non-null
   `(repo, deployed_at)`.
2. **`ranked`** — for each row, compute:
   - `LAG(is_failure)` over `(repo) ORDER BY deployed_at` → flag previous
     row's failure status.
   - **`chain_anchor_id`** — correlated subquery walking back through
     consecutive failures to find the **first** failure in the chain (the
     row whose previous-success-on-repo is the most recent).
3. **LATERAL join** — for each failure row, find the next
   `is_failure=false` deploy on the same `(repo, env)` within
   `open_window_days`.
4. **Classification** (Python layer):
   - `chain_anchor_id ≠ self_id` → **`'superseded'`** + populate
     `superseded_by_deploy_id` with the anchor.
   - `next_success_at IS NOT NULL` → **`'resolved'`** +
     `recovery_time_hours = (next_success_at − failure_at) / 3600`.
   - else → **`'open'`** (window expired, still no recovery).

Idempotent: re-running on a row whose `(recovered_by, superseded_by,
status)` would not change is a no-op.

## 6. Calculation logic — `calculate_mttr()`

**Inputs:** `list[DeploymentData]` — only failed deploys with non-null
`recovery_time_hours` reach the median.

**Filters:**

```python
_MTTR_MIN_RECOVERY_HOURS = 5.0 / 60.0   # 5 minutes — flaky test guard
_MTTR_MIN_SAMPLE = 5                     # DORA practice: don't publish n<5
```

- **Flaky filter:** `recovery_time_hours >= 5/60` (5 minutes). Anything
  shorter is treated as "Jenkins re-trigger after a flaky test", not a
  real incident. Avoids deflating MTTR with re-runs that aren't outages.
- **Sample-size guard:** if fewer than 5 resolved incidents survive the
  filter, `calculate_mttr` returns `None`. Frontend renders a "—" with
  context tooltip rather than a misleading number.
- **Median**, not mean — same DORA reasoning as the rest of the suite.
  One catastrophic incident shouldn't dominate.

`DoraMetrics` exposes two new counters for context:

- `mttr_incident_count` — resolved failures that survived the filter.
- `mttr_open_incident_count` — failures with `recovery_time_hours IS NULL`
  (still open in the window).

These render under the MTTR card so users see "P50 = 0.5h, n=73 resolved,
3 still open in 90d" rather than a naked number.

## 7. Classification thresholds (DORA 2023)

| Tier | Threshold |
|------|-----------|
| Elite | `< 1h` |
| High | `1h ≤ x < 24h` |
| Medium | `24h ≤ x < 168h` (1 week) |
| Low | `≥ 168h` |

## 8. Pipeline integration — forward-path hook

Same pattern that closed INC-004. After `_sync_deployments` upserts new
deploy rows in the sync worker, it calls
`pair_recent_incidents(tenant_id, since_at=now())` (defined in
`backfill_mttr.py`). The hook is non-fatal: if pairing crashes, sync
completes and a follow-up run picks it up. Logs as
`INC-005/MTTR forward-pair: N failure rows reclassified`.

## 9. Admin endpoint — historical backfill

`POST /data/v1/admin/deployments/refresh-mttr` (X-Admin-Token guarded,
constant-time compare like the other admin endpoints).

Body:

```json
{
  "scope": "all" | "stale" | "last-90d",
  "open_window_days": 7,
  "dry_run": false,
  "max_failures": null
}
```

Returns counts: `deploys_scanned`, `failures_resolved`, `failures_open`,
`failures_superseded`, `failures_unchanged`, plus `sample_pairings` (10
rows) for sanity. Admin admin endpoint mounts via the new
`deployments_admin_router` in `routes.py`.

## 10. Anti-surveillance compliance

Verified by `tests/unit/test_mttr_calculation.py::TestAntiSurveillance::
test_calculate_mttr_only_reads_aggregable_fields` — a structural
source-grep test that fails the build if `calculate_mttr` ever references
`author`, `assignee`, `reporter`, `user`, or `committer`. MTTR operates
exclusively on `(repo, environment, timestamps, is_failure)` tuples.

## 11. Live results — Webmotors (2026-04-29)

```
255 prod failures classified in 1.14s
   84 → resolved
  148 → superseded (back-to-back failures within a chain)
   23 → open

After flaky filter (recovery_time_hours ≥ 5 min):
   73 real incidents
   P50 = 0.50h
   P90 = 16.58h
```

The 0.50h P50 places Webmotors squarely in **Elite** for MTTR (DORA
2023). Sanity: many of the 84 resolved chains are short Jenkins
re-trigger sequences — the flaky filter knocks 11 of those out, leaving
73 genuine incidents. Long tail (P90 ≈ 16h) reflects a handful of
weekend regressions paired against Monday-morning fixes.

## 12. Comparative analysis — what other platforms do

| Platform | Source | Filter | Comment |
|----------|--------|--------|---------|
| **DevLake (Apache)** | `cicd_deployment_commits.result IN ('FAILURE','ABORTED')` paired with next success | None visible | Closest to our approach; we add the flaky filter and explicit `superseded` classification |
| **Sleuth** | PR labels + Jenkins/CD result + manual incident decl. | Manual override | Multi-source; offers a "declared incident" UX which Phase 2 backlog item explores |
| **LinearB** | PR labels (`hotfix`, `incident`) + deploy frequency anomaly | Manual decl. | Heavy on PR-based heuristics; misses non-PR hotfixes |
| **Code Climate Velocity** | PagerDuty / Opsgenie webhooks first, deploys as fallback | Webhook-driven | Best fidelity but requires customer-side integration |
| **Jellyfish** | Jira incident issue type + transitions | Per-team config | Decoupled from deploy stream — risks underreporting deploy-only incidents |

PULSE Phase 1 lands at the **DevLake-equivalent** tier with the additional
safeguards (flaky filter, sample-size guard, idempotent pairing,
anti-surveillance test). Phase 2 backlog (see §13) adds the optional
enrichment layers.

## 13. Phase 2 backlog (deferred per user decision)

Phase 1 is intentionally minimal. Phase 2 items currently deferred:

1. **Jira "Bug" / "Incident" enrichment** — overlay Jira issues with
   `priority IN (Highest, Blocker)` and a "Bug" issue type onto the deploy
   pairing to catch incidents that don't have a clean
   failure→success Jenkins signature. Depends on INC-026/INC-027 (Jira
   issue type discovery + project-level config). User decision: defer to
   later sprint.
2. **GitHub label enrichment** — `hotfix`, `revert`, `P0`, `P1` PR labels
   as a confidence boost / orphan-incident catcher.
3. **External webhooks** — PagerDuty / Opsgenie integration for direct
   incident declaration.
4. **Per-team MTTR breakdown** — currently aggregated at tenant; once
   FDD-DSH-060 lands per-team snapshots, MTTR follows for free.
5. **Open-window auto-tune** — make `open_window_days` per-team (some
   squads ship hourly, others weekly).

## 14. Files changed

| File | Change |
|------|--------|
| `packages/pulse-data/alembic/versions/013_mttr_incident_pairing.py` | NEW migration — 3 columns + CHECK + 2 partial indexes |
| `packages/pulse-data/src/contexts/engineering_data/models.py` | `EngDeployment` Mapped[] for the 3 new columns; `import uuid`, `Uuid` |
| `packages/pulse-data/src/contexts/engineering_data/services/backfill_mttr.py` | NEW — pairing CTE + `run_backfill` + `pair_recent_incidents` |
| `packages/pulse-data/src/contexts/engineering_data/routes.py` | NEW `deployments_admin_router` with `POST /refresh-mttr` |
| `packages/pulse-data/src/main.py` | Mount the new admin router |
| `packages/pulse-data/src/contexts/metrics/domain/dora.py` | `_MTTR_MIN_RECOVERY_HOURS`, `_MTTR_MIN_SAMPLE`, `mttr_incident_count`, `mttr_open_incident_count`; `calculate_mttr` flaky + sample guards |
| `packages/pulse-data/src/workers/devlake_sync.py` | Forward-hook calling `pair_recent_incidents` after `_sync_deployments` |
| `packages/pulse-data/tests/unit/test_mttr_calculation.py` | NEW — 16 unit tests across 5 classes (median, sample guard, flaky filter, open incidents, counts integration, anti-surveillance source-grep) |

## 15. Test coverage

`pytest tests/unit/test_mttr_calculation.py -q` → **16 passed**.

Full regression: **183 / 183 unit tests passing** (no regressions).

Integration tests for the SQL pairing logic itself are listed as a
follow-up in the test guard docstring — they require a live DB and
weren't in scope for Phase 1.
