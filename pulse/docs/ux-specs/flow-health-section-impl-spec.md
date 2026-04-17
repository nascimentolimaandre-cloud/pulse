# Flow Health Section — Implementation Spec

**Scope:** nova seção `Flow Health` na home do PULSE Dashboard. Cobre **Aging WIP** (M1) e **Flow Efficiency** (M2), as duas primeiras métricas Kanban-native do MVP.
**Hand-off:** `pulse-engineer` (React + Vite em `pulse/packages/pulse-web/`).
**Prototype runnable:** `pulse/pulse-ui/pages/dashboard/flow-health-section.html` (+ `.css`, `.js`).
**Release tag:** MVP · Sprint corrente. Cards FDD-KB-003 e FDD-KB-004.

---

## 1. Objective & Scope

**Objetivo:** responder em ≤ 10s a pergunta "o fluxo Kanban está saudável **agora**?" e em ≤ 30s "onde estão os gargalos?", sem expor assignees individuais (anti-surveillance).

**In scope (MVP):**
- Card `Aging WIP` com callout de itens at_risk, viewport principal e drawer de drill-down.
- Card `Flow Efficiency` com gauge 0–100%, trend vs período anterior, disclaimer v1 inline.
- Seção integrada à home **entre** `KPI strip (kpi-groups)` e `Comparativo por squad (rankings)`. Não criar rota `/flow-health` — decisão do product-director.
- Estados: loading, empty, healthy, degraded (at_risk alto), error, partial (insufficient_data em FE).
- Responsive desktop/tablet/mobile. PT-BR. WCAG AA. Tokens-only.

**Out of scope (deferido):**
- Rota standalone `/flow-health` — só entra em R1 se analytics (`flow_health_viewed` + drill-down rate) validar o interesse.
- Comparação inter-squad de Flow Efficiency (R1, após mapeamento de status por squad).
- Classificação com benchmark externo de FE — R2.

---

## 2. Design Rationale — 3 conceitos + escolha

**Challenge:** 633 itens em progresso × 27 squads = densidade perigosa. Um scatter item-level vira sopa visual e não é acionável para Priya (Agile Coach). Os três conceitos exploram ângulos editoriais distintos:

| Concept | Hipótese visual | Primary persona | Força | Fraqueza |
|---|---|---|---|---|
| **A · Outlier-first** | Tabela top-8 at_risk + drawer completo. Não mostra distribuição | Priya (ação imediata) | Scan em 5s, drill direto. Escala bem com 800/8000 itens | Esconde padrões de distribuição; não responde "quantos estão saudáveis?" |
| **B · Distribution-first** | Histograma agregado 5 buckets + chips das 6 squads críticas | Carlos/Ana (health check) | Dá senso de distribuição geral. Boa relação sinal/ruído | Item-level só via drawer; chips viram ruído se > 10 squads críticas |
| **C · Squad-matrix** | Heatmap top-12 squads × 5 buckets de idade (0-7/7-14/14-22/risco/%) | Carlos (comparativo cross-squad) | Compara squads de relance. Escala razoavelmente | 27 squads não cabem — corte para top-12 é decisão editorial que pode mascarar; aprendizado exige alfabetização em heatmap |

### 🏆 Recomendação final — **Concept A (Outlier-first)**

**Justificativa com dados Webmotors:**
1. Com `at_risk_count` esperado em 25–120 itens (5–15% do WIP), a tabela top-8 cobre o **pior 10–30%** dos at_risk — suficiente para Priya agir numa cerimônia de 15 min sem abrir o drawer.
2. O **JTBD crítico de Priya** é *"onde está o gargalo **hoje**?"* — distribuição agregada (concept B) não responde isso: 400 itens em "0-7d" é a mesma cor de 400 em "14-22d" e ela continua sem saber **qual ticket** tocar.
3. Concept C (heatmap) é sedutor no demo mas falha em dois pontos reais: (a) 15 das 27 squads ficariam cortadas do MVP; (b) heatmap com 5×12 células = 60 números — Carlos faz o scan em 20s, não 5s.
4. Concept A é o **único que funciona em mobile** sem cortes — apenas esconde a coluna de barra de progresso; histograma e heatmap precisam de scroll horizontal.

