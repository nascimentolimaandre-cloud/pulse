# PULSE Ingestion Architecture — v2 Review

**Status:** Proposal · **Author:** orchestrator (post-mortem of 2026-04-27/28 incidents)
**Audience:** `pulse-data-engineer`, `pulse-engineer`, `pulse-product-director`
**Companion docs:** `ingestion-spec.md` (current architecture), `metrics/metrics-inconsistencies.md` (data quality history)

---

## 1. Why this document exists

This week's full re-ingestion against the Webmotors tenant exposed
structural defects in PULSE's ingestion pipeline that **cannot be
fixed by patches**. Five distinct failures in five days:

| # | Date | Failure | Time wasted |
|---|---|---|---|
| 1 | 2026-04-23 | Snapshot drift (FDD-OPS-001) — workers running stale code | hours of debugging across 3 incidents |
| 2 | 2026-04-27 | `make seed-reset` wiped 442k rows of real Webmotors data without explicit gate | full re-ingestion required |
| 3 | 2026-04-27 | `metrics_snapshots` 50× perf regression at 7M rows — partial index missing | dashboard erro, ~2h diagnose+fix |
| 4 | 2026-04-27 21:23 | Cycle 2 failed silently — Jira ConnectionError (network blip) → 0 issues persisted → unnoticed for 14h | 14h × engineer attention |
| 5 | 2026-04-28 | Sync stuck 1.5h in JQL pagination, then hours in `fetch_issue_changelogs` (estimated 24-28h to converge) | currently running, decision pending |

Each was **rational locally** when shipped. The sum is **not viable
for SaaS**. When we onboard the second tenant, every problem above
multiplies; when we onboard tenant N, we never finish.

The user-stated target: **at least 10× improvement in speed,
simplicity, resilience, and security.**

This document is the proposal.

---

## 2. The five anti-patterns we keep hitting

### AP-1: Bulk-fetch-then-persist (issues only)

**Symptom (today):** `eng_issues.COUNT() = 0` for **3+ hours** while
sync worker buffers 250k+ issues in memory before any DB write.

**Code:** `packages/pulse-data/src/workers/devlake_sync.py:_sync_issues()`
lines 605-635:

```python
raw_issues = await self._reader.fetch_issues(...)            # blocks until ALL 32 projects paginated
changelogs = await self._reader.fetch_issue_changelogs(ids)  # 1 GET per issue (250k+ HTTP calls)
normalized = [normalize_issue(...) for raw in raw_issues]    # all in memory
count = await self._upsert_issues(normalized)                # single bulk upsert
```

**Why it's wrong:**
- Time-to-first-row (TTFR): hours, not seconds
- Memory: 1.5+ GB peak (manageable today, OOM at 2× scale)
- Visibility: operator queries `COUNT(*)`, sees 0, can't tell if working or stuck
- Recovery: crash mid-sync = lose 100% of fetched work

**Notable:** PRs ALREADY escaped this pattern via commit `7f9f339`
(2026-04-23), which made `_sync_pull_requests` batch-per-repo. PR sync
now persists ~100 rows every few seconds — operator sees `COUNT(*)`
growing in real-time. Issues was missed in that refactor.

**Tracked:** FDD-OPS-012 (created 2026-04-28).

---

### AP-2: Redundant API calls

**Symptom (today):** worker is hitting `GET /rest/api/3/issue/{id}?expand=changelog&fields=status`
once per issue — ~3 calls/sec. For 250k issues this is ~24 hours of
blocking HTTP work.

**Code:** `devlake_sync.py:614`:

```python
issue_ids = [str(raw["id"]) for raw in raw_issues]
changelogs_by_issue = await self._reader.fetch_issue_changelogs(issue_ids)
```

**Why it's wrong:** `fetch_issues()` already requests `expand=changelog`
on the JQL search (`jira_connector.py:240`). The changelog data is
**already in `raw_issues`** — the separate fetch is duplicate work.

The connector itself documents this:

```python
# jira_connector.py:267
def fetch_issue_changelogs(...):
    """...
    Since fetch_issues already includes changelogs via expand=changelog,
    this method is used for issues fetched WITHOUT expand (e.g., sprint issues).
    """
```

