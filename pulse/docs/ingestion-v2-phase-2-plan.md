# Ingestion v2 — Phase 2 Plan (FDD-OPS-014)

**Status:** DRAFT — produced in parallel while Phase 1 ingestion runs.
**Companion docs:** `ingestion-architecture-v2.md` (overall design),
`ingestion-spec.md` (current architecture).
**Sister artifact:** `alembic/versions/010_pipeline_watermarks_scope_key_DRAFT.py`

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

**Status of this document:** DRAFT 1. Awaiting review by
`pulse-data-engineer` and `pulse-engineer`. No code changes
beyond the sister Alembic migration draft (also DRAFT). Phase 1
ingestion is currently running and must converge before any Phase 2
implementation begins.

When approved:
1. Rename `010_pipeline_watermarks_scope_key_DRAFT.py` → `010_pipeline_watermarks_scope_key.py`
2. Open implementation PRs in the order described in §3
3. Update this doc's status to "APPROVED" and remove the DRAFT prefix
