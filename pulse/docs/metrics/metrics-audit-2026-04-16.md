# PULSE Metrics Audit — 2026-04-16

**Auditor:** pulse-data-scientist  
**Scope:** All indicators displayed on the PULSE dashboard  
**Data context:** 27 squads, 283 repos, 69 Jira projects, 373k issues, 63k PRs, 1,396 deployments, Jenkins live since 2026-03-30

---

## Methodology

All formulas were verified against the 2023 DORA State of DevOps Report and established Lean/Kanban literature. Each indicator section follows a fixed structure: canonical definition, PULSE implementation, data sources, temporal window, edge case handling (present and absent), adaptations/shortcuts, classification thresholds, and anti-surveillance status. SQL evidence is in `metrics-evidence-2026-04-16.md`.

---

## 1. Deployment Frequency (DF)

### 1.1 Definicao canonica (DORA 2023)
```
DF = count(deployments_in_period) / period_days
```
Unit: deployments per calendar day. All deployments count toward frequency regardless of success/failure status — a failed deploy is still a deploy event. Classification is on the per-day rate.

### 1.2 Implementacao no PULSE
**File:** `pulse/packages/pulse-data/src/contexts/metrics/domain/dora.py`, lines 107-150  
**Function:** `calculate_deployment_frequency`

```python
period_days = (end_date - start_date).total_seconds() / 86_400
count = sum(1 for d in deployments if start_date <= d.deployed_at <= end_date)
per_day = count / period_days
per_week = per_day * 7
```

### 1.3 Fonte dos dados
- **Table:** `eng_deployments`
- **Fields used:** `deployed_at`, `is_failure` (not filtered — all deployments counted, conforming to DORA)
- **Worker fetch:** `_fetch_deployments` filters by `EngDeployment.deployed_at >= start AND <= end` (correct anchor)
- **No environment filter applied** — all environments (production + staging + dev) are counted together

### 1.4 Janela temporal
The metrics worker pre-computes snapshots for periods `[7d, 14d, 30d, 90d]`. The API accepts `{7d, 14d, 30d, 60d, 90d, 120d}`. When the API requests `60d` or `120d`, it falls back to the most recent snapshot via `_get_latest_snapshot` — which is the 90d snapshot. The number returned for `60d` is the 90d calculation, not a 60d calculation.

### 1.5 Edge cases tratados
- `start_date > end_date` returns `(None, None)` — safe
- `period_days <= 0` returns `(None, None)` — safe
- `count == 0` returns `(None, None)` — safe

### 1.6 Edge cases NAO tratados
- **No production environment filter:** staging and dev deploys inflate DF. If a team deploys to dev 10x/day but production 1x/week, DF reads "elite" but engineering reality is "high."
- **60d and 120d periods return stale 90d snapshot** (see section 1.4 above).
- No deduplication of the same commit deploying to multiple environments.

### 1.7 Atalhos e adaptacoes identificadas
- **CRITICAL ADAPTATION:** The normalizer sets `environment = "production"` for any unrecognized environment string (normalizer.py line 407-409). This means unknown environments silently become production, potentially overstating production deployment counts.
- `deployed_at` falls back to `started_date or datetime.now()` when `finished_date` is absent (normalizer.py line 405). For jobs that never finish (ABORTED), this assigns `now()` as the deploy timestamp — incorrect.

### 1.8 Classificacao (thresholds)
| Level   | Condition         | DORA 2023 Official |
|---------|-------------------|-------------------|
| Elite   | >= 1.0/day        | >= 1/day          |
| High    | >= 1/7/day (~0.143) | 1/week to 1/day |
| Medium  | >= 1/30/day (~0.033) | 1/month to 1/week |
| Low     | < 1/30/day        | < 1/month         |

Thresholds match DORA 2023 exactly.

### 1.9 Anti-surveillance check
PASSED. No per-author breakdown. Only aggregate counts.

---

## 2. Lead Time for Changes (LT)

### 2.1 Definicao canonica (DORA 2023)
```
LT = median(deployed_at - first_commit_at)
```
Measured in hours. Uses deployed_at as the endpoint; merge_at is an accepted proxy when deploy timestamp is unavailable. Applies only to PRs that reached production.

### 2.2 Implementacao no PULSE
**File:** `dora.py`, lines 153-188  
**Function:** `calculate_lead_time`