**Os 3 ajustes pré-dev obrigatórios:**

1. **Adicionar "agrupar por squad" como toggle inline no card** (não só no drawer). A tabela top-8 em estado crítico vai ficar dominada por 1 squad (ex: DESK com 24 at_risk). Um toggle `por item · por squad` permite Priya alternar entre "qual ticket?" e "qual squad?" sem abrir drawer. Impacto: +1 componente de segmented control no header do card, reaproveita padrão de `period filter`.
2. **Mostrar sparkline de `at_risk_count` 30d no callout** (60×16px, à direita do texto). Hoje o callout diz "67 itens em risco" sem contexto. Saber que ontem eram 45 é a diferença entre alarme e deterioração progressiva. Tokens já cobrem (var(--color-danger), var(--chart-6)).
3. **Inverter a hierarquia do card FE**: valor 32px + trend ↑↓ + disclaimer **antes** do gauge. O gauge hoje ancora visualmente, mas o valor textual é o que Carlos lê em 2s. Manter gauge como "reforço visual" embaixo, com tamanho reduzido (120×120) para liberar espaço ao disclaimer.

---

## 3. Information Architecture

Posição na home:

```
topbar
└ page-head + filters
└ applied-filters
└ kpi-groups (DORA + Flow & Management)           ← existente
└ flow-health  ← NOVA SEÇÃO (500–580px altura)    ← entre KPI e rankings
└ rankings (Comparativo por squad)                ← existente
└ evolution (Evolução por squad)                  ← existente
```

Estrutura da seção:

```
flow-health
├── header
│   ├── h2 "Flow Health"
│   └── sub "Saúde do fluxo Kanban · ..."
└── grid (2 cols desktop, 1 col <1100px)
    ├── fh-card--wide: AGING WIP
    │   ├── head (title, sub com P50/P85/count)
    │   ├── callout danger (hidden se at_risk_count=0)
    │   │   └── sparkline at_risk 30d (ajuste #2)
    │   ├── segmented toggle (ajuste #1) — item | squad
    │   └── viewport: tabela top-8 (sort por age desc)
    └── fh-card: FLOW EFFICIENCY
        ├── head (title, sub, badge "v1")
        ├── value 32px + trend vs prev (ajuste #3)
        ├── disclaimer inline (obrigatório)
        ├── gauge 120x120 (reforço visual)
        └── stats dl (amostra, janela, classificação)
```

---

## 4. Component Breakdown

