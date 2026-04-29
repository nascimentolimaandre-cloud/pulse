# PULSE Data Ingestion Specification

## SDD — Spec-Driven Development Document

**Version:** 1.0  
**Date:** 2026-04-14  
**Status:** Living Document  
**Audience:** Engineering, Product, Future AI Ingestion Agent  

---

## 1. Executive Summary

This document captures every adjustment, problem, and solution encountered during PULSE's data ingestion buildout — from initial DevLake-based pipeline to current proprietary connectors with dynamic discovery. It serves as the **single source of truth** for understanding ingestion behavior and as the **specification baseline** for building a fully autonomous SaaS ingestion engine.

### Current State (2026-04-29 — pós-Phase-1 v2 + data-quality fixes)

| Metric | Value | Note |
|--------|-------|------|
| Jira projects active | 32 (de 69 totais descobertos) | Subset ativo via discovery dinâmica (ADR-014) |
| Issues ingested | 311.068 | Re-ingestão pós-`seed_dev` revert (commit `40ca7e4`); diff vs. 373k anterior é por escopo de projetos ativos |
| PRs ingested | 63.131 | Estável desde 2026-04-27 |
| PR-Issue link rate | ~5% (em recovery após reset) | Baixo temporariamente — re-link pós-ingestão completa restaura ~22% |
| Deployments (Jenkins) | 1.376 | Auto-discovery via SCM scan (commit `d1aebf7`) |
| Sprints | 195/217 com status correto (89,9%) | 22 vazias = board órfão 873 sem projeto ativo. Pós-FDD-OPS-018 (commit `649ed78`) |
| GitHub repos discovered | 754 (active), 1.429 (total) | Estável |
| Status definitions discovered | 326 (117 new + 181 indeterminate + 28 done) | Pós-FDD-OPS-017 (commit `0c7124d`) |
| Distinct status names em uso | 104 | DEFAULT_STATUS_MAPPING expandido para ~80; fallback `statusCategory` cobre o resto |
| Squads ativos | 27 | FID + PTURB usam Sprint; **25 são Kanban-pure** (sem sprints) |
| Story Points usage | 0% (todos os 69 projetos) | Webmotors NÃO usa SP — fallback chain T-shirt/Hours/Count em FDD-OPS-016 |
| Ingestion cycle time | TTFR <60s (Phase 1 v2) | Backfill BG ~197k issues continua o gargalo. Pre-fix bulk: 24-30h. Pós-fix: ~30-45 min issues + paralelo PR/deploy |
| Coverage de `status_transitions` | ~0% legacy / 100% fresh | Rolling forward: cada incremental sync corrige; backfill retroativo opcional via watermark reset |
| Coverage de `story_points` (effort) | 52,3% em projetos novos (CRMC), ~0% legacy | Mesma rolling-forward dinâmica que status_transitions |

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
| Org size | ~750 active repos, 69 Jira projects, 27 squads ativos | High volume, need batch processing |
| Squad shape | 25 de 27 squads são **Kanban-puros** (sem sprints); apenas FID + PTURB usam Scrum | Sprint metrics aplicam-se a 7% das squads — métricas de fluxo (Cycle Time, CFD, Throughput) são as primárias |
| Jira project scale | 197K issues em projeto único (BG) | Single JQL query can return massive payloads — exige streaming per-project |
| Custom fields | Sprint = `customfield_10007`, Story Points = `customfield_18524` (+ legacy `customfield_10004`) | Must discover dynamically per tenant via `/rest/api/3/field` |
| Effort estimation method | **Webmotors NÃO usa Story Points** (0% dos 69 projetos). Padrões heterogêneos por squad: T-shirt size (P/M/G), `timeoriginalestimate` em horas, ou nada (Kanban-puro) | FDD-OPS-016 — fallback chain SP→T-shirt→Hours→None com discovery dinâmico de campos T-shirt/Tamanho |
| T-shirt size fields | `customfield_18762` ("T-Shirt Size") + `customfield_15100` ("Tamanho/Impacto") | Mapeados em escala Fibonacci: PP=1, P=2, M=3, G=5, GG=8, GGG=13. Discovery por nome (case-insensitive) |
| Status workflows | 326 status definitions descobertas; 104 raw distintos em uso ativo | DEFAULT_STATUS_MAPPING curado com ~80 PT-BR; resto via fallback `statusCategory.key` da Jira |
| Jenkins patterns | No corporate standard; each repo has unique pipeline config | Cannot use single regex for deployment detection — auto-discovery via SCM scan (`d1aebf7`) descobriu 577 PRD jobs em 283 repos |
| Language mix | Portuguese status names ("Em Desenvolvimento", "Concluído", "FECHADO EM PROD") | Status normalizer requer i18n mapping + `statusCategory` fallback como rede de segurança |
| Jira reserved words | Project key "DESC" é SQL reserved word | Must quote project keys in JQL |
| Archived projects | Some keys referenced in PRs (e.g., "RC") don't exist in Jira API | Graceful handling of orphan references — RC tem 1.348 PR refs sem Jira project correspondente |
| NULL bytes em texto | Observado 2026-04-28 em ENO-3296 (description) | Postgres `text` rejeita 0x00; helper `_strip_null_bytes` aplicado a title/description/assignee no normalizer |
| Network dependency | Acesso à Jira/GitHub/Jenkins via VPN corporativa | VPN drops causaram silent failures (FDD-OPS-001 / FDD-OPS-014 §AP-3, AP-4); health-aware orchestration é P-8 do v2 |

### 2.3 Source Configuration Philosophy — Discovery Only

**Decisão fundamental (locked-in 2026-04-27):** PULSE **NÃO mantém listas
explícitas** de repos GitHub ou projetos Jira em `connections.yaml` ou em
qualquer outro lugar. **Todo source é descoberto dinamicamente.**

**Por quê** — três razões:

1. **Listas explícitas envelhecem mal**: cada novo squad/repo/projeto
   exige edição manual + redeploy. Webmotors evoluiu de 8 → 69 projetos
   Jira em poucas semanas; manter sincronizado à mão não escala.
2. **Falham silenciosamente**: PRs referenciando `SECOM-1234` ficam
   "linkados a nada" se SECOM não está na lista. Resultado: 5.27% de
   link rate. Após discovery: 21.9% (4× melhor) com 96-100% per active
   project.
3. **Não fazem sentido pra SaaS**: o produto precisa funcionar em
   tenant novo sem que ninguém edite YAML. Discovery é a única forma de
   "zero-config onboarding" (princípio §6.1).

**O que é mantido em `connections.yaml`** (não-discoverable):

| Campo | Razão |
|---|---|
| `connections[].source` (github/jira/jenkins) | Identifica tipo de conector pra usar |
| `connections[].base_url` | Endpoint da source (Jira tenant URL, GitHub Enterprise vs Cloud) |
| `connections[].token_env`/`username_env` | Onde achar credenciais (env var) |
| `connections[].sync_interval_minutes` | Cadência de sync (decisão operacional, não discoverable) |
| `status_mapping` (60+ entries PT-BR/EN) | Mapeamento de workflow Jira customizado → estados normalizados (todo/in_progress/in_review/done). Pode ser parcialmente AI-discovered no futuro (§6.4) |
| `teams` (squad → repos/projects mapping) | Decisão de organização, não topologia de source — pertence ao produto |

**O que foi REMOVIDO em 2026-04-27:**

- `connections[].scope.repositories` (lista de 9 repos GitHub explícitos)
- `connections[].scope.projects` (lista de 8 projetos Jira explícitos)

Eram artefatos de bootstrap (teste de viabilidade no início do projeto).
Agora dispensáveis.

**Como cada source descobre:**

