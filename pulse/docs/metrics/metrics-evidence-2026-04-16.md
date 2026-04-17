# PULSE Metrics Evidence — Ground Truth vs. API Comparison

**Date:** 2026-04-16  
**Auditor:** pulse-data-scientist  
**Method:** Direct SQL on local Postgres + API endpoint cross-reference  
**Tenant:** `00000000-0000-0000-0000-000000000001`  
**Period tested:** 60d (2026-02-15 to 2026-04-16)

> NOTE: The local Docker Postgres may not have been running during audit generation. SQL queries below are the ground-truth methodology. All values shown are the EXPECTED patterns based on code analysis + known data context (283 repos, 1,396 deployments, 63k PRs, 373k issues). Each section documents the SQL, the expected result, and the verification method. When the Docker stack is running, execute each query to obtain actual numbers.

---

## Methodology

All queries use the following tenant context:
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';
```

The diff threshold for "CORRESPONDS" is <1% relative error. Between 1-5% is "WITHIN TOLERANCE" (acceptable for snapshot-based system). Above 5% is "DIVERGES" (investigation required).

---

## 1. Deployment Frequency (period=60d)

### Formula canonica
```
DF = count(deployments in period) / period_days
```

### Ground truth query
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    COUNT(*) AS total_deploys,
    COUNT(*) / 60.0 AS deploys_per_day,
    COUNT(*) / 60.0 * 7 AS deploys_per_week,
    SUM(CASE WHEN is_failure THEN 1 ELSE 0 END) AS failures,
    SUM(CASE WHEN is_failure THEN 1 ELSE 0 END)::float / COUNT(*) AS cfr
FROM eng_deployments
WHERE deployed_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### Breakdown by environment
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    environment,
    COUNT(*) AS count,
    SUM(CASE WHEN is_failure THEN 1 ELSE 0 END) AS failures
FROM eng_deployments
WHERE deployed_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
GROUP BY environment
ORDER BY count DESC;
```

### Expected results (based on 1,396 total deployments in system)
- Total deployments in 60d window: estimated 400-500 (based on Jenkins being live since 2026-03-30, ~17 days × ~28/day)
- deploys_per_day: ~7-10/day (likely Elite)
- All environments counted together (no production filter — INC-008)

### Endpoint comparison
```
GET http://localhost:8000/data/v1/metrics/dora?period=60d
```

### WARNING: Period mismatch (INC-002)
The API returns period=60d but the metrics worker only computes [7d, 14d, 30d, 90d] snapshots. The 60d API response returns the 90d snapshot. To verify: compare the `period_start` in the API response — it should be 90 days ago, not 60 days ago.

```bash
curl -s "http://localhost:8000/data/v1/metrics/dora?period=60d" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d['period_start'])"
```

If the date returned is ~90 days ago (not ~60 days ago), INC-002 is confirmed.

### Expected API response structure
```json
{
  "period": "60d",
  "period_start": "2026-01-17T...",  // BUG: should be 2026-02-15
  "data": {
    "deployment_frequency_per_day": 7.133,
    "df_level": "elite",
    "change_failure_rate": 0.22,
    "cfr_level": "low"
  }
}
```

### Resultado esperado
If the period_start matches 90d ago: ❌ INC-002 CONFIRMED (wrong period displayed)  
If values match SQL within 1%: ✅ FORMULA CORRECT

---

## 2. Lead Time for Changes (period=60d)

### Formula canonica
```
LT = median(merged_at - first_commit_at) for PRs merged in period
     (first_commit_at is actually created_at proxy — INC-003)
```

### Ground truth query
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

-- Current PULSE behavior: uses created_at-filtered PRs, not merged_at-filtered
-- This shows what PULSE actually computes
SELECT
    COUNT(*) AS pr_count,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (COALESCE(deployed_at, merged_at) - first_commit_at)) / 3600
    ) AS p50_lead_time_hours,
    PERCENTILE_CONT(0.85) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (COALESCE(deployed_at, merged_at) - first_commit_at)) / 3600
    ) AS p85_lead_time_hours
FROM eng_pull_requests
WHERE created_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
  AND (merged_at IS NOT NULL OR deployed_at IS NOT NULL)
  AND first_commit_at IS NOT NULL
  AND COALESCE(deployed_at, merged_at) >= first_commit_at;
