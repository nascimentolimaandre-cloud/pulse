# PULSE — Manual de Utilização do Time de Agentes

## Como funciona: a regra de ouro

**Você sempre fala com o Orquestrador.** Ele é a sessão principal do Claude Code — é quem lê seu pedido, decide qual agente (ou combinação de agentes) deve executar, e coordena o fluxo.

Você **nunca** precisa invocar um agente diretamente (embora possa, se quiser). O modelo mental correto é:

```
Você → Orquestrador → Agente(s) → Resultado → Orquestrador → Você
```

Pense no Orquestrador como um Tech Lead que recebe sua demanda, quebra em tarefas, distribui para os especialistas certos, e te entrega o resultado consolidado.

---

## Quando usar cada agente

### Mapa de decisão rápido

```
"Quero definir uma nova feature"
  → Product Director define → Orquestrador coordena implementação

"Quero construir uma página nova"
  → Protótipo? → Frontend Engineer
  → Produção React? → Full-Stack Engineer

"Quero criar uma API de métricas"
  → Data Scientist define a fórmula
  → Data Engineer constrói o pipeline
  → Full-Stack Engineer cria a rota e a página React

"Quero garantir que está tudo testado"
  → Test Engineer

"Quero revisar a segurança"
  → CISO

"Quero saber o status do MVP"
  → /pulse-status (roda no Orquestrador)
```

---

## Cenário 1: Criar uma nova página do zero

**Situação:** Você quer criar a página de Sprint Overview no PULSE.

### Passo 1 — Peça ao Orquestrador (linguagem natural)

```
Você: Preciso criar a página de Sprint Overview. Ela deve mostrar 
o sprint atual com committed/added/completed/carryover, um burndown 
chart, e uma comparação dos últimos 6 sprints.
```

### O que o Orquestrador faz internamente

1. Identifica que é uma feature multi-agente
2. Verifica se existe spec (se não, aciona Product Director)
3. Roteia em sequência:
   - `pulse-data-scientist` → define as fórmulas de sprint metrics
   - `pulse-data-engineer` → garante que `eng_sprints` + `metrics_snapshots` têm os dados
   - `pulse-engineer` → cria a rota API + página React
   - `pulse-frontend` → cria a versão protótipo em HTML/CSS/JS
   - `pulse-test-engineer` → escreve testes
4. Retorna o resultado consolidado

### Alternativa: usar o slash command

```
/pulse-implement Sprint Overview
```

Faz exatamente a mesma coisa, mas com o protocolo formal de implementação.

---

## Cenário 2: Só quero o protótipo visual

**Situação:** Você quer ver como o CFD (Cumulative Flow Diagram) vai ficar antes de implementar.

```
Você: Crie o componente CFD no protótipo. Quero um stacked area chart 
com 5 estágios (Backlog, To Do, In Progress, In Review, Done), 
12 semanas de dados, e tooltips no hover.
```

O Orquestrador detecta: `protótipo` + `componente visual` → roteia direto para `pulse-frontend`.

### Se quiser ser mais direto:

```
/pulse-build CFD prototype
```

Ou forçar o agente explicitamente:

```
Use o pulse-frontend para criar o componente cumulative-flow-diagram 
em pulse-ui/components/cumulative-flow-diagram/ com chart.js stacked 
area, 5 estágios, tooltips customizados, e skeleton loading state.
```

---

## Cenário 3: Definir uma feature nova (Product Director)

**Situação:** Você quer adicionar uma feature de "Scope Creep Alert" que avisa quando o sprint tem mais de 20% de itens adicionados após o início.

### Opção A — Falar com o Orquestrador

```
Você: Quero criar uma feature de alerta de scope creep nos sprints. 
Quando mais de 20% dos itens forem adicionados após o início do sprint, 
o sistema deve mostrar um warning na Sprint Overview.
```

