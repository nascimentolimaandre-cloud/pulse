# PULSE Data Platform Backlog

## Pipeline Monitor v2

### 1. Step-level instrumentation
Sync worker should emit `{entity_type, step_name, processed, total, duration_sec, status}` events per batch to a `pipeline_step_progress` table. The frontend already renders 4 steps (fetch / changelog / normalize / upsert) when present. Currently the API synthesizes 2 aggregated steps from `pipeline_ingestion_progress` fields as a placeholder.

**Priority:** High
**Depends on:** Sync worker refactor to emit granular progress events.

### 2. Rate limit tracking
Currently hardcoded placeholder values per source. Source connectors need to report remaining/limit from API response headers:
- **GitHub:** `X-RateLimit-Remaining` / `X-RateLimit-Limit` headers
- **Jira:** 429 backoff tracking (Jira Cloud does not expose explicit rate-limit headers)
- **Jenkins:** Internal concurrency counter (no standard rate-limit header)

Store in a `source_rate_limits` table or Redis cache; Pipeline Monitor reads from there.

**Priority:** Medium

### 3. Retry button E2E
- RBAC role required: `data_platform`
- POST `/data/v1/pipeline/entities/{sourceId}/{entityType}/retry` endpoint (currently returns 501)
- Sync worker should consume retry requests from a queue (Redis or Kafka topic)
- Frontend button is already hidden behind a feature flag

**Priority:** Low (requires RBAC + sync worker queue consumer)

### 4. PR link rate per team -- denominator refinement
Current approximation: `pr_reference_count / total_repo_prs` may overcount when a repo serves multiple squads. Formal definition should be:

> (PRs mentioning KEY in title AND `linked_issue_ids` contains a matching issue_id) / (PRs mentioning KEY in title)

This requires joining `eng_pull_requests` with `eng_issues` on issue_key extraction, which is expensive at scale. Consider a materialized view or pre-calculated field on the catalog.

**Priority:** Medium (accuracy improvement, no user-facing change)

### 5. Populate `jira_project_catalog.issue_count`
Currently all 69 rows have `issue_count = 0`. The Pipeline Monitor `/teams` endpoint exposes this as the per-squad "ISSUES" column, so it always shows 0. Fix: update the Jira sync worker to refresh `issue_count` (e.g. `UPDATE jira_project_catalog SET issue_count = (SELECT count(*) FROM eng_issues WHERE project_key = jpc.project_key)`) after each full or incremental sync. Also consider refreshing `pr_reference_count` the same way to unblock alternative queries.

**Priority:** Medium

### 6. Pipeline events feed
`pipeline_events` table is empty — sync worker and metrics worker don't emit events yet. The `/timeline` endpoint works but returns `[]`. Fix: emit events on:
- Successful sync cycle completion (`success`, per source, with records/duration)
- Errors (existing `recent_errors` plumbing can be forwarded to events)
- Rate-limit warnings
- Backfill start/end

**Priority:** High (core observability; Pipeline Monitor Timeline tab is inert without this)

