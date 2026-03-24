# PULSE — Análise de Arquitetura do Data Core
## Três Hipóteses para a Fundação de Dados

**Versão:** 1.0 | **Data:** Março 2026

---

## CONTEXTO

A decisão mais crítica da arquitetura do PULSE é **como ingerimos, normalizamos, armazenamos e consultamos dados de engenharia**. Essa camada é o alicerce de todo o produto — se errarmos aqui, toda feature construída sobre ela herda as limitações. Analisamos três hipóteses.

---

# HIPÓTESE 1 — Apache DevLake como Data Core

## O que é o Apache DevLake

Apache DevLake é uma plataforma open-source (Apache Incubator) que ingere, normaliza e visualiza dados de ferramentas DevOps. Escrito em **Go** (com extensão Python via PyDevLake), utiliza **MySQL ou PostgreSQL** como banco e **Grafana** como camada de visualização padrão.

**Arquitetura interna do DevLake (3 camadas):**

```
┌─────────────────────────────────────────────────────┐
│                   DevLake Architecture              │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐       │
│  │  Raw      │   │  Tool    │   │  Domain  │       │
│  │  Layer    │──▶│  Layer   │──▶│  Layer   │       │
│  │          │   │          │   │          │       │
│  │ JSON das │   │ Schema   │   │ Schema   │       │
│  │ APIs     │   │ por tool │   │ unificado│       │
│  │ originais│   │(GitHub,  │   │(PR, Issue│       │
│  │          │   │ Jira...) │   │ Deploy..)│       │
│  └──────────┘   └──────────┘   └──────────┘       │
│                                     │               │
│                              ┌──────▼──────┐       │
│                              │  Grafana    │       │
│                              │  Dashboards │       │
│                              └─────────────┘       │
│                                                     │
│  Componentes: Config UI, API Server, Runner,        │
│  Plugin System, Blueprint/Pipeline Engine           │
└─────────────────────────────────────────────────────┘
```

## Plugins Nativos Disponíveis (relevantes para o PULSE)

| Plugin | Status | Cobre MVP? | Notas |
|---|---|---|---|
| **GitHub** | ✅ Maduro | ✅ PRs, commits, reviews, issues, deployments, Actions | Plugin mais completo |
| **GitLab** | ✅ Maduro | ✅ MRs, commits, pipelines, deployments | Bom coverage |
| **Jira** | ✅ Maduro | ✅ Issues, sprints, boards, status transitions | Plugin robusto |
| **Azure DevOps** | ✅ Disponível | ✅ Repos, boards, pipelines | Cloud only; menos maduro que GitHub/GitLab |
| **Bitbucket** | ✅ Disponível | (R3) | Cloud e Data Center |
| **Jenkins** | ✅ Maduro | (R1) | Builds, jobs, deploys |
| **PagerDuty** | ✅ Disponível | (RN) | Incidents |
| **Opsgenie** | ✅ Disponível | (RN) | Incidents |
| **SonarQube** | ✅ Disponível | (RN) | Code quality |
| **Slack** | ❌ Não existe | (R2) | Precisaria ser desenvolvido |
| **MS Teams** | ❌ Não existe | (R2) | Precisaria ser desenvolvido |
| **Linear** | ❌ Não existe | (RN) | Precisaria ser desenvolvido |
| **ClickUp** | ❌ Não existe | (RN) | Precisaria ser desenvolvido |
| **HR tools** | ❌ Não existe | (R4) | Precisaria ser desenvolvido |

**Cobertura para o MVP: 4/4 fontes essenciais (GitHub, GitLab, Jira, Azure DevOps) já existem nativamente.**

## Domain Layer Model (o que já vem modelado)

O DevLake já possui um **domain layer schema** com 6 domínios normalizados:

| Domínio | Entidades Principais | Relevância PULSE |
|---|---|---|
| **Issue Tracking** | Issues, Boards, Sprints, Issue Labels, Assignees, Status Transitions | 🔴 Crítico — base para Lean metrics, sprint analytics, investment tracking |
| **Source Code Mgmt** | Repos, Commits, Refs (branches/tags) | 🔴 Crítico — base para throughput, code churn |
| **Code Review** | Pull Requests, PR Comments, PR Commits, PR Labels, Reviewers | 🔴 Crítico — base para cycle time, PR analytics |
| **CI/CD** | CI/CD Pipelines, Jobs, Builds, Deployments | 🔴 Crítico — base para DORA metrics |
| **Code Quality** | Projects, Issues (do SonarQube) | 🟡 Futuro (RN) |
| **Cross-Domain** | Issue↔Commit linking, Board↔Repo mapping, Project concept | 🔴 Crítico — vinculação entre domínios |