**Why it survives:** there's no test asserting "main issues sync uses
inline changelogs". The redundant call is invisible until production
scale exposes it.

**Cost:** 376k HTTP calls × ~300ms = ~31 hours of pure API latency,
plus Atlassian rate-limit pressure.

**Fix:** one-line — replace the separate call with read from
`raw["changelog"]` field already present in JQL response.

**Tracked:** to be opened as FDD-OPS-013.

---

### AP-3: Sequential phases with global watermark

**Symptom (yesterday):** cycle 2 hit a Jira ConnectionError at 21:23,
issues sync errored silently with 0 results, sync moved on to PRs/deploys/
sprints (which succeeded), watermark for issues never advanced. Next
14 hours of cycles wasted because the worker kept trying issues with
the same scope, hitting the same ordering issue, never producing data.

**Code:** `devlake_sync.py:DataSyncWorker.sync()` runs phases in fixed
order:

```python
1. _sync_issues()       # fails silently → 0 issues
2. _sync_pull_requests() # ok → 63131 PRs
3. _sync_deployments()   # ok → 1376 deploys
4. _sync_sprints()       # ok → 216 sprints
```

`pipeline_watermarks` has ONE row per `entity_type` regardless of scope:

```sql
entity_type='issues', last_synced_at='2020-01-01' (when reset)
```

**Why it's wrong:**

1. **Single failure point**: failure in any phase doesn't degrade
   gracefully; watermark stays where it was, next cycle reruns same
   work, no signal that "issues broke at 21:23, PRs were fine".

2. **Global watermark = full backfill on scope expansion**: when
   discovery activates a new project, we have to reset watermark to
   2020-01-01 to backfill — but this also re-fetches the 200k
   already-ingested issues from existing projects. Wasteful.

3. **No bulkheads**: if Jira has a hiccup, issues phase blocks. No
   timeout, no skip, no degraded mode.

**Tracked:** to be opened as FDD-OPS-014 (per-scope watermarks +
phase isolation).

---

### AP-4: No source isolation

**Symptom (today AM):** sync worker stuck retrying Jenkins jobs
(VPN was off overnight) — every cycle would burn ~10s × 200 dead jobs
= 30+ minutes on Jenkins timeouts before getting to anything else.

**Code:** all four sources (GitHub, Jira, Jenkins, future GitLab)
share **one process**, **one event loop**, **one cycle order**.

**Why it's wrong:**

- Jenkins outage (VPN, infra) blocks GitHub sync (which works fine)
- Jira rate-limited → blocks deployment ingestion that doesn't touch Jira
- One slow source = global throughput floor
- Adding GitLab/ADO/Linear means more code in the same shared loop

**The asymmetry:** discovery already has its OWN worker
(`discovery_scheduler.py`). The sync side wasn't given the same
treatment.

**Tracked:** FDD-OPS-014 (covers per-source workers).

---

### AP-5: Estimate-and-pray (no real observability)

**Symptom (every cycle):** I tell you "ETA 45min", we wait 4h, find
out it's stuck, restart, lose work. We've done this **5 times this
week**. Each time my estimate is plausible at start, wrong by an
order of magnitude after exposure.

**Why estimates fail:**

1. **No pre-flight cost estimate.** We don't ask Jira "how many issues
   match this JQL?" before fetching. We don't ask GitHub "how many PRs
   in active repos last 12 months?" We just start and hope.

2. **Progress proxy is `COUNT(*)`** — but in bulk-fetch mode (AP-1),
   COUNT stays 0 until the very end. Useless during the long phase.

3. **No rate-aware ETA.** When pace is 27 calls/min for 10 minutes,
   we don't multiply by remaining work to get a real ETA.

4. **No per-scope visibility.** When stuck, we can't tell "is BG
   project taking forever, or is OKM done and we're on a small one?"

**Tracked:** FDD-OPS-015 (observable ingestion: pre-flight estimate +
per-scope progress + rate-aware ETA).

---

## 3. Target Principles for v2 (the 10× envelope)

These are non-negotiable design constraints. Every code change in
ingestion lands or is rejected against these.