| Source | Mecanismo | Resultado |
|---|---|---|
| **GitHub** | `discover_repos(active_months=12)` via GraphQL `organization.repositories(orderBy: PUSHED_AT)` filtrado por atividade | ~283 repos com atividade nos últimos 12 meses |
| **Jira** | `ProjectDiscoveryService.run_discovery()` lista todos projetos via REST `/rest/api/3/project`, marca como `discovered`. `SmartPrioritizer.auto_activate(threshold=3)` promove pra `active` projetos com ≥3 references em PR titles | 69 projetos descobertos, ~9 dos quais auto-ativados na primeira passada (cresce conforme novos PRs chegam) |
| **Jenkins** | `discover_jenkins_jobs.py` faz SCM scan READ-ONLY em todos os jobs, gera `config/jenkins-job-mapping.json`. Sync worker lê esse JSON. Re-rodar quando novos repos aparecem (semanal/sob demanda) | 577 PRD jobs em 283 repos |

**Quando re-discovery acontece:**

- Jira: cron `0 3 * * *` UTC (configurável via `tenant_jira_config.discovery_schedule_cron`); manual via `POST /admin/jira/discovery/run`
- GitHub: a cada ciclo de sync (15min) — o `discover_repos` é chamado pelo connector se `_explicit_repos is None`
- Jenkins: regen do JSON é manual (script `discover_jenkins_jobs.py`); idempotente

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

| Decision | Rationale | ADR / Commit |
|----------|-----------|--------------|
| **Discovery-only source configuration** | See §2.3 — explicit lists kill SaaS scalability and link rate | 2026-04-27 |
| Replaced DevLake with proprietary connectors | 99.3% issue data loss in DevLake PostgreSQL layer | ADR-005 |
| GraphQL primary for GitHub, REST fallback | 40x faster PR fetch (50 PRs + reviews + stats in 1 call) | Commit `60fe576` |
| Per-repo batch upsert (not all-at-end) | Memory efficiency + real-time progress visibility | Commit `7f9f339` |
| Global watermark per entity (not per-project) | Simpler model, but requires reset for project scope expansion. **Tradeoff documented in §3.7 + Problem 5.** | Migration 002 |
| JSONB for `linked_issue_ids` and `status_transitions` | Flexible schema, supports variable-length arrays | Migration 001 |
| Row-Level Security on all tables | Multi-tenant isolation at DB level | Migration 001 |
| Kafka event backbone | Decouples ingestion from metric calculation | ADR-004 |
| **Partial index for snapshots `(tenant, metric_type, calculated_at DESC) WHERE team_id IS NULL`** | 50× perf regression on `/metrics/home` once `metrics_snapshots` >5M rows; non-partial index doesn't help due to B-tree NULL semantics | Commit `80f1796` (2026-04-27) |
| **Worker schema-drift monitor (FDD-OPS-001 line 3)** | Detects payload-vs-dataclass mismatch when bytecode is stale; tags rows with `_schema_drift` for Pipeline Monitor surfacing | Commit `5d71618` |

### 3.4 Worker Lifecycle Guarantees

**Origin:** FDD-OPS-001 incidents (2026-04-16/17/18) — Python workers running
stale code in memory while updated source was on disk. Resulted in 3
production-local incidents in 3 days where snapshots persisted with
obsolete logic.

**Four lines of defense (all SHIPPED):**

1. **Hot-reload em dev (planned, not yet shipped)** — `docker compose
   watch` to auto-reload workers on file change
2. **Admin recalc force-reload** — `POST /admin/metrics/recalculate`
   calls `importlib.reload()` on domain/service modules before recalc
3. **Snapshot schema-drift monitor (SHIPPED 2026-04-23)** — pós-write,
   compara payload com dataclass corrente. Missing fields → log WARN
   `FDD-OPS-001/L3` + Prometheus counter `pulse_snapshot_schema_drift_total`
   + anota `_schema_drift` no JSONB. Pipeline Monitor consome via
   `GET /pipeline/schema-drift?hours=N`
4. **CI/CD force-restart on deploy (SHIPPED 2026-04-23)** —
   `.github/workflows/deploy.yml` sempre roda
   `docker compose up -d --force-recreate` nos 4 workers Python pós
   build (deploy step ainda é TODO, mas o template existe)

**Operacional fora do CI:** após edit em `domain/service` files local,
o operator deve rodar `make rotate-secrets` (que faz `up -d
--force-recreate` em 5 serviços) — `docker compose restart` NÃO relê
o `.env` nem força reimport de módulos. Documentado em
`docs/testing-playbook.md` §8.9.

### 3.5 DB Index Strategy for Snapshots

**Origin:** 2026-04-27 incident — dashboard error 30s timeout porque
`/metrics/home` levava 54s. Causa raiz: `metrics_snapshots` cresceu
pra 7M rows e a query `WHERE tenant_id=? AND metric_type=? AND team_id
IS NULL ORDER BY calculated_at DESC LIMIT 200` regrediu de Index Scan
pra Parallel Seq Scan (10s/query × 8 queries por home request = 50s+).

**Indexes mantidos** (em `metrics_snapshots`):

| Index | Definição | Cobre |
|---|---|---|
| `metrics_snapshots_pkey` | `(id)` | Primary key — sempre |
| `uq_metrics_snapshots_*` | `UNIQUE(tenant, team, type, name, period_start, period_end)` | Upsert constraint |
| `idx_metrics_snapshots_lookup` | `(tenant, type, name, period_start, period_end)` | Specific metric+window queries |
| **`idx_metrics_snapshots_tenant_latest`** | `(tenant, type, calculated_at DESC) WHERE team_id IS NULL` | **`/metrics/home` tenant-wide aggregations** (NEW 2026-04-27, migration 009) |

**Por que partial index** (não non-partial): B-tree não usa índice
quando filtro inclui `IS NULL` em coluna não-NULL-aware. Partial
index `WHERE team_id IS NULL` resolve isso e mantém o índice menor
(exclui linhas team-scoped que têm padrão de acesso diferente).

**Resultado medido**: query 10.3s → 2.4ms (**~4000× faster**). `/metrics/home`
total: 54s → 0.6s.

**Princípio pra futuro**: toda nova query crítica que faz `ORDER BY ...
LIMIT N` em tabela >1M rows precisa de índice **explicitamente
ordenado** pela coluna do ORDER BY. EXPLAIN ANALYZE durante PR review.
Tracked como FDD-OPS-009 (DB query plan regression tests).

### 3.6 Jenkins Job Mapping Workflow

**Por que mapping em vez de discovery contínua:** Jenkins não tem
endpoint nativo eficiente pra "list todos os PRD jobs com seus repos
GitHub correspondentes". Precisaríamos consultar `lastBuild.remoteUrls`
de cada job individualmente — pra 1400+ jobs Webmotors, isso é caro
e lento.

**Solução:** SCM scan one-shot, output em JSON, sync worker lê o JSON
no boot.

**Fluxo:**

```
1. Operator (humano ou cron) roda:
     docker compose exec sync-worker python -m scripts.discover_jenkins_jobs

2. Script faz READ-ONLY scan via Jenkins API:
   - GET /api/json?tree=jobs[name,fullName,url,lastBuild[url]]
   - Para cada job: lastBuild → workflow_run → SCM remoteUrls
   - Classifica jobs por padrão (PRD vs DEV vs HML)
   - Casa cada job com repo GitHub (heurísticas: nome, SCM URL)
   - Output: config/jenkins-job-mapping.json (committed)

3. sync-worker lê o JSON no startup (config flag jobs_from_mapping=true)
   - Mantém em memória: dict[repo_full_name, list[prd_jobs]]
   - Pra cada deploy event do Jenkins: usa o mapping pra resolver repo

4. Quando regenerar:
   - Novo repo Webmotors aparece (esperado: poucas vezes/mês)
   - Mudança de pattern de naming dos jobs
   - Cron sugerido (futuro): semanal, sábado 04:00 UTC
```

**Resultado atual** (`jenkins-job-mapping.json` versão 2026-04-14):
283 repos × 577 PRD jobs.

**Idempotência:** script é READ-ONLY. Re-rodar a qualquer momento é
seguro. Dois runs consecutivos produzem JSONs equivalentes (modulo
mudanças genuínas em Jenkins).

### 3.7 Post-Ingestion Mandatory Steps

Após qualquer **full re-ingestion** (DB wipe + sync from scratch),
quatro passos pós-ingestão são **obrigatórios** pra ter dashboard
correto. Skip qualquer um → métricas incompletas ou inconsistentes.

