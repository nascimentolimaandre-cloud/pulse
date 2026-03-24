# PULSE — Frontend Design Documentation
## Product Designer Specification for Development

**Versão:** 1.0 | **Data:** Março 2026
**Papel:** Product Designer / Design Lead

---

# 1. DESIGN PLAYBOOK

## 1.1 Design System Foundation

### Stack Técnica do Design System

| Camada | Tecnologia | Função |
|---|---|---|
| **Framework** | React 19 + TypeScript 5.x | Componentes declarativos, type-safe |
| **Build** | Vite 6 | Hot Module Replacement, fast builds |
| **CSS** | Tailwind CSS 4 | Utility-first, tokens via CSS variables |
| **Primitivos UI** | Radix UI | Headless, acessível, unstyled primitives (dialog, dropdown, tooltip, etc.) |
| **Component Library** | shadcn/ui | Copy-paste components sobre Radix + Tailwind. Dono do código |
| **Dashboard Widgets** | Tremor | KPI cards, spark lines, metric badges, progress bars |
| **Charts** | Recharts (primário) + Apache ECharts (avançados, se necessário) | Gráficos de barra, linha, área, scatter, stacked, donut |
| **Data Tables** | TanStack Table v8 | Sorting, filtering, pagination, column resize |
| **Forms** | React Hook Form + Zod | Validação type-safe, performance |
| **State (server)** | TanStack Query v5 | Cache, refetch, stale-while-revalidate |
| **State (client)** | Zustand | Filtros globais, auth, preferences |
| **Routing** | TanStack Router | Type-safe, file-based, search params sync |
| **Icons** | Lucide React | Consistente, tree-shakeable, MIT license |
| **Motion** | Framer Motion (pontual) | Transições de page, skeleton → content |
| **Testes** | Vitest + Testing Library + Playwright | Unit, component, E2E |

### Design Tokens (Tailwind CSS Variables)

```css
/* globals.css — Design Tokens PULSE */
:root {
  /* Colors — Semantic */
  --color-bg-primary: #FFFFFF;
  --color-bg-secondary: #F9FAFB;      /* gray-50 */
  --color-bg-tertiary: #F3F4F6;       /* gray-100 */
  --color-bg-surface: #FFFFFF;
  --color-bg-elevated: #FFFFFF;

  --color-text-primary: #111827;       /* gray-900 */
  --color-text-secondary: #6B7280;     /* gray-500 */
  --color-text-tertiary: #9CA3AF;      /* gray-400 */
  --color-text-inverse: #FFFFFF;

  --color-border-default: #E5E7EB;     /* gray-200 */
  --color-border-subtle: #F3F4F6;      /* gray-100 */

  /* Brand */
  --color-brand-primary: #6366F1;      /* indigo-500 */
  --color-brand-primary-hover: #4F46E5;/* indigo-600 */
  --color-brand-light: #EEF2FF;        /* indigo-50 */

  /* Semantic Status */
  --color-success: #10B981;            /* emerald-500 */
  --color-warning: #F59E0B;            /* amber-500 */
  --color-danger: #EF4444;             /* red-500 */
  --color-info: #3B82F6;               /* blue-500 */

  /* DORA Classification */
  --color-dora-elite: #10B981;         /* emerald */
  --color-dora-high: #3B82F6;          /* blue */
  --color-dora-medium: #F59E0B;        /* amber */
  --color-dora-low: #EF4444;           /* red */

  /* Chart Palette (6 cores distintas para series) */
  --chart-1: #6366F1;   /* indigo — primary series */
  --chart-2: #8B5CF6;   /* violet */
  --chart-3: #EC4899;   /* pink */
  --chart-4: #F59E0B;   /* amber */
  --chart-5: #10B981;   /* emerald */
  --chart-6: #6B7280;   /* gray */

  /* Spacing scale (Tailwind default + custom) */
  --space-page-padding: 1.5rem;        /* 24px */
  --space-card-padding: 1.25rem;       /* 20px */
  --space-section-gap: 1.5rem;         /* 24px */

  /* Radius */
  --radius-card: 0.75rem;             /* 12px */
  --radius-button: 0.5rem;            /* 8px */
  --radius-badge: 9999px;             /* pill */

  /* Shadows */
  --shadow-card: 0 1px 3px rgba(0,0,0,0.05);
  --shadow-elevated: 0 4px 12px rgba(0,0,0,0.08);
}

/* Dark mode (futuro - R2+) */
.dark {
  --color-bg-primary: #0F172A;         /* slate-900 */
  --color-bg-secondary: #1E293B;       /* slate-800 */
  --color-text-primary: #F1F5F9;       /* slate-100 */
  --color-border-default: #334155;     /* slate-700 */
}
```

