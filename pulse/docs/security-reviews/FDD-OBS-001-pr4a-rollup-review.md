# Security Review — FDD-OBS-001 PR 4a: Observability Rollup Worker

**Reviewer**: PULSE CISO  
**Date**: 2026-05-06  
**Branch**: `feat/obs-001-rollup-worker`  
**Scope**: `token_bucket.py`, `tier2_inference.py`, `rollup_service.py`, `obs_rollup_worker.py`, `docker-compose.yml` (obs-rollup-worker service), `ADR-028`  
**Prior approved baseline**: PR 2 review (`FDD-OBS-001-pr2-datadog-review.md`)

---

## Summary Verdict

**APPROVE WITH REQUIRED BACKLOG ITEMS.** No must-fix-pre-merge blockers found. The eight
threat-model items submitted for review either hold as designed, or carry a narrow residual
risk that is acceptable at R0/single-tenant scale with a backlog item to close before R1
multi-tenant rollout. Four backlog items are raised; the highest-priority is Medium.

---

## Threat-Model Findings

### Issue 1 — Master-key residence at scale

**Verdict: Holds as designed. No residual gap.**

The residence contract documented in ADR-028 §1–§2 is correctly implemented.
`provider_factory.build_for_tenant` is called inside `async with provider:` in
`rollup_service.py:418-426`, so the decrypted per-tenant credential lives only for the
duration of `_rollup_one_tenant`. The `async with` block owns the provider's lifetime:
`__aexit__` calls `aclose()`, which closes the underlying `httpx.AsyncClient` and drops
its in-process reference before the next tenant begins.

The specific concern about an unhandled exception keeping a provider alive in a frame
local is mitigated by the `try/except Exception` at `rollup_service.py:433-438`, which
wraps the entire `async with provider:` block. If `_rollup_one_tenant` raises an
unexpected exception inside the `async with`, Python's context manager protocol
guarantees `__aexit__` is called on any exit path — including exception exits — before
the `except` clause runs. The provider reference is cleared from the local frame at that
point, not deferred to GC. No leak vector found.

The master key singleton in `Settings` surviving for the worker's lifetime is the
acknowledged trade-off in ADR-028 §1 ("Why not also rotate the master key per cycle?").
The R4 KMS migration path is documented as RISK-1. No new finding here.

---

### Issue 2 — Log redaction: service names

**Verdict: Log calls are correctly redacted. One gap in anti-surveillance scan coverage.
Raise as RISK-12 backlog item (Low).**

Full grep of all `logger.*` calls in `rollup_service.py` (lines 181, 245, 265, 278, 289,
296, 398, 412, 435, 441) was performed. Every call that involves a per-service context
uses `_hash_service_name(service_name)` — confirmed at lines 280, 291, 298. The raw
`service_name` variable appears on lines 263 (loop binding), 286 (passed to
`provider.query_metric` as a method argument — not logged), and 318 (passed to
`_upsert_snapshot` as the DB column value — not logged). No log statement anywhere in the
file emits the raw `service_name` string.

`tier2_inference.py` logs only counters at line 263; no service or repo names appear in
the log output.

`provider_factory.py` line 89 logs `metadata.key_fingerprint[:8]` — correct, this is the
fingerprint prefix, not a key value.

Gap identified: `test_obs_anti_surveillance.py` scans only `src/connectors/observability/`
and `src/contexts/observability/` (lines 79-87). The worker entry point
`src/workers/obs_rollup_worker.py` is outside these roots and is not scanned. While the
worker file itself contains no PII references, establishing the scan as explicitly
exhaustive protects against future additions to the worker that add a log line with a raw
service name or customer identifier.

**RISK-12 (carried from ADR-028 §5):** Extend `_iter_observability_python_files()` to
include `src/workers/obs_rollup_worker.py` (or the broader `src/workers/` directory if
other observability workers land in the future). Alternatively add a targeted lint rule
that asserts no direct `service_name` variable reaches a `logger.*` call without passing
through `_hash_service_name`. This is a CI lint addition, not a code change.

