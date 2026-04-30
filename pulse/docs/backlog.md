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

---

## Data Gaps — Master Index (audit 2026-04-30)

> **Para o agente**: cada item abaixo é um gap de dados conhecido com cross-ref para
> a fonte autoritativa (INC catalog, FDD-OPS-*, ingestion-spec section, ou
> kanban-metrics-backlog sequence). Quando o usuário pedir "próximos passos",
> "o que está faltando", "data quality" — surface esta tabela. Updates de
> coverage devem refletir aqui (não criar duplicatas em outros arquivos).
>
> Coverage tenant-wide atual (Webmotors, 311.190 issues / 63k PRs / 1.376 deploys / 217 sprints):
> - `status_transitions`: **54%** (alvo: ~90%, blocked por FDD-OPS-019 BG short-fetch)
> - `story_points` (effort): **3,7%** (Webmotors 25/27 squads são Kanban-puros — esperado baixo)
> - `priority` em issues: **0%** (INC-026 — campo não populado)
> - `url`/`closed_at` em PRs: **0%** (INC-025)
> - `trigger_type`/`url`/`trigger_ref` em deploys: **0%** (INC-024)
> - `linked_pr_ids` em issues: **0%** (INC-027)
> - `recovery_time_hours` em deploys: **0%** (INC-005, MTTR pipeline ausente)
> - `deployed_at` em PRs: **~40%** (limitado por Jenkins repo coverage)
> - PR↔Issue link rate: **5%** pós-reset (recovering, target ~22%)
> - Issue descriptions: **~43%** (FDD-OPS-002 backfill scope='all' pendente, teto realista ~70%)
> - Sprint status: **89,9%** (22/217 board órfão, fora de escopo)

### 🔴 ALTO IMPACTO — bloqueia métrica-chave ou tem visibilidade direta

| # | Gap | Source autoritativa | Status |
|---|---|---|---|
| 1 | MTTR / `recovery_time_hours` sempre NULL — DORA overall incompleto | [INC-005](metrics/metrics-inconsistencies.md) + FDD-DSH-050 | Bloqueador R1 |
| 2 | Scope Creep / `added_items`/`removed_items` sempre 0 | [INC-006](metrics/metrics-inconsistencies.md) | P0 documentado |
| 3 | Per-team snapshots ausentes (worker não computa por `team_id`) | [INC-015](metrics/metrics-inconsistencies.md) | P1 — squad filter ineficaz |
| 4 | BG ~72k issues missing após backfill (JQL pagination cap) | [FDD-OPS-019](backlog/ops-backlog.md) | OPEN — investigation plan |
| 5 | `deployed_at` coverage só 40% (Jenkins prod mapping) | [INC-004](metrics/metrics-inconsistencies.md) (✅ Fixed for mapped repos) | Limit configuracional |
| 6 | Issue descriptions backfill ~43% (FDD-OPS-002 scope='all' pendente) | [FDD-OPS-002](backlog/ops-backlog.md) ✅ DONE / 🔴 backfill stale | Operational task |

### 🟡 MÉDIO IMPACTO — schema correto, normalizer não popula (real bugs)

| # | Gap | Source autoritativa | Quick-win? |
|---|---|---|---|
| 7 | `eng_deployments.trigger_type/trigger_ref/url` NULL — investigation cega | [INC-024](metrics/metrics-inconsistencies.md) | **S** (Jenkins API tem dados) |
| 8 | `eng_pull_requests.url/closed_at` NULL — drill-down sem link | [INC-025](metrics/metrics-inconsistencies.md) | **XS** (2 linhas no normalizer) |
| 9 | `eng_issues.priority` NULL — priority-based segmentação inviável | [INC-026](metrics/metrics-inconsistencies.md) | **XS** (1 linha no normalizer) |
| 10 | `eng_issues.linked_pr_ids` vazio — reverse lookup PR↔Issue | [INC-027](metrics/metrics-inconsistencies.md) | **S** (post-link SQL UPDATE) |
| 11 | PR↔Issue link rate em recovery (5% pós-reset, target ~22%) | Item #4 desta seção do backlog.md | Auto-recovery via incremental |
| 12 | Custom fields além de T-shirt (severity, complexity) — discovery limitada | [FDD-OPS-016](backlog/ops-backlog.md) follow-up | Extension da fallback chain |

### 🟢 BAIXO IMPACTO — edge cases / aceitável para R1

| # | Gap | Source autoritativa |
|---|---|---|
| 13 | Sprint status 22 vazias (board órfão 873) | [INC-023](metrics/metrics-inconsistencies.md) (✅ Fixed essencialmente) — 89,9% coverage |
| 14 | `first_commit_at` histórico (~10% PRs antigas sem commit date real) | [INC-003](metrics/metrics-inconsistencies.md) ✅ Fixed; backfill `scope=stale` pendente |
| 15 | Orphan project keys (RC: 1.348 PR refs sem projeto Jira) | [ingestion-spec.md §6.4.5](ingestion-spec.md) — AI alias resolver |
| 16 | Jenkins coverage 126/390 repos com prod jobs mapeados | [ingestion-spec.md §6.4.1](ingestion-spec.md) — AI job classifier |

### ⚪ ESTRUTURAL — release futura

| # | Gap | Release | Source |
|---|---|---|---|
| 17 | Blocked time / workflow status tracking | R2 | [kanban-metrics-backlog.md Seq 3](backlog/kanban-metrics-backlog.md) |
| 18 | `effort_source` column em `eng_issues` (auditoria de método de estimativa) | R3 | Pré-req [FDD-DEV-METRICS-001](backlog/ops-backlog.md) |
| 19 | AI fallback para status desconhecidos (quando textual + statusCategory falham) | R3 | [ingestion-spec.md §6.4.2](ingestion-spec.md) |
| 20 | AI repository-to-project mapping | R3 | [ingestion-spec.md §6.4.3](ingestion-spec.md) |

### Top 5 quick-wins (recomendado próximo)

| Quick-win | Esforço | Impacto |
|---|---|---|
| **#9** populate `priority` no `normalize_issue` | XS (1 linha) | Habilita priority-based segmentation imediato |
| **#8** populate `url`/`closed_at` no `normalize_pull_request` | XS (2 linhas) | Drill-down PR funcional |
| **#7** populate `trigger_type/url/trigger_ref` no `normalize_deployment` | S | Observability + investigation deploys |
| **#14** rodar backfill `first_commit_at scope=stale` | XS (1 curl) | +10% coverage Lead Time histórico |
| **#6** rodar backfill descriptions `scope=all` | M (~30min run) | +20% description coverage (43% → 63%) |

### Update protocol (quem mantém esta tabela)

- **Adicionar gap novo**: criar entrada em `metrics-inconsistencies.md` (INC-XXX) ou
  `ops-backlog.md` (FDD-OPS-XXX), depois adicionar referência aqui. Não duplicar conteúdo.
- **Coverage mudou**: atualizar header (`status_transitions: 54%` etc.) refletindo
  panorama atual.
- **Gap fechado**: marcar com ✅ + commit sha do fix, mantém na tabela como
  histórico até a próxima audit cleanup.
- **Última audit**: 2026-04-30 — pós backfill comprehensive issues.

