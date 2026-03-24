# PULSE — Release Plan v3.0
## MVP Ultra-Lean: Connect → Collect → Calculate → Display

**Versão:** 3.0 | **Data:** Março 2026

---

## MUDANÇAS vs v2.0

| Item | v2.0 | v3.0 (atual) | Para onde foi |
|---|---|---|---|
| Tela de login (SSO Google/GitHub) | MVP | **R1** | Não necessário para validar hipótese |
| Onboarding wizard (5 steps) | MVP | **R1** | Configuração estática no MVP |
| Criar org / convidar membros | MVP | **R1** | Single-tenant estático no MVP |
| Status mapping UI | MVP | **R1** | Mapping via arquivo de config |
| Seleção de repos via UI | MVP | **R1** | Repos configurados via env/config |
| OAuth flow para conectores | MVP | **R1** | Tokens configurados via env vars (Secrets) |
| Team management UI | MVP | **R1** | Teams definidos via config file |

**O que permanece no MVP:** Pipeline de dados (DevLake + PULSE DB), conectores funcionando (via config estática), cálculo de métricas, e TODOS os dashboards/visualizações.

---

## LÓGICA DAS ONDAS (v3.0)

```
MVP              R1                R2                 R3                R4              RN
PIPELINE &       ONBOARD &         MANAGEMENT         DEVEX &           INTELLIGENCE   SCALE
DASHBOARDS       SELF-SERVICE      LAYER              AUTOMATION        & FINANCE

┌────────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐  ┌────────────┐  ┌─────────┐
│ Conectores │  │ Login/Auth   │  │ Investment     │  │ Surveys      │  │ AI Conver- │  │ Plugin  │
│ (config    │  │ SSO          │  │ tracking       │  │ Working      │  │ sational   │  │ Mktplace│
│  estática) │  │              │  │                │  │ Agreements   │  │            │  │         │
│            │  │ Onboarding   │  │ Forecasting    │  │              │  │ DevFinOps  │  │ On-prem │
│ Data Lake  │  │ wizard       │  │                │  │ Team Goals   │  │            │  │         │
│ (DevLake + │  │              │  │ Executive      │  │              │  │ AI Tool    │  │ Data    │
│  PULSE DB) │  │ Team mgmt   │  │ views          │  │ Automation   │  │ Impact     │  │ Export  │
│            │  │ UI           │  │                │  │ Engine       │  │            │  │         │
│ DORA dash  │  │              │  │ Notifications  │  │              │  │ Predictive │  │ Advanced│
│ Lean dash  │  │ Repo select  │  │ bot            │  │ Coaching     │  │ Risk       │  │ Lean    │
│ Sprint dash│  │ UI           │  │                │  │              │  │            │  │         │
│ Home page  │  │              │  │                │  │              │  │            │  │         │
│            │  │ Dashboards   │  │                │  │              │  │            │  │         │
│ Filtros    │  │ avançados    │  │                │  │              │  │            │  │         │
└────────────┘  └──────────────┘  └───────────────┘  └──────────────┘  └────────────┘  └─────────┘

 Personas:        Personas:          Personas:           Personas:         Personas:
 EM (manual       EM + Dev           CTO + EM            Dev + EM          CTO + CFO
 config)          (self-service)
```

---

# 🏁 MVP — "PIPELINE & DASHBOARDS"

## Hipótese

> É possível conectar nas principais bases de código e métricas (Jira, GitHub, GitLab, Azure DevOps) via configuração estática, coletar dados no data lake (DevLake + PULSE DB multi-tenant), calcular métricas DORA e Lean/Agile, e exibir dashboards que entreguem valor a engineering managers na primeira sessão de uso?

## Critérios de Sucesso

| Critério | Meta |
|---|---|
| Conexão funcional com 4 fontes via config estática | Sim |
| Backfill de 3 meses de dados | < 30 min |
| DORA metrics renderizando corretamente | 4/4 |
| Lean metrics renderizando (CFD, WIP, Lead Time Dist) | 3/3 |
| Sprint analytics renderizando | Sim |
| Dashboard home com métricas-chave | Sim |
| Tempo do `docker compose up` até dashboard com dados | < 45 min (15 config + 30 backfill) |
| Beta users dizem "substituiria minha planilha" | > 60% |

## Como Funciona a Config Estática (sem UI)