O Orquestrador aciona o `pulse-product-director` para:
- Definir a persona (Carlos, o Engineering Manager)
- Escrever a user story com BDD
- Validar anti-surveillance
- Definir analytics events
- Taggar como MVP ou R1

### Opção B — Usar o slash command

```
/pulse-spec Scope Creep Alert
```

### O que o Product Director retorna

```
Feature: Scope Creep Alert
Persona: Carlos (Engineering Manager)
Story: As Carlos, I want to see a warning when scope creep exceeds 
  20% in a sprint, so that I can address mid-sprint changes early.

BDD:
  Given a sprint with 10 committed items
  When 3 items are added after sprint start
  Then the Sprint Overview shows an amber warning "30% scope creep"
  And the tooltip explains "3 items added after sprint started"

  Given a sprint with 10 committed items
  When 1 item is added after sprint start
  Then no warning is shown (10% < 20% threshold)

Anti-surveillance: ✅ Shows team-level data only, no individual attribution.
Release tag: MVP (part of Epic 3, Sprint metrics)
Analytics event: sprint_scope_creep_warning_viewed
Visualization: Inline badge on Sprint Overview card (amber when >20%, red when >40%)
```

### E depois?

```
Você: Ótimo, agora implementa essa feature.
```

O Orquestrador pega a spec e coordena: Data Scientist → Data Engineer → Engineer → Test Engineer.

---

## Cenário 4: Trabalhar com o Data Scientist (fórmulas e métricas)

**Situação:** Você quer entender como o DORA Overall Classification é calculado.

```
Você: Como é calculado o DORA Overall score? Qual a fórmula?
```

O Orquestrador roteia para `pulse-data-scientist`:

```
Data Scientist: O DORA Overall é o MÍNIMO das classificações individuais 
das 4 métricas. Se você tem:

  - Deployment Frequency: Elite
  - Lead Time: High
  - Change Failure Rate: Medium  ← este é o mínimo
  - MTTR: High

Overall = Medium (o mais baixo)

Hierarquia: Elite > High > Medium > Low

Isso significa que uma equipe precisa melhorar TODAS as métricas para 
subir de classificação. Uma métrica ruim puxa o overall para baixo.

Fórmula em Python:
  def dora_overall(df, lt, cfr, mttr):
      levels = {'elite': 4, 'high': 3, 'medium': 2, 'low': 1}
      min_level = min(levels[df], levels[lt], levels[cfr], levels[mttr])
      return {v: k for k, v in levels.items()}[min_level]
```

### Exemplo mais avançado — pedir recomendação de visualização

```
Você: Quero mostrar a distribuição de Lead Time das issues dos 
últimos 90 dias. Qual o melhor tipo de gráfico?
```

```
Data Scientist: Histograma com linhas de percentil é o ideal aqui.

- Eixo X: bins de lead time (0-2d, 3-5d, 6-10d, 11-15d, 16-20d, 21-30d, 30d+)
- Eixo Y: contagem de issues por bin
- Linhas verticais: P50 (azul tracejado), P85 (amber tracejado), P95 (vermelho tracejado)

Por que histograma e não box plot:
- Engenheiros entendem histogramas intuitivamente
- Os percentis sobrepostos permitem definir SLAs ("85% das issues em <10 dias")
- Box plots escondem a forma da distribuição (bimodal, skew)

Por que NÃO usar média:
- Lead time tem distribuição assimétrica (long tail)
- Mediana + percentis representam melhor a experiência real do time

Isso segue o padrão do ActionableAgile e é o que coaches Kanban esperam ver.
```

---

## Cenário 5: Trabalhar com o Data Engineer (pipeline de dados)

**Situação:** O Sync Worker não está trazendo os dados de deployment do GitHub.

```
Você: Os deployments não estão aparecendo no PULSE DB. O DevLake 
sincroniza os dados, mas o sync worker não está publicando eventos 
de deployment no Kafka.
```

O Orquestrador roteia para `pulse-data-engineer`:

```
Data Engineer: Vou investigar o pipeline de deployments.

1. Verificando se DevLake tem dados na domain layer:
   SELECT COUNT(*) FROM _tool_github_deployments;
   
2. O sync worker lê de `cicd_deployments` (tabela do DevLake domain layer), 
   não de `_tool_github_deployments`. Verifique se o blueprint do DevLake 
   inclui o transformer de deployments:
   
   GET http://localhost:8080/api/plugins/github/connections/1/scopes
   → Confirme que "deployments" está no scope do blueprint
   
3. Se os dados existem no DevLake domain layer, o problema está no 
   sync worker. Verifique:
   - Watermark: o cursor pode estar à frente dos novos dados
   - Schema: eng_deployments.external_id pode ter formato diferente
   
4. Fix: [implementa a correção no sync worker]
```

### Exemplo: criar um novo tópico Kafka

```
Você: Preciso de um novo tópico Kafka para eventos de sprint.
```

```
Data Engineer: Vou criar o tópico domain.sprint.normalized com schema versionado.

Schema do evento:
{
  "schema_version": "1.0",
  "event_type": "sprint.normalized",
  "tenant_id": "uuid",
  "timestamp": "ISO-8601",
  "payload": {
    "external_id": "string",
    "name": "Sprint 23",
    "state": "active|closed|future",
    "started_at": "ISO-8601",
    "ended_at": "ISO-8601|null",
    "committed_items": 12,
    "added_items": 3,
    "completed_items": 10,
    "carryover_items": 2
  }
}

Tópico: domain.sprint.normalized, 2 partições, retenção 7 dias.
Consumer group: pulse-metrics-worker-sprint.

[cria os arquivos necessários]
```

---

## Cenário 6: Trabalhar com o Test Engineer (TDD)

**Situação:** Você quer implementar o cálculo de Cycle Time com TDD.

```
Você: Implemente o cálculo de Cycle Time breakdown com TDD. 
Quero testes primeiro.
```

Ou via command:

```
/pulse-test cycle-time
```

O Test Engineer cria os testes ANTES da implementação:

```python
# tests/unit/test_cycle_time.py

def test_cycle_time_total_is_sum_of_phases():
    """Total cycle time = coding + pickup + review + merge + deploy"""
    prs = [create_pull_request(
        first_commit_at="2024-01-01T09:00:00Z",
        pr_created_at="2024-01-01T17:00:00Z",     # coding: 8h
        first_review_at="2024-01-02T01:00:00Z",    # pickup: 8h
        approved_at="2024-01-02T13:00:00Z",         # review: 12h
        merged_at="2024-01-02T13:30:00Z",           # merge: 0.5h
        deployed_at="2024-01-02T14:30:00Z",         # deploy: 1h
    )]
    result = calculate_cycle_time(prs)
    assert result.total.median == 29.5  # hours
    assert result.phases[0].name == "Coding"
    assert result.phases[0].median == 8.0

def test_cycle_time_identifies_bottleneck():
    """The phase with highest median is marked as bottleneck"""
    prs = [create_pull_request(
        # Review is the longest phase (12h)
        first_review_at=..., approved_at=...
    )]
    result = calculate_cycle_time(prs)
    bottleneck = [p for p in result.phases if p.is_bottleneck]
    assert len(bottleneck) == 1
    assert bottleneck[0].name == "Review"

def test_cycle_time_empty_prs_returns_zero():
    """Edge case: no PRs should return zero, not error"""
    result = calculate_cycle_time([])
    assert result.total.median == 0.0

def test_cycle_time_single_pr():
    """Edge case: single PR should still calculate correctly"""
    prs = [create_pull_request(...)]
    result = calculate_cycle_time(prs)
    assert result.total.median > 0

def test_cycle_time_missing_deploy_excludes_deploy_phase():
    """PRs not yet deployed should calculate up to merge only"""
    prs = [create_pull_request(deployed_at=None)]
    result = calculate_cycle_time(prs)
    assert len(result.phases) == 4  # no deploy phase
```

