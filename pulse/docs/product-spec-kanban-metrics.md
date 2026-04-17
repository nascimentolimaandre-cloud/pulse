# PULSE — Kanban-Native Flow Metrics Suite
### Product Spec · v1.0 · 2026-04-17 · Owner: `pulse-product-director`

> "A time precisa parar de olhar pra quanto entregamos na semana passada e começar a olhar pra o que está preso no fluxo agora." — Priya (Agile Coach persona)

---

## 1. Problema e hipótese

### 1.1 Contexto
PULSE hoje cobre DORA (4 métricas) + um subset Lean canônico (CFD, WIP, Lead Time Distribution, Throughput, Scatterplot) + Sprint metrics (velocity, commitment, carryover). Essa suíte foi desenhada assumindo um cliente Scrum-first. O cliente-âncora **Webmotors (27 squads, 373k issues históricas)** opera em **100% fluxo contínuo**: zero sprints ativos, `eng_sprints` está vazio para eles, e todo o trabalho transita em quadros Jira com status categories (To Do → In Progress → In Review → Done).

Resultado: um Engineering Manager Webmotors abre a home do PULSE hoje e vê:
- 4 KPIs DORA (úteis, mas latentes — respondem "como estávamos há 60 dias")
- Sprint velocity zerado (ruído, não sinal)
- CFD + WIP + Throughput (úteis, mas não acionáveis sozinhos — "tenho 184 items em WIP, e daí?")

Ele **não consegue responder** em 1 glance:
- Qual squad está sobrecarregado agora?
- Quais items estão envelhecendo e provavelmente vão furar SLA?
- Qual % do meu cycle time é trabalho real vs fila?
- Estou entregando mais feature ou mais bug nos últimos 60 dias?

### 1.2 Hipótese de produto

> **Se entregarmos 5 métricas Kanban-native (Aging WIP, Flow Efficiency, Flow Load, Flow Distribution, Blocked Time) no dashboard principal, então EMs e Agile Coaches de clientes Kanban-puros (Webmotors e perfil similar) vão aumentar frequência de acesso semanal de 1,2x/dev para ≥3x/dev em 60 dias, e vão adotar ≥2 decisões operacionais/semana baseadas em dados da plataforma (medido via analytics events + entrevistas com os 3 primeiros squads piloto).**

Medimos sucesso por: WAU/MAU dashboard, tempo na página Flow Health, taxa de uso de drill-down por squad, e NPS persona Priya.

### 1.3 Decisão que melhoramos

| Antes | Depois |
|---|---|
| "Está tudo bem, throughput subiu 8%" (vago, lagging) | "Squad Pricing tem 4 items com age > 2× P85 — intervenção hoje" |
| "Cycle time médio é 9 dias" | "9 dias, mas apenas 22% é touch time — 78% é fila. Gargalo: In Review" |
| "Temos muito WIP" | "Squad Billing está a 1,9× sua capacidade histórica — pausar intake" |
| "Entregamos 42 items no mês" | "42 items: 48% feature, 31% bug, 18% tech-debt, 3% ops — bug ratio subindo 3 meses seguidos" |

---

## 2. Personas impactadas e JTBDs

| Persona | Primária? | JTBD específico | Métrica âncora |
|---|---|---|---|
| **Priya** (Agile Coach) | PRIMÁRIA | "Quando eu entro numa daily, quero chegar com 3 cards aging identificados e 1 hipótese de gargalo por squad" | Aging WIP, Flow Efficiency |
| **Carlos** (EM) | PRIMÁRIA | "Toda segunda, quero saber qual dos meus 4 squads está em overload antes de redistribuir intake" | Flow Load |
| **Ana** (CTO) | Secundária | "Na revisão de trimestre, quero ver se estamos mantendo proporção saudável feature/bug/debt — sinal de saúde técnica" | Flow Distribution |
| **Marina** (Sr Dev) | Secundária | "Quero saber se meu squad é saudável ou sufocado — sem me comparar a outros" | Flow Efficiency (squad), Blocked Time |
| **Roberto** (CFO) | Fora de escopo MVP | — Flow Distribution alimenta DevFinOps em R3+ | — |