### Tipografia

| Uso | Font | Weight | Size | Line Height |
|---|---|---|---|---|
| **H1 (page title)** | Inter | 600 (semi) | 24px / `text-2xl` | 1.3 |
| **H2 (section)** | Inter | 600 | 18px / `text-lg` | 1.4 |
| **H3 (card title)** | Inter | 500 (medium) | 14px / `text-sm` | 1.5 |
| **Body** | Inter | 400 | 14px / `text-sm` | 1.5 |
| **Metric Value (KPI)** | Inter | 700 (bold) | 28px / `text-3xl` | 1.2 |
| **Metric Label** | Inter | 400 | 12px / `text-xs` | 1.5 |
| **Code/Mono** | JetBrains Mono | 400 | 13px | 1.5 |

### Grid e Layout

```
Sidebar (fixa, 240px) + Content Area (flexível)

┌─────────┬──────────────────────────────────────────────────┐
│         │  TopBar (56px height)                             │
│         │  [Breadcrumb] [Global Filters: Team | Period]     │
│ Sidebar ├──────────────────────────────────────────────────┤
│ 240px   │                                                   │
│ fixed   │  Content Area                                     │
│         │  max-width: 1440px                                │
│         │  padding: 24px                                    │
│         │                                                   │
│ Logo    │  Grid: CSS Grid / Flexbox                         │
│ Nav     │  Cards: min-width 280px, gap 24px                │
│ Teams   │  Charts: responsive, maintain aspect ratio        │
│ Settings│                                                   │
│         │                                                   │
└─────────┴──────────────────────────────────────────────────┘

Breakpoints:
  - Desktop: > 1280px (full sidebar + content)
  - Tablet: 768-1280px (sidebar collapsa para icons)
  - Mobile: < 768px (sidebar vira drawer, não prioritário MVP)
```

## 1.2 Análise Competitiva de UX — Oportunidades

### Padrões Observados nos Concorrentes

| Padrão | Swarmia | Jellyfish | LinearB | PULSE (nossa oportunidade) |
|---|---|---|---|---|
| **Estética** | Clean, minimalista, light mode only. Espaço branco generoso. Tipografia limpa | Corporativo, denso. Muitas tabelas, UX datada. Light mode. Parece "enterprise old-school" | Funcional mas carregado. Muitos elementos na tela. Dashboards com excesso de informação | **Modern minimal** inspirado em Linear/Vercel. Densidade controlada. Light mode (dark mode como R2+) |
| **Navegação** | Sidebar limpa com agrupamento lógico. Fácil de achar features | Sidebar complexa. Muitos níveis. Sprint insights enterrados, difícil achar dados | Sidebar funcional mas com muitos itens. Curva de aprendizado reportada | **Sidebar flat** com no máximo 2 níveis. ⌘K para busca global. Progressive disclosure |
| **Filtros** | Filtro de time no topo. Período selecionável. Limpo | Filtros existem mas são complexos. Customização confusa | Filtros por time e período. Funcional | **FilterBar persistente** no TopBar. Team + Period + Project. Persiste ao navegar. URL sync |
| **Métricas** | Cards com valor + trend arrow. Sparklines. Foco em trends, não valores absolutos | Cards densos com muitos números. Menos ênfase visual em trends | Cards com valor, trend, e benchmark. Boa hierarquia | **MetricCard** com: valor big number, trend ↑↓, sparkline, e tooltip com contexto. Clicável para drill-down |
| **Charts** | Limpos, pouco interativos. Sem drill-down. Poucos tipos de chart | Mais variedade mas UX de interação fraca. Charts não conectam entre si | Charts funcionais. Benchmarks visuais nos gráficos (linhas de referência) | **Charts com interação rica**: hover tooltips com contexto, click para drill-down, linhas de referência (targets/benchmarks), zoom temporal |
| **Onboarding** | Excelente. Setup em poucos minutos. Valor imediato | Complexo. Semanas para full setup. Precisa consultoria | Setup pode ser complexo. Learning curve reportada | **Wizard de 5 passos** com progress bar. Primeiro dashboard com dados em < 15 min |
| **Empty States** | Não documentado | Não documentado | Não documentado | **Empty states ricos** com ilustração + CTA claro: "Conecte seu GitHub para ver métricas aqui" |
| **Loading** | Não documentado | Lento para carregar reportado | Não documentado | **Skeleton screens** (não spinners). Shimmer animation. Progressivo: cards carregam independentemente |