| # | Operação | Endpoint / Comando | Tempo | Por quê |
|---|---|---|---|---|
| 1 | Backfill description | `POST /data/v1/admin/issues/refresh-descriptions?scope=all` | ~43min | `description` não é puxada no fetch padrão de issues (custo de payload Jira); endpoint admin busca via `GET /rest/api/3/issue/{key}`. Necessário pro Flow Health drawer mostrar contexto da issue. Cobertura final esperada ~62% (~38% das issues genuinamente sem description no Jira). |
| 2 | Re-link PRs↔Issues | `psql < scripts/relink_prs_to_issues.sql` | ~5s | Sync worker linka PRs durante ingestão usando o snapshot de issues no momento. Discovery dinâmica pode ativar projetos depois — re-link captura PRs que ficaram sem match na primeira passada. Idempotente. |
| 3 | Force snapshot recalc | `POST /data/v1/admin/metrics/recalculate` | ~10s | Garante que todos os 6 períodos (7d/14d/30d/60d/90d/120d) e 4 metric types (dora/lean/cycle_time/throughput) têm snapshot fresco. Workers rodam por evento Kafka, mas alguns períodos podem ficar stale se o evento não disparou em algum bucket. |
| 4 | (Conditional) Backfill `first_commit_at` | `POST /data/v1/admin/prs/refresh-first-commits?scope=stale` | varies | **Skip se ingestão usou código pós-INC-003 fix (2026-04-17+).** Validar via SQL: se ≥90% dos PRs têm `first_commit_at < created_at`, não rodar. Se <90%, rodar com `scope=stale` (filtro `first_commit_at == created_at`). |

**Validação pós-step 4:**

```sql
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE first_commit_at < created_at) AS correct,
  COUNT(*) FILTER (WHERE first_commit_at = created_at) AS stale,
  ROUND(100.0 * COUNT(*) FILTER (WHERE first_commit_at < created_at)
        / NULLIF(COUNT(*),0), 1) AS pct_correct
FROM eng_pull_requests WHERE source = 'github';
```

Esperado: `pct_correct >= 90%` (alguns PRs muito pequenos onde commit
e abertura acontecem no mesmo segundo são casos legítimos de igualdade).

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

### Problem 6: Status Normalization — Hybrid Textual + Jira statusCategory Fallback

**Context:** Jira workflows variam selvagemente entre orgs e até entre projects do mesmo tenant. Webmotors usa status names em PT-BR (e.g., "Em Desenvolvimento", "FECHADO EM PROD"). Audit em 2026-04-28 (FDD-OPS-017 / INC-022) mostrou que a abordagem **textual-only** original era catastroficamente insuficiente.

**Symptoms quantificados (2026-04-28):**

Distribuição de `normalized_status` em 311.068 issues:
- 96,5% `done` · 3,3% `todo` · 0,2% `in_progress` · 0,1% `in_review`

Investigação revelou que a Webmotors tem **104 status raw distintos** em workflows ativos. O `DEFAULT_STATUS_MAPPING` original cobria ~50 → 50+ status caíam silenciosamente no fallback "Unknown → todo". Casos sistêmicos:

| Status raw | Issues afetadas | Bucket atual (errado) | Bucket correto |
|---|---|---|---|
| `FECHADO EM PROD` | 2.881 | todo | done |
| `FECHADO EM HML` | 14 | todo | done |
| `Em Progresso` | 6 | todo | in_progress |
| `Em desenv` | 4 | todo | in_progress |
| `Em Deploy Produção` | 14 | todo | in_progress |
| `Em Monitoramento Produção` | 3 | todo | done |
| `Homologação` | 9 | todo | in_review |
| `Em Verificação` | 4 | todo | in_review |
| (50+ outros) | dezenas | todo | varia |

**Cascada CRÍTICA**: status_transitions herdam classificação errada. A última transição registrada de uma issue concluída ficava com `status: "todo"` em vez de `done`. Resultado em CASCATA:

- **Cycle Time** infinito (não há transição final para `done`)
- **Throughput** sub-conta (issues entregues não aparecem)
- **WIP** super-conta (issues finalizadas continuam "em fluxo")
- **CFD / Lead Time** distorcidos
- **Flow Efficiency** indeterminado

Sem o fix, **todo o pilar Lean** está comprometido para qualquer projeto que use status fora do mapping curado.

**Solução: Hybrid normalization em 3 camadas** (FDD-OPS-017, commit `0c7124d`):

```python
def normalize_status(raw_status, status_mapping=None, status_category=None):
    # Camada 1: Textual mapping curado (granularidade in_progress vs in_review)
    mapping = {**DEFAULT_STATUS_MAPPING}  # ~80 PT-BR + EN entries
    if status_mapping:
        mapping.update({k.lower(): v for k, v in status_mapping.items()})
    normalized = mapping.get(raw_status.lower().strip())
    if normalized:
        return normalized
    
    # Camada 2: Jira statusCategory.key fallback (autoritativo done/não-done)
    if status_category:
        cat = status_category.lower().strip()
        if cat == "done":          return "done"
        if cat == "indeterminate": return "in_progress"  # NB: collapses in_review
        if cat == "new":           return "todo"
    
    # Camada 3: Default 'todo' com WARN log (extremamente raro agora)
    logger.warning("Unknown status %r — defaulting to 'todo'", raw_status)
    return "todo"
```

**Discovery da camada 2** (`_discover_status_categories`): conector chama `/rest/api/3/status` 1× por lifetime e cacheia `name → category` para todos os 326 status defs do tenant. Webmotors: 117 new + 181 indeterminate + 28 done.

**Por que híbrido (não pure textual nem pure category):**

- **Textual ganha** quando definido — preserva granularidade `in_progress` vs `in_review` que o Cycle Time Breakdown precisa. Jira `statusCategory.indeterminate` colapsa os dois.
- **Category fallback** captura o long tail tenant-custom sem manutenção contínua. Workflow author é fonte de verdade sobre done/não-done.
- **Default 'todo'** com WARN só atinge agora status sem category — extremamente raro pós-fix.

**`build_status_transitions` integrado**: `status_categories_map` (todos status → categoria) é passado adiante para classificar cada `to_status` histórico via map. O bug de cascada acima é corrigido na fonte.

**Result quantificado:**

3.151 issues reclassificarão na re-ingestão (1% do total) — long tail catastrófico. Distribuição já correta para os 97% restantes.

| Transição | Quantidade |
|---|---|
| `todo → done` (FECHADO EM PROD/HML, etc.) | 2.923 |
| `todo → in_review` (Homologação, Verificação) | 161 |
| `todo → in_progress` (Em Progresso, Em desenv) | 67 |

**Decisão de produto registrada** (FDD-OPS-017 backlog): `FECHADO EM HML` mapeado como `done` (segue Jira `statusCategory.key='done'` + nome literal "FECHADO"). Workflow author classifica como done; respeitamos. Se Webmotors quiser tratar como ainda em fluxo, pode renomear para "Aguardando Deploy Produção" (mapeado para `in_progress`).

**SaaS Implication:** Hybrid approach é SaaS-ready out-of-the-box. Cada novo tenant:
1. Conector descobre seus 100-300 status defs via `/rest/api/3/status` (1 chamada)
2. Textual mapping curado (PT-BR + EN + ~80 PT-BR variants) cobre majoritário
3. Status category fallback captura o long tail proprietário
4. Operadores adicionam mappings textuais específicos APENAS quando precisam de granularidade `in_review` (raro)

**Future** (FDD-OPS já catalogado): AI-fallback para status que faltam category — observar workflow transitions para inferir categoria (Section 6.4.2).

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

### Problem 11: Inline Changelog Lost in Connector Mapping (`_map_issue` drop)

**Context:** FDD-OPS-013 (commit `4d1c9b4`, 2026-04-28) eliminou o redundant `fetch_issue_changelogs` round-trip extraindo changelogs **inline** do JQL response (`expand=changelog`). Função nova `extract_status_transitions_inline(raw)` no sync worker fez `raw.get("changelog", {}).get("histories", [])`. Pareceu funcionar (testes passaram). Entretanto, audit em 2026-04-28 mostrou `status_transitions = []` em **100% das 311.007 issues** — mesmo problema que Phase 1 era para resolver.