| Visual block | Existing design-system | New component | Layout primitives |
|---|---|---|---|
| Section header (h2 + sub) | `SectionHead` (já usado em KPI groups) | — | Stack |
| `fh-card` | `Card` (existente) | — | Card + Stack |
| Callout strip | — | `<Callout tone="danger" icon dismissible={false}>` | Row |
| Sparkline (ajuste #2) | `Sparkline` (usado em KPI strip) | — | — |
| Segmented toggle (ajuste #1) | `SegmentedControl` (já existe p/ período) | — | — |
| Outlier table | `DataTable` (existente em rankings) | `AgingRiskRow` com barra de progresso horizontal | Table |
| Ratio bar | — | `RatioBar` (6px, warn/danger) | — |
| FE gauge | — | `RingGauge` (SVG, value + trend slot) | — |
| FE disclaimer | — | `InlineNote` (icon + text, tone neutral) | Row |
| Drawer | `Drawer` (existente — mesmo do team drill-down) | — | Drawer |
| Drawer filters | `SearchInput` + `Select` | — | Row |

**Props propostos (TS):**
```ts
type AgingWipSummary = {
  count: number; p50_days: number; p85_days: number;
  at_risk_count: number; at_risk_threshold_days: number;
  at_risk_trend_30d?: number[]; // daily counts
};
type AgingWipItem = {
  issue_key: string; age_days: number;
  status_category: 'in_progress' | 'in_review';
  status_name: string; squad_key: string; is_at_risk: boolean;
};
type FlowEfficiency = {
  value: number | null; trend_pp: number;
  sample_size: number; formula_version: 'v1_simplified';
  formula_disclaimer: string; insufficient_data: boolean;
};
```

---

## 5. Design Tokens Used

**Cores:** `--color-bg-surface`, `--color-bg-tertiary`, `--color-border-default`, `--color-border-subtle`, `--color-text-primary/secondary/tertiary`, `--color-brand-primary`, `--color-danger`, `--color-warning`, `--color-info`, `--color-success`, `--color-dora-low-bg`, `--color-dora-medium-bg`.

**Tipografia:** Inter (UI), JetBrains Mono (issue keys, ages, counts). Escala: section-title 16/600, card-title 15/600, sub 12/400, table 13/400, KPI gauge 32/700, mono 12–13.

**Spacing:** `--space-card-padding` (20px), `--space-section-gap` (24px), gap 12–16px interno.

**Radius:** `--radius-card` (12px), `--radius-button` (8px), `--radius-badge` (full).

**Sombra:** `--shadow-card`. Drawer usa `--shadow-elevated`.

**Motion:** 150ms ease-out para hover, 200ms drawer open, respeita `prefers-reduced-motion`.

**Ícones:** Lucide `alert-triangle` (callout), `info` (disclaimer), `x` (drawer close), `chevron-down` (trends). Sempre acompanhados de texto — nunca cor-only.

**Zero hex hardcoded.** (Exceção justificada: intensity classes do heatmap em concept C — ali uso escala azul/vermelho derivada de `--color-info`/`--color-danger`; se concept C for implementado no futuro, mover para `tokens.css` com nomes `--color-heat-blue-*`.)

---

## 6. States Matrix

| Estado | Trigger | Spec visual | Dados necessários | Analytics |
|---|---|---|---|---|
| **Loading** | Fetch in-flight | 6 skeleton rows (14px) no viewport; gauge com arc vazio; sub "Carregando…" | — | `flow_health_loaded` (on complete) |
| **Empty** | `aging_wip.count === 0` E `fe.insufficient_data === true` | Empty hero com próxima ação ("Quando squads iniciarem trabalho…"); gauge `—`; callout hidden | — | `flow_health_empty_shown` |
| **Healthy** | at_risk_count > 0 mas ≤ 5% WIP · FE within ±2pp de histórico | Callout warning-tone (amarelo); tabela top-8 com barras warn | full | — |
| **Degraded/critical** | at_risk_count > 10% WIP **OU** 1 squad com ≥ 20 at_risk | Callout danger-tone (vermelho); sparkline trend visível; toggle squad chama atenção via badge count no label | full | `flow_health_critical_viewed` |
| **Error** | HTTP 5xx / timeout | Card body substituído por `<ErrorState onRetry>`; chrome (header) permanece | — | `flow_health_error`, `flow_health_retry_clicked` |
| **Partial (FE)** | `fe.insufficient_data === true` (amostra < 30) | Gauge com "—" + trend "dados insuficientes"; disclaimer ampliado "Amostra 12 itens, mínimo 30. Aguarde mais ciclos." | sample_size | `fe_insufficient_data_shown` |

---

## 7. Responsive Rules

| Breakpoint | Layout |
|---|---|
| **≥ 1280px** | Grid 2 cols (2.1fr / 1fr). Tabela top-8 com todas as colunas. Gauge 160×160. |
| **1100–1279px** | Grid 2 cols mantido, gauge 140×140. |
| **768–1099px** | Grid colapsa em 1 col. FE card passa a ocupar full-width abaixo de Aging WIP. |
| **< 768px** | 1 col. Esconde coluna "barra de progresso" da tabela. Drawer full-screen. Filtros do drawer em 1 col. Gauge 120×120. FE stats em stack vertical. |

Nunca esconder o callout danger em nenhum breakpoint. Nunca esconder o disclaimer v1.

---

## 8. Accessibility Checklist (WCAG AA)

- [ ] Contraste `--color-danger` (#EF4444) sobre `--color-dora-low-bg` (#FEE2E2) = 4.6:1 — usar `#991B1B` para texto (spec já usa).
- [ ] Callout é `role="status"` (atualiza com filtros sem perder foco).
- [ ] Gauge tem `role="img"` com `aria-label` completo ("42%, queda de 3pp").
- [ ] Disclaimer não pode ser tooltip-only — spec enforça texto visível.
- [ ] Todas as rows da tabela são `tabindex="0"` e abrem o drawer via Enter/Space.
- [ ] Drawer: trap de foco, Esc fecha, primeiro foco em close button, `aria-modal="false"` (usuário pode voltar à página — é um side-panel).
- [ ] Status `In Progress`/`In Review` sempre com dot + texto (nunca cor-only).
- [ ] At_risk bar com `role="img"` + aria-label "Idade relativa ao máximo".
- [ ] Heatmap (concept C) tem `role="table"` + cells com `title` para leitores de tela.
- [ ] `prefers-reduced-motion`: desabilita pulse-skeleton, transições de drawer.
- [ ] Foco visível em todos os interativos (herda `:focus-visible` do tokens.css).

---

## 9. Analytics Events

| Event | Payload | Quando |
|---|---|---|
| `flow_health_viewed` | `{ concept: 'A', has_at_risk: bool, at_risk_count, fe_value, fe_insufficient: bool }` | Seção entra no viewport (IntersectionObserver 50%) |
| `aging_wip_item_clicked` | `{ issue_key, age_days, squad_key, position: 1–8, from: 'card'|'drawer' }` | Row clicada |
| `aging_wip_drawer_opened` | `{ trigger: 'callout_cta'|'foot_link'|'row_click'|'squad_chip', at_risk_count }` | Drawer abre |
| `aging_wip_toggle_grouping` | `{ grouping: 'item'|'squad' }` | Ajuste #1 — toggle clicado |
| `fe_disclaimer_hovered` | `{ dwell_ms }` | Usuário hoverar ≥500ms no disclaimer |
| `flow_health_critical_viewed` | `{ at_risk_count, top_squad_key, top_squad_at_risk }` | Estado crítico renderizado |
| `fe_insufficient_data_shown` | `{ sample_size }` | Estado partial |
| `flow_health_error` | `{ error_code, source: 'aging'|'fe' }` | Falha de fetch |
| `flow_health_retry_clicked` | `{ source }` | Retry |

Mapeamento AARRR: eventos alimentam **Activation** (viewed), **Retention** (drawer_opened por usuário recorrente), **Engagement** (toggle, disclaimer_hovered) — usados pelo product-director para decidir promoção a rota `/flow-health` em R1.

---

## 10. Open Questions / Risks

1. **Performance do drawer com 200+ at_risk.** Mitigação: virtualização (react-window) se `at_risk_count > 100`. Decisão do engineer.
2. **Sparkline no callout (ajuste #2)** exige série temporal `at_risk_count_daily_30d` — precisa ser adicionada ao endpoint `GET /metrics/kanban/aging-wip` ou computada de snapshots. **Pendência para `pulse-data-engineer`.**
3. **Toggle item/squad (ajuste #1)**: na visão "por squad" a tabela muda colunas (squad, WIP total, at_risk count, % risco). **Confirmar com product-director se precisa de linha separada** ou se o heatmap do concept C entra como "visão alternativa" em R1.
4. **Mobile < 768px**: gauge SVG 120px ainda cabe ao lado do disclaimer? Testar em 375px. Fallback: gauge acima, disclaimer abaixo.
5. **Anti-surveillance audit**: confirmar no code review que **nenhum campo `assignee` vaza** do backend para o front. `pulse-ciso` check obrigatório.
6. **Unidade de idade**: atualmente `age_days` com 1 decimal. Para items novos (<24h) mostrar `3h` ou `0,5d`? Decisão: sub-24h exibir em horas.
7. **Ordenação do drawer**: idade desc (default), squad (alfabético), status — confirmar com Priya.

---

**Hand-off complete.** `pulse-engineer` consome este spec + HTML em `pulse/pulse-ui/pages/dashboard/flow-health-section.html` para implementação em `pulse/packages/pulse-web/src/components/dashboard/FlowHealth/`.
