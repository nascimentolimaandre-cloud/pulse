# Stitch/Manus Prompt — Pipeline Monitor v2 (Multi-Source @ Scale)

> Cole o conteúdo abaixo da linha `---` em Google Stitch, Manus, v0 ou equivalente para gerar variações da tela. O prompt foi escrito para uma persona sênior (Principal Product Designer + Product Director) — ou seja, espera-se interpretação, trade-offs e priorização editorial, não cópia literal.

---

## PERSONA & MODO DE TRABALHO

Você é um **Principal Product Designer & Product Director** com 15+ anos projetando ferramentas de observabilidade de dados para engenharia (pense em alguém que já liderou UI do Datadog Pipelines, Snowflake Snowpipe, Databricks Lakeflow, Dagster Cloud ou Airbyte Cloud). Você NÃO é um ilustrador de wireframes — você é um tomador de decisão de produto que pensa em:

- **Hierarquia de informação** (o que o usuário precisa ver em 2 segundos vs. 30 segundos vs. quando está investigando um incidente)
- **Densidade vs. respiração** (quando tabelas densas salvam vidas, quando cartões aéreos educam)
- **Escala real** (um usuário com 283 repositórios GitHub e 69 projetos Jira NÃO pode ver 352 cartões — precisa de agregação, agrupamento e drill-down)
- **Estados emocionais** (tranquilidade em steady-state, urgência cirúrgica em incidente, otimismo acolhedor em empty-state)
- **Trade-offs explícitos**: cada escolha de layout deve vir com uma breve justificativa ("optei por X porque Y; a alternativa Z falharia quando…")

**Entregáveis esperados** (nesta ordem):
1. **3 conceitos visuais distintos** da tela — cada um com hipótese editorial diferente (ex.: "DAG-first", "Table-first densa", "Incident-first"). Para cada conceito: screenshot hi-fi + 3–5 linhas de justificativa + 2 limitações.
2. **Recomendação final** (qual conceito e por quê), com as 3 mudanças que você faria antes de ir para dev.
3. **Estados**: loading (skeleton), empty (primeira conexão), healthy-steady, running-backfill (atenção), degraded (1 fonte com problema), error (fonte fora), partial-catalog (projetos `discovered` aguardando ativação).
4. **Responsivo**: desktop ≥1280px, tablet 768–1279px, mobile <768px.

Se sentir que o briefing tem lacuna, **explicite a suposição** antes de desenhar.

---

## 1. CONTEXTO DE PRODUTO

**Produto**: PULSE — Engineering Intelligence SaaS (DORA + Lean/Agile + Sprint analytics).
**Cliente-âncora**: Webmotors (100% Brasil, português-BR como idioma padrão da UI, mas copy aceitável em inglês onde termo técnico for dominante).
**Tela**: `Pipeline Monitor` — subsídio de `/integrations`.

### A "promessa" do produto para esta tela
> *"Um olhar na saúde do pipeline e eu confio em todas as outras métricas do PULSE."*

Esta NÃO é uma tela que o usuário olha todo dia — é o **"engine light"** do produto. Quando ele olha, geralmente é em 3 contextos:

1. **Check casual (5s)** — "Está tudo verde? Ok, confio no DORA que vou mostrar na sprint review."
2. **Suspeita (30s–2min)** — "O gráfico de PRs tá estranho, será que parou de sincronizar?" → precisa drillar até repo/projeto específico e ver watermark.
3. **Incidente (5–30min)** — "Nada sincroniza há 3h" → precisa ver erro específico, taxa de falha por step, retry/rate-limit, timeline de eventos.

### Escala real (Webmotors — estado atual, abril/2026)

| Dimensão | Número | Implicação de UI |
|---|---|---|
| Repositórios GitHub sincronizados | **283** | Não cabe em cartão individual — agrupe por time/criticidade |
| Jobs Jenkins PRD monitorados | **577** | Mesmo problema — agrupar por repo |
| Projetos Jira ativos | **69** (9 originais + 60 ativados do *discovered*) | Precisa filtro por status |
| Issues sincronizadas | **373.633** (8 → 65 projetos) | Contadores grandes precisam abreviação (373k) |
| Pull Requests | **63.692** | Idem |
| Deployments | **1.396** (ago/2023 → abr/2026) | Trend mensal visível, janela configurável |
| Taxa de linkagem PR↔Issue | **22%** (era 5,27%) | KPI visível de qualidade de dados |
| Cobertura repos com deploy | **88,7%** (253/283) | KPI de cobertura |

