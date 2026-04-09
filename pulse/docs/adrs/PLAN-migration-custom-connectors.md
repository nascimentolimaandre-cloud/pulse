# Plano de Migracao: DevLake → Conectores Proprietarios

**Status:** Aprovado  
**Data:** 2026-04-09  
**Referencia:** ADR-005  
**Estimativa total:** 2-3 semanas  

---

## Visao Geral da Mudanca

```
ANTES (DevLake):
  GitHub API → DevLake Raw → DevLake Tool → DevLake Domain → DevLakeReader → Normalizer → PULSE DB → Kafka
  (4 hops, caixa preta Go, 2 DBs separados)

DEPOIS (Conectores Proprios):
  GitHub API → GitHubConnector → Normalizer → PULSE DB → Kafka
  Jira API   → JiraConnector   → Normalizer → PULSE DB → Kafka
  Jenkins API → JenkinsConnector → Normalizer → PULSE DB → Kafka
  (1 hop, Python puro, 1 DB)
```

---

## Estrutura de Arquivos — O Que Muda

```
packages/pulse-data/src/
├── config.py                              # MODIFICA: remove devlake_*, adiciona source configs
├── connectors/                            # NOVO: diretorio de conectores
│   ├── __init__.py
│   ├── base.py                            # NOVO: classe abstrata BaseConnector
│   ├── github_connector.py                # NOVO: ~350 linhas
│   ├── jira_connector.py                  # NOVO: ~400 linhas
│   └── jenkins_connector.py               # NOVO: ~250 linhas
├── contexts/
│   └── engineering_data/
│       ├── devlake_reader.py              # REMOVE (272 linhas)
│       ├── normalizer.py                  # MODIFICA: ajusta field names (~30 linhas mudam)
│       └── models.py                      # INTACTO
│   └── pipeline/
│       ├── devlake_api.py                 # REMOVE (76 linhas)
│       ├── routes.py                      # MODIFICA: troca DevLake health por connector health
│       └── models.py                      # INTACTO
├── workers/
│   ├── devlake_sync.py                    # REFATORA → data_sync.py (~150 linhas mudam)
│   └── metrics_worker.py                  # INTACTO
└── shared/
    ├── kafka.py                           # INTACTO
    └── http_client.py                     # NOVO: httpx wrapper com retry/rate-limit (~100 linhas)
```

### Resumo quantitativo

| Acao | Arquivos | Linhas |
|------|----------|--------|
| NOVO (conectores + base + http_client) | 5 | ~1.200 |
| MODIFICA (normalizer, config, routes, sync) | 4 | ~200 linhas alteradas |
| REMOVE (devlake_reader, devlake_api) | 2 | -348 linhas |
| INTACTO (models, kafka, migrations, metrics) | 8+ | ~1.500 linhas |
| **Saldo liquido** | | **+~1.050 linhas** |

---

## Fase 1 — Fundacao (Dia 1-2)

### 1.1 Base Connector + HTTP Client

**Arquivo:** `src/connectors/base.py`

```python
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

class BaseConnector(ABC):
    """Interface que todo conector de fonte de dados deve implementar.
    
    Retorna listas de dicts no formato que o normalizer espera.
    Cada conector traduz os campos da API nativa para o formato padrao.
    """
    
    @abstractmethod
    async def fetch_pull_requests(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Retorna PRs/MRs no formato padrao."""
        ...
    
    @abstractmethod
    async def fetch_issues(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Retorna issues/work items no formato padrao."""
        ...
    
    @abstractmethod
    async def fetch_issue_changelogs(self, issue_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Retorna changelogs de status transitions por issue_id."""
        ...
    
    @abstractmethod
    async def fetch_deployments(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Retorna deployments/builds no formato padrao."""
        ...
    
    @abstractmethod
    async def fetch_sprints(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Retorna sprints no formato padrao."""
        ...
    
    @abstractmethod
    async def fetch_sprint_issues(self, sprint_id: str) -> list[dict[str, Any]]:
        """Retorna issues de um sprint especifico."""
        ...
    
    @abstractmethod
    async def close(self) -> None:
        """Libera recursos (HTTP sessions, etc)."""
        ...
```

