# PULSE Data Ingestion Specification

## SDD — Spec-Driven Development Document

**Version:** 1.0  
**Date:** 2026-04-14  
**Status:** Living Document  
**Audience:** Engineering, Product, Future AI Ingestion Agent  

---

## 1. Executive Summary

This document captures every adjustment, problem, and solution encountered during PULSE's data ingestion buildout — from initial DevLake-based pipeline to current proprietary connectors with dynamic discovery. It serves as the **single source of truth** for understanding ingestion behavior and as the **specification baseline** for building a fully autonomous SaaS ingestion engine.

### Current State (2026-04-14)

| Metric | Value |
|--------|-------|
| Jira projects active | 69 |
| Issues ingested | 373,872 |
| PRs ingested | 63,647 |
| PR-Issue link rate | 21.9% (13,966 PRs) |
| Deployments (Jenkins) | 83 |
| Sprints | 215 |
| GitHub repos discovered | 754 (active), 1,429 (total) |
| Ingestion cycle time | ~3h (full backfill), ~7min (incremental) |

---

## 2. Data Source Context

### 2.1 Source Systems

| Source | System | Auth | API | Volume |
|--------|--------|------|-----|--------|
| **Git** | GitHub Enterprise (cloud) | PAT (GraphQL + REST) | GraphQL v4 primary, REST v3 fallback | 1,429 repos, 63K+ PRs |
| **Issues** | Jira Cloud | Basic Auth (email + API token) | REST API v3 + Agile API v1 | 69 projects, 373K+ issues |
| **CI/CD** | Jenkins On-Premise | Basic Auth (username + API token) | JSON API `/api/json` | ~1,400 jobs, 83 deployments mapped |

### 2.2 Environment Characteristics (Webmotors)

| Characteristic | Detail | Impact on Ingestion |
|---------------|--------|-------------------|
| Org size | ~750 active repos, 69 Jira projects | High volume, need batch processing |
| Jira project scale | 197K issues in single project (BG) | Single JQL query can return massive payloads |
| Custom fields | Sprint = `customfield_10007`, Story Points = `customfield_18524` | Must discover dynamically per tenant |
| Jenkins patterns | No corporate standard; each repo has unique pipeline config | Cannot use single regex for deployment detection |
| Language mix | Portuguese status names ("Em Desenvolvimento", "Concluido") | Status normalizer needs i18n mapping |
| Jira reserved words | Project key "DESC" is SQL reserved word | Must quote project keys in JQL |
| Archived projects | Some keys referenced in PRs (e.g., "RC") don't exist in Jira API | Graceful handling of orphan references |

---

## 3. Ingestion Architecture

### 3.1 Pipeline Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌───────────┐
│   Sources    │────>│  Connectors  │────>│ Normalizer  │────>│  PULSE DB │
│ GitHub/Jira/ │     │ (fetch +     │     │ (transform) │     │ (upsert)  │
│ Jenkins      │     │  paginate)   │     │             │     │           │
└─────────────┘     └──────────────┘     └─────────────┘     └─────┬─────┘
                                                                    │
                                                              ┌─────▼─────┐
                                                              │   Kafka   │
                                                              │ (events)  │
                                                              └───────────┘
```

### 3.2 Sync Orchestration

```python
# devlake_sync.py — DataSyncWorker.sync()
async def sync(self):
    1. _sync_issues()       # Jira → normalize → upsert → Kafka
    2. _sync_pull_requests() # GitHub → normalize → link to issues → upsert → Kafka
    3. _sync_deployments()   # Jenkins → normalize → upsert → Kafka
    4. _sync_sprints()       # Jira Agile → normalize → upsert → Kafka