---

### Issue 3 — Tier 2 anti-surveillance column access

**Verdict: Clean. No surveillance-violating columns accessed. One scan gap to close.**

`_TIER2_SQL` (lines 135-153 of `tier2_inference.py`) selects `lower(pr.repo)` and
`(regexp_match(pr.title, ...))[1]` from `eng_pull_requests`. No `author`, `reviewer`,
`user_id`, `committer`, `created_by`, `assignee`, or any individual-identity column
appears anywhere in the file. Confirmed by grep (zero matches).

The extracted squad key comes from the Jira project prefix in the PR title (e.g. `PTURB`
from `PTURB-1234`), which is squad-level aggregation — not an individual identity. The
dominance-ratio and tie-window gates further ensure the inferred ownership reflects
aggregate team behavior, not any single contributor's activity.

The output logged at line 263 contains only counts (`candidates_seen`, `inferred`, skip
counters) — no repo names, no squad keys, no service names.

Gap: as noted under Issue 2, `tier2_inference.py` is inside `src/contexts/observability/`
and IS covered by the anti-surveillance scan. However, the FORBIDDEN_REFS list in
`test_obs_anti_surveillance.py` focuses on PII field names (`user.email`, `ack_by`,
`resolved_by`, etc.) and does not include forbidden SQL column names like `pr.author_id`,
`pr.merge_by`, or `pr.reviewer`. A future PR extending `_TIER2_SQL` to add one of these
columns would not be caught by the current scan. This is a separate backlog item from
RISK-12.

**RISK-13 (new):** Add `pr.author`, `pr.author_id`, `pr.merge_by`, `pr.reviewer` as
additional entries in `FORBIDDEN_REFS` inside `test_obs_anti_surveillance.py` and the
corresponding `FORBIDDEN_FIELD_NAMES` in `_anti_surveillance.py`. These are the specific
columns in `eng_pull_requests` that must never reach query results used by Tier 2
inference.

---

### Issue 4 — Token bucket fail-closed correctness under Redis flapping

**Verdict: No runaway DD spend path. Design holds.**

The concern: Redis flapping mid-cycle (some `eval` calls succeed, some fail). Code path
for a failing call: `_get_redis()` returns a client, `client.eval(...)` raises an
exception, the `except Exception` at `token_bucket.py:205` catches it and returns `False`.
The caller (`rollup_service.py:275`) receives `False`, counts `rate_limited_skipped += 1`,
and returns immediately from `_rollup_one_tenant`. No further `query_metric` calls for
that tenant in that cycle.

The important observation: fail-closed returns `False` (not `True`), so Redis flapping
does not cause additional DD API calls. If anything, a Redis outage suppresses the rollup
entirely for that cycle. The bucket does not need to be in a consistent state for
fail-closed to protect against overspend — the gate is simply absent (no token consumed,
no API call made).

There is no "partially-consumed bucket, partially-open gate" scenario because the Lua
script is atomic: either the token is decremented and the call is allowed, or the call
returns before the DD query is made. There is no path where a token is consumed but the
DD query is not guarded.

---

### Issue 5 — Lua script atomicity

**Verdict: Correct. No race condition.**

The Lua script `_LUA_TRY_ACQUIRE` executes `HMGET → compute → HMSET → EXPIRE` as a single
`EVAL` call. Redis executes Lua scripts in a single-threaded, non-preemptive manner. Two
concurrent worker pods hitting the same bucket key will have their Lua executions
serialized by the Redis event loop. No two scripts can interleave between the HMGET and
the HMSET.