**Contrato chave:** Os dicts retornados devem ter os mesmos nomes de campos que o `normalizer.py` espera. Isso permite reuso total do normalizer existente.

**Arquivo:** `src/shared/http_client.py`

```python
"""HTTP client wrapper com retry, rate-limiting e logging."""

import httpx
import asyncio
import logging
from typing import Any

class ResilientHTTPClient:
    """httpx AsyncClient com:
    - Retry com exponential backoff (3 tentativas)
    - Rate limit awareness (respeita headers X-RateLimit-*)
    - Timeout configuravel (30s default)
    - Logging de requests/responses
    """
    
    def __init__(self, base_url: str, auth: dict, timeout: float = 30.0):
        ...
    
    async def get(self, path: str, params: dict = None) -> Any:
        """GET com retry e rate-limit handling."""
        ...
    
    async def get_paginated(self, path: str, params: dict = None, 
                            page_size: int = 100, max_pages: int = 100) -> list[dict]:
        """GET com paginacao automatica. Suporta:
        - Link header (GitHub)
        - startAt/maxResults (Jira) 
        - page/pageSize (generico)
        """
        ...
    
    async def close(self):
        ...
```

### 1.2 Atualizar config.py

**Remover:**
```python
devlake_db_url: str = "..."
devlake_api_url: str = "..."
```

**Adicionar:**
```python
# Source API tokens (lidos de env vars, mesmos que o DevLake usava)
github_token: str = ""
github_org: str = "webmotors-private"

jira_base_url: str = ""
jira_email: str = ""
jira_api_token: str = ""

jenkins_base_url: str = ""
jenkins_username: str = ""
jenkins_api_token: str = ""
```

> **Nota:** Essas env vars ja existem no .env e no docker-compose.yml (GITHUB_TOKEN, JIRA_API_TOKEN, etc). Nao precisa criar novas.

### 1.3 Mapeamento de Campos: API Nativa → Normalizer

O normalizer espera dicts com campos especificos. Cada conector precisa mapear:

**Pull Requests (normalizer espera):**
```
id, base_repo_id, head_repo_id, status, title, url, author_name,
created_date, merged_date, closed_date, merge_commit_sha, 
base_ref, head_ref, additions, deletions
```

**Issues (normalizer espera):**
```
id, url, issue_key, title, status, original_status, story_point,
priority, created_date, updated_date, resolution_date,
lead_time_minutes, assignee_name, type, sprint_id
```

**Issue Changelogs (normalizer espera):**
```
issue_id, from_status (original_from_value), to_status (original_to_value), created_date
```

**Deployments (normalizer espera):**
```
id, cicd_deployment_id, repo_id, name, result, status, 
environment, created_date, started_date, finished_date
```

**Sprints (normalizer espera):**
```
id, original_board_id, name, url, status, started_date, 
ended_date, completed_date, total_issues (count)
```

**Sprint Issues (normalizer espera):**
```
id, issue_key, status, original_status, story_point, type, resolution_date
```

---

## Fase 2 — Conector Jira (Dia 3-5)

**Prioridade #1** porque e o que esta quebrado no DevLake.

**Arquivo:** `src/connectors/jira_connector.py`

### Endpoints Jira REST API v3 a usar:

| Dado | Endpoint | Paginacao |
|------|----------|-----------|
| Issues | `GET /rest/api/3/search` (JQL) | startAt + maxResults (50) |
| Issue detail | `GET /rest/api/3/issue/{key}?expand=changelog` | N/A |
| Sprints | `GET /rest/agile/1.0/board/{boardId}/sprint` | startAt + maxResults |
| Sprint issues | `GET /rest/agile/1.0/sprint/{sprintId}/issue` | startAt + maxResults |
| Boards | `GET /rest/agile/1.0/board` | startAt + maxResults |
| Changelogs | Incluido no expand=changelog do issue | In-line |

### JQL para busca incremental:
```
project IN (DESC, ENO, ANCR, PUSO, APPF, FID, CTURBO, PTURB) 
AND updated >= "2026-04-01"
ORDER BY updated DESC
```

### Mapeamento de campos Jira → Normalizer:

```python
def _map_issue(self, jira_issue: dict) -> dict:
    fields = jira_issue["fields"]
    return {
        "id": f"jira:JiraIssue:{self._connection_id}:{jira_issue['id']}",
        "url": f"{self._base_url}/browse/{jira_issue['key']}",
        "issue_key": jira_issue["key"],
        "title": fields.get("summary", ""),
        "status": fields.get("status", {}).get("name", ""),
        "original_status": fields.get("status", {}).get("name", ""),
        "story_point": fields.get("story_points") or fields.get("customfield_10028"),
        "priority": fields.get("priority", {}).get("name", ""),
        "created_date": fields.get("created"),
        "updated_date": fields.get("updated"),
        "resolution_date": fields.get("resolutiondate"),
        "lead_time_minutes": None,  # Calculado pelo PULSE
        "assignee_name": (fields.get("assignee") or {}).get("displayName"),
        "type": fields.get("issuetype", {}).get("name", "Task"),
        "sprint_id": None,  # Preenchido via sprint API
    }
```

### Changelogs (inline no expand=changelog):

```python
def _map_changelogs(self, jira_issue: dict) -> list[dict]:
    changelogs = []
    for history in jira_issue.get("changelog", {}).get("histories", []):
        for item in history.get("items", []):
            if item.get("field") == "status":
                changelogs.append({
                    "issue_id": f"jira:JiraIssue:{self._connection_id}:{jira_issue['id']}",
                    "from_status": item.get("fromString", ""),
                    "to_status": item.get("toString", ""),
                    "created_date": history.get("created"),
                })
    return changelogs
```

### Vantagem direta sobre DevLake:
- **Changelogs vem junto com o issue** (expand=changelog) — 1 request vs 2 no DevLake
- **JQL nativo** para filtrar por projeto/data — sem intermediarios
- **API v3** direto — sem depender de fix do DevLake

### Estimativa: ~400 linhas, 3 dias (incluindo testes)

---

## Fase 3 — Conector Jenkins (Dia 5-6)

**Arquivo:** `src/connectors/jenkins_connector.py`

### Endpoints Jenkins API:

| Dado | Endpoint |
|------|----------|
| Job list | `GET /api/json?tree=jobs[name,url,fullName]` |
| Job builds | `GET /job/{name}/api/json?tree=builds[number,result,timestamp,duration,url]` |
| Build detail | `GET /job/{name}/{number}/api/json` |

### Mapeamento Jenkins → Normalizer (deployments):

```python
def _map_build(self, job_name: str, build: dict) -> dict:
    result = build.get("result", "UNKNOWN")
    timestamp_ms = build.get("timestamp", 0)
    duration_ms = build.get("duration", 0)
    started = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    finished = datetime.fromtimestamp((timestamp_ms + duration_ms) / 1000, tz=timezone.utc)
    
    return {
        "id": f"jenkins:JenkinsBuild:{self._connection_id}:{job_name}:{build['number']}",
        "cicd_deployment_id": f"jenkins:JenkinsJob:{self._connection_id}:{job_name}",
        "repo_id": None,
        "name": job_name,
        "result": result,           # SUCCESS, FAILURE, UNSTABLE, ABORTED
        "status": "DONE",
        "environment": self._detect_environment(job_name),
        "created_date": started.isoformat(),
        "started_date": started.isoformat(),
        "finished_date": finished.isoformat(),
    }
```

### Deteccao de environment:
Ler de `config/connections.yaml` os patterns `deploymentPattern` e `productionPattern` por job.

### Estimativa: ~250 linhas, 1.5 dias

---

## Fase 4 — Conector GitHub (Dia 7-10)

**Arquivo:** `src/connectors/github_connector.py`

### Estrategia: REST + GraphQL

**REST API v3** para PRs (simples, paginated):
```
GET /repos/{owner}/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100
```

