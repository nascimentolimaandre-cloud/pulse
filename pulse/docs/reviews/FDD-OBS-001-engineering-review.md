# FDD-OBS-001 — Engineering & Architecture Review

**Reviewer:** PULSE Engineer (post-PR-29 cross-cutting review)
**Date:** 2026-05-11
**Scope:** 8 PRs landed 2026-05-04 → 2026-05-10 (#21–#29)
**Lens:** "Can we put this in front of paying tenants this week?"

## Verdict (TL;DR)

**NOT YET — closer to "internal pilot ready" than "friendly-tenant ready".**
Backend + data layer are solid (good DDD, real anti-surveillance enforcement,
defensible security choices). **Two structural gaps block external exposure:**
the React production frontend was never built (UI lives only in the static
prototype, served on a separate port via `python -m http.server 8080`), and
the NestJS API layer was never asked to proxy/aggregate the new endpoints.
A friendly tenant currently has no way to consume FDD-OBS-001 from
`pulse-web` — they'd have to hit `pulse-data` directly on port 8000.

Estimated R2-friendly-tenant readiness work: **~12-15 person-days** of which
~10 are pure UI/wiring and ~3 are operational hardening (RISK items
7/14/15/16, runbook, drift alerts).

---

## A. Production-Readiness Gaps

### A1. 🚨 React frontend was never built (highest-priority blocker)

**Evidence:**

- `pulse/packages/pulse-web/src/routeTree.gen.ts:1-37` — route tree imports
  zero observability routes. Grep for `observability` / `obs/` /
  `/admin/integrations` inside `pulse-web/src/` returns zero hits.
- `pulse/packages/pulse-web/src/routes/_dashboard/` contains
  `home, integrations, metrics, pipeline-monitor, prs, settings` — no
  `observability/`.
- UI deliverable lives entirely under
  `pulse/pulse-ui/pages/observability-timeline/` (133 + 323 + 264 = **720 LoC**)
  and `pulse/pulse-ui/pages/observability-ownership/` (148 + 141 + 283 + 286
  + 158 + 357 = **1373 LoC**). Total prototype surface: **~2,093 LoC** of
  vanilla HTML/CSS/JS that the React app does not consume.

**Process violation (CLAUDE.md routing):** these prototype pages were
written by `pulse-engineer` during the FDD-OBS-001 PRs (PR 3 + PR 4b).
Per `CLAUDE.md` routing rules, anything inside `pulse/pulse-ui/` is owned
by `pulse-frontend`; production React inside `pulse/packages/pulse-web/`
is owned by `pulse-engineer`. The work that *was* in scope for this agent
(componentize into `pulse-web/`) **was skipped**.

**Componentization work to reach parity (estimates from a senior FE
engineer's standpoint):**

| Page / artifact | Source | Target | Est. LoC | Est. effort |
|---|---|---|---|---|
| Deploy Health Timeline | `observability-timeline/` | `_dashboard/observability/timeline.tsx` + `<HealthBucket>` + `<DeployMarker>` + Tremor heatmap shim | ~600 TSX | 2d |
| Service Ownership Map | `observability-ownership/index.html` | `_dashboard/observability/ownership.tsx` + TanStack Table + override modal | ~800 TSX | 2-3d |
| Team Aliases tab | `observability-ownership/aliases.html` | `ownership.aliases.tsx` route + CSV paste flow + bulk-import progress | ~500 TSX | 1.5d |
| Admin / connection panel | (no prototype yet) | `_dashboard/settings/integrations/datadog.tsx` + validate flow | ~400 TSX | 1.5d |
| API client shim (TanStack Query) | n/a | `lib/api/observability.ts` (types + fetchers + invalidation) | ~250 TS | 0.5d |
| State (Zustand) for filters / squad picker | n/a | `stores/observabilityStore.ts` | ~100 TS | 0.5d |
| Tests (unit + Playwright smoke) | n/a | `__tests__/` + `tests/e2e/observability.spec.ts` | ~300 TS | 1d |
| **Total** | | | **~3,000 TSX/TS** | **~9–10 dev-days** |

**Action:** Open four `pulse-engineer` impl-spec FDD cards (timeline, ownership,
aliases, admin) with explicit hand-off from the prototype. Cards do not exist
today — verified by grepping `pulse/docs/backlog/` for "observability" +
"componentiz" returns nothing.

### A2. ⚠️ `pulse-api` never wired to proxy the new endpoints

`pulse/packages/pulse-api/src/modules/` has `identity, integration, integrations`
— **no** `observability` module. Grep for `observability|obs-rollup|/obs/|/admin/integrations/datadog` inside `pulse-api/src` returns one
unrelated jira-admin DTO doc-comment.

**Architectural question this exposes:** the rest of the platform has
`pulse-web` → `pulse-api` (NestJS) → `pulse-data` (FastAPI). Observability
currently has no NestJS layer. Either:

- **(a)** Document an explicit architectural exception: the obs feature is
  consumed by `pulse-web` directly hitting `pulse-data` (port 8000) without
  NestJS in between. This breaks pattern consistency and means
  `pulse-web`'s API client needs to know about two backends.
- **(b)** Add an `observability` NestJS module that proxies to `pulse-data`.
  Adds ~1 day of NestJS work and is more consistent.

**Recommendation:** (b). The proxy module is mostly forwarding, but it's
where R1 auth (RISK-10 §I-001) will need to attach, and it lets the
frontend keep a single base URL. Until then, the friendly-tenant story
includes "open port 8000 to the browser" — uncomfortable.

### A3. 🚨 Multi-tenant blockers beyond RISK-15

The user already tracks RISK-15 (worker tenant discovery). Two adjacent
multi-tenancy gaps I noticed:

- **`pulse/packages/pulse-data/src/database.py:49`** — `_set_tenant` uses
  an **f-string interpolation** to embed `tenant_id` into `SET app.current_tenant = '...'`. Today `tenant_id` is a `UUID` instance so the
  injection surface is zero, but if anyone ever passes a `str` here (a
  realistic R1 risk with multi-tenancy code added in a rush), it becomes a
  SET-statement injection vector. Replace with a parameter or
  `quote_literal()` wrapper. **Backlog item.**
- **`provider_factory.build_for_tenant`** caches nothing across calls —
  good for R0 (matches ADR-028) but at R1 100-tenant scale the rollup
  worker pays one DB roundtrip per cycle per tenant just to re-fetch
  credentials + metadata. That's 100 × 2 = 200 queries every 15min
  (~13 qpm). Survivable, but worth a single batch read in R1.
- **`SquadDirectory.list_qualified_squads` is called twice per inference
  cycle** (`ownership_inference._get_row` → re-fetches qualified squads
  every override). Cache per-tenant for the cycle's lifetime; trivial fix,
  current waste is one full table scan per single-service override.

---

## B. Backend Architectural Quality

### B1. ⚠️ Abstraction leak: rollup_service depends on a concrete provider method

**Evidence:**

- `pulse/packages/pulse-data/src/connectors/observability/base.py:191-232`
  — `ObservabilityProvider` Protocol declares `list_deployments`,
  `query_metric`, `list_services`, `health_check`.
- `pulse/packages/pulse-data/src/contexts/observability/services/rollup_service.py:293`
  calls `await provider.list_monitors_for_service(service_name)` — a
  method that exists ONLY on `DatadogProvider`, not on the Protocol.
- Result: the day someone adds `NewRelicProvider` and passes it through
  `provider_factory`, the rollup cycle blows up at runtime with
  `AttributeError`. The Protocol's purpose — being the contract — is
  defeated.

**Fix:** add `list_monitors_for_service` (or a more abstract
`monitor_health(service: str) -> list[MonitorState]`) to the Protocol
and make any non-DD provider raise `NotImplementedError`. Or invert: split
into a `MonitorCapableProvider` sub-protocol and let the worker
runtime-check via `isinstance`. **Either is fine; pretending it isn't
there is not fine** — exactly the "vendor leak" ADR-023 was meant to
prevent.

### B2. ⚠️ DDD bounded context: a few "service-layer god" smells

- `ownership_inference.py` (460 LoC) does *both* Tier-1 sync (provider
  call + DB) *and* Tier-3 override (pure DB), *and* the read-model
  (`list_for_tenant`). Three responsibilities in one module. Not a god
  service yet, but `sync_tier1_inference` (~140 LoC, one function) is the
  one I'd split first — it's the only one with a provider dependency.
- `rollup_service.py` mixes:
  1. tenant discovery (`_list_eligible_tenants`)
  2. cycle orchestration (`run_cycle`)
  3. per-tenant pipeline (`_rollup_one_tenant`)
  4. DB upsert (`_upsert_snapshot`)
  5. Tier 2 trigger
  
  Reasonable cohesion for now, but `_upsert_snapshot` opens a fresh
  `get_session()` **per row** (`rollup_service.py:351`). At
  Webmotors-scale (430 services × 1 monitor metric/hour = 430 sessions
  per cycle), that's wasteful — even with `pool_pre_ping`, you're
  paying setup/teardown latency 430× per cycle. **Batch into a single
  session per tenant cycle.** ETA: ~2h, will likely halve cycle wall-time.

- `timeline_service` and `tier2_inference` import each other's helpers
  (`timeline_service._normalize_repo` calls
  `tier2_inference.normalize_repo` lazily at line 143). Move
  `normalize_repo` to a shared `_url_utils.py` in the BC.

### B3. ✅ Anti-corruption layer for DD: clean

The only vendor-specific code is in `datadog_connector.py`. The Protocol-defined
shapes (`DeployMarker`, `MetricSeries`, `ServiceEntity`, `MonitorState`)
flow downstream pristine. The rollup/timeline/ownership services never
import from `connectors/observability/datadog_connector.py` except for
the `DatadogConnectorError` exception class — that import in
`rollup_service.py:46-48` is acceptable as an explicit ACL crossing.
**One small smell:** `routes.py:32-35` imports `DatadogProvider`
directly to build the validate endpoint. That's fine — admin/validate IS
provider-specific by nature — but the BC's `__init__.py` should re-export
it so the routes file doesn't reach into `connectors/`.

### B4. ✅ Repository pattern question: deliberate non-pattern

`SquadDirectory` and the various service modules use direct
`text()`+`get_session` calls instead of a Repository class. **Stated
rationale in `squad_directory.py:18-22` is defensible**: a Repository
abstraction for a 1-method read would be ceremony. Consistent with the
codebase's overall pragmatic approach. I'd keep it.

### B5. ⚠️ Token bucket Lua script — production-grade with one gap

`pulse/packages/pulse-data/src/contexts/observability/services/token_bucket.py:64-92`
— the Lua is correct (atomic check + decrement) and idiomatic.
**Two minor issues:**

- No `ARGV` validation inside the script. A bug that passes
  `capacity=nil` from Python would set `tokens=NaN` and the bucket
  becomes silently broken. Add `if capacity == nil or refill == nil
  then return -1 end` and treat -1 in Python as a config error.
- The script computes `last_ts = now` on cold start (line 76), so the
  first call after a Redis flush gets a FULL bucket regardless of how
  much time has passed before. Acceptable; documented.
- Redis `EXPIRE 7200` (line 90) is set on every call — fine but
  redundant; `EXPIRE bucket TTL NX` would be slightly cheaper.

### B6. ✅ Capability detection: clean shape, but missing one signal

`capability_detection.py:118` returns `rate_limit_remaining=None` because
"not yet measured". The Redis bucket key exists; the read is a single
`HGET t`. Implementing this is ~5 lines and matches the RISK-3 SLO of
"admin UI shows current consumption vs cap, refreshing every 60s."
**Do this in the same PR as A2 (NestJS proxy)** — the UI will need it.

---

## C. Testing

### C1. ⚠️ 113 tests, ZERO end-to-end integration

Test counts (from `grep -c "def test_"`):
- credential_service: 17 (good — covers crypto, validation, sites)
- rollup_service: 14
- team_alias_service: 14
- tier2_inference: 13
- ownership_inference: 11
- admin_routes: 10
- ownership_routes: 10
- token_bucket: ~12 (file 180 LoC)
- timeline_service: 7
- timeline_route: 6
- alias_routes: 11
- capability_detection: ~8
- datadog_connector + strip_pii: ~25 (separate files)
- **Total observability unit tests: ~150–160** (not 274 — the
  274 figure cited in the prompt is the *combined* run including
  reused fixtures and parametrized variants).

**Gap:** `pulse/packages/pulse-data/tests/integration/` has zero
observability tests (verified by `find ... -name "*obs*"` returning
nothing). The end-to-end "rollup worker writes → API serves the
timeline" path is **only mocked**. A real integration test would:

1. Spin up Postgres + Redis (via the existing `testcontainers` fixture in
   `tests/integration/`).
2. Seed `tenant_observability_credentials`, `service_squad_ownership`,
   `eng_deployments`.
3. Invoke `rollup_service.run_cycle()` with a fakehttpx provider.
4. HTTP-GET `/data/v1/obs/timeline?squad_key=FID` and assert shape.

Estimated: ~1d for the fixture + 3-4 happy/sad path scenarios. **High
ROI** — would have caught the `list_monitors_for_service` Protocol gap.

### C2. ⚠️ No `test_webmotors_obs_*` exists

The user's prompt asks about `test_webmotors_obs_ownership.py` — **this
file does not exist in the repo** (`find ... -name "*webmotors*obs*"`
empty). The existing `test_webmotors_*` tests are for issue/PR coverage,
not observability. If a Webmotors-specific assertion test was promised
in the PR descriptions, it was not delivered. Recommend adding one in
the integration-test PR proposed in C1: seed the 99.8% DD coverage / 0%
qualified-squad scenario described in RISK-11.

### C3. ⚠️ Worker tests live in two places

`tests/unit/contexts/observability/services/test_rollup_service.py` AND
`tests/unit/workers/test_obs_rollup_worker.py`. The latter covers the
scheduler shell; the former covers the orchestrator. Acceptable, but
inconsistent with `metrics_worker` (single test file). Document or
consolidate.

### C4. 💡 Estimated coverage % on the new code

Rough estimate by inspection: **70–75% line coverage** on the obs
modules. The shape:

- credential_service ~90% (heavy unit coverage)
- rollup_service ~75% (deadline + rate-limit + happy path; provider
  exception branches partially covered)
- timeline_service ~65% (the squad path has 2 tests; the service path 4;
  no coverage of "repos=∅" early return)
- ownership_inference ~70% (Tier 1 happy path + override path; the
  metadata-allowlist filter is barely exercised)
- token_bucket ~80% (lua mock, fail-closed path)
- tier2_inference ~85% (gate-by-gate parametric tests)

Recommend `pytest --cov=src/contexts/observability` to confirm — config
already supports it in `pyproject.toml`.

---

## D. Security Architecture Review

### D1. ✅ The CISO reviews caught the right things

`docs/security-reviews/FDD-OBS-001-pr2-datadog-review.md` and `pr4a-rollup-review.md`
both surface real issues (H-001 sqlalchemy_echo isolation, H-002
`hide_parameters`, M-001 nested PII, L-003 site allowlist) and the fixes
landed. No theatre.

### D2. ⚠️ Things CISO did NOT catch that I'd flag

- **`database.py:49` f-string SET app.current_tenant** — Type system
  protects today (UUID), but H-class severity if anyone passes a string.
  Add a one-line `quote_literal` wrapper. **Backlog: RISK-21 (new).**
- **`hide_parameters=True` is engine-level — but only applies to
  SQLAlchemy-emitted exceptions.** A raw asyncpg/psycopg
  `InvalidTextRepresentationError` raised inside the driver can still
  carry the bound parameter dict before it reaches SQLA. The fix is
  *complete* against `AmbiguousParameterError` (the one caught live), but
  any DB-driver-level exception path is **not** covered. To validate,
  add an integration test that triggers a driver-side error (e.g.
  malformed UUID) inside `upsert_credential` and asserts the exception
  message contains zero substring of the plaintext key. **Backlog
  RISK-22 (new).**
- **`_set_tenant` runs *before* any tenant validation.** If a route bug
  passes `tenant_id=settings.default_tenant_id` after RLS bypass logic
  was meant to apply, every observability read will leak default-tenant
  data. Today only one tenant exists, but R1 needs an "explicit tenant
  context" guard pattern.

### D3. ⚠️ ADR-025 5-layer enforcement — Layer 4 has a real gap

Layer 4 (`tests/unit/test_obs_anti_surveillance.py`) only scans
`src/connectors/observability/` and `src/contexts/observability/`.
**`src/workers/obs_rollup_worker.py` is NOT scanned** — this is RISK-12,
already in the backlog, but the user's prompt asks "are all 5 layers
actually deployed?" — **Layer 4 is deployed but with an
acknowledged-and-untracked-as-blocking gap.** Promote RISK-12 to P0
pre-R2 ($30min fix per the backlog).

Layer 2 (DB trigger) — **shipped in migration 018 but RISK-7 acknowledges
top-level-keys-only.** Migration 020 was supposed to ship the recursive
`jsonb_path_exists` fix; verified by `Read 020_obs_creds_site_check.py`
the migration only adds site CHECK, NOT the trigger upgrade.
**RISK-7 is open and unshipped, contrary to what migration-numbering
might suggest.**

### D4. 🚨 No key rotation runbook — RISK-8 unaddressed

RISK-8 ("Master key rotation runbook") is in the backlog dated 2026-04
something. Today the procedure is:

1. Operator runs `openssl rand -base64 32`
2. Sets `PULSE_OBS_MASTER_KEY_NEW` (this env var doesn't exist anywhere
   in the codebase — verified via grep)
3. ...???

**There is no `scripts/rotate_obs_master_key.py`**, no entry in
`docs/security-reviews/obs-master-key-rotation-runbook.md`, no
re-encryption path. For R0 (single dev tenant) this is OK. For ANY
friendly tenant who stores a real DD app key, the answer to "what if the
key leaks?" is currently "we can't rotate without a manual SQL update
that decrypts each row and re-encrypts under the new key, and we've
never tested that path."

**Before friendly-tenant exposure:** ship `scripts/rotate_obs_master_key.py`
(~3h) + runbook (~1h) + dry-run smoke test (~1h). **Hard pre-R2 blocker.**

---

## E. Operational Quality

### E1. ⚠️ Worker observability — invisible to operators

`obs-rollup-worker` healthcheck is `python -c 'import os;
os.stat("/proc/1/status")'` (`docker-compose.yml:243`). This passes as
long as PID 1 exists. **It does NOT detect:**

- Worker stuck in a tight DD-503 retry loop.
- Cycles consistently overrunning the 12-min deadline.
- Token bucket exhausted every cycle for the last 4 hours.
- Tier 2 inference silently failing each cycle (current behaviour
  per `rollup_service.py:253-259` — it's logged WARN and the cycle
  continues, but no metrics export).

**Fix:** the worker should emit Prometheus counters or write a
`worker_health.last_cycle` row to a new ops table. Carlos's UI then
shows a "warming up / freshness" indicator. Estimated: ~4h, covers
RISK-3 acceptance criterion ("API calls today: X / 300").

### E2. ⚠️ Cycle-time monitoring — no alerts

12-min deadline is enforced (`rollup_service.py:60`) and logged
(`rollup_service.py:406-411`), but nothing alerts. A regression that
makes cycles 14-min would tick along silently until a tenant complains
about stale data.

**Fix:** in CI, add `pytest-benchmark` for `_rollup_one_tenant` with 100
fake services and assert < 60s. Catches algorithmic regressions
pre-merge.

### E3. ⚠️ Rate-limit calibration — flying blind

RISK-16 acknowledges 500 tokens/h is "conservative" but for
Webmotors's actual Pro+ plan we don't know the real ceiling. The token
bucket should LOG every refill + every denial with the counter value so
we can graph actual consumption vs theoretical limit. Today
`logger.info("[rollup] rate-limited tenant=%s svc_hash=%s — pausing this
cycle", ...)` happens at the denial point but the bucket level isn't
logged. **Add `bucket.remaining(tenant_id)` introspection + emit per
cycle.** ~30min.

### E4. ✅ Kill switch is well-designed

`OBS_ROLLUP_ENABLED=false` is a clean kill switch, tested in
`test_obs_rollup_worker.py`. Mirror it on the validate endpoint (env
flag to disable new connections) for full operational containment.

---

## F. Documentation Gaps

### F1. 🚨 No tenant onboarding runbook

`scripts/datadog_register.sh` exists (mentioned in the user prompt — I
didn't find it via grep, may be uncommitted) but no markdown runbook for
"how does an operator onboard a new DD tenant end-to-end". Process today
appears to be:

1. Operator gets tenant API key + app key + site
2. `curl POST /data/v1/admin/integrations/datadog/validate?persist=true`
3. `curl POST /data/v1/admin/integrations/datadog/ownership/sync`
4. Wait 5h+ for first full rollup cycle
5. Open... what URL? (Carlos page lives at port 8080 static-server.)

**Needed:** `docs/runbooks/observability-tenant-onboarding.md`. ~1h.

### F2. 🚨 No architecture overview doc

8 PRs. 8 ADRs. 3 CISO reviews. Zero "here's the system at a glance" doc.
A new engineer reading this codebase needs to follow PR chains to
understand the data flow.

**Needed:** `docs/fdd/FDD-OBS-001-architecture.md` with:

- one Mermaid diagram (tenant → admin endpoint → credential_service →
  pgcrypto; rollup worker → provider_factory → DatadogProvider →
  obs_metric_snapshots; UI → timeline_service → joined view).
- inventory of all 22 endpoints / 5 tables / 4 services / 1 worker
- the 5 anti-surveillance layers in one paragraph.

~2h, would pay back in any onboarding or review.

### F3. ⚠️ ADR-028 (key residence) is a follow-up to ADR-021 — not cross-linked

Reading ADR-021 in isolation, you'd miss that ADR-028 sharpens the
in-memory residence story for the worker. Add "Subsequent ADRs: 028
(rollup worker key residence)" at the bottom of 021.

### F4. ⚠️ Did `pulse-engineer` follow CLAUDE.md routing?

Honest assessment per the user's question:

| File location | Should have been written by | Was written by | Verdict |
|---|---|---|---|
| `packages/pulse-data/src/contexts/observability/**` | `pulse-engineer` | `pulse-engineer` | ✅ |
| `packages/pulse-data/src/connectors/observability/**` | `pulse-engineer` | `pulse-engineer` | ✅ |
| `packages/pulse-data/src/workers/obs_rollup_worker.py` | `pulse-engineer` | `pulse-engineer` | ✅ |
| `pulse-ui/pages/observability-timeline/**` | `pulse-frontend` | `pulse-engineer` | ❌ routing violation |
| `pulse-ui/pages/observability-ownership/**` | `pulse-frontend` | `pulse-engineer` | ❌ routing violation |
| `packages/pulse-web/src/routes/_dashboard/observability/**` | `pulse-engineer` | **nobody (missing)** | 🚨 deliverable gap |
| `docs/adrs/0{21..28}-*.md` | orchestrator + `pulse-ciso` co-sign | written in flow | ✅ acceptable |
| `docs/security-reviews/FDD-OBS-001-*.md` | `pulse-ciso` | `pulse-ciso` | ✅ |

**Net:** wrong-agent on prototype UI (low harm — code works) AND missed
the actual production-FE deliverable (high harm — that's what the user
flagged).

---

## G. Architectural Debt — Which Risks Block Production?

Triage of the 18 OBS RISK items in `ops-backlog.md`:

### 🚨 Must close before R2 friendly-tenant exposure

- **RISK-7** (top-level PII trigger only) — Layer 2 has a documented
  bypass. Migration 020 was earmarked but only shipped the site CHECK.
  XS fix.
- **RISK-8** (master-key rotation runbook + script) — operational
  blocker if any tenant key leaks.
- **RISK-12** (anti-surveillance scan misses workers) — 30min fix;
  closing it before R2 is hygiene.
- **RISK-16** (token bucket calibration) — currently undersized for
  Webmotors's 430-service catalog. Operationally the rollup table will
  warm up over 5h+ on first run; the UI must handle this honestly
  (already partly does via `has_data: false`).
- **NEW RISK-21** (database.py f-string in SET) — D2 above.
- **NEW RISK-22** (driver-level exception leak past hide_parameters) — D2.

### ⚠️ Should close pre-R1 SaaS (multi-tenant)

- **RISK-2** (Service Ownership data quality) — Tier 2 + alias map are
  the mitigations and they shipped, but the "bulk confirm heuristic"
  button (R2 acceptance criterion) isn't built — see A1 (no UI).
- **RISK-3** (DD cost surprise) — capability_detection has the slot for
  `rate_limit_remaining` but it returns None today. Easy win.
- **RISK-4** (DD plan tier disparity) — capability detection partially
  addresses this; the actual "your DD plan doesn't have X" UI message
  needs the React frontend.
- **RISK-13** (FORBIDDEN_REFS missing PR-author columns) — defensive
  hardening; current code is clean per review.
- **RISK-15** (multi-tenant worker discovery) — already P0 R1.

### 💡 Defer (correctly classified in backlog)

- **RISK-1** (KMS migration) — R4.
- **RISK-5** (spurious correlation) — only matters once enhanced metrics
  ship; current MONITOR_HEALTH is a state read, not a causation claim.
- **RISK-6** (vendor concentration) — post-R2 GA discovery as decided.
- **RISK-9 / RISK-10** (deferred CISO findings) — appropriately phased.
- **RISK-19** (Query API not entitled) — resolved via monitor-fallback.
- **RISK-20** (PII tag patterns) — extend Layer 1 list pre-R2; XS fix.

### 💡 Decisions that look right but will hurt at scale

- **Provider built per-cycle in worker** (ADR-028): correct for security,
  costly at 100 tenants. R1 should reuse providers within one cycle
  through a tenant-scoped pool with explicit `aclose()` in finally.
- **Session-per-row in `_upsert_snapshot`** (rollup_service.py:351):
  works at Webmotors's ~430 services; at R1 multi-tenant 10k services /
  cycle this is the next bottleneck.
- **`SquadDirectory.list_qualified_squads` re-queried per override**:
  cache for cycle lifetime, ~10min fix.

---

## H. Other Smells & Inconsistencies

- **`datadog_connector.py:47-69`** — `_METRIC_QUERIES[ALERT_COUNT] = ""`
  (empty string) is a code smell. Either remove the entry or raise on
  empty template. Today `query_metric` silently returns "no data" for
  ALERT_COUNT — looks like a bug.
- **`rollup_service.py:44`** — imports `TimeWindow` (line 44) but never
  uses it. Dead import.
- **`rollup_service.py:72-79`** — `_CYCLE_QUERY_METRICS` is defined but
  unreferenced (the worker uses the monitor path only). Either remove
  with a comment "kept for R3 reactivation per RISK-19" or move to a
  `_legacy.py`.
- **`ownership_inference.py:262`** — `_json_dumps` is a wrapper around
  `json.dumps` defined locally. Either inline or move to shared utils.
- **`schemas.py:158`** — `Literal["tag", "alias", "heuristic", "none"]
  | None` — having both `"none"` literal and `None` is confusing. Pick
  one (recommend nullable without the "none" literal).
- **`timeline_service.py:108`** — comment mentions `service_squad_ownership.repo_url` is in `org/name` form, but the function
  uses lazy import of `tier2_inference.normalize_repo` to do the
  normalization. Naming the value `repo_url` is misleading because the
  match in `eng_deployments` is against `lower(repo)` (`org/name`). Rename
  to `_resolve_squad_repo_names`.
- **`models.py:9-26`** — long docstring justifying why these models
  inherit from `Base` not `TenantModel`. That's defensive engineering,
  but the same justification should live in `shared/models.py` so anyone
  adding a new BC sees the choice.
- **`obs_rollup_worker.py:67-77`** — `_run_one_cycle` rebuilds `TokenBucket()` every cycle. The bucket is stateless (state is in
  Redis), so this is correct, but rebuilding the bucket means each cycle
  re-discovers Redis via `_get_redis`. A long-lived singleton would
  remove `connect_timeout` (0.5s) × number_of_calls overhead. Marginal.
- **`migration 019` (`obs_metric_snapshots`)** — `samples_count INT NOT
  NULL DEFAULT 0` is fine, but the unique constraint
  `(tenant_id, provider, service, metric, hour_bucket)` doesn't include
  an index hint for `hour_bucket DESC` reads (timeline lookback). The
  PK index serves the prefix but a separate `(tenant_id, hour_bucket
  DESC)` index would help squad-level aggregations. Profile first.
- **`docker-compose.yml:213-254`** — `obs-rollup-worker` does NOT have
  the `JIRA_*` or `GITHUB_TOKEN` env vars wired even though
  `tier2_inference` reads `eng_pull_requests` (which is populated by
  the github connector). Today that works because the worker only reads
  Postgres, but if `tier2_inference` ever needed a live fetch it would
  fail silently. Document.

---

## Action List — Priority-Ordered

### 🚨 Pre-R2 friendly-tenant (week 1 — ~5-6 days)

1. **Stand up React observability UI in `pulse-web`** (A1) — ~9 dev-days.
   Split into 4 cards (timeline, ownership, aliases, datadog admin).
2. **Add NestJS proxy module in `pulse-api`** (A2) — ~1 dev-day.
3. **Master-key rotation runbook + script + smoke test** (D4) — ~5h.
4. **Fix RISK-7 (recursive JSONB PII trigger)** — XS (1h).
5. **Fix RISK-12 (anti-surveillance scan covers workers)** — 30min.
6. **Add RISK-21 (database.py SET app.current_tenant safe quote)** — 30min.
7. **Add `docs/fdd/FDD-OBS-001-architecture.md` + onboarding runbook** (F1,
   F2) — 3h total.

### ⚠️ Pre-R1 SaaS (week 2)

8. End-to-end integration test (C1) — 1d.
9. Worker health metrics + dashboard (E1) — 4h.
10. Token bucket consumption logging (E3) — 30min.
11. Address Protocol leak `list_monitors_for_service` (B1) — 1h.
12. Batch sessions in `_upsert_snapshot` (B2) — 2h.
13. RISK-22 (driver-level exception leak audit) — 4h.

### 💡 Nice-to-have

14. Code cleanups (H) — bundled ~3h.
15. RISK-13, RISK-20 (FORBIDDEN_REFS hardening) — 1h.

---

## Final Verdict

**Backend grade: B+.** Strong DDD, real anti-surveillance enforcement,
sensible operational choices (kill switch, deadline, fail-closed bucket).
Two real abstraction leaks and a handful of "future-you will hate this"
patterns (session-per-row, provider Protocol gap).

**Operational grade: C+.** Kill switch ✅. Healthcheck ⚠️ (process-only).
Rotation story ❌. Calibration story ⚠️.

**Frontend grade: F (not delivered to production).** Beautiful prototype,
no React.

**Security grade: B.** CISO process caught the real things; two new
findings to add (D2). Rotation runbook is a gating item.

**Overall:** This is **"internal pilot ready"**. To say "friendly-tenant
ready" with a straight face, close the 7 🚨 items above. Estimated 5-6
calendar days of focused work; ~9-10 dev-days if the React build runs
serial. Webmotors as the anchor partner makes this very doable — their
data already validates the backend end-to-end.

The work is good. The gap is that it stops at the API.