```python
endpoint = pr.deployed_at if pr.deployed_at is not None else pr.merged_at
delta_hours = (endpoint - pr.first_commit_at).total_seconds() / 3_600
# Returns statistics.median(lead_times)
```

### 2.3 Fonte dos dados
- **Table:** `eng_pull_requests`
- **Fields:** `first_commit_at`, `deployed_at`, `merged_at`
- **CRITICAL:** The normalizer maps `first_commit_at = created_date` — the PR creation date, NOT the date of the first commit in the branch. For GitHub PRs, the first commit may predate the PR opening by hours or days.

### 2.4 Janela temporal
Same worker/API period mismatch as DF: worker only computes 7d, 14d, 30d, 90d snapshots. API accepts 60d and 120d but returns the 90d snapshot for those.

Additionally, PRs are fetched by `created_at >= period_start` (worker line 444). A PR created 35 days ago and merged 5 days ago would be EXCLUDED from a 30d snapshot even though it completed within the 30d window.

### 2.5 Edge cases tratados
- `first_commit_at is None` — PR excluded from calculation
- Both `deployed_at` and `merged_at` are None — PR excluded
- `delta_hours < 0` — PR excluded (negative timestamps handled)

### 2.6 Edge cases NAO tratados
- `first_commit_at` is actually `created_date` (PR open date), not the true first commit — this systematically understates lead time by the time the developer worked on the branch before opening the PR
- `deployed_at` is almost always `None` (78% of cases, since PR-to-deploy linking requires the Jenkins→PR match which depends on the 22% link rate) — so the fallback to `merged_at` is the actual formula used for ~78% of PRs
- PRs filtered by `created_at` miss long-lived PRs that completed within the period

### 2.7 Atalhos e adaptacoes identificadas
- **P0 ADAPTATION:** `first_commit_at = PR_created_date`. This is a documented proxy (normalizer.py line 282 comment: "Use created_date as proxy for first commit") but it means the formula is measuring `merged_at - pr_opened_at`, not `deployed_at - first_commit_at`. The canonical formula cannot be satisfied without actual commit data from the repository.
- **P1 ADAPTATION:** `deployed_at` is None for ~78% of PRs, so the formula degrades to `merged_at - pr_opened_at` for most records. This is a valid DORA-accepted fallback but should be explicitly surfaced to users.
- The `deployed_at` column on `eng_pull_requests` is set to `None` at normalization time (normalizer.py line 286: `"deployed_at": None`). No code path currently populates it from deployment data.

### 2.8 Classificacao (thresholds)
| Level   | Condition   | DORA 2023 Official |
|---------|-------------|-------------------|
| Elite   | < 1h        | < 1h              |
| High    | 1h to 168h  | 1h to 1 week      |
| Medium  | 168h to 720h | 1 week to 1 month |
| Low     | >= 720h     | >= 1 month        |

Thresholds match DORA 2023 exactly.

### 2.9 Anti-surveillance check
PASSED. Median over team PRs, no per-author exposure.

---

## 3. Change Failure Rate (CFR)

### 3.1 Definicao canonica (DORA 2023)
```
CFR = count(failed_deployments) / count(all_deployments)
```
Range: 0.0 to 1.0 (displayed as percentage). A "failed" deployment is one that causes a service degradation or requires a hotfix/rollback.

### 3.2 Implementacao no PULSE
**File:** `dora.py`, lines 191-211  
**Function:** `calculate_change_failure_rate`

```python
total = len(deployments)
failures = sum(1 for d in deployments if d.is_failure)
return failures / total
```

### 3.3 Fonte dos dados
- **Table:** `eng_deployments`
- **Field:** `is_failure` (Boolean)
- `is_failure` is set in normalizer.py based on Jenkins result: `result in ("FAILURE", "FAILED", "ERROR", "UNSTABLE")`
- UNSTABLE is treated as failure (builds where tests fail but compilation succeeds)

### 3.4 Janela temporal
Same period mismatch (60d/120d API requests return 90d snapshot).

### 3.5 Edge cases tratados
- Empty deployments list returns `None` — safe
- Division by zero guarded by `if not deployments` check