As conexões com repositórios e trackers são configuradas via **environment variables e arquivo de configuração YAML**, não via interface. Isso é minimamente seguro e suficiente para validar a hipótese.

```yaml
# config/connections.yaml (montado como volume no Docker, ou em Secrets Manager na AWS)
tenant:
  id: "default-tenant"
  name: "Acme Corp"

teams:
  - name: "Backend"
    repos:
      - source: github
        org: "acme-corp"
        repos: ["api-service", "auth-service", "payment-service"]
      - source: jira
        project_key: "BACK"
        board_id: 42
    status_mapping:
      "Backlog": "backlog"
      "To Do": "todo"
      "In Development": "in_progress"
      "Code Review": "in_review"
      "QA": "in_review"
      "Done": "done"
      "Deployed": "done"
  
  - name: "Frontend"
    repos:
      - source: github
        org: "acme-corp"
        repos: ["web-app", "design-system"]
      - source: jira
        project_key: "FRONT"
        board_id: 43
    status_mapping:
      "Backlog": "backlog"
      "In Progress": "in_progress"
      "Review": "in_review"
      "Done": "done"

connections:
  github:
    type: "github"
    token: "${GITHUB_TOKEN}"           # Env var, nunca hardcoded
    org: "acme-corp"
  
  gitlab:
    type: "gitlab"
    token: "${GITLAB_TOKEN}"
    url: "https://gitlab.com"          # ou self-managed URL
  
  jira:
    type: "jira"
    token: "${JIRA_API_TOKEN}"
    email: "${JIRA_EMAIL}"
    url: "https://acme-corp.atlassian.net"
  
  azure_devops:
    type: "azure_devops"
    token: "${AZURE_DEVOPS_PAT}"
    org: "acme-corp"

deploy_config:
  github:
    strategy: "tags"                    # tags | releases | github_actions
    production_pattern: "^v\\d+\\.\\d+\\.\\d+$"
  gitlab:
    strategy: "pipeline_environment"
    environment: "production"
```

```bash
# .env (local dev — NÃO commitado no Git)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
JIRA_API_TOKEN=ATATT3xxxxxxxxxxx
JIRA_EMAIL=carlos@acme.com
GITLAB_TOKEN=glpat-xxxxxxxxxx
AZURE_DEVOPS_PAT=xxxxxxxxxxxxxxxxxx
```

**Segurança mínima:**
- Tokens NUNCA no código ou no YAML. Sempre via environment variables
- `.env` no `.gitignore`
- Em staging/prod: AWS Secrets Manager
- O YAML referencia `${VAR}` que o sistema resolve dos env vars
- Acesso metadata-only (tokens com permissão de read, nunca write)

---

## Escopo do MVP — 3 Épicos, ~27 Stories

### ÉPICO 1 — Data Pipeline (Conectar + Coletar)

**Objetivo:** Dados fluem das fontes para o PULSE DB, normalizados e prontos para cálculo de métricas.

```
Config YAML → PULSE Bootstrap → DevLake API (create connections) → DevLake sync
→ DevLake Domain DB → Sync Worker → Kafka → Metrics Worker → PULSE DB
```

**Feature Set 1.1 — Bootstrap & Config Loader**

| Story ID | User Story (técnica) | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-1.1.1 | Como sistema, preciso ler `connections.yaml` + env vars no startup e configurar o DevLake automaticamente | DADO que `connections.yaml` e env vars estão configurados QUANDO o sistema inicia (bootstrap) ENTÃO ele cria as connections no DevLake via API, configura blueprints com os repos listados, e inicia o primeiro sync | 🔴 Alta |
| MVP-1.1.2 | Como sistema, preciso ler a configuração de `teams` do YAML e criar os registros correspondentes no PULSE DB | DADO que `connections.yaml` tem 2 teams definidos QUANDO o bootstrap roda ENTÃO existem 2 registros em `iam_teams` com os repos e boards associados | 🟡 Média |
| MVP-1.1.3 | Como sistema, preciso ler o `status_mapping` do YAML e usar para normalizar status de issues | DADO que o mapping define "In Development" → "in_progress" QUANDO uma issue do Jira com status "In Development" é sincronizada ENTÃO no PULSE DB ela aparece com `normalized_status = "in_progress"` | 🟡 Média |
| MVP-1.1.4 | Como sistema, preciso configurar deploy detection conforme `deploy_config` do YAML | DADO que deploy strategy = "tags" com pattern regex QUANDO DevLake importa tags do GitHub ENTÃO deployments são registrados no PULSE DB | 🟡 Média |

