# Ingestion v2 — Phase 2 Plan (FDD-OPS-014)

**Status:** PARTIAL — foundation shipped 2026-04-28, read-side refactor + worker split deferred.
**Companion docs:** `ingestion-architecture-v2.md` (overall design),
`ingestion-spec.md` (current architecture).
**Sister artifact (applied):** `alembic/versions/010_pipeline_watermarks_scope_key.py`

---

## 0. Shipping summary (2026-04-28 status)

What landed in this iteration vs. what carries forward:

### ✅ Shipped (production-ready, validated against live tenant)

| Step | Commit | What |
|---|---|---|
| **2.1** | `f357d05` | Migration 010 applied: `pipeline_watermarks.scope_key VARCHAR(255) NOT NULL DEFAULT '*'` + `uq_watermark_entity_scope` UNIQUE coexisting with legacy `uq_watermark_entity` |
| **2.2** | `f357d05` | Per-scope watermarks API: `GLOBAL_SCOPE`, `make_scope_key(source, dim, value)`, `_get_watermark(scope_key=...)`, `_set_watermark(scope_key=...)`, `_list_watermarks_by_scope(scope_keys=[...])`. Default `'*'` preserves all legacy callers. |
| **2.3** | `f357d05` | `_sync_issues()` reads + writes per-project watermarks (`jira:project:<KEY>`). Logs "watermark plan: N backfill, M incremental" pre-flight. Per-project advance fires on project transition. Legacy global '*' kept for compat. |
| **2.4** | `15574a7` | `_sync_pull_requests()` writes per-repo watermarks (`github:repo:<owner>/<name>`) on each batch persist. **Write-side only** — connector still uses single `since` for fetch. |
| **2.5** | `15574a7` | `_sync_deployments()` writes per-repo watermarks (`jenkins:repo:<repo>`) post-upsert. Per-repo not per-job (Q2 decision: matches PR↔deploy linking dimension). **Write-side only.** |

Test coverage shipped: 19 unit tests (`test_watermark_scope_keys.py` 9, `test_inline_changelog_extraction.py` 10 — re-validated alongside).

### 🟡 Deferred to next iteration (sister FDD)

| Step | What's missing | Why deferred |
|---|---|---|
| **2.4-B / 2.5-B** | Connector signature refactor: accept `since_by_repo` / `since_by_project` so per-scope watermarks are READ during fetch (not just written) | Required for new-repo backfill correctness — without it, adding a repo only fetches PRs newer than the global `*` watermark. Significant connector code change (~M effort), warranted in a dedicated PR with thorough tests. |
| **2.6** | docker-compose split into per-source workers (jira/github/jenkins) | Architectural value of split (per-source isolation, parallel cycles) only realizes when combined with 2.4-B + 2.5-B. Splitting alone = 3 containers running same global-watermark logic — zero throughput win. |
| **2.7** | Migration 011: drop legacy `uq_watermark_entity` constraint | Plan §3 explicitly requires "after one successful per-source cycle". Per-source doesn't exist yet (deferred above). Legacy constraint coexists harmlessly until then. |
| **Health-aware pre-flight** (P-8 in v2 doc) | Pre-cycle source reachability check (skip cycle if source unhealthy) | Belongs with worker-split work (each per-source worker owns its health-check). Without split, a single sync still has interleaved phases. |

### 🟢 Foundation shipped means

- New scope rows accumulate every cycle. When the read-side refactor lands, every active repo/project already has its own watermark — no schema migration, no backfill of historic data.
- Migration 010 is rollback-safe via `downgrade()`. The legacy unique constraint coexists with the new one for as long as needed.
- All Phase 1 wins (FDD-OPS-012 batched persistence, FDD-OPS-013 inline changelogs) remain intact and continue working.

### 📅 Suggested next iteration

Open as `feat/ingestion-v2-phase-2b` branch:

1. Refactor `JiraConnector.fetch_issues_batched` to accept `since_by_project` dict (already does — done in Phase 1). Just verify wired correctly.
2. Refactor `GithubConnector.fetch_pull_requests_batched` to accept `since_by_repo: dict[str, datetime | None]` and use per-repo since when provided.
3. Refactor `JenkinsConnector` deployments fetch to accept per-repo since.
4. Update `_sync_*` methods to pass `since_by_<scope>` from `_list_watermarks_by_scope` results.
5. Smoke test: add new project to Jira catalog → confirm only that scope backfills.
6. THEN: docker-compose split (Step 2.6) + companion migration 011.