### 3.6 Edge cases NAO tratados
- **No environment filter:** UNSTABLE staging builds inflate CFR. A team with 50 staging test failures and 10 production failures would show CFR = 60/total instead of 10/total.
- **ABORTED builds:** Not flagged as failures (result not in the is_failure set). An ABORTED Jenkins build is ambiguous — could be cancelled by engineer or an infrastructure timeout. Currently silently counted as success.
- `recovery_time_hours` is set to `None` permanently in the normalizer (line 438). There is no code path that calculates or populates it afterward in the metrics worker. This means MTTR is always `None` in practice (see section 4).

### 3.7 Atalhos e adaptacoes identificadas
- **P1 ADAPTATION:** UNSTABLE (test failures) equated to deployment failures. This is a defensible choice for rigor, but it inflates CFR compared to teams using only production incidents. Should be a configuration parameter.
- **P2:** The frontend multiplies CFR by 100 for display (`cfrItem.value = safeNumber(d.change_failure_rate.value) * 100`). This is correct — the backend stores 0.0-1.0 ratio, frontend converts to percentage. No error here, but the conversion happens on the frontend only; the DORA endpoint returns the raw ratio, which could confuse direct API consumers.

### 3.8 Classificacao (thresholds)
| Level   | Condition  | DORA 2023 Official |
|---------|------------|-------------------|
| Elite   | < 5%       | < 5%              |
| High    | 5% to 10%  | 5% to 10%         |
| Medium  | 10% to 15% | 10% to 15%        |
| Low     | > 15%      | > 15%             |

Thresholds match DORA 2023 exactly. Note the 2023 report updated CFR thresholds (prior version had wider ranges) — the implementation uses the current 2023 values.

### 3.9 Anti-surveillance check
PASSED. Only aggregate failure counts.

---

## 4. Mean Time to Restore (MTTR)

### 4.1 Definicao canonica (DORA 2023)
```
MTTR = median(recovery_time_hours) WHERE is_failure = TRUE AND recovery_time_hours IS NOT NULL
```

### 4.2 Implementacao no PULSE
**File:** `dora.py`, lines 214-242  
**Function:** `calculate_mttr`

The formula is correct. However:

**File:** `normalizer.py`, line 438
```python
"recovery_time_hours": None,  # Calculated by metrics worker
```

**File:** `metrics_worker.py`, line 338
```python
recovery_time_hours=d.recovery_time_hours,  # passed through from DB
```

There is **no code anywhere that calculates or populates `recovery_time_hours`**. The normalizer sets it to `None`, and the worker passes through whatever is in the DB — which is `None`. The MTTR formula in `dora.py` will always receive an empty `recovery_times` list and return `None`.

### 4.3 Fonte dos dados
- `eng_deployments.recovery_time_hours` — always `None` in current system

### 4.4 Janela temporal
N/A — metric always returns `None`.

### 4.5 Edge cases tratados
- Empty list returns `None` — correct behavior given data absence

### 4.6 Edge cases NAO tratados
- **P0:** Recovery time is never populated. The MTTR calculation exists as correct code but has no data to operate on.
- The incident ingestion pipeline required for MTTR (FDD-DSH-050) has not been built.

### 4.7 Atalhos e adaptacoes identificadas
- **P0 ACKNOWLEDGED:** The home endpoint explicitly returns `time_to_restore=HomeMetricCard(unit="hours")` with no value (routes.py line 698-699). The frontend renders "—" with a tooltip. This is a deliberate, documented decision — not an accidental gap. FDD-DSH-050 in backlog.
- **The DORA `/dora` endpoint returns `mean_time_to_recovery_hours: null` and `mttr_level: null`**, which means the overall DORA level is computed from only 3 metrics (DF, LT, CFR), not all 4.

### 4.8 Classificacao (thresholds)
Code is correct (matches DORA 2023). Not reachable with current data.

### 4.9 Anti-surveillance check
PASSED (not computed at all currently).

---

## 5. Cycle Time P50, P85, P95

### 5.1 Definicao canonica
Cycle Time = time from first commit to merge (or deploy). P50/P85/P95 are percentiles of the distribution across all PRs in the period. P50 is the median, P85 and P95 identify the tail.

### 5.2 Implementacao no PULSE
**File:** `cycle_time.py`, lines 199-275  
**Function:** `calculate_cycle_time_breakdown`

Uses linear interpolation percentile (not nearest-rank). Per-phase aggregation is independent — phases have different sample sizes.

