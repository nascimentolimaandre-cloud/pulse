# INC-015 — Per-squad Deep-Dive Metrics

**Status:** ✅ Phase 1 shipped (2026-05-04)
**Owner:** `pulse-engineer` (architect-validated) + `pulse-data-engineer` (data access)
**Resolves:** INC-015 (`?squad_key=OKM` silently ignored on `/dora`, `/lean`, `/cycle-time`, `/throughput`)
**Related:** FDD-DSH-060 (home on-demand — same hybrid pattern)

## 1. Problem

Four deep-dive metrics endpoints accepted `squad_key` as a query param
but ignored it (`_ = squad_key  # See FDD-DSH-060`). The metrics worker
only writes snapshots with `team_id=None` (tenant-wide). Result:
selecting "OKM" on the dashboard's deep-dive pages returned the SAME
data as "all squads" — making per-squad comparison impossible.

The `/metrics/home` endpoint had already solved this in FDD-DSH-060
via on-demand computation. INC-015 extends the same pattern to the
four deep-dive endpoints.

## 2. Architecture (validated by `pulse-engineer` agent)

Two important corrections to the initial proposal — captured here as
SaaS-architecture lessons learned:

### 2.1 Repository pattern (not "shared fetchers" module)

**Wrong proposal**: extract module-level `_fetch_*` helpers from
`home_on_demand.py` into a new `_fetchers.py`.

**Why wrong**: bypasses the `MetricsRepository` that already exists in
the same context. The `_fetch_*` helpers were the actual anti-pattern
(opening their own DB sessions, untestable, duplicating what the repo
should encapsulate). The correct fix is to **extend the existing
repository**.

**Right design**: 5 new methods on `MetricsRepository`:

```python
@staticmethod
def extract_project_key(title: str | None) -> str | None
async def get_prs_in_window(tenant_id, start, end, squad_key=None) -> list[EngPullRequest]
async def get_repos_active_for_squad(tenant_id, squad_key, lookback_days=90) -> list[str]
async def get_deployments_by_squad(tenant_id, start, end, squad_key=None, environment="production") -> list[EngDeployment]
async def get_issues_in_window(tenant_id, start, end, squad_key=None, *, date_field="created_at") -> list[EngIssue]
```

### 2.2 One service per endpoint (not one mega-file)

`services/on_demand/` package with one module per endpoint:

```
services/on_demand/
├── __init__.py     # public API re-exports
├── home.py         # compute_home_metrics_on_demand + compute_previous_period
├── dora.py         # compute_dora_on_demand
├── lean.py         # compute_lean_on_demand (CFD + WIP + LT-distrib + throughput + scatterplot)
├── cycle_time.py   # compute_cycle_time_on_demand (breakdown + trend)
└── throughput.py   # compute_throughput_on_demand (trend + pr_analytics)
```

The previous `home_on_demand.py` was deleted — it became
`services/on_demand/home.py`, refactored to use `MetricsRepository`.

### 2.3 DDD bounded-context note

`MetricsRepository` deliberately reaches into the `engineering_data`
context's models (`EngPullRequest`, `EngDeployment`, `EngIssue`,
`EngSprint`). This pre-dates INC-015. The cleaner alternative — a
separate `EngineeringDataRepository` exposed by the `engineering_data`
context — is a defensible refactor but explicitly **out of scope** for
INC-015. Documented in `repositories.py` so future maintainers know
the compromise is intentional.

### 2.4 INC-001 / INC-010 alignment

The new `get_prs_in_window` filters by `merged_at` (not `created_at`),
matching the metrics worker's snapshot-writer logic. The new
`get_issues_in_window` accepts a `date_field` selector (`created_at`
for CFD/WIP, `completed_at` for Throughput / Lead-Time-Distribution /
Scatterplot) — both INC-001 and INC-010 fix lines preserved.

## 3. Hybrid routing

Each of `/dora`, `/lean`, `/cycle-time`, `/throughput` follows:

```python
if squad_key or period == "custom":
    # On-demand path — sub-second SQL via squad-aware repo methods
    on_demand = await compute_<endpoint>_on_demand(tenant_id, start, end, squad_key)
    return <Response>(...)
# else: existing snapshot fast-path
```

Default `squad_key=None + period in {7d,14d,30d,60d,90d,120d}`
continues to read pre-computed snapshots → no performance regression
for the most common case.

## 4. Live smoke (Webmotors, 2026-05-04)

`/metrics/dora?period=30d`:

| Scope | DF/day | CFR | LT (h) |
|-------|--------|-----|--------|
| tenant-wide (snapshot) | 12.6 | 24.1% | snapshot |
| `squad_key=OKM` (on-demand) | 2.87 | 39.5% | 115.13 |
| `squad_key=BG` (on-demand) | 2.27 | 50.0% | (varies) |

Other endpoints similarly differ across squads. All sub-500ms.

## 5. Anti-surveillance

✅ Compliant. Squad granularity is `project_key` (extracted from PR
titles via `\b([A-Za-z][A-Za-z0-9]+)-\d+`). No author / assignee /
reviewer fields read or returned by any on-demand service.

## 6. Tests

Two-tier strategy (architect-recommended):

- **Unit (no DB)** — repo statics + service composition with mocked
  repository. New: 13 tests in
  `tests/unit/contexts/metrics/services/on_demand/`:
  - `test_repository_helpers.py` (8) — `extract_project_key` regex
  - `test_dora_on_demand.py` (5) — squad propagation, normalization,
    None-passthrough, output shape, calculator-error fallback
- **Integration (live Postgres)** — deferred to follow-up; live smoke
  via curl validated all 4 endpoints + tenant-wide-vs-squad differ.

Recent feature regression: 91/91 pass. The 39 pre-existing failures in
`test_dora.py` / `test_normalizer.py` are stale tests (assertions
written before INC-005 flaky filter / INC-021 effort fallback shipped)
unrelated to INC-015 — confirmed by running same tests on `main` before
my changes.

## 7. Files changed

| File | Change |
|------|--------|
| `metrics/repositories.py` | +5 methods + DDD doc-comment + `extract_project_key` static + regex constant |
| `metrics/services/on_demand/__init__.py` | NEW package with public API |
| `metrics/services/on_demand/home.py` | Moved from `services/home_on_demand.py`; refactored to use repo |
| `metrics/services/on_demand/dora.py` | NEW |
| `metrics/services/on_demand/lean.py` | NEW (5 sub-metrics) |
| `metrics/services/on_demand/cycle_time.py` | NEW (breakdown + trend) |
| `metrics/services/on_demand/throughput.py` | NEW (trend + pr_analytics) |
| `metrics/services/home_on_demand.py` | DELETED (replaced by on_demand/home.py) |
| `metrics/routes.py` | Wired hybrid for 4 endpoints; `_RELOAD_TARGETS` updated; `_build_dora_response_from_value` extracted |
| `tests/unit/contexts/metrics/services/on_demand/*` | NEW 13 tests |

## 8. Phase 2 (deferred backlog)

1. **Worker per-team snapshots** — when on-demand exceeds ~500ms (likely
   at >100 squads), add a worker loop that pre-computes per-team
   snapshots. The on-demand path becomes the fallback for cache miss
   only. Same hybrid as today, just with an extra cache layer.
2. **Engineering-data Repository** — proper DDD bounded-context
   inversion: `EngineeringDataRepository` exposed by that context;
   `MetricsRepository` composes it. Cosmetic for SaaS but cleans up
   the cross-context coupling.
3. **`flow_health_on_demand.py` audit** — likely has the same
   `_fetch_*` anti-pattern; refactor to use `MetricsRepository` in a
   follow-up.
4. **Repository integration tests** — add Testcontainers Postgres-based
   tests for the SQL paths (regex `~*`, `split_part`, GIN indexes) that
   can't be exercised with mocks.