**Feature Set 1.2 — GitHub Connector (via DevLake)**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-1.2.1 | Como sistema, preciso que o DevLake GitHub plugin importe PRs, commits, reviews e deploy events dos repos configurados | DADO que `connections.yaml` lista 3 repos do GitHub QUANDO o sync executa ENTÃO DevLake Domain DB contém PRs, commits e reviews desses 3 repos dos últimos 3 meses | 🟡 Média |
| MVP-1.2.2 | Como sistema, preciso detectar deployments do GitHub (tags/releases/Actions) conforme config | DADO que deploy_config.github.strategy = "tags" QUANDO tags matching o pattern são criadas ENTÃO deployment events são registrados | 🟡 Média |

**Feature Set 1.3 — GitLab Connector (via DevLake)**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-1.3.1 | Como sistema, preciso que o DevLake GitLab plugin importe MRs, commits e pipelines dos projetos configurados | DADO que config tem projetos GitLab QUANDO sync executa ENTÃO MRs e pipeline data estão no DevLake Domain DB | 🟡 Média |

**Feature Set 1.4 — Jira Connector (via DevLake)**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-1.4.1 | Como sistema, preciso que o DevLake Jira plugin importe issues, sprints e status transitions dos boards configurados | DADO que config tem Jira project BACK board 42 QUANDO sync executa ENTÃO issues com status_transitions completos estão no DevLake Domain DB | 🟡 Média |

**Feature Set 1.5 — Azure DevOps Connector (via DevLake)**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-1.5.1 | Como sistema, preciso que o DevLake Azure DevOps plugin importe PRs, work items e pipelines | DADO que config tem Azure DevOps org/project QUANDO sync executa ENTÃO dados estão no DevLake Domain DB | 🔴 Alta |

**Feature Set 1.6 — Data Pipeline Core**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-1.6.1 | Como sistema, preciso normalizar dados de GitHub/GitLab/ADO em modelo unificado de PullRequest | DADO que DevLake tem PRs do GitHub e MRs do GitLab QUANDO Sync Worker processa ENTÃO PULSE DB tem registros normalizados em `eng_pull_requests` com campos padronizados (created_at, first_review_at, merged_at, deployed_at, etc.) | 🔴 Alta |
| MVP-1.6.2 | Como sistema, preciso normalizar dados de Jira/ADO Boards em modelo unificado de Issue com status_transitions | DADO que DevLake tem issues do Jira QUANDO Sync Worker processa ENTÃO PULSE DB tem registros em `eng_issues` com status_transitions JSONB, started_at, completed_at, e lead_time/cycle_time calculados | 🔴 Alta |
| MVP-1.6.3 | Como sistema, preciso vincular Issues ↔ PRs automaticamente via branch name ou commit message | DADO que PR branch = "feature/BACK-123-add-payment" QUANDO Sync Worker processa ENTÃO `eng_pull_requests.linked_issue_ids` contém ref para issue BACK-123 | 🟡 Média |
| MVP-1.6.4 | Como sistema, preciso de backfill engine que importe 3 meses de histórico e sync incremental a cada 15 min | DADO que bootstrap completou QUANDO DevLake termina o primeiro sync ENTÃO Sync Worker processa todo o backlog E depois roda incrementalmente a cada 15 min | 🔴 Alta |
| MVP-1.6.5 | Como sistema, preciso publicar eventos normalizados no Kafka (domain.pr.normalized, domain.issue.normalized, domain.deployment.normalized) | DADO que Sync Worker processou dados QUANDO escreve no PULSE DB ENTÃO também publica no Kafka topic correspondente | 🟡 Média |
| MVP-1.6.6 | Como sistema, preciso que o Metrics Worker consuma eventos do Kafka e calcule métricas pre-agregadas em `metrics_snapshots` | DADO que eventos de PR/Issue/Deploy chegam no Kafka QUANDO Metrics Worker processa ENTÃO `metrics_snapshots` contém métricas calculadas por team/period/type | 🟡 Média |

**Total Épico 1: 14 stories**

---

### ÉPICO 2 — DORA & Delivery Metrics (Calcular + Exibir)