Depois:

```
Você: Testes escritos. Agora implemente o cálculo para passar os testes.
```

O Orquestrador aciona `pulse-engineer` (ou `pulse-data-engineer` dependendo do contexto) para implementar `cycle_time.py` fazendo todos os testes passarem.

---

## Cenário 7: Trabalhar com o CISO (security review)

**Situação:** Você terminou o Phase 1 e quer validar segurança.

```
Você: Faça um security review completo do Phase 1.
```

Ou:

```
/pulse-review security
```

O CISO analisa e retorna:

```
PULSE Security Review — Phase 1 Bootstrap
==========================================
Score: 72/100

CRITICAL (2):
  1. docker-compose.yml linha 45: postgres service expõe porta 5432 
     no host. Em produção, deve ser internal only.
     Fix: remover "ports: - 5432:5432", usar Docker network interno.

  2. packages/pulse-data/src/workers/devlake_sync.py linha 123: 
     campo "description" da issue não é validado para conteúdo de código.
     Um repositório com issues contendo code blocks pode vazar código.
     Fix: adicionar metadata_validator.strip_code_content(issue.description)

WARNING (4):
  1. .env.example lista GITHUB_TOKEN=ghp_xxxx com formato real de token.
     Fix: usar GITHUB_TOKEN=your_github_pat_here

  2. Containers rodando como root: pulse-api Dockerfile não tem USER directive.
     Fix: adicionar "RUN adduser -D appuser" + "USER appuser"

  3. Sem rate limiting no health endpoint (/health).
     Fix: adicionar @Throttle(100, 60) no controller

  4. gitleaks pre-commit hook não está configurado no .pre-commit-config.yaml
     Fix: adicionar gitleaks hook

SUGGESTION (3):
  1. Adicionar security headers via Helmet.js no NestJS bootstrap
  2. Adicionar CORS restritivo (apenas localhost:5173 em dev)
  3. Adicionar npm audit e pip audit no CI pipeline

Metadata-only enforcement: ⚠️ PARCIAL
  - Sync worker filtra campos de PR corretamente
  - Sync worker NÃO filtra campo description de issues (ver CRITICAL #2)
  - Recomendo: criar metadata_validator como módulo compartilhado
```

---

## Cenário 8: Feature end-to-end (todos os agentes)

**Situação:** "Quero implementar DORA metrics de ponta a ponta."

```
/pulse-implement DORA metrics
```

### Sequência que o Orquestrador executa:

**1. Product Director** (se spec incompleta):
```
Verifica que DORA está especificado como MVP-2.1.1 a MVP-2.1.5.
Personas: Carlos (EM), Ana (CTO).
BDD já definido no release plan. ✅ Spec completa.
```

**2. Data Scientist** define fórmulas:
```
DF = count(deploys) / period_days
LT = median(deployed_at - first_commit_at)
CFR = count(failed) / count(total)
MTTR = median(restored_at - incident_at)
Overall = min classification

Thresholds confirmados. Edge cases: zero deployments → "No data".
Visualization: 4 MetricCards + trend line charts + classification badges.
```

**3. Test Engineer** escreve testes primeiro (TDD):
```
test_dora.py: 15 tests cobrindo cada métrica + edge cases + overall.
Target: 95% coverage. Todos falhando (RED). ✅
```

**4. Data Engineer** constrói pipeline:
```
- eng_deployments schema verificado
- Sync worker: DevLake cicd_deployments → normalize → Kafka
- Metrics worker: consume domain.deployment.normalized → calcula DORA
- Upsert em metrics_snapshots com granularidade diária
```

**5. Full-Stack Engineer** implementa:
```
- pulse-data: src/contexts/metrics/domain/dora.py (faz testes passarem)
- pulse-data: src/contexts/metrics/routes.py (GET /data/v1/metrics/dora)
- pulse-web: src/routes/_dashboard/metrics/dora.tsx
- pulse-web: src/components/charts/DORAClassificationBadge.tsx
- pulse-web: src/hooks/useDoraMetrics.ts
```