Estimated effort for Phase 2-B: **M-L (~3-5 dev-days)**. Honest scoping based on actual time spent on Phase 2-A (much faster than originally estimated due to clean foundation).

---

## 1. Goals (acceptance criteria)

The migration is "done" when **all 5** acceptance items hold:

1. **Per-source isolation**: Jenkins outage (or Jira slowness, or GitHub
   rate-limit) does not block the other two sources. Each source has its
   own worker process, event loop, and cycle cadence.
2. **Per-scope watermarks**: a new Jira project activation does not
   trigger a full re-fetch of existing 200k+ issues. Each scope_key
   advances independently.
3. **Health-aware pre-flight**: each cycle checks source reachability
   before starting any I/O. VPN drop = mark unhealthy + skip cycle, not
   block-and-retry-forever.
4. **Backwards-compat**: existing `pipeline_watermarks` rows keep working
   during the transition (scope_key='*' default).
5. **Tests pass**: 100% of existing unit/integration suites + new tests
   for per-source and per-scope behavior.

Non-goals (deferred to Phase 3):
- Job queue / worker pool
- Pre-flight cost estimation via API count call
- `/pipeline/jobs` per-job endpoint

---

## 2. Architecture diff (current → target)

### Current

```
docker-compose.yml:
  sync-worker         (one process, one event loop, runs:
                       _sync_issues → _sync_prs → _sync_deploys → _sync_sprints
                       sequentially, every 15 min)

pipeline_watermarks:
  (tenant, entity_type) UNIQUE          ← GLOBAL across all scopes
  e.g. row: (tenant=001, entity='issues', last_synced_at='2026-04-26')
```

### Target

```
docker-compose.yml:
  jira-sync-worker     (entity: issues, sprints, sprint-issues)
  github-sync-worker   (entity: pull_requests, repos)
  jenkins-sync-worker  (entity: deployments)

  All independent: own event loop, cron schedule, retry policy,
  health-check, watermark scope, container.

  discovery-worker (unchanged — already separate)

pipeline_watermarks:
  (tenant, entity_type, scope_key) UNIQUE   ← PER-SCOPE
  e.g. rows:
    (tenant=001, entity='issues', scope='jira:project:BG',  last_synced='...')
    (tenant=001, entity='issues', scope='jira:project:OKM', last_synced='...')
    (tenant=001, entity='prs',    scope='github:repo:foo',  last_synced='...')
```

---

## 3. Implementation order (dependencies)

The order minimizes risk and allows early rollback.

### Step 2.1 — Schema migration (010, sister file)

Add `scope_key` column with default `'*'` + companion unique constraint.
Existing rows continue to work (read by `(tenant, entity_type)` matches
the `'*'` row exactly).

**Risk:** very low. Default value preserves all existing reads/writes.
**Rollback:** `alembic downgrade -1`.
**Validation:** smoke against existing sync flow — should produce
identical behavior.

### Step 2.2 — Repository layer: per-scope watermark API

Add `get_watermark(tenant, entity, scope_key='*')` and
`set_watermark(tenant, entity, scope_key, ts, count)` to the watermarks
repo. Default `'*'` keeps current callers untouched.

**Risk:** low. Existing call sites untouched; new ones opt in.
**Validation:** unit tests for default vs explicit scope_key.

### Step 2.3 — JiraSyncWorker (extract from monolith)

New module `src/workers/jira_sync_worker.py` containing:

```python
class JiraSyncWorker:
    """Single-source worker. Owns: issues, sprints, sprint-issues."""

    async def cycle(self):
        if not await self._check_jira_health():
            logger.info("Jira unhealthy this cycle; skipping")
            return

        await self._sync_issues()        # uses per-project scope keys
        await self._sync_sprints()       # scope='jira:board:<id>'
        await self._sync_sprint_issues() # scope='jira:sprint:<id>'

    async def _check_jira_health(self) -> bool:
        # GET /rest/api/3/myself with 5s timeout
        ...
```

