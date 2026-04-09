# Feature Spec: Pipeline Monitor Dashboard

**Feature Set:** MVP-1.7 (Epico 1 -- Data Pipeline)
**Status:** Draft
**Author:** Product Director Agent
**Date:** 2026-04-07
**Version:** 1.0

---

## 1. Problem Statement

PULSE has a four-stage data pipeline: **Source (Jira/GitHub)** --> **DevLake Collection** --> **Sync Worker** --> **Metrics Worker**. Today there is zero visibility into this pipeline. Users only discover problems when metrics stop updating or show stale data. Carlos (EM) opens the DORA dashboard, sees metrics from 3 days ago, and has no idea whether the pipeline is broken, slow, or simply idle. He has no recourse other than checking logs -- which he should never need to do.

This is a trust problem. If users cannot see that the pipeline is healthy, they cannot trust the metrics. And metrics without trust have zero value.

### Who Feels This Pain

| Persona | Scenario | Impact |
|---------|----------|--------|
| **Carlos** (EM) | Opens DORA dashboard, sees `calculated_at: 3 days ago`. Is the system broken? Is there no data? He has no way to know. | Loses trust in metrics, stops using PULSE |
| **Ana** (CTO) | Asks "Are all teams connected and flowing data?" before an exec review. No answer available. | Cannot use PULSE for decision-making |
| **Priya** (Agile Coach) | Notices CFD looks wrong. Wants to know if Jira issues are being synced correctly. Cannot inspect. | Blames PULSE instead of investigating data quality |

### Value Proposition

> "One glance at pipeline health means I can trust every metric on every other page."

The Pipeline Monitor is not a feature users will stare at daily. It is a **trust signal** -- a page they check once when something looks off, and that presence alone increases confidence in the entire platform. Think of it as the "engine light" for PULSE.

---

## 2. Design Principles

1. **Read-only, always.** This dashboard reads status from DevLake API, PULSE DB counts, Kafka consumer lag, and worker state. It NEVER triggers pipelines, retries, or writes to any external system.
2. **Team-level, never individual.** Pipeline health is about the system, not about who broke it.
3. **One glance, one answer.** The primary question is: "Is data flowing?" The answer should be visible in under 2 seconds.
4. **Progressive disclosure.** Top level = 4 stage cards with status. Click/expand = detailed counters, errors, history.

---

## 3. Information Architecture

### Placement

The Pipeline Monitor lives as a **section within the existing `/integrations` page**, accessible via a tab or anchor scroll. The URL becomes `/integrations` with two visual sections:

- **Connections** (existing) -- Source-level cards showing GitHub, Jira, etc.
- **Pipeline Health** (new) -- The four-stage flow visualization with status and counters.

This avoids creating a new nav item for an MVP feature while keeping the information architecturally coherent: "Integrations" is already where users go to understand data source health.

### Navigation Change

No sidebar change needed. The existing "Integrations" link gains richer content.

---

## 4. Status Taxonomy

Generic statuses like "processing" or "active" are not actionable. The pipeline monitor uses a **semantic status model** where each status tells the user what is happening and what to expect:

### Stage Statuses

| Status | Visual | Meaning | User Action |
|--------|--------|---------|-------------|
| `healthy` | Green dot, steady | Last cycle completed successfully, within expected schedule | None needed |
| `running` | Blue dot, animated pulse | Currently executing a sync/calculation cycle | Wait; system is working |
| `stale` | Yellow dot | Last successful run was more than 2x the expected interval (e.g., >30min for a 15min cycle) | Investigate; may need restart |
| `error` | Red dot | Last cycle failed with an error | Check error details panel |
| `idle` | Gray dot | No data has ever been processed (first-run or unconfigured) | Verify configuration |
| `degraded` | Orange dot | Partially working -- some entities succeeded, others failed | Check per-entity breakdown |

### Overall Pipeline Status

Derived from the four stage statuses using worst-status-wins:
- All `healthy` --> Pipeline `healthy`
- Any `running` (none `error`) --> Pipeline `running`
- Any `stale` (none `error`) --> Pipeline `stale`
- Any `error` --> Pipeline `error`
- All `idle` --> Pipeline `idle`