### 5 Vantagens Competitivas de Design

1. **"One glance, one insight"** — Cada card conta UMA história. Valor + trend + contexto. Sem sobrecarga cognitiva. Inspirado na filosofia Swarmia de trends > raw numbers, mas com interatividade que Swarmia não tem.

2. **Drill-down universal** — Qualquer métrica é clicável. DORA score → quais deploys contribuíram → detalhe do deploy. Jellyfish e Swarmia não fazem isso bem. LinearB faz parcialmente.

3. **FilterBar always-on** — Filtros globais (Team, Period, Project) sempre visíveis no TopBar. Persistem entre páginas. Sincronizados com URL (deep-linkable). Nenhum concorrente faz URL sync de filtros.

4. **Lean metrics nativas com visualização elegante** — CFD, Scatterplot, Lead Time Distribution não existem em nenhum concorrente. Teremos os gráficos Lean mais bonitos do mercado (Kanban community vai adorar).

5. **Onboarding → Valor em 15 min** — Wizard guiado + empty states ricos + first dashboard com dados reais. Swarmia é bom aqui mas podemos ser ainda melhor com preview de "como vai ficar" durante o setup.

---

# 2. COMPONENTES DO DESIGN SYSTEM

## 2.1 Atomic Components (Base — shadcn/ui + Tremor)

| Componente | Origem | Uso |
|---|---|---|
| `Button` | shadcn/ui | Primary, Secondary, Ghost, Destructive. Sizes: sm, md, lg |
| `Input`, `Select`, `Checkbox` | shadcn/ui | Formulários |
| `Dialog`, `Sheet`, `Popover` | shadcn/ui (Radix) | Modais, painéis laterais, popovers |
| `Dropdown Menu` | shadcn/ui (Radix) | Ações contextuais |
| `Tabs` | shadcn/ui (Radix) | Navegação intra-page |
| `Tooltip` | shadcn/ui (Radix) | Contexto on-hover |
| `Badge` | shadcn/ui | Status indicators, labels |
| `Skeleton` | shadcn/ui | Loading states |
| `Toast` | shadcn/ui (Sonner) | Notificações transientes |
| `Command` (⌘K) | shadcn/ui (cmdk) | Busca global, navigation rápida |

## 2.2 Domain Components (PULSE-specific)

### MetricCard

O componente mais importante do produto. Aparece em toda tela.

```
┌──────────────────────────────────┐
│  Cycle Time (median)        [i]  │  ← Label + info tooltip
│                                  │
│  18.4h                      ↓12% │  ← Big number + trend badge
│                                  │
│  ▁▂▃▄▅▃▂▄▅▆                    │  ← Sparkline (últimas 8 semanas)
│                                  │
│  Target: < 24h              ✓    │  ← Benchmark/target (se definido)
└──────────────────────────────────┘

Props:
  label: string
  value: string | number
  unit?: string ("h", "%", "deploys/week")
  trend: { direction: "up"|"down"|"flat", percentage: number, isPositive: boolean }
  sparklineData?: number[]
  target?: { value: number, met: boolean }
  onClick?: () => void  // drill-down
  loading?: boolean  // shows skeleton
  tooltipContent?: string
```

### DORAClassificationBadge

```
┌──────────┐
│ ● Elite  │  ← Dot color + label
└──────────┘

Variants: elite (emerald), high (blue), medium (amber), low (red)
```

### CycleTimeBreakdown