`_sync_issues` becomes per-project loop with per-project watermark
read/write. The PR loop pattern from Phase 1 transfers directly.

**Risk:** medium. Monolithic worker still works; new worker is opt-in
via env flag `PULSE_USE_PER_SOURCE_WORKERS=true`.

### Step 2.4 — GithubSyncWorker

Same pattern. Owns: pull_requests, repos discovery.
scope_key format: `github:repo:<owner>/<name>`.

### Step 2.5 — JenkinsSyncWorker

Same pattern. Owns: deployments.
scope_key format: `jenkins:job:<job_full_name>`.

Health check: `GET /api/json` with 5s timeout. If VPN off → unhealthy
this cycle; resume on next.

### Step 2.6 — docker-compose.yml: 3 workers replace 1

```yaml
sync-worker:
  # REMOVED. Replaced by 3 specific workers below.

jira-sync-worker:
  image: pulse-jira-sync-worker
  command: python -m src.workers.jira_sync_worker
  ...

github-sync-worker:
  ...

jenkins-sync-worker:
  ...
```

**Risk:** low — Dockerfiles unchanged (single image, 3 different commands).
**Rollback:** revert compose, restart sync-worker.

### Step 2.7 — Companion migration 011: drop legacy unique constraint

After all workers are emitting per-scope writes for >1 successful cycle,
drop `uq_watermark_entity` constraint. Coexistence period prevents cutover
surprises.

---

## 4. Test plan

Each item lists the test type and what it asserts.

### Unit tests (no DB, no network)

| Test | What it asserts |
|---|---|
| `test_watermarks_repo_default_scope_compat` | `get_watermark(t, e)` returns same row as `get_watermark(t, e, scope_key='*')` |
| `test_watermarks_repo_set_per_scope` | Setting scope=`'jira:project:BG'` doesn't affect global `'*'` row |
| `test_jira_health_check_returns_false_on_timeout` | Mock httpx returning timeout → health=False |
| `test_jira_sync_skips_cycle_when_unhealthy` | `_check_jira_health()=False` → `_sync_issues()` not called |
| `test_github_sync_per_repo_watermark` | Each repo has independent watermark |
| `test_jenkins_sync_per_job_watermark` | Each job has independent watermark |

### Integration tests (DB, mocked HTTP)

| Test | What it asserts |
|---|---|
| `test_jira_full_cycle_uses_per_project_watermarks` | After cycle, every active project has its own watermark row |
| `test_jira_new_project_activation_only_backfills_that_scope` | Activate new project → only that scope_key gets full backfill, others unchanged |
| `test_jira_one_project_failure_does_not_block_others` | Mock 401 on project X → other projects still complete |
| `test_companion_migration_011_safe_after_workers_migrated` | Verify constraint drop doesn't break existing reads |

### End-to-end (Webmotors-scale, manual run)

| Test | What it asserts |
|---|---|
| Boot 3 workers, full re-ingestion against Webmotors | Convergence in <90 min total (parallel sources) |
| Disable VPN mid-Jenkins-sync | Jenkins worker pauses gracefully; Jira+GitHub continue |
| Add new Jira project to catalog | Only that project backfilled in next cycle; others skipped |
| Kill jira-sync-worker mid-cycle | On restart, ≥80% of fetched issues already persisted (per Phase 1) AND watermarks reflect work done |

### Regression tests (must keep passing)

- All 52 unit tests from Phase 1 connector/aggregator suite
- `test_inline_changelog_extraction.py` (10 tests, FDD-OPS-013 anti-regression)
- All existing dora/lean/cycle_time domain tests

---

## 5. Rollout sequence (in production / staging)

When this Phase 2 code is ready:

1. **Pre-flight**: announce maintenance window (~30 min for safety even
   though zero-downtime is the design goal).
2. **Run migration 010** (additive) → verify no errors, queries unchanged.
3. **Deploy new worker images** with `PULSE_USE_PER_SOURCE_WORKERS=false`
   (still the monolith). No behavior change.
4. **Validate** monolith still works with new schema column present.
5. **Flip flag** to `=true`. Three new workers start. Old `sync-worker`
   container is replaced.
6. **Watch one full cycle** (~30 min). All three sources should run
   independently with per-scope watermarks.