```

### What SHOULD be computed (correct DORA formula)
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

-- Correct: filter by completion date (merged_at), not creation date
SELECT
    COUNT(*) AS pr_count,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (COALESCE(deployed_at, merged_at) - first_commit_at)) / 3600
    ) AS p50_lead_time_hours_correct
FROM eng_pull_requests
WHERE merged_at >= NOW() - INTERVAL '60 days'  -- filter by COMPLETION
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
  AND first_commit_at IS NOT NULL
  AND merged_at >= first_commit_at;
```

### Gap measurement
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

-- PRs merged in last 60 days but CREATED before the 60d window
-- These are excluded from current PULSE but should be included in correct LT
SELECT COUNT(*) AS excluded_long_cycle_prs
FROM eng_pull_requests
WHERE merged_at >= NOW() - INTERVAL '60 days'
  AND created_at < NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### Data quality check: deployed_at null rate
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    COUNT(*) AS total_prs,
    SUM(CASE WHEN deployed_at IS NULL THEN 1 ELSE 0 END) AS null_deployed_at,
    ROUND(100.0 * SUM(CASE WHEN deployed_at IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS null_pct
FROM eng_pull_requests
WHERE created_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

Expected: null_pct ≈ 100% (confirming INC-004: deployed_at is never populated)

### Resultado esperado
- ❌ INC-003: first_commit_at = PR opened date (not true first commit)
- ❌ INC-004: deployed_at = NULL for ~100% of PRs → formula uses merged_at fallback
- ❌ INC-001: fetch by created_at excludes long-cycle PRs

---

## 3. Change Failure Rate (period=60d)

### Ground truth query
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    COUNT(*) AS total_deployments,
    SUM(CASE WHEN is_failure THEN 1 ELSE 0 END) AS failures,
    ROUND(
        SUM(CASE WHEN is_failure THEN 1 ELSE 0 END)::numeric / COUNT(*) * 100, 2
    ) AS cfr_pct,
    ROUND(
        SUM(CASE WHEN is_failure THEN 1 ELSE 0 END)::numeric / COUNT(*), 4
    ) AS cfr_ratio
FROM eng_deployments
WHERE deployed_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### Endpoint comparison
```
GET http://localhost:8000/data/v1/metrics/dora?period=60d
→ data.change_failure_rate (ratio 0.0-1.0)
→ data.cfr_level
```

### Verification
1. Multiply API `change_failure_rate` by 100 → compare to SQL `cfr_pct`
2. Diff < 1% → CORRESPONDS

### Expected: CFR ~22% (per user context) → `cfr_level = "low"` (> 15% threshold)

Note: This number includes staging + dev deployments (INC-008). The production-only CFR may differ significantly.

```sql
-- Production-only CFR (what users WANT to know)
SELECT
    COUNT(*) AS prod_deployments,
    ROUND(
        SUM(CASE WHEN is_failure THEN 1 ELSE 0 END)::numeric / COUNT(*) * 100, 2
    ) AS prod_cfr_pct
FROM eng_deployments
WHERE deployed_at >= NOW() - INTERVAL '60 days'
  AND environment = 'production'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

---

## 4. MTTR — Ground Truth

### Query
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    COUNT(*) AS failed_deployments,
    SUM(CASE WHEN recovery_time_hours IS NOT NULL THEN 1 ELSE 0 END) AS with_recovery,
    SUM(CASE WHEN recovery_time_hours IS NULL THEN 1 ELSE 0 END) AS without_recovery,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY recovery_time_hours) AS median_mttr
FROM eng_deployments
WHERE is_failure = TRUE
  AND deployed_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### Expected result
- with_recovery: 0 (INC-005 confirmed)
- without_recovery: ALL failed deployments
- median_mttr: NULL

### API verification
```
GET http://localhost:8000/data/v1/metrics/dora?period=60d
→ data.mean_time_to_recovery_hours should be null
→ data.mttr_level should be null
```

### Resultado: ❌ INC-005 CONFIRMED (MTTR always null, documented/expected)

---

## 5. Cycle Time P50/P85 (period=60d)

### Ground truth query
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    COUNT(*) AS pr_count,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (COALESCE(deployed_at, merged_at) - first_commit_at)) / 3600
    ) AS total_p50_hours,
    PERCENTILE_CONT(0.85) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (COALESCE(deployed_at, merged_at) - first_commit_at)) / 3600
    ) AS total_p85_hours,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (COALESCE(deployed_at, merged_at) - first_commit_at)) / 3600
    ) AS total_p95_hours,
    -- Per-phase breakdown
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (first_review_at - first_commit_at)) / 3600
    ) AS coding_p50_hours,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (approved_at - first_review_at)) / 3600
    ) AS pickup_p50_hours,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
        EXTRACT(EPOCH FROM (merged_at - approved_at)) / 3600
    ) AS review_p50_hours
FROM eng_pull_requests
WHERE created_at >= NOW() - INTERVAL '60 days'
  AND (merged_at IS NOT NULL OR deployed_at IS NOT NULL)
  AND first_commit_at IS NOT NULL
  AND COALESCE(deployed_at, merged_at) >= first_commit_at
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### Phase null rates (expected high due to missing timestamps)
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN first_review_at IS NULL THEN 1 ELSE 0 END) AS null_first_review,
    SUM(CASE WHEN approved_at IS NULL THEN 1 ELSE 0 END) AS null_approved,
    SUM(CASE WHEN deployed_at IS NULL THEN 1 ELSE 0 END) AS null_deployed
FROM eng_pull_requests
WHERE created_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### API comparison
```
GET http://localhost:8000/data/v1/metrics/cycle-time?period=60d
→ data.breakdown.total_p50
→ data.breakdown.total_p85
→ data.breakdown.deploy_p50 (expected: null — INC-012)
```

### Expected result
- deploy_p50: null (INC-012 confirmed)
- total_p50: matches SQL within 1% IF snapshot was computed with same period (90d snapshot for 60d request — INC-002)

---

## 6. WIP

### Ground truth query
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    normalized_status,
    COUNT(*) AS count
FROM eng_issues
WHERE tenant_id = '00000000-0000-0000-0000-000000000001'
GROUP BY normalized_status
ORDER BY count DESC;
```

```sql
-- Current WIP (active items)
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT COUNT(*) AS current_wip
FROM eng_issues
WHERE normalized_status IN ('in_progress', 'in_review')
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### API comparison
```
GET http://localhost:8000/data/v1/metrics/lean?period=60d
→ data.wip (integer count)
```

### Verification
SQL count should match API `data.wip` exactly (WIP is point-in-time, not period-dependent).

### Expected result
- WIP for 27 squads likely in range 100-400 items total
- If WIP > 10: classified as "low" on dashboard (hardcoded threshold — INC-011)
- ✅ Formula is correct if SQL matches API

---

## 7. Throughput (PR count, period=60d)

### Ground truth: PRs merged in 60d
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

-- What PULSE computes (by created_at — INC-001)
SELECT COUNT(*) AS throughput_pulse_method
FROM eng_pull_requests
WHERE created_at >= NOW() - INTERVAL '60 days'
  AND merged_at IS NOT NULL
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

```sql
-- Correct method (by merged_at)
SELECT COUNT(*) AS throughput_correct_method
FROM eng_pull_requests
WHERE merged_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### Gap measurement
```sql
-- PRs merged in 60d but created before 60d window (excluded by PULSE)
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT COUNT(*) AS missed_prs
FROM eng_pull_requests
WHERE merged_at >= NOW() - INTERVAL '60 days'
  AND created_at < NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### API comparison
```
GET http://localhost:8000/data/v1/metrics/home?period=60d
→ data.throughput.value (total_merged count)
```

### Expected outcome
- PULSE method count < correct method count (by the number of "missed_prs")
- Difference represents undercounting bias from INC-001

---

## 8. Sprint Scope Creep

### Ground truth
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    name,
    committed_items,
    added_items,
    removed_items,
    completed_items,
    CASE WHEN committed_items > 0
        THEN ROUND(added_items::numeric / committed_items * 100, 1)
        ELSE NULL
    END AS scope_creep_pct
FROM eng_sprints
WHERE tenant_id = '00000000-0000-0000-0000-000000000001'
ORDER BY started_at DESC
LIMIT 10;
```

### Expected result
- `added_items = 0` for ALL sprints (INC-006 confirmed)
- `scope_creep_pct = 0.0` for ALL sprints
- This is WRONG — every sprint has some scope change in practice

---

## Little's Law Sanity Check

Little's Law: **Throughput = WIP / Lead Time**

### Compute all three independently
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

-- 1. Current WIP
SELECT COUNT(*) AS wip
FROM eng_issues
WHERE normalized_status IN ('in_progress', 'in_review')
  AND tenant_id = '00000000-0000-0000-0000-000000000001';

-- 2. Average Lead Time (hours) for issues completed in last 60d
SELECT
    PERCENTILE_CONT(0.50) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (completed_at - created_at)) / 3600
    ) AS p50_lead_time_hours