```
┌──────────────────────────────────────────────────────┐
│  Cycle Time Breakdown                                 │
│                                                       │
│  ████████░░░░░░░░░░████████████░░░██                 │
│  Coding   Pickup   Review      Merge Deploy          │
│  8.2h     4.1h     12.3h       0.5h  1.2h           │
│                    ▲ bottleneck                       │
│                                                       │
│  Total: 26.3h (median)                               │
└──────────────────────────────────────────────────────┘

Horizontal stacked bar. Cada segmento com cor distinta.
A fase com maior valor é highlighted como "bottleneck".
Hover mostra tooltip com detalhes da fase.
```

### CumulativeFlowDiagram

```
┌──────────────────────────────────────────────────────┐
│  Cumulative Flow Diagram          [Team: Backend ▾]  │
│                                                       │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓             │
│  ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                   │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░                         │
│  ████████████████████████                             │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                                  │
│  ──────────────────────────────────────              │
│  W1   W2   W3   W4   W5   W6   W7   W8              │
│                                                       │
│  Legend: ■ Done ■ Review ■ In Progress ■ To Do ■ Backlog│
└──────────────────────────────────────────────────────┘

Stacked area chart (Recharts AreaChart).
Cada estágio = uma área com cor.
Hover mostra tooltip com counts por estágio naquela semana.
```

### LeadTimeScatterplot

```
┌──────────────────────────────────────────────────────┐
│  Lead Time Distribution                               │
│                                                       │
│  days                                                 │
│  40 │              ●                                  │
│  30 │    ●    ●         ●                             │
│  20 │─────────────────────── P95 (22d) ─────────     │
│  15 │────────── P85 (15d) ──────                     │
│  10 │ ●  ● ● ●●●● ●● ●● ●                          │
│   5 │──── P50 (7d) ────                              │
│   0 └────────────────────────────────── date →       │
│      Jan      Feb      Mar                            │
│                                                       │
│  ● Normal  ● Outlier (> P95)                         │
└──────────────────────────────────────────────────────┘

Recharts ScatterChart.
Cada issue = um ponto.
Horizontal lines para P50, P85, P95.
Pontos acima do P95 ficam vermelhos.
Click em ponto abre detalhes da issue.
```

### WipMonitor

```
┌────────────────────────────┐
│  Work In Progress           │
│                             │
│  ██████████████░░  12 / 15 │  ← progress bar + count / limit
│                             │
│  ⚠ 3 items aging > 10 days │  ← alert se aging
└────────────────────────────┘

Variants: normal (brand), warning (amber, approaching limit), danger (red, over limit)
```

### SprintOverview

```
┌──────────────────────────────────────────────────────┐
│  Sprint "Sprint 24"   Mar 1 - Mar 15                 │
│                                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐│
│  │Committed │ │ Added    │ │Completed │ │ Carry    ││
│  │  24      │ │  +3      │ │  20      │ │  7       ││
│  │          │ │          │ │  (83%)   │ │  (29%)   ││
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘│
│                                                       │
│  [Burndown Chart]                                     │
│  ████████████████████████                             │
│  ██████████████████                                   │
│  ████████████                                         │
│  ████████                                             │
│  ──────────────────────────────────────              │
│  D1  D2  D3  D4  D5  D6  D7  D8  D9  D10            │
└──────────────────────────────────────────────────────┘
```

---

# 3. LAYOUT DAS TELAS — MAPEAMENTO ÉPICO → HISTÓRIA → TELA

## 3.1 Sitemap do MVP

**Nota:** No MVP não há tela de login nem onboarding. O usuário acessa diretamente o dashboard. Conexões são configuradas via YAML/env vars.

```
/                        → Home overview (MetricCards) — entry point direto
/metrics/dora            → DORA dashboard
/metrics/cycle-time      → Cycle Time breakdown
/metrics/throughput      → Throughput + PR analytics
/metrics/lean            → Lean metrics (CFD, WIP, Lead Time)
/metrics/lean/cfd        → CFD detail
/metrics/lean/scatterplot→ Lead Time Scatterplot
/metrics/sprints         → Sprint overview + comparison
/metrics/sprints/:id     → Sprint detail

/prs                     → Open PRs list
/integrations            → Integration status (read-only, sem config UI)
```

**Páginas NÃO incluídas no MVP (vão para R1):**
- `/login`, `/register` — Auth via SSO
- `/onboarding/*` — Wizard de 5 passos
- `/settings` — Org settings
- `/settings/teams` — Team management UI