**Objetivo:** Dashboards DORA e Cycle Time funcionando com dados reais.

**Feature Set 2.1 — DORA Metrics**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-2.1.1 | Como EM, quero ver **Deployment Frequency** por time e período | DADO que deployments estão no PULSE DB QUANDO acesso /metrics/dora ENTÃO vejo MetricCard com valor (deploys/week), trend %, sparkline, e classificação DORA | 🟡 Média |
| MVP-2.1.2 | Como EM, quero ver **Lead Time for Changes** com breakdown | DADO que PRs têm timestamps de commit→deploy QUANDO acesso /metrics/dora ENTÃO vejo lead time mediano e gráfico de evolução semanal | 🟡 Média |
| MVP-2.1.3 | Como EM, quero ver **Change Failure Rate** | DADO que deploys têm flag `is_failure` QUANDO acesso /metrics/dora ENTÃO vejo % de failures e trend | 🟡 Média |
| MVP-2.1.4 | Como EM, quero ver **MTTR** | DADO que deploys falhos têm link para deploy de correção QUANDO acesso /metrics/dora ENTÃO vejo MTTR médio e trend | 🟡 Média |
| MVP-2.1.5 | Como EM, quero ver **classificação DORA** (Elite/High/Medium/Low) por métrica e overall | DADO que 4 métricas estão calculadas QUANDO vejo o dashboard ENTÃO badges coloridos mostram classificação por métrica + overall | 🟢 Baixa |

**Feature Set 2.2 — Cycle Time & Throughput**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-2.2.1 | Como EM, quero ver **Cycle Time Breakdown** por fase (Coding/Pickup/Review/Merge/Deploy) | DADO que PRs têm timestamps por fase QUANDO acesso /metrics/cycle-time ENTÃO vejo stacked bar horizontal com cada fase, bottleneck highlighted | 🟡 Média |
| MVP-2.2.2 | Como EM, quero ver **Cycle Time Trend** ao longo de semanas | DADO que tenho 3 meses de dados QUANDO vejo trend ENTÃO line chart com cycle time por semana e phases togglable | 🟡 Média |
| MVP-2.3.1 | Como EM, quero ver **Throughput** (PRs merged/semana) com trend | DADO que PRs merged estão no DB QUANDO acesso /metrics/throughput ENTÃO bar chart com throughput semanal + trend line | 🟢 Baixa |
| MVP-2.3.2 | Como EM, quero ver **PR Analytics** (tamanho médio, first review time, review turnaround) | DADO que PRs estão no DB QUANDO acesso /metrics/throughput ENTÃO vejo MetricCards com cada métrica + distribution charts | 🟡 Média |
| MVP-2.3.3 | Como EM, quero ver **lista de PRs abertas** com idade, tamanho e status de review | DADO que PRs abertas existem QUANDO acesso /prs ENTÃO tabela sortable: título, autor, repo, idade, tamanho, reviewers, status | 🟢 Baixa |

**Total Épico 2: 10 stories**

---

### ÉPICO 3 — Lean/Agile Metrics + Platform Shell (Calcular + Exibir + Navegar)

**Objetivo:** Métricas Lean (diferencial competitivo) + shell do dashboard (sidebar, filtros, home).

**Feature Set 3.1 — Lean Flow Metrics**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-3.1.1 | Como Agile Coach, quero ver **Cumulative Flow Diagram** por time | DADO que issues têm status_transitions QUANDO acesso /metrics/lean ENTÃO area chart empilhado com 5 estágios ao longo de semanas | 🟡 Média |
| MVP-3.1.2 | Como EM, quero ver **WIP atual** com alerta quando excede threshold | DADO que threshold está configurado (ex: 15) QUANDO acesso dashboard ENTÃO card mostra WIP atual, progress bar, e alerta se acima do limit | 🟡 Média |
| MVP-3.1.3 | Como Agile Coach, quero ver **Lead Time Distribution** com percentis P50/85/95 | DADO que issues concluídas existem QUANDO acesso /metrics/lean ENTÃO histograma com bins + linhas verticais P50/85/95 | 🟡 Média |
| MVP-3.1.4 | Como EM, quero ver **Throughput Run Chart** com moving average | DADO que issues concluídas existem QUANDO acesso /metrics/lean ENTÃO bar chart (items/week) + trend line (4w moving avg) | 🟢 Baixa |
| MVP-3.1.5 | Como Agile Coach, quero ver **Scatterplot de Lead Time** com outliers | DADO que issues concluídas existem QUANDO acesso /metrics/lean/scatterplot ENTÃO scatter chart com cada issue como ponto, P50/85/95 lines, outliers em vermelho | 🟡 Média |