**O domain model do DevLake já cobre ~80% do modelo de dados necessário para o MVP do PULSE.**

## Métricas Pré-Construídas no DevLake

| Métrica | Disponível? | Notas |
|---|---|---|
| DORA: Deployment Frequency | ✅ | Calculado nativamente |
| DORA: Lead Time for Changes | ✅ | Calculado nativamente |
| DORA: Change Failure Rate | ✅ | Calculado nativamente |
| DORA: MTTR | ✅ | Calculado nativamente |
| Cycle Time (agregado) | ✅ Parcial | Existe mas sem breakdown por fase (Coding/Pickup/Review/Deploy) |
| Throughput | ✅ Parcial | PRs merged disponível via queries |
| PR Size / Review Time | ✅ Parcial | Dados existem, métricas via SQL |
| Sprint analytics | ✅ Parcial | Dados de sprint existem, dashboards básicos |
| CFD / WIP / Lead Time Dist. | ❌ | Dados brutos existem, mas métricas Lean não estão pré-construídas |
| Investment tracking | ❌ | Não existe. Precisaria modelar sobre issue labels/types |
| Working agreements | ❌ | Não existe. Feature de aplicação, não de data |
| Surveys | ❌ | Não existe. Domínio completamente diferente |

## O Que Precisamos Acreditar (Premissas Críticas)

### Premissa 1: É possível expor o DevLake como backend de um SaaS multi-tenant

**Análise:** O DevLake foi desenhado como ferramenta **single-tenant, self-hosted**. Não há conceito nativo de multi-tenancy. Para usar como core de um SaaS, precisamos de uma das abordagens:

- **Opção A — Instance-per-tenant:** Cada cliente recebe uma instância isolada do DevLake (container separado + DB separado). Simples de isolar, mas caro de operar e escalar (100 clientes = 100 instâncias).
- **Opção B — Schema-per-tenant sobre um DevLake modificado:** Fork do DevLake adicionando tenant_id em todas as tabelas. Invasivo e cria divergência permanente do upstream.
- **Opção C — DevLake como engine de ingestão, dados replicados para um DB multi-tenant próprio:** O DevLake ingere e normaliza, depois um processo ETL move os dados do domain layer para um banco próprio do PULSE com multi-tenancy nativa. O DevLake é "internal tool", não é exposto ao usuário.

**Veredicto:** A opção C é a mais viável. O DevLake funciona como **motor de ingestão e normalização** por trás do PULSE, mas não é o banco que a aplicação consulta diretamente.

### Premissa 2: É possível configurar o DevLake via uma interface SaaS do PULSE

**Análise:** O DevLake tem uma **API REST** para gerenciar connections, blueprints, pipelines e scopes. É totalmente possível automatizar a configuração do DevLake via API, sem que o usuário nunca veja a Config UI nativa. O fluxo seria:

```
Usuário PULSE UI → PULSE Backend → DevLake API → DevLake ingere dados → Domain Layer DB
                                                                              │
                                                       PULSE ETL ◄───────────┘
                                                          │
                                                    PULSE App DB (multi-tenant)
                                                          │
                                                    PULSE Frontend (dashboards)
```

**Veredicto:** Viável. A API do DevLake é suficiente para configuração programática completa.

### Premissa 3: É possível adicionar fontes de dados não disponíveis no DevLake

**Análise:** O DevLake suporta dois mecanismos de extensão:
- **Plugin system (Go ou Python/PyDevLake):** Permite criar plugins customizados seguindo o padrão Raw→Tool→Domain.
- **Webhook plugin:** Permite enviar dados de qualquer fonte via HTTP POST, que o DevLake normaliza.
- **dbt plugin:** Permite definir transformações customizadas via dbt (SQL-based).

Para Slack, Teams, Linear, ClickUp, HR tools — podemos criar plugins customizados ou usar webhooks. Para métricas Lean que não existem como dashboards (CFD, WIP, Lead Time Distribution), os **dados brutos já existem** no domain layer; só precisamos calcular as métricas.

**Veredicto:** Viável, com esforço. Plugins customizados em Go/Python são factíveis, mas adicionam complexidade de manutenção e exigem conhecimento do framework DevLake.

## Avaliação Consolidada — Hipótese 1