## 3.2 Mapeamento Detalhado: Épico → História → Tela

### ÉPICO 1: Data Pipeline → Tela de Status de Integrações (Read-Only)

No MVP, as conexões são configuradas via YAML. A única tela do Épico 1 no frontend é uma view read-only que mostra o status das integrações.

| Story ID | User Story | Tela(s) | Componentes Principais |
|---|---|---|---|
| MVP-3.3.4 | Como EM, quero ver status das integrações (read-only) | `/integrations` | ConnectionCard (logo, status badge, last sync, repo count). Estados: Active (green), Syncing (spinner), Error (red). Sem botões de config — apenas visualização |

**Tela: /integrations (read-only)**

```
┌──────────────────────────────────────────────────────────────┐
│  Integrations                          Status: All Active ✓  │
│─────────────────────────────────────────────────────────────│
│                                                               │
│  ┌──────────────────────┐ ┌──────────────────────┐          │
│  │ ◉ GitHub     Active  │ │ ◉ Jira       Active  │          │
│  │ acme-corp            │ │ acme-corp.atlassian  │          │
│  │ 5 repos monitored    │ │ 2 boards monitored   │          │
│  │ Last sync: 3 min ago │ │ Last sync: 5 min ago │          │
│  └──────────────────────┘ └──────────────────────┘          │
│  ┌──────────────────────┐ ┌──────────────────────┐          │
│  │ ○ GitLab   Not config│ │ ○ Azure     Not config│          │
│  │ No connection        │ │ No connection        │          │
│  │ Configure in YAML    │ │ Configure in YAML    │          │
│  └──────────────────────┘ └──────────────────────┘          │
│                                                               │
│  ℹ Connections are configured via connections.yaml            │
│    See documentation for setup instructions.                  │
└──────────────────────────────────────────────────────────────┘
```

**Telas de Onboarding e Login → movidas para R1.** As wireframes de login, register e onboarding wizard (5 steps) permanecem especificadas neste documento para uso futuro no R1, mas NÃO são implementadas no MVP.

---

### ÉPICO 2: DORA Metrics → Telas de Métricas DORA

| Story ID | User Story | Tela(s) | Componentes |
|---|---|---|---|
| MVP-2.1.1 | Deployment Frequency | `/metrics/dora` | MetricCard (value + trend), BarChart (deploys/week), DORABadge |
| MVP-2.1.2 | Lead Time for Changes | `/metrics/dora` | MetricCard, BarChart com stacked breakdown |
| MVP-2.1.3 | Change Failure Rate | `/metrics/dora` | MetricCard, LineChart (% over time) |
| MVP-2.1.4 | MTTR | `/metrics/dora` | MetricCard, BarChart |
| MVP-2.1.5 | Classificação DORA | `/metrics/dora` | DORAOverview: 4 badges lado a lado com classificação geral |
| MVP-2.2.1 | Cycle Time Breakdown | `/metrics/cycle-time` | CycleTimeBreakdown component (stacked bar), MetricCards por fase |
| MVP-2.2.2 | Cycle Time Trends | `/metrics/cycle-time` | LineChart multi-series (cada fase como série togglable) |
| MVP-2.3.1 | Throughput | `/metrics/throughput` | BarChart (PRs/week), MetricCard com trend |
| MVP-2.3.2 | PR Analytics | `/metrics/throughput` | 4x MetricCards (size, first review, review time, reviewers) + distribution charts |
| MVP-2.3.3 | Lista de PRs abertas | `/prs` | DataTable (TanStack Table): título, autor, repo, age, size, status. Sortable |

**Tela: /metrics/dora**