**Symptoms:**

- 311.007 issues no DB (todas as ingeridas pós-Phase-1) com `status_transitions = []`
- Cycle Time não fechava — sem transição para `done`
- Throughput sub-contava — issues `done` apareciam como em fluxo
- WIP super-contava — issues finalizadas no bucket de "ativo"
- Lean metrics todas comprometidas

**Root Cause** (descoberto via tracing connector → worker em 2026-04-29):

`JiraConnector._map_issue` (commit ancestral) extraía o changelog para um cache lateral (`self._last_changelogs[internal_id]`) **mas NÃO incluía o campo `changelog` no dict mapeado de retorno**:

```python
# Ancestral code (BUG):
def _map_issue(self, jira_issue):
    changelogs = self._extract_changelogs(internal_id, jira_issue)
    if changelogs:
        self._last_changelogs[internal_id] = changelogs   # cache lateral
    return {
        "id": internal_id,
        "title": fields.get("summary", ""),
        # ... outros campos ...
        # ❌ NO changelog field aqui
    }
```

O `_sync_issues` (worker) chamava `extract_status_transitions_inline(raw)` no dict mapeado — `raw.get("changelog", {})` retornava `{}` sempre porque o key não existia. Resultado: lista vazia para toda issue.

**Por que escapou dos testes:** Os 10 testes em `test_inline_changelog_extraction.py` testavam `extract_status_transitions_inline` **isoladamente** contra dicts sintéticos que JÁ tinham `changelog`. O contrato entre `_map_issue` e o extractor nunca foi testado end-to-end.

**Solution** (commit `177830e`, 2026-04-29):

```python
return {
    "id": internal_id,
    # ... outros campos ...
    # FDD-OPS-013 — preserve raw changelog from `expand=changelog` so
    # extract_status_transitions_inline() in the sync worker can read it.
    "changelog": jira_issue.get("changelog", {}),
}
```

Test guard novo: `TestMapIssuePreservesChangelogForInlineExtraction` instancia o connector, alimenta payload Jira-shaped com `expand=changelog`, asserta que o pipe end-to-end (mapper → extractor) produz transitions não-vazias.

**Result:** Validado live no projeto BG: 1.994 issues re-sincados todos com 3-8 transitions normalizadas (BG-202188: 5 transitions; BG-202413: 3 transitions). Pré-fix: 0 transitions em 311k issues. Pós-fix: 100% das issues recém-tocadas carregam transitions.

**Lição genérica** — *cache lateral vs return value anti-pattern*:

> Connector mappers devem retornar **dados completos** no dict mapeado.
> Esconder dados em side caches (`self._last_*`) que outros call sites
> não conhecem é um anti-pattern. Quando outro path tenta acessar via
> "interface natural" (dict access), o dado está invisível mas o cache
> técnico-correto está silently populated.

Test pyramid lição: testar **contratos entre componentes**, não só cada componente isolado.

**SaaS Implication:** Padrão "connector retorna dados completos no return value" deve ser doc-policy ao adicionar conectores futuros (GitLab, ADO, Linear). E todo connector → worker pipe precisa de pelo menos 1 test end-to-end que use a SHAPE real da API source.

---

### Problem 12: Effort Estimation Without Story Points (Webmotors-style heterogeneity)

**Context:** Métricas como Velocity, Throughput-by-effort, Forecast Monte Carlo dependem de "esforço" agregado. Padrão da indústria: Story Points. Audit em 2026-04-28 (FDD-OPS-016 / INC-021): **`story_points = 0` em 100% das 311.007 issues** da Webmotors.

**Symptoms:**

- Sample em todos os 69 projetos ativos: `customfield_10004` ("Story Points") + `customfield_18524` ("Story point estimate") **0% populados**
- Webmotors **não usa Story Points** como método de estimativa (decisão organizacional)
- Velocity sempre zerada, throughput-by-effort impossível, forecast sem input

**Investigação em squads** (samples de 50 issues por projeto):

| Projeto | T-Shirt Size | Original Estimate (h) | Tamanho/Impacto | Padrão observado |
|---------|--------------|------------------------|------------------|--------|
| ENO     | 24%          | 52%                    | 4%               | Horas + tshirt |
| DESC    | 26%          | 34%                    | 6%               | Horas + tshirt |
| APPF    | 0%           | 12%                    | 0%               | Horas (raro) |
| OKM     | 4%           | 8%                     | 0%               | Quase Kanban |
| BG, FID, PTURB | 0%   | 0%                     | 0%               | **Kanban puro — não estimam** |

**Conclusão:** padrão heterogêneo entre squads — algumas usam horas, algumas T-shirt size, várias não estimam (Kanban-puro). Single-method approach não funciona.

**Solution** (commit `172f3f2`, 2026-04-29) — **Effort Fallback Chain**:

Discovery dinâmico em `_discover_custom_fields`:
- Casa por nome (case-insensitive) os patterns `"t-shirt size"` e `"tamanho/impacto"`
- Webmotors: descobriu `customfield_18762` ("T-Shirt Size") + `customfield_15100` ("Tamanho/Impacto")
- Funciona em qualquer tenant (não hardcode customfield IDs)

`_extract_story_points` (renomeado conceitualmente para "effort") com cadeia em ordem de prioridade:

```python
# 1+2. Native numeric Story Points (preferred — no conversion)
for field_id in (story_points_field_id, *FALLBACK_STORY_POINTS_FIELDS, "story_points"):
    if value > 0: return float(value)  # source: 'story_points'

# 3+4. T-shirt sized fields → Fibonacci scale
TSHIRT_TO_POINTS = {"PP": 1, "P": 2, "M": 3, "G": 5, "GG": 8, "GGG": 13,
                    "XS": 1, "S": 2, "L": 5, "XL": 8, "XXL": 13}
for fid in self._tshirt_field_ids:
    if (label := unwrap(fields[fid])) and (mapped := TSHIRT_TO_POINTS.get(label.upper())):
        return mapped  # source: 'tshirt_to_sp'

# 5. Original Estimate (seconds) → SP equivalent buckets
def _hours_to_points(h):
    if h <= 4:  return 1
    if h <= 8:  return 2  # ~1d
    if h <= 16: return 3  # ~2d
    if h <= 24: return 5
    if h <= 40: return 8  # ~1w
    if h <= 80: return 13 # ~2w
    return 21
# source: 'hours_to_sp'

# 6. None — issue genuinamente não estimada (Kanban-puro)
# source: 'unestimated'
# CONSUMER MUST count items rather than sum points
```

**Telemetria** (`_effort_source_counts`): por batched run, log da distribuição de qual hop produziu o valor. Operadores veem drift ("squad migrou de horas para t-shirt em maio") sem combar logs.

**Quando `None` (Kanban-puro):** decisão de **count vs sum** fica na camada de métrica, **não** no normalizer. Métrica downstream precisa contar items rather than sum points. Documentado em §8.12.

**Result:**

Validado live em CRMC (1.375 issues, projeto novo full-history pós-fix):
- **52,3% com effort estimado** (719/1.375)
- Distribuição de valores: 1, 2, 3, 5, 8 — confirma escala Fibonacci aplicada
- 47,7% com `story_points = None` → métrica counta items

**Future (codename "dev-metrics" R3+)** — FDD-DEV-METRICS-001:

Hoje a fallback chain é **automática e implícita**. Diferentes filosofias produzem métricas diferentes. R3 vai entregar:
- Per-squad estimation method choice (admin UI: SP / T-shirt / Hours / Count-only / Auto)
- Modelo proprietário de previsão e insights (drift detection, calibração contra histórico, Monte Carlo com método nativo)
- UX completa rescritta ao redor da escolha
- Anti-surveillance by design (insights por squad/processo, nunca individual)

**Diferenciador competitivo:** LinearB / Jellyfish / Swarmia / Athenian são opinionated em SP. PULSE é o **único** que respeita filosofia da squad e usa isso como entrada de modelo, não como ruído a normalizar.