```

**Ordering matters:** Issues must sync before PRs so the `issue_key_map` is populated for PR-Issue linking.

### 3.3 Key Design Decisions

| Decision | Rationale | ADR |
|----------|-----------|-----|
| Replaced DevLake with proprietary connectors | 99.3% issue data loss in DevLake PostgreSQL layer | ADR-005 |
| GraphQL primary for GitHub, REST fallback | 40x faster PR fetch (50 PRs + reviews + stats in 1 call) | Commit `60fe576` |
| Per-repo batch upsert (not all-at-end) | Memory efficiency + real-time progress visibility | Commit `7f9f339` |
| Global watermark per entity (not per-project) | Simpler model, but requires reset for project scope expansion | Migration 002 |
| JSONB for `linked_issue_ids` and `status_transitions` | Flexible schema, supports variable-length arrays | Migration 001 |
| Row-Level Security on all tables | Multi-tenant isolation at DB level | Migration 001 |
| Kafka event backbone | Decouples ingestion from metric calculation | ADR-004 |

---

## 4. Problems, Solutions, and Results

### Problem 1: DevLake Data Loss (99.3% Issues Lost)

**Context:** Initial architecture used Apache DevLake as ingestion engine (ADR-003). DevLake collected data from GitHub and Jira into its own PostgreSQL domain tables, and a Sync Worker ETL'd from DevLake to PULSE DB.

**Symptoms:**
- DevLake Tool Layer: 32,621 issues
- DevLake Domain Layer: 243 issues (99.3% loss)
- Root cause: DevLake's PostgreSQL support is "second-class citizen" (designed for MySQL)
- Jira API v2 deprecation (HTTP 410) — only fixed in DevLake beta, no stable release

**Solution:** Full proprietary connector replacement (ADR-005, Option B).
- Built `JiraConnector`, `GitHubConnector`, `JenkinsConnector` implementing `BaseConnector` interface
- Reused 100% of `normalizer.py` (539 lines), 80% of sync orchestration
- Added 321 unit tests for new connectors

**Result:**
- Issues: 243 -> 373,872 (1,538x improvement)
- PRs: 5,314 -> 63,647 (12x, due to full org scan vs 4 repos)
- Zero data loss in ingestion pipeline

**SaaS Implication:** DevLake is eliminated. Custom connectors are the path forward. Each new source (GitLab, Azure DevOps, Linear, etc.) needs a connector implementing `BaseConnector`.

---

### Problem 2: Jira Custom Field Discovery

**Context:** Jira custom field IDs vary per tenant. Sprint field might be `customfield_10007` in one org and `customfield_10020` in another. Story points similarly vary.

**Symptoms:**
- Hardcoded field IDs worked for Webmotors but would break for any other customer
- Sprint data returned empty when wrong field ID was used

**Solution:** Dynamic field discovery via `/rest/api/3/field` endpoint.

```python
# jira_connector.py — _discover_custom_fields()
async def _discover_custom_fields(self):
    """Query Jira field metadata and match by name patterns."""
    fields = await self._get("/rest/api/3/field")
    for field in fields:
        name_lower = field["name"].lower()
        if "sprint" in name_lower and field.get("custom"):
            self._sprint_field_id = field["id"]
        if "story point" in name_lower and field.get("custom"):
            self._story_points_field_id = field["id"]
    # Fallback to common defaults if discovery fails
    FALLBACK_SPRINT_FIELDS = ["customfield_10020", "customfield_10016"]
    FALLBACK_STORY_POINTS_FIELDS = ["customfield_10016", "customfield_10028"]