**Não-persona:** não existe persona "Manager supervisionando devs individuais". É proibido por design.

---

## 3. Escopo da suíte — 5 métricas

Após avaliar 8 candidatos, selecionamos 5. Justificativa editorial em §10.

| # | Métrica | Persona | Release | Prioridade |
|---|---|---|---|---|
| M1 | **Aging WIP** (Work Item Age) | Priya | **MVP** | P0 |
| M2 | **Flow Efficiency** | Priya, Marina | **MVP** | P0 |
| M3 | **Flow Load** (WIP vs capacity) | Carlos | **R1** | P0 |
| M4 | **Flow Distribution** (work type mix) | Ana | **R1** | P1 |
| M5 | **Blocked Time Distribution** | Priya, Marina | **R2** | P1 |

**Excluídas (com razão):** ver §10.

---

## 4. Detalhamento por métrica

### M1 · Aging WIP (Work Item Age)

**Unidade:** dias (inteiros) · **Chart:** scatterplot horizontal + aging heatmap por coluna

#### Definição conceitual
Para cada item atualmente em WIP (normalized_status ∈ {in_progress, in_review}), calcula há quantos dias ele está na fase ativa (desde `started_at`). A distribuição permite identificar *outliers* — items que já excederam 2× o P85 histórico de cycle time do squad e têm probabilidade estatística alta de atrasar. É a métrica mais acionável do Kanban segundo Daniel Vacanti (Actionable Agile, cap. 4): "Work Item Age is the only metric that tells you about work in flight, not work already done."

#### Fórmula canônica

```
Para cada issue i com normalized_status ∈ {in_progress, in_review}:
  age_days(i) = (now - started_at(i)) / 1 day

Distribuição = {
  items:       [{issue_key, age_days, column, squad}, ...],
  p50, p85:    percentis de age_days no WIP atual,
  at_risk:     count de issues onde age_days > 2 × p85_cycle_time_historico(squad),
  overdue:     count de issues onde age_days > p95_cycle_time_historico(squad),
}

Threshold histórico (janela móvel):
  p85_cycle_time_historico(squad) = P85 do lead_time_hours
    dos issues completed_at nos últimos 90 dias do squad
    (converter horas → dias)
```

#### Fonte de dados (Webmotors-validable HOJE)

| Campo | Tabela | Observação |
|---|---|---|
| `normalized_status` | `eng_issues` | Já existe, filtro ∈ {in_progress, in_review} |
| `started_at` | `eng_issues` | Já populado via normalizer |
| `completed_at`, `lead_time_hours` | `eng_issues` | Para baseline histórico |
| `squad` / `team` mapping | join por `project_key` / labels | Já implementado no dashboard global |

**Sem dependência de schema novo.** Usa apenas dados disponíveis hoje.

#### Visualização
- **Primária:** scatterplot horizontal agrupado por coluna (In Progress / In Review). Eixo X = idade em dias. Linha vertical pontilhada no P85 do squad. Cards acima de 2×P85 em cor de alerta (token `--color-risk`).
- **Secundária:** heatmap aging-por-coluna (linhas = squads, colunas = faixas de idade 0-3d/4-7d/8-14d/15d+, célula = count).
- **KPI compact:** "Aging WIP: X items a risco (Y% do WIP atual)".

#### Thresholds (classificação squad)

| Estado | Critério | Justificativa |
|---|---|---|
| Healthy | 0 items > 2×P85 | Fluxo saudável |
| Degraded | 1-2 items > 2×P85 OU ≥1 item > P95 | Atenção |
| Risk | ≥3 items > 2×P85 OU ≥1 item > 3×P85 | Ação imediata |

Justificativa estatística: P85 como SLA interno é o padrão Actionable Agile (Vacanti). 2× P85 é regra empírica de "tail risk" — items que cruzam 2× P85 têm probabilidade <15% de completar dentro do P95 histórico.

#### Anti-surveillance check: **PASS**
Métrica é *por item*, não por autor. Drill-down expõe issue key + coluna + age, nunca `assignee` individual. Agregações: por squad / por tipo / por coluna.

---

### M2 · Flow Efficiency

**Unidade:** % · **Chart:** gauge + trendline semanal