---

## 5. Visualization Specification

### 5.1 Pipeline Flow Diagram (Hero Component)

A horizontal four-stage flow diagram, inspired by CI/CD pipeline visualizations (GitLab CI, GitHub Actions), but adapted for a data pipeline context.

```
  [Source]  ------>  [DevLake]  ------>  [Sync Worker]  ------>  [Metrics Worker]
   Jira/GH           Collection          Normalize/Upsert        Calculate/Write

   (green)   ---->    (blue)    ---->      (green)       ---->      (green)
   3 active          Running             847 records              12 snapshots
   0 errors          Task 3/5            last: 2min ago           last: 2min ago
```

**Layout:**
- Four cards arranged horizontally (responsive: stack vertically on mobile)
- Animated connecting arrows between stages (CSS animation, dashed line with flowing dots when `running`)
- Arrow color matches the source stage status
- Each card: icon + stage name + status badge + key metric + sub-detail

**Stage Card Contents:**

| Stage | Icon | Primary Metric | Secondary Detail |
|-------|------|----------------|------------------|
| Source | Plug icon | `{N} connections active` | Per-source breakdown (2 GitHub, 1 Jira) |
| DevLake Collection | Database icon | `{status}` or `Task {N}/{total}` | Current pipeline name, started at, duration |
| Sync Worker | Refresh icon | `{N} records synced` | Per-entity: PRs, Issues, Deploys, Sprints + last cycle timestamp |
| Metrics Worker | Calculator icon | `{N} snapshots written` | Per-metric-type: DORA, Lean, CycleTime, Throughput, Sprint + last calc timestamp |

### 5.2 Record Counters Panel

Below the flow diagram, a summary table showing record counts across the pipeline:

```
Entity          | DevLake   | PULSE DB  | Last Synced       | Kafka Lag
Pull Requests   |    1,247  |    1,243  | 2 min ago         | 4
Issues          |    3,891  |    3,891  | 2 min ago         | 0
Deployments     |      156  |      156  | 2 min ago         | 0
Sprints         |       24  |       24  | 2 min ago         | 0
```

- **DevLake count:** `SELECT COUNT(*) FROM pull_requests` (via DevLake reader)
- **PULSE DB count:** `SELECT COUNT(*) FROM eng_pull_requests WHERE tenant_id = ?`
- **Last Synced:** From watermark or `MAX(updated_at)` on PULSE DB tables
- **Kafka Lag:** Consumer group offset lag (available via Kafka admin client)

A mismatch between DevLake and PULSE DB counts is a signal of sync issues. Highlight rows where `devlake_count - pulse_count > threshold` in yellow.

### 5.3 Error Panel

A collapsible panel (collapsed by default) that shows recent errors:

```
Errors (2)                                              [Expand v]

  [!] Sync Worker - Issues       3 min ago
      sqlalchemy.exc.IntegrityError: duplicate key value violates
      unique constraint "uq_eng_issue_tenant_external"
      Affected: issue BACK-1234

  [!] DevLake - collectChangelogs    15 min ago
      HTTP 429 Too Many Requests from Jira API
      Blueprint: pulse-jira-sync, Task: collectChangelogs
```

- Shows the last N errors (default 10)
- Includes stage, timestamp, error message (first 200 chars), and context
- No stack traces exposed (security) -- only business-relevant error info
- Errors are team-level, never attributed to individual developers

### 5.4 Sync History Timeline (Stretch)

A small sparkline or mini-timeline showing the last 24h of sync cycles:

```
Sync History (24h)
|..||||.|||||||.||||||.||||||||..||||..|
 ^errors    ^gaps           ^normal
```

Each tick = one sync cycle. Color = status. This gives at-a-glance pattern recognition (e.g., "errors started 6h ago").

---

## 6. Data Sources and API Design

### 6.1 New API Endpoint

```
GET /data/v1/pipeline/status
```

**Response Schema:**