```

**Result:** Sprint and story points discovered correctly for Webmotors (`customfield_10007` and `customfield_18524`). Fallback chain ensures graceful degradation.

**SaaS Implication:** This is already SaaS-ready. Each tenant's first sync auto-discovers their field IDs. No manual configuration needed.

---

### Problem 3: Jira Project Scope — Static Config vs Dynamic Reality

**Context:** Initial setup required manually listing Jira project keys in `JIRA_PROJECTS` env var. Only 8 projects were configured, but the org had 69+ projects.

**Symptoms:**
- Only 29,389 issues from 8 projects (out of 373K+ total)
- PR-Issue link rate stuck at 5.27% because 60 projects' issues weren't indexed
- New projects or team reorganizations required manual env var updates

**Solution:** Dynamic Jira Project Discovery (ADR-014, 4-phase implementation).

**Phase 1 — Discovery Engine:**
- `ProjectDiscoveryService`: fetches all Jira projects via API, diffs against catalog
- `ModeResolver`: 4 modes (auto, allowlist, blocklist, smart)
- `Guardrails`: project caps, rate limits, auto-pause on failures
- `SmartPrioritizer`: scores projects by PR reference count

**Phase 2 — Admin API + UI:**
- NestJS controller: CRUD for catalog, activate/pause/block actions
- React page: project list with search, sort, bulk actions
- Audit trail: append-only log of all state changes

**Phase 3 — Security Hardening:**
- PII gating: regex detects sensitive project names (HR, legal, finance)
- Rate limiting: per-tenant hourly issue quota
- Set-based allowlists: O(1) lookup instead of array iteration

**Phase 4 — Rollout:**
- Feature flag: `DYNAMIC_JIRA_DISCOVERY_ENABLED` gates sync-worker
- `ModeResolver` queries DB fresh each cycle (no stale cache)
- APScheduler runs discovery on configurable cron

**Result:** 
- 69 projects discovered and activated (9 original + 60 new)
- Full backfill: 373,872 issues ingested in ~3h
- System adapts to new projects without human intervention (in auto/smart mode)

**SaaS Implication:** Core discovery is SaaS-ready. Smart mode + PII gating enables zero-config onboarding. Need to extend pattern to GitHub (org/repo discovery) and Jenkins (job discovery).

---

### Problem 4: PR-Issue Linkage — Low Match Rate

**Context:** PRs reference Jira issues in titles/branches (e.g., "SECOM-1441 fix login flow"), but the linker could only match against issues already in the DB.

**Symptoms:**
- 5.27% link rate (3,351 of 63,516 PRs)
- Regex matched 24.41% of PR titles (15,503 PRs across 68 project keys)
- Gap: 19% of PRs referenced projects whose issues weren't ingested

**Root Cause Analysis:**
1. `build_issue_key_map()` loads `(issue_key, external_id)` from `eng_issues` at sync start
2. Map only contained 8 projects' keys = 29,389 entries
3. PRs referencing SECOM, ESTQ, CKP, OKM, etc. found no match in map

**Solution:** Multi-step approach:
1. Activated all 60 discovered projects (bulk API calls)
2. Reset issues watermark to `2020-01-01` to force full historical backfill
3. Restarted sync-worker (triggers immediate sync cycle)
4. After 373K issues landed, ran `relink_prs_to_issues.sql` to backfill links on existing PRs

**Result:**
- Link rate: 5.27% -> **21.9%** (13,966 PRs linked)
- Per-project rates: SDI/PUSO/DSP/FID/CRMC = **100%**, most projects >96%
- Orphan keys identified: RC (1,348 refs, project not in Jira — possibly archived)

**Remaining Gap Analysis (21.9% vs theoretical 24.4%):**
- False positive regex matches: HOTFIX-123, RELEASE-1, BUGFIX-42, lib names (LODASH-4)
- Orphan project "RC" accounts for 1,348 refs (2.1%)
- Typos in PR titles: ESQT instead of ESTQ, SECON instead of SECOM, PUS0 (zero) instead of PUSO

**SaaS Implication:** Linking works well when issue scope matches PR scope. Key insight: **issue ingestion scope determines link quality**. Smart mode's PR-reference scoring naturally prioritizes projects that matter for linking. Future: fuzzy matching for typos, alias tables for renamed projects.

---

### Problem 5: Global Watermark vs Per-Project Scope

**Context:** `pipeline_watermarks` stores one `last_synced_at` per entity type (issues, pull_requests, etc.), shared across all projects.

**Symptoms:**
- After activating 60 new projects, their historical issues would be skipped
- Watermark at `2026-04-14` meant JQL `updated >= "2026-04-14"` excluded old issues from new projects
- Required manual watermark reset to `2020-01-01` for backfill

**Solution (immediate):** Manual watermark reset + upsert idempotency guarantees safety.

```sql
UPDATE pipeline_watermarks
SET last_synced_at = '2020-01-01 00:00:00+00'
WHERE entity_type = 'issues';
```

**Impact:** Re-fetched 29K existing issues (harmless — upsert ON CONFLICT updates). Added ~3h to cycle for 373K total.

**SaaS Implication:** Global watermark is a **fundamental limitation** for SaaS. When a new project is activated, a full backfill is needed. Options for future:
1. **Per-project watermarks** (most correct, higher storage cost)
2. **Dual-pass sync**: incremental for existing + backfill for newly activated (recommended)
3. **Hybrid**: global watermark + "needs_backfill" flag per project in catalog

---

### Problem 6: Status Normalization — Portuguese and Custom Workflows

**Context:** Jira workflows vary wildly across orgs and even across projects within the same org. Webmotors uses Portuguese status names.

**Symptoms:**
- "Em Desenvolvimento" not mapping to `in_progress`
- "Concluido" (without accent) not mapping to `done`
- Custom statuses like "Aguardando Deploy", "Em Code Review" unrecognized

**Solution:** Extensive DEFAULT_STATUS_MAPPING with 60+ entries covering English, Portuguese, and common custom workflows.

```python
DEFAULT_STATUS_MAPPING = {
    # English
    "open": "todo", "to do": "todo", "backlog": "todo",
    "in progress": "in_progress", "in development": "in_progress",
    "done": "done", "closed": "done", "resolved": "done",
    # Portuguese
    "em desenvolvimento": "in_progress", "em progresso": "in_progress",
    "concluído": "done", "concluido": "done", "finalizado": "done",
    "a fazer": "todo", "pendente": "todo",
    # Custom patterns
    "code review": "in_progress", "em code review": "in_progress",
    "aguardando deploy": "in_progress", "ready for qa": "in_progress",
    "em teste": "in_progress", "testing": "in_progress",
    ...
}
```

**Result:** 99%+ status normalization accuracy for Webmotors workflows.

**SaaS Implication:** Static mapping won't scale. Need:
1. **Learning-based mapper**: observe workflow transitions to infer categories
2. **Per-tenant overrides**: allow admin to map custom statuses
3. **AI fallback**: LLM classifies unknown statuses into todo/in_progress/done

---

### Problem 7: Jenkins — No Standard Pipeline Pattern

**Context:** DORA Deployment Frequency and Change Failure Rate require identifying production deployments. Jenkins has no standard way to mark a build as "production deployment."

**Symptoms:**
- 1,400+ Jenkins jobs, only ~75 map to actual production deployments
- Each team uses different naming patterns: `deploy-prod`, `release-main`, `CD-production`
- Job folder structures vary: `folder/subfolder/job` vs flat jobs

**Solution (partial — in progress):**
- `connections.yaml` supports per-job `deploymentPattern` and `productionPattern` regex
- 17 job mappings manually configured for Webmotors
- Jenkins connector pre-compiles patterns for efficient matching

**Result:** 83 deployments mapped (75 Jenkins + 8 GitHub Actions). Coverage is low relative to actual deployment volume.

**SaaS Implication:** This is the **hardest problem** for SaaS automation. No deterministic solution exists across all Jenkins setups. Requires AI-assisted job classification (see Section 6).

---

### Problem 8: GitHub GraphQL Rate Limits and Fallbacks

**Context:** GitHub GraphQL API has a separate rate limit (5,000 points/hour) and some queries fail for specific repos.

**Symptoms:**
- Certain repos fail GraphQL with schema/permission errors
- Rate limit exhaustion during large org scans (754 repos)

**Solution:** Hybrid GraphQL + REST with automatic fallback.

```python
# github_connector.py
async def _fetch_repo_prs_graphql(self, repo_name, since):
    try:
        # Single GraphQL query: PR + reviews + commits + files
        ...
    except GraphQLError:
        logger.warning("GraphQL failed for %s — retrying with REST", repo_name)
        return await self._fetch_repo_prs_rest(repo_name, since)