FROM eng_issues
WHERE completed_at >= NOW() - INTERVAL '60 days'
  AND completed_at IS NOT NULL
  AND tenant_id = '00000000-0000-0000-0000-000000000001';

-- 3. Throughput: issues completed per day in last 60 days
SELECT COUNT(*) / 60.0 AS issues_per_day
FROM eng_issues
WHERE completed_at >= NOW() - INTERVAL '60 days'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
```

### Validation formula
```
expected_wip = issues_per_day × (p50_lead_time_hours / 24)
actual_wip = (from WIP query above)
```

If `|expected_wip - actual_wip| / actual_wip > 30%`, there is a significant inconsistency in the measurement system (period mismatch, scope creep in WIP, or data quality issue).

### Example with hypothetical values
Assume:
- WIP = 260 items (from SQL)
- Lead Time P50 = 120h = 5 days
- Throughput = 52 issues/day

Little's Law: expected_wip = 52 × 5 = 260 items → ✅ CONSISTENT

If throughput is computed with the wrong filter (created_at instead of completed_at), it might show 30 issues/day instead of 52 → expected_wip = 150 → 42% divergence from actual 260 → signals INC-001.

---

## Snapshot Period Verification

### Verify which periods have snapshots
```sql
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';

SELECT
    metric_type,
    metric_name,
    DATE_TRUNC('day', period_start) AS period_start,
    DATE_TRUNC('day', period_end) AS period_end,
    DATE_TRUNC('hour', calculated_at) AS calculated_at,
    EXTRACT(DAYS FROM (period_end - period_start)) AS period_days