**6. Test Engineer** complementa:
```
- Integration tests: API retorna dados corretos do DB
- E2E: Playwright navega Home → clica DORA card → vê 4 métricas
- A11y: axe-core sem violations na página DORA
```

**7. Frontend Engineer** (protótipo):
```
- pulse-ui/pages/metrics-dora.html atualizado com Chart.js
- 4 MetricCards com sparklines e trend badges
- Classification banner (Elite/High/Medium/Low com cores corretas)
```

**8. CISO** valida:
```
- Dados de deployment são metadata-only ✅
- RLS enforced na rota ✅  
- Sem individual developer data exposto ✅
```

---

## Cenário 9: Pedir algo ambíguo

**Situação:** Você pede algo que pode ir para mais de um agente.

```
Você: Cria o componente MetricCard.
```

O Orquestrador vai te perguntar:

```
Orquestrador: O MetricCard deve ser criado no protótipo (pulse-ui/, 
HTML/CSS/JS com Chart.js) ou na produção (packages/pulse-web/, 
React com Recharts)?

Ou ambos?
```

Para evitar isso, seja específico:

```
# Protótipo
Cria o MetricCard no protótipo com sparkline em Chart.js

# Produção
Cria o MetricCard em React com Recharts no pulse-web

# Ambos
Cria o MetricCard no protótipo e na produção
```

---

## Cenário 10: Invocação direta de um agente

Embora o Orquestrador seja o padrão, você pode invocar qualquer agente diretamente:

```
# Forçar o Data Scientist
Use o pulse-data-scientist para validar se a fórmula de CFD 
está correta considerando issues que mudam de status mais de uma vez.

# Forçar o CISO
Use o pulse-ciso para criar o threat model do fluxo de 
OAuth connector que vamos implementar no R1.

# Forçar o Product Director
Use o pulse-product-director para escrever o PR/FAQ (Amazon Working 
Backwards) da feature de Monte Carlo forecasting do R2.

# Forçar o Test Engineer
Use o pulse-test-engineer para criar os page objects do Playwright 
para todas as páginas do dashboard.

# Forçar o Data Engineer
Use o pulse-data-engineer para otimizar a query de CFD que está 
levando 2 segundos — precisa ficar abaixo de 500ms.

# Forçar o Frontend Engineer
Use o pulse-frontend para criar a animação de skeleton loading 
no design system com CSS shimmer effect.

# Forçar o Full-Stack Engineer
Use o pulse-engineer para configurar o TanStack Router com 
type-safe routes para todas as 11 páginas do MVP.
```

---

## Referência rápida dos Slash Commands

### /pulse-build — Constrói qualquer coisa

```bash
/pulse-build MetricCard prototype          # → Frontend Engineer
/pulse-build DORA api route                # → Full-Stack Engineer
/pulse-build sync worker for deployments   # → Data Engineer
/pulse-build DORA classification logic     # → Data Scientist
/pulse-build Playwright page objects       # → Test Engineer
/pulse-build RLS policies for eng_sprints  # → CISO
/pulse-build Sprint Overview user story    # → Product Director
```

### /pulse-bootstrap — Infraestrutura por fases

```bash
/pulse-bootstrap        # Phase 1: skeleton + Docker + CI
/pulse-bootstrap 2      # Phase 2: DevLake + Kafka + workers
/pulse-bootstrap 3      # Phase 3: API routes + React pages + dashboards
```

### /pulse-implement — Feature end-to-end

```bash
/pulse-implement MVP-2.1.1                 # Por story ID
/pulse-implement DORA metrics              # Por feature name
/pulse-implement CFD component             # Componente específico
/pulse-implement Sprint Comparison chart   # Chart específico
```

### /pulse-test — Testes com TDD