7. **Run migration 011** → drop legacy constraint.
8. **Remove backwards-compat code paths** (separate cleanup PR).

If anything misbehaves at any step, rollback path:
- Steps 1-4: `alembic downgrade -1` + redeploy old image
- Steps 5-6: flip flag back to `false`, kill new workers, restart monolith
- Step 7: requires manual constraint recreation; coordinate carefully

---

## 6. Estimate (effort)

Honest scoping:

| Step | Effort | Owner |
|---|---|---|
| 2.1 Schema migration | XS (1h, already drafted) | data-engineer |
| 2.2 Watermarks repo per-scope API | S (2-3h) | data-engineer |
| 2.3 JiraSyncWorker extraction | M (1 day) | data-engineer |
| 2.4 GithubSyncWorker extraction | S (4-6h, simpler since PRs already streaming) | data-engineer |
| 2.5 JenkinsSyncWorker extraction | S (4h, simplest) | data-engineer |
| 2.6 docker-compose split | XS (1h) | engineer |
| 2.7 Companion migration 011 | XS (30min) | data-engineer |
| Tests (unit + integration) | M (1 day total) | test-engineer |
| Rollout + validation | S (half day) | engineer + data-engineer |
| **Total** | **~1 week of focused engineering** | |

This matches the `ingestion-architecture-v2.md` Phase 2 estimate (3-5 days).

---

## 7. Open questions (for review)

These need a decision before implementation starts. Captured here so
they don't block the technical work.

### Q1: Health-check policy for workers

Question: when a source is unhealthy, should the worker:
- (a) Skip the cycle entirely (current Phase 1 behavior — simple)
- (b) Run with cached data only (more code, useful for read-heavy tasks)
- (c) Pause the worker (no retry until manual restart)

Recommendation: **(a) skip + log + retry next cycle**. Matches what the
v2 doc implies. Operators can grep for "unhealthy this cycle".

### Q2: Scope-key format — strict schema or freeform string?

Question: should `scope_key` follow a strict pattern like
`<source>:<dimension>:<value>` (e.g., `jira:project:BG`) or stay as
opaque text?

Recommendation: **convention enforced in code, not constraint**.
String column is flexible; helper functions like
`make_scope_key(source, dimension, value)` enforce shape. Allows
future scopes (e.g., `jira:tenant-rule:bg-only`) without migration.

### Q3: What happens to the global `*` rows after migration 011?

Question: keep them as "tenant-wide aggregate watermarks" (informational)
or delete?

Recommendation: **delete in a separate cleanup PR after 1 month of
stable per-scope operation**. Removes cognitive load. If someone wants
"latest across scopes", that's a `MAX(last_synced_at)` query, trivial.

### Q4: Alembic chain — single migration or two?

Question: keep migration split (010 add, 011 drop) or combine?

Recommendation: **keep split**. The risk of dropping the old constraint
before workers are confirmed writing per-scope is high; the cost of
keeping both for a month is zero. Two migrations provide a safe rollback
window.

---

## 8. What this plan does NOT cover (explicitly out of scope)

- **Job queue + worker pool** — Phase 3, separate plan
- **Pre-flight item count via API** — FDD-OPS-015 full version, separate
- **Pipeline Monitor UI per-scope tab** — needs FDD-OPS-015's data layer
  first
- **GitLab / Azure DevOps / Linear connectors** — R2+, separate work
- **MTTR pipeline** — FDD-DSH-050, completely independent track

---

## Status

**Status of this document:** PARTIAL IMPLEMENTATION (2026-04-28).

Phase 2-A foundation shipped — see §0 for the breakdown of what landed
vs. what was deferred to Phase 2-B. The architectural pattern (per-scope
watermarks coexisting with legacy global '*' rows) is in production use
and validated against the Webmotors tenant.

Phase 2-B (read-side connector refactor + docker-compose split + drop
legacy constraint) opens as a separate effort — see §0 "Suggested next
iteration" for the concrete roadmap.

### Document changelog

- **2026-04-28 evening** — PARTIAL status. Steps 2.1–2.5 (write-side)
  shipped. Steps 2.4-B, 2.5-B, 2.6, 2.7 deferred with rationale.
- **2026-04-28 afternoon** — DRAFT 1 produced in parallel while Phase 1
  ingestion converged.