**GraphQL** para dados enriquecidos (timeline events):
```graphql
query($owner: String!, $repo: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequests(first: 100, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        title
        state
        author { login }
        createdAt
        mergedAt
        closedAt
        additions
        deletions
        changedFiles
        baseRefName
        headRefName
        mergeable
        reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
        reviews(first: 20) { nodes { author { login } state submittedAt } }
        timelineItems(first: 50, itemTypes: [READY_FOR_REVIEW_EVENT, REVIEW_REQUESTED_EVENT, PULL_REQUEST_REVIEW]) {
          nodes {
            __typename
            ... on ReadyForReviewEvent { createdAt }
            ... on ReviewRequestedEvent { createdAt }
            ... on PullRequestReview { submittedAt state }
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
```

### Dados EXTRAS que o DevLake NAO fornecia:
- `first_review_at` — timestamp da primeira review request ou review submetida
- `approved_at` — timestamp da primeira review com state=APPROVED
- `files_changed` — count real de arquivos alterados
- `reviewers` — lista de reviewers com seus estados
- Review timeline completa

### Mapeamento GitHub → Normalizer:

```python
def _map_pr(self, repo_full_name: str, pr: dict) -> dict:
    return {
        "id": f"github:GithubPullRequest:{self._connection_id}:{pr['number']}",
        "base_repo_id": f"github:GithubRepo:{self._connection_id}:{repo_full_name}",
        "head_repo_id": f"github:GithubRepo:{self._connection_id}:{repo_full_name}",
        "status": pr["state"].upper(),    # OPEN, CLOSED, MERGED
        "title": pr["title"],
        "url": pr.get("html_url") or pr.get("url", ""),
        "author_name": pr.get("user", {}).get("login", "unknown"),
        "created_date": pr["created_at"],
        "merged_date": pr.get("merged_at"),
        "closed_date": pr.get("closed_at"),
        "merge_commit_sha": pr.get("merge_commit_sha"),
        "base_ref": pr.get("base", {}).get("ref", ""),
        "head_ref": pr.get("head", {}).get("ref", ""),
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        # NOVOS — enriquecem o normalizer
        "_files_changed": pr.get("changed_files", 0),
        "_reviewers": [...],
        "_first_review_at": ...,
        "_approved_at": ...,
    }
```

### Discovery de repos:
Substitui `scripts/bulk_import_repos.py`:
```python
async def discover_repos(self, org: str, active_months: int = 12) -> list[str]:
    """Lista todos os repos da org, filtrado por atividade recente."""
    repos = await self._client.get_paginated(f"/orgs/{org}/repos", params={"type": "all"})
    cutoff = datetime.now(timezone.utc) - timedelta(days=active_months * 30)
    return [r["full_name"] for r in repos if _parse_datetime(r["pushed_at"]) > cutoff]
```

### Rate limiting:
- REST: 5.000 req/hora com token (PyGithub gerencia automaticamente)
- GraphQL: 5.000 pontos/hora (1 query = ~1 ponto)
- Para 1.426 repos com ~4 PRs cada: ~5.704 requests = ~1.1 hora no pior caso
- Com GraphQL: ~1.426 queries × 1 ponto = muito menos

### Estimativa: ~350 linhas, 3 dias (incluindo GraphQL + discovery)

---

## Fase 5 — Refatorar Sync Worker (Dia 10-11)

### De: `devlake_sync.py` → Para: `data_sync.py`

**Mudanca cirurgica:** O sync worker troca `DevLakeReader` por `ConnectorAggregator`:

```python
# ANTES (devlake_sync.py, linha 28):
from src.contexts.engineering_data.devlake_reader import DevLakeReader

# DEPOIS (data_sync.py):
from src.connectors.github_connector import GitHubConnector
from src.connectors.jira_connector import JiraConnector
from src.connectors.jenkins_connector import JenkinsConnector
```

### ConnectorAggregator — agrega dados de multiplos conectores:

```python
class ConnectorAggregator:
    """Agrega dados de multiplos conectores numa interface unificada.
    
    Implementa a mesma interface que DevLakeReader tinha, para que o
    sync worker nao precise mudar sua logica de watermark/upsert/kafka.
    """
    def __init__(self):
        self._connectors = {
            "github": GitHubConnector(...),
            "jira": JiraConnector(...),
            "jenkins": JenkinsConnector(...),
        }
    
    async def fetch_pull_requests(self, since=None) -> list[dict]:
        return await self._connectors["github"].fetch_pull_requests(since)
    
    async def fetch_issues(self, since=None) -> list[dict]:
        return await self._connectors["jira"].fetch_issues(since)
    
    async def fetch_issue_changelogs(self, issue_ids) -> dict:
        return await self._connectors["jira"].fetch_issue_changelogs(issue_ids)
    
    async def fetch_deployments(self, since=None) -> list[dict]:
        return await self._connectors["jenkins"].fetch_deployments(since)
    
    async def fetch_sprints(self, since=None) -> list[dict]:
        return await self._connectors["jira"].fetch_sprints(since)
    
    async def fetch_sprint_issues(self, sprint_id) -> list[dict]:
        return await self._connectors["jira"].fetch_sprint_issues(sprint_id)
```

### O que NAO muda no sync worker:
- `sync()` — orquestracao de todas as entidades ✅
- `_sync_pull_requests()` — logica de watermark + normalize + upsert + kafka ✅
- `_sync_issues()` — idem ✅
- `_sync_deployments()` — idem ✅
- `_sync_sprints()` — idem ✅
- `_upsert_*()` — todas as queries de ON CONFLICT ✅
- `_get_watermark()` / `_set_watermark()` — watermark persistence ✅
- `_log_sync_cycle()` — observability ✅
- `run_sync_loop()` — cron loop ✅

### O que MUDA no sync worker:
- Linha 28: import DevLakeReader → import ConnectorAggregator
- Linha ~114: `self._reader = DevLakeReader()` → `self._reader = ConnectorAggregator()`
- Linha ~205: `await self._reader.close()` → idem (ConnectorAggregator.close() fecha todos)

**Total: ~5-10 linhas de mudanca no sync worker.**

### Estimativa: 1 dia

---

## Fase 6 — Atualizar Normalizer (Dia 11)

### Mudancas minimas no normalizer:

O normalizer e 99% reutilizavel porque os conectores mapeiam para o formato esperado. Ajustes:

1. **`_detect_source()`** — Manter como esta (os conectores geram IDs com prefixo `github:`, `jira:`, `jenkins:`)

2. **`normalize_pull_request()`** — Adicionar suporte aos campos extras do GitHub GraphQL:
```python
# Adicionar apos linha 274:
"first_review_at": _parse_datetime(devlake_pr.get("_first_review_at")),
"approved_at": _parse_datetime(devlake_pr.get("_approved_at")),
"files_changed": devlake_pr.get("_files_changed", 0),
"reviewers": devlake_pr.get("_reviewers", []),
```

3. **Docstrings** — Atualizar "DevLake" → "source connector" nas docstrings

### Estimativa: 0.5 dia

---

## Fase 7 — Atualizar Pipeline Monitor (Dia 12)

### Remover: `devlake_api.py` (76 linhas)

### Modificar: `routes.py`

**ANTES:** Pipeline Monitor compara DevLake counts vs PULSE counts  
**DEPOIS:** Pipeline Monitor mostra connector health + PULSE counts

```python
# Remover:
from src.contexts.pipeline.devlake_api import DevLakeAPIClient
from src.contexts.engineering_data.devlake_reader import DevLakeReader

# Adicionar:
from src.connectors.github_connector import GitHubConnector
from src.connectors.jira_connector import JiraConnector  
from src.connectors.jenkins_connector import JenkinsConnector
```

**`_get_devlake_counts()`** → **`_get_source_health()`**:
```python
async def _get_source_health() -> dict:
    """Check connectivity and basic counts from each source."""
    health = {}
    # GitHub: test API connectivity
    try:
        gh = GitHubConnector(...)
        health["github"] = {"status": "healthy", "org": settings.github_org}
        await gh.close()
    except Exception as e:
        health["github"] = {"status": "error", "error": str(e)}
    # ... idem para Jira e Jenkins
    return health
```

A comparacao DevLake vs PULSE nao faz mais sentido (nao ha DB intermediario). No lugar, o Pipeline Monitor mostra:
- **Connector status** (healthy/error per source)
- **PULSE DB counts** (total records por entidade)
- **Last sync** (de pipeline_sync_log, ja funciona)
- **Watermarks** (de pipeline_watermarks, ja funciona)
- **Errors** (de pipeline_sync_log, ja funciona)