#### Definição conceitual
Percentual do cycle time em que um item está em trabalho ativo (touch time) versus em filas ou bloqueado (wait time). Responde: "Dos 9 dias de cycle time, quantos foram trabalho real?"

Métrica canônica do Lean (Mary Poppendieck, *Lean Software Development*). Benchmarks públicos (Vacanti, Reinertsen):
- Elite: ≥ 40%
- Healthy: 25-40%
- Typical industry: 15-25%
- Degraded: < 15%

#### Fórmula canônica

```
Para cada issue i concluído no período:
  touch_time(i)  = Σ tempo em status ∈ {in_progress, in_review}
                   (via status_transitions)
  wait_time(i)   = Σ tempo em status ∈ {todo, blocked, waiting, on_hold}
                   (entre started_at e completed_at)
  cycle_time(i)  = touch_time(i) + wait_time(i)
                 = completed_at - started_at

  flow_efficiency(i) = touch_time(i) / cycle_time(i)

Agregação squad/período:
  FE = Σ touch_time(i) / Σ cycle_time(i)   (weighted, não mean of ratios)
```

#### Fonte de dados

| Campo | Tabela | Dependência |
|---|---|---|
| `status_transitions` (JSONB array) | `eng_issues` | **Já existe**, populado por normalizer |
| `started_at`, `completed_at` | `eng_issues` | Já existe |
| **Mapa de status "blocked"** | config tenant | **NOVO — dependência R1** |

**Dependência crítica:** Webmotors não tem uma coluna/status "Blocked" canônico no Jira. O cálculo **MVP** assume: `wait_time = cycle_time - (tempo em in_progress ∪ in_review)`, ou seja, qualquer tempo fora do ativo conta como espera. Isso superestima wait_time se o item oscila por `todo` no meio (retrabalho), mas é conservador e acionável.

No **R2**, adicionar config de tenant `blocked_statuses: [string]` para permitir modelagem mais precisa (ex: "Waiting for Review", "Impediment").

#### Visualização
- **Primária (dashboard home):** KPI com gauge 0-100% e color-coded band (red < 15 / amber 15-25 / green 25-40 / elite ≥40). Trend sparkline 12 semanas.
- **Drill-down:** distribuição de FE por squad (barra horizontal ordenada).
- **Explicação inline ao hover:** "Flow Efficiency = touch time ÷ cycle time. Mede % do tempo em trabalho ativo."

#### Thresholds
| Classificação | Range | Benchmark |
|---|---|---|
| Elite | ≥ 40% | Top decil indústria |
| Healthy | 25-40% | Meta realista SaaS maduro |
| Degraded | 15-25% | Média indústria |
| Risk | < 15% | Fila dominando o fluxo |

#### Anti-surveillance check: **PASS**
Agregado squad/tenant. Nunca por autor. Drill-down mostra distribuição de FE por squad, não por pessoa.

---

### M3 · Flow Load (WIP vs Capacity)

**Unidade:** ratio (adimensional) · **Chart:** gauge horizontal + lista squads sobrecarregadas