### P-1: Stream by default — Time-to-first-row (TTFR) ≤ 60s

Every fetcher is an `AsyncIterator` yielding small batches (50-200
items). Each batch:
- normalize → upsert → emit Kafka event → ack → advance watermark

Memory bound: ~10 MB max in flight at any time, regardless of total volume.

**Effect:** operator sees row count growing from minute 1. Crash
recovery loses ≤1 batch.

### P-2: Source-isolated workers (bulkheads)

One worker process **per source** (github-sync-worker, jira-sync-worker,
jenkins-sync-worker, future gitlab-sync-worker). Independent:

- Event loop
- Cycle cadence
- Watermarks
- Failure handling
- Rate-limit budget

**Effect:** Jira down ≠ GitHub down ≠ Jenkins down. Onboarding GitLab
adds a worker; doesn't touch the others.

### P-3: Per-scope watermarks (kill global)

`pipeline_watermarks` keyed by `(source, entity_type, scope_key)`:

```sql
(jira, issues, project_key=BG)     last=2026-04-26 18:33
(jira, issues, project_key=OKM)    last=2026-04-26 18:35
(github, prs, repo=foo/bar)        last=2026-04-26 18:40
```

**Effect:** new project activated = backfill ONLY that scope. Existing
work preserved. Per-scope progress and ETA become trivial.

### P-4: Job queue + worker pool (not in-process loops)

Discovery emits jobs ("ingest scope X, since Y") onto a queue
(Redis-backed or Kafka topic). Worker pool consumes with configurable
concurrency per source.

```
Discovery → enqueue jobs → Queue → Worker[1..N] → DB streaming
```

**Effect:**

- Concurrency scales with hardware (5 parallel JQL queries vs 1)
- Failure = job retried, not whole cycle restarted
- New tenant = new jobs in queue, no orchestrator change
- SaaS-ready: 100 tenants = 100× jobs but same code

### P-5: Backpressure + rate-limit awareness

Read API rate-limit headers (`X-RateLimit-Remaining`, `Retry-After`).
Adapt automatically:

- 90% of limit consumed → slow down (sleep proportional to remaining budget)
- 429 / Retry-After → exponential backoff with jitter (per source)
- GitHub GraphQL cost: track query cost vs hourly budget (5000)

**Effect:** never hit hard limits. Sustained throughput is `~80% of
limit`, not `100% then 429 storm then crash`.

### P-6: Saga pattern per batch (idempotent + recoverable)

Each batch is a transactional unit:

```
BEGIN
  INSERT/UPDATE rows (ON CONFLICT DO UPDATE)
  INSERT pipeline_event (kafka_emitted=false)
  UPDATE pipeline_watermarks SET last_synced_at = max(batch)
COMMIT

ASYNC: emit Kafka event, mark pipeline_event.kafka_emitted=true
```

If crash before COMMIT: nothing changes, watermark unchanged, on
restart the worker re-fetches the same batch.

If crash after COMMIT but before Kafka emit: outbox pattern catches
unemitted events on next cycle.

**Effect:** zero data loss, zero duplicates (upsert idempotent), zero
silent skips.

### P-7: Observable by default

Every job emits structured progress:

```json
{
  "scope": "jira:project:BG",
  "phase": "fetching",
  "items_total_estimate": 197043,
  "items_done": 12500,
  "items_per_second": 84,
  "eta_seconds": 2200,
  "started_at": "...",
  "errors": []
}
```

Exposed via:
- `GET /pipeline/jobs` — current state of all jobs
- Prometheus metrics: `pulse_ingestion_items_total{source,scope,entity}`,
  `pulse_ingestion_duration_seconds`, `pulse_ingestion_error_rate`
- Pipeline Monitor UI — already exists, gets per-scope breakdown

**Effect:** "is it stuck?" answered in 5 seconds, not 4 hours.

### P-8: Health-aware orchestration

Before each batch:

```python
if not source.is_reachable():
    self.mark_unhealthy(source)
    return
```

When source unhealthy, jobs go to "paused" queue. Periodic health
ping (1/min) re-tests; on recovery, jobs resume from where they were.