```json
{
  "overall_status": "healthy",
  "stages": {
    "source": {
      "status": "healthy",
      "connections": [
        {
          "name": "GitHub - acme-corp",
          "source": "github",
          "status": "active",
          "repos_monitored": 5,
          "last_sync_at": "2026-04-07T14:30:00Z"
        }
      ],
      "active_count": 3,
      "error_count": 0
    },
    "devlake": {
      "status": "healthy",
      "current_pipeline": null,
      "last_pipeline": {
        "id": 42,
        "status": "TASK_COMPLETED",
        "started_at": "2026-04-07T14:15:00Z",
        "finished_at": "2026-04-07T14:18:32Z",
        "duration_seconds": 212,
        "tasks_total": 5,
        "tasks_completed": 5,
        "tasks_failed": 0
      },
      "blueprints_active": 2
    },
    "sync_worker": {
      "status": "healthy",
      "last_cycle": {
        "started_at": "2026-04-07T14:18:35Z",
        "finished_at": "2026-04-07T14:19:12Z",
        "duration_seconds": 37,
        "results": {
          "pull_requests": 12,
          "issues": 45,
          "deployments": 3,
          "sprints": 0
        }
      },
      "watermarks": {
        "pull_requests": "2026-04-07T14:18:35Z",
        "issues": "2026-04-07T14:18:35Z",
        "deployments": "2026-04-07T14:18:35Z",
        "sprints": "2026-04-07T14:18:35Z"
      }
    },
    "metrics_worker": {
      "status": "healthy",
      "last_calculation_at": "2026-04-07T14:19:15Z",
      "snapshots_by_type": {
        "dora": { "count": 4, "last_at": "2026-04-07T14:19:15Z" },
        "lean": { "count": 20, "last_at": "2026-04-07T14:19:14Z" },
        "cycle_time": { "count": 8, "last_at": "2026-04-07T14:19:13Z" },
        "throughput": { "count": 8, "last_at": "2026-04-07T14:19:12Z" },
        "sprint": { "count": 2, "last_at": "2026-04-07T14:19:10Z" }
      }
    }
  },
  "record_counts": {
    "pull_requests": { "devlake": 1247, "pulse_db": 1243, "kafka_lag": 4 },
    "issues": { "devlake": 3891, "pulse_db": 3891, "kafka_lag": 0 },
    "deployments": { "devlake": 156, "pulse_db": 156, "kafka_lag": 0 },
    "sprints": { "devlake": 24, "pulse_db": 24, "kafka_lag": 0 }
  },
  "recent_errors": [
    {
      "stage": "sync_worker",
      "entity": "issues",
      "timestamp": "2026-04-07T14:16:00Z",
      "message": "IntegrityError: duplicate key on eng_issues",
      "context": { "issue_key": "BACK-1234" }
    }
  ]
}
```

### 6.2 Data Source Mapping

| Response Field | Source | Read Method |
|----------------|--------|-------------|
| `stages.source.connections` | `connections.yaml` + DevLake connection test API | `GET /plugins/{plugin}/connections/{id}/test` (read-only) |
| `stages.devlake.last_pipeline` | DevLake REST API | `GET /pipelines?page=1&pageSize=1` (read-only) |
| `stages.devlake.current_pipeline` | DevLake REST API | `GET /pipelines?status=TASK_RUNNING` (read-only) |
| `stages.sync_worker.last_cycle` | **New:** `pipeline_sync_log` table in PULSE DB | `SELECT * FROM pipeline_sync_log ORDER BY started_at DESC LIMIT 1` |
| `stages.sync_worker.watermarks` | **New:** `pipeline_watermarks` table (replaces in-memory `_WATERMARKS` dict) | `SELECT * FROM pipeline_watermarks WHERE tenant_id = ?` |
| `stages.metrics_worker` | `metrics_snapshots` table | `SELECT metric_type, COUNT(*), MAX(calculated_at) FROM metrics_snapshots GROUP BY metric_type` |
| `record_counts.devlake` | DevLake DB (read-only) | `SELECT COUNT(*) FROM pull_requests` (via DevLakeReader) |
| `record_counts.pulse_db` | PULSE DB | `SELECT COUNT(*) FROM eng_pull_requests WHERE tenant_id = ?` |
| `record_counts.kafka_lag` | Kafka AdminClient | Consumer group offset lag query |

