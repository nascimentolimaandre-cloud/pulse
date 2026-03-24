# PULSE — Especificação de Arquitetura Técnica
## Architecture Decision Record + RNFs

**Versão:** 2.0 | **Data:** Março 2026
**Paradigmas:** DDD, TDD, Event-Driven, Serverless-First

---

# 1. VISÃO GERAL DA ARQUITETURA

## 1.1 Princípios Arquiteturais

| # | Princípio | Implicação Prática |
|---|---|---|
| P1 | **Start Small, Scale Smart** | Lambda + managed services. Pague por uso, não por capacidade ociosa |
| P2 | **Event-Driven First** | Kafka (MSK) como backbone. Lambda triggered by events. REST só para queries do frontend |
| P3 | **Polyglot pragmático** | Node.js (NestJS) para API/app layer. Python (FastAPI) para data/ML. API Gateway unifica |
| P4 | **DDD como guia** | Bounded contexts definem decomposição. Ubiquitous language compartilhada |
| P5 | **TDD como prática** | Testes first para domain logic. Integration tests para APIs. E2E para fluxos críticos |
| P6 | **Local-first** | Todo o stack roda em Docker Compose. Paridade com cloud via containers |
| P7 | **Serverless-First** | Lambda para compute. Managed services para tudo (RDS, MSK, ElastiCache). Zero server management |
| P8 | **Metadata-only** | Nunca armazenar código-fonte. Apenas metadata |

## 1.2 Diagrama de Arquitetura (Serverless / Lambda)

```
                              ┌──────────────────────────────┐
                              │         INTERNET              │
                              └──────────────┬───────────────┘
                                             │
                              ┌──────────────▼───────────────┐
                              │   CloudFront (CDN)            │
                              │   → SPA static assets (S3)    │
                              │   → /api/* → API Gateway      │
                              └──────────────┬───────────────┘
                                             │
                              ┌──────────────▼───────────────┐
                              │      AWS API Gateway          │
                              │   (REST + WebSocket)          │
                              │   Rate Limiting, Auth check   │
                              │   Custom domain + CORS        │
                              └──┬────────────────────────┬──┘
                                 │                        │
                    ┌────────────▼──────┐    ┌───────────▼──────────┐
                    │  Lambda: PULSE    │    │  Lambda: PULSE       │
                    │  API (NestJS)     │    │  Data API (FastAPI)  │
                    │                   │    │                      │
                    │  • Auth/Users     │    │  • Metrics queries   │
                    │  • Teams/Orgs     │    │  • DORA serving      │
                    │  • Integrations   │    │  • Lean serving      │
                    │  • Surveys (R3)   │    │  • Forecasting (R1)  │
                    │  • Goals (R3)     │    │  • Data Export (RN)  │
                    │  • Notifications  │    │                      │
                    └────────┬──────────┘    └──────────┬───────────┘
                             │                          │
                             │    ┌─────────────────┐   │
                             ├───▶│  RDS PostgreSQL  │◀──┤
                             │    │  (via RDS Proxy) │   │
                             │    │  Multi-tenant    │   │
                             │    └─────────────────┘   │
                             │                          │
                             │    ┌─────────────────┐   │
                             ├───▶│  ElastiCache     │◀──┤
                             │    │  Redis           │   │
                             │    └─────────────────┘   │
                             │                          │
                    ┌────────▼──────────────────────────▼───────┐
                    │              AWS MSK (Kafka)               │
                    │              Serverless                    │
                    └────────┬──────────────────────────────────┘
                             │
                    ┌────────▼──────────────────────────────────┐
                    │     Lambda Workers (Python)                │
                    │     Triggered by MSK Event Source Mapping  │
                    │                                            │
                    │  ┌─────────────────────────────────────┐  │
                    │  │  DevLake Sync Lambda                │  │
                    │  │  Trigger: CloudWatch cron (15 min)  │  │
                    │  │  Lê DevLake DB → Publica no Kafka   │  │
                    │  └─────────────────────────────────────┘  │
                    │  ┌─────────────────────────────────────┐  │
                    │  │  Metrics Lambda                     │  │
                    │  │  Trigger: MSK (domain.* topics)     │  │
                    │  │  Calcula métricas → PULSE DB        │  │
                    │  └─────────────────────────────────────┘  │
                    │  ┌─────────────────────────────────────┐  │
                    │  │  Notification Lambda                │  │
                    │  │  Trigger: MSK (notifications.*)     │  │
                    │  │  Envia Slack/Teams/Email             │  │
                    │  └─────────────────────────────────────┘  │
                    └────────────────────────────────────────────┘
                             │
                    ┌────────▼──────────────────────────────────┐
                    │     Apache DevLake (ECS Fargate - 1 task) │
                    │     Único componente que precisa container │
                    │     Plugins: GitHub,GitLab,Jira,ADO       │
                    │     DevLake PostgreSQL (RDS separado)      │
                    │     Configurado via DevLake REST API       │
                    └───────────────────────────────────────────┘
```