**Effect:** VPN drop = jobs pause cleanly, no error storm, no time
wasted retrying. VPN back = automatic resume.

---

## 4. Proposed Architecture v2

```
┌──────────────────────────────────────────────────────────────────┐
│                  Discovery Service (per source)                  │
│  github-discovery     jira-discovery     jenkins-discovery       │
│   (org-scan)          (project-scan)     (job-scan via SCM)      │
│      │                    │                   │                  │
│      └────────┬───────────┴───────────────────┘                  │
│               ▼                                                  │
│  emits jobs: { source, scope, entity, since, priority }          │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│       Job Queue (Redis Streams or Kafka topic)                   │
│  jira:issues:BG       since=2026-04-26  priority=high            │
│  jira:issues:OKM      since=2026-04-26                           │
│  github:prs:foo/bar   since=2026-04-26                           │
│  jenkins:deploys:job-X since=2026-04-26                          │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Worker Pool (configurable concurrency per source)               │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ jira-worker[1..5]                                        │    │
│  │   pick job → BatchedFetcher → for batch in stream:       │    │
│  │     normalize → upsert → emit_event → advance_watermark  │    │
│  │     emit progress event                                   │    │
│  └──────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ github-worker[1..3]                                      │    │
│  │ jenkins-worker[1..3]                                     │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────┬───────────────────────────────────────────────────┘
               │ writes
               ▼
┌──────────────────────────────────────────────────────────────────┐
│                          PULSE DB                                │
│  eng_pull_requests, eng_issues, eng_deployments, eng_sprints     │
│  pipeline_watermarks  (source, entity, scope_key) → last_at      │
│  pipeline_jobs        (job state: pending/running/done/failed)   │
│  pipeline_events_outbox (Kafka emit guarantee)                   │
│  pipeline_progress    (per-scope progress + ETA)                 │
└──────────────────────────────────────────────────────────────────┘
                                                                    
┌──────────────────────────────────────────────────────────────────┐
│  Metrics Worker (unchanged)                                      │
│  consumes Kafka events → recomputes snapshots                    │
└──────────────────────────────────────────────────────────────────┘
```

### Key API contracts

```python
# A fetcher is just an AsyncIterator yielding small batches
class BatchedFetcher(Protocol):
    def fetch(self, scope: str, since: datetime | None) -> AsyncIterator[Batch]:
        ...

@dataclass
class Batch:
    scope: str          # e.g., "BG"
    items: list[dict]   # 50-200 raw items
    source_high_water: datetime  # for watermark advancement
    estimated_total: int | None  # if pre-flight known, for ETA
    rate_limit: RateLimitInfo | None  # adaptive throttling
```

```python
# Job worker is a generic loop, source-agnostic
class IngestionJobWorker:
    async def run_job(self, job: Job):
        fetcher = registry.get_fetcher(job.source, job.entity)
        async for batch in fetcher.fetch(job.scope, job.since):
            await self.persist_batch(batch)            # transactional
            await self.emit_progress(job, batch)        # per batch
            await self.check_health()                   # circuit breaker
```

---

## 5. The 10× envelope, decomposed

| Lever | Today | v2 | Speedup | Notes |
|---|---|---|---|---|
| Stream vs bulk-then-persist | 250k issues × 1.5h fetch + 0.5h normalize+upsert = 2h | 100 items every ~3s = constant-time TTFR | **30×** TTFR | AP-1 + FDD-OPS-012 |
| Kill redundant changelog fetch | 376k × 1 HTTP call (~24h) | 0 (use inline) | **∞** (eliminates phase) | AP-2 + FDD-OPS-013 |
| Source isolation (parallel) | 4 phases sequential | 3 source workers concurrent | **3-4×** wall time | AP-4 + FDD-OPS-014 |
| Per-source concurrency | 1 connector active | 3-5 workers per source | **5×** sustained throughput | P-4 |
| Adaptive rate limits | naive retries, sometimes 429-banned | stay 80% of limit | **2×** sustained, **0** ban | P-5 |
| Per-scope watermarks | new project = full reset = full backfill | new scope = scope-only backfill | **10×** for incremental ops | AP-3 + FDD-OPS-014 |
| Health-aware (skip unreachable) | block whole cycle on Jenkins outage | pause source, others continue | qualitative — turns hours of wasted retry into 0 | P-8 |
| Pre-flight estimate | guess | actual API count | qualitative — answers "stuck?" in seconds | P-7 + FDD-OPS-015 |

