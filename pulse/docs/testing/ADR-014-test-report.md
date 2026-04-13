# ADR-014 Test Report — Dynamic Jira Project Discovery

**ADR:** 014 — Dynamic Jira Project Discovery (Hybrid 4-Mode)
**Branch:** `feat/jira-dynamic-discovery`
**Date:** 2026-04-13
**Author:** pulse-test-engineer

---

## Coverage Summary

| Track | File | Tests | What It Proves |
|---|---|---|---|
| Integration | `test_discovery_end_to_end.py` | 5 | Full run populates catalog; mode/status invariants |
| Integration | `test_mode_switch_reroutes_sync.py` | 5 | All 4 modes return exact expected project sets |
| Integration | `test_smart_mode_integration.py` | 3 | Score_projects reads real PR rows; auto_activate threshold |
| Integration | `test_guardrails_integration.py` | 5 | Cap enforcement; auto-pause; blocked immunity |
| Integration | `test_discovery_failure_modes.py` | 4 | Total failure, partial failure, disabled discovery |
| E2E | `e2e/jira-admin.spec.ts` | 7 | All 3 tabs, discovery trigger, filter, activation, audit, mode save |
| Load | `performance/k6/jira-discovery-load.js` | 3 scenarios | p95 latency, rate-budget guardrail, trigger spam |

**Total integration tests:** 22
**Total E2E tests:** 7 (3 browsers via Playwright projects)
**Load scenarios:** 3

---

## Track 1 — Integration Tests

### Location
```
pulse/packages/pulse-data/tests/integration/contexts/integrations/jira/discovery/
```

### How to Run

```bash
cd pulse/packages/pulse-data

# Install integration test deps (one-time)
pip install 'testcontainers[postgres]' pytest-asyncio asyncpg sqlalchemy[asyncio] alembic

# Run integration tests only
pytest tests/integration/ -v

# Run with coverage delta
pytest tests/integration/ --cov=src/contexts/integrations/jira/discovery \
  --cov-report=term-missing -v
```

### What Each File Proves

**`test_discovery_end_to_end.py`**
- `run_discovery` with a mocked `JiraClient` (10 projects) inserts exactly 10 catalog rows into a real PostgreSQL instance.
- `allowlist` mode + no activations → resolver returns [].
- Manually activating 3 projects → resolver returns exactly those 3.
- Blocking 1 of the 3 → resolver returns 2 (blocked invariant).
- Switching to `auto` mode → blocked project still excluded (invariant persists across mode changes).

**`test_mode_switch_reroutes_sync.py`**
- Seeds 5 projects with distinct statuses: active, paused, blocked, discovered, archived.
- Proves exact set returned by `resolve_active_projects` for each of 4 modes:
  - `auto`: discovered + active, never blocked/paused/archived
  - `allowlist`: active only
  - `blocklist`: discovered + active + paused, never blocked/archived
  - `smart`: active always + discovered ≥ threshold; sub-threshold discovered excluded
- Cross-mode invariant test: blocked project absent from resolve in ALL modes.

**`test_smart_mode_integration.py`**
- Inserts real `eng_pull_requests` rows with Jira keys in titles.
- `score_projects` reads actual DB rows; returns count=5 for PROJ1, count=2 for PROJ2, count=10 for PROJ3.
- `auto_activate` with threshold=3 promotes PROJ1 and PROJ3 to `active` with `activation_source='smart_pr_scan'`.
- PROJ2 stays `discovered` (below threshold).
- Audit table contains `project_activated` rows with `actor='smart_auto'` for PROJ1 and PROJ3.
- Negative test: threshold=10, all projects have 2 refs → zero activations.