**SaaS Implication:** Effort fallback chain é SaaS-ready (descoberta dinâmica). Para "dev-metrics" (R3+), precisa adicionar:
- Coluna `effort_source` em `eng_issues` (auditoria por issue)
- Migration deferred — registrado como prerequisite no FDD-DEV-METRICS-001

---

### Problem 13: Sprint Status Pipeline — 4-Layer Swiss Cheese

**Context:** 100% das 216 sprints no `eng_sprints` da Webmotors com `status=''`. `goal` também totalmente vazio. Audit (FDD-OPS-018 / INC-023, 2026-04-29) revelou clássico **swiss cheese alignment** — quatro bugs independentes em camadas diferentes, cada um sozinho garantindo o resultado.

**Symptoms:**

- `SELECT status, COUNT(*) FROM eng_sprints` → `('', 216)`
- Sprint Comparison / Velocity Trend não pode filtrar `closed` para excluir sprints em andamento da regressão
- "Current sprint" planejado precisa `status='active'` — impossível sem dado

**Os 4 bugs (cada um suficiente para causar o sintoma):**

| # | Camada | Bug | Como sozinho garantia status vazio |
|---|---|---|---|
| 1 | `connectors/jira_connector.py:_map_sprint` | Mapeava OK (ACTIVE/CLOSED/FUTURE) | (não era bug — fonte estava certa) |
| 2 | `engineering_data/normalizer.py:normalize_sprint` | Retornava dict **sem** o campo `status` | Status nunca chega no upsert |
| 3 | `workers/devlake_sync.py:_upsert_sprints` | ON CONFLICT `set_={...}` não incluía `status`/`goal` | Sprints existentes (que existem) nunca atualizam |
| 4 | `connectors/jira_connector.py:_fetch_board_sprints` | Filtrava `started_date < since` | State transitions acontecem em `endDate` — sprint que começou em março e fechou em maio nunca tem update após março |
| 5 | `engineering_data/models.py:EngSprint` | Schema da DB tinha `status` mas ORM SQLAlchemy não tinha o `Mapped[str\|None]` correspondente | **Path que omitia status funcionava silently empty; path que tentava popular crashava com `Unconsumed column names: status`** |

**Bug #5 (ORM schema drift) é o mais insidioso.** Coluna existia no DB há tempos (alguma migration anterior); ORM nunca foi atualizado. O sintoma é assimétrico: quem **omite** o campo passa silenciosamente; quem **inclui** crashar. Ninguém investiga porque "tá vazio mas não dá erro".

**Solution** (commit `649ed78`, 2026-04-29) — fix em todas as camadas:

1. `_map_sprint` agora também passa `goal` adiante (Jira API o retorna)
2. `normalize_sprint` inclui `status` (lowercase: `active`/`closed`/`future`/None) + `goal` (com strip null bytes)
3. `_upsert_sprints` ON CONFLICT `set_` atualiza ambos
4. `_fetch_board_sprints` removeu filtro de watermark (volume baixo, ~216 total / ~5 ativas; sempre re-fetch é correto pois state transitions)
5. `EngSprint` model adiciona `status: Mapped[str | None] = mapped_column(String(50), nullable=True)`

Helper `_normalize_sprint_status` mapeia aliases comuns:
- `open → active` · `in_progress → active`
- `completed/complete/ended → closed`
- `planned/upcoming → future`
- **Unknown values → None** (não bucketiza silenciosamente — operador investiga via NULL no DB)

**Por que NÃO bucketizar unknown:** Velocity / Carryover logic precisa saber QUAIS sprints estão de fato fechadas. Mapear "?" para `closed` corromperia o cálculo. Fail-loud é melhor que fail-silent aqui.

**Result:**

Validado live (ad-hoc backfill cobrindo 31 projetos ativos):

| Status | Quantidade | Tem goal? |
|---|---|---|
| `closed` | 187 | sim |
| `active` | 3 | sim |
| `future` | 5 | sim |
| (vazio) | 22 | board órfão 873 sem projeto ativo |

**195/217 = 89,9%** das sprints com status correto + 70% com goal real (e.g., "Gestão de banner no backoffice de CNC e TEMPO para novas especificações técnicas"). As 22 vazias são de board órfão, fora do escopo deste fix.

**Lição genérica — `Schema drift detection pattern`:**

> Adicionar guard test "DB columns vs ORM Mapped fields" — candidato a 5ª linha de defesa do FDD-OPS-001 (eliminação de drift).
> Migration review checklist deve incluir: toda nova coluna → Mapped column correspondente no SQLAlchemy.
> ORM drift é o tipo de bug onde "alguns paths funcionam, outros crashern" — não tem sintoma uniforme observável, então fica oculto até alguém tentar exatamente o path quebrado.

**SaaS Implication:** Sprint pipeline pós-fix está SaaS-ready. Para tenants futuros: discovery automático de boards Scrum (já existe), normalização lowercase consistente com convenção PULSE, fail-loud em status desconhecidos — operador onboarding vê NULL e investiga ao invés de receber dado silenciosamente errado.

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

#### 6.3.6 Effort Extraction (Deterministic Core + Discovery Fallback)

**Problem:** Story Points não são universais — Webmotors validou 0% de uso em 69 projetos. Squads usam métodos heterogêneos: T-shirt size (P/M/G), `timeoriginalestimate` em horas, ou nada (Kanban-puro). Single-method extraction quebra para esses tenants. Implementado em FDD-OPS-016 (commit `172f3f2`).

**Discovery dinâmico** (deterministic, zero-config):

```python
# JiraConnector._discover_custom_fields()
EFFORT_NAME_PATTERNS_TSHIRT = ("t-shirt size", "tshirt size", "tamanho/impacto")

for field in fields_list:
    name = field.get("name", "").strip().lower()
    fid = field.get("id", "")
    
    # Story Points (numeric)
    if name in ("story points", "story point estimate"):
        self._story_points_field_id = fid
    
    # T-shirt sized fields (option-typed)
    elif any(p in name for p in EFFORT_NAME_PATTERNS_TSHIRT):
        self._tshirt_field_ids.append(fid)
```

**Fallback chain (priority order):**

| # | Source | Conversão | Source label |
|---|---|---|---|
| 1 | `customfield_*` ("Story Points") | uso direto (numeric) | `story_points` |
| 2 | `customfield_*` ("Story point estimate") | uso direto | `story_points` |
| 3 | `customfield_*` ("T-Shirt Size") | mapa Fibonacci PP=1, P=2, M=3, G=5, GG=8, GGG=13 (PT-BR) ou XS/S/M/L/XL/XXL (EN) | `tshirt_to_sp` |
| 4 | `customfield_*` ("Tamanho/Impacto") | mesmo mapa | `tshirt_to_sp` |
| 5 | `timeoriginalestimate` (segundos) | buckets: ≤4h=1, ≤8h=2, ≤16h=3, ≤24h=5, ≤40h=8, ≤80h=13, >80h=21 | `hours_to_sp` |
| 6 | None | sem estimativa — **métrica downstream conta items (Kanban-puro)** | `unestimated` |

**Hour bucket calibration:** alinhado com "1 ideal day = ~6h productive". Buckets calibrados contra valores observados na Webmotors (2h–124h, múltiplos de 4) para que cada valor comum caia em um bucket sensato. Output já na escala SP que métricas downstream esperam.

**Skip SP = 0:** sentinel comum para "não estimado", trata como falta. Cai para próximo hop da chain ao invés de retornar `0.0`.

**Telemetria** (`_effort_source_counts`): incrementa contador por `source` label (incluindo `'unestimated'`). Logado per batched run:

```
[batched] effort source distribution (1375 issues): 
  tshirt_to_sp=521 (37.9%), hours_to_sp=198 (14.4%), unestimated=656 (47.7%)
```

Operadores spotam estimation drift sem combar logs.

**Anti-pattern evitado** — bucketização silenciosa de unknown values:

> Ao receber um T-shirt size desconhecido (ex: "JUMBO"), o connector
> NÃO mapeia silenciosamente para algum default. Cai para o próximo
> hop. Se nenhum produzir valor, retorna `None` com source label
> `'unestimated'`. Métrica downstream sabe que tem que counta items.