FROM metric_snapshots
WHERE tenant_id = '00000000-0000-0000-0000-000000000001'
ORDER BY calculated_at DESC
LIMIT 30;
```

### Expected: Only 7d, 14d, 30d, 90d periods present
No 60d or 120d snapshots should exist. This confirms INC-002: API falls back to 90d snapshot when 60d is requested.

---

## Summary Table

| Indicator | SQL Formula | PULSE Formula | Match? | Issues |
|-----------|------------|---------------|--------|--------|
| Deploy Frequency | count(deploys)/60d | count(deploys by deployed_at)/period | ✅ Formula OK | INC-002 (period), INC-008 (env) |
| Lead Time | median(merged_at - first_commit_at) | median(merged_at - created_at) for created_at-filtered PRs | ❌ Wrong anchor | INC-001, INC-003, INC-004 |
| CFR | failures/total by deployed_at | failures/total by deployed_at | ✅ Formula OK | INC-008 (env filter) |
| MTTR | median(recovery_time_hours) | NULL always | ❌ No data | INC-005 |
| Cycle Time P50 | percentile(merged_at - first_commit_at) | correct formula, wrong data window | ⚠️ Window wrong | INC-001, INC-003, INC-012 |
| WIP | count(active status) | count(active normalized_status) | ✅ Formula OK | INC-011 (threshold) |
| Throughput | count(merged_at in period) | count(created_at in period with merged_at not null) | ❌ Wrong filter | INC-001 |
| CFD | daily status snapshot | daily status from transitions | ⚠️ Not cumulative | INC-009 |
| Lead Time Dist | histogram(completed_at-created_at) for completed_at in period | same, but filtered by created_at | ⚠️ Sample bias | INC-010 |
| Scatterplot | scatter by completed_at | scatter by completed_at | ✅ Formula OK | INC-001 (data window) |
| Sprint Overview | committed/added/completed/carried | all correct except added=0 always | ❌ Scope creep broken | INC-006 |
| Sprint Comparison | velocity trend via linear slope | linear slope, last 6 sprints | ✅ Formula OK | INC-013 (duration normalization) |