### 6.3 New Database Tables

**`pipeline_sync_log`** -- Persisted sync cycle history (replaces ephemeral logging)

```sql
CREATE TABLE pipeline_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          VARCHAR(32) NOT NULL,  -- running | completed | failed | partial
    pull_requests   INTEGER DEFAULT 0,
    issues          INTEGER DEFAULT 0,
    deployments     INTEGER DEFAULT 0,
    sprints         INTEGER DEFAULT 0,
    error_message   TEXT,
    error_details   JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_sync_log_tenant_started ON pipeline_sync_log(tenant_id, started_at DESC);
```

**`pipeline_watermarks`** -- Persistent watermarks (replaces in-memory `_WATERMARKS` dict)

```sql
CREATE TABLE pipeline_watermarks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    entity      VARCHAR(64) NOT NULL,  -- pull_requests | issues | deployments | sprints
    watermark   TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, entity)
);
```

---

## 7. FDD User Stories -- Backlog MVP-1.7

### MVP-1.7.1 -- Persistir watermarks do Sync Worker no banco

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.1 |
| **User Story** | Como sistema, preciso persistir os watermarks do Sync Worker no banco de dados (tabela `pipeline_watermarks`) em vez de manter em memoria, para que o estado de sync sobreviva restarts e fique disponivel para consulta pela API. |
| **Acceptance Criteria** | DADO que o Sync Worker completa um ciclo de sync de pull_requests QUANDO o watermark e atualizado ENTAO o registro em `pipeline_watermarks` para entity="pull_requests" reflete o novo timestamp E o watermark persiste apos restart do worker. DADO que a tabela `pipeline_watermarks` nao tem registro para uma entity QUANDO o Sync Worker inicia ENTAO ele assume `since=NULL` (full sync) e cria o registro apos o primeiro ciclo. |
| **Complexidade** | Baixa |
| **Impacto** | Habilita MVP-1.7.3 e MVP-1.7.5. Corrige bug atual onde restart do worker causa re-sync completo. |
| **Escopo tecnico** | Migracao Alembic para `pipeline_watermarks`. Refatorar `_WATERMARKS` dict em `devlake_sync.py` para usar DB. |

---

### MVP-1.7.2 -- Persistir historico de ciclos do Sync Worker

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.2 |
| **User Story** | Como sistema, preciso registrar cada ciclo de sync (inicio, fim, status, contagens por entidade, erros) na tabela `pipeline_sync_log`, para que o historico fique disponivel para a API e para diagnostico. |
| **Acceptance Criteria** | DADO que o Sync Worker inicia um ciclo QUANDO o metodo `sync()` e chamado ENTAO um registro e inserido em `pipeline_sync_log` com `status='running'`. DADO que o ciclo completa com sucesso QUANDO todos os entity syncs finalizam ENTAO o registro e atualizado com `status='completed'`, contagens por entidade, e `finished_at`. DADO que o ciclo falha com excecao QUANDO ocorre um erro nao-tratado ENTAO o registro e atualizado com `status='failed'`, `error_message`, e `error_details` (JSON com traceback sanitizado, sem dados sensiveis). DADO que alguns entities falham mas outros nao QUANDO issues falha mas PRs succeeds ENTAO o registro tem `status='partial'` com contagens parciais. |
| **Complexidade** | Media |
| **Impacto** | Habilita MVP-1.7.5 e MVP-1.7.7. Fornece dados para o timeline de historico. |
| **Escopo tecnico** | Migracao Alembic para `pipeline_sync_log`. Wrap `sync()` com log escritor. Sanitizar error details (sem tokens, sem dados PII). |

---