### Estimativa: 1 dia

---

## Fase 8 — Limpar Infraestrutura (Dia 12-13)

### 8.1 docker-compose.yml

**Remover services:**
```yaml
# REMOVER COMPLETAMENTE:
devlake:
  image: apache/devlake:v1.0.3-beta7
  ...

devlake-pg:
  image: postgres:16-alpine
  ...
```

**Remover volume:**
```yaml
volumes:
  # REMOVER:
  devlake_pgdata:
    driver: local
```

**Atualizar pulse-data e sync-worker:**
```yaml
pulse-data:
  environment:
    # REMOVER:
    DEVLAKE_DB_URL: ...
    DEVLAKE_API_URL: ...
    # ADICIONAR:
    GITHUB_TOKEN: ${GITHUB_TOKEN:-}
    GITHUB_ORG: ${GITHUB_ORG:-webmotors-private}
    JIRA_BASE_URL: ${JIRA_BASE_URL:-}
    JIRA_EMAIL: ${JIRA_EMAIL:-}
    JIRA_API_TOKEN: ${JIRA_API_TOKEN:-}
    JENKINS_BASE_URL: ${JENKINS_BASE_URL:-}
    JENKINS_USERNAME: ${JENKINS_USERNAME:-}
    JENKINS_API_TOKEN: ${JENKINS_API_TOKEN:-}
  depends_on:
    # REMOVER:
    devlake-pg:
      condition: service_healthy
```

### 8.2 NestJS — Simplificar Integration Module

O `ConfigLoaderService` hoje faz provisioning no DevLake (criar connections, blueprints, scopes). Com conectores proprios, isso nao e mais necessario.

**Simplificar `config-loader.service.ts`:**
- Manter: Leitura do `connections.yaml` + criacao de teams/org no PULSE DB
- Remover: Toda logica de `DevLakeApiClient` calls (~300 linhas)
- Remover: `devlake-api.client.ts` inteiro (319 linhas)

**Resultado:** O NestJS apenas carrega a config YAML e cria registros no PULSE DB. O Python (pulse-data) cuida da ingestao.

### 8.3 Scripts

- **Remover:** `scripts/bulk_import_repos.py` (substituido por `GitHubConnector.discover_repos()`)
- **Reescrever:** `scripts/full_ingestion.py` (simplificar — sem DevLake API polling)

### 8.4 Dependencies (pyproject.toml)

**Adicionar:**
```toml
PyGithub = ">=2.1.0"     # GitHub REST API
gql = ">=3.5.0"          # GitHub GraphQL (opcional, pode usar httpx direto)
jira = ">=3.8.0"         # Jira REST API v3
python-jenkins = ">=1.8.0"  # Jenkins API
```

**Nota:** `httpx` ja e dependencia existente — reutilizar para requests customizados.

### Estimativa: 1 dia

---

## Fase 9 — Testes (Dia 13-15)

### 9.1 Unit Tests por Conector

```python
# tests/connectors/test_jira_connector.py
async def test_map_issue_normalizer_compatible():
    """Garante que o dict retornado tem todos os campos que o normalizer espera."""
    raw_jira = {...}  # fixture de issue Jira real
    mapped = connector._map_issue(raw_jira)
    # Todos os campos devem existir:
    assert "id" in mapped
    assert "issue_key" in mapped
    assert "original_status" in mapped
    assert "story_point" in mapped
    ...

async def test_changelog_extraction():
    """Garante que changelogs sao extraidos do expand=changelog."""
    ...

async def test_incremental_sync_jql():
    """Garante que JQL inclui filtro de updated >= since."""
    ...
```

### 9.2 Integration Test — Full Pipeline

