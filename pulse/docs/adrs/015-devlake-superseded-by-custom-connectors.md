# ADR-015: DevLake Replaced by Custom Source Connectors

**Status:** Accepted + Implemented (migração concluída 2026-04-10)
**Date:** 2026-04-09 (proposto) · **Implemented:** 2026-04-10
**Deciders:** Andre Nascimento + PULSE team
**Supersedes:** ADR-003 (Apache DevLake as Internal Pipeline Engine)
**Implementation commits:** `ee34b6a` (replace), `b10fdfa` (remove dead code), `c206b7d` (321 unit tests)
**Related plan:** `docs/adrs/PLAN-migration-custom-connectors.md` (status: DONE)

> **Renumbering note (2026-05-06):** This document was originally
> filed as `ADR-005-devlake-vs-custom-ingestion.md`, which collided
> with the existing `005-polyglot-nestjs-fastapi.md`. Renumbered to
> ADR-015 (next free slot when written in 2026-04). The filename was
> the only change; all decisions, commits, and code already reference
> this content.

**Contexto original:** Problemas recorrentes com DevLake bloqueavam o
pipeline de dados (Jira API v2 deprecada, upgrade quebrava no
PostgreSQL, 99,3% perda de dados Jira tool→domain). Análise completa
abaixo permanece para histórico — a decisão tomada (Opção B,
substituição total) foi executada conforme planejado.

## Outcome (post-implementation, 2026-05-06)

A recomendação foi seguida exatamente:
- **Conectores próprios shipped** em `packages/pulse-data/src/connectors/`:
  `github_connector.py`, `jira_connector.py`, `jenkins_connector.py`.
- **DevLake removido** do `docker-compose.yml` (commit `b10fdfa`).
- **`devlake_reader.py` deletado**; `devlake_sync.py` renamed
  internamente para `DataSyncWorker` (alias `DevLakeSyncWorker`
  mantido por backward compat — pode ser removido em release de limpeza).
- **321 unit tests** cobrindo os 3 connectors (commit `c206b7d`).
- **Normalizer reused** ~100% como previsto.

ADR-003 marcado como **Superseded by ADR-015**.

---

## Análise original (preservada como histórico)

---

## 1. Contexto e Motivacao

O PULSE adotou o Apache DevLake como motor de ingestao na arquitetura hibrida (ADR-001, Hipotese 3), com score 4.3/5. A premissa era: "usar DevLake como acelerador de MVP sem criar acoplamento irreversivel" e substituir plugins por conectores customizados quando necessario.

**Estamos nesse ponto de inflexao.** Nas ultimas semanas, enfrentamos:

1. **Jira API v2 deprecada** — 6/8 boards falham (HTTP 410). Fix existe em v1.0.3-beta7+, mas upgrade falha
2. **Upgrade DevLake v1.0.2 → v1.0.3-beta7** — Migrations usam sintaxe MySQL (`int unsigned`, `double`, `datetime`) que quebram no PostgreSQL
3. **Perda massiva de dados** — 32.621 issues no tool-layer, apenas 243 no domain-layer (99.3% de perda)
4. **1.426 repos registrados, apenas 21 ingeridos** — Pipeline GitHub tambem incompleto
5. **0 sprints** no domain-layer, apesar de 8 boards Jira configurados
6. **0 deploys Jenkins reais** — Apenas 76 builds dos 16 jobs mapeados

### Estado Atual dos Dados (09/04/2026)

| Camada | PRs | Issues | Deployments | Sprints | Repos |
|--------|-----|--------|-------------|---------|-------|
| DevLake Tool Layer | 5.564 | 32.621 | 76 | ? | 1.426 |
| DevLake Domain Layer | 5.544 | 243 | 83 | 0 | 21 |
| PULSE App DB | 5.314 | 243 | 83 | 0 | - |
| **Perda Tool→Domain** | **0.4%** | **99.3%** | - | **100%** | **98.5%** |

---

## 2. Diagnostico: Por que o DevLake esta falhando?

### 2.1 PostgreSQL e Cidadao de Segunda Classe

O DevLake foi projetado para MySQL. O suporte a PostgreSQL e "nao oficial":