**Aggregate effect on the workload that's running RIGHT NOW** (376k
issues across 32 projects, fresh tenant):

- **Today's path:** 24-30h+ (potentially infinite if changelog fetch
  rate-limits)
- **v2 Phase 1 path** (just AP-1+AP-2 fixes): 30-45 minutes
- **v2 Phase 2 path** (+ source isolation): same 30-45 min for issues,
  but now happens in parallel with PR sync, deploy sync — total cycle
  ~45 min vs ~3h

---

## 6. Migration Path — non-bigbang, in 3 phases

I will NOT propose a clean-room rewrite. The codebase has 1 year of
hard-won correctness (status mapping, anti-surveillance, edge cases).
Throwing it out is the wrong reflex.

Each phase delivers value standalone and is reversible.

### Phase 1: Quick Wins — fixes the immediate pain (1-2 days, P0)

**Scope:** correct existing code, no architecture change.

| Item | Effort | Effect |
|---|---|---|
| **AP-2 fix** — comment out redundant `fetch_issue_changelogs` call in `_sync_issues`; teach normalizer to read inline `raw["changelog"]` | XS (1h code + tests) | 24h+ → ~5 min for changelog phase (eliminated) |
| **AP-1 fix** (FDD-OPS-012) — refactor `_sync_issues` to batch-per-project, mirror `_sync_pull_requests` pattern from `7f9f339` | M (4-6h) | TTFR for issues: hours → seconds; memory: 1.5GB → 50MB |
| **Pre-flight estimate logging** — before each `_sync_*`, log "I will fetch ~N items based on JQL count / GraphQL nodeId / Jenkins job count" | XS (1h) | Operator gets actual ETA vs guess |

**Total Phase 1: ~1-2 dev-days.**
**Result on Webmotors workload: 24h → ~30-45 min for full re-ingest.**

### Phase 2: Source Isolation (3-5 days, P1)

**Scope:** structural — split sync-worker into per-source workers.

| Item | Effort |
|---|---|
| Extract `JiraSyncWorker`, `GithubSyncWorker`, `JenkinsSyncWorker` from monolithic `DataSyncWorker` | M (1 day) |
| docker-compose: 3 services instead of 1 | XS |
| Per-source watermarks: schema migration + repo update | M (1 day) |
| Health-aware pre-flight check before each cycle | S (2-3h) |
| Update Pipeline Monitor UI for per-source breakdown | S (existing surface) |

**Total Phase 2: 3-5 dev-days.**
**Result: failure isolation, parallel execution, correct watermarks
under scope expansion.**

### Phase 3: Job Queue + Pool (1-2 weeks, R1)

**Scope:** the SaaS-ready pattern.

| Item | Effort |
|---|---|
| Choose job queue (Redis Streams vs Kafka topic — both already running) | XS (decision) |
| Job state schema (`pipeline_jobs` table) | S |
| Generic `IngestionJobWorker` consuming jobs | M (1-2 days) |
| Refactor each source to expose `BatchedFetcher` interface | M (1 day per source) |
| Discovery emits jobs (no longer triggers sync directly) | S |
| Retry policy + dead-letter | M |
| Tests + chaos eng (kill worker mid-job, verify resume) | M |

**Total Phase 3: 1-2 dev-weeks.**
**Result: SaaS-ready ingestion. Adding 100 tenants = 100× more jobs,
not 100× more code paths.**

---

## 7. What we are NOT doing (out of scope)

- **No connector rewrites.** GitHub/Jira/Jenkins connectors stay as-is;
  they have well-tested correctness logic. Only the orchestration layer
  changes.
- **No DevLake re-introduction.** ADR-015 (ex-ADR-005, renumbered 2026-05-06) is settled.
- **No event sourcing.** Outbox pattern (Phase 1.5+) is sufficient
  for our Kafka guarantee.