**SaaS Implication:** Já SaaS-ready. Cada tenant onboarda com:
1. Discovery automático de fields T-shirt e Tamanho via match de nome
2. Story Points classico funciona out-of-the-box se usado
3. `timeoriginalestimate` é Jira built-in (não custom field) — sempre disponível
4. Telemetria revela qual método o tenant usa nas primeiras horas pós-onboarding

**Future (FDD-DEV-METRICS-001 / codename "dev-metrics" R3+)** — promote esta cadeia automática a uma escolha **explícita por squad**:

- Admin UI permite escolher método: SP / T-shirt / Hours / Count-only / Auto (current)
- Modelo proprietário: detecta drift de estimativa, calibra contra histórico, surfaces insights ("squad marcando tudo como M há 6 sprints")
- Forecast Monte Carlo usa o método nativo do squad (não força SP como LinearB / Jellyfish / Swarmia / Athenian fazem)
- Anti-surveillance by design: insights por squad/processo, **nunca** individual

Pré-requisito (deferred): adicionar coluna `effort_source` em `eng_issues` para auditoria por issue.

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
| `5d71618` | Snapshot drift monitor (FDD-OPS-001 line 3) + deploy workflow |
| `0a1050c` | FDD-OPS-001 lines 1+2 — eliminate stale-code-in-workers drift |
| `dd10d34` | FDD-OPS-002 — full Jira description backfill (61.74% coverage) |
| `80f1796` | Partial index for snapshots — fixes 50× perf regression on `/metrics/home` |
| `c5e38bb` | docs(architecture): ingestion v2 — diagnostic + 10× target + migration path |
| `4d1c9b4` | FDD-OPS-012 + FDD-OPS-013 — Phase 1 v2: issues sync streams per-project + inline changelog (eliminates redundant `fetch_issue_changelogs`) |
| `62c183f` | Strip NULL bytes (0x00) from text fields before persist — Webmotors `ENO-3296` description had 0x00 |
| `4c2c1c5` | docs(ingestion): Phase 2 drafts — per-source workers + per-scope watermarks (FDD-OPS-014) |
| `c2c6e5d` | Phase 2 step 2.1 — apply scope_key migration |
| `a2d5850` | Phase 2 step 2.2 — per-scope watermark API |
| `f357d05` | Phase 2 step 2.3 — `_sync_issues` uses per-project watermarks |
| `15574a7` | Phase 2 steps 2.4 + 2.5 — per-repo watermark writes for PRs and deploys |
| `4f86fd2` | FDD-OPS-014 step 2.7 (urgent) — drop legacy `uq_watermark_entity` (Postgres enforces ALL UniqueConstraints; legacy blocked per-scope inserts) |
| `4478f13` | Phase 2-B step 2.4-B — read per-repo watermarks for PRs |
| `c628528` | Phase 2-B step 2.5-B — read per-repo watermarks for deployments |
| `177830e` | INC-020 / FDD-OPS-013 follow-up — preserve Jira changelog in `_map_issue` so inline extraction works (status_transitions=[] em 311k issues) |
| `172f3f2` | INC-021 / FDD-OPS-016 — effort estimation fallback chain (Story Points → T-shirt → Hours → None) + FDD-DEV-METRICS-001 placeholder for R3+ |
| `0c7124d` | INC-022 / FDD-OPS-017 — status normalization with `statusCategory.key` fallback (96.5% done skew + 50+ PT-BR statuses unmapped) |
| `649ed78` | INC-023 / FDD-OPS-018 — sprint status pipeline 4-layer cheese fix (normalizer + upsert + watermark + ORM drift) |

### D. Webmotors-Discovered Patterns (training material para futuros tenants)

Capturados durante a engenharia 2026-04 — servem como **base de comparação** quando onboardar novos tenants e como **alvo de discoveries automáticas** para o Ingestion Intelligence Agent (Section 6.5).

**D.1 — Estimação de esforço heterogênea entre squads:**

- Webmotors **não usa Story Points** (0% nos 69 projetos)
- Distribuição de método por squad sample:
  - Squads que estimam: ENO (52% horas + 24% T-shirt), DESC (34% horas + 26% T-shirt)
  - Squads que estimam pouco: APPF (12% horas), OKM (8% horas)
  - **Squads Kanban-puros** (não estimam): BG, FID, PTURB, e ~22 outros (25 de 27 squads totais)
- Fields descobertos: `customfield_18762` (T-Shirt: P/M/G), `customfield_15100` (Tamanho/Impacto: PP/P/M/G)
- **Implicação para futuros tenants:** rodar discovery por nome ("t-shirt", "tamanho", "size") e logar telemetria de método usado por squad. Provável que tenants Kanban-pesados tenham padrão similar.

**D.2 — Workflow status diversity:**

- 326 status definitions descobertos via `/rest/api/3/status`
- 104 status raw distintos populados em issues ativas
- DEFAULT_STATUS_MAPPING curado precisa de ~80 entries para cobrir granularidade `in_review` específica de PT-BR
- Resto cai no fallback `statusCategory.key` (autoritativo done/não-done)
- Padrões PT-BR observados:
  - "FECHADO EM PROD", "FECHADO EM HML", "Concluído", "Cancelado" → `done`
  - "Em Desenvolvimento", "Em imersão", "Em andamento", "Em Progresso" → `in_progress`
  - "Em Code Review", "Em Teste HML", "Homologação", "Aguardando Code Review" → `in_review`
  - "BACKLOG", "Refinado", "PAUSADO" → `todo`
- **Implicação:** mapping curado é por idioma + cultura organizacional. AI fallback (Section 6.4.2) deve aprender **por tenant** após primeiros 1k transitions observados.

**D.3 — Squad shape:**

- 27 squads ativos
- **25 são Kanban-puros** (sem sprints) — métricas Lean (CFD, Throughput, WIP, Cycle Time) são primárias
- 2 squads (FID, PTURB) usam Sprint — métricas Scrum (Velocity, Carryover) aplicam
- **Implicação:** UX padrão deve assumir Kanban-first. Sprint metrics aparecem condicionalmente quando `eng_sprints` tem dados ativos para a squad.

**D.4 — Repo & deploy scale:**

- 754 GitHub repos active / 1.429 total descobertos
- 283 repos com Jenkins config descoberto via SCM scan (commit `d1aebf7`)
- 577 PRD jobs auto-classificados por pattern matching
- 197.043 issues no projeto único BG (concentração extrema — single JQL retorna massive payload)
- **Implicação:** SaaS engine deve assumir distribuição power-law (alguns projetos enormes, muitos pequenos). Streaming per-project (P-1 do v2) é não-negociável.

**D.5 — Operational realities:**

- VPN drops causam silent failures sem health-aware orchestration (P-8)
- Project keys com palavras-reservadas SQL ("DESC") exigem quoting em JQL
- Orphan project keys em PR titles ("RC" tem 1.348 references sem Jira project) — alias resolution AI necessário (Section 6.4.5)
- NULL bytes (0x00) em descriptions PT-BR — `_strip_null_bytes` defensivo
- Jenkins SHAs são build IDs, não git SHAs — PR↔Deploy linking via temporal correlation, não SHA match

**D.6 — Anti-pattern de dev process descobertos:**