> ⚠️ **Lição aprendida (feedback real do usuário anterior)**:
> *"Preciso ver por etapa — fetch, changelog, normalize, upsert — com contagens e ETA. Barra única de progresso não serve."*
> Isso implica que cada fonte tem **sub-steps** e cada sub-step tem seu próprio status/contador.

---

## 2. ARQUITETURA DO PIPELINE (o que estamos monitorando)

```
┌──────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌──────────────┐    ┌────────────────┐
│   SOURCES    │ →  │   DISCOVERY  │ →  │  SYNC WORKER    │ →  │   PULSE DB   │ →  │ METRICS WORKER │
│ GitHub/Jira/ │    │   (catalog + │    │ (fetch → change │    │  (Postgres   │    │  (DORA/Lean/   │
│   Jenkins    │    │  PII check)  │    │ log → normalize │    │  + Kafka)    │    │ Cycle/Sprint)  │
│              │    │              │    │   → upsert)     │    │              │    │                │
└──────────────┘    └──────────────┘    └─────────────────┘    └──────────────┘    └────────────────┘
```

### 2.1 Cada **fonte** (Source) tem características próprias

| Fonte | Unidade de trabalho | Entidades sincronizadas | Rate limit | Modo default |
|---|---|---|---|---|
| GitHub | Repositório | PRs, Reviews, Commits, Deployments (via API) | 5000 req/h (org) | Incremental por `updated_at` |
| Jira | Projeto (key) | Issues, Changelog, Sprints | ~100 req/min | Incremental por `updated` JQL |
| Jenkins | Job PRD | Builds, Stages, Deployments | ~60 req/min | Incremental por `build number` |

### 2.2 Cada **sincronização** tem 4 sub-steps obrigatoriamente visíveis

Para **cada fonte × cada entidade**, o sync worker executa e reporta:

1. **Fetch** — chamadas à API externa (paginação). Métricas: requisições feitas, req/s, % do rate limit.
2. **Changelog** — só Jira: expande histórico de transições de status por issue (N+1 requests — gargalo conhecido). Métricas: issues com changelog buscado, latência p95.
3. **Normalize** — transforma payload externo em schema canônico PULSE. Métricas: registros normalizados, erros de schema.
4. **Upsert** — grava no Postgres com `ON CONFLICT` (idempotente). Métricas: inserts, updates, rejeições.

> O usuário quer ver os 4 como colunas/timeline SEPARADAS por entidade, com contagens absolutas + ETA calculada, **não** uma barra única somada.

### 2.3 Dois modos de operação

| Modo | Quando ocorre | UX implica |
|---|---|---|
| **Incremental** (steady-state) | A cada 15min, processa só o delta desde o watermark | Cartão compacto "healthy", verde, 2 min ago |
| **Backfill** (após reset, nova fonte, novo projeto ativado) | Pode levar de 15min a 10h | Cartão expandido, barra de progresso por step, ETA, contador live |

### 2.4 Estados do **catálogo** de fontes (Jira como exemplo)

Projetos Jira podem estar em 5 estados — e o usuário precisa ver a transição:

`discovered` → `active` → (`paused` | `blocked` | `archived`)

A tela precisa mostrar, no mínimo, quantos há em cada estado e oferecer ação para promover `discovered` → `active` em massa (já existe um endpoint `POST /v1/admin/integrations/jira/projects/{key}/activate`).

---

## 3. PERSONAS E JOBS-TO-BE-DONE

### Carlos — Engineering Manager (primário)
> *"Tenho que mostrar DORA na review em 15min. Os dados estão recentes?"*

JTBD:
- Ver "está tudo verde?" em <2s
- Quando não está, identificar **qual fonte / qual time** está com problema em <30s
- Não quer ver detalhe de step a não ser que tenha razão