| Dimensão | Score | Análise |
|---|---|---|
| **Time-to-MVP** | ⭐⭐⭐⭐⭐ | Excelente. 4 conectores prontos + domain model + DORA pré-calculado. Economia de 2-3 meses no MVP |
| **Cobertura de dados MVP** | ⭐⭐⭐⭐ | GitHub, GitLab, Jira, Azure DevOps nativos. Métricas DORA prontas. Lean metrics precisam ser calculadas sobre dados existentes |
| **Multi-tenancy** | ⭐⭐ | Não nativo. Requer arquitetura adicional (DevLake como engine + PULSE DB separado) |
| **Scalability** | ⭐⭐⭐ | Funciona bem para centenas de repos. Para centenas de tenants, precisa de orquestração cuidadosa (Temporal runner existe mas é beta) |
| **Extensibilidade** | ⭐⭐⭐⭐ | Plugin system sólido (Go/Python). Webhook generic. dbt para transformações. Boa extensibilidade |
| **Manutenção longo-prazo** | ⭐⭐⭐ | Depende de projeto Apache open-source (ainda incubating). Risco se o projeto perder tração. Fork cria divergência |
| **Complexidade operacional** | ⭐⭐ | Operar DevLake + PULSE DB + ETL entre eles adiciona moving parts. Precisa orquestrar Docker/K8s do DevLake por tenant ou grupo |
| **Custo de infra** | ⭐⭐⭐ | Open-source = sem custo de licença. Mas precisa de compute para rodar o DevLake + DB separado |
| **Lock-in técnico** | ⭐⭐ | Alto coupling com framework Go do DevLake. Se o projeto mudar direção, ficamos presos |

**Nota geral: 3.2 / 5**

---

# HIPÓTESE 2 — Data Platform do Zero (AWS-Native)

## Descrição

Construir toda a stack de ingestão, normalização, armazenamento e consulta usando serviços AWS (ou equivalentes), sem o DevLake. Isso significa criar cada conector, definir o schema, implementar ETL e calcular métricas manualmente.

## Arquitetura Conceitual