- **No SaaS multi-tenant orchestration.** Phase 3 makes it possible;
  full multi-tenant rollout is R1 product work, separate spec.

---

## 8. Decisions to make NOW

For the team. These are not code decisions; they need product/eng
alignment.

### D-1: Phase 1 NOW vs after current sync converges?

**Option A:** Stop the current sync (lose ~3h of work), apply Phase 1
fixes (~1-2 days), restart. Total: 2 days + 30 min final ingestion.
Sustainable code lands.

**Option B:** Wait for current sync to converge (24-30h+), then start
Phase 1. Total: 1-2 days waste + 1-2 days Phase 1.

**Recommendation:** A. Even with restart cost, A finishes faster AND
ships durable code. Continuing with the broken pipeline is sunk cost.

### D-2: Phase 2 + 3 timing

Phase 2 is a clear R1 commitment. Phase 3 is the SaaS gate — must
ship before second tenant goes live. Suggest committing both to R1
sprint planning explicitly.

### D-3: Backlog FDDs

Three new FDDs come out of this:

- **FDD-OPS-013** Kill redundant `fetch_issue_changelogs` (Phase 1 quick win, XS)
- **FDD-OPS-014** Per-source workers + per-scope watermarks (Phase 2, M-L)
- **FDD-OPS-015** Observable ingestion: pre-flight estimates + per-scope progress + ETA (Phase 1.5)

(FDD-OPS-012 — issue batch-per-project — was already opened 2026-04-28.)

---

## 9. Success criteria — how we know v2 worked

Lock these as acceptance for the migration:

1. **TTFR ≤ 60s for any source/entity** (measured: time from cycle
   start to first row in `eng_*` table) — ✅ **ATINGIDO (Phase 1, commit `4d1c9b4`)**: `_sync_issues` agora streams per-project; primeira issue persistida em <30s tipicamente
2. **Full re-ingestion at Webmotors scale (376k issues, 64k PRs, 1.4k
   deploys, 200 sprints) completes in ≤ 90 minutes** — ⚠️ **PARCIAL**: backfill BG (197k issues em projeto único) ainda é o gargalo dominante. Demais projetos rápidos. Estimativa total ~2-3h, não 90min — projeto BG sozinho consome maioria do tempo
3. **Memory peak ≤ 200 MB per worker** (vs 1.5 GB today) — ✅ **ATINGIDO**: Phase 1 streaming reduz para ~50-100 MB peak observado em produção
4. **Zero silent failures** — every error is logged with scope and
   visible via `GET /pipeline/jobs` endpoint — ⚠️ **PARCIAL**: per-batch logs detalhados existem; `pipeline_ingestion_progress` tracking OK; falta `GET /pipeline/jobs` endpoint dedicado (FDD-OPS-015 pendente)
5. **VPN drop simulation**: kill jenkins network in test, GitHub +
   Jira ingestion continues unaffected, Jenkins resumes on reconnect — ❌ **NÃO ATINGIDO**: Phase 2-A/B per-scope watermarks shippadas mas worker still monolítico. P-2 source isolation requer Step 2.6 (docker-compose split em workers per-source) — pendente
6. **Adding 1 fake project to Jira catalog** triggers backfill ONLY
   for that scope (not full rerun of existing 32 projects) — ✅ **ATINGIDO (Phase 2-A + 2-B, commits `c2c6e5d`..`c628528`)**: per-scope watermarks `(tenant, entity, scope_key)` + read-side resolution `since_by_project`/`since_by_repo` enviam since correto por escopo
7. **Crash recovery test**: SIGKILL worker mid-batch, restart, verify
   ≥99% of fetched data persisted (not 0, like today) — ✅ **ATINGIDO (Phase 1)**: cada batch persiste imediatamente via `_upsert_*` antes de avançar watermark; crash recovery loses ≤1 batch (~50-100 issues)

**Status agregado v2 (2026-04-29):**