## 1.3 Por que Lambda + 1 Container (DevLake)

| Componente | Compute | Justificativa |
|---|---|---|
| **PULSE API (NestJS)** | Lambda | Stateless REST API. Escala a zero. Pay-per-request. NestJS roda em Lambda via `@vendia/serverless-express` |
| **PULSE Data API (FastAPI)** | Lambda | Read-heavy queries. Escala horizontal automática. FastAPI roda em Lambda via `Mangum` adapter |
| **Sync Worker** | Lambda (scheduled) | Roda a cada 15 min via EventBridge rule. Execution time < 15 min (dentro do limite Lambda) |
| **Metrics Worker** | Lambda (MSK trigger) | Event-driven. Processa batch de eventos do Kafka. Escala com throughput |
| **Notification Worker** | Lambda (MSK trigger) | Event-driven. Baixo volume. Ideal para Lambda |
| **DevLake** | **ECS Fargate** (1 task) | DevLake é uma aplicação Go stateful com scheduler interno. Não pode rodar em Lambda. Único container da infra |

**Ponto-chave:** DevLake é o **único componente que precisa de um container persistente**. Todo o resto é serverless.

## 1.4 Lambda — Decisões Técnicas

**NestJS em Lambda:**
```typescript
// lambda.ts (entry point)
import { NestFactory } from '@nestjs/core';
import { ExpressAdapter } from '@nestjs/platform-express';
import serverlessExpress from '@vendia/serverless-express';
import { AppModule } from './app.module';

let cachedServer: any;

export const handler = async (event, context) => {
  if (!cachedServer) {
    const app = await NestFactory.create(AppModule, new ExpressAdapter());
    await app.init();
    cachedServer = serverlessExpress({ app: app.getHttpAdapter().getInstance() });
  }
  return cachedServer(event, context);
};
```

**FastAPI em Lambda:**
```python
# lambda_handler.py
from mangum import Mangum
from src.main import app  # FastAPI app

handler = Mangum(app, lifespan="off")
```

**RDS Proxy (Obrigatório com Lambda):**
Lambda pode criar centenas de conexões simultâneas ao DB. RDS Proxy faz connection pooling transparente, evitando exaustão de conexões PostgreSQL. Custo adicional mínimo (~$15/mês para instância pequena), mas essencial.

**Cold Start Mitigation:**
- Provisioned Concurrency para PULSE API Lambda (1-2 instâncias warm) — custo ~$5-10/mês
- FastAPI Lambda: cold start ~1-2s (aceitável para data queries que não são real-time-critical)
- Workers: cold start irrelevante (processamento async)

---

# 2. ANÁLISE DE FRONTEND — DECISÃO TÉCNICA

## 2.1 Contexto e Requisitos

O PULSE é um **SaaS de área logada** (dashboard application). Isso implica:

- **Sem necessidade de SEO** — 100% área autenticada, zero necessidade de indexação
- **Heavy data visualization** — Gráficos complexos: CFD, Scatterplots, Heatmaps, Stacked Bars, Gauge charts
- **Interatividade alta** — Filtros globais, drill-down, hover tooltips, period selectors, drag-and-drop
- **State complexo** — Filtros persistentes, múltiplos dashboards, dados de múltiplos times simultâneos
- **Real-time updates** — Métricas atualizadas via polling ou WebSocket
- **Responsividade** — Desktop-first, mas funcional em tablet
- **Performance** — Dashboards com 10-20 widgets carregando em < 3 segundos

## 2.2 Análise Comparativa de Frameworks

### Opção A: Next.js (React + SSR/SSG)

| Dimensão | Avaliação |
|---|---|
| **Fit para o caso de uso** | ⭐⭐⭐ — Excelente framework, mas SSR/SSG são irrelevantes para área logada. O App Router adiciona complexidade (Server Components, cache policies) sem benefício para dashboards. Overhead desnecessário |
| **Charting ecosystem** | ⭐⭐⭐⭐⭐ — React tem o maior ecossistema de charting do mercado |
| **Component libraries** | ⭐⭐⭐⭐⭐ — shadcn/ui, Tremor, Ant Design, Mantine — tudo disponível |
| **Performance** | ⭐⭐⭐ — SSR pode até prejudicar dashboards (hydration mismatch com dados dinâmicos) |
| **Complexidade** | ⭐⭐ — App Router, Server Components, client/server boundaries, caching layers — overhead significativo para um SPA |
| **Build/Deploy** | ⭐⭐⭐⭐ — Vercel nativo, mas para S3+CloudFront precisa de export estático ou adapter |
| **Contratação** | ⭐⭐⭐⭐⭐ — Mercado React é o maior |

**Veredicto:** Over-engineered para nosso caso. Next.js brilha em marketing sites, blogs, e-commerce. Para um dashboard SaaS puro, a complexidade do App Router não se justifica.