### Priya — Agile Coach (secundário)
> *"O CFD do time X parece errado. Faltou issue? Status mapping tá certo?"*

JTBD:
- Drillar até um projeto Jira específico e ver: último sync, contagem esperada vs. real, status mapping aplicado
- Ver orphan refs (PR que cita `ENO-1234` mas não tem issue correspondente ingerida)

### Lucas — Data Platform Engineer (operador)
> *"A ingestão de ontem travou. Qual step? Qual rate limit estourou?"*

JTBD:
- Timeline de eventos filtrada por severidade
- Log de watermark por entidade
- Visão de rate limit vs. throughput ao longo das últimas 24h
- Botão "Retry failed" (apenas ele — RBAC)

### Ana — CTO (executivo, visita rara)
> *"Todos os times estão conectados?"*

JTBD:
- KPI de cobertura (X% dos repos com deploy, Y% dos PRs linkados a issue)
- Tendência mensal (saúde da plataforma ao longo do tempo)

---

## 4. PRINCÍPIOS DE DESIGN

1. **Read-only, always.** PULSE NUNCA dispara builds/syncs em sistemas externos. Botões de "Retry" atuam em filas internas, não no Jenkins/GitHub/Jira.
2. **Escala explícita.** Nunca desenhe uma lista finita de 3–5 itens — desenhe sempre como se o usuário tivesse 283 repos e 69 projetos.
3. **Agregação antes de detalhe.** Primeiro tela = agregados (por fonte, por time, por status). Drill-down = detalhe.
4. **Per-step, per-entidade, sempre.** Nunca uma barra única. Fetch/Changelog/Normalize/Upsert são primeira classe.
5. **ETA sempre que possível.** "Upsert 12.4k/47k issues · ETA 3m 20s" > "Processing…"
6. **Watermark visível.** É o único dado que permite debug de "por que está faltando?". Mostre como `2026-04-15 13:22 UTC` + relativo (`2m ago`).
7. **Rate limit como primeira classe.** Gráfico ou meter visível — GitHub 82% (4.100/5.000) é um sinal precoce.
8. **Anti-surveillance.** Nunca mostre autor individual em contexto de "o que atrasou". Tudo a nível de time/fonte/projeto.
9. **Acessibilidade WCAG AA.** Status sempre acompanhado de label (não só cor). Animações respeitam `prefers-reduced-motion`.
10. **Empty states dignos.** Antes da primeira conexão, não mostre zeros — mostre próximo passo ("Conectar GitHub").

---

## 5. DECISÕES DE IA (benchmark de referência — pesquisado)

Use como âncora, NÃO copie:

| Produto | O que imitar | O que evitar |
|---|---|---|
| **Databricks Lakeflow** | DAG visualization + List view alternativa + Matrix view (histórico); SLA como threshold visível; streaming observability (backlog segundos/bytes/records) | Densidade excessiva típica de Databricks; fontes minúsculas |
| **AWS Glue Observability** | Classificação de erro por causa raiz; métricas de job finas (56 sinais); integração com dashboards Grafana/QuickSight | Dependência de CloudWatch — aqui não temos |
| **Snowflake Snowpipe Streaming** | Latência de ingest-to-query como KPI; lag por tabela; throughput em GB/s | Interface é textual/CLI — não é referência visual forte |
| **Dagster Dagit** | Asset-focused (não task-focused); lineage visual navegável; inspeção de materializações; "rerun this step" | Curva de aprendizado alta; conceitos de asset podem confundir EM |
| **Fivetran** | Status por connector + watermark/cursor explícito; sync schedule visível; badge simples | Pouco drill-down — fica preso no connector-card |
| **Airbyte** | Log-viewer integrado; status por stream; retry granular | UI ainda irregular, não referência visual pura |
| **GitHub Actions (run view)** | Steps verticais com tempo por step; live log abaixo; status glyph simples (check/x/dot) | Layout task-centric não escala para 283 repos |
| **Vercel Deployments** | Lista com status-glyph + duration + commit; filtro por environment | Centrado em deploy único, não em pipeline contínuo |
| **Datadog Pipeline Observability** | Heatmap de erros por stage; drill a partir de timeline; dashboard por serviço | Custa caro em densidade visual |
| **Honeycomb** | BubbleUp para localizar a query que diverge (útil quando 10 repos falham — qual feature é comum?) | Requer modelo mental de traces |