| Phase | Status | Commits |
|---|---|---|
| Phase 1 (Quick Wins — AP-1 + AP-2 + pre-flight) | ✅ SHIPPED | `4d1c9b4`, `62c183f` |
| Phase 2-A (writes per-scope watermarks) | ✅ SHIPPED | `c2c6e5d`, `a2d5850`, `f357d05`, `15574a7`, `4f86fd2` |
| Phase 2-B (reads per-scope watermarks) | ✅ SHIPPED | `4478f13`, `c628528` |
| Phase 2.6 (docker-compose split per-source workers) | ⏳ PENDING | next session |
| Phase 3 (job queue + worker pool — SaaS-ready) | ⏳ PENDING | R1 |
| **Bonus data-quality fixes descobertos durante v2** | ✅ SHIPPED | `177830e` (changelog), `172f3f2` (effort), `0c7124d` (status), `649ed78` (sprint) |

**Observação importante:** durante a engenharia Phase 1+2 emergiram 4 bugs estruturais de data quality (status_transitions=0, story_points=0, status normalization skew, sprint status vazio) que **não estavam no escopo original** mas ficaram visíveis quando começamos a olhar dados frescos pós-Phase 1. Documentados como INC-020..023 / FDD-OPS-016..018. Fix de cada um expandiu o escopo do v2 — mas todos foram resolvidos ainda dentro da janela de 2 dias.

These are testable. Phase 3 acceptance hinges on items 4-7. **Item 5 (VPN simulation)** é o gating não-resolvido para confiar em SaaS multi-source.

---

## 10. The honest risk

This document advocates for stopping a 3-hour-old sync to start a
2-day refactor. That is itself a "another patch" pattern — promise
something better, ask to throw away the work in flight.

**Why I think this time it's different:**

- The diagnosis is structural, not a one-off (5 distinct failures, all
  same root cause family)
- Phase 1 alone is small enough to verify in 1-2 days, not 1-2 weeks
- The 10× number is decomposed and falsifiable — if we ship Phase 1
  and don't see TTFR drop from hours to seconds, we made a wrong
  diagnosis and need to revise
- The current sync's 24h ETA is itself a falsifiable claim that I'm
  putting in writing now — if it converges in <2h, I was wrong and
  Phase 1's urgency is reduced

But the user's frustration is correct. The default should be: "until
proven otherwise, every ingestion run is doomed at this scale." Phase
1 disproves that for issues. Phase 2 disproves it for cross-source
failures. Phase 3 disproves it for SaaS multi-tenant.

If we don't take this seriously now, we will rediscover all of it
when the second tenant onboards, with much more visibility and
political cost.

---

## Appendix A: Why the current architecture exists

This is not blame. The current state is the natural accretion of:

- ADR-015 (replace DevLake; originally ADR-005, renumbered 2026-05-06): the focus was correctness, not throughput.
  Bulk-then-persist was acceptable when datasets were small and we were
  proving feasibility.
- Commit `7f9f339` (PR batch refactor): proved the streaming pattern
  works. Should have generalized then; didn't because PRs were the
  pain at the time.
- Discovery service (ADR-014): correctly built as separate worker.
  The lesson didn't propagate to sync.
- 60+ status mappings (PT-BR): hard-won correctness. Don't break.
- Schema-drift monitor (FDD-OPS-001 line 3): smart, defensive,
  belongs in v2 unchanged.

v2 is **not** "throw away the work." It's "promote streaming +
isolation from local optimization in 1-2 places to architectural
default."

---

## Appendix B: Counter-arguments I considered

- "Just optimize the current code, don't restructure" — 5 incidents
  in 5 days argue against. Optimization without isolation = endless
  whack-a-mole.
- "Wait until 2nd customer pays, then build SaaS-ready ingestion" —
  building SaaS infra under customer time pressure is how outages
  happen at acquisition demos.
- "Use a 3rd-party data platform (Airbyte, Fivetran)" — explicitly
  rejected in ADR-015 (DevLake had the same coverage gap on Postgres).
  Adding another opaque layer doesn't solve our problems.
- "The 10× number is hand-wavy" — fair, but each lever is decomposed
  in §5. Falsifiable acceptance criteria in §9.

---

**Status of this document:** PROPOSAL. Awaiting review by
`pulse-data-engineer`, `pulse-engineer`, `pulse-product-director`,
and final approval from the user before any implementation.