### MVP-1.7.3 -- API endpoint de status do pipeline

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.3 |
| **User Story** | Como EM (Carlos), quero acessar `GET /data/v1/pipeline/status` para obter o status consolidado das 4 etapas do pipeline, contagens de registros, e erros recentes, para poder diagnosticar problemas de dados sem precisar acessar logs. |
| **Acceptance Criteria** | DADO que o pipeline esta saudavel QUANDO acesso `GET /data/v1/pipeline/status` ENTAO recebo JSON com `overall_status: "healthy"` e status por etapa (source, devlake, sync_worker, metrics_worker). DADO que o DevLake esta executando um pipeline QUANDO acesso o endpoint ENTAO `stages.devlake.status` e "running" com detalhes do pipeline corrente (tasks total/completed). DADO que o Sync Worker completou ha mais de 30 minutos QUANDO acesso o endpoint ENTAO `stages.sync_worker.status` e "stale". DADO que ha erros recentes QUANDO acesso o endpoint ENTAO `recent_errors` contem os ultimos 10 erros com stage, timestamp, e mensagem (sem stack traces completos). DADO que DevLake tem 1247 PRs e PULSE DB tem 1243 QUANDO acesso o endpoint ENTAO `record_counts.pull_requests` mostra ambos os valores e `kafka_lag: 4`. |
| **Complexidade** | Alta |
| **Impacto** | Endpoint central que alimenta toda a UI. Depende de MVP-1.7.1 e MVP-1.7.2. |
| **Escopo tecnico** | Novo router FastAPI em `src/contexts/pipeline/routes.py`. Le de: DevLake API (`GET /pipelines`), `pipeline_watermarks`, `pipeline_sync_log`, `metrics_snapshots` (agregado), `eng_*` tables (count), DevLake DB (count). Kafka lag via `aiokafka` AdminClient. |

---

### MVP-1.7.4 -- Adicionar contagens de registros ao DevLakeReader

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.4 |
| **User Story** | Como sistema, preciso de metodos no DevLakeReader que retornem contagens de registros (`COUNT(*)`) das tabelas do DevLake (pull_requests, issues, cicd_deployment_commits, sprints), para comparar com as contagens do PULSE DB e detectar divergencias de sync. |
| **Acceptance Criteria** | DADO que o DevLake DB contem dados QUANDO chamo `reader.count_pull_requests()` ENTAO recebo o inteiro com total de registros. DADO que o DevLake DB esta inacessivel QUANDO chamo qualquer metodo de count ENTAO recebo `None` (nao excecao) com log de warning. DADO que preciso de contagens de todas as entidades QUANDO chamo `reader.count_all()` ENTAO recebo `{"pull_requests": N, "issues": N, "deployments": N, "sprints": N}`. |
| **Complexidade** | Baixa |
| **Impacto** | Habilita a comparacao de record counts em MVP-1.7.3. |
| **Escopo tecnico** | 4 novos metodos em `devlake_reader.py`: `count_pull_requests()`, `count_issues()`, `count_deployments()`, `count_sprints()` + convenience `count_all()`. Todas com try/except retornando None on failure. |

---

### MVP-1.7.5 -- Componente visual do Pipeline Flow Diagram

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.5 |
| **User Story** | Como EM (Carlos), quero ver um diagrama de fluxo horizontal com 4 etapas (Source, DevLake, Sync Worker, Metrics Worker) com indicadores de status, contadores animados, e setas de conexao, para entender de relance se os dados estao fluindo corretamente. |
| **Acceptance Criteria** | DADO que acesso `/integrations` QUANDO a pagina carrega ENTAO vejo a secao "Pipeline Health" abaixo dos connection cards existentes, com 4 cards horizontais conectados por setas. DADO que todas as etapas estao saudaveis QUANDO a pagina renderiza ENTAO todos os 4 cards mostram dot verde e label "Healthy". DADO que o DevLake esta executando um pipeline QUANDO a pagina renderiza ENTAO o card DevLake mostra dot azul pulsante, label "Running", e progress "Task 3/5". DADO que o Sync Worker esta em estado "stale" QUANDO a pagina renderiza ENTAO o card mostra dot amarelo e label "Stale -- last sync 45 min ago". DADO que ha erro no Metrics Worker QUANDO a pagina renderiza ENTAO o card mostra dot vermelho e label "Error". DADO que o endpoint esta carregando QUANDO a pagina renderiza ENTAO skeleton shimmer e exibido (nao spinner). DADO que a tela e mobile (<768px) QUANDO renderiza ENTAO os cards empilham verticalmente com setas verticais. |
| **Complexidade** | Alta |
| **Impacto** | Componente hero da feature. Visualmente comunica saude do pipeline em <2 segundos. |
| **Escopo tecnico** | React component `PipelineFlowDiagram`. Consome `GET /data/v1/pipeline/status`. CSS animations para setas (dashed + flowing dots). Auto-refresh a cada 30 segundos (React Query `refetchInterval`). |