```python
async def test_full_sync_cycle():
    """Testa o fluxo completo: Connector → Normalizer → Upsert → Kafka."""
    # Mock dos conectores com dados reais (fixtures)
    aggregator = ConnectorAggregator(connectors={
        "github": MockGitHubConnector(fixtures/github_prs.json),
        "jira": MockJiraConnector(fixtures/jira_issues.json),
        "jenkins": MockJenkinsConnector(fixtures/jenkins_builds.json),
    })
    worker = DataSyncWorker(reader=aggregator)
    results = await worker.sync()
    
    assert results["pull_requests"]["synced"] > 0
    assert results["issues"]["synced"] > 0
    assert results["deployments"]["synced"] > 0
```

### 9.3 Smoke Test com APIs reais

```bash
# Script de validacao manual (nao automatizado)
python -m scripts.smoke_test_connectors
# Testa:
# 1. GitHub: busca 10 PRs do repo mais ativo
# 2. Jira: busca 10 issues do projeto DESC
# 3. Jenkins: busca 5 builds do job mais recente
# 4. Normalizer: processa os dados sem erro
# 5. Upsert: insere no PULSE DB
```

### Estimativa: 2 dias

---

## Fase 10 — Validacao e Cutover (Dia 15)

### 10.1 Comparar dados pre/pos migracao

```sql
-- Antes: snapshot dos dados existentes
SELECT source, COUNT(*) FROM eng_pull_requests GROUP BY source;
SELECT source, COUNT(*) FROM eng_issues GROUP BY source;
SELECT source, COUNT(*) FROM eng_deployments GROUP BY source;
```

### 10.2 Rodar full sync com conectores novos

```bash
docker compose up -d  # Sem DevLake!
docker exec pulse-data python -m scripts.full_ingestion --reset-watermarks
```

### 10.3 Validar contagens

```sql
-- Depois: contagens devem ser >= as anteriores
-- (podem ser maiores porque os conectores acessam dados que DevLake perdia)
SELECT source, COUNT(*) FROM eng_pull_requests GROUP BY source;
SELECT source, COUNT(*) FROM eng_issues GROUP BY source;  -- Esperado: >>243 (os 32K issues do Jira)
```

### 10.4 Verificar Pipeline Monitor

- Dashboard deve mostrar connectors healthy
- Sync logs registrando ciclos completos
- Watermarks atualizando

---

## Cronograma Consolidado

| Dia | Fase | Entregavel |
|-----|------|-----------|
| 1-2 | Fundacao | `base.py`, `http_client.py`, config atualizada |
| 3-5 | Jira Connector | `jira_connector.py` + testes unitarios |
| 5-6 | Jenkins Connector | `jenkins_connector.py` + testes unitarios |
| 7-10 | GitHub Connector | `github_connector.py` + GraphQL + discovery |
| 10-11 | Refatorar Sync Worker | `data_sync.py` com ConnectorAggregator |
| 11 | Atualizar Normalizer | Campos extras, docstrings |
| 12 | Pipeline Monitor | Trocar DevLake health por connector health |
| 12-13 | Limpar Infra | docker-compose, NestJS, scripts |
| 13-15 | Testes + Validacao | Unit, integration, smoke, cutover |

---

## Riscos e Mitigacoes

| Risco | Mitigacao |
|-------|----------|
| Rate limit GitHub (1.426 repos) | GraphQL batch + sleep entre batches + cache |
| Story points field customizado no Jira | Ler de connections.yaml qual customfield usar |
| Jenkins auth por certificado | Verificar se basic auth funciona (ja funciona no .env) |
| Dados existentes no PULSE DB divergem | Rodar com --reset-watermarks no primeiro sync |
| Regressao no normalizer | Testes unitarios com fixtures dos dados reais |

---

## Checklist de Prontidao (DoD)

- [ ] Todos os 3 conectores implementados e testados
- [ ] Normalizer adaptado e testes passando
- [ ] Sync worker usando ConnectorAggregator
- [ ] Pipeline Monitor sem referencias a DevLake
- [ ] docker-compose.yml sem servicos DevLake
- [ ] NestJS sem DevLakeApiClient
- [ ] `make up` sobe stack completo sem DevLake
- [ ] Full sync retorna >= dados anteriores
- [ ] Issues Jira: 32.000+ (vs 243 anteriores)
- [ ] Pipeline Monitor mostra connectors healthy
- [ ] Testes unitarios para os 3 conectores
- [ ] Smoke test com APIs reais da Webmotors