#### Definição conceitual
Ratio entre WIP atual do squad e sua capacidade calculada historicamente. Capacity não é um número mágico — inferimos do P85 histórico de WIP do próprio squad nos últimos 90 dias. Load > 1,2 indica overload; > 1,5 é risco alto (Little's Law: cycle time cresce super-linearmente com WIP).

#### Fórmula canônica

```
Para cada squad s:
  wip_atual(s)        = count(issues ∈ s com normalized_status ∈ {in_progress, in_review})
  wip_baseline(s)     = P85 do WIP diário de s nos últimos 90 dias
                        (extraído do histórico CFD)
  flow_load(s)        = wip_atual(s) / wip_baseline(s)
```

**Alternativa considerada** (rejeitada para MVP): `capacity = squad_size × 1.5`. Rejeitada porque:
1. `squad_size` não é dado confiável (devs trocam de squad, alocação parcial)
2. O multiplicador 1.5 é arbitrário e não calibra por natureza do trabalho (squad de ops vs squad de feature têm loads ótimos diferentes)
3. Baseline histórico é self-referential e não precisa de metadata externa

Trocamos por baseline histórico: cada squad se compara consigo mesmo.

#### Fonte de dados

| Campo | Tabela | Observação |
|---|---|---|
| `normalized_status`, `started_at`, `completed_at`, `status_transitions` | `eng_issues` | Já existe |
| `squad`/`team` mapping | já implementado | — |
| **Histórico CFD** | calculado on-demand ou em snapshot | Reaproveita `calculate_cfd` já existente |

Sem schema novo. Reaproveita pipeline existente.

#### Visualização
- **Primária:** lista horizontal ranqueada de squads por flow_load desc. Barras coloridas (verde < 1.0, amber 1.0-1.2, vermelho > 1.2).
- **Drill-down squad:** comparativo WIP atual × baseline P50/P85 com anotação.
- **KPI compact:** "X squads em overload (load > 1.2)".

#### Thresholds

| Classificação | Range | Justificativa (Little's Law) |
|---|---|---|
| Under-utilized | < 0.7 | Ociosidade ou mudança de demanda |
| Healthy | 0.7 - 1.1 | Operando próximo da média histórica |
| Degraded | 1.1 - 1.3 | Cycle time provavelmente subindo |
| Overload | > 1.3 | Intake precisa pausar |

#### Anti-surveillance check: **PASS**
Métrica é squad-level. Nunca por autor. O ranking é **squad**, não pessoas — e está alinhado ao objetivo anti-surveillance ("squads overloaded" é sinal de *proteção ao time*, não de cobrança individual).

---

### M4 · Flow Distribution (work type mix)

**Unidade:** % distribuição · **Chart:** stacked bar semanal + pizza

#### Definição conceitual
Proporção de items entregues por tipo de trabalho: **Feature / Bug / Tech Debt / Ops**. Responde: "Onde estamos investindo?" e "Nossa proporção bug/feature está saudável?".

Inspirado em Mik Kersten (*Flow Framework*) — Flow Distribution é uma das 5 Flow Metrics canônicas.

#### Fórmula canônica

```
Categorizar cada issue concluído no período:
  Se issue_type = "Bug"                     → bug
  Elif issue_type = "Epic"                  → excluir (é container, não work)
  Elif labels ∩ {"tech-debt","refactor"}    → tech_debt
  Elif labels ∩ {"ops","infra","sre"}       → ops
  Else                                      → feature

Distribuição:
  { feature_pct, bug_pct, tech_debt_pct, ops_pct }
Série temporal: mesma categorização bucketed por semana.
```

#### Fonte de dados

| Campo | Tabela | Dependência |
|---|---|---|
| `issue_type` | `eng_issues` | Já existe |
| `labels` (array) | `eng_issues` | **DEPENDÊNCIA — campo não existe hoje em `eng_issues`** |
| `completed_at` | `eng_issues` | Já existe |

**Dependência crítica:** `eng_issues` não tem coluna `labels`. Hoje o normalizer descarta labels do Jira.

Opções:
1. **Adicionar `labels JSONB` em `eng_issues`** (migration + normalizer update) — preferido, unblocks outras features
2. **Classificação heurística baseada apenas em `issue_type`** — MVP-degradado, sem separação tech-debt/ops

Para R1 entregamos a versão completa (opção 1). Para MVP não entregamos M4. Documentado abaixo na Release planning.

#### Visualização
- **Primária:** stacked bar horizontal semanal (12 semanas), cores tokenizadas por categoria.
- **Drill-down:** breakdown por squad (cada squad = uma linha, stacked por %).
- **KPI compact:** "Bug ratio: X% (↑ Y pts vs 90d atrás)".

#### Thresholds

Sem classificação Elite/Healthy/Degraded — é descritiva, não diagnóstica. Mas sinalizar com aviso:
- **Warning:** bug_pct > 35% em 4 semanas consecutivas (sinal de dívida técnica explodindo)
- **Warning:** tech_debt_pct < 5% em trimestre (sinal de negligência crônica)

#### Anti-surveillance check: **PASS**
Agregado squad/tenant. Classificação é por work item, não por autor.

---

### M5 · Blocked Time Distribution

**Unidade:** horas/dias (P50/P85) · **Chart:** histograma + sparkline trend

#### Definição conceitual
Para items que passaram por um status de bloqueio (ou label/flag), mede a distribuição de tempo bloqueado. Responde: "Quanto tempo meus items ficam presos esperando decisão/dependência externa?"

Diferente de Flow Efficiency (que agrega tudo que não é "ativo"), Blocked Time isola **bloqueio explícito** — é granular e acionável.

#### Fórmula canônica

```
Requer: configuração de tenant `blocked_statuses: [string]`
        (ex: ["Blocked", "On Hold", "Waiting Dependency"])

Para cada issue i concluído no período:
  blocked_time(i) = Σ tempo em status ∈ blocked_statuses
                    (via status_transitions)
  blocked(i)      = True se blocked_time(i) > 0

Distribuição (apenas issues bloqueadas):
  count_blocked, pct_blocked (% do throughput),
  p50_blocked_hours, p85_blocked_hours
  Top razões (se `block_reason` label existir) — R3
```

#### Fonte de dados

| Campo | Tabela | Dependência |
|---|---|---|
| `status_transitions` | `eng_issues` | Já existe |
| Config `blocked_statuses` | **tabela nova** `tenant_workflow_config` | **R2 dependency** |

**Webmotors não tem status "Blocked" no Jira hoje** — validado por discovery. R2 requer onboarding de config.

#### Visualização
- Histograma buckets: 0-1d / 1-3d / 3-7d / 7-14d / 14d+
- Sparkline: % de items bloqueados por semana (12 semanas)
- KPI: "X% dos items entregues foram bloqueados ≥1× · P85 blocked time = Yd"

#### Thresholds
| Estado | Critério |
|---|---|
| Healthy | pct_blocked < 10% E P85 < 2 dias |
| Degraded | pct_blocked 10-25% OU P85 2-5 dias |
| Risk | pct_blocked > 25% OU P85 > 5 dias |

#### Anti-surveillance check: **PASS**
Agregado, não expõe assignee.

---

## 5. Little's Law validation e consistência com métricas existentes

**Little's Law:** `Cycle Time = WIP / Throughput`

As novas métricas respeitam a lei e explicam desvios quando a relação degrada:

| Sintoma | Métrica nova que explica |
|---|---|
| Cycle Time subiu, WIP constante | Flow Efficiency caiu (mais tempo em fila) OU Blocked Time cresceu |
| WIP subindo, throughput igual | Flow Load > 1, intake desalinhado com capacity |
| Throughput caiu sem mudança de headcount | Flow Distribution mudou (mais bug/debt vs feature) OU Aging WIP acumulando |

**Consistency checks (test obrigatórios em `pulse-test-engineer`):**
- `mean(flow_efficiency_per_issue) × cycle_time_avg ≈ touch_time_avg` (dentro de ±5%)
- `sum(wip_by_squad) == wip_global` (no período)
- `flow_distribution.sum() == 100%` (tolerance 0.5 pp por arredondamento)

---

## 6. Anti-surveillance — auditoria global

| Métrica | Agregação mínima | Exposição de autor? | Ranking de pessoas? | Status |
|---|---|---|---|---|
| Aging WIP | por item (com squad) | NÃO (assignee escondido) | NÃO | PASS |
| Flow Efficiency | squad + período | NÃO | NÃO | PASS |
| Flow Load | squad | NÃO | NÃO (ranking é *de squad*) | PASS |
| Flow Distribution | squad + período | NÃO | NÃO | PASS |
| Blocked Time | squad + período | NÃO | NÃO | PASS |

**Compromisso explícito no FE:** o drill-down de Aging WIP mostra `issue_key`, `title` (truncado), `column`, `age_days`, **NUNCA** `assignee`. No hover/link, abre o Jira direto — delegando a informação de autor para o sistema fonte (onde o usuário já tem contexto de governança).

---

## 7. Positioning competitivo

| Métrica | PULSE (pós-entrega) | Swarmia | LinearB | Allstacks | Plandek | Jellyfish |
|---|---|---|---|---|---|---|
| Aging WIP / Work Item Age | **SIM (MVP)** | SIM | Parcial | NÃO | SIM | SIM |
| Flow Efficiency | **SIM (MVP)** | SIM | NÃO | NÃO | SIM | SIM |
| Flow Load (WIP/capacity) | **SIM (R1)** | NÃO | Parcial | NÃO | NÃO | Parcial |
| Flow Distribution | **SIM (R1)** | SIM | NÃO | SIM | SIM | SIM |
| Blocked Time | **SIM (R2)** | SIM | NÃO | NÃO | Parcial | NÃO |

**Conclusão editorial:** com as 5 métricas entregues (MVP + R1 + R2), PULSE atinge paridade com Swarmia/Plandek em Kanban nativo, mantém vantagem em DORA + Lean combinado, e continua diferenciado em (1) preço, (2) anti-surveillance, (3) LatAm/PT-BR, (4) Jenkins-native CI/CD.

**Defensive moat:** Flow Load calculado via baseline histórico (não headcount) é sutilmente melhor que concorrentes — não depende de metadata de RH que clientes não mantêm atualizada.

---

## 8. Release planning

### MVP (T+4 semanas)
- **M1 Aging WIP** — zero dependência de schema, alta ação, persona Priya
- **M2 Flow Efficiency** — com simplificação "wait = cycle − touch"
- Integração na página `/home` existente (NOVA seção "Flow Health" abaixo das KPIs DORA)

### R1 (T+8 semanas)
- **M3 Flow Load** — precisa histórico CFD persistido (baseline)
- **M4 Flow Distribution** — requer migration `labels JSONB` em `eng_issues` + normalizer update
- Página dedicada `/flow-health` (drill-down completo)

**Decisão arquitetural (assumption):** começamos integrando em `/home` (decisão conservadora per instrução). Criamos página `/flow-health` em R1 somente se analytics mostrar >50% dos usuários clicando em drill-downs. Registrado como hypothesis.

### R2 (T+12 semanas)
- **M5 Blocked Time Distribution** — requer config tenant `tenant_workflow_config.blocked_statuses`
- Refinamento M2 Flow Efficiency com `blocked` explícito

### R3+ (roadmap)
- Monte Carlo forecasting usando Aging WIP + Throughput (probabilidade de items atuais completarem em N dias)
- Flow Distribution → feed de DevFinOps (persona Roberto)
- Block reason taxonomy (top reasons bloqueio via NLP sobre comments)

---

## 9. Hand-off checklist

### Para `pulse-data-scientist` — validar e refinar fórmulas

- [ ] **M1** Validar cálculo de P85 histórico com janela móvel 90 dias (confirmar estabilidade com amostra Webmotors real — 27 squads, verificar que squads com throughput baixo (<5 items/90d) tenham fallback para benchmark global)
- [ ] **M2** Confirmar agregação weighted-sum (`Σ touch / Σ cycle`) vs mean-of-ratios. Testar em dataset Webmotors. Validar edge case: issue com cycle_time < 1h (arredondamento).
- [ ] **M2** Validar decisão MVP de "wait = cycle − touch" vs erro esperado quando items oscilam em `todo`. Quantificar com amostra real.
- [ ] **M3** Confirmar baseline = P85 dos snapshots diários de WIP (não média). Testar estabilidade numérica com squads novos (<90 dias de histórico — fallback para P85 global do tenant).
- [ ] **M3** Decidir janela (60/90/120d) via análise de sensibilidade.
- [ ] **M4** Definir canonical labels taxonomy para MVP: `tech-debt`, `tech_debt`, `techdebt`, `refactor` → bucket `tech_debt`. Documentar mapping, expor como config.
- [ ] **M5** Propor estatísticas alternativas (P50/P85 truncado pode ser instável com n pequeno — considerar "% items bloqueados" como KPI mais robusto).
- [ ] **Cross-cutting** Escrever testes estatísticos (TDD): Little's Law consistency, sum-to-100% em distributions, monotonicidade de P50 ≤ P85 ≤ P95.

### Para `pulse-data-engineer` — schema, pipeline, endpoints

- [ ] **Migration R1:** `ALTER TABLE eng_issues ADD COLUMN labels JSONB DEFAULT '[]'` + índice GIN
- [ ] **Normalizer:** populate `labels` a partir de `fields.labels` do Jira (já no payload raw)
- [ ] **Migration R2:** nova tabela `tenant_workflow_config (tenant_id PK, blocked_statuses JSONB, tech_debt_labels JSONB, ops_labels JSONB)` com RLS
- [ ] **Endpoint `GET /data/v1/metrics/flow-health`** (MVP) — retorna `{aging_wip: {...}, flow_efficiency: {...}}` com filtros `squad`, `period`
- [ ] **Endpoint `GET /data/v1/metrics/flow-load`** (R1) — retorna ranking squads
- [ ] **Endpoint `GET /data/v1/metrics/flow-distribution`** (R1) — retorna séries temporais por categoria
- [ ] **Endpoint `GET /data/v1/metrics/blocked-time`** (R2)
- [ ] **Snapshot strategy:** Aging WIP é calculado on-demand (WIP muda minuto-a-minuto); Flow Efficiency / Flow Distribution persistem em `metric_snapshots` com grain diário; Flow Load depende de snapshot CFD histórico persistido (validar que já está em snapshots)
- [ ] **Performance guardrail:** endpoint de Aging WIP precisa retornar em < 800ms p95 para squad com WIP ≤ 200; para tenant inteiro (27 squads), < 1.5s — usar índice parcial `(tenant_id, normalized_status) WHERE normalized_status IN ('in_progress','in_review')`

### Para `pulse-ux-reviewer` — design de visualizações

- [ ] Componente **AgingWipScatter** (horizontal) — desafio: 27 squads × até 30 items cada = 800 pontos, densidade visual
- [ ] Componente **FlowEfficiencyGauge** com trend sparkline embed
- [ ] Componente **FlowLoadRanking** (lista de squads com barra horizontal)
- [ ] Componente **FlowDistributionStacked** (bar stacked + pizza)
- [ ] Seção home "Flow Health" (3 slots: Aging WIP KPI + scatter mini / FE gauge / Flow Load top-3 overloaded)
- [ ] Estados: loading (skeleton), empty (ex: squad sem WIP — "Sem trabalho em andamento"), partial (histórico insuficiente), error
- [ ] Copy PT-BR: "Itens envelhecendo", "Eficiência de fluxo", "Carga do squad", "Distribuição de trabalho", "Tempo bloqueado"

### Para `pulse-engineer` — implementação

- [ ] Depois de ux-reviewer, quebrar HTML em componentes React em `pulse/packages/pulse-web/src/components/flow-health/`
- [ ] Hook `useFlowHealth(filters)` em `pulse/packages/pulse-web/src/hooks/`
- [ ] Route `/flow-health` (R1)
- [ ] Analytics events: `flow_health_viewed`, `aging_wip_drill_down_opened`, `flow_efficiency_hovered`, `flow_load_squad_clicked`, `flow_distribution_period_changed`

### Para `pulse-test-engineer`

- [ ] Unit tests TDD (escrever ANTES): aging_wip_calculator, flow_efficiency_calculator, flow_load_calculator, flow_distribution_categorizer
- [ ] Property-based tests: Little's Law consistency, percentil monotonicity, sum-to-100%
- [ ] Integration tests: endpoints com fixtures Webmotors-like (27 squads, distribution realista)
- [ ] E2E Playwright: jornada Priya "abrir home → ver flow health → drill Aging WIP → clicar item → redirect Jira"
- [ ] Performance benchmark k6: `/flow-health` com payload de 27 squads, p95 < 1.5s
- [ ] a11y: axe-core nos componentes novos, contraste color-coded gauges WCAG AA

### Para `pulse-ciso`

- [ ] Review: Aging WIP drill-down **NÃO** deve vazar `assignee` no payload da API (policy middleware)
- [ ] Review: Tenant config `blocked_statuses` (R2) — strings arbitrárias, validar tamanho e sanitização (evitar SQL injection downstream)
- [ ] RLS validation: todas as queries filtram por `tenant_id`

---

## 10. Decisões editoriais (justificativa)

### Por que 5 e não 8 métricas
> "Escolha é valor." Cada métrica extra custa: 1 chart, 1 estado empty/error, 1 explicação, 1 decisão de quando olhar. 5 é o ponto onde o EM consegue "lembrar o menu" em 10s.

### Por que NÃO incluímos

| Excluído | Razão |
|---|---|
| **Flow Debt** (age > 2× P85 count) | É uma *faceta* de Aging WIP, não métrica autônoma. Expomos como `at_risk_count` dentro de M1. |
| **Delivery Rate per Squad** | Redundante com Throughput existente. Já temos `/metrics/throughput` com breakdown. |
| **Cycle Time by Work Type** | Útil, mas derivável do join entre Flow Distribution (M4) e cycle time existente. Vira dashboard de análise em R2+, não métrica de topo. |

### Por que Flow Efficiency está em MVP apesar da limitação (wait = cycle − touch)
Honesto: a fórmula não-ideal ainda produz sinal acionável (tendências, comparação entre squads). O risco é absoluto (o número pode parecer pior do que é), mas o valor relativo é preservado. Priya consegue responder "meu squad melhorou vs 90d atrás?" mesmo sem a refinação R2.

### Por que Flow Load em R1 e não MVP
Depende de baseline histórico CFD que ainda não está persistido em `metric_snapshots` de forma consumível. Precisa do `pulse-data-engineer` primeiro. Não forçamos dívida técnica pra ganhar 4 semanas.

### Por que página integrada (`/home`) e não separada em MVP
Instrução de conservadorismo + hipótese de que usuários novos não vão navegar pra "mais uma página". R1 cria `/flow-health` se analytics validar.

### Por que baseline histórico em Flow Load vs capacity por headcount
Defendido em §4 M3 — `squad_size` é metadata ruim em empresas reais. Baseline histórico é auto-suficiente.

---

## 11. Riscos e mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| Webmotors não usa status "Blocked" no Jira | Bloqueia M5 R2 | Documentado. R2 inclui config tenant opt-in. Cliente sem config vê placeholder educativo. |
| `labels` não persistido → M4 travado | Bloqueia R1 | Migration simples, PR estimado 1 dia. Já listado em hand-off para `pulse-data-engineer`. |
| Squads novos (<90d) têm baseline ruim | M1, M3 ruido | Fallback para baseline global do tenant + aviso UI "Dados insuficientes, usando baseline da empresa". |
| Perfomance: 27 squads × cálculo on-demand | p95 > 1.5s | Índice parcial + cache de 60s em camada de API para Flow Load (muda lentamente). Aging WIP sem cache (precisa ser live). |
| Drift entre Flow Efficiency MVP (simplified) e R2 (com blocked explícito) | Confusão cliente | Versionar: expor `formula_version: "mvp_simplified"` no payload. Documentar na página de ajuda. |
| Anti-surveillance quebrado acidentalmente | Dano de marca | Checklist no PR template. Test automatizado que falha se `assignee` aparecer em payload de métrica. |

---

## 12. Analytics events (definição)

| Event | Props | Owner |
|---|---|---|
| `flow_health_section_viewed` | tenant_id, squad_filter, period | Frontend |
| `aging_wip_item_clicked` | issue_key_hash, age_days, column | Frontend |
| `flow_efficiency_hovered` | squad, value_pct | Frontend |
| `flow_load_squad_clicked` | squad, load_value | Frontend |
| `flow_distribution_period_changed` | period_before, period_after | Frontend |
| `blocked_time_config_opened` | (R2) | Frontend |

Hash `issue_key` se privacy policy exigir — discutir com CISO.

---

## 13. Aprovação e próximos passos

**Ready-for-dev?** Sim para M1 e M2 (MVP). M3/M4 dependem de pré-work `pulse-data-engineer` (migration + snapshots). M5 depende de config tenant (design R2).

**Próxima ação:**
1. `pulse-data-scientist` revisa §9 checklist e confirma fórmulas em 2 dias
2. `pulse-data-engineer` estima migrations e endpoints — prazo 3 dias
3. `pulse-ux-reviewer` produz concepts para a seção Flow Health em `/home` — 1 semana
4. Kickoff sprint MVP com os 3 artefatos

---

*Fim do spec.*