```bash
/pulse-test dora          # TDD: testes de DORA primeiro
/pulse-test lean          # TDD: testes de Lean metrics
/pulse-test cycle-time    # TDD: testes de Cycle Time
/pulse-test api           # Integration tests
/pulse-test web           # Component tests
/pulse-test e2e           # Playwright journeys
/pulse-test all           # Tudo: lint + unit + integration
```

### /pulse-review — Code review por domínio

```bash
/pulse-review pulse-ui/                    # Design tokens, HTML, a11y
/pulse-review packages/pulse-api/          # Architecture, TypeScript
/pulse-review packages/pulse-data/         # Python, domain logic
/pulse-review security                     # RLS, secrets, headers
/pulse-review data-quality                 # Pipeline, idempotency
/pulse-review metrics                      # Formula correctness
/pulse-review tests                        # Coverage, flakiness
```

### /pulse-spec — Especificação de feature

```bash
/pulse-spec WIP Monitor                    # Feature spec com BDD
/pulse-spec Sprint Comparison              # User story + criteria
/pulse-spec Scope Creep Alert              # Nova feature
```

### /pulse-status — Progresso do MVP

```bash
/pulse-status              # Dashboard visual de progresso
```

---

## Perguntas frequentes

### "Posso falar direto com o Product Director sem passar pelo Orquestrador?"

Sim, mas o Orquestrador não vai saber o que vocês discutiram. O melhor fluxo é:

```
# Bom: Orquestrador coordena tudo
Você: Preciso definir a feature de Monte Carlo forecasting para o R2.
→ Orquestrador aciona Product Director
→ Resultado fica no contexto do Orquestrador para coordenar implementação depois

# Também funciona: invocação direta quando você só quer consultoria
Use o pulse-product-director para me explicar como funciona o 
pricing do tier Business e por que $39/dev/month.
→ Resposta vem direto, sem necessidade de coordenar implementação
```

### "E se dois agentes discordarem?"

O Orquestrador resolve conflitos. Exemplo: o Engineer quer simplificar o schema e o Data Engineer diz que precisa de mais colunas. O Orquestrador analisa os tradeoffs e decide com base nos documentos de arquitetura.

### "Posso adicionar um agente novo?"

Sim. Crie um `.md` em `.claude/agents/` com frontmatter YAML (name, description, tools, model) e o system prompt em markdown. Depois adicione as regras de roteamento no `CLAUDE.md`.

### "Os agentes se lembram de conversas anteriores?"

Não. Cada subagente roda em contexto isolado. O que ele retorna ao Orquestrador é um resumo. Por isso o protocolo de delegação inclui sempre: scope, spec reference, dependencies, acceptance criteria.

### "Opus ou Sonnet — quando usar cada um?"

- **Opus** (Product Director, Frontend, Engineer, Data Engineer): fazem trabalho pesado de implementação que exige raciocínio longo e qualidade máxima.
- **Sonnet** (Data Scientist, Test Engineer, CISO): consultoria, validação e revisão — tarefas mais focadas onde Sonnet é rápido e eficiente.

Você pode mudar o model de qualquer agente editando o campo `model:` no frontmatter do `.md`.

### "Qual a ordem ideal para construir o MVP?"

```
1. /pulse-bootstrap           → Infraestrutura base
2. /pulse-bootstrap 2         → Pipeline de dados rodando
3. /pulse-test dora            → TDD: testes de DORA
4. /pulse-implement DORA metrics  → DORA end-to-end
5. /pulse-test lean            → TDD: testes de Lean
6. /pulse-implement Lean metrics  → Lean end-to-end
7. /pulse-implement Cycle Time    → Cycle Time
8. /pulse-implement Sprint metrics → Sprint
9. /pulse-implement Home dashboard → Home page
10. /pulse-review security      → CISO valida tudo
11. /pulse-test e2e             → Playwright journeys
12. /pulse-status               → Verificar completude
```