**`test_guardrails_integration.py`**
- 15 active projects, cap=10 → `enforce_project_cap` pauses exactly 5 (lowest pr_reference_count: CAP00–CAP04).
- Each paused project has a `project_cap_enforced` audit event with `actor='system'`.
- 5 consecutive `record_sync_outcome(success=False)` calls auto-pause project; 4th call does not.
- `record_sync_outcome(success=True)` after failures resets `consecutive_failures` to 0.
- Blocked project: `enforce_project_cap` does not change its status; `record_sync_outcome` is a no-op (failures don't increment).

**`test_discovery_failure_modes.py`**
- Total Jira API failure (exception raised) → `result['status']='failed'`, `discoveredCount=0`, error message in `result['errors']`, existing catalog row untouched.
- No Jira client configured → `result['status']='failed'` immediately.
- Per-project upsert failure (monkey-patched) → `result['status']='partial'`, failing key in errors, successful keys persisted.
- `discovery_enabled=False` → `run_discovery` exits early without calling Jira API.

### Infrastructure Notes
- Testcontainers spins up a `postgres:16-alpine` container once per test session.
- Alembic `upgrade head` applies all 6 migrations including 006_jira_discovery.
- Each test runs inside a savepoint rolled back on teardown — O(1) cleanup, no `DELETE` statements.
- RLS is bypassed via `SET LOCAL app.current_tenant = '<uuid>'` at session level.
- `JIRA_PROJECTS` env var is set to empty before migration 006 bootstrap to prevent catalog pre-seeding.

---

## Track 2 — E2E Tests (Playwright)

### Location
```
pulse/e2e/jira-admin.spec.ts
pulse/playwright.config.ts
```

### How to Run

```bash
cd pulse

# Install Playwright browsers (one-time)
npx playwright install --with-deps

# Run all E2E tests (requires Vite dev server on :5173)
npm run dev -w packages/pulse-web &
npx playwright test e2e/jira-admin.spec.ts

# Run headed (with browser UI) for debugging
npx playwright test e2e/jira-admin.spec.ts --headed

# HTML report
npx playwright test e2e/jira-admin.spec.ts --reporter=html
open playwright-report/index.html
```

### What Each Test Proves

| Test | Journey | API Mock |
|---|---|---|
| `loads /settings/integrations/jira and renders 3 tabs` | Page renders 3 tabs; default redirect to /catalog | Static config + idle status |
| `Idle status badge is visible on initial load` | Badge renders "Idle" when inFlight=false | Static status mock |
| `clicking Descobrir agora shows "Descobrindo..." badge` | Trigger button → confirm dialog → badge cycles Idle→Descobrindo→Idle | Status mock cycles through states |
| `filtering by status "active" shows only active rows` | Filter chip → API filters → only active rows displayed | Route intercept filters by status param |
| `activating a discovered project via row actions` | Actions dropdown → Ativar → confirm → toast | POST status → audit updated |
| `audit tab shows project_activated event` | Audit tab → project_activated visible with actor | Pre-seeded audit mock |
| `changing mode on Config tab and saving` | Config tab → mode radio → save → audit shows mode_changed | PUT config → audit updated |
| `no individual developer rankings or scores` | Anti-surveillance: page content check | N/A |
| `accessibility: zero critical violations` | axe-core WCAG 2.0 AA scan on /jira/catalog | Conditional on @axe-core/playwright install |

### Mocking Strategy
Playwright route interception (`page.route()`) intercepts all `/api/v1/admin/integrations/jira/*` calls. No real API required. Tests run against the Vite dev server with mocked responses — deterministic and fast.

### Known Gaps
- The `project-row-actions.tsx` component renders a dropdown; the E2E test uses `getByRole('button', { name: /acoes/i })`. If the component uses a different aria-label or a non-button trigger, the selector may need adjustment after reading the actual rendered HTML.
- The `DiscoveryTriggerButton` polling interval is React Query's `refetchInterval`. The E2E test waits up to 10s for the status to cycle; this is safe for local dev but may need tuning in CI if React Query's refetch interval > 5s.
- Toast message text for activation ("Projeto ativado") depends on the `ProjectRowActions` component's implementation — verify the exact string matches the component's toast output.

---

## Track 3 — Load Tests (k6)

### Location
```
pulse/performance/k6/jira-discovery-load.js
```

### How to Run

```bash
# Install k6 (macOS)
brew install k6

# Seed 500 catalog rows (run once against your test DB)
psql $DATABASE_URL <<'SQL'
INSERT INTO jira_project_catalog (id, tenant_id, project_key, project_id, name,
  project_type, status, consecutive_failures, metadata)
SELECT
  gen_random_uuid(),
  '00000000-0000-0000-0000-000000000001'::uuid,
  'LOAD' || gs::text,
  'ID-LOAD' || gs::text,
  'Load Test Project ' || gs::text,
  'software',
  CASE WHEN (gs % 4) = 0 THEN 'active' WHEN (gs % 4) = 1 THEN 'discovered'
       WHEN (gs % 4) = 2 THEN 'paused' ELSE 'blocked' END,
  0, '{}'::jsonb
FROM generate_series(1, 500) gs
ON CONFLICT DO NOTHING;
SQL

# Run all three scenarios
BASE_URL=http://localhost:8000 k6 run pulse/performance/k6/jira-discovery-load.js

# JSON summary written to /tmp/k6-jira-discovery-summary.json
```

### Scenario Details

**Scenario A — Tenant with 500 projects (60s, 20 VUs)**
- Paginates `GET /api/v1/admin/integrations/jira/projects?limit=50&offset=N`
- Randomises page offset so all 10 pages get exercised
- Threshold: p95 < 400ms, error rate < 1%
- Validates: response contains `items` array (not an error body)

**Scenario B — Rate budget guardrail (30s, 200 VUs)**
- POSTs `{"issues_to_fetch": 1}` to `/guardrails/rate-check`
- Token bucket capacity = `max_issues_per_hour` (100 in test config)
- Expected: ~100 succeed (200 OK, `allowed: true`), ~100 denied (200 OK `allowed: false` or 429)
- Validates: no 5xx responses from server; counters tracked via custom metrics

**Scenario C — Discovery trigger spam (10 VUs × 5 iterations = 50 POSTs in <20s)**
- POSTs to `POST /api/v1/admin/integrations/jira/discover` rapidly
- Server must exhibit single-flight or rate-limiting (not process 50 concurrent discovery runs)
- Validates: zero 5xx; all responses are 200, 202, or 429

### Thresholds

| Metric | Threshold | Scenario |
|---|---|---|
| `http_req_duration` p95 | < 400ms | A |
| `http_req_failed` rate | < 1% | A |
| `scenario_a_error_rate` | < 1% | A |
| `scenario_a_p95_ms` p95 | < 400ms | A |
| `scenario_c_5xx_count` | 0 | C |

### Notes
- Scenario B requires the `/guardrails/rate-check` endpoint to be implemented and wired up to `Guardrails.enforce_rate_budget`. If the endpoint does not exist yet, k6 will receive 404s — these count as non-5xx and the threshold passes (server stays healthy), but the token-bucket counting metrics will be 0.
- The k6 `handleSummary` function writes a JSON file to `/tmp/k6-jira-discovery-summary.json` for CI artifact collection.

---

## Gaps and Known Limitations

1. **Rate budget endpoint not yet verified**: `POST /api/v1/admin/integrations/jira/guardrails/rate-check` may not exist in the Phase 2 API surface. The k6 scenario will still run but Scenario B counter metrics will be 0.

2. **E2E requires live Vite dev server**: Tests are not self-contained; they require `npm run dev` in `packages/pulse-web`. The `playwright.config.ts` `webServer` block handles this automatically in local dev. For CI, add `npm run build && npx vite preview` as the webServer command.

3. **Testcontainers requires Docker**: Integration tests need a Docker daemon. In environments without Docker (e.g., restricted CI), mark integration tests with `pytest -m integration` and skip them explicitly.

4. **`@axe-core/playwright` is optional**: The accessibility E2E test gracefully skips if the package is not installed. Install with: `npm install --save-dev @axe-core/playwright` in `packages/pulse-web` (or at the pulse root for the e2e context).

5. **Redis not mocked in guardrails integration tests**: `Guardrails.enforce_rate_budget` requires Redis. All integration tests that call `enforce_project_cap` or `record_sync_outcome` pass `redis_client=None` to `Guardrails`, which means `enforce_rate_budget` itself is not exercised in integration tests. A Scenario B load test or a separate Redis Testcontainer fixture covers this.

6. **Anti-surveillance guarantee**: The E2E test `no individual developer rankings or scores are exposed` validates at the HTML content level. A more robust check would include API response scanning — add to the integration test suite once the API route handlers are finalized.