**Síntese da recomendação editorial** (posicionamento de quem você é no projeto):
> *O usuário do PULSE é menos sofisticado que o de Dagster, mas opera uma escala maior que a de Fivetran. A melhor âncora é **Databricks Lakeflow com densidade reduzida**, **status-glyph à la Vercel/GitHub Actions** e **timeline de eventos à la Datadog Pipelines**. Evite DAG animado como peça central — ele impressiona em demo, mas não escala para 283 nós.*

---

## 6. ESTRUTURA DA TELA (proposta ponto-de-partida; desafie)

### 6.1 Topo — "Trust strip" (visível em <2s)

Barra horizontal única, 64–80px altura, com:

- **Badge global** (Pill grande): `Healthy` · `Degraded (1)` · `Error (3)` · `Backfilling` — com cor + ícone + label.
- **KPI row inline** (4 números + mini-sparkline 24h cada):
  - `Records today` → 12.482 (+8% vs. ontem)
  - `PR↔Issue link rate` → 22,0% (↑ 4.2pp vs. semana passada)
  - `Repos with deploys (last 30d)` → 253 / 283 (88,7%)
  - `Avg sync lag` → 4m 12s (p95: 11m)
- **Última atualização**: "Atualizado há 12s" com refresh manual.

### 6.2 Mid — Fontes + Entidades (matriz condensada)

**Proposta A (matriz)**: uma tabela/matriz 3 colunas × N linhas onde:
- Colunas: GitHub · Jira · Jenkins
- Linhas: cada entidade sincronizada (PRs, Issues, Deployments, Sprints)
- Célula: status-glyph + contagem do último ciclo + watermark + duração + mini-bar de % do rate limit

**Proposta B (cartões)**: 3 cartões grandes (1 por fonte), cada um abrindo em accordion para listar entidades + steps fetch/changelog/normalize/upsert.

→ **Decida e justifique**. Minha hipótese: **Proposta A** ganha em steady-state, **Proposta B** ganha durante backfill. Talvez a resposta seja "matriz quando healthy, cartão expandido automaticamente quando degraded".

### 6.3 Per-entity drawer (ao clicar numa célula)

Drawer lateral (ou modal) com:
- **4 steps** (Fetch · Changelog · Normalize · Upsert) como tabs ou como linha horizontal tipo stepper
- Para cada step: status, contagem (processed/total), taxa (items/s), ETA, erro se houver
- **Trace** do último ciclo: gráfico de duração por step (stacked horizontal bar) dos últimos 24 runs
- **Watermark history**: linha simples de quando o watermark avançou nas últimas 24h (plano de fundo para debug)
- **Logs recentes** (5 últimos events dessa entidade, severidade-colored)
- **Rate limit curve**: eixo X = hora, eixo Y = % limite, linha única
- Botão **"Retry failed items"** (visível só para Data Platform role)

### 6.4 Catálogo de fontes (card dedicado, lado direito no desktop)

Mostra, para cada fonte:
- Projetos/repos em cada estado (`discovered` / `active` / `paused` / `blocked` / `archived`) como stacked bar ou chips
- CTA: "Promover N `discovered` → `active`" (bulk action, exige confirmação)
- Link para /settings/connections

### 6.5 Timeline global de eventos (rodapé ou coluna direita)

Feed cronológico inverso, filtrado por severidade (all / warn+ / error-only):
- Dot colorido + stage pill + timestamp + mensagem + (opcional) deep-link ao drawer da entidade
- Virtualizado (pode ter 1000s de eventos)
- Badge "pause auto-scroll" quando usuário rolar manualmente

### 6.6 Cobertura & Qualidade (secondary panel)

Cartão quase-executivo (para Carlos/Ana):
- Donut: % de repos com deploy nos últimos 30d
- Donut: % de PRs linkados a issue
- Lista: top 5 "órfãos" — prefixos de PR-ref (`RC-*`, `AFDEV-*`) sem projeto Jira correspondente, com CTA "investigar"
- Lista: projetos ativos com 0 issues ingeridas (investigar config ou PII)