---

### MVP-1.7.6 -- Tabela de contagens de registros por entidade

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.6 |
| **User Story** | Como EM (Carlos), quero ver uma tabela comparando contagens de registros entre DevLake e PULSE DB, com indicacao de Kafka lag e timestamp do ultimo sync, para detectar divergencias de dados entre as camadas. |
| **Acceptance Criteria** | DADO que os dados estao sincronizados QUANDO a tabela renderiza ENTAO cada linha mostra Entity, DevLake Count, PULSE DB Count, Last Synced, Kafka Lag com valores iguais e sem highlight. DADO que DevLake tem 1247 PRs e PULSE DB tem 1243 QUANDO a tabela renderiza ENTAO a linha Pull Requests e destacada em amarelo com tooltip "4 records pending sync". DADO que o Kafka lag e maior que 100 para Issues QUANDO a tabela renderiza ENTAO a coluna Kafka Lag mostra badge vermelho com o valor. DADO que contagem do DevLake esta indisponivel QUANDO a tabela renderiza ENTAO a celula mostra "--" com tooltip "DevLake unavailable". |
| **Complexidade** | Media |
| **Impacto** | Permite diagnostico rapido de problemas de sync. |
| **Escopo tecnico** | React component `RecordCountsTable`. Dados ja disponiveis no response de MVP-1.7.3. |

---

### MVP-1.7.7 -- Painel de erros recentes

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.7 |
| **User Story** | Como EM (Carlos), quero ver um painel colapsavel mostrando erros recentes do pipeline com stage, timestamp, mensagem resumida, e contexto, para entender a causa de falhas sem acessar logs do servidor. |
| **Acceptance Criteria** | DADO que nao ha erros recentes QUANDO a pagina renderiza ENTAO o painel mostra "No recent errors" com icone de check verde e esta colapsado. DADO que ha 3 erros recentes QUANDO a pagina renderiza ENTAO o header mostra "Errors (3)" com badge vermelho, painel esta expandido automaticamente. DADO que um erro tem contexto QUANDO expando o erro ENTAO vejo stage, entity, timestamp (relative, ex: "3 min ago"), mensagem, e detalhes de contexto (ex: issue_key afetada). DADO que a mensagem de erro contem dados sensiveis (tokens, URLs com credenciais) QUANDO o backend serializa ENTAO esses dados sao sanitizados antes de chegar ao frontend. |
| **Complexidade** | Media |
| **Impacto** | Transforma diagnostico de "check server logs" para "check the dashboard". |
| **Escopo tecnico** | React component `PipelineErrorPanel`. Collapsible com animacao. Dados de `recent_errors` no response de MVP-1.7.3. |

---

### MVP-1.7.8 -- Leitura de status de pipelines do DevLake via API

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.8 |
| **User Story** | Como sistema, preciso consultar a API do DevLake para obter o status do pipeline mais recente e do pipeline em execucao (se houver), incluindo detalhes de tasks, para exibir o estado da etapa DevLake no Pipeline Monitor. |
| **Acceptance Criteria** | DADO que o DevLake tem pipelines finalizados QUANDO consulto `GET /pipelines?page=1&pageSize=1` ENTAO obtenho o pipeline mais recente com id, status, started_at, finished_at, e tasks. DADO que ha um pipeline em execucao QUANDO consulto `GET /pipelines?status=TASK_RUNNING&pageSize=1` ENTAO obtenho o pipeline corrente com progresso de tasks. DADO que o DevLake API esta indisponivel QUANDO a consulta falha ENTAO retorno `status: "error"` com `message: "DevLake API unreachable"` sem propagar excecao. DADO que o DevLake retorna pipeline com tasks QUANDO consulto `GET /pipelines/{id}/tasks` ENTAO obtenho lista de subtasks com nome, status, e progresso. |
| **Complexidade** | Media |
| **Impacto** | Habilita a visibilidade do estagio DevLake em MVP-1.7.3 e MVP-1.7.5. |
| **Escopo tecnico** | Novos metodos no `DevLakeApiClient` (NestJS): `getLatestPipeline()`, `getRunningPipeline()`, `getPipelineTasks(id)`. Todos read-only GET. Ou, se a rota e servida pelo pulse-data (FastAPI), adicionar metodos equivalentes ao DevLakeReader. |

