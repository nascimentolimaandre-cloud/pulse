# Deep Dive: Features, Pricing & Modelo de Negócio
## Swarmia · Jellyfish · LinearB

**Data:** Março 2026 | **Versão:** 1.0

---

## SUMÁRIO

1. [Swarmia — Análise Completa](#1-swarmia)
2. [Jellyfish — Análise Completa](#2-jellyfish)
3. [LinearB — Análise Completa](#3-linearb)
4. [Comparativo Feature-by-Feature Detalhado](#4-comparativo)
5. [Análise de Modelos de Preço e Cobrança](#5-precos)
6. [Lacunas e White Spaces Identificados](#6-lacunas)

---

## 1. SWARMIA

### 1.1 Filosofia e Posicionamento

Swarmia se posiciona como uma plataforma **developer-first** de engineering intelligence. O princípio fundador, articulado pelo CEO Otto Hilska, é que não é possível melhorar produtividade de engenharia top-down sem buy-in dos engenheiros. A plataforma foi pensada para ser usada por todos os níveis — do IC ao CTO — com dados transparentes e acessíveis.

Três pilares centrais: **Business Outcomes**, **Developer Productivity** e **Developer Experience**.

### 1.2 Catálogo Completo de Features

#### A) BUSINESS OUTCOMES

**Initiatives (Tracking de Iniciativas)**
- Permite acompanhar iniciativas cross-team em tempo real
- Mostra progresso visual de cada iniciativa com status at-risk
- Agrega issues e PRs de múltiplos times sob uma mesma iniciativa
- Recentemente adicionou initiative forecasting (previsão de conclusão)
- Filtro por time, período, e investment category
- Vista "focus summary" mostra a divisão de foco entre iniciativas

**Investment Balance (Rastreamento de Investimento)**
- Categoriza automaticamente o trabalho de engenharia por tipo (features, bugs, tech debt, maintenance, etc.)
- Usa regras de categorização configuráveis pelo usuário
- Mostra onde o tempo de engenharia está sendo gasto
- Permite criar breakdowns customizados de investimento
- Sistema de "inbox zero" para trabalho não categorizado
- Modelo effort-based lançado em 2024 para entender tempo gasto por tipo de trabalho

**Software Capitalization**
- Lançado em 2024, com melhorias contínuas
- Gera relatórios de capitalização R&D
- Integração com plataformas de HR planejada para 2025 (já em roadmap)
- Rastreamento automático de atividades capitalizáveis vs. não-capitalizáveis
- Exportação de dados para data warehouses externos ("data cloud")

#### B) DEVELOPER PRODUCTIVITY

**Engineering Metrics**
- Cycle time (tempo total do commit ao deploy, quebrado em sub-etapas)
- Throughput (volume de PRs merged)
- PR review time e time to first review
- PR size / batch size (com exclusão inteligente de arquivos auto-gerados)
- Code review turnaround
- Merge frequency
- Benchmarks comparativos vs. indústria

**DORA Metrics**
- Deployment Frequency
- Lead Time for Changes
- Change Failure Rate
- Mean Time to Recovery (nota: alguns usuários reportam que MTTR de incident management não está presente, apenas a versão DORA)
- Filtro por time de engenharia
- Tracking histórico com trends

**CI Visibility**
- Monitoramento de pipelines de CI/CD
- Tempos de build e taxas de falha
- CI failure notifications no Slack (inclui últimas 50 linhas do log de falha diretamente na notificação)
- Identificação de CI checks lentos
- Insights para reduzir wait times

**Sprints**
- Sprint analytics para times Scrum (lançado em 2024)
- Total sprint scope, scope increases, carryover e completion rate
- Tracking de tendências ao longo de múltiplos sprints
- Sprint health overview

**Developer Overview**
- Visão individual do trabalho de cada developer
- PRs abertos, em review, merged
- Workload distribution
- Não é posicionado como "monitoring individual" — a Swarmia enfatiza que é para o próprio developer acompanhar seu trabalho

**Work Log**
- Visão bird's-eye de atividades do time
- Mostra o que cada pessoa está trabalhando em dado período
- Permite identificar trabalho bloqueado e padrões de atividade

#### C) DEVELOPER EXPERIENCE

**Surveys (Pesquisas de Developer Experience)**
- Framework proprietário com **32 perguntas research-backed**
- Possibilidade de **adicionar perguntas customizadas** (ex: sobre Copilot, GraphQL, comunicação cross-team)
- Resultados com análise de áreas mais discutidas e perguntas mais puladas
- Comparação de feedback entre times
- Tracking de mudanças ao longo do tempo
- Correlação automática entre resultados de surveys e métricas quantitativas do sistema
- Integração com Slack para notificar sobre surveys ao vivo e response rates

**Working Agreements**
- Times configuram seus próprios acordos (ex: "PRs devem ser revisados em menos de 4h", "nenhum PR com mais de 400 linhas")
- Tracking automático de aderência aos acordos
- Cada time define o que é relevante para si
- Feedback loops automatizados: se um acordo é violado, o sistema notifica
- Base de dados de exemplos de working agreements de times de alta performance

#### D) AUTOMAÇÃO E NOTIFICAÇÕES

**Slack Notifications**
- Notificações de code review pendente
- Alertas de CI failures (com log inline)
- Daily digest configurável (escolha de dias da semana)
- Issue summary notifications
- Alertas de PRs órfãos / abandoned branches
- Respostas a comentários do GitHub diretamente no Slack
- Notificações pessoais e de time

**Signals (IA)**
- Feature de AI que analisa padrões na organização e surfacea insights automaticamente
- Em vez de só mostrar que cycle time aumentou, diz qual time é afetado, possível causa, e o que organizações similares fizeram
- AI-powered issue grouping (agrupa issues relacionadas automaticamente)
- Smart issue suggestions (vincula PRs a issues certas baseado em código e metadata)

#### E) INTEGRAÇÕES

| Categoria | Ferramentas |
|---|---|
| Source Code | GitHub (principal, mais profundo) |
| Issue Tracker | Jira, Linear |
| Chat | Slack |
| CI/CD | GitHub Actions, CircleCI, e outros via CI visibility |
| AI Tools | Analytics de ferramentas de AI coding (planejado: GenAI/Copilot analytics para 2025) |
| HR | Planejado para 2025 (software capitalization) |
| Data Export | Data cloud para data warehouses |
| Marketplace | Atlassian Marketplace (app para Jira Cloud) |

**Lacuna notável:** Não suporta GitLab, Bitbucket, Azure DevOps, Teams, PagerDuty, ou ferramentas de incident management diretamente.

#### F) SEGURANÇA E COMPLIANCE

- SOC 2 Type 2 compliant
- GDPR compliant (vantagem europeia)
- Auditorias de segurança 2x ao ano
- Não acessa código-fonte — apenas metadata de PRs e issues
- Dados processados na EU (data residency europeia)

### 1.3 Modelo de Preço Swarmia

| Plano | Preço | Público | Features Incluídas |
|---|---|---|---|
| **Startup** | Grátis | Até 9 developers | GitHub insights, Issue tracker insights, Automated reminders |
| **Lite** | €20/dev/mês | 15-150 developers | GitHub insights, DORA metrics, Slack integration, Working agreements configuráveis, In-app chat support |
| **Standard** | €39/dev/mês | 15-150 developers | Tudo do Lite + Issue tracker insights, Investment insights, Flow insights, CSM dedicado |
| **Enterprise** | Custom | 150+ developers | Tudo do Standard + SSO/SAML, team hierarchies complexas, SLA dedicado, data export, software capitalization |

**Notas sobre pricing:**
- Preços em EUR (empresa finlandesa)
- Desconto para pagamento anual (reportado ~10-25% em negociações via Vendr)
- Self-service purchase disponível desde 2024 (sem necessidade de falar com vendas para Lite/Standard)
- Free trial de 14 dias para todos os planos
- Preço por "developer ativo" (não por seat ou contributor — fator importante)
- Enterprise: precisa falar com vendas, sem preço público

**Modelo de negócio:** Land-and-expand. O free tier (Startup) serve como porta de entrada para times pequenos. Quando crescem para 15+ devs, precisam migrar para Lite ou Standard. A progressão Lite → Standard desbloqueia issue tracker insights e investment tracking, que são essenciais para gestores.

---

## 2. JELLYFISH

### 2.1 Filosofia e Posicionamento

Jellyfish é a plataforma mais **enterprise e business-aligned** do mercado. Posicionamento claro: traduzir o trabalho de engenharia em linguagem que CFOs, VPs e board entendem. O modelo patenteado de alocação é o diferencial fundamental — ele automatiza a categorização de onde o esforço de engenharia vai, sem depender de timesheets.

Buyer personas: VP/SVP Engineering, CTO, CFO, Engineering Managers. Mais recentemente: também DevEx teams e ICs (via Jellyfish DevEx free tier).

### 2.2 Catálogo Completo de Features

#### A) ENGINEERING MANAGEMENT PLATFORM (Core)

**Allocation Model (Patenteado)**
- Modelo proprietário que analisa sinais de engenharia (commits, PRs, Jira tickets, calendar events) para determinar automaticamente onde o tempo de engenharia está sendo investido
- Categoriza trabalho por: initiative, project, team, work type (feature, bug, tech debt, KTLO)
- Não requer time tracking manual ou interrupção do developer
- Backfill de 12-18 meses de histórico na primeira configuração (overnight)
- Virtual time cards para visualizar alocação de cada pessoa

**Investment Tracking**
- Dashboard que mostra a distribuição de investimento por iniciativa, produto, ou tipo de trabalho
- Permite que líderes demonstrem ao board onde engenharia está investindo
- Comparativo planned vs. actual investment
- Drill-down de organização → business line → projeto → time → indivíduo
- Visualização de trade-offs (se alocar mais para X, quanto tira de Y)

**Capacity Planning**
- Scenario Planner: simula cenários "what-if" (ex: se contratarmos 5 devs, quando entregamos?)
- Capacity forecasting com base em dados históricos
- Headcount planning integrado com dados de HR
- Resource allocation optimization

**Delivery & Performance Metrics**
- Cycle time (end-to-end e quebrado por fase)
- Throughput de PRs e issues
- Planning accuracy (planned vs. delivered)
- Capacity accuracy (estimado vs. real)
- DORA metrics completos
- Sprint analytics e velocity trends
- Delivery risk indicators
- Burnup charts e progress tracking por initiative

#### B) DEVFINOPS (Módulo Financeiro)

**Software Capitalization**
- Automatiza categorização de atividades capitalizáveis vs. expense
- Gera relatórios audit-ready (SOC-1 compliant)
- Elimina necessidade de timesheets manuais
- Classifica automaticamente trabalho de desenvolvimento como capex/opex
- Case: Priceline reduziu entrevistas de auditoria interna em 80% e capitaliza 5x mais rápido

**R&D Cost Reporting**
- Relatórios financeiros para times de finance
- Tracking de custos por projeto, time, e iniciativa
- Reporting de tax credits de R&D
- Integração com dados de payroll/HR para cálculo de custos

**Budget Alignment**
- Visualização de engineering spend vs. business priorities
- Tracking de headcount costs e contractor spend
- Forecasting de custos futuros baseado em cenários de contratação

#### C) AI IMPACT (Módulo de Medição de IA)

**AI Adoption Tracking**
- Mede adoção de ferramentas como GitHub Copilot, Cursor, Amazon Q
- Dashboard de adoption rates por time, indivíduo, e organização
- Trends de adoção ao longo do tempo

**Multi-Tool Comparison**
- Compara impacto de diferentes AI tools lado a lado
- Ex: Copilot vs. Cursor — qual gera mais impacto em cycle time?
- Métricas: code acceptance rate, PR merge speed, code quality indicators

**AI Spend**
- Tracking de gastos com ferramentas de AI
- ROI calculation: quanto a IA está custando vs. quanto está entregando
- Dashboards para justificar investimento em AI tools para o board

**Code Review Agent Insights**
- Mede impacto de AI code review agents na qualidade do código
- Tracking de auto-approvals vs. human reviews

**Impact Insights**
- Avalia como AI afeta delivery e quality com sinais objetivos do SDLC
- Separa correlação de causalidade (na medida do possível)
- Benchmarks de AI impact vs. organizações similares

#### D) DEVELOPER EXPERIENCE

**Jellyfish DevEx (Free)**
- Produto gratuito lançado como beta
- Developer Experience surveys
- Correlação de sentimento com métricas objetivas de performance
- Diagnóstico de necessidades de equipes

**Team Health Metrics**
- Burnout indicators (workload distribution, after-hours work patterns)
- Engagement metrics
- Qualitative feedback + quantitative signals

#### E) INTEGRAÇÕES (50+)

| Categoria | Ferramentas |
|---|---|
| Source Code | GitHub, GitLab, Bitbucket |
| Project Management | Jira, Azure DevOps (ADO), Linear (recente), Aha!, ProductBoard, ProductPlan |
| CI/CD | Jenkins, CircleCI, GitHub Actions, GitLab CI, Bitbucket Pipelines, + outros |
| Incident Management | PagerDuty, Opsgenie |
| Communication | Slack, Confluence |
| HR/Finance | BambooHR, Workday HCM, dados de payroll |
| Security/Quality | Sonar (integração com SonarQube) |
| AI Tools | GitHub Copilot, Cursor, Amazon Q |
| SSO | Okta, Duo |
| BI/Export | Google Sheets, API, data export |
| Marketplace | AWS Marketplace |

**Diferencial:** Jellyfish tem o ecossistema de integrações mais amplo. São 50+ integrações out-of-the-box, cobrindo praticamente toda a cadeia SDLC + HR + Finance.

#### F) SEGURANÇA E COMPLIANCE

- SOC 2 Type 2
- SOC 1 (para DevFinOps / relatórios financeiros)
- Não acessa código-fonte completo — trabalha com metadata
- Data encryption in transit e at rest
- Role-based access control (RBAC)
- SSO/SAML
- Available on AWS Marketplace (facilita procurement enterprise)

### 2.3 Modelo de Preço Jellyfish

| Atributo | Detalhe |
|---|---|
| **Modelo** | Custom enterprise pricing (sem preço público por tier) |
| **Preço mediano reportado** | ~US$ 19.000/ano (para times menores) |
| **ACV médio** | ~US$ 95.000/ano (enterprise) |
| **Unidade de cobrança** | Por developer monitorado + módulos contratados |
| **Módulos disponíveis** | Engineering Management, DevFinOps, AI Impact, DevEx |
| **Free tier** | Jellyfish DevEx (surveys only — beta) |
| **Contract** | Anual |
| **Expansion model** | Add teams, add modules, add integrations |

**Dinâmica de pricing:**
- Não existe self-service purchase. Todo deal passa por vendas
- Pricing escala com número de developers + breadth de integrações + módulos
- Deals enterprise podem passar de US$ 200K/ano para organizações com 500+ devs
- AWS Marketplace availability ajuda com Enterprise Discount Programs
- Training e support incluídos no preço
- O free DevEx product é estratégia de land-and-expand (atrai orgs menores que depois expandem)

**Modelo de negócio:** Sales-led enterprise SaaS. O Jellyfish tem um sales cycle típico que demonstra valor imediato via backfill histórico na primeira demo. A expansão acontece naturalmente quando mais times são adicionados e novos módulos (DevFinOps, AI Impact) são contratados. O ACV médio de ~$95K indica forte posicionamento enterprise.

---

## 3. LINEARB

### 3.1 Filosofia e Posicionamento

LinearB se diferencia por ser o mais **automation-first** do mercado. Enquanto Jellyfish é analytics-first e Swarmia é developer-first, LinearB aposta na ideia de que insights sem automação são insuficientes. A plataforma vai além de mostrar dados — ela intervém ativamente no fluxo de trabalho via gitStream e WorkerB.

Posicionamento duplo: serve engineering managers (com dashboards e forecasting) E developers (com automação de PR workflow e notificações contextuais). A comunidade **Dev Interrupted** (podcast + newsletter) é um canal de thought leadership muito forte.

### 3.2 Catálogo Completo de Features

#### A) VISIBILITY & METRICS

**DORA Metrics Dashboard**
- Deployment Frequency, Lead Time for Changes, Change Failure Rate, MTTR
- Dashboard gratuito (free tier) — principal ferramenta de aquisição
- Benchmarks vs. categorias DORA (Elite, High, Medium, Low)
- Histórico e trends por time

**Cycle Time Breakdown**
- Coding time (tempo do primeiro commit ao PR)
- Pickup time (tempo até primeiro review)
- Review time (tempo em review ativo)
- Deploy time (tempo do merge ao deploy)
- Cada fase é trackada separadamente para diagnosticar gargalos específicos

**Throughput & Velocity**
- PRs merged por período
- Issues completed
- Story points delivered (se habilitado)
- Velocity como ferramenta diagnóstica (não como KPI)

**Planning Accuracy**
- Ratio de trabalho planejado vs. entregue
- Capacity accuracy (estimado vs. real)
- Tracking de unplanned work vs. planned work
- Sprint predictability scores

**Investment Profile**
- Distribuição de investimento por tipo: new features, enhancements, bugs, KTLO, DevEx
- Customizável por tipo de issue no Jira/tracker
- Comparativo entre projetos novos (mais new features) vs. maduros (mais KTLO)

#### B) WORKFLOW AUTOMATION (Diferencial Principal)

**gitStream (Policy-as-Code para PRs)**
- Motor de automação open-source que aplica políticas ao fluxo de PRs
- Auto-routing: direciona PRs para reviewers certos com base em contexto (quem é expert naquele código, quem tem capacidade)
- Auto-labeling: adiciona labels color-coded com estimated review time
- Auto-approval: aprova automaticamente changes de baixo risco (ex: dependabot minor, docs updates)
- Flag deprecated components: alerta quando PR usa componentes que devem ser substituídos
- Policy-as-code: regras configuráveis via YAML (ou UI)
- Pré-built automations + custom automations
- Dashboard em tempo real mostrando tempo economizado com automações
- Integração com CI/CD, DevSecOps e documentation tools

**WorkerB (Bot Assistant)**
- Bot no Slack/Teams que fornece notificações contextuais
- Alerta sobre PRs parados, reviews pendentes, status updates
- Developer coaching: identifica oportunidades de melhoria individual
- Fomenta hábitos data-driven nos times
- Não é apenas notificação — inclui insights acionáveis
- Diferencial vs. SlackBots de outros tools: WorkerB é proativo e coaching-oriented

**AI Workflows**
- AskAI plugin: acessa modelo de IA da LinearB para code reviews GPT-based
- Automatic PR descriptions: gera descrições de PR automaticamente
- Iteration summary retrospectives automatizadas
- Prompt-based actions customizáveis
- AI-provided recommendations para otimização de processo

#### C) PROJECT MANAGEMENT & FORECASTING

**Project Delivery Tracker**
- Initiatives view com burnup charts
- Progress tracking visual por initiative
- Risk indicators em tempo real
- Scope change tracking

**Monte Carlo Forecasting**
- Simulação probabilística de datas de entrega
- Múltiplos cenários com confidence levels (50%, 75%, 90%)
- Baseado em throughput histórico real (não em estimates)
- Forecast por initiative, epic, ou projeto

**Resource Allocation**
- Visualização de como capacidade está distribuída
- WIP (Work In Progress) per developer
- Detecção de overload e sinais de burnout
- Recomendações de rebalanceamento

**Team Goals**
- Dashboard editável onde o time define suas metas
- Métricas selecionáveis (cycle time target, review time target, etc.)
- Tracking visual de progresso vs. goal
- Usado em retros e 1:1s

#### D) DEVELOPER EXPERIENCE

**DevEx Metrics**
- Métricas SPACE integradas
- Signals de satisfação e saúde do time
- Developer surveys (feature mais recente, lançada 2025)
- AI Insights Dashboard (mede impacto de AI no DevEx)

**GenAI Code Impact**
- Módulo lançado em Jan 2024
- Quantifica ganhos de produtividade do GitHub Copilot e ferramentas similares
- Mede: adoption rate, code acceptance rate, impact on cycle time
- Dashboard para R&D leaders demonstrarem ROI de investimento em AI

**Developer Coaching Dashboard**
- Insights individuais para 1:1s entre manager e developer
- Identifica padrões de melhoria (ex: reviews lentos, PRs muito grandes)
- Não é "ranking" — posicionado como ferramenta de coaching

#### E) SEI+ PLATFORM (Extensibilidade)

**Plugin Marketplace**
- Lançado em Jun 2024
- Plugins para DevEx, platform engineering, security checks
- Policy-as-code capabilities
- Permite que clientes expandam uso ativando módulos pagos adicionais
- Marketplace em crescimento

**Control Plane UI**
- Interface centralizada para ver todas as automações ativas
- Visão cross-repo e cross-org
- Gestão de políticas de gitStream

**MCP Server (Em desenvolvimento)**
- Anunciado em Set 2025
- Model Context Protocol server para integração com AI agents
- Permitirá que AI agents acessem dados de engenharia da LinearB

#### F) INTEGRAÇÕES

| Categoria | Ferramentas |
|---|---|
| Source Code | GitHub, GitLab, Bitbucket, Azure Repos |
| Project Management | Jira, Azure DevOps (Boards) |
| CI/CD | Jenkins, GitHub Actions, GitLab CI, CircleCI |
| Communication | Slack, Microsoft Teams |
| Security/Quality | Sonar, Swimm, Jit |
| AI Tools | GitHub Copilot (via GenAI Impact module) |
| Documentation | Swimm (knowledge management) |

**Nota:** LinearB acessa o **repositório de código completo** (não apenas metadata de PRs). Isso permite análises mais profundas mas levanta preocupações de segurança para empresas sensíveis.

#### G) SEGURANÇA

- SOC 2 Type 2
- Acesso ao código completo (diferente de Swarmia/Jellyfish que usam só metadata)
- SSO/SAML
- Role-based access control
- Opção de data retention configurável

### 3.3 Modelo de Preço LinearB

| Plano | Preço | Público | Features Incluídas |
|---|---|---|---|
| **Free** | $0 | Qualquer tamanho | DORA metrics dashboards, benchmarks básicos, community access |
| **Business** | $49/mês/contributor | Min. 50 contributors | Tudo do Free + gitStream automations, WorkerB, team goals, investment tracking, dev coaching, project forecasting |
| **Enterprise** | Custom | Min. 100 contributors | Tudo do Business + SSO/SAML, advanced RBAC, dedicated CSM, SLA, custom integrations, GenAI Impact module, SEI+ plugins |

**Notas sobre pricing:**
- Cobrança por "contributor" (alguém que faz commits/PRs)
- Free tier é muito generoso para aquisição (DORA dashboards completos)
- Business: $49/mês = $588/contributor/ano (mais caro que Swarmia Standard)
- Enterprise não tem preço público
- Mínimo de 50 contributors no Business (barreira para times pequenos)
- gitStream é open-source e gratuito separadamente, mas a versão enterprise com Control Plane UI e analytics requer plano pago
- Hybrid monetization: per-contributor + usage-based credits (para AI features)

**Revenue estimado:** ~US$ 16M ARR em 2024 (Sacra), crescimento de 45% YoY. Mais de 5.000 times e 500.000 developers no funil (incluindo free users).

**Modelo de negócio:** Product-led growth (PLG) com forte free tier + sales-led enterprise. O DORA dashboard gratuito atrai mais de 1.500 times para o funil. A conversão para paid acontece quando times querem automação (gitStream/WorkerB) e forecasting. A expansão para Enterprise desbloqueia GenAI Impact, SSO e plugins.

---

## 4. COMPARATIVO FEATURE-BY-FEATURE DETALHADO

### 4.1 Métricas e Analytics

| Feature | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| DORA Metrics | ✅ Completo | ✅ Completo | ✅ Completo (free) |
| SPACE Framework | ✅ Nativo | ✅ Integrado | ✅ Integrado |
| Cycle Time Breakdown (por fase) | ✅ | ✅ | ✅✅ (mais granular) |
| Throughput/Velocity | ✅ | ✅ | ✅ |
| Sprint Analytics | ✅ (2024) | ✅ | ✅ |
| Planning Accuracy | ❌ | ✅ | ✅✅ |
| Benchmarks Indústria | ✅ | ✅✅ (maior dataset) | ✅ |
| CI/CD Visibility | ✅✅ (com logs inline) | ✅ | ✅ |
| Custom Metrics | Parcial | ✅ | Parcial |

### 4.2 Business Alignment & Finance

| Feature | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| Investment Tracking | ✅ | ✅✅ (patenteado) | ✅ |
| Software Capitalization | ✅ (básico, 2024) | ✅✅ (SOC-1, audit-ready) | ✅ (básico) |
| R&D Cost Reporting | Parcial | ✅✅ | Parcial |
| Budget Alignment | ❌ | ✅✅ | ❌ |
| Headcount Planning | ❌ | ✅✅ (Scenario Planner) | ❌ |
| Capacity Planning | ❌ | ✅✅ | Parcial |
| Virtual Time Cards | ❌ | ✅ (patenteado) | ❌ |
| CFO/Board Reporting | ❌ | ✅✅ | ❌ |

### 4.3 Developer Experience

| Feature | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| DevEx Surveys | ✅✅ (32 perguntas + custom) | ✅ (DevEx free tier) | ✅ (novo, 2025) |
| Correlação survey ↔ metrics | ✅✅ | ✅ | Parcial |
| Working Agreements | ✅✅ (diferencial) | ❌ | ❌ |
| Developer Coaching | ❌ | ❌ | ✅✅ (WorkerB + Dashboard) |
| Team Goals Setting | ❌ | ✅ | ✅✅ |
| Burnout Detection | Parcial (surveys) | ✅ (after-hours patterns) | ✅ (WIP overload) |
| Developer Overview (individual) | ✅ | ✅ | ✅ |
| Work Log / Activity View | ✅✅ | ✅ | ✅ |

### 4.4 Automação e AI

| Feature | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| PR Workflow Automation | ❌ | ❌ | ✅✅ (gitStream) |
| Bot Assistant (Slack/Teams) | ✅ (notifications) | ❌ | ✅✅ (WorkerB coaching) |
| Auto-approve safe PRs | ❌ | ❌ | ✅ |
| Auto-route reviews | ❌ | ❌ | ✅ |
| AI-powered recommendations | ✅ (Signals, novo) | ❌ | ✅ (AskAI) |
| AI Code Review | ❌ | ❌ | ✅ (AskAI plugin) |
| Auto PR Descriptions | ❌ | ❌ | ✅ |
| AI Issue Grouping | ✅ (novo) | ❌ | ❌ |
| Policy-as-Code | ❌ | ❌ | ✅✅ (gitStream) |
| Plugin Marketplace | ❌ | ❌ | ✅ (SEI+) |

### 4.5 AI Tool Measurement

| Feature | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| AI Adoption Tracking | 🔜 (roadmap 2025) | ✅✅ | ✅ |
| Multi-Tool Comparison | ❌ | ✅✅ (Copilot vs Cursor vs Q) | Parcial |
| AI Spend Tracking | ❌ | ✅ | ❌ |
| AI Impact on Delivery | ❌ | ✅✅ | ✅ (GenAI Code Impact) |
| AI ROI Dashboard | ❌ | ✅✅ | ✅ |
| Code Review Agent Insights | ❌ | ✅ | ❌ |

### 4.6 Forecasting e Planejamento

| Feature | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| Initiative Forecasting | ✅ (novo, básico) | ✅✅ (Scenario Planner) | ✅✅ (Monte Carlo) |
| Project Risk Alerts | ✅ (at-risk indicators) | ✅ | ✅ |
| What-If Scenario Modeling | ❌ | ✅✅ | ❌ |
| Monte Carlo Simulation | ❌ | ❌ | ✅✅ |
| Burnup Charts | ❌ | ✅ | ✅ |

### 4.7 Integrações

| Integração | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| GitHub | ✅✅ (mais profundo) | ✅ | ✅ |
| GitLab | ❌ | ✅ | ✅ |
| Bitbucket | ❌ | ✅ | ✅ |
| Azure DevOps / Repos | ❌ | ✅ (novo, 2025) | ✅ |
| Jira | ✅ | ✅ | ✅ |
| Linear (PM) | ✅ | ✅ (recente) | ❌ |
| Slack | ✅✅ (mais profundo) | ✅ | ✅ |
| Microsoft Teams | ❌ | ❌ | ✅ |
| PagerDuty | ❌ | ✅ | ❌ |
| BambooHR / Workday | ❌ | ✅ | ❌ |
| Sonar | ❌ | ✅ | ✅ |
| AWS Marketplace | ❌ | ✅ | ❌ |
| Total estimado | ~6-8 | ~50+ | ~15-20 |

---

## 5. ANÁLISE COMPARATIVA DE MODELOS DE PREÇO E COBRANÇA

### 5.1 Estrutura de Pricing

| Dimensão | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| **Unidade de cobrança** | Developer ativo | Developer monitorado + módulos | Contributor (committer) |
| **Free tier** | ✅ (até 9 devs) | ✅ (DevEx surveys only) | ✅ (DORA dashboards) |
| **Entry price** | €20/dev/mês (~$22) | ~$19K/ano (custom) | $49/contributor/mês |
| **Mid-tier** | €39/dev/mês (~$43) | ~$50-95K/ano (custom) | Incluso no Business |
| **Enterprise** | Custom | Custom (ACV ~$95K) | Custom |
| **Self-service purchase** | ✅ (Lite e Standard) | ❌ (sales-led) | Parcial (free tier auto, paid via sales) |
| **Minimum seats** | 1 (Startup) / 15 (paid) | ~50+ (enterprise focus) | 50 (Business) |
| **Billing** | Mensal ou anual | Anual | Mensal ou anual |
| **Currency** | EUR | USD | USD |

### 5.2 Custo para Cenários Típicos

**Cenário A: Startup com 20 developers**

| Plataforma | Plano | Custo Anual |
|---|---|---|
| Swarmia Lite | €20 × 20 × 12 | ~€4.800/ano (~$5.300) |
| Swarmia Standard | €39 × 20 × 12 | ~€9.360/ano (~$10.300) |
| LinearB Business | $49 × 20 × 12 | **Não elegível** (min 50) |
| LinearB Free | Free | $0 (DORA apenas) |
| Jellyfish | Custom | **Provavelmente não atende** (foco enterprise) |

**Cenário B: Scale-up com 100 developers**

| Plataforma | Plano | Custo Anual |
|---|---|---|
| Swarmia Standard | €39 × 100 × 12 | ~€46.800/ano (~$51.500) |
| LinearB Business | $49 × 100 × 12 | ~$58.800/ano |
| Jellyfish | Custom | ~$50.000-95.000/ano (estimado) |

**Cenário C: Enterprise com 500 developers**

| Plataforma | Plano | Custo Anual |
|---|---|---|
| Swarmia Enterprise | Custom | Estimado $100K-200K |
| LinearB Enterprise | Custom | Estimado $150K-300K |
| Jellyfish Enterprise | Custom | Estimado $200K-475K (ACV $95K × scale) |

### 5.3 Unit Economics e Go-to-Market

| Dimensão | Swarmia | Jellyfish | LinearB |
|---|---|---|---|
| **GTM Primary** | PLG + sales-assist | Sales-led enterprise | PLG + sales-led enterprise |
| **Sales cycle** | Curto (self-service para < 150 devs) | Médio-longo (enterprise demo cycle) | Médio (free → paid conversion) |
| **Time to value** | Minutos (auto-setup) | Horas (overnight backfill) | Minutos (free DORA) |
| **Expansion motion** | More devs + upgrade tier | More teams + more modules | More contributors + enterprise tier |
| **Key conversion trigger** | 10+ devs (free → Lite), issue tracker needs (Lite → Standard) | Board/CFO needs financial reporting | Automation needs (Free → Business) |
| **Churn risk** | Low (working agreements create stickiness) | Very low (deep integration + financial reporting lock-in) | Medium (free users can churn easily) |

---

## 6. LACUNAS E WHITE SPACES IDENTIFICADOS

### 6.1 Lacunas do Swarmia

1. **Integrações limitadas** — Sem GitLab, Bitbucket, Azure DevOps, Teams. Para empresas que não usam GitHub, Swarmia simplesmente não funciona. Isso é a maior limitação.
2. **Sem workflow automation** — Nenhum equivalente ao gitStream/WorkerB. Insights são ótimos mas não automatiza a melhoria.
3. **Software capitalization ainda imatura** — Básica comparada ao Jellyfish. Sem SOC-1, sem integração HR completa (embora planejada).
4. **Sem AI tool measurement** — Copilot analytics está no roadmap mas não entregue. Jellyfish e LinearB já oferecem.
5. **Forecasting básico** — Initiative forecasting é novo e limitado vs. Monte Carlo (LinearB) ou Scenario Planner (Jellyfish).
6. **Sem incident management** — MTTR de incidentes não é trackeado (apenas DORA MTTR baseado em deploys).
7. **Escalabilidade cross-team** — Reportado como limitado para organizações muito grandes.

### 6.2 Lacunas do Jellyfish

1. **Zero automação de workflow** — Jellyfish mostra onde estão os problemas mas não automatiza a solução. Nenhum bot, nenhum auto-routing de PRs.
2. **Não é developer-friendly** — Posicionamento management-first pode gerar resistência de ICs. "Mais uma ferramenta que o management quer usar pra nos vigiar."
3. **Pricing inacessível para startups/scale-ups** — ACV de $95K exclui 90% do mercado potencial.
4. **Sem AI code review** — Não tem equivalente ao AskAI da LinearB.
5. **Setup mais complexo** — Embora o backfill seja rápido, a configuração completa com HR, finance e todas as integrações pode demorar semanas.
6. **Sem Microsoft Teams support** — Grande gap para empresas que usam stack Microsoft.
7. **Sem free tier real** — O DevEx free é limitado a surveys, não dá visão completa da plataforma.

### 6.3 Lacunas do LinearB

1. **Acesso ao código completo** — Requirement de full code repo access é red flag para muitas empresas enterprise (security, compliance, IP concerns).
2. **Sem DevFinOps maturo** — Software capitalization e financial reporting são básicos comparados ao Jellyfish.
3. **Sem Scenario Planning avançado** — Monte Carlo é bom para previsões mas não permite modeling "what-if" de headcount e budget.
4. **Integrações HR/Finance inexistentes** — Não integra com BambooHR, Workday, dados de payroll.
5. **Working agreements ausentes** — Conceito de working agreements (Swarmia) é poderoso e LinearB não tem equivalente.
6. **Percepção de surveillance** — WorkerB e gitStream podem ser percebidos como micro-management por developers.
7. **Minimum 50 seats no plano pago** — Exclui startups e times pequenos do plano Business.
8. **Developer surveys são novíssimas** — Lançadas em 2025, muito menos maduras que Swarmia (32 perguntas research-backed) ou DX.

### 6.4 White Spaces para um Novo Produto

Com base na análise profunda das três plataformas, os white spaces mais promissores são:

**1. "Full-Stack Intelligence" Acessível**
Combinar: surveys do Swarmia + allocation do Jellyfish + automação do LinearB. Nenhuma plataforma faz os três bem. Um produto que cubra visibility + automation + DevEx + business alignment em um só lugar a um preço mid-market (~$15-30/dev/mês) teria enorme apelo.

**2. Automation-First com Developer Buy-In**
O LinearB tem a melhor automação mas é percebido como management tool. Um produto que embale automações como "developer productivity tools" (não "management monitoring") teria menos resistência. Working agreements (Swarmia) + automação (LinearB) = combinação poderosa.

**3. GitLab + Azure DevOps como first-class citizens**
Swarmia só funciona com GitHub. LinearB e Jellyfish suportam outros mas GitHub é sempre o mais profundo. Empresas Brasil/LatAm usam muito Azure DevOps e GitLab — um produto que tenha essas como integrações de primeira classe teria vantagem regional enorme.

**4. AI-Native desde o design**
Nenhum dos três é verdadeiramente AI-native. Todos adicionaram AI features sobre dashboards existentes. Um produto onde IA é a interface primária (conversational, proativa, que surfacea insights automaticamente) — com dashboards como apoio visual — seria geracionalmente diferente.

**5. DevFinOps Simplificado para Mid-Market**
Jellyfish DevFinOps é excelente mas inacessível (preço + complexidade). Startups e scale-ups também precisam de software capitalization e investment tracking. Um DevFinOps "lite" a $10-20/dev/mês seria disruptivo.

**6. Lean/Agile Metrics Nativos**
Nenhum dos três tem métricas Lean nativas: WIP limits com enforcement, cumulative flow diagrams, flow efficiency, lead time distribution, aging WIP. São métricas complementares ao DORA que muitos Agile coaches e Scrum Masters precisam.

**7. LatAm-First**
Pricing em BRL/moeda local, suporte PT-BR, integrações com Azure DevOps (predominante no enterprise brasileiro), onboarding localizado, case studies regionais. Nenhum competidor faz isso hoje.

---

*Documento preparado para fins de especificação de produto. Dados de março 2026.*