---

## 7. ESTADOS (desenhe TODOS)

### 7.1 Healthy steady-state
Tudo verde. Matriz compacta. Timeline com eventos `success/info`. Última sync 2min atrás.

### 7.2 Backfilling (após reset de watermark)
- Badge global `Backfilling` (cor info/azul, não alarme)
- Cartões expandidos automaticamente mostrando steps com progresso
- ETA calculado por step ("Fetch 32k/85k · 18m left")
- CTA: "Ver progresso detalhado"

### 7.3 Degraded (1 fonte com issue, resto ok)
- Badge `Degraded (1)` amber
- Célula afetada destacada com borda/bg amber-50
- Resto da tela permanece informativo (não entra em modo pânico)

### 7.4 Error (fonte fora)
- Badge `Error` vermelho
- Banner no topo: "Jira connection failing — retrying in 45s (attempt 3/5)"
- Linha afetada com erro expandido e link p/ logs

### 7.5 Rate-limit saturado (edge-case crítico)
- Badge `Slow (Rate-limited)`
- Célula mostrando 98% do rate limit, animação de pulso na barra
- Copy: "GitHub rate limit atingido — retomando em 12m"
- ETA ajustada automaticamente

### 7.6 Empty (primeira execução)
- Nenhum número zero. Desenhe hero: "Conecte sua primeira fonte → GitHub · Jira · Jenkins"
- 3 cartões grandes de onboarding com ícone, descrição curta, CTA

### 7.7 Discovered pendentes (catálogo incompleto)
- Banner informativo: "60 projetos Jira foram descobertos mas não ativados. [Revisar & ativar]"
- Não bloqueia, é apenas um call-to-awareness

### 7.8 Loading (skeleton)
- Shimmer em cada bloco — não spinners
- Preserve a geometria (evite "pular" quando dados chegarem)

---

## 8. DESIGN SYSTEM (obrigatório)

### 8.1 Cores (tokens PULSE)
- **Brand**: Indigo-500 `#6366F1` (hover: Indigo-600 `#4F46E5`)
- **Status**:
  - Success/Healthy: Emerald-500 `#10B981`
  - Info/Running: Blue-500 `#3B82F6`
  - Warning/Slow/Stale: Amber-500 `#F59E0B`
  - Danger/Error: Red-500 `#EF4444`
  - Idle: Gray-300 `#D1D5DB`
- **Superfícies**: White `#FFFFFF` · Gray-50 `#F9FAFB` · Gray-100 `#F3F4F6`
- **Texto**: Gray-900 `#111827` · Gray-500 `#6B7280` · Gray-400 `#9CA3AF`
- **Bordas**: Gray-200 `#E5E7EB`
- Status badges: bg `color-50` + text `color-700`

### 8.2 Tipografia
- Família: **Inter** (UI) + **JetBrains Mono** (timestamps, watermarks, IDs)
- H1 24px/600 · H2 18px/600 · H3 14px/500
- Body 14px/400 · Small 12px/400 · KPI 28px/700
- Mono 13px/400 em timestamps e watermarks

### 8.3 Geometria
- Card radius 12px, button radius 8px, badge radius full
- Shadow default `0 1px 3px rgba(0,0,0,0.05)`, elevated `0 4px 12px rgba(0,0,0,0.08)`
- Grid: 24px section gap, 20px card padding, 16px inner gap

### 8.4 Componentes de referência
- shadcn/ui (Radix + Tailwind)
- Lucide React ícones
- Recharts ou Tremor para mini-sparklines e donuts

### 8.5 Iconografia sugerida (Lucide)
- Sources: `Cable` · DevLake/Discovery: `Database` · Sync: `RefreshCw` · DB: `HardDrive` · Metrics: `Calculator`
- GitHub: `Github` · Jira: logo custom (Jira não existe no Lucide) · Jenkins: logo custom
- Status: `CheckCircle2` / `AlertCircle` / `AlertTriangle` / `Loader2` / `CircleDot`