**Feature Set 3.2 — Sprint Basics**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-3.2.1 | Como Scrum Master, quero ver **Sprint Overview** (committed, added, completed, carryover + burndown) | DADO que sprints estão importados QUANDO acesso /metrics/sprints ENTÃO vejo cards de resumo + burndown chart | 🟡 Média |
| MVP-3.2.2 | Como Scrum Master, quero **comparar sprints** ao longo do tempo | DADO que tenho 6+ sprints QUANDO acesso comparativo ENTÃO bar chart committed vs completed + scope creep % trend | 🟡 Média |

**Feature Set 3.3 — Dashboard Shell (Mínimo para navegação)**

| Story ID | User Story | Acceptance Criteria | Complexidade |
|---|---|---|---|
| MVP-3.3.1 | Como EM, quero uma **sidebar** com navegação para todas as seções de métricas | DADO que acesso o app QUANDO a página carrega ENTÃO sidebar mostra: Home, DORA, Cycle Time, Throughput, Lean & Flow, Sprints, Open PRs, Integrations (status only) | 🟢 Baixa |
| MVP-3.3.2 | Como EM, quero **filtrar métricas por time e período** (global filter no TopBar) | DADO que tenho 2+ times configurados QUANDO seleciono "Backend" + "Last 30d" ENTÃO todas as métricas na página filtram para aquele time/período | 🟡 Média |
| MVP-3.3.3 | Como EM, quero uma **home page** com overview de métricas-chave (MetricCards) | DADO que métricas estão calculadas QUANDO acesso / (home) ENTÃO vejo 6 MetricCards: Deploy Freq, Lead Time, Change Fail Rate, Cycle Time, WIP, Throughput + seção "PRs Needing Attention" | 🟡 Média |
| MVP-3.3.4 | Como EM, quero ver **status das integrações** (read-only, sem config UI) | DADO que conexões estão configuradas via YAML QUANDO acesso /integrations ENTÃO vejo cards mostrando: fonte, status (active/syncing/error), último sync, repos monitorados | 🟢 Baixa |
| MVP-3.3.5 | Como sistema, preciso de **skeleton loading** em todos os componentes que recebem dados async | DADO que dados estão carregando QUANDO a página renderiza ENTÃO componentes mostram skeleton shimmer (não spinner) | 🟢 Baixa |

**Total Épico 3: 12 stories**

---

## Resumo do MVP v3.0

| Épico | Stories | Foco |
|---|---|---|
| Épico 1 — Data Pipeline | 14 | Conectores (config estática), DevLake, normalização, Kafka, metrics worker |
| Épico 2 — DORA & Delivery | 10 | DORA dashboard, Cycle Time, Throughput, PR analytics |
| Épico 3 — Lean + Shell | 12 | CFD, WIP, Lead Time, Sprints, Sidebar, Filtros, Home |
| **TOTAL** | **36** | |

**Redução vs v2.0:** De 39 stories para 36. Mas a redução real de esforço é maior porque as stories removidas (login, OAuth, onboarding wizard com 5 steps, team management UI) eram complexas em UX.

**Estimativa revisada: 10-14 semanas** com time de 4-5 devs.

---

## O que foi para R1

O R1 agora absorve tudo que saiu do MVP + o que já era R1:

### 🚀 R1 — "ONBOARD & SELF-SERVICE" (novo nome)

**Hipótese:** Com self-service (login, onboarding, config via UI), times adotam o produto sem intervenção manual e DAU/MAU > 40%?

```
Features que vieram do MVP:
  ■ Login page (Google/GitHub SSO)
  ■ Onboarding wizard (5 steps)
  ■ OAuth flow para conectores (substituindo config estática)
  ■ Seleção de repos via UI
  ■ Status mapping UI
  ■ Criar org + convidar membros
  ■ Team management UI

Features já previstas para R1:
  ■ Cross-team comparison (heatmap)
  ■ Trends + anomaly detection
  ■ Metric drill-down
  ■ Custom dashboards
  ■ CI/CD visibility
  ■ Quality signals
  ■ Flow Efficiency
  ■ Aging WIP
  ■ Monte Carlo "When" forecast
  ■ SLE Tracking
  ■ Sprint Health Score
  ■ Email alerts + weekly digest
  ■ Developer Overview + Work Log
```