```python
def _percentile(sorted_values, p):
    rank = (p / 100.0) * (n - 1)
    lower = int(rank)
    upper = lower + 1
    return sorted_values[lower] + (rank - lower) * (sorted_values[upper] - sorted_values[lower])
```

This is a standard method (similar to numpy's linear interpolation). Correct.

### 5.3 Fonte dos dados
- **Table:** `eng_pull_requests`
- **Fields:** `first_commit_at`, `first_review_at`, `approved_at`, `merged_at`, `deployed_at`
- **CRITICAL:** `first_commit_at` = PR creation date (see section 2.7)
- **Deploy phase:** `deploy_hours = merged_at → deployed_at`. Since `deployed_at` is always `None` (section 2.7), the Deploy phase will always be `None` for every PR.

### 5.4 Janela temporal
Worker period mismatch (60d/120d returns 90d snapshot). Additionally PRs fetched by `created_at`, not `merged_at`.

### 5.5 Edge cases tratados
- Empty PR list returns all-None breakdown struct — safe
- Missing timestamps excluded from that phase's percentile (correct)
- Per-phase sample sizes differ from total — correctly documented in code

### 5.6 Edge cases NAO tratados
- **Deploy phase always None** because `deployed_at` is never populated
- If `first_review_at` is None (GitHub PRs without review events), the Coding, Pickup, and Review phases all return None, but total can still be computed
- No negative delta guard on the aggregated breakdown (relies on `_delta_hours` returning `None` for negatives, which it does correctly)

### 5.7 Atalhos e adaptacoes identificadas
- **P0:** The `cycle_time_hours` column property in `models.py` (line 68-76) computes `first_commit_at → merged_at`. In the throughput worker (metrics_worker.py line 192), `cycle_time_hours=None` is passed to `PullRequestThroughputData` explicitly — the model's computed column is ignored. This means the throughput trend's per-week P50/P85 cycle times are always `None`.
- **P1:** Cycle Time P50/P85 on the home dashboard comes from `cycle_time breakdown total_p50/total_p85`, which uses the PR `created_at` as first_commit proxy, not the true first commit.

### 5.8 Classificacao (thresholds)
Cycle Time classification is done on the **frontend** in `transforms.ts` (lines 171-176), not by the backend:
```typescript
function classifyCycleTime(hours: number): DoraClassification {
  if (hours < 2) return 'elite';
  if (hours < 24) return 'high';
  if (hours < 72) return 'medium';
  return 'low';
}
```
These thresholds are NOT from the DORA 2023 report (which does not define cycle time thresholds). They are PULSE-internal custom thresholds shown alongside DORA benchmarks in the UI (`BENCHMARKS['cycle_time']`). This is acceptable but should be documented as "PULSE-defined" to avoid appearing as official DORA classifications.

### 5.9 Anti-surveillance check
PASSED. Team-level percentiles only.

---

## 6. Cycle Time Breakdown (Coding / Pickup / Review / Deploy)

### 6.1 Definicao canonica
Industry standard (based on LinearB / Jellyfish definitions):
- Coding: first commit → PR opened
- Pickup: PR opened → first review comment/approval
- Review: first approval → merge
- Deploy: merge → production deploy

### 6.2 Implementacao no PULSE
**File:** `cycle_time.py`, lines 8-27 (docstring definitions)

PULSE definition differs from industry standard:
- Coding: `first_commit_at → first_review_at` (uses PR open date as proxy for first commit)
- Pickup: `first_review_at → approved_at`
- Review: `approved_at → merged_at`
- Deploy: `merged_at → deployed_at` (always None — see section 5.7)

### 6.3 Fonte dos dados
Same as section 5.3.

### 6.4 Janela temporal
Same as section 5.4.

### 6.5 Edge cases tratados
- Missing timestamps for a phase: that PR excluded from phase percentile
- Bottleneck computed from phase P50s — if all are None, bottleneck is None

### 6.6 Edge cases NAO tratados
- **Deploy phase is permanently None** — the stacked bar chart will always show only 3 phases (Coding/Pickup/Review)
- `first_commit_at` proxy inflation: Coding phase absorbs all pre-PR work time that happened before the PR was created

### 6.7 Atalhos e adaptacoes identificadas
- **P1:** Deploy phase = 0 data. The breakdown chart is structurally incomplete.
- **P2:** The naming "Pickup" diverges from some tools (GitHub's own analytics calls this "Time to first review"). PULSE's definition is internally consistent and documented in code.

### 6.8 Classificacao
No thresholds for individual phases — bottleneck identification is via max P50. Correct.

### 6.9 Anti-surveillance check
PASSED.

---

## 7. WIP (Work in Progress)

### 7.1 Definicao canonica (Lean/Kanban)
```
WIP = count(items WHERE status IN ('in_progress', 'in_review'))
```
Point-in-time count. No percentiles. Used to detect WIP accumulation and violation of WIP limits.

### 7.2 Implementacao no PULSE
**File:** `lean.py`, lines 259-313  
**Function:** `calculate_wip`

Two modes:
- `as_of=None`: uses current `normalized_status` field directly
- `as_of=datetime`: replays `status_transitions` to find historical status

The `as_of=None` mode is what the dashboard uses (current WIP).

### 7.3 Fonte dos dados
- **Table:** `eng_issues`
- **Field:** `normalized_status` (for current WIP)
- WIP limit used for color coding is hardcoded in the frontend: `wipLimit: 10` (transforms.ts line 571)

### 7.4 Janela temporal
WIP is a point-in-time count, not period-dependent. However, it is stored in snapshots keyed to the computation period. The home dashboard uses the latest `lean/wip` snapshot regardless of the period requested.

### 7.5 Edge cases tratados
- `as_of` mode: issues created after `as_of` skipped correctly
- No status transitions: falls back to current status (acceptable approximation)

### 7.6 Edge cases NAO tratados
- **WIP limit is hardcoded to 10 in the frontend** — this is not configurable per team or per project. For Webmotors' 27 squads with different sizes, a single WIP limit of 10 is meaningless.
- Issues with status mapped to `in_progress` via the normalizer — some statuses like "aguardando code review" map to `in_review` (normalizer line 70), which correctly enters WIP. Others like "aguardando deploy produção" map to `done` (line 77), which is debatable (the item is waiting, not done).
- **Issues scope:** WIP counts ALL issues in `eng_issues` (no team filter in the current worker query). This is a cross-squad WIP count, not per-team.

### 7.7 Atalhos e adaptacoes identificadas
- **P1:** WIP limit hardcoded at 10 in frontend — not a real business WIP limit.
- **P2:** "aguardando deploy produção" mapped to "done" — arguable; some teams consider this still in-flight.

### 7.8 Classificacao (frontend-defined)
```typescript
if (count <= 3) return 'elite';
if (count <= 6) return 'high';
if (count <= 10) return 'medium';
return 'low';
```
These are PULSE-internal thresholds, not DORA-defined. They apply to cross-squad aggregate WIP which makes the thresholds poorly calibrated (27 squads with 10 items each = 270 WIP aggregate → always "low").

### 7.9 Anti-surveillance check
PASSED. Count only, no issue-level attribution.

---

## 8. Throughput

### 8.1 Definicao canonica
Two separate throughput metrics exist:
1. **Issue throughput (Lean):** `count(issues completed_at IN period)` per week
2. **PR throughput:** `count(PRs merged_at IN period)` per week

The home dashboard "Throughput" card shows **PR count** from `pr_analytics.total_merged` (routes.py line 608).

### 8.2 Implementacao no PULSE
**Lean throughput:** `lean.py` lines 425-487 (`calculate_throughput`) — counts by `completed_at` per week with 4-week moving average  
**PR throughput:** `throughput.py` lines 129-199 (`calculate_throughput_trend`) — counts by `merged_at` per week

Home card uses `pr_analytics.total_merged` — the total count of PRs in the period, not per week.

### 8.3 Fonte dos dados
- Lean: `eng_issues.completed_at`
- PR: `eng_pull_requests.merged_at`
- Home card value = total PRs merged in snapshot period

### 8.4 Janela temporal
- PR fetch uses `created_at` filter (worker line 444) — PRs created outside the period but merged within it are EXCLUDED.
- Lean issue fetch uses `created_at` filter (worker line 462) — same exclusion problem.
- Period mismatch: worker only computes 7d/14d/30d/90d.

### 8.5 Edge cases tratados
- Zero-count weeks included (correct for trend visualization)
- 4-week moving average only starts from index 3 (correct — first 3 weeks have fewer than 4 data points)
- Empty PR list returns empty period list

### 8.6 Edge cases NAO tratados
- **PR fetch by `created_at` misses long-cycle PRs**: A PR opened 45 days ago and merged 2 days ago would not appear in the 30d snapshot throughput, undercounting completed work.
- The 4-week moving average uses `None` for the first 3 points rather than a partial average — this is documented behavior, but the first 3 weeks of a trend will have no moving average line.

### 8.7 Atalhos e adaptacoes identificadas
- **P0:** PRs and issues are queried by `created_at` (creation time), not by completion time. Throughput should be measured by when work was COMPLETED (merged/done), not when it was STARTED. This is the most significant systemic data-window error in the platform.
- **P1:** Home card throughput = total PRs merged (a count), not a rate. The label "PRs merged" is clear, but the classification `classifyThroughput` converts it to per-week rate for the badge. This is correct but the raw value displayed and the classified level use different denominators.

### 8.8 Classificacao (frontend-defined)
```typescript
const perWeek = (total / Math.max(periodDays, 1)) * 7;
if (perWeek >= 50) return 'elite';
if (perWeek >= 20) return 'high';
if (perWeek >= 5) return 'medium';
return 'low';
```
Not from DORA (DORA does not define throughput thresholds). PULSE-internal. Reasonable.

### 8.9 Little's Law validation
See section in evidence document. Short version: `avg_wip / avg_lead_time_days ≠ throughput_per_day` when periods are inconsistent.

### 8.10 Anti-surveillance check
PASSED. Aggregate counts only. The `author` field in `PullRequestThroughputData` is used only for repo-level breakdown, not per-author ranking.

---

## 9. CFD (Cumulative Flow Diagram)

### 9.1 Definicao canonica
Daily counts of issues per status band, cumulative (done count is monotonically non-decreasing). Parallel band widths = stable flow; widening = WIP accumulation.

### 9.2 Implementacao no PULSE
**File:** `lean.py`, lines 136-251  
**Function:** `calculate_cfd`

For each calendar day D:
1. For each issue, find the last `status_transition.entered_at <= end_of_day(D)`
2. Increment the band counter for that status
3. Fallback: if no transitions, use `created_at` as initial "todo" entry

The implementation produces a snapshot-based CFD (counts issues in each status per day), not a strictly cumulative flow. The `done` band CAN decrease if issues transition back out of done — which is semantically wrong for a CFD. A true CFD should use the maximum historical done count. However in practice, issues rarely regress out of done in Jira.

### 9.3 Fonte dos dados
- **Table:** `eng_issues`
- **Field:** `status_transitions` (JSONB), `normalized_status`, `created_at`

### 9.4 Janela temporal
- Issues fetched by `created_at >= period_start`
- Issues created before the period that are still active (in_progress) would be EXCLUDED from the CFD — this understates WIP for long-running items

### 9.5 Edge cases tratados
- Empty issues or start > end: returns empty list
- Issues with no transition data: falls back to `created_at` as "todo" entry
- Issues with transitions containing null `entered_at`: skipped safely

### 9.6 Edge cases NAO tratados
- **CFD not strictly cumulative for `done` band** — can decrease if issues regress
- **Issues pre-dating the period missing** — CFD starts from zero even if there was existing WIP before the window
- **Mixed timezone handling:** The CFD builds EOD timestamp with `tzinfo=timezone.utc` (lean.py line 206), but `issue.created_at` may be naive (if stored without timezone from the normalizer). A naive datetime > an aware datetime raises a TypeError. This is a latent crash bug.

### 9.7 Atalhos e adaptacoes identificadas
- **P1:** CFD not strictly cumulative (done band can decrease). For most use cases this is acceptable, but it's technically incorrect.
- **P1:** Mixed timezone naive/aware comparison is a latent crash. See section 9.6.

### 9.8 Anti-surveillance check
PASSED. Status counts per band, no attribution.

---

## 10. Lead Time Distribution

### 10.1 Definicao canonica (Lean)
Histogram of `lead_time = completed_at - created_at` for all completed issues in the period. P50/P85/P95 percentile markers overlaid. The distribution reveals whether flow is consistent or has a long tail.

### 10.2 Implementacao no PULSE
**File:** `lean.py`, lines 337-412  
**Function:** `calculate_lead_time_distribution`

Histogram buckets:
```
0-4h | 4-8h | 8-24h | 1-2d | 2-5d | 5-10d | 10-20d | 20-30d | 30d+
```

Note: The PULSE system prompt specifies bins as `0-2d, 3-5d, 6-10d, 11-15d, 16-20d, 21-30d, 30d+` (daily resolution). The actual implementation uses a different bucketing scheme (0-4h, 4-8h, etc.) with finer granularity at the short end. This is a **better** choice for software teams but differs from the spec.

### 10.3 Fonte dos dados
- **Table:** `eng_issues`
- **Field:** `lead_time_hours` (computed column: `completed_at - created_at`)
- Only issues with `completed_at IS NOT NULL` and `lead_time_hours >= 0` contribute

### 10.4 Janela temporal
- Issues fetched by `created_at` — an issue created outside the window but completed inside it is excluded. **This means the distribution reflects issues that were CREATED in the period, not issues that COMPLETED in the period.** For a 30d view, we see the lead time of issues that started and ended within 30 days — systematically excluding long-cycle items.

### 10.5 Edge cases tratados
- No completed issues: returns all-zero buckets and None percentiles
- Lead time < 0: excluded (data quality guard)

### 10.6 Edge cases NAO tratados
- **Sample bias** from created_at filter (see 10.4)
- Histogram bins have a gap: `XS (1-10)` in PR size uses `<=` on upper bound (lines 266-267: `elif lo <= size <= hi`), which means size=10 falls in XS and size=11 in S. For the lead time histogram the logic uses `lo <= lt < hi` (line 386-387) — exclusive upper bound. These two adjacent data structures use different boundary conventions.

### 10.7 Atalhos e adaptacoes identificadas
- **P1:** Histogram applies to `created_at`-filtered issues, not `completed_at`-filtered issues. Long-cycle items are systematically excluded.
- **P2:** Bucket scheme differs from spec but is empirically better.

### 10.8 Anti-surveillance check
PASSED.

---

## 11. Lead Time Scatterplot

### 11.1 Definicao canonica
Each completed issue plotted as (completion_date, lead_time). Horizontal P50/P85/P95 lines. Outliers (> P95) highlighted in danger color. Reveals flow predictability and cluster vs. long-tail patterns.

### 11.2 Implementacao no PULSE
**File:** `lean.py`, lines 495-542  
**Function:** `calculate_lead_time_scatterplot`

- Outlier: `lead_time_hours > p95` (strict greater-than, correct)
- Points sorted by `completed_date` ascending
- P95 computed from the same sample — so exactly 5% of points are flagged as outliers by construction (percentile definition)

### 11.3 Fonte dos dados
- `eng_issues.completed_at`, `lead_time_hours`
- Same created_at filter bias as other lean metrics

### 11.4 Edge cases tratados
- No completed issues: returns ([], None, None, None) — safe
- Exactly 1 completed issue: percentile returns that single value, no outliers flagged

### 11.5 Edge cases NAO tratados
- The `issue_id` is included in scatterplot points — this does NOT expose individual developer data, but it does expose issue identifiers which could be cross-referenced outside PULSE to attribute work. Acceptable at issue level (not developer level) but worth reviewing if issues are connected to specific assignees in the UI.

### 11.6 Atalhos e adaptacoes identificadas
None significant. This metric is cleanly implemented.

### 11.7 Anti-surveillance check
PASSED (issue-level, not developer-level). `issue_id` in scatterpoint is acceptable — it is not developer identity.

---

## 12. Sprint Overview

### 12.1 Definicao canonica
- Committed: items in sprint at start date
- Added: items added after sprint started (scope creep)
- Completed: items in done state by end date
- Completion Rate = completed / (committed + added - removed)
- Scope Creep % = (added / committed) × 100
- Carryover Rate = carried_over / committed

### 12.2 Implementacao no PULSE
**File:** `sprint.py`, lines 124-172  
**Function:** `calculate_sprint_overview`

```python
final_scope = max(committed + added - removed, 0)
completion_rate = min(completed / final_scope, 1.0)  # capped at 100%
scope_creep_pct = (added / committed) * 100
carryover_rate = carried_over / committed
completion_rate_points = min(completed_points / committed_points, 1.0)
```

### 12.3 Fonte dos dados
- **Table:** `eng_sprints`
- **Fields:** `committed_items`, `committed_points`, `added_items`, `removed_items`, `completed_items`, `completed_points`, `carried_over_items`
- **CRITICAL:** The normalizer (`normalize_sprint`, line 444-503) sets `added_items = 0` and `removed_items = 0` (lines 498-499). There is NO code path that tracks mid-sprint scope changes.

### 12.4 Janela temporal
Sprints fetched without period filter — the most recent 20 sprints regardless of the API period parameter.

### 12.5 Edge cases tratados
- `committed_items == 0`: scope_creep_pct and carryover_rate return None
- `final_scope <= 0`: completion_rate returns None
- `committed_points == 0`: completion_rate_points returns None
- Completion rate capped at 1.0 (no over-completion)

### 12.6 Edge cases NAO tratados
- **added_items and removed_items are always 0**: scope_creep_pct is always 0, which is factually wrong. Every sprint has some scope change.
- `carried_over_items` is computed in the normalizer as `committed - completed` only if the sprint has ended. For active sprints, `carried_over_items = 0`, making carryover_rate always 0 for the current sprint.

### 12.7 Atalhos e adaptacoes identificadas
- **P0:** `added_items = 0` and `removed_items = 0` always. Scope creep (a key business metric for sprint health) is always reported as 0%. This is structurally wrong.
- **P1:** `carried_over_items` computed from `committed - completed` at normalization time without real-time tracking. Items that were added mid-sprint and then removed are invisible.

### 12.8 Classificacao
No formal thresholds for sprint metrics — completion rate is displayed as a percentage. Velocity trend uses linear slope with 5% of mean as the threshold for "improving" vs "stable" vs "declining." This is a reasonable heuristic.

### 12.9 Anti-surveillance check
PASSED. No per-developer attribution.

---

## 13. Sprint Comparison

### 13.1 Definicao canonica
Velocity trend across the last N sprints. Velocity = story points completed per sprint. Trend determined by linear regression slope.

### 13.2 Implementacao no PULSE
**File:** `sprint.py`, lines 180-266  
**Function:** `calculate_sprint_comparison`, `_velocity_trend`

Linear regression slope over the last 6 sprints. Threshold: slope > 5% of mean velocity = "improving," slope < -5% = "declining."

The slope computation uses index as x-variable (0, 1, 2...) which is correct for evenly-spaced observations. Sprint durations vary in practice, so equal spacing is an approximation.

### 13.3 Edge cases tratados
- Fewer than 2 sprints: "insufficient_data"
- All same velocity: slope=0 → "stable"
- Mean velocity = 0: slope comparison bypassed → "stable"

### 13.4 Edge cases NAO tratados
- Sprints of different durations (1-week vs 2-week) are treated as equally spaced
- The 5% threshold is hardcoded — not configurable per team

### 13.5 Atalhos e adaptacoes identificadas
- **P1:** Sprint duration not normalized. A team switching from 2-week to 1-week sprints would appear to have "declining" velocity even if their per-day output is constant.

### 13.6 Anti-surveillance check
PASSED.

---

## Cross-cutting Issues

### Period Mismatch (P0)
The Metrics Worker computes snapshots for `[7d, 14d, 30d, 90d]`. The API `_VALID_PERIODS = {"7d", "14d", "30d", "60d", "90d", "120d"}`. Requests for `60d` and `120d` fall back to the most recent snapshot, which is the 90d calculation. The period displayed to the user is "60 days" but the data is "last 90 days." This is silently wrong.

### PR/Issue fetch window (P0)
All data fetchers in the metrics worker query by `created_at` (when the item was opened/created), not by `merged_at` (completion). This means:
- Long-cycle PRs created before the window are excluded even if they merged within it
- Short-cycle PRs that opened and closed within the window are included correctly
- The bias increases for longer periods and longer-cycle teams

### No team-level segmentation in snapshots (P1)
The worker writes all snapshots with `team_id=None`. The API supports `team_id` filtering but will always get the same tenant-wide snapshot. Per-team metrics are not computed.

### `deployed_at` never populated on PRs (P0)
`eng_pull_requests.deployed_at` is set to `None` at normalization and no code path populates it afterward. This means:
- Lead Time for Changes uses `merged_at` as endpoint for all PRs (not deployed_at)
- Cycle Time Deploy phase is always None
- PR-to-deployment linking (the feature that would populate `deployed_at`) is not implemented despite the infrastructure being in place

---

*End of audit document. See metrics-inconsistencies.md for severity-ranked list and metrics-evidence-2026-04-16.md for SQL ground truth.*