```
┌──────────────────────────────────────────────────────────────────┐
│                     PULSE Data Platform (AWS)                    │
│                                                                  │
│  ┌──────────────┐                                                │
│  │  Connectors  │  GitHub API, GitLab API, Jira API, ADO API    │
│  │  (custom)    │  Cada um = microservice ou Lambda              │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐                                                │
│  │  Raw Storage │  S3 (JSON) ou DynamoDB                        │
│  │              │  API responses brutas                          │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐                                                │
│  │  ETL /       │  AWS Glue, Step Functions, ou custom           │
│  │  Transform   │  Normaliza para schema unificado               │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐                                                │
│  │  PULSE DB    │  PostgreSQL (RDS) com multi-tenancy nativa    │
│  │  (domain     │  Schema unificado: PRs, Issues, Deploys,     │
│  │   layer)     │  Sprints, etc.                                │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐                                                │
│  │  Metrics     │  Materialized views, ou compute layer          │
│  │  Engine      │  que calcula DORA, Lean, etc.                  │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐                                                │
│  │  PULSE App   │  Next.js / React                               │
│  │  (Frontend)  │                                                │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

## O Que Precisamos Construir do Zero

| Componente | Esforço Estimado | Complexidade |
|---|---|---|
| GitHub Connector (OAuth + sync + backfill + incremental) | 3-4 semanas | 🔴 Alta |
| GitLab Connector (token + sync + backfill) | 3-4 semanas | 🔴 Alta |
| Jira Connector (OAuth + sync + backfill + status mapping) | 3-4 semanas | 🔴 Alta |
| Azure DevOps Connector (PAT + sync + backfill) | 3-4 semanas | 🔴 Alta |
| Unified Domain Schema (design + migrations) | 2-3 semanas | 🟡 Média |
| ETL Pipeline (raw → normalized) por conector | 2 semanas/conector | 🟡 Média |
| Issue ↔ PR Linking Logic | 1-2 semanas | 🟡 Média |
| DORA Metrics Calculation Engine | 2-3 semanas | 🟡 Média |
| Backfill Engine (3 meses) | 2-3 semanas | 🔴 Alta |
| Incremental Sync (polling/webhooks) | 2-3 semanas | 🟡 Média |
| API Rate Limit Management (GitHub/GitLab limits) | 1-2 semanas | 🟡 Média |
| Multi-tenancy Architecture | 2-3 semanas | 🟡 Média |
| **TOTAL ESTIMADO** | **~28-38 semanas só para data layer** | |

**Vs. MVP estimado em 12-16 semanas total com DevLake.** O data layer sozinho consumiria 2-3x o tempo total do MVP.

## Avaliação Consolidada — Hipótese 2

| Dimensão | Score | Análise |
|---|---|---|
| **Time-to-MVP** | ⭐ | Péssimo. Só os conectores levam 12-16 semanas. Sem contar métricas, UI, platform. MVP levaria 6-9 meses |
| **Cobertura de dados MVP** | ⭐⭐⭐⭐⭐ | Perfeita — modelamos exatamente o que precisamos, sem limitações de um framework externo |
| **Multi-tenancy** | ⭐⭐⭐⭐⭐ | Nativa desde o design. Sem gambiarras. Schema pensado para SaaS desde o dia 1 |
| **Scalability** | ⭐⭐⭐⭐ | AWS-native escala bem. RDS, Aurora, ou Redshift conforme necessidade |
| **Extensibilidade** | ⭐⭐⭐⭐⭐ | Total controle. Adicionamos qualquer fonte/métrica sem restrições de framework |
| **Manutenção longo-prazo** | ⭐⭐⭐⭐⭐ | Sem dependência de projeto open-source externo. Todo código é nosso |
| **Complexidade operacional** | ⭐⭐⭐⭐ | Stack conhecida (AWS). Menos moving parts que DevLake-sandwiched |
| **Custo de infra** | ⭐⭐⭐ | Serviços AWS têm custo (RDS, Glue, Lambdas, S3). Mas previsível |
| **Lock-in técnico** | ⭐⭐⭐⭐ | Baixo. PostgreSQL + APIs padrão. Migração futura é factível |

**Nota geral: 3.8 / 5** — Mas com a penalidade severa de time-to-MVP.

---

# HIPÓTESE 3 — HÍBRIDA: DevLake como Accelerator + PULSE App DB (RECOMENDADA)

## Conceito Central

Usar o Apache DevLake **exclusivamente como motor de ingestão e normalização** (data pipeline engine) no backend, mas construir a **camada de aplicação, multi-tenancy, métricas avançadas e toda a UX** sobre um banco de dados próprio do PULSE. O DevLake é um "implementation detail" que o usuário nunca vê.

À medida que o produto amadurece, ganhamos a opção de substituir progressivamente os plugins do DevLake por conectores próprios quando/se necessário — sem impacto ao usuário.

## Arquitetura Conceitual

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           PULSE Platform                                     │
│                                                                              │
│   USUÁRIO                                                                    │
│     │                                                                        │
│     ▼                                                                        │
│  ┌──────────────────┐                                                        │
│  │  PULSE App       │  Next.js + React                                       │
│  │  (Frontend)      │  Dashboards, Surveys, Automations                      │
│  └────────┬─────────┘                                                        │
│           │                                                                  │
│  ┌────────▼─────────┐                                                        │
│  │  PULSE API       │  Node.js/Python (FastAPI)                              │
│  │  (Backend)       │  REST API, Auth, Multi-tenant, Business Logic           │
│  └────────┬─────────┘                                                        │
│           │                                                                  │
│  ┌────────▼─────────────────────────────────────┐                            │
│  │           PULSE App Database                  │                            │
│  │           PostgreSQL (multi-tenant)           │                            │
│  │                                               │                            │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────────┐  │                            │
│  │  │ Domain  │ │ Metrics  │ │ App-specific │  │                            │
│  │  │ Layer   │ │ Pre-calc │ │ Tables       │  │                            │
│  │  │(PR,Issue│ │(DORA,Lean│ │(Teams,Users, │  │                            │
│  │  │Deploy..)│ │ Cycle T.)│ │ Surveys,Goals│  │                            │
│  │  └─────────┘ └──────────┘ │ Agreements,  │  │                            │
│  │                           │ Alerts,Config)│  │                            │
│  │                           └──────────────┘  │                            │
│  └──────────────────▲───────────────────────────┘                            │
│                     │                                                        │
│           ┌─────────┴──────────┐                                             │
│           │  PULSE Sync Worker │  Lê do DevLake Domain Layer                 │
│           │  (ETL interno)     │  Transforma + enriquece                     │
│           │                    │  Escreve no PULSE App DB                    │
│           └─────────▲──────────┘                                             │
│                     │                                                        │
│  ┌──────────────────┴───────────────────────────────────┐                    │
│  │              Apache DevLake (interno)                 │                    │
│  │              "Data Pipeline Engine"                   │                    │
│  │                                                       │                    │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │                    │
│  │  │GitHub  │ │GitLab  │ │ Jira   │ │ Azure  │       │                    │
│  │  │Plugin  │ │Plugin  │ │Plugin  │ │DevOps  │       │                    │
│  │  └────────┘ └────────┘ └────────┘ └────────┘       │                    │
│  │                                                       │                    │
│  │  Raw Layer → Tool Layer → Domain Layer (DevLake DB)  │                    │
│  │                                                       │                    │
│  │  Configurado via DevLake API (não exposto ao user)   │                    │
│  └───────────────────────────────────────────────────────┘                    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────┐                    │
│  │  Futuro: Conectores Próprios (quando necessário)     │                    │
│  │  Slack Bot, Teams Bot, Linear, ClickUp, HR           │                    │
│  │  → Escrevem direto no PULSE App DB (bypassam DevLake)│                    │
│  └──────────────────────────────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Como Funciona — Fluxo de Dados

```
1. Usuário configura conexão na UI do PULSE (ex: "Conectar GitHub")
         │
         ▼