---

## 9. ACESSIBILIDADE (WCAG AA — obrigatório)

- Status nunca apenas por cor — sempre + texto/ícone
- Contraste mínimo 4.5:1 em todo texto
- Drawer trap-focus + Esc fecha
- Timeline `role="log"` + `aria-live="polite"`
- Animações wrapped em `@media (prefers-reduced-motion: reduce)`
- Todos os controles atingíveis por teclado, foco visível

---

## 10. CONTEÚDO / COPY (português-BR)

Algumas frases de apoio que podem aparecer na tela — ajuste o tom, mas mantenha clareza operacional, zero "engenheirês":

- `Atualizado há 12s`
- `Sincronização saudável` / `Atenção: fonte lenta` / `Erro em 1 fonte`
- `Backfill em andamento · 3 de 4 etapas concluídas`
- `Próxima sincronização em ~3 min`
- `Taxa de vínculo PR ↔ Issue: 22%`
- `60 projetos aguardando ativação. [Revisar]`
- `Rate limit do GitHub atingido. Retomando em 12 min.`
- `Watermark atual: 15/04/2026 13:22 UTC (há 2 min)`

Evite copy infantilizada ("Oba!" "Tudo certinho!"). Use tom direto, profissional, confiante.

---

## 11. DADOS MOCK (use para popular a tela)

```json
{
  "global": {
    "health": "healthy",
    "lastUpdatedAt": "2026-04-15T14:02:12Z",
    "kpis": {
      "recordsToday": 12482,
      "recordsTrendPct": 8.2,
      "prIssueLinkRate": 0.220,
      "prIssueLinkTrendPp": 4.2,
      "reposWithDeploy30d": { "covered": 253, "total": 283 },
      "avgSyncLagSec": 252,
      "p95SyncLagSec": 660
    }
  },
  "sources": [
    {
      "id": "github",
      "name": "GitHub",
      "status": "healthy",
      "connections": 283,
      "rateLimitPct": 0.42,
      "watermark": "2026-04-15T13:58:00Z",
      "entities": [
        { "type": "pull_requests", "lastCycleRecords": 342, "lastCycleDurationSec": 4.2, "status": "idle" },
        { "type": "deployments", "lastCycleRecords": 56, "lastCycleDurationSec": 1.1, "status": "idle" }
      ]
    },
    {
      "id": "jira",
      "name": "Jira Cloud",
      "status": "backfilling",
      "catalog": { "active": 69, "discovered": 0, "paused": 0, "blocked": 0, "archived": 0 },
      "rateLimitPct": 0.78,
      "watermark": "2026-04-14T20:59:09Z",
      "entities": [
        {
          "type": "issues",
          "status": "backfilling",
          "steps": [
            { "name": "fetch", "status": "done", "processed": 373633, "total": 373633, "durationSec": 5280 },
            { "name": "changelog", "status": "running", "processed": 212400, "total": 373633, "etaSec": 1080, "throughputPerSec": 148 },
            { "name": "normalize", "status": "running", "processed": 198210, "total": 373633, "etaSec": 1180, "throughputPerSec": 142 },
            { "name": "upsert", "status": "running", "processed": 195003, "total": 373633, "etaSec": 1200, "throughputPerSec": 139 }
          ]
        }
      ]
    },
    {
      "id": "jenkins",
      "name": "Jenkins",
      "status": "degraded",
      "connections": 577,
      "rateLimitPct": 0.21,
      "watermark": "2026-04-15T13:22:10Z",
      "entities": [
        {
          "type": "deployments",
          "status": "degraded",
          "lastCycleRecords": 1396,
          "lastCycleDurationSec": 112,
          "error": "3 jobs classified with unresolved repo (PI-Security/prd-lambda-jira-automation)"
        }
      ]
    }
  ],
  "coverage": {
    "reposWithDeploy": { "covered": 253, "total": 283 },
    "prIssueLinkRate": 0.22,
    "orphanPrefixes": [
      { "prefix": "RC", "prMentions": 1288 },
      { "prefix": "AFDEV", "prMentions": 204 },
      { "prefix": "GE", "prMentions": 101 }
    ],
    "activeProjectsWithoutIssues": [
      { "key": "CAM", "name": "Compras & ADM" },
      { "key": "HR", "name": "Pessoas & Cultura" }
    ]
  },
  "timeline": [
    { "ts": "2026-04-15T14:01:22Z", "severity": "warning", "stage": "jira", "message": "Jira rate limit em 78% (78/100 req/min)" },
    { "ts": "2026-04-15T13:58:00Z", "severity": "success", "stage": "github", "message": "Sync completo: 342 PRs em 4.2s" },
    { "ts": "2026-04-15T13:45:00Z", "severity": "info",    "stage": "jira", "message": "Backfill de changelog iniciado para 60 projetos recém-ativados" },
    { "ts": "2026-04-15T13:22:10Z", "severity": "success", "stage": "jenkins", "message": "Backfill Jenkins completo: 1.396 deployments em 253 repos" },
    { "ts": "2026-04-15T13:20:14Z", "severity": "error",   "stage": "jenkins", "message": "Falha ao resolver repo para job PI-Security/prd-lambda-jira-automation" }
  ]
}
```