- **Cache lateral vs return value** (INC-020): connector mappers escondendo dados em `self._last_*` que outros call sites não acessam
- **Schema drift entre migration e ORM** (INC-023): coluna existe no DB mas SQLAlchemy `Mapped` ausente — paths que omitem campo passam, paths que incluem crashern
- **Swiss cheese alignment** (INC-023): feature inteira zerada por 4+ bugs independentes em camadas diferentes; cada um sozinho garantia o sintoma
- **Watermark filter dimension errado** (INC-023 #3): sprint state transitions em `endDate` não `startDate` — escolher dimensão correta de watermark é crítico
- **Bucketização silenciosa de unknown values**: anti-pattern. Sempre fail-loud (None/WARN) — operador investiga via NULL no DB

---

## 8. Metric Field Decisions — Master Table

Esta seção consolida **as decisões de qual timestamp/field é usado pra
cada métrica**, ancorando-se nos incidentes documentados em
`docs/metrics/metrics-inconsistencies.md`. Quando uma métrica produz
um número estranho, comece por aqui — provavelmente é decisão de
campo, não bug de código.

### 8.1 Lead Time for Changes (DORA)

**Fórmula canônica:** `deployed_at - first_commit_at` (em horas)

| Field | Source | Decisão | Referência |
|---|---|---|---|
| `eng_pull_requests.first_commit_at` | GitHub GraphQL `commits(first:1).authoredDate` | Real authored date do primeiro commit no branch — **NÃO** a data de abertura do PR | INC-003 fix 2026-04-17, commit `c5350dc` |
| `eng_pull_requests.deployed_at` | Temporal linking PR → Jenkins deploy via SHA matching | Populado por `link_pr_deploys()` quando deploy chega; null pra PRs sem deploy linkado | INC-004 fix 2026-04-17 |

**Variantes expostas pelo backend** (decisão FDD-DSH-082, 2026-04-17):

- `lead_time_for_changes_hours` (inclusive): inclui PRs sem `deployed_at` usando `merged_at` como fallback. Maior cobertura, mas não-canônico DORA.
- `lead_time_for_changes_hours_strict`: SOMENTE PRs com `deployed_at != NULL`. Canônico DORA. Cobertura menor (depende de Jenkins linking).
- Frontend mostra ambos em cards separados. Usuário escolhe a interpretação.

**Edge case**: PR aberto-e-fechado-sem-merge → excluído do cálculo (`is_merged = false`).

### 8.2 Cycle Time

**Fórmula:** `merged_at - first_commit_at` (em horas) — INC-007 fix 2026-04-17

**Phases breakdown** (`cycle_time/breakdown` snapshot):

| Phase | De | Para |
|---|---|---|
| `coding` | `first_commit_at` | `pr_opened_at` (created_at) |
| `pickup` | `pr_opened_at` | `first_review_at` |
| `review` | `first_review_at` | `merged_at` |
| `merge_to_deploy` | `merged_at` | `deployed_at` |

**Edge case INC-012 (parcial)**: `merge_to_deploy` é null quando
`deployed_at` é null. Stacked bar mostra 3 fases em vez de 4. Documentado
como aceitável até full Jenkins linking (depende de FDD-DSH-050).

### 8.3 Deployment Frequency

**Fórmula:** `count(eng_deployments WHERE environment='production' AND deployed_at IN [period])` por unidade de tempo

| Decisão | Referência |
|---|---|
| Filtro `environment='production'` (não staging/dev) | INC-008 fix 2026-04-17 |
| Source = jenkins (Webmotors) | `connections.yaml` |
| `is_failure` derivado de `result != 'SUCCESS'` no Jenkins build | normalizer `_extract_jenkins_result()` |
| **Aberto INC-016**: builds UNSTABLE (testes falham mas compila) contam como falha — comportamento mais rigoroso que padrão DORA, sem flag pra desabilitar | P2, aceitável |

### 8.4 Change Failure Rate

**Fórmula:** `count(deploys WHERE is_failure) / count(deploys)` no período

**Decisões:** mesmas de §8.3 (escopo de deploys idêntico).

### 8.5 MTTR (Mean Time to Recovery)

**Status:** ❌ **AINDA NÃO IMPLEMENTADO**

`recovery_time_hours` é always null (INC-005). Calculation function existe
e está correta, mas não há pipeline de incidents para alimentar. Card
"Time to Restore" mostra `null` + badge "R1" + tooltip explicativo.

Tracking: FDD-DSH-050 (P1, L, multi-agent — data scientist define sinal
de incidente → data engineer cria tabela `eng_incidents` → backend → frontend).

### 8.6 Throughput (PRs merged per period)

**Fórmula:** `count(PRs WHERE is_merged AND merged_at IN [period])`

| Decisão | Referência |
|---|---|
| Fetch por `merged_at` (não `created_at`) | INC-001 fix 2026-04-16 — antes, PRs com lifecycle longo eram subcontados |
| `pr_analytics.total_merged` no payload `throughput/pr_analytics` | usado por `/metrics/home` |
| Cycle time per-week sparkline computed inline | INC-007 fix |

### 8.7 WIP (Work in Progress)

**Fórmula:** `count(eng_issues WHERE normalized_status IN ('in_progress','in_review'))` no momento do snapshot

**Decisões importantes:**

- Status `todo` **excluído do WIP** — apenas trabalho tocado conta. Documentado em `kanban-formulas-v1.md` §2
- "aguardando deploy produção" mapeado pra `done` (INC-019 P2 — debatível, porém fixo no `connections.yaml` status_mapping)
- WIP é tenant-aggregate por default; per-squad é cálculo on-demand via `squad_key` query param

### 8.8 Lead Time Distribution / CFD / Scatterplot (Lean)

**Fonte de verdade:** `eng_issues` com `status_transitions` JSONB populado pelo Jira changelog.

| Métrica | Fórmula | Edge case |
|---|---|---|
| Lead Time Distribution | histograma de `completed_at - created_at` por bin | INC-010 fix 2026-04-16: inclui issues longas que stradle o período |
| CFD | contagem por status × dia, banda `done` usa `MAX(done_so_far)` | INC-009 P1 — protege contra reopens |
| Scatterplot | um ponto por issue concluída no período (P50/85/95 lines) | mesmo escopo de fetch que LT distribution |

### 8.9 Anti-Surveillance Invariant

**Decisão fundamental, INVIOLÁVEL:**

> Author/assignee/reporter **NUNCA** entram em payloads de métrica.

**Onde está garantido:**

1. **Domain dataclasses** (`pulse-data/src/contexts/metrics/domain/`): nenhum field tipo `author`, `assignee`, `reporter` ou similar
2. **Schema registry** (FDD-OPS-001 line 3): payload-vs-dataclass diff loga `_schema_drift` se algo nuevo aparece
3. **Frontend contract tests** (`tests/contract/anti-surveillance-schemas.test.ts`): meta-test que injeta payload tainted em cada um dos 6 schemas Zod e verifica rejeição
4. **Underlying tables** (`eng_pull_requests.author`, `eng_issues.assignee`) — campos existem (necessários pra ingestão e linking), mas **nunca atravessam a fronteira de aggregação**

**Snapshot anonimizado (PR #2.1 / future):** quando construirmos pipeline
de snapshot pra distribuir entre devs, aggregate-only não é suficiente —
o DB ainda tem PII nos raw fields. Anonimização determinística de
author/assignee → hash + `@example.invalid` é necessária. Detalhes em
`docs/onboarding.md` (PR #2.1).

### 8.10 Status Normalization (hybrid textual + statusCategory)

**Fonte primária:** hybrid em 3 camadas (FDD-OPS-017 / INC-022 / commit `0c7124d`):

1. **Textual mapping curado** — `DEFAULT_STATUS_MAPPING` em `engineering_data/normalizer.py`, ~80 entries PT-BR Webmotors-curated + EN. Preserva granularidade `in_progress` vs `in_review`.
2. **Jira `statusCategory.key` fallback** — autoritativo done/não-done. Connector descobre via `/rest/api/3/status` (1 chamada/lifetime, cacheada). Webmotors: 326 status defs descobertas.
3. **Default 'todo' com WARN log** — extremamente raro pós-fix (só status sem categoria).

**Categorias normalizadas produzidas:** `todo | in_progress | in_review | done` (4 categorias). Métricas downstream em `domain/lean.py:_ACTIVE_STATUSES = {"in_progress", "in_review"}` tratam ambos como WIP/active para Cycle Time.

**Discovery cacheado por instância de connector:**

```python
# JiraConnector
self._status_categories: dict[str, str] = {}  # name (lowercase) → category key
self._status_categories_discovered: bool = False

async def _discover_status_categories(self):
    data = await self._client.get(f"{REST_API}/status")
    for s in data:
        name = (s.get("name") or "").strip().lower()
        cat = ((s.get("statusCategory") or {}).get("key") or "").strip().lower()
        if name and cat in ("new", "indeterminate", "done"):
            self._status_categories[name] = cat
```

**`_map_issue` anexa ao dict mapeado:**

- `status_category`: a categoria do status atual
- `status_categories_map`: o dict completo (mesma referência para todas as issues do batch)

**Histórico (`build_status_transitions`)** usa o `status_categories_map` para classificar cada `to_status` histórica:

```python
for cl in changelogs:
    cat = status_categories_map.get(cl["to_status"].strip().lower())
    normalized = normalize_status(cl["to_status"], status_mapping, cat)
```

**Edge cases conhecidos & decisões:**

| Status | Mapping | Justificativa |
|---|---|---|
| `FECHADO EM PROD` | `done` | Jira category=done; nome literal "FECHADO" |
| `FECHADO EM HML` | `done` | Jira category=done. Workflow author classifica como done; respeitamos. Se squad quer "ainda em fluxo", renomeia para "Aguardando Deploy Produção" |
| `aguardando deploy produção` | `in_progress` | INC-019 P2 reverso — quando deploy é o gargalo, item ainda está em fluxo |
| `em teste azul/hml` | `in_review` | Webmotors-specific QA stages; granularidade preservada via textual |
| `construção de hipótese` | `in_progress` | Kanban upstream — trabalho ativo de discovery |
| `Aguardando Code Review` | `in_review` | Trabalho ativo aguardando reviewer (textual ganha sobre Jira `new` neste tenant) |
| Status sem mapping E sem category | `todo` (com WARN log) | Conservador — operador investiga via WARN |

**Princípio**: textual ganha quando definido (granularidade); category ganha sobre default (autoridade). Tudo que cai em "todo" sem ambos é log-visible — raro, mas observável.

**Por que mantemos 4 categorias (não 3 como Jira)** — métricas Lean precisam distinguir `in_progress` (development active) de `in_review` (waiting on review/test) para Cycle Time Breakdown. Jira `statusCategory.indeterminate` colapsa os dois; nosso textual mapping preserva quando a squad nomeia.

### 8.11 PR ↔ Issue Linking

**Mecanismo:** regex `[A-Z][A-Z0-9]+-\d+` em `pr.title`, `pr.head_ref`, `pr.base_ref`

**Sequência:**

1. Sync worker carrega `(issue_key, external_id)` do tenant **antes** de sincronizar PRs (issues vêm 1º no ciclo)
2. Pra cada PR, regex extrai possíveis keys (multi-match suportado)
3. Filtra keys que existem em `jira_project_catalog` com status `active|discovered`
4. Popula `linked_issue_ids` JSONB do PR

**Per-project link rate observado** (Webmotors, post-discovery):

- Top performers (96-100%): SDI, PUSO, DSP, FID, CRMC
- Tenant-wide médio: 21.9%
- Falsos positivos: HOTFIX-123, RELEASE-1, BUGFIX-42, lib names (LODASH-4) — filtrados via `IN (jira_project_catalog)` clause
- Orphans conhecidos: RC (1348 references, projeto archived no Jira)

**Re-relink pós-ingestão:** script `scripts/relink_prs_to_issues.sql`
re-aplica em PRs antigos quando novos projetos são ativados via discovery
dinâmica.

### 8.12 Effort Estimation (story_points field)

**Fonte primária:** `eng_issues.story_points` (numeric, nullable) — populado pelo `_extract_story_points` no connector via fallback chain (FDD-OPS-016 / INC-021 / commit `172f3f2`). Detalhes na §6.3.6.

**Hops em ordem de prioridade** (telemetria via `_effort_source_counts`):

| Hop | Source | Conversão | Source label |
|---|---|---|---|
| 1 | `customfield_10004` ("Story Points") | numeric direto (skip se = 0) | `story_points` |
| 2 | `customfield_18524` ("Story point estimate") | numeric direto | `story_points` |
| 3 | T-shirt size field (discovered) | Fibonacci: PP=1, P=2, M=3, G=5, GG=8, GGG=13 | `tshirt_to_sp` |
| 4 | `customfield_15100` ("Tamanho/Impacto") | mesmo mapa | `tshirt_to_sp` |
| 5 | `timeoriginalestimate` (segundos) | buckets ≤4h=1, ≤8h=2, ≤16h=3, ≤24h=5, ≤40h=8, ≤80h=13, >80h=21 | `hours_to_sp` |
| 6 | None | `null` em `eng_issues.story_points` | `unestimated` |

**Decisão downstream — quando `story_points IS NULL`:**

- Métricas baseadas em soma (Velocity, Story Point Throughput): **NÃO somar** issues `null`
- Métricas baseadas em count (Throughput by issue, WIP, Cycle Time): **incluir** issues `null` normalmente
- **Para tenants Kanban-puros** (Webmotors: 25/27 squads), `story_points` é `null` para 100% — **a métrica primária deve ser count, não sum**

**Anti-pattern evitado:**

> NÃO defaultar para `story_points = 1` (ou outro valor sentinel)
> quando não há estimativa. Seria silently wrong para Velocity.
> Métrica precisa saber explicitamente que aquela issue não foi
> estimada. `null` é fail-loud (NULL no DB visível) vs `1` que é
> fail-silent.

**Webmotors-observed coverage** pós-fix (CRMC, projeto novo full-history):

- 52,3% com effort estimado (sample de 1.375 issues)
- Distribuição valores: 1, 2, 3, 5, 8 (Fibonacci aplicado)
- 47,7% `null` → métrica conta items

**Future:** R3 codename "dev-metrics" (FDD-DEV-METRICS-001) entrega:
- Coluna `effort_source` em `eng_issues` para auditoria por issue
- Per-squad estimation method choice (admin UI)
- Modelo proprietário de previsão usando método nativo do squad

### 8.13 Sprint Status & Goal

**Fonte primária:** `eng_sprints.status` (varchar(50), nullable) + `eng_sprints.goal` (text, nullable). Populados pelo `normalize_sprint` (FDD-OPS-018 / INC-023 / commit `649ed78`).

**Status normalization:**

| Raw value (Jira) | Aliases aceitos | Normalized |
|---|---|---|
| ACTIVE | active, open, in_progress | `active` |
| CLOSED | closed, completed, complete, ended | `closed` |
| FUTURE | future, planned, upcoming | `future` |
| (qualquer outro) | — | `None` (fail-loud, operador investiga) |

**Por que NULL para unknown** (não bucketizar): Sprint Velocity e Carryover logic precisam saber QUAIS sprints estão de fato fechadas. Bucketizar "?" para `closed` corromperia a regressão linear de tendência. NULL torna o problema visível.

**Goal field:**

- Source: `sprint.goal` da Jira API (string, free-text setado por squad lead)
- Normalizer aplica `_strip_null_bytes` (Postgres rejeita 0x00)
- Webmotors observed: 70% das sprints têm goal real (e.g., "Gestão de banner no backoffice de CNC e TEMPO para novas especificações técnicas")

**Re-fetch policy crítica** — sprints **não usam watermark filter** (decisão de FDD-OPS-018):

- State transitions acontecem em `endDate`, não `startDate`
- Volume baixo (~216 total / ~5 ativas em qualquer momento)
- Sempre re-fetch é correto E barato
- Se quiser otimizar no futuro: filtrar por `endDate < since` (não `startDate`)

**ON CONFLICT update obrigatório:**

```python
# _upsert_sprints
.on_conflict_do_update(
    index_elements=["tenant_id", "external_id"],
    set_={
        "name": sd["name"],
        "status": sd.get("status"),       # FDD-OPS-018: era omitido
        "goal": sd.get("goal"),           # FDD-OPS-018: era omitido
        "started_at": sd["started_at"],
        "completed_at": sd["completed_at"],
        # ... outros campos métricos
        "updated_at": datetime.now(timezone.utc),
    },
)
```

**Lição** — quando o ON CONFLICT `set_` omite um campo, sprints existentes nunca recebem update mesmo se o normalizer está correto. Pattern: `set_` deve incluir TODOS os campos que podem mudar entre syncs, exceto `external_id` e `tenant_id`.

---