R2, R3, R4 e RN permanecem inalterados da v2.0.

---

## VISUAL DO STORY MAP v3.0

```
JORNADA ► CONNECT(static)  OBSERVE           UNDERSTAND       NAVIGATE
          ───────────────  ────────────      ────────────     ────────────

 MVP      ■ Config YAML    ■ DORA 4 metrics                   ■ Sidebar
 ░░░░     ■ GitHub conn.   ■ DORA Classify                    ■ TopBar+Filters
          ■ GitLab conn.   ■ Cycle Time Brkdn                 ■ Home overview
          ■ Jira conn.     ■ Cycle Time Trend                 ■ Integration
          ■ ADO conn.      ■ Throughput                         status (r/o)
          ■ Deploy config  ■ PR Analytics                     ■ Skeleton
          ■ Status mapping ■ Open PR list                       loading
            (YAML)         ■ CFD
          ■ Team config    ■ WIP Monitor
            (YAML)         ■ Lead Time Dist.
          ■ Data pipeline  ■ Scatterplot
            (normalize)    ■ Throughput Run
          ■ Backfill 3m    ■ Sprint Overview
          ■ Sync 15min     ■ Sprint Compare
          ■ Kafka events
          ■ Metrics Worker

 R1       ■ Login SSO      ■ Cross-team Comp ■ Flow Effic.    ■ Onboarding
 ▒▒▒▒     ■ OAuth flows    ■ Trends+Anomaly  ■ Aging WIP        Wizard
          ■ Repo select UI ■ Drill-down      ■ MC "When"     ■ Org+Members
          ■ Status map UI  ■ Custom Dashb.   ■ SLE           ■ Team Mgmt UI
                           ■ CI/CD Vis.      ■ Sprint Health ■ Dev Overview
                           ■ Quality Signals ■ Planning Acc. ■ Work Log

 R2       ■ Slack          ■ Invest. Trend   ■ Invest. Cat.  ■ Exec Dashb.
 ▓▓▓▓     ■ MS Teams       ■ Invest. Compare                 ■ PDF Export
          ■ SSO/SAML                                          ■ Sched.Reports
          ■ API REST

 R3                                          ■ Survey↔Metrics■ Working Agr.
 ████                                        ■ DevEx Score   ■ Team Goals
                                                              ■ DevEx Surveys
                                                              ■ Coaching Dash

 R4                                          ■ AI Signals    ■ DevFinOps
 ████                                        ■ NL Queries    ■ SW Capital.
                                             ■ Predictive    ■ AI Tool Impact
```

---

## FLUXO DO USUÁRIO NO MVP (sem login, sem onboarding)

```
1. Ops/Admin configura connections.yaml + .env com tokens
                    │
2. make setup (docker compose up + migrations + bootstrap)
                    │
3. Bootstrap lê YAML → cria connections no DevLake → inicia sync
                    │
4. DevLake importa dados (backfill ~15-30 min)
                    │
5. Sync Worker + Metrics Worker processam dados → PULSE DB
                    │
6. Usuário abre http://localhost:5173
                    │
7. Cai direto na HOME (sem login)
   ┌─────────────────────────────────────┐
   │ Home: 6 MetricCards + PRs list      │
   │ Sidebar: navegar para DORA, Lean... │
   │ FilterBar: selecionar Team + Period │
   └─────────────────────────────────────┘
                    │
8. Navega pelo produto, explora métricas
```

**Não há tela de login.** O MVP assume single-tenant, acesso direto. A autenticação virá no R1.

**Segurança mínima para o MVP:**
- Tokens de API armazenados em env vars (nunca no código)
- `.env` no `.gitignore`
- Em staging: Secrets Manager
- O app não é exposto na internet pública no MVP (roda local ou em VPN de staging)
- Multi-tenancy estrutural existe no DB (tenant_id, RLS) mas com um único tenant "default"

---

*Release Plan v3.0 — MVP ultra-lean focado em pipeline de dados + dashboards. Auth, onboarding e self-service vão para R1.*