---

### MVP-1.7.9 -- Auto-refresh e indicador de freshness

| Campo | Valor |
|-------|-------|
| **Story ID** | MVP-1.7.9 |
| **User Story** | Como EM (Carlos), quero que o Pipeline Monitor atualize automaticamente a cada 30 segundos e mostre um indicador de "freshness" (ex: "Updated 5s ago"), para que eu possa monitorar em tempo real sem refresh manual. |
| **Acceptance Criteria** | DADO que estou na pagina de integrations QUANDO 30 segundos se passam ENTAO os dados do pipeline sao re-fetched automaticamente sem reload da pagina. DADO que os dados foram atualizados ha 15 segundos QUANDO olho para o indicador ENTAO vejo "Updated 15s ago" com contador ao vivo. DADO que o fetch falha QUANDO o auto-refresh executa ENTAO o indicador mostra "Update failed -- retrying..." sem perder os dados anteriores (stale-while-revalidate). DADO que a aba do browser nao esta ativa (blur) QUANDO 30 segundos se passam ENTAO o fetch NAO executa (evitar carga desnecessaria). |
| **Complexidade** | Baixa |
| **Impacto** | Experiencia de monitoramento em tempo real. |
| **Escopo tecnico** | React Query `refetchInterval: 30000` com `refetchIntervalInBackground: false`. Freshness indicator component com `useEffect` + timer. |

---

## 8. Story Dependency Graph

```
MVP-1.7.1  (watermarks DB)
    |
    +-----> MVP-1.7.3  (API endpoint) <----- MVP-1.7.4  (DevLake counts)
    |           |                                  |
    |           |                     MVP-1.7.8  (DevLake pipeline status)
    |           |                         |
MVP-1.7.2  (sync log DB)                 |
    |           |                         |
    |           v                         v
    |       MVP-1.7.5  (Flow Diagram UI)
    |       MVP-1.7.6  (Record Counts Table UI)
    |       MVP-1.7.7  (Error Panel UI)
    |       MVP-1.7.9  (Auto-refresh)
    |
    v
[all UI stories depend on MVP-1.7.3]
```

**Recommended implementation order:**
1. MVP-1.7.1 + MVP-1.7.4 (parallel, no dependencies)
2. MVP-1.7.2 + MVP-1.7.8 (parallel, no dependencies)
3. MVP-1.7.3 (depends on 1, 2, 4, 8)
4. MVP-1.7.5 + MVP-1.7.6 + MVP-1.7.7 (parallel, depend on 3)
5. MVP-1.7.9 (depends on 5)

---

## 9. Complexity Summary

| Story | Description | Complexity | Effort Estimate |
|-------|-------------|------------|-----------------|
| MVP-1.7.1 | Watermarks persistence | Baixa | 0.5d |
| MVP-1.7.2 | Sync log persistence | Media | 1d |
| MVP-1.7.3 | Pipeline status API | Alta | 2d |
| MVP-1.7.4 | DevLake record counts | Baixa | 0.5d |
| MVP-1.7.5 | Flow Diagram UI | Alta | 2d |
| MVP-1.7.6 | Record Counts Table | Media | 1d |
| MVP-1.7.7 | Error Panel | Media | 1d |
| MVP-1.7.8 | DevLake pipeline reads | Media | 1d |
| MVP-1.7.9 | Auto-refresh | Baixa | 0.5d |
| **Total** | | | **~9.5d (2 sprints)** |