```

**Result:** 
- 40x faster than pure REST (50 PRs/page with all enrichments in 1 call)
- Automatic fallback for ~3-5 problematic repos per scan
- Parallel repo processing (5 concurrent) maximizes throughput

**SaaS Implication:** Already SaaS-ready. Rate limit handling needs per-tenant token management (each customer provides their own PAT/GitHub App).

---

### Problem 9: Ingestion Progress Visibility

**Context:** Long-running ingestion (2-3 hours for full backfill) needs real-time progress tracking.

**Symptoms:**
- Users couldn't tell if ingestion was running, stuck, or failed
- Single progress bar didn't convey sub-steps (fetch vs changelog vs normalize vs upsert)

**Solution (implemented):**
- `pipeline_ingestion_progress` table with per-entity tracking
- Fields: `total_sources`, `sources_done`, `records_ingested`, `current_source`, `started_at`
- API endpoint: `GET /data/v1/pipeline/ingestion/progress`
- Pipeline Monitor dashboard with polling

**Known Gap (user feedback):**
> "Dashboard should show each sub-step separately: fetch issues -> fetch changelogs -> normalize -> upsert. With count done/total, rate, and ETA per step. Like the CLI monitoring we're doing."

**SaaS Implication:** Critical for self-service. Users need to understand what's happening during first onboarding sync. Needs per-step granularity.

---

### Problem 10: Dockerfile Build Context for Shared Packages

**Context:** `pulse-api` imports from `@pulse/shared` (TypeScript shared types). Docker build context was scoped to `./packages/pulse-api`, making `../pulse-shared` inaccessible.

**Symptoms:**
- `Cannot find module '@pulse/shared/types/jira-admin'` during Docker build
- After fixing context, dist output path changed: `dist/main.js` -> `dist/pulse-api/src/main.js`

**Solution:**
1. Changed docker-compose build context to `./packages` (wider scope)
2. Rewrote Dockerfile with `/workspace/` layout copying both packages
3. Changed imports to barrel: `@pulse/shared` instead of deep paths
4. Updated CMD to match new dist structure

**SaaS Implication:** Monorepo build patterns are a one-time setup. No impact on per-tenant ingestion.

---

## 5. Entity Relationship Map

### 5.1 Cross-Source Entity Linking

```
GitHub PR ──────────────────────────────────── Jira Issue
  title: "SECOM-1441 fix login"                 issue_key: "SECOM-1441"
  linked_issue_ids: ["jira:...:1:792543"]       external_id: "jira:...:1:792543"
         │                                              │
         │  regex [A-Z][A-Z0-9]+-\d+ in               │  sprint_id
         │  title + head_ref + base_ref                 │
         │                                              ▼
         │                                       Jira Sprint
         │                                         external_id: "jira:JiraSprint:1:6619"
         │                                         board_id → project_key
         ▼