One minor precision note: `ARGV[3]` passes `str(time.time())` from Python, which is a
float serialized to a string. Lua's `tonumber()` recovers the float. At `time.time() ~
1.746e9` (current Unix epoch range), IEEE-754 double precision (53-bit mantissa) can
represent values to approximately 1-microsecond resolution, which is well within the
refill-rate resolution needed for a 500-tokens/hour bucket. No functional issue.

---

### Issue 6 — Worker DOS / runaway risk on DD 5xx wave

**Verdict: Bounded by token bucket. No runaway risk.**

When `provider.query_metric` raises `DatadogConnectorError`, the worker catches it at
`rollup_service.py:287-293`, increments `result.errors`, and continues to the next metric.
It does NOT call `try_acquire` again before attempting the next metric — the token was
already consumed at line 275 before the query was attempted. This means each attempted
query consumes exactly one token regardless of outcome. If DD returns 5xx for every call,
the bucket drains at the same rate as during normal operation, and the cycle ends when
the bucket is empty or the deadline is hit. Maximum DD API pressure in one cycle remains
bounded at 500 requests regardless of the 5xx rate.

---

### Issue 7 — Tenant discovery query, RLS, and the NIL-UUID fallback

**Verdict: Functional gap between the code comment and actual DB configuration. Raise as
Medium backlog item (RISK-14).**

`_list_eligible_tenants` (`rollup_service.py:144-186`) calls `get_session(NIL)` where
`NIL = UUID(int=0)`. This calls `_set_tenant(session, NIL)`, which executes:

```
SET app.current_tenant = '00000000-0000-0000-0000-000000000000'
```

With RLS enabled and policies enforcing `tenant_id = current_setting('app.current_tenant')::uuid`,
the query on `tenant_observability_credentials` will filter rows to
`tenant_id = '00000000-...-0000'` — which matches no real tenant row — and return an
empty result set. The `except Exception` clause then catches the empty-result case...
except it does not: an empty result is not an exception. The code returns
`[row.tenant_id for row in result.all()]` with `result.all() == []`, so it returns an
empty list. No fallback to `default_tenant_id` fires.

The actual R0 behavior depends on whether `BYPASSRLS` has been granted to the `pulse`
database user. The comment at line 152 asserts it has: "the worker connects with the same
`pulse` DB user as the API, which has BYPASSRLS for service paths." However, no Alembic
migration in the codebase grants `BYPASSRLS` to the `pulse` user. A search of all
migration files and init SQL found zero occurrences of the string `BYPASSRLS` outside
this comment. If the `pulse` user does not have `BYPASSRLS`, the cross-tenant credential
discovery query returns an empty list at R0 (single tenant), and the worker does nothing
every cycle — silently.

The fallback at lines 180-186 fires only on an `Exception`, not on an empty result. The
fallback therefore only helps if the SQL itself raises (connection failure, syntax error).
For the normal "RLS filters to zero rows" case, the fallback is unreachable. This means
the R0 claim of "single-tenant fallback" does not actually function as documented.

Additionally, the `default_tenant_id` in `src/config.py:168` defaults to
`"00000000-0000-0000-0000-000000000001"`, which is a well-known stub UUID. If this matches
a real tenant row in production (it would only if someone explicitly created a tenant with
this ID), the fallback would expose that tenant's full credential list as the "system" view
— but this is an extremely unlikely misconfiguration and not the primary concern.

The primary concern is the silent no-op: if BYPASSRLS is not configured, the worker starts,
logs "worker started", runs cycles, and writes zero rollup rows — with no error, no alert,
and no indication of the configuration gap.

**RISK-14 (Medium, must resolve before R1):**  
(a) Add a Alembic migration (or init SQL) that explicitly grants `BYPASSRLS` to the `pulse`
user, or creates a dedicated `pulse_worker` role with `BYPASSRLS` for cross-tenant worker
paths. Document which DB role is expected to have `BYPASSRLS` in the migration and in
ADR-028.  
(b) Change `_list_eligible_tenants` to treat an empty result as a warning, not silence.
Add a `logger.warning("[rollup] tenant discovery returned 0 tenants — verify BYPASSRLS on
DB user or PULSE_DEFAULT_TENANT_ID in env")` when the result is empty. This makes the
misconfiguration observable on the first cycle instead of requiring someone to notice the
absence of rollup data.  
(c) The empty-result-is-not-exception issue means the explicit `except Exception` fallback
is not actually guarding the common RLS-filtered case. Either restructure to check
`len(rows) == 0` and fall back, or accept that the fallback only covers genuine DB errors
(which is also a valid design — just document it and fix the comment).

At R0 with Webmotors as the single tenant, this is mitigated by the fact that the
`default_tenant_id` fallback (if it were reached) correctly targets the single tenant.
But the silent-empty-result path means the worker may already be producing zero output at
R0 if BYPASSRLS is not set. This warrants immediate verification against the running
stack.

---

### Issue 8 — Backlog items (RISK-N format)

All findings are consolidated here. Findings from Issues 1-7 are summarized with their
risk IDs. New items not surfaced above are also listed.

---

## Classified Findings

### Must Fix Before Merge

None. No pre-merge blockers.

---

### Medium — Resolve Before R1 Multi-Tenant Rollout

**RISK-14:** `_list_eligible_tenants` relies on BYPASSRLS but no migration grants it.
The cross-tenant query silently returns empty when RLS is enforced without BYPASSRLS,
causing the worker to run 96×N cycles per day with zero output and no observable error.

Files: `rollup_service.py:149-186`, `src/config.py:168`, missing Alembic migration.

Action: (a) Add explicit `GRANT BYPASSRLS` migration for the worker DB role, (b) add
`logger.warning` when tenant discovery returns 0 rows, (c) correct the comment at
`rollup_service.py:151-153` to accurately describe the DB user's privileges.

---

### Low — Recommended Before R1

**RISK-12** (referenced in ADR-028 §5): The Layer 4 anti-surveillance source-grep test
does not cover `src/workers/obs_rollup_worker.py`. While the file is currently clean, the
scan should be exhaustive to catch future additions.

File: `tests/unit/test_obs_anti_surveillance.py:79-87`.

Action: Add `repo_root / "src" / "workers"` to the `roots` list in
`_iter_observability_python_files`, filtered to files whose name starts with `obs_`.

**RISK-13** (new): `FORBIDDEN_REFS` in the anti-surveillance test does not include
individual-identity column names from `eng_pull_requests` (`pr.author_id`, `pr.merge_by`,
`pr.reviewer`). A future extension of `_TIER2_SQL` that adds one of these columns would
pass the current scan.

File: `tests/unit/test_obs_anti_surveillance.py:32-44`.

Action: Add `"pr.author"`, `"pr.merge_by"`, `"pr.reviewer"`, `"pr.author_id"` to
`FORBIDDEN_REFS` and the corresponding entries to `FORBIDDEN_FIELD_NAMES` in
`_anti_surveillance.py`.

---

### Informational

**INFO-1: No healthcheck on `obs-rollup-worker` container.**

`docker-compose.yml` defines a `healthcheck` on `sync-worker` and `metrics-worker` (lines
129, 160) but the `obs-rollup-worker` service block (lines 213-244) has no `healthcheck`
stanza. The Dockerfile's default `HEALTHCHECK` is HTTP-based (port 8000) and will fail
for this worker since it has no HTTP listener. Docker will report the container as
"unhealthy" after the default timeout, which could trigger unnecessary restarts under
`restart: unless-stopped` if the orchestrator interprets unhealthy as down.

Action: Add a process-based healthcheck to the `obs-rollup-worker` service in
`docker-compose.yml`, matching the pattern used by `sync-worker`:

```yaml
healthcheck:
  test: ["CMD-SHELL", "python -c 'import os; os.stat(\"/proc/1/status\")'"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

**INFO-2: Startup `asyncio.create_task` is not guarded by APScheduler `max_instances=1`.**

`obs_rollup_worker.py:129` fires an immediate cycle via `asyncio.create_task(_run_one_cycle())`
before `scheduler.start()`. APScheduler's `max_instances=1` only applies to jobs spawned
by the scheduler itself — this manually-created task runs concurrently with any
scheduler-triggered tick if the first task happens to still be running when the first
15-minute tick fires (which the 12-minute deadline makes extremely unlikely but not
impossible on a very slow DB).

The actual risk is bounded by the shared Redis token bucket: two concurrent cycles share
the same bucket and collectively cannot exceed 500 DD requests/hour. No DD overspend is
possible. This is an operational cleanliness issue, not a security issue.

Action (backlog, R1): Replace `asyncio.create_task(_run_one_cycle())` with
`scheduler.add_job(..., next_run_time=datetime.now())` so the startup cycle is also
subject to `max_instances=1`. This is a one-line change.

**INFO-3: `service_name` stored plaintext in `obs_metric_snapshots.service` column.**

`_upsert_snapshot` writes the raw `service_name` string to the `service` column of
`obs_metric_snapshots`. The log redaction (hashing) is log-layer only — the DB stores
the full name, as required by the timeline query. This is correct by design: the Deploy
Health Timeline must be able to query by service name, and the column is protected by
per-tenant RLS (migration 019 enables RLS with four policies). This is not a gap.

Note for future reviewers: the hash-in-logs / plaintext-in-DB split is intentional and
documented in ADR-028 §3. The concern is shared log infra, not DB access (which is
tenant-isolated via RLS). No action needed.

**INFO-4: `_set_tenant` uses an f-string for SQL construction (`database.py:49`).**

`SET app.current_tenant = '{tenant_id}'` constructs the SQL string using an f-string
rather than a parameterized query. In the worker context, `tenant_id` values come from
the DB itself (the `_list_eligible_tenants` query), not from external user input, so the
injection risk is negligible in practice. However, as a general codebase pattern, this
is a latent risk if `tenant_id` origin ever changes.

This finding is pre-existing and outside this PR's scope. Noting for the record. Action
(backlog, general): convert `_set_tenant` to use a parameterized `SET` via
`SET LOCAL app.current_tenant TO :val` with bound parameter, if SQLAlchemy's `SET LOCAL`
syntax supports it for session-level variables.

---

## Verification Against ADR-028

| ADR-028 Section | Implementation | Status |
|---|---|---|
| §1 — KEK held in Settings singleton, per-tenant credential ≤ one cycle | `rollup_service.py:418-426`, `provider_factory.build_for_tenant` | Confirmed |
| §2 — Providers never cached across cycles | `rollup_service.py:408-409` (builds fresh each tenant) | Confirmed |
| §3 — Service names hashed in logs (`sha256[:8]`) | `rollup_service.py:280, 291, 298` | Confirmed — all logger calls use `_hash_service_name` |
| §4 — `hide_parameters=True` on SQLAlchemy engine | `database.py:34` | Pre-existing, confirmed |
| §5 — Log levels (INFO cycle, WARNING rate-limit/error) | `rollup_service.py:265, 278, 289-298` | Confirmed |
| RISK-12 — CI lint for log statements | Not yet implemented | RISK-12 backlog |

---

## References

- `pulse/packages/pulse-data/src/contexts/observability/services/token_bucket.py`
- `pulse/packages/pulse-data/src/contexts/observability/services/tier2_inference.py`
- `pulse/packages/pulse-data/src/contexts/observability/services/rollup_service.py`
- `pulse/packages/pulse-data/src/workers/obs_rollup_worker.py`
- `pulse/packages/pulse-data/src/contexts/observability/services/provider_factory.py`
- `pulse/packages/pulse-data/src/contexts/observability/services/credential_service.py`
- `pulse/packages/pulse-data/src/database.py`
- `pulse/docker-compose.yml`
- `pulse/docs/adrs/028-observability-rollup-worker-key-residence.md`
- `pulse/packages/pulse-data/alembic/versions/017_observability_credentials.py`
- `pulse/packages/pulse-data/alembic/versions/019_obs_metric_snapshots.py`
- `pulse/packages/pulse-data/tests/unit/test_obs_anti_surveillance.py`
- `pulse/packages/pulse-data/tests/unit/contexts/observability/services/test_rollup_service.py`
- `pulse/packages/pulse-data/tests/unit/contexts/observability/services/test_token_bucket.py`