---

## 12. CHECKLIST FINAL (auto-review antes de entregar)

Verifique cada item antes de considerar "done":

- [ ] A pergunta "está tudo ok?" é respondida em <2s a partir do topo da tela
- [ ] Cada sub-step (fetch/changelog/normalize/upsert) é visível individualmente com contagem + ETA
- [ ] Escala de 283 repos e 69 projetos não quebra o layout
- [ ] Watermark é visível em cada entidade (absoluto + relativo)
- [ ] Rate limit é primeira classe (gráfico ou meter)
- [ ] Catálogo mostra contagem por status (`discovered`/`active`/etc.)
- [ ] Timeline de eventos suporta 1000+ entradas (virtualized)
- [ ] KPIs de qualidade (link rate, cobertura) estão presentes
- [ ] Todos os 8 estados desenhados (healthy/backfilling/degraded/error/rate-limited/empty/pending/loading)
- [ ] Responsivo desktop + tablet + mobile
- [ ] WCAG AA: contraste, labels de status, reduced-motion
- [ ] Copy em português-BR, tom profissional e direto
- [ ] Tokens do design system PULSE respeitados (cores, tipografia, radii, shadows)
- [ ] Para cada conceito: 3–5 linhas de justificativa editorial + 2 limitações
- [ ] Recomendação final com as 3 mudanças antes de ir pra dev

---

## 13. O QUE NÃO FAZER (anti-patterns)

- ❌ DAG animado com 283 nós — impressiona em demo, quebra em escala real
- ❌ Um único cartão "Pipeline" com lista vertical de steps — ignora multi-fonte
- ❌ Barra de progresso única agregando fetch+changelog+normalize+upsert — feedback do usuário foi explícito contra
- ❌ Usar apenas cor para transmitir status — acessibilidade
- ❌ Exibir autor individual em qualquer contexto — viola princípio anti-surveillance
- ❌ Spinners de loading em qualquer componente — use skeletons
- ❌ Copy infantilizada ou com emoji em excesso — usuário é sênior, tempo é escasso
- ❌ Botão "Trigger Sync Now" que chame API externa — PULSE é READ-ONLY nas fontes; retry só atua em filas internas
- ❌ Gráficos 3D, donuts com >5 segmentos, pie charts para time-series
- ❌ Modal que bloqueia investigação — prefira drawer lateral não-modal

---

## 14. DIRETRIZES DE ENTREGA

Formato esperado do output (para cada conceito):
1. **Screenshot hi-fi** (desktop ≥1280px) da tela completa
2. **Screenshot hi-fi** de 1 estado alternativo importante (backfilling OU degraded)
3. **Screenshot** do drawer de per-entity drill-down
4. **Screenshot responsivo** (mobile OU tablet)
5. **Texto** (3–5 linhas) com a tese editorial do conceito
6. **Texto** (2 bullets) com as limitações conhecidas do conceito
7. **Após os 3 conceitos**: recomendação final + 3 ajustes sugeridos para o conceito vencedor

Vamos.