---

## 10. Scope Boundaries -- What We Are NOT Building

- **Pipeline triggering or retry UI.** This is read-only. Users cannot trigger syncs, retry failed tasks, or restart workers from the UI. That would violate the read-only constraint.
- **Historical charts or trend analysis of pipeline health.** The sync history timeline (section 5.4) is explicitly a stretch goal, not part of the 9 stories above.
- **Alerting or notifications.** No Slack/email/webhook alerts for pipeline failures. That is R2 scope (Notifications bot).
- **Individual developer attribution.** Pipeline errors are attributed to stages and entities, never to individual developers.
- **Kafka topic management UI.** No ability to create/delete topics, reset offsets, or manage consumer groups.
- **DevLake configuration or blueprint management.** The existing Integrations page remains read-only for connection status. No config changes.

---

## 11. Acceptance Test Scenarios (End-to-End)

### Scenario A: Happy Path -- Pipeline Healthy

```
DADO que todos os conectores estao ativos, DevLake completou o ultimo pipeline,
      Sync Worker completou ha 5 minutos, e Metrics Worker escreveu snapshots
QUANDO Carlos acessa /integrations
ENTAO ele ve:
  - Secao "Pipeline Health" abaixo dos connection cards
  - 4 cards horizontais todos com dot verde e "Healthy"
  - Setas entre cards em verde com animacao suave
  - Tabela de record counts com valores iguais entre DevLake e PULSE DB
  - Painel de erros colapsado com "No recent errors"
  - Indicador "Updated just now"
```

### Scenario B: DevLake Running

```
DADO que o DevLake esta executando um pipeline com 5 tasks (3 completas)
QUANDO Carlos acessa /integrations
ENTAO ele ve:
  - Card DevLake com dot azul pulsante e "Running -- Task 3/5"
  - Seta de Source para DevLake em azul com animacao de flowing dots
  - Overall status: "Running"
```

### Scenario C: Sync Worker Stale

```
DADO que o Sync Worker completou o ultimo ciclo ha 45 minutos
      (esperado: a cada 15 minutos, threshold stale: 30 min)
QUANDO Carlos acessa /integrations
ENTAO ele ve:
  - Card Sync Worker com dot amarelo e "Stale -- last sync 45 min ago"
  - Overall status: "Stale"
```

### Scenario D: Error with Actionable Details

```
DADO que o Sync Worker falhou no ultimo ciclo com IntegrityError
QUANDO Carlos acessa /integrations
ENTAO ele ve:
  - Card Sync Worker com dot vermelho e "Error"
  - Painel de erros expandido automaticamente
  - Erro listado: "Sync Worker - Issues | 3 min ago | IntegrityError: duplicate key..."
  - Overall status: "Error"
```

---

## 12. Anti-Surveillance Checklist

| Check | Status |
|-------|--------|
| No individual developer names in pipeline errors | Enforced -- errors reference entity keys (BACK-1234), not people |
| No per-developer sync metrics | N/A -- pipeline metrics are system-level |
| No "who caused this error" attribution | Enforced -- errors are attributed to stages and entities |
| Team-level only | Enforced -- pipeline status is org/tenant scoped |
| Read-only interactions with external systems | Enforced -- all DevLake, Jira, GitHub API calls are GET only |

---

## 13. Impact on Existing Backlog

Adding Feature Set 1.7 (9 stories) to Epico 1:

| Before | After |
|--------|-------|
| Epico 1: 14 stories | Epico 1: 23 stories |
| MVP Total: 36 stories | MVP Total: 45 stories |
| Estimated: 10-14 weeks | Estimated: 12-16 weeks (+2 weeks) |

**Justification:** The Pipeline Monitor is essential for MVP user trust. Without it, users have no way to diagnose data freshness issues, leading to support burden and churn. The 2-week investment prevents a category of "where is my data?" support tickets that would consume far more than 2 weeks post-launch.

**Suggested offset:** Stories MVP-1.7.1 and MVP-1.7.2 replace work we would need to do anyway (watermark persistence is a known bug; sync logging is needed for operations). Net new effort is closer to 7-8 days.