### Opção B: React + Vite (SPA puro) ✅ RECOMENDADA

| Dimensão | Avaliação |
|---|---|
| **Fit para o caso de uso** | ⭐⭐⭐⭐⭐ — SPA é o modelo ideal para dashboards. Sem SSR overhead. Estado 100% client-side. Routing simples. Hot reload instantâneo |
| **Charting ecosystem** | ⭐⭐⭐⭐⭐ — Mesmo ecossistema React: Recharts, Tremor, ECharts, Nivo, D3 |
| **Component libraries** | ⭐⭐⭐⭐⭐ — shadcn/ui, Tremor, Radix UI, Mantine — tudo funciona |
| **Performance** | ⭐⭐⭐⭐⭐ — Vite build é ultra-rápido. Code splitting automático. Sem hydration overhead |
| **Complexidade** | ⭐⭐⭐⭐⭐ — Simples. React puro. Sem magic framework. O que você escreve é o que roda |
| **Build/Deploy** | ⭐⭐⭐⭐⭐ — `vite build` → pasta `dist/` → S3 + CloudFront. Trivial |
| **Contratação** | ⭐⭐⭐⭐⭐ — React + Vite é o padrão da indústria |

**Veredicto:** Melhor fit. Simplicidade máxima, performance máxima, zero overhead de SSR para um produto que não precisa dele.

### Opção C: Vue 3 + Nuxt

| Dimensão | Avaliação |
|---|---|
| **Fit para o caso de uso** | ⭐⭐⭐⭐ — Vue é excelente para SPAs. Composition API é elegante |
| **Charting ecosystem** | ⭐⭐⭐ — Menor que React. Apache ECharts tem wrapper Vue. Falta equivalentes de Tremor e Nivo |
| **Component libraries** | ⭐⭐⭐ — Vuetify, PrimeVue, Naive UI. Boas, mas menos opções que React |
| **Performance** | ⭐⭐⭐⭐ — Excelente. Vue é mais leve que React |
| **Complexidade** | ⭐⭐⭐⭐ — Simples e opinado |
| **Build/Deploy** | ⭐⭐⭐⭐ — Bom |
| **Contratação** | ⭐⭐⭐ — Mercado menor que React, especialmente para seniores |

**Veredicto:** Boa opção técnica, mas ecossistema de charting e contratação são inferiores a React.

### Opção D: Angular

| Dimensão | Avaliação |
|---|---|
| **Fit para o caso de uso** | ⭐⭐⭐ — Angular é enterprise-grade mas verboso para dashboards |
| **Charting ecosystem** | ⭐⭐⭐ — ngx-charts, Apache ECharts wrapper. Menos opções |
| **Component libraries** | ⭐⭐⭐⭐ — Angular Material, PrimeNG. Maduras mas menos modernas |
| **Performance** | ⭐⭐⭐ — Bundle size maior. Change detection pode ser desafiador com muitos charts |
| **Complexidade** | ⭐⭐ — TypeScript obrigatório, decorators, DI, modules — boilerplate alto |
| **Build/Deploy** | ⭐⭐⭐ — Bom |
| **Contratação** | ⭐⭐⭐ — Mercado existe mas está migrando para React |

**Veredicto:** Excesso de cerimônia para o que precisamos. Não recomendado.

### Opção E: SvelteKit

| Dimensão | Avaliação |
|---|---|
| **Fit** | ⭐⭐⭐⭐ — Reatividade nativa é excelente para dashboards interativos |
| **Charting** | ⭐⭐ — Ecossistema pequeno. LayerCake existe mas é nicho. Falta Tremor/Nivo equivalent |
| **Components** | ⭐⭐ — Skeleton UI, DaisyUI. Muito menos opções |
| **Contratação** | ⭐⭐ — Difícil encontrar devs Svelte seniores |

**Veredicto:** Tecnicamente elegante mas ecossistema imaturo para nosso caso de uso.

## 2.3 Score Consolidado

| Framework | Fit | Charting | Components | Performance | Simplicidade | Contratação | **TOTAL** |
|---|---|---|---|---|---|---|---|
| **React + Vite** | 5 | 5 | 5 | 5 | 5 | 5 | **30/30** ✅ |
| Next.js | 3 | 5 | 5 | 3 | 2 | 5 | 23/30 |
| Vue + Nuxt | 4 | 3 | 3 | 4 | 4 | 3 | 21/30 |
| SvelteKit | 4 | 2 | 2 | 5 | 4 | 2 | 19/30 |
| Angular | 3 | 3 | 4 | 3 | 2 | 3 | 18/30 |

## 2.4 Stack de Frontend Recomendada