- **Issue #8350** — Maintainers declararam: *"We don't have plans to make Postgres officially supported in the near future"*
- **Issue #8778 (Mar 2026)** — Plugin Copilot usa `gorm:"type:datetime"` (MySQL-only)
- **Issue #8564 (Nov 2025)** — Migration usa `ALTER TABLE ... MODIFY` (sintaxe MySQL)
- **Issue #8548 (Aug 2025)** — `GROUP BY` incompativel com PG17 (valido em MySQL com `ONLY_FULL_GROUP_BY` off)
- **Issue #1790 (Mai 2022!)** — `unsigned` integer types. Reportado ha 4 anos, mesmo padrao de bug reaparece em 2026

**Padrao sistematico:** Cada novo plugin e escrito/testado contra MySQL. Compatibilidade PG quebra em toda release.

### 2.2 Versao Estavel? Nao Existe

| Versao | Status | Periodo Beta |
|--------|--------|-------------|
| v1.0.2 | Estavel | 10 meses (9 betas) |
| v1.0.3 | **Sem data** | 10+ meses (10 betas e contando) |

O fix do Jira API v3 (PR #8608) foi mergeado em Out/2025 e so existe em betas. Nao ha versao estavel com esse fix. Dependemos de software beta para funcionalidade critica.

### 2.3 Dupla Normalizacao

O fluxo atual e:

```
GitHub API → DevLake Raw → DevLake Tool → DevLake Domain → PULSE Normalizer → PULSE DB
```

PULSE ja reimplementa toda a normalizacao:
- `normalizer.py` (539 linhas): Status mapping com 60+ mapeamentos PT-BR, deteccao de source, linking issue↔PR, calculo de cycle time
- `devlake_reader.py` (272 linhas): Queries SQL no DevLake domain layer
- `devlake_sync.py` (552 linhas): Watermarks, upserts, Kafka publishing

**Total: 1.363 linhas** de codigo que existem **apenas para ler do DevLake e re-normalizar**.

O DevLake fornece a extracao de API + paginacao + rate limiting. Tudo mais, PULSE refaz.

### 2.4 Overhead Operacional

Para rodar DevLake localmente ou em producao, precisamos de:

| Componente | Recurso | Custo Estimado (AWS) |
|-----------|---------|---------------------|
| DevLake Server (Go) | ECS Fargate 1vCPU/2GB | ~$35-45/mes |
| DevLake PostgreSQL | RDS separado do PULSE | ~$15-25/mes |
| DevLake Config UI | Nao deployado, mas necessario p/ migrations | ~$10/mes |
| Debugging time | Horas de dev em issues PG | Incalculavel |
| **Total infra extra** | | **~$60-80/mes** |

---

## 3. As Opcoes

### Opcao A: Manter DevLake + Forcar Upgrade (MySQL backend)

Trocar o DevLake para usar MySQL ao inves de PostgreSQL, resolvendo os problemas de compatibilidade.

**Mudancas necessarias:**
- Adicionar container MySQL ao docker-compose (para DevLake)
- Manter PostgreSQL para PULSE App DB
- Re-configurar DevLake `DB_URL` para MySQL
- Re-importar todas as connections/scopes/blueprints
- Testar upgrade path para v1.0.3-beta7+

**Prós:**
- Menor mudanca arquitetural — DevLake continua no papel atual
- MySQL e o backend "oficial" — migrations funcionam
- Preserva opcao de adicionar GitLab/Bitbucket/ADO via plugins nativos
- Fix do Jira v3 vem "de graca" com upgrade
- Comunidade DevLake mantem conectores atualizados

**Contras:**
- Adiciona MySQL ao stack (mais um DB para operar)
- Continuamos dependendo de software beta (v1.0.3 sem release estavel)
- Dupla normalizacao permanece
- Nao resolve o problema de 99.3% de perda de dados Jira (pode ser bug separado)
- Cada upgrade futuro e risco de novos bugs

**Esforco estimado:** 1-2 dias  
**Risco:** Medio — resolve PG, mas nao os problemas estruturais

---

### Opcao B: Ingestao Proprietaria (Substituicao Total)

Construir conectores Python proprios usando bibliotecas maduras, eliminando DevLake completamente.

**Bibliotecas por source:**

| Source | Biblioteca | Stars | Maturidade |
|--------|-----------|-------|------------|
| GitHub | PyGithub / `gql` (GraphQL) | 7k+ | Estavel, ativa |
| Jira | jira-python | 1.8k+ | Estavel, suporta v3 |
| Jenkins | python-jenkins | 600+ | Estavel, ja usamos |
| GitLab (futuro) | python-gitlab | 2k+ | Estavel |
| ADO (futuro) | azure-devops-python-api | MS oficial | Estavel |

**Componentes a construir (por source):**

```
source_connector/
  ├── client.py          # API client com auth, rate limiting, retry (~150 linhas)
  ├── paginator.py       # Paginacao generica (~80 linhas)
  ├── extractor.py       # Extracao de dados especificos (~200 linhas)
  └── tests/             # Unit tests (~150 linhas)
```

**Estimativa por conector:** ~400-600 linhas de codigo + ~150 linhas de testes

**Fluxo simplificado:**
```
GitHub API ──→ GitHub Connector ──→ Normalizer ──→ PULSE DB ──→ Kafka
Jira API   ──→ Jira Connector   ──→ Normalizer ──→ PULSE DB ──→ Kafka
Jenkins API ─→ Jenkins Connector ─→ Normalizer ──→ PULSE DB ──→ Kafka
```

**Eliminamos:**
- DevLake Server (Go)
- DevLake PostgreSQL (ou MySQL)
- DevLake Config UI
- `devlake_reader.py` (272 linhas)
- Toda logica de DevLake API provisioning no NestJS (~400 linhas)

**Re-usamos:**
- `normalizer.py` (539 linhas) — mantem intacto, so muda o input
- `devlake_sync.py` → `data_sync.py` — watermarks + Kafka publishing (adapta ~200 linhas)
- Pipeline Monitor — adapta para monitorar conectores ao inves de DevLake

**Prós:**
- Controle total — sem dependencia de software beta
- Stack simplificado — elimina 2 containers (DevLake + DevLake DB)
- Dados mais ricos — APIs diretas fornecem PR timeline events, first review, approval timestamps que DevLake perde na normalizacao
- Sem dupla normalizacao — Source API → PULSE Normalizer → DB (1 hop, nao 4)
- Python nativo — mesmo stack do resto do pulse-data
- Debugging transparente — sem caixa preta Go
- Comunidade forte — PyGithub, jira-python sao mais estáveis que DevLake
- Customizacao Webmotors — mapeamentos PT-BR, Jenkins patterns, Jira custom fields: controlamos tudo
- Exit strategy planejado — O ADR-001 ja previa isso: "substituir plugins por custom connectors sem impacto ao usuario"

**Contras:**
- **Esforco maior upfront** — ~2-3 semanas para os 3 conectores MVP (GitHub, Jira, Jenkins)
- Rate limiting proprio — Precisamos implementar backoff/retry (PyGithub ja faz isso)
- Paginacao propria — Cada API tem paginacao diferente (PyGithub/jira-python abstraem isso)
- Manter conectores — Se GitHub/Jira mudar API, precisamos atualizar (risco similar ao DevLake)
- Menos "gratis" para novos sources — GitLab/ADO sao ~1 semana cada para construir

**Esforco estimado:** 2-3 semanas (3 conectores MVP)  
**Risco:** Baixo — APIs sao estaveis, bibliotecas sao maduras

---

### Opcao C: Hibrido Pragmatico (Substituicao Gradual)

Manter DevLake para GitHub (que funciona), construir conector proprio para Jira (que esta quebrado), e Jenkins (que ja temos python-jenkins).

**Fase 1 (esta semana):** Conector Jira proprio + Conector Jenkins proprio  
**Fase 2 (proximas 2 semanas):** Conector GitHub proprio  
**Fase 3:** Remover DevLake completamente

**Prós:**
- Desbloqueia Jira imediatamente sem esperar upgrade DevLake
- Migra incrementalmente, menor risco
- Pode validar abordagem com Jira antes de migrar GitHub

**Contras:**
- Complexidade transitoria — dois pipelines rodando em paralelo
- Mais codigo para manter durante a transicao
- DevLake continua consumindo recursos durante a transicao

**Esforco estimado:** 1 semana (Fase 1) + 1-2 semanas (Fase 2)  
**Risco:** Baixo-Medio — complexidade da transicao

---

## 4. Analise Comparativa

| Criterio | Peso | A (DevLake+MySQL) | B (Proprio Total) | C (Hibrido Gradual) |
|----------|------|-------------------|--------------------|----------------------|
| Time-to-unblock Jira | 25% | 1-2 dias (se funcionar) | 3-5 dias | 3-5 dias |
| Estabilidade longo prazo | 25% | ⚠ Baixa (beta eterno) | ✅ Alta | ✅ Alta |
| Simplicidade operacional | 15% | ❌ +MySQL no stack | ✅ -2 containers | ⚠ Transitorio |
| Riqueza de dados | 15% | ❌ Perde timeline events | ✅ Dados completos | ✅ Dados completos |
| Esforco total (4 semanas) | 10% | ✅ Menor | ⚠ Medio | ⚠ Medio |
| Risco de regressao | 10% | ❌ Alto (cada upgrade) | ✅ Baixo | ✅ Baixo |
| **Score ponderado** | | **2.6/5** | **4.3/5** | **3.9/5** |

---

## 5. Recomendacao

**Opcao B — Ingestao Proprietaria Total**, com a seguinte priorizacao:

### Semana 1: Desbloquear Dados
1. **Conector Jira** (~3 dias) — `jira-python`, extrai issues + changelogs + sprints
2. **Conector Jenkins** (~2 dias) — `python-jenkins`, extrai builds de producao

### Semana 2: Completar GitHub
3. **Conector GitHub** (~4 dias) — `PyGithub` + GraphQL para PR timeline
4. **Adaptar sync worker** (~1 dia) — Trocar `DevLakeReader` por `SourceConnectors`

### Semana 3: Limpeza
5. **Remover DevLake** do docker-compose
6. **Adaptar Pipeline Monitor** para monitorar conectores
7. **Testes de integracao** end-to-end

### O que reutilizamos (nao joga fora)
- `normalizer.py` — 100% reuso, so muda a forma como o `raw` dict chega
- `devlake_sync.py` → `data_sync.py` — Watermarks, upserts, Kafka publishing (80% reuso)
- Pipeline Monitor routes — Adapta DevLake health por connector health
- Alembic migrations — Intactas (eng_pull_requests, eng_issues, etc.)
- Kafka topics e metrics worker — Intactos

### O que muda
- `devlake_reader.py` (272 linhas) → `connectors/{github,jira,jenkins}.py` (~1.200 linhas total)
- DevLake API client no NestJS (~400 linhas) → Removido (config via YAML direto)
- `docker-compose.yml` → Remove `devlake` + `devlake-pg` services
- `scripts/bulk_import_repos.py` → Substituido por GitHub connector com auto-discovery

---

## 6. Validacao da Decisao Original

O ADR-001 (Hipotese 3) ja previa explicitamente este cenario:

> *"Se o Apache DevLake perder tracao ou se tornar limitante, substituimos plugins individualmente por conectores customizados sem impacto ao usuario. DevLake e um 'detalhe de implementacao' atras de uma camada de abstracao (o Sync Worker)."*

**Essa abstracao funcionou.** O Sync Worker + Normalizer + Kafka sao a camada que isolou PULSE do DevLake. A substituicao e cirurgica: trocamos a **fonte de dados** do normalizer, nao a arquitetura.

---

## 7. Riscos e Mitigacoes

| Risco | Probabilidade | Mitigacao |
|-------|--------------|-----------|
| APIs mudam (GitHub, Jira) | Baixa | Bibliotecas PyGithub/jira-python sao mantidas por comunidades grandes |
| Rate limiting em org grande | Media | PyGithub tem retry built-in; implementar exponential backoff |
| Backfill lento (1.426 repos) | Media | Paralelizar com asyncio; GraphQL batch queries; incremental |
| Falta GitLab/ADO quando cliente pedir | Baixa (R2+) | python-gitlab e azure-devops-python-api estao prontos; ~1 semana cada |
| Regressao nos dados ja ingeridos | Baixa | Manter DevLake DB como backup read-only por 30 dias |

---

## Apendice: Codigo Existente que Sera Reutilizado

```
Componente                          Linhas    Reuso
──────────────────────────────────────────────────
normalizer.py                        539     ~100%
devlake_sync.py (→ data_sync.py)     552     ~80%
pipeline/routes.py                   350     ~70%
pipeline/models.py                   120     100%
engineering_data/models.py           180     100%
alembic migrations (001-003)         400     100%
metrics_worker                       300+    100%
kafka shared module                  150     100%
──────────────────────────────────────────────────
Total reutilizado                   2.591    ~90%
Total a construir (conectores)     ~1.500    novo
```