```
┌──────────────────────────────────────────────────────────────────────┐
│  DORA Metrics                          [Team: All ▾] [Last 30d ▾]   │
│─────────────────────────────────────────────────────────────────────│
│                                                                      │
│  Overall: ● High                                                     │
│                                                                      │
│  ┌──────────────────┐ ┌──────────────────┐                          │
│  │ Deployment Freq.  │ │ Lead Time        │                          │
│  │ ● Elite           │ │ ● High           │                          │
│  │ 4.2 /week    ↑8%  │ │ 18.4h       ↓12% │                          │
│  │ ▁▂▃▄▅▆▅▆▇        │ │ ▆▅▄▃▄▃▂▃▂       │                          │
│  └──────────────────┘ └──────────────────┘                          │
│  ┌──────────────────┐ ┌──────────────────┐                          │
│  │ Change Fail Rate  │ │ MTTR             │                          │
│  │ ● Medium          │ │ ● High           │                          │
│  │ 8.3%         ↑2%  │ │ 2.1h        ↓25% │                          │
│  │ ▂▃▂▃▄▃▄▅▄        │ │ ▅▄▃▂▃▂▁▂▁       │                          │
│  └──────────────────┘ └──────────────────┘                          │
│                                                                      │
│  ┌─── Deployment Frequency Over Time ────────────────────────────┐  │
│  │  ▌                                                             │  │
│  │  ▌▌   ▌▌   ▌▌▌  ▌▌▌  ▌▌▌▌ ▌▌▌▌ ▌▌▌▌▌▌▌▌▌                   │  │
│  │  ──────────────────────────────────────────────                │  │
│  │  W1   W2   W3   W4   W5   W6   W7   W8                       │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─── Lead Time Trend ───────────────────────────────────────────┐  │
│  │  30h ─                                                         │  │
│  │  20h ─  ╲    ╱╲                                               │  │
│  │  10h ─    ╲╱    ╲──── target: 24h ─────                       │  │
│  │   0h ─                                                         │  │
│  │       W1   W2   W3   W4   W5   W6   W7   W8                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

### ÉPICO 3: Lean/Agile Metrics → Telas Lean

| Story ID | User Story | Tela(s) | Componentes |
|---|---|---|---|
| MVP-3.1.1 | CFD | `/metrics/lean` + `/metrics/lean/cfd` | CumulativeFlowDiagram (area chart), período selecionável |
| MVP-3.1.2 | WIP Monitor | `/metrics/lean` | WipMonitor card, lista de itens em progresso |
| MVP-3.1.3 | Lead Time Distribution | `/metrics/lean` | Histogram (Recharts BarChart com bins), P50/85/95 lines |
| MVP-3.1.4 | Throughput Run Chart | `/metrics/lean` | BarChart + LineChart overlay (moving average) |
| MVP-3.1.5 | Scatterplot | `/metrics/lean/scatterplot` | LeadTimeScatterplot, percentile lines, click-to-detail |
| MVP-3.2.1 | Sprint Overview | `/metrics/sprints` | SprintOverview component, burndown chart |
| MVP-3.2.2 | Sprint Comparison | `/metrics/sprints` | Multi-bar chart: committed vs completed per sprint. Line charts para scope creep % e carryover % |

**Tela: /metrics/lean**

```
┌──────────────────────────────────────────────────────────────────────┐
│  Lean & Flow Metrics                   [Team: Backend ▾] [90d ▾]    │
│─────────────────────────────────────────────────────────────────────│
│                                                                      │
│  ┌──── Summary Cards ────────────────────────────────────────────┐  │
│  │ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ │  │
│  │ │ WIP        │ │ Lead Time  │ │ Throughput  │ │ SLE        │ │  │
│  │ │ 12 / 15    │ │ P85: 15d   │ │ 8.2/week   │ │ (future)   │ │  │
│  │ │ ██████░░   │ │ P50: 7d    │ │ ↑12%       │ │            │ │  │
│  │ └────────────┘ └────────────┘ └────────────┘ └────────────┘ │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─── Cumulative Flow Diagram ───────────────────────────────────┐  │
│  │  [Area chart empilhado com 5 cores por estágio]                │  │
│  │  Height: 300px                                                 │  │
│  │  Hover: tooltip com counts por estágio                        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─── Lead Time Distribution ─────┐ ┌─── Throughput Run Chart ───┐  │
│  │  [Histogram com P50/85/95]     │ │  [Bar + trend line]        │  │
│  │  Click bar: ver issues nesse   │ │                             │  │
│  │  range de lead time            │ │                             │  │
│  └────────────────────────────────┘ └─────────────────────────────┘  │
│                                                                      │
│  [View Scatterplot →]   [View Aging WIP → (R1)]                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

### ÉPICO 3 (Shell): Platform Foundation → Dashboard Shell

No MVP, o Platform Foundation é reduzido ao shell de navegação. Sem login, sem org management, sem team management UI.

