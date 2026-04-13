/**
 * k6 load test: Jira Dynamic Discovery API — ADR-014
 *
 * Three scenarios:
 *
 * A) "tenant-with-500-projects"
 *    - Paginated GET /api/v1/admin/integrations/jira/projects (50 rows/page)
 *    - 60 seconds of continuous load from 20 VUs
 *    - Threshold: p95 < 400ms, error rate < 1%
 *
 * B) "rate-budget-guardrail"
 *    - POST /api/v1/admin/integrations/jira/guardrails/rate-check with varying
 *      issues_to_fetch counts; bucket capacity is 100 per hour.
 *    - 200 concurrent VUs for 30 seconds
 *    - Asserts server stays healthy (no 5xx); ~100 should succeed (bucket cap)
 *
 * C) "discovery-trigger-spam"
 *    - POST /api/v1/admin/integrations/jira/discover from 10 VUs × 5 iterations
 *      = 50 requests within a 10s window
 *    - Server must return 200/202/429 (no 5xx); demonstrates single-flight or
 *      rate-limiting behaviour
 *
 * Output:
 *   Results printed to stdout.
 *   JSON summary written to /tmp/k6-jira-discovery-summary.json
 *
 * Usage:
 *   k6 run pulse/performance/k6/jira-discovery-load.js
 *   k6 run --env BASE_URL=http://localhost:8000 pulse/performance/k6/jira-discovery-load.js
 *
 * Prerequisites:
 *   - API server running and accessible at BASE_URL
 *   - Test tenant seeded with 500 catalog rows (use setup() or SQL script below)
 *
 * SQL seed (run once before scenario A):
 *   INSERT INTO jira_project_catalog (id, tenant_id, project_key, project_id, name,
 *     project_type, status, consecutive_failures, metadata)
 *   SELECT
 *     gen_random_uuid(),
 *     '00000000-0000-0000-0000-000000000001'::uuid,
 *     'LOAD' || generate_series::text,
 *     'ID-LOAD' || generate_series::text,
 *     'Load Test Project ' || generate_series::text,
 *     'software',
 *     CASE WHEN (generate_series % 4) = 0 THEN 'active'
 *          WHEN (generate_series % 4) = 1 THEN 'discovered'
 *          WHEN (generate_series % 4) = 2 THEN 'paused'
 *          ELSE 'blocked' END,
 *     0,
 *     '{}'::jsonb
 *   FROM generate_series(1, 500)
 *   ON CONFLICT DO NOTHING;
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const TENANT_ID = '00000000-0000-0000-0000-000000000001';
const API_BASE = `${BASE_URL}/api/v1/admin/integrations/jira`;

const DEFAULT_HEADERS = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
  // In test environments the dev auth middleware accepts this header to skip JWT
  'X-Test-Tenant-ID': TENANT_ID,
};

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const scenarioAErrors = new Rate('scenario_a_error_rate');
const scenarioADuration = new Trend('scenario_a_p95_ms', true);
const scenarioBAllowed = new Counter('scenario_b_allowed_requests');
const scenarioBDenied = new Counter('scenario_b_denied_requests');
const scenarioCServerErrors = new Counter('scenario_c_5xx_count');
const triggerResponseCodes = new Counter('discovery_trigger_response_codes');

// ---------------------------------------------------------------------------
// k6 scenario configuration
// ---------------------------------------------------------------------------

export const options = {
  scenarios: {
    // ----------------------------------------------------------------
    // Scenario A: 500-project paginated listing
    // ----------------------------------------------------------------
    tenant_with_500_projects: {
      executor: 'constant-vus',
      vus: 20,
      duration: '60s',
      exec: 'scenarioA',
      tags: { scenario: 'A' },
    },

    // ----------------------------------------------------------------
    // Scenario B: Rate budget guardrail stress
    // ----------------------------------------------------------------
    rate_budget_guardrail: {
      executor: 'constant-vus',
      vus: 200,
      duration: '30s',
      exec: 'scenarioB',
      startTime: '65s', // starts after scenario A completes
      tags: { scenario: 'B' },
    },

    // ----------------------------------------------------------------
    // Scenario C: Discovery trigger spam
    // ----------------------------------------------------------------
    discovery_trigger_spam: {
      executor: 'per-vu-iterations',
      vus: 10,
      iterations: 5,   // 10 × 5 = 50 requests
      maxDuration: '20s',
      exec: 'scenarioC',
      startTime: '100s', // starts after scenario B completes
      tags: { scenario: 'C' },
    },
  },

  thresholds: {
    // Scenario A thresholds (applied globally; scenario-specific tags used for
    // filtering in the JSON summary).
    http_req_duration: ['p(95)<400'],
    http_req_failed: ['rate<0.01'],

    // Scenario-specific custom metrics
    scenario_a_error_rate: ['rate<0.01'],
    scenario_a_p95_ms: ['p(95)<400'],

    // Scenario C: zero 5xx responses
    scenario_c_5xx_count: ['count<1'],
  },

  // Output options
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

// ---------------------------------------------------------------------------
// Setup: verify the API is reachable before running
// ---------------------------------------------------------------------------

export function setup() {
  const res = http.get(`${API_BASE}/config`, { headers: DEFAULT_HEADERS });
  if (res.status >= 500) {
    console.error(
      `[setup] API not reachable or returned ${res.status}. ` +
        'Ensure the server is running and the test tenant is seeded.'
    );
  }
  return { baseUrl: BASE_URL };
}

// ---------------------------------------------------------------------------
// Scenario A — Paginated catalog listing for tenant with 500 projects
// ---------------------------------------------------------------------------

export function scenarioA() {
  group('Scenario A: paginated catalog (500 projects)', () => {
    const pageSize = 50;
    // Randomise offset so all pages are exercised under load
    const maxOffset = 450; // 500 - 50 = last page start
    const offset = Math.floor(Math.random() * (maxOffset / pageSize)) * pageSize;

    const url = `${API_BASE}/projects?limit=${pageSize}&offset=${offset}&sort_by=project_key&sort_dir=asc`;
    const res = http.get(url, { headers: DEFAULT_HEADERS, tags: { name: 'catalog_list' } });

    const ok = check(res, {
      'A: status is 200': (r) => r.status === 200,
      'A: response has items array': (r) => {
        try {
          const body = JSON.parse(r.body as string);
          return Array.isArray(body.items);
        } catch {
          return false;
        }
      },
      'A: response time < 400ms': (r) => r.timings.duration < 400,
    });

    scenarioAErrors.add(!ok);
    scenarioADuration.add(res.timings.duration);

    // No sleep — maintain continuous load for accurate p95
  });
}

// ---------------------------------------------------------------------------
// Scenario B — Rate budget guardrail: token-bucket cap at max_issues_per_hour=100
// ---------------------------------------------------------------------------

export function scenarioB() {
  group('Scenario B: rate budget guardrail (200 concurrent VUs)', () => {
    // Each VU requests 1 issue token. With max=100 and 200 VUs hitting at once,
    // ~100 should succeed and ~100 should be denied (rate limited).
    const payload = JSON.stringify({ issues_to_fetch: 1 });
    const res = http.post(
      `${API_BASE}/guardrails/rate-check`,
      payload,
      {
        headers: DEFAULT_HEADERS,
        tags: { name: 'rate_check' },
      }
    );

    check(res, {
      'B: server stays healthy (no 5xx)': (r) => r.status < 500,
    });

    if (res.status === 200) {
      // Token granted
      const body = (() => {
        try { return JSON.parse(res.body as string); } catch { return {}; }
      })();
      if (body.allowed === true) {
        scenarioBAllowed.add(1);
      } else {
        scenarioBDenied.add(1);
      }
    } else if (res.status === 429) {
      // Rate limited — also counts as denied
      scenarioBDenied.add(1);
    }

    sleep(0.01); // minimal pause to avoid overwhelming Redis
  });
}

// ---------------------------------------------------------------------------
// Scenario C — Discovery trigger spam: 50 POST /discover in 10s
// ---------------------------------------------------------------------------

export function scenarioC() {
  group('Scenario C: discovery trigger spam (10 VUs × 5 iter)', () => {
    const res = http.post(
      `${API_BASE}/discover`,
      JSON.stringify({}),
      {
        headers: DEFAULT_HEADERS,
        tags: { name: 'discovery_trigger' },
      }
    );

    // Record response code for summary
    triggerResponseCodes.add(1, { status: String(res.status) });

    const ok = check(res, {
      'C: no 5xx on trigger spam': (r) => r.status < 500,
      'C: response is 200, 202, or 429': (r) =>
        r.status === 200 || r.status === 202 || r.status === 429,
    });

    if (res.status >= 500) {
      scenarioCServerErrors.add(1);
    }

    // No sleep — test single-flight / rate-limiting robustness
  });
}

// ---------------------------------------------------------------------------
// Summary output — printed to stdout + JSON file
// ---------------------------------------------------------------------------

export function handleSummary(data: Parameters<typeof textSummary>[0]) {
  const summary = textSummary(data, { indent: '  ', enableColors: true });

  console.log('\n' + summary);
  console.log('\n--- ADR-014 Load Test Interpretation ---');
  console.log(
    'Scenario A (p95 catalog listing):',
    data.metrics['scenario_a_p95_ms']?.values?.['p(95)'] ?? 'N/A',
    'ms (threshold: <400ms)'
  );
  console.log(
    'Scenario A error rate:',
    ((data.metrics['scenario_a_error_rate']?.values?.rate ?? 0) * 100).toFixed(2) + '%',
    '(threshold: <1%)'
  );
  console.log(
    'Scenario B allowed:',
    data.metrics['scenario_b_allowed_requests']?.values?.count ?? 0,
    '/ denied:',
    data.metrics['scenario_b_denied_requests']?.values?.count ?? 0
  );
  console.log(
    'Scenario C server errors (5xx):',
    data.metrics['scenario_c_5xx_count']?.values?.count ?? 0,
    '(threshold: 0)'
  );

  return {
    stdout: summary,
    '/tmp/k6-jira-discovery-summary.json': JSON.stringify(data, null, 2),
  };
}