```
DECISÃO: React 19 + Vite 6 + TypeScript

┌─────────────────────────────────────────────────────────────┐
│                    PULSE Frontend Stack                      │
│                                                              │
│  Framework:    React 19 + Vite 6 + TypeScript 5.x           │
│  Routing:      TanStack Router (type-safe, file-based)      │
│  State:        Zustand (global) + TanStack Query (server)   │
│  UI Base:      shadcn/ui (Radix + Tailwind, copy-paste)     │
│  Charts:       Tremor (dashboard widgets) + Recharts (base) │
│  Data Tables:  TanStack Table v8 (sorting, filtering, pag.) │
│  Forms:        React Hook Form + Zod (validation)           │
│  HTTP:         Axios or ky                                   │
│  CSS:          Tailwind CSS 4                                │
│  Testing:      Vitest (unit) + Testing Library + Playwright │
│  Build:        Vite → dist/ → S3 + CloudFront              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Por que Tremor + Recharts (e não Apache ECharts ou Nivo)?**

| Critério | Tremor + Recharts | Apache ECharts | Nivo |
|---|---|---|---|
| **Dashboard-specific components** | ✅ KPI cards, spark lines, metric badges built-in | ❌ Charts only, sem dashboard widgets | ❌ Charts only |
| **Tailwind native** | ✅ Built on Tailwind + Radix | ❌ Styling próprio | ❌ Styling próprio |
| **Simplicidade** | ✅ Copy-paste, zero config | ❌ API complexa, declarativa | 🟡 Média |
| **Bundle size** | ✅ Leve (Tremor é tree-shakeable) | ❌ ~800KB full | 🟡 Médio (~300KB) |
| **Chart types para nosso caso** | ✅ Bar, Line, Area, Donut, Scatter — cobre 90% | ✅ Cobre 100% | ✅ Cobre 95% |
| **React-native** | ✅ Built for React | 🟡 Wrapper (`echarts-for-react`) | ✅ Built for React |
| **Vercel/ecosystem** | ✅ Tremor adquirido pela Vercel | ❌ Apache project | ❌ Independent |

**Estratégia de charting progressiva:**
- **MVP → R2:** Tremor + Recharts cobrem 95% dos charts (bar, line, area, scatter, donut, KPI cards)
- **R3+:** Se precisarmos de charts avançados (heatmaps, treemaps, advanced CFD), adicionamos Apache ECharts pontualmente. Não precisa escolher só um — Recharts e ECharts coexistem

**Nota sobre Tremor:** Foi adquirido pela Vercel em 2024, opera como modelo copy-paste (similar ao shadcn/ui) — você copia o código para seu projeto e é dono dele. Sem dependência de runtime.

## 2.5 Estrutura do Frontend

```
pulse-web/
├── src/
│   ├── main.tsx                   # Entry point
│   ├── App.tsx                    # Root component + Router
│   │
│   ├── routes/                    # TanStack Router (file-based)
│   │   ├── _auth/                 # Layout: not-authenticated
│   │   │   ├── login.tsx
│   │   │   └── register.tsx
│   │   ├── _dashboard/            # Layout: authenticated + sidebar
│   │   │   ├── home.tsx           # Home overview
│   │   │   ├── metrics/
│   │   │   │   ├── dora.tsx
│   │   │   │   ├── cycle-time.tsx
│   │   │   │   ├── lean.tsx       # CFD, WIP, Lead Time Dist
│   │   │   │   └── sprints.tsx
│   │   │   ├── teams/
│   │   │   │   ├── index.tsx      # Team list
│   │   │   │   └── $teamId.tsx    # Team detail
│   │   │   ├── integrations/
│   │   │   │   └── index.tsx      # Connect sources
│   │   │   └── settings/
│   │   │       └── index.tsx
│   │   └── __root.tsx
│   │
│   ├── components/
│   │   ├── charts/                # Visualization components
│   │   │   ├── DoraGauge.tsx      # DORA classification badge
│   │   │   ├── CycleTimeBreakdown.tsx  # Stacked bar por fase
│   │   │   ├── CumulativeFlowDiagram.tsx  # Area chart empilhado
│   │   │   ├── LeadTimeScatterplot.tsx    # Scatter + percentil lines
│   │   │   ├── ThroughputRunChart.tsx     # Bar + trend line
│   │   │   ├── WipMonitor.tsx             # Card com alert
│   │   │   ├── SprintBurndown.tsx
│   │   │   └── MetricCard.tsx             # Tremor KPI card
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── TopBar.tsx
│   │   │   └── FilterBar.tsx      # Global filters (team, period)
│   │   └── ui/                    # shadcn/ui components
│   │
│   ├── lib/
│   │   ├── api/                   # API client functions
│   │   │   ├── client.ts          # Axios instance + interceptors
│   │   │   ├── metrics.ts         # getDoraMetrics(), getCycleTime()...
│   │   │   └── integrations.ts
│   │   └── utils/
│   │       ├── date.ts
│   │       └── formatters.ts
│   │
│   ├── hooks/
│   │   ├── useDoraMetrics.ts      # TanStack Query hook
│   │   ├── useCycleTime.ts
│   │   ├── useLeadTimeDistribution.ts
│   │   └── useGlobalFilters.ts    # Zustand + URL sync
│   │
│   └── stores/
│       ├── authStore.ts           # Zustand: user, token, tenant
│       └── filterStore.ts         # Zustand: team, period, project
│
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── vitest.config.ts
└── package.json
```

**Deploy:** `vite build` gera `dist/` (HTML + JS + CSS estáticos) → upload para S3 → CloudFront distribui globalmente. Custo: ~$1-5/mês.

---

# 3. INFRAESTRUTURA AWS (Serverless-First)

## 3.1 Diagrama AWS

```
┌─────────────────────────────────────────────────────────────────┐
│                        AWS Account                               │
│                                                                  │
│  Route53 (DNS) → CloudFront (CDN)                               │
│                    ├── /* → S3 (SPA static files)               │
│                    └── /api/* → API Gateway                     │
│                                                                  │
│  ┌── API Gateway ────────────────────────────────────────────┐  │
│  │  POST/GET /api/v1/*  →  Lambda: pulse-api (NestJS)        │  │
│  │  POST/GET /data/v1/* →  Lambda: pulse-data (FastAPI)      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── VPC (pulse-vpc) ───────────────────────────────────────┐   │
│  │                                                           │   │
│  │  Lambda Functions (VPC-attached para acesso ao RDS):      │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │   │
│  │  │ pulse-api   │ │ pulse-data  │ │ sync-worker │        │   │
│  │  │ 512MB-1GB   │ │ 512MB-1GB   │ │ 1GB-2GB     │        │   │
│  │  │ NestJS      │ │ FastAPI     │ │ Python      │        │   │
│  │  └─────────────┘ └─────────────┘ │ Cron 15min  │        │   │
│  │  ┌─────────────┐ ┌─────────────┐ └─────────────┘        │   │
│  │  │ metrics-    │ │ notification│                          │   │
│  │  │ worker      │ │ -worker     │                          │   │
│  │  │ MSK trigger │ │ MSK trigger │                          │   │
│  │  └─────────────┘ └─────────────┘                          │   │
│  │                                                           │   │
│  │  ┌─────────────────────────────────────────────────┐     │   │
│  │  │  RDS Proxy → RDS PostgreSQL (db.t4g.micro)      │     │   │
│  │  │  Connection pooling para Lambda                  │     │   │
│  │  └─────────────────────────────────────────────────┘     │   │
│  │                                                           │   │
│  │  ┌──────────────┐  ┌──────────────────────────────┐      │   │
│  │  │ ElastiCache  │  │ ECS Fargate (1 task)         │      │   │
│  │  │ Redis        │  │ DevLake container             │      │   │
│  │  │ cache.t4g.   │  │ 1 vCPU, 2GB RAM              │      │   │
│  │  │ micro        │  │ + DevLake PostgreSQL (RDS)    │      │   │
│  │  └──────────────┘  └──────────────────────────────┘      │   │
│  │                                                           │   │
│  │  MSK Serverless (Kafka)                                   │   │
│  │                                                           │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  EventBridge (cron rules para sync-worker)                      │
│  Secrets Manager (tokens, API keys)                              │
│  CloudWatch (logs, metrics, alarms)                              │
│  S3 (SPA dist, backups)                                          │
│  ACM (SSL Certificates)                                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 3.2 Estimativa de Custo (Serverless — MVP)

| Serviço | Config | Custo Estimado/Mês |
|---|---|---|
| **Lambda** (5 functions) | ~500K invocações/mês, avg 500ms | ~$5-15 |
| **API Gateway** | ~500K requests/mês | ~$2-5 |
| **RDS PostgreSQL** | db.t4g.micro (free tier 12 meses) | ~$0-15 |
| **RDS Proxy** | Mínimo | ~$15 |
| **MSK Serverless** | Low throughput | ~$30-50 |
| **ElastiCache Redis** | cache.t4g.micro | ~$12 |
| **ECS Fargate** (DevLake only) | 1 vCPU, 2GB RAM, 1 task | ~$35-45 |
| **S3 + CloudFront** | SPA hosting | ~$2-5 |
| **Route53** | 1 hosted zone | ~$1 |
| **Secrets Manager** | ~10 secrets | ~$4 |
| **CloudWatch** | Logs + basic monitoring | ~$10-15 |
| **TOTAL ESTIMADO** | | **~$120-180/mês** |

**Comparação com versão ECS anterior: economia de ~$80-100/mês** (30-40% menor). E o custo escala linearmente com uso real, não com capacidade provisionada.

## 3.3 Ambientes

| Ambiente | Frontend | Backend | DB | Kafka | DevLake |
|---|---|---|---|---|---|
| **Local** | `vite dev` (HMR) | Docker: NestJS + FastAPI + Workers | PG container | Kafka container | DevLake container |
| **Staging** | S3 + CloudFront | Lambda (API GW) | RDS micro (separado) | MSK Serverless | ECS Fargate |
| **Production** | S3 + CloudFront | Lambda (API GW) | RDS micro/small | MSK Serverless | ECS Fargate |

---

# 4. DOMAIN-DRIVEN DESIGN — BOUNDED CONTEXTS

*(Mantido da v1.0 — estrutura de BCs, schema de banco, e deployment strategy idênticos. A mudança para Lambda é transparente para os bounded contexts.)*

## 4.1 Context Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PULSE Context Map                                  │
│                                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │ IDENTITY &  │    │ INTEGRATION  │    │ ENGINEERING  │                   │
│  │ ACCESS      │◄──▶│ CONTEXT      │───▶│ DATA         │                   │
│  │ (NestJS)    │    │ (NestJS +    │    │ (Python)     │                   │
│  │             │    │  Workers)    │    │              │                   │
│  └─────────────┘    └──────────────┘    └──────┬───────┘                   │
│         │                                       │                           │
│         │           ┌──────────────┐◄───────────┘                           │
│         │           │ METRICS &    │                                        │
│         │           │ ANALYTICS    │    ┌──────────────┐                   │
│         │           │ (FastAPI)    │───▶│ DEVEX (R3)   │                   │
│         │           └──────┬───────┘    │ (NestJS)     │                   │
│         │                  │            └──────────────┘                   │
│         │           ┌──────▼───────┐    ┌──────────────┐                   │
│         └──────────▶│ NOTIFICATION │◄───│ AUTOMATION   │                   │
│                     │ (NestJS+Wrkr)│    │ (R3, NestJS) │                   │
│                     └──────────────┘    └──────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 4.2 Deployment dos BCs

**MVP → R1: Modular Monolith (2 Lambdas + Workers)**

Todos os BCs NestJS vivem no mesmo Lambda function bundle. Todos os BCs Python vivem no mesmo Lambda function bundle. Boundaries via módulos internos.

```
Deployment units:
┌────────────────────────────┐
│  Lambda: pulse-api         │  1 function, múltiplos módulos NestJS
│  ├── modules/identity      │
│  ├── modules/integration   │
│  └── modules/notification  │
└────────────────────────────┘
┌────────────────────────────┐
│  Lambda: pulse-data        │  1 function, múltiplos contexts FastAPI
│  ├── contexts/eng_data     │
│  └── contexts/metrics      │
└────────────────────────────┘
┌────────────────────────────┐
│  Lambda: sync-worker       │  EventBridge cron → reads DevLake DB
│  Lambda: metrics-worker    │  MSK trigger → calcula métricas
│  Lambda: notif-worker      │  MSK trigger → Slack/Teams/Email
└────────────────────────────┘
```

**R2+: Split as needed.** Quando um módulo cresce, extraí-lo para uma Lambda separada é trivial — basta rotear no API Gateway.

---

# 5. KAFKA (MSK) — EVENT-DRIVEN

*(Mantido da v1.0 — topics idênticos, mas consumers são Lambda functions com MSK Event Source Mapping em vez de long-running containers)*

**Lambda + MSK Event Source Mapping:**
```
MSK Topic (domain.pr.normalized)
         │
         ▼
AWS Event Source Mapping (batch size: 100, window: 30s)
         │
         ▼
Lambda: metrics-worker (invocado com batch de 100 eventos)
         │
         ▼
Processa batch → Calcula métricas → Escreve no PULSE DB
```

Benefício: Lambda escala automaticamente com o volume de eventos. Zero gerenciamento de consumers.

---

# 6. DESENVOLVIMENTO LOCAL

## 6.1 Docker Compose (Local Completo)

```yaml
# docker-compose.yml
services:
  # --- Frontend (hot reload, não container) ---
  # Run: cd pulse-web && npm run dev (Vite HMR na porta 5173)

  # --- Backend APIs (containers para paridade) ---
  pulse-api:
    build: ./packages/pulse-api
    ports: ["3000:3000"]
    environment:
      DATABASE_URL: postgresql://pulse:pulse@postgres:5432/pulse
      KAFKA_BROKERS: kafka:9092
      DEVLAKE_API_URL: http://devlake:8080
      REDIS_URL: redis://redis:6379
      NODE_ENV: development
      # Connector tokens (from .env file)
      GITHUB_TOKEN: ${GITHUB_TOKEN:-}
      GITLAB_TOKEN: ${GITLAB_TOKEN:-}
      JIRA_API_TOKEN: ${JIRA_API_TOKEN:-}
      JIRA_EMAIL: ${JIRA_EMAIL:-}
      AZURE_DEVOPS_PAT: ${AZURE_DEVOPS_PAT:-}
    volumes:
      - ./packages/pulse-api/src:/app/src  # Hot reload
      - ./config/connections.yaml:/app/config/connections.yaml:ro
    depends_on: [postgres, kafka, redis]

  pulse-data:
    build: ./packages/pulse-data
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql://pulse:pulse@postgres:5432/pulse
      KAFKA_BROKERS: kafka:9092
    volumes:
      - ./packages/pulse-data/src:/app/src
    depends_on: [postgres, kafka]

  sync-worker:
    build: ./packages/pulse-data
    command: python -m src.workers.devlake_sync
    environment:
      DATABASE_URL: postgresql://pulse:pulse@postgres:5432/pulse
      DEVLAKE_DB_URL: postgresql://devlake:devlake@devlake-pg:5432/lake
      KAFKA_BROKERS: kafka:9092

  metrics-worker:
    build: ./packages/pulse-data
    command: python -m src.workers.metrics_worker
    environment:
      DATABASE_URL: postgresql://pulse:pulse@postgres:5432/pulse
      KAFKA_BROKERS: kafka:9092

  # --- Infrastructure ---
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_DB: pulse, POSTGRES_USER: pulse, POSTGRES_PASSWORD: pulse }
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    ports: ["9092:9092"]
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qk

  # --- DevLake ---
  devlake:
    image: apache/devlake:latest
    ports: ["8080:8080"]
    environment:
      DB_URL: postgresql://devlake:devlake@devlake-pg:5432/lake
      ENCRYPTION_SECRET: ${DEVLAKE_ENCRYPTION_SECRET:-abcdefghijklmnop}
    depends_on: [devlake-pg]

  devlake-pg:
    image: postgres:16-alpine
    environment: { POSTGRES_DB: lake, POSTGRES_USER: devlake, POSTGRES_PASSWORD: devlake }

volumes:
  pgdata:
```

**Workflow do desenvolvedor:**

```bash
# Terminal 1: Infra + backend
make up                    # docker compose up -d

# Terminal 2: Frontend (fora do Docker para HMR instantâneo)
cd packages/pulse-web
npm run dev                # Vite dev server na porta 5173

# Terminal 3: Logs
make logs                  # docker compose logs -f
```

O frontend roda fora do Docker em dev (Vite HMR é ~10x mais rápido sem layer de container). APIs e infra rodam em Docker para paridade com cloud.

---

# 7. CI/CD (GitHub Actions) — Spec

```
Workflows:

ci.yml (todo PR):
  ├── Lint (ESLint + Prettier, Ruff)
  ├── Unit Tests (Vitest, Jest, Pytest)
  ├── Integration Tests (Testcontainers)
  ├── Build Docker images
  ├── Build frontend (vite build)
  ├── Security scan (Trivy)
  └── Coverage report

deploy-staging.yml (push to develop):
  ├── Build Lambda packages (zip)
  ├── Build frontend (vite build)
  ├── Upload SPA to S3, invalidate CloudFront
  ├── Deploy Lambdas via SAM/CDK/Terraform
  ├── Run DB migrations (Lambda one-off)
  ├── Smoke tests
  └── Notify Slack

deploy-prod.yml (push to main + approval):
  ├── Require manual approval
  ├── Same build + deploy steps
  ├── Canary health check
  └── Rollback on failure
```

---

# 8. ESTRATÉGIA DE TESTES (TDD Pragmático)

## 8.1 Pirâmide

```
                    ╱  ╲
                   ╱ E2E╲           ~5% — Playwright
                  ╱      ╲          Login → connect → view DORA
                 ╱────────╲
                ╱Integration╲       ~25% — Testcontainers
               ╱             ╲      API + DB + Kafka reais
              ╱───────────────╲
             ╱   Unit Tests    ╲    ~70% — Vitest, Pytest
            ╱                   ╲   DORA calc, Lean calc, components
           ╱─────────────────────╲
```

## 8.2 Regras por Camada

| Camada | Ferramenta | Coverage Target | TDD? |
|---|---|---|---|
| **Domain Logic (Python)** | Pytest | **≥ 90%** | ✅ Sempre |
| **Domain Logic (Node)** | Jest | **≥ 90%** | ✅ Sempre |
| **API Routes** | Supertest / HTTPX + Testcontainers | **≥ 80%** | Desejável |
| **Workers** | Pytest + Testcontainers | **≥ 75%** | Desejável |
| **Frontend Components** | Vitest + Testing Library | **≥ 60%** | Não obrigatório |
| **Frontend Charts** | Visual regression (Chromatic/Percy) | N/A | Snapshot only |
| **E2E** | Playwright | N/A (por fluxo) | Nunca TDD |

---

# 9. REQUISITOS NÃO-FUNCIONAIS (RNFs)

## 9.1 Performance

| RNF | Requisito | Medição |
|---|---|---|
| **RNF-P1** | Dashboard load < 3s (P95) | API latency < 500ms + frontend render < 2.5s |
| **RNF-P2** | Backfill 3 meses < 30 min | Para org com 100 repos, 10K PRs |
| **RNF-P3** | Data freshness ≤ 15 min | Do evento na fonte até dashboard |
| **RNF-P4** | Lambda cold start < 2s (API), < 5s (Workers) | Provisioned Concurrency para API |
| **RNF-P5** | API suporta 100 req/s por tenant | Load test com k6 |

## 9.2 Scalability

| RNF | Requisito |
|---|---|
| **RNF-S1** | Suportar 50 tenants com config MVP (~$150/mês) |
| **RNF-S2** | Lambda escala automaticamente com demanda (0 → 1000 concurrent) |
| **RNF-S3** | MSK Serverless escala automaticamente |
| **RNF-S4** | RDS vertical scaling até db.r6g.xlarge antes de sharding |

## 9.3 Availability & Security

| RNF | Requisito |
|---|---|
| **RNF-A1** | SLA target: 99.5% (MVP), 99.9% (R2+) |
| **RNF-A2** | RDS Multi-AZ em prod |
| **RNF-A3** | Graceful degradation: DevLake down → dashboards mostram cache |
| **RNF-SEC1** | Metadata-only. Nunca armazenar código |
| **RNF-SEC2** | AES-256 at rest, TLS 1.3 in transit |
| **RNF-SEC3** | OAuth tokens em Secrets Manager |
| **RNF-SEC4** | Row-Level Security (RLS) no PostgreSQL |
| **RNF-SEC5** | OWASP Top 10 compliance |
| **RNF-SEC6** | Dependency scanning no CI (Trivy, npm audit, pip audit) |

## 9.4 Observability & Maintainability

| RNF | Requisito |
|---|---|
| **RNF-O1** | Structured logging JSON (CloudWatch Logs Insights) |
| **RNF-O2** | X-Ray tracing entre Lambdas e serviços |
| **RNF-O3** | Health check endpoints (/health, /ready) |
| **RNF-O4** | Alertas: error rate > 1%, Lambda duration > 10s, sync failures |
| **RNF-M1** | Coverage ≥ 80% domain, ≥ 70% overall |
| **RNF-M2** | Linting enforçado no CI |
| **RNF-M3** | DB migrations versionadas e reversíveis |
| **RNF-M4** | ADRs para decisões significativas |
| **RNF-M5** | README com setup local funcional em < 10 min |

---

# 10. MONOREPO STRUCTURE

```
pulse/
├── .github/workflows/          # CI/CD pipelines
├── packages/
│   ├── pulse-api/              # NestJS (Lambda)
│   │   ├── src/modules/        # DDD bounded contexts
│   │   ├── test/
│   │   ├── lambda.ts           # Lambda entry point
│   │   ├── main.ts             # Local dev entry point
│   │   └── Dockerfile          # Local dev container
│   ├── pulse-data/             # FastAPI + Workers (Lambda)
│   │   ├── src/contexts/       # DDD bounded contexts
│   │   ├── src/workers/        # Lambda worker handlers
│   │   ├── tests/
│   │   ├── lambda_handler.py   # Lambda entry point (Mangum)
│   │   └── Dockerfile          # Local dev container
│   ├── pulse-web/              # React + Vite (SPA)
│   │   ├── src/
│   │   ├── vite.config.ts
│   │   └── package.json
│   └── pulse-shared/           # Shared types, schemas
├── infra/
│   ├── terraform/              # IaC para tudo
│   └── docker/devlake/         # DevLake configs
├── docker-compose.yml          # Local full stack
├── Makefile
├── docs/adrs/
└── README.md
```

---

# 11. DECISION LOG (ADRs Atualizados)

| ADR | Decisão | Justificativa |
|---|---|---|
| ADR-001 | **Modular Monolith em Lambdas** | Start small. DDD boundaries permitem extração futura |
| ADR-002 | **PostgreSQL + RLS** | Multi-tenancy simples e eficaz |
| ADR-003 | **DevLake como pipeline engine** | Acelera MVP. Exit strategy embutida |
| ADR-004 | **MSK Serverless + Lambda triggers** | Event-driven. Lambda escala com eventos. Zero management |
| ADR-005 | **NestJS + FastAPI (polyglot)** | Melhor tool para cada job. API GW unifica |
| ADR-006 | **React + Vite (SPA)** | Dashboard SaaS não precisa de SSR. Simplicidade, performance, ecossistema de charting inigualável |
| ADR-007 | **Lambda + 1 ECS Fargate (DevLake)** | Serverless first. Custo mínimo. DevLake é o único stateful |
| ADR-008 | **Tremor + Recharts** | Dashboard-specific components + React-native charting. Tailwind-native. Cobrem 95% dos charts |
| ADR-009 | **Monorepo (packages/)** | Shared types, atomic PRs, CI unificado |
| ADR-010 | **Testcontainers para integration** | Testes contra PG + Kafka reais |
| ADR-011 | **Metadata-only, nunca código** | Diferencial de segurança |
| ADR-012 | **S3 + CloudFront para SPA** | ~$5/mês, edge global, zero servers |
| ADR-013 | **RDS Proxy obrigatório** | Lambda connection pooling para PostgreSQL |

---

*Documento de arquitetura técnica v2.0 — Serverless (Lambda) + React/Vite SPA.*