| Story ID | User Story | Tela(s) | Componentes |
|---|---|---|---|
| MVP-3.3.1 | Sidebar com navegação para seções de métricas | Global (sidebar) | Sidebar: Home, DORA, Cycle Time, Throughput, Lean & Flow, Sprints, Open PRs, Integrations (status) |
| MVP-3.3.2 | Filtros globais (time + período) | TopBar (global) | FilterBar: TeamSelector (dropdown, dados do config), PeriodSelector (presets 7d/30d/90d) |
| MVP-3.3.3 | Home page com MetricCards overview | `/` (home) | Grid de 6 MetricCards + seção "PRs Needing Attention" |
| MVP-3.3.4 | Status das integrações (read-only) | `/integrations` | ConnectionCards read-only com status |
| MVP-3.3.5 | Skeleton loading em todos os componentes async | Global | Skeleton shimmer em MetricCards, charts, tables |

**Tela: /home (Dashboard Principal)**

```
┌──────────────────────────────────────────────────────────────────────┐
│  Welcome back, Carlos              [Team: All ▾] [Last 30 days ▾]   │
│─────────────────────────────────────────────────────────────────────│
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  DORA Score: ● High                          [View details →] │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐    │
│  │ Deploy Freq.      │ │ Lead Time        │ │ Change Fail Rate │    │
│  │ 4.2/wk       ↑8%  │ │ 18.4h       ↓12% │ │ 8.3%        ↑2%  │    │
│  │ ▁▂▃▄▅▆▅▆▇        │ │ ▆▅▄▃▄▃▂▃▂       │ │ ▂▃▂▃▄▃▄▅▄       │    │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘    │
│                                                                      │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐    │
│  │ Cycle Time       │ │ WIP              │ │ Throughput       │    │
│  │ 26.3h       ↓5%  │ │ 12/15      ⚠     │ │ 8.2/wk      ↑12% │    │
│  │ ▅▄▃▃▃▂▂▂▂       │ │ ██████████░░░░   │ │ ▁▂▃▃▄▅▅▆▆       │    │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘    │
│                                                                      │
│  ┌─── Open PRs Needing Attention ────────────────────────────────┐  │
│  │  PR #342 "Add payment validation" — 3 days, awaiting review   │  │
│  │  PR #339 "Fix auth timeout" — 5 days, 2 comments              │  │
│  │  PR #337 "Update deps" — 7 days, no reviewers                 │  │
│  │                                               [View all PRs →]│  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 4. INTERAÇÕES E COMPORTAMENTOS

## 4.1 Padrões de Interação

| Padrão | Comportamento | Implementação |
|---|---|---|
| **Drill-down** | Click em MetricCard → navega para página de detalhe da métrica | `onClick={() => navigate('/metrics/cycle-time')}` |
| **Chart hover** | Hover em ponto/barra do chart → tooltip com valor + contexto | Recharts `<Tooltip>` customizado |
| **Filter persist** | Filtros do TopBar persistem ao navegar entre páginas | Zustand store + URL search params sync (TanStack Router) |
| **Skeleton loading** | Enquanto dados carregam, mostra skeleton do MetricCard/Chart | shadcn `<Skeleton>` com mesmas dimensões do componente final |
| **Empty state** | Quando não há dados (ex: sem conexão) mostra ilustração + CTA | EmptyState component com ícone, texto, e button primário |
| **Error state** | Quando API falha mostra mensagem amigável + retry | ErrorBoundary com "Something went wrong" + [Retry] button |
| **Period presets** | 7d, 30d, 90d, Custom range picker | PeriodSelector dropdown com presets + date range picker (shadcn Calendar) |
| **⌘K Palette** | Global shortcut para buscar métricas, times, PRs, pages | shadcn/ui Command component (cmdk library) |

## 4.2 State Management Pattern

```
┌──────────────────────────────────────────────────┐
│  Zustand Stores (Client State)                    │
│                                                    │
│  authStore: { user, token, org, isAuthenticated }  │
│  filterStore: { teamId, period, projectId }        │
│  sidebarStore: { isCollapsed, activeItem }         │
│                                                    │
│  ← Sync com URL search params via TanStack Router  │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  TanStack Query (Server State)                    │
│                                                    │
│  useDoraMetrics(teamId, period)                    │
│  useCycleTime(teamId, period)                      │
│  useThroughput(teamId, period)                     │
│  useLeadTimeDistribution(teamId, period)           │
│  useCFD(teamId, period)                            │
│  useSprintOverview(sprintId)                       │
│  useOpenPRs(teamId)                                │
│  useConnections()                                  │
│                                                    │
│  Config: staleTime 5min, refetchInterval 60s       │
│  (dados não mudam em real-time, polling suave)     │
└──────────────────────────────────────────────────┘
```

## 4.3 Responsive Behavior

| Breakpoint | Sidebar | Content | Charts |
|---|---|---|---|
| **>1280px** (Desktop) | Full sidebar (240px, labels + icons) | 3-column grid para MetricCards | Full width charts |
| **768-1280px** (Tablet) | Icon-only sidebar (64px), expand on hover | 2-column grid | Full width charts, menores |
| **<768px** (Mobile) | Hidden, acessível via hamburger menu | 1-column stack | Full width, scroll vertical |

---

# 5. ACESSIBILIDADE

| Requisito | Implementação |
|---|---|
| **Keyboard navigation** | Radix UI primitives garantem focus management, arrow keys em menus, Escape para fechar |
| **Screen reader** | ARIA labels em todos os charts (fallback text description), role="img" com aria-label descritivo |
| **Color contrast** | WCAG AA mínimo (4.5:1 para text, 3:1 para UI elements). Design tokens já são AA-compliant |
| **Focus visible** | Ring de focus visible em todos os interativos (Tailwind `focus-visible:ring-2`) |
| **Reduced motion** | `prefers-reduced-motion: reduce` desliga animações de charts e transitions |
| **Chart alternatives** | Cada chart tem data table toggleable (ícone de tabela no canto) para quem prefere dados tabulares |

---

# 6. CONVENÇÕES DE CÓDIGO REACT

## 6.1 Estrutura de Componentes

```typescript
// Exemplo: MetricCard.tsx
import { type FC } from 'react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { TrendBadge } from './TrendBadge';
import { Sparkline } from './Sparkline';
import { Skeleton } from '@/components/ui/skeleton';

interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  trend?: { direction: 'up' | 'down' | 'flat'; pct: number; positive: boolean };
  sparklineData?: number[];
  target?: { value: number; met: boolean };
  onClick?: () => void;
  loading?: boolean;
  className?: string;
}

export const MetricCard: FC<MetricCardProps> = ({
  label, value, unit, trend, sparklineData, target, onClick, loading, className
}) => {
  if (loading) return <MetricCardSkeleton />;

  return (
    <Card
      className={cn(
        'p-5 cursor-pointer hover:shadow-md transition-shadow',
        className
      )}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {/* ... rendering logic */}
    </Card>
  );
};

const MetricCardSkeleton: FC = () => (
  <Card className="p-5">
    <Skeleton className="h-4 w-24 mb-3" />
    <Skeleton className="h-8 w-16 mb-2" />
    <Skeleton className="h-6 w-full" />
  </Card>
);
```

## 6.2 Convenções Obrigatórias

| Regra | Detalhe |
|---|---|
| **Colocation** | Componentes de domínio ficam junto da rota que os usa. Components globais em `/components/` |
| **Props interface** | Toda prop tipada com interface explícita. Sem `any` |
| **Loading states** | Todo componente que recebe dados assíncronos tem skeleton state |
| **Error boundaries** | `ErrorBoundary` em cada section do dashboard (falha isolada não derruba a página) |
| **Naming** | PascalCase para componentes. camelCase para hooks. kebab-case para arquivos de rotas |
| **Hooks custom** | Prefixo `use`. Cada endpoint de API tem um hook TanStack Query dedicado |
| **No inline styles** | 100% Tailwind classes. Exceção: valores dinâmicos calculados (ex: width de progress bar) |
| **Test file co-located** | `MetricCard.tsx` + `MetricCard.test.tsx` na mesma pasta |

---

*Documento de design frontend para desenvolvimento. Cruza com roadmap MVP (Épicos 1-4, 39 stories). Stack: React 19 + Vite 6 + TypeScript + Tailwind + shadcn/ui + Tremor + Recharts.*