Jenkins Deployment
  repo: matched via connections.yaml
  sha: nullable (Jenkins doesn't always expose)
  environment: inferred from job pattern
```

### 5.2 Linking Mechanisms

| Link | Method | Accuracy | Deterministic? |
|------|--------|----------|---------------|
| PR -> Issue | Regex in title/branch | 21.9% overall, 96-100% per active project | Yes (pattern match) |
| Issue -> Sprint | Jira API field | 100% (source data) | Yes |
| PR -> Deployment | Commit SHA matching | Low (Jenkins SHA often missing) | Partial |
| Deployment -> Repo | `connections.yaml` job-to-repo mapping | Manual config | No |

### 5.3 ID Format Convention

| Entity | external_id format | Example |
|--------|-------------------|---------|
| Jira Issue | `jira:JiraIssue:{conn_id}:{internal_id}` | `jira:JiraIssue:1:792543` |
| Jira Sprint | `jira:JiraSprint:{conn_id}:{internal_id}` | `jira:JiraSprint:1:6619` |
| GitHub PR | `github:{owner}/{repo}/{number}` | `github:webmotors-private/portal-turbo-api/1234` |
| Jenkins Deploy | `jenkins:{job_full_name}#{build_number}` | `jenkins:folder/deploy-prod#456` |

---

## 6. Future SaaS Ingestion Engine — Specification

### 6.1 Design Principles

1. **Zero-config onboarding**: User provides credentials, everything else is discovered
2. **Adaptive pipeline**: Parameters adjust automatically based on source environment
3. **AI-assisted gap resolution**: Non-deterministic problems delegated to embedded AI
4. **Observable by default**: Every step has progress, counts, ETA
5. **Idempotent always**: Any step can be re-run safely

### 6.2 Onboarding Flow

```
User provides:          System discovers:           System configures:
┌──────────────┐       ┌─────────────────────┐     ┌──────────────────────┐
│ Jira URL     │──────>│ Projects (69)        │────>│ Active project list  │
│ Jira token   │       │ Custom fields        │     │ Status mapping       │
│              │       │ Workflows/statuses   │     │ Sprint field IDs     │
│ GitHub org   │──────>│ Repos (754)          │────>│ Active repo list     │
│ GitHub token │       │ Team structure       │     │ Branch conventions   │
│              │       │ PR naming patterns   │     │ PR-Issue link config │
│ Jenkins URL  │──────>│ Jobs (1400)          │────>│ Deployment patterns  │
│ Jenkins token│       │ Folder structure     │     │ Production markers   │
└──────────────┘       │ Build naming         │     │ Job-to-repo mapping  │
                       └─────────────────────┘     └──────────────────────┘
```

### 6.3 Deterministic Components (Implement with Rules)

These problems have well-defined solutions and should be implemented as deterministic code:

#### 6.3.1 Source Discovery

| Source | Discovery Method | Implementation |
|--------|-----------------|----------------|
| **Jira projects** | `GET /rest/api/3/project` | Already implemented (ProjectDiscoveryService) |
| **Jira custom fields** | `GET /rest/api/3/field` + name matching | Already implemented (_discover_custom_fields) |
| **GitHub repos** | GraphQL `organization.repositories` | Straightforward pagination query |
| **GitHub active repos** | Filter by `pushedAt > N months` | Already implemented (filter by activity) |
| **Jenkins jobs** | `GET /api/json?tree=jobs[name,url,fullName]` recursive | Already implemented (JenkinsConnector) |

#### 6.3.2 Incremental Sync with Scope Expansion

**Problem:** Global watermark skips historical data from newly discovered sources.

**Solution:** Per-source watermark + backfill queue.

```
Table: pipeline_watermarks_v2
- tenant_id UUID
- entity_type VARCHAR  -- 'issues', 'pull_requests', etc.
- source_key VARCHAR   -- 'jira:SECOM', 'github:portal-turbo-api', etc.
- last_synced_at TIMESTAMPTZ
- needs_backfill BOOLEAN DEFAULT true
- backfill_started_at TIMESTAMPTZ
- backfill_completed_at TIMESTAMPTZ
```

**Sync logic:**
```python
for source in active_sources:
    watermark = get_watermark(tenant, entity, source.key)
    if watermark.needs_backfill:
        # Full historical fetch (since=None or since=org_creation_date)
        data = connector.fetch(since=None, source=source)
        watermark.needs_backfill = False
        watermark.backfill_completed_at = now()
    else:
        # Incremental (only changes since last sync)
        data = connector.fetch(since=watermark.last_synced_at, source=source)
    upsert(data)
    watermark.last_synced_at = now()
```

**Deterministic:** Yes. The logic is pure state machine (needs_backfill flag).

#### 6.3.3 PR-Issue Linking (Deterministic Core)

**Current regex:** `[A-Z][A-Z0-9]+-\d+` (matches SECOM-1441, BG-12345, etc.)

**Enhancement — multi-strategy linking pipeline:**

```python
LINK_STRATEGIES = [
    # Priority 1: Exact key match in title (highest confidence)
    TitleKeyMatch(pattern=r"[A-Z][A-Z0-9]+-\d+"),
    
    # Priority 2: Branch name convention (feature/SECOM-1441-description)
    BranchKeyMatch(pattern=r"[A-Z][A-Z0-9]+-\d+"),
    
    # Priority 3: GitHub-native issue links (if PR body contains Jira URL)
    BodyURLMatch(pattern=r"atlassian\.net/browse/([A-Z][A-Z0-9]+-\d+)"),
    
    # Priority 4: Commit message references
    CommitMessageMatch(pattern=r"[A-Z][A-Z0-9]+-\d+"),
    
    # Priority 5: Jira dev panel links (if available via Jira API)
    JiraDevPanelMatch(),  # Requires Jira development info API
]
```

**Deterministic:** Yes (regex + URL parsing). Each strategy adds confidence score.

#### 6.3.4 Status Normalization (Deterministic Core + AI Fallback)

**Deterministic mapping (covers ~95% of statuses):**

```python
# Category patterns (regex-based, language-independent)
STATUS_PATTERNS = {
    "todo": [
        r"^(to\s*do|backlog|new|open|created|a\s*fazer|pendente|aberto|novo)$",
        r"^(ready\s*for\s*dev|pronto|selected|triaged|refinado)$",
    ],
    "in_progress": [
        r"(in\s*progress|em\s*(desenvolvimento|progresso|andamento))",
        r"(review|teste|testing|qa|validat|homolog|deploy|aguardando)",
        r"(development|coding|implementing|analyzing|analise)",
    ],
    "done": [
        r"^(done|closed|resolved|complete|finish|conclu|finaliz|entregue)$",
        r"(released|deployed|shipped|publicado|em\s*produ)",
    ],
}
```

**AI fallback for unrecognized statuses:** see Section 6.4.2.

#### 6.3.5 Rate Limit Management

| Source | Limit | Strategy |
|--------|-------|----------|
| GitHub GraphQL | 5,000 pts/hr | Token bucket, exponential backoff, per-tenant quota |
| GitHub REST | 5,000 req/hr | Same |
| Jira Cloud | ~100 req/min (varies by plan) | Adaptive backoff on 429, respect Retry-After header |
| Jenkins | No formal limit | Concurrent connection cap (default 5) |

**Implementation:** Already have backoff. Need to add:
- Per-tenant token accounting
- Cross-worker coordination (Redis-based token bucket)
- Graceful degradation (reduce batch size on rate limit, don't fail)

### 6.4 Non-Deterministic Components (Implement with AI)

These problems have ambiguous inputs and require contextual understanding. An embedded AI agent ("Ingestion Intelligence Agent") handles them.

#### 6.4.1 Jenkins Job Classification

**Problem:** Given 1,400 Jenkins jobs, which ones are production deployments?

**Why non-deterministic:** Job naming varies wildly:
- `deploy-prod-api`, `release/main`, `CD-production`, `publish-live`
- `QA-deploy`, `staging-release`, `integration-test-deploy`
- Folder structures: `PF/deploy-api`, `SECOM/pipelines/cd-main`

**AI Agent Approach:**

```yaml
Agent: JenkinsJobClassifier
Input:
  - Full list of Jenkins jobs (name, fullName, folder path, color/status)
  - Sample build logs (last 5 builds per job — NOT executed, READ from API)
  - Job configuration XML (parameters, triggers, downstream jobs)
  
Classification Task:
  For each job, determine:
    1. Is this a deployment job? (yes/no/uncertain)
    2. Target environment: production|staging|dev|test|unknown
    3. Confidence score: 0.0 - 1.0
    4. Associated repository (inferred from job name/config)
    
Signals to consider:
  - Job name contains "deploy", "release", "cd", "publish"
  - Job triggers on main/master branch
  - Job has parameters like ENVIRONMENT=production
  - Downstream of build jobs (pipeline pattern)
  - Build frequency matches deployment cadence
  - Job folder structure indicates team/project
  
Output:
  - Deterministic mappings for confidence > 0.8
  - Suggested mappings for 0.5-0.8 (human review)
  - Skipped for < 0.5
```

**Human-in-the-loop:** For confidence 0.5-0.8, present suggestions in Admin UI with "Approve/Reject" buttons. Learn from corrections.

#### 6.4.2 Unknown Status Classification

**Problem:** New Jira workflow statuses not in the mapping dictionary.

**AI Agent Approach:**

```yaml
Agent: StatusClassifier
Input:
  - Unknown status name (e.g., "Aguardando Aprovação do PO")
  - Workflow context: what statuses come before and after it
  - Issue type (bug, story, task)
  - Language detection

Classification:
  Map to: todo | in_progress | done
  
Reasoning:
  - "Aguardando" (waiting) + workflow position (between dev and done)
  - Transition pattern: "Em Desenvolvimento" → THIS → "Em Teste"
  - Conclusion: in_progress (waiting state between active work stages)

Output:
  - Classification + confidence
  - If confidence > 0.9: auto-add to tenant's mapping
  - If confidence < 0.9: queue for admin review
```

#### 6.4.3 Repository-to-Project Mapping

**Problem:** GitHub repos don't inherently know which Jira project they belong to. Current linking relies on PR titles containing issue keys.

**AI Agent Approach:**

```yaml
Agent: RepoProjectMapper
Input:
  - Repository name, description, topics/tags
  - PR title patterns (aggregate: which Jira keys appear most)
  - Team members (GitHub collaborators vs Jira project members)
  - README content (project references)
  
Mapping Task:
  For each repo, determine:
    1. Primary Jira project(s) associated
    2. Confidence score
    3. Evidence (which signals matched)

Signals:
  - PR title regex: 80% of PRs in repo X reference project SECOM
  - Team overlap: 5 of 7 GitHub collaborators are Jira SECOM members
  - Repo name: "secom-api" → likely SECOM project
  - README mentions: "Part of the SECOM platform"
```

**Deterministic component:** The PR-title statistical approach is already implemented in `SmartPrioritizer`. AI adds repo name/description/team analysis.

#### 6.4.4 Changelog Gap Detection

**Problem:** Some Jira issues have incomplete changelogs (missing transitions). This produces wrong cycle time calculations.

**AI Agent Approach:**

```yaml
Agent: ChangelogAuditor
Input:
  - Issue with current status "Done" but no transitions in changelog
  - Issue with status_transitions showing jump from "To Do" → "Done" (no intermediate)
  - Issue created date vs first transition date gap > 30 days

Detection Rules (deterministic):
  - Flag: issue.normalized_status == "done" AND len(status_transitions) == 0
  - Flag: time between consecutive transitions > 90 days
  - Flag: final status doesn't match last transition's target

AI Resolution:
  - Estimate missing transitions based on similar issues in same project
  - Mark affected metrics as "low confidence" in calculations
  - Surface data quality alerts in Pipeline Monitor
```

#### 6.4.5 Project Alias and Rename Detection

**Problem:** PRs reference "RC-1234" but no Jira project "RC" exists. Could be renamed, archived, or an abbreviation.

**AI Agent Approach:**

```yaml
Agent: ProjectAliasResolver
Input:
  - Orphan project keys from PR titles (e.g., RC: 1,348 refs)
  - Active Jira project catalog
  - Historical project data (if available from Jira admin API)

Resolution strategies:
  1. Fuzzy match: RC → closest Jira project? (no strong match)
  2. Temporal analysis: when did "RC-" PRs stop? Did a new key start?
  3. Team overlap: who authored RC-* PRs? Which projects do they work on now?
  4. Ask admin: "We found 1,348 PRs referencing 'RC' but no matching project. 
     Is this an old name for an existing project?"
     
Output:
  - Alias table: {"RC": "CRW"} (if confirmed)
  - Archived marker: {"RC": "archived_project"} (if no match)
```

### 6.5 Ingestion Intelligence Agent — Architecture

```
┌─────────────────────────────────────────────────────┐
│              Ingestion Intelligence Agent             │
│                                                       │
│  ┌───────────┐  ┌────────────┐  ┌─────────────────┐ │
│  │  Jenkins   │  │  Status    │  │  Repo-Project   │ │
│  │  Job       │  │  Classifier│  │  Mapper         │ │
│  │  Classifier│  │            │  │                 │ │
│  └─────┬─────┘  └─────┬──────┘  └───────┬─────────┘ │
│        │              │                  │            │
│  ┌─────▼──────────────▼──────────────────▼─────────┐ │
│  │              Decision Engine                      │ │
│  │  - High confidence (>0.9): auto-apply             │ │
│  │  - Medium (0.5-0.9): queue for admin review       │ │
│  │  - Low (<0.5): skip, log for analysis             │ │
│  └─────────────────────┬─────────────────────────────┘ │
│                        │                               │
│  ┌─────────────────────▼─────────────────────────────┐ │
│  │              Learning Loop                          │ │
│  │  - Admin approvals feed back into rules             │ │
│  │  - Accumulate tenant-specific patterns              │ │
│  │  - Graduate AI decisions to deterministic rules     │ │
│  │    when pattern is confirmed N times                │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 6.6 Observable Ingestion — Per-Step Progress

Based on user feedback, the Pipeline Monitor should expose:

```yaml
IngestionPipeline:
  source: jira
  steps:
    - name: "Discover Projects"
      status: completed
      count: "69 projects found"
      duration: "3s"
      
    - name: "Fetch Issues"
      status: completed
      total: 373669
      done: 373669
      rate: "2,240/min"
      duration: "2h 04min"
      
    - name: "Fetch Changelogs"
      status: completed
      total: 6845
      done: 6845
      cached: 366784
      rate: "170/min"
      duration: "40min"
      
    - name: "Normalize & Upsert"
      status: completed
      records: 373872
      duration: "8min"
      
    - name: "Link PRs to Issues"
      status: completed
      linked: 13966
      total_prs: 63647
      link_rate: "21.9%"
      duration: "5s"

  source: github
  steps:
    - name: "Discover Repos"
      status: completed
      count: "754 active repos"
      
    - name: "Fetch PRs (GraphQL)"
      status: running
      total_repos: 754
      repos_done: 232
      prs_fetched: 98
      rate: "~120 repos/min"
      eta: "~4 min"
      
    - name: "Normalize & Upsert"
      status: pending

  source: jenkins
  steps:
    - name: "Fetch Jobs"
      status: pending
    - name: "Fetch Builds"
      status: pending
    - name: "Classify Deployments"
      status: pending
```

### 6.7 Implementation Roadmap

| Phase | Component | Deterministic? | Effort | Priority |
|-------|-----------|---------------|--------|----------|
| **S1** | Per-source watermarks (6.3.2) | Yes | 3 days | P0 |
| **S1** | Multi-strategy PR linking (6.3.3) | Yes | 2 days | P0 |
| **S1** | Per-step progress tracking (6.6) | Yes | 3 days | P0 |
| **S2** | GitHub org/repo discovery | Yes | 2 days | P1 |
| **S2** | Jenkins job discovery | Yes | 1 day | P1 |
| **S2** | Status regex patterns (6.3.4) | Yes | 1 day | P1 |
| **S2** | Rate limit coordination (6.3.5) | Yes | 2 days | P1 |
| **S3** | Jenkins AI classifier (6.4.1) | No (AI) | 5 days | P1 |
| **S3** | Status AI classifier (6.4.2) | No (AI) | 3 days | P2 |
| **S3** | Repo-Project AI mapper (6.4.3) | No (AI) | 3 days | P2 |
| **S4** | Changelog auditor (6.4.4) | Hybrid | 3 days | P2 |
| **S4** | Project alias resolver (6.4.5) | No (AI) | 2 days | P3 |
| **S4** | Learning loop / feedback system | No (AI) | 5 days | P3 |

---

## 7. Appendix

### A. Key File References

| File | Purpose |
|------|---------|
| `packages/pulse-data/src/connectors/base.py` | BaseConnector interface |
| `packages/pulse-data/src/connectors/jira_connector.py` | Jira REST v3 + Agile API |
| `packages/pulse-data/src/connectors/github_connector.py` | GraphQL + REST hybrid |
| `packages/pulse-data/src/connectors/jenkins_connector.py` | Jenkins JSON API |
| `packages/pulse-data/src/connectors/aggregator.py` | Multi-source router |
| `packages/pulse-data/src/contexts/engineering_data/normalizer.py` | 5 normalize functions + linker |
| `packages/pulse-data/src/workers/devlake_sync.py` | Sync orchestrator |
| `packages/pulse-data/src/contexts/integrations/jira/discovery/` | Dynamic discovery system |
| `packages/pulse-data/scripts/relink_prs_to_issues.sql` | Backfill PR-Issue links |
| `packages/pulse-data/alembic/versions/` | 6 migrations (001-006) |

### B. Configuration Files

| File | Purpose |
|------|---------|
| `config/connections.yaml` | Source credentials + Jenkins job mappings |
| `.env` | Feature flags, API tokens, Redis URL |
| `docker-compose.yml` | Service definitions + env var injection |

### C. Commit History (Ingestion-Related)

| Commit | Description |
|--------|-------------|
| `c9b5cf6` | Replace DevLake with direct source connectors (ADR-005) |
| `54d7002` | Harden connectors (Jira POST search, board filtering) |
| `221db7c` | Add 321 unit tests for connectors |
| `60fe576` | Migrate PR fetch to GraphQL (40x faster) |
| `7f9f339` | Batch persistence for PR ingestion |
| `6b3183c` | Real-time ingestion progress dashboard |
| `36d9157` | Emit per-repo starting signal for UI |
| `0723df9` | Discover sprint/story_points custom fields |
| `1f9ac52` | Add issue_key column for PR linking |
| `c243a87` | Foundation for dynamic project discovery (ADR-014) |
| `efaeba7` | Discovery service, mode resolver, guardrails |
| `bea8b13` | Admin API + React UI for discovery |
| `c5350dc` | Security hardening, PII gating, Phase 4 rollout |