2. PULSE Backend chama DevLake API para criar connection + blueprint
         │
         ▼
3. DevLake executa pipeline: GitHub API → Raw → Tool → Domain Layer
         │
         ▼
4. PULSE Sync Worker detecta novos dados no DevLake Domain Layer
         │
         ▼
5. Sync Worker transforma, enriquece e escreve no PULSE App DB
   - Adiciona tenant_id
   - Calcula métricas derivadas (DORA, Lean, Cycle Time Breakdown)
   - Vincula a teams, initiatives, goals (entidades PULSE-only)
         │
         ▼
6. PULSE App DB atualizado → Frontend renderiza dashboards em tempo real
```

## Por que Essa Arquitetura Resolve os Dois Problemas

| Problema da H1 | Como H3 resolve | Problema da H2 | Como H3 resolve |
|---|---|---|---|
| Multi-tenancy não nativa | PULSE App DB é multi-tenant desde o design | Time-to-MVP enorme | DevLake cobre 4 conectores + domain model de graça |
| Grafana como UI | Grafana substituído por frontend próprio | Reinventar conectores | Não reinventa; usa plugins existentes |
| DevLake é single-tenant | DevLake roda como infra interna, não é exposto | Rate limit management | DevLake SDK já cuida disso |
| Métricas Lean não existem | Calculadas no PULSE Sync Worker | Backfill engine complexo | DevLake já resolve backfill |
| Features de app (surveys, goals) | Tabelas app-specific no PULSE DB | API parsing de 4 fontes | DevLake já parseia todas |

## Estratégia de Multi-Tenancy para DevLake

Para o MVP (poucos clientes), a opção mais pragmática:

**Fase 1 (MVP-R1): Shared DevLake Instance**
- Uma instância DevLake compartilhada entre todos os tenants
- PULSE Sync Worker adiciona tenant_id ao mover dados para o PULSE DB
- Funciona para dezenas de clientes com orgs de tamanho médio

**Fase 2 (R2+): Pool de DevLake Instances**
- Conforme escala cresce, orquestramos múltiplas instâncias DevLake
- Kubernetes operator ou ECS tasks para provisionar
- Cada cluster de tenants compartilha uma instância

**Fase 3 (RN): Migração gradual para conectores próprios**
- Quando um plugin DevLake se torna limitante, substituímos por conector próprio
- O conector próprio escreve direto no PULSE DB, bypassing DevLake
- Migration path suave, sem breaking changes

## Avaliação Consolidada — Hipótese 3

| Dimensão | Score | Análise |
|---|---|---|
| **Time-to-MVP** | ⭐⭐⭐⭐⭐ | Excelente. Conectores e domain model do DevLake aceleram enormemente. Foco do time em UI, métricas e UX |
| **Cobertura de dados MVP** | ⭐⭐⭐⭐ | 4 conectores nativos + domain model. Lean metrics precisam ser calculadas no Sync Worker, mas dados brutos existem |
| **Multi-tenancy** | ⭐⭐⭐⭐ | Nativa no PULSE App DB. DevLake é infra interna sem multi-tenancy, mas isolado do usuário |
| **Scalability** | ⭐⭐⭐⭐ | PULSE DB escala com PostgreSQL/Aurora. DevLake pode ser escalado em pool. Path para substituição futura |
| **Extensibilidade** | ⭐⭐⭐⭐⭐ | Melhor dos dois mundos: plugins DevLake para o existente, conectores próprios para o novo. Zero lock-in |
| **Manutenção longo-prazo** | ⭐⭐⭐⭐ | Se DevLake morrer, migramos gradualmente para conectores próprios. PULSE DB é nosso, sem dependência |
| **Complexidade operacional** | ⭐⭐⭐ | Mais moving parts (DevLake + Sync Worker + PULSE DB). Mas cada parte tem responsabilidade clara |
| **Custo de infra** | ⭐⭐⭐⭐ | DevLake é open-source. PULSE DB em PostgreSQL. Sem licenças. Compute é o principal custo |
| **Lock-in técnico** | ⭐⭐⭐⭐⭐ | Mínimo. DevLake é substituível peça a peça. PULSE DB é nosso. Frontend é independente |

**Nota geral: 4.3 / 5** ✅

---

# COMPARATIVO FINAL DAS 3 HIPÓTESES

| Dimensão | H1 (DevLake Core) | H2 (Do Zero) | H3 (Híbrida) ✅ |
|---|---|---|---|
| Time-to-MVP | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| Multi-tenancy | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Scalability | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Extensibilidade | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Manutenção LP | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Complexidade Ops | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Lock-in | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **MÉDIA** | **3.0** | **3.4** (penalizada pelo tempo) | **4.3** ✅ |

---

# RECOMENDAÇÃO

## Hipótese 3 — Híbrida — é a recomendação clara.

**Razões:**

1. **Speed-to-market sem dívida técnica.** Usamos o DevLake como acelerador do MVP sem criar acoplamento irreversível. Os conectores maduros (GitHub, GitLab, Jira, ADO) nos poupam meses de trabalho de parsing de APIs.

2. **Liberdade arquitetural total.** O PULSE App DB é nosso, com multi-tenancy nativa, métricas customizadas, e tabelas de domínio de aplicação (surveys, goals, agreements, etc.) que o DevLake nunca vai ter.

3. **Exit strategy embutida.** Se o Apache DevLake perder tração ou se tornar limitante, substituímos plugins individualmente por conectores próprios sem nenhum impacto ao usuário. O DevLake é um "implementation detail" atrás de uma abstraction layer (o Sync Worker).

4. **Foco onde importa.** O time de produto foca em UX, métricas diferenciais (Lean/Agile) e experiência do usuário em vez de reconstruir parsers de API do GitHub pela milésima vez.

## Tech Stack Sugerida (Alto Nível)

| Camada | Tecnologia | Justificativa |
|---|---|---|
| **Frontend** | Next.js + React + Tailwind | SSR para performance, ecossistema maduro, contratação fácil |
| **Backend API** | Node.js (NestJS) ou Python (FastAPI) | Ambos viáveis. Python tem vantagem para data/ML futuro |
| **PULSE App DB** | PostgreSQL (AWS RDS ou Supabase) | Maduro, multi-tenant via row-level security, excelente para analytics SQL |
| **DevLake Instance** | Docker/ECS com PostgreSQL | Deploy via Terraform. Config via API REST |
| **Sync Worker** | Worker process (Node/Python) | Lê DevLake DB → transforma → escreve PULSE DB. Roda a cada 15 min |
| **Cache/Real-time** | Redis | Cache de dashboards, session, rate limiting |
| **Auth** | Auth0 ou Supabase Auth | OAuth providers, SSO, RBAC |
| **Infra** | AWS (ECS ou EKS) + Terraform | Ou Vercel (frontend) + Railway/Render (backend) para MVP lean |
| **Observabilidade** | Datadog ou OpenTelemetry + Grafana | Monitoring da infra e do data pipeline |

## Próximos Passos Técnicos

1. **PoC do Sync Worker** — Construir um protótipo que leia do DevLake Domain Layer e escreva em um PostgreSQL multi-tenant. Validar que dados fluem corretamente.
2. **PoC do DORA Calculator** — Implementar as 4 métricas DORA sobre dados do PULSE DB e comparar com os valores calculados pelo DevLake para validar accuracy.
3. **PoC do CFD/Lean** — Implementar CFD e Lead Time Distribution sobre os dados de issues normalizados para validar que o domain model suporta métricas Lean.
4. **PoC da configuração via API** — Automatizar a criação de connection + blueprint no DevLake via API a partir de um OAuth flow no PULSE frontend.

---

*Documento de análise arquitetural para decisão de fundação técnica do PULSE.*
