# PULSE — Estratégia de Testes

> **Versão:** 1.0 — Abril 2026
> **Autor:** pulse-test-engineer
> **Status:** Aguardando aprovação
> **Contexto:** cliente-âncora Webmotors — 374k issues, 57k PRs, 27 squads, 50 EMs, ~200 devs

---

## 1. TL;DR

**Problema.** O PULSE tem 278 testes unitários de backend funcionando, mas o frontend carece quase completamente de cobertura automática (55 Vitests apenas em utilities), e toda a camada de E2E, performance e segurança é inexistente. Quatro bugs escaparam para produção em dois dias (16–17/04) — UUID regex, split_part de repo, throughput uniforme em períodos diferentes, Cycle Time P50 absurdo — todos teriámos capturado com testes de integração e contrato. Dois princípios não-negociáveis (anti-surveillance e multi-tenant RLS) não têm gates automatizados, só convenção de código.

**Abordagem.** Pirâmide clássica rebalanceada: unit sólido já existe no backend — prioridade imediata é preencher o frontend (component + hook + E2E) e criar uma camada de segurança automatizada. A sequência proposta é: quick wins retroativos nos 5 bugs escapados → fundação de ferramentas (Vitest RTL + Playwright + MSW + k6) → cobertura progressiva em 6 sprints. Foco em feedback rápido: PR gate < 10 minutos.

**ROI esperado.** Com Sprint 1 completo (fundação + quick wins): elimina regressões do tipo INC-001/002/003 (throughput, cycle time, snapshot drift). Com Sprint 3 completo (E2E happy paths): detecta breaking changes de API antes de chegar ao usuário. Custo estimado: ~200 h/homem ao longo de 6 sprints + ferramentas predominantemente gratuitas (ver Seção 10 para custo detalhado).

**Proximo passo imediato.** Aprovação desta estratégia → Sprint 1 começa com os 6 testes retroativos (quick wins).

> ⚠️ **CI/CD do PULSE usa GitHub Actions** (pipeline em `pulse/.github/workflows/`).
> O arquivo de memória `project_jenkins_cicd.md` refere-se à **Webmotors** como
> cliente (que usa Jenkins pra deployar as próprias aplicações — monitoradas pelo
> PULSE via connector READ-ONLY). Não confundir com o CI do próprio PULSE.

---

## 2. Princípios da Estratégia

> **Separação crítica arquitetural** — ver `pulse/docs/testing-playbook.md`.
> Testes de **plataforma** (universais, rodam em qualquer tenant) ficam em
> `pulse/packages/<service>/tests/`. Testes **customer-specific** (validam
> premissas de um cliente) ficam em `pulse/packages/<service>/tests-customers/<customer>/`.
> Métrica de cobertura headline é **platform coverage**; customer coverage é
> complementar por cliente. Ver Seção 2.5 abaixo.

### 2.1 Pirâmide de Testes Adaptada

```
                     ┌────────────┐
                     │   E2E      │  8-10 jornadas (Playwright)
                     │  ~5%       │
                    ┌┴────────────┴┐
                    │  Integration │  API + Data + Contract
                    │    ~25%      │
                   ┌┴──────────────┴┐
                   │   Component/   │
                   │   Hook (FE)    │  Vitest + RTL + MSW
                   │     ~20%       │
                  ┌┴────────────────┴┐
                  │   Unit (BE+FE)   │  Pytest + Vitest
                  │      ~50%        │  (backend: existe; frontend: deficit)
                  └──────────────────┘
```

As proporções do PULSE diferem da pirâmide canônica porque:
- O cálculo de métricas (camada mais crítica) é domínio puro Python — unit adequado.
- O frontend hoje tem quasi-zero cobertura — component e hook recebem peso acima do normal até equilibrar.
- E2E é intencionalmente pequeno: 8-10 jornadas críticas, não testa cada estado de UI.

### 2.2 Test Data Strategy

**Dados sintéticos determinísticos** para todos os testes de métrica. Nunca `random()` sem seed fixo. O padrão de golden file é utilizado para outputs de métricas complexas (CFD, scatterplot): o output calculado é serializado na primeira execução e comparado em runs subsequentes.

**Três conjuntos de fixtures fixos:**

- `happy_path`: 8 semanas de dados realistas Webmotors — 27 squads, ~200 PRs/semana, 2000 issues, 428 deploys em 60 dias. Fundamentado nos valores de produção reais.
- `edge_cases`: vazio, item único, valores de boundary (exatamente 1 deploy em 30 dias, CFR = 0%, CFR = 100%, sprint com 0 committed items).
- `large_volume`: 1000+ PRs, 10000+ issues para benchmark de performance do worker e da API.

**Dados de PII:** zero dados reais em testes. Nomes de usuários, emails e assignees são sempre gerados via factory com dados fictícios (ex: `assignee: "user-{uuid}"` quando necessário para testar RLS, nunca nomes reais).

### 2.3 Politica de Flakiness

**Zero tolerância para flakiness em CI.** Um teste que falha de forma não-determinística uma vez é imediatamente movido para quarentena (label `@flaky`) e excluído do quality gate até ser corrigido. O responsável pelo PR que introduziu o teste é dono da correção.

Causas raiz de flakiness que devem ser eliminadas proativamente:
- `time.sleep()` — proibido. Usar `wait_for_condition()` ou eventos explícitos.
- Dependência de timestamp do relógio real — sempre usar timestamps controlados/injetados.
- Estado compartilhado entre testes — cada teste deve ser idempotente e auto-suficiente.
- Playwright com `waitForTimeout()` — proibido. Usar `waitForSelector()`, `waitForResponse()`, ou polling com timeout explícito.

O rate de flakiness alvo é menor que 1% medido como: `falhas não-determinísticas / total de execuções` nos últimos 14 dias.

### 2.4 Isolation entre Testes

**Backend (Pytest):** cada teste de integração roda dentro de uma transaction que é rolled back ao final. O `app.current_tenant` é setado explicitamente em cada teste multi-tenant via fixture de session. Testcontainers sobem PostgreSQL isolado para testes de integração — nunca banco compartilhado.

**Frontend (Vitest):** cada teste tem seu próprio store isolado (reset via `beforeEach`). MSW server é iniciado `beforeAll` e resetado `afterEach`. Não há estado global persistindo entre arquivos de teste.

**E2E (Playwright):** cada jornada começa com seed de dados via API de teste (não via UI). Browser context isolado por arquivo de spec. Nenhum teste depende de dados criados por outro teste.

### 2.5 Separação Platform vs Customer-Specific

#### Contexto estratégico

O PULSE é um SaaS multi-tenant. A estratégia de testes reflete essa realidade: existem testes que validam a **plataforma** (invariantes universais, schemas, algoritmos) e testes que validam **premissas específicas de um cliente** (mapeamentos, taxonomias, valores ground-truth de produção). Essas duas categorias devem permanecer claramente separadas para que seja possível medir cobertura da plataforma independentemente de qualquer cliente.

#### Estrutura de diretórios

**Backend (pulse-data)**:
```
pulse/packages/pulse-data/tests/              ← PLATFORM tests
  unit/                                       ← funções puras, domain, fórmulas canônicas
  integration/                                ← API + DB com fixtures sintéticas deterministas
  contract/                                   ← schemas Pydantic, anti-surveillance gate
  fixtures/                                   ← factories sintéticas reutilizáveis

pulse/packages/pulse-data/tests-customers/    ← CUSTOMER-specific tests
  webmotors/
    README.md                                 ← contexto Webmotors (Jira projects, status mapping)
    test_webmotors_throughput_values.py       ← ground truth: throughput(60d)=5044, (90d)=7341, (120d)=9007
    test_webmotors_status_mapping.py          ← ex: "Aguardando Code Review" = in_review
    test_webmotors_squad_taxonomy.py          ← ex: squads têm códigos de 2-5 chars maiúsculos
    test_webmotors_data_quality.py            ← ex: zumbis Jira > 365d detectados
    test_webmotors_fontes_coverage.py         ← 27 squads têm sources > 0
    fixtures/
      jira_projects_sample.json               ← padrões Jira Webmotors reais (anonimizados)
      sprint_boards_sample.json
```

**Frontend (pulse-web)**:
```
pulse/packages/pulse-web/tests/               ← PLATFORM tests
  unit/
  component/
  hook/
  e2e/
    platform/                                 ← jornadas genéricas

pulse/packages/pulse-web/tests-customers/     ← CUSTOMER-specific
  webmotors/
    README.md
    e2e/
      webmotors-squad-names.spec.ts           ← ex: "PF - OEM Integração" aparece corretamente
      webmotors-fid-sprints.spec.ts           ← FID tem sprints, BG não
```

#### Princípios

1. **Testes platform** funcionam em qualquer tenant com qualquer dado sintético. São a métrica headline de cobertura do projeto.
2. **Testes customer** validam premissas específicas de um cliente — mapeamentos, taxonomias, valores de produção ground-truth. Usam dados reais (anonimizados) ou padrões observados do cliente.
3. **Testes customer fazem skip gracioso** quando o ambiente não tem os dados do cliente (banco sem dados de produção, CI sem credenciais do tenant). A flag `SKIP_IF_NO_CUSTOMER_DATA=true` ativa esse comportamento.
4. **Coverage reporting separado** — dois indicadores independentes:
   - **Platform coverage** (métrica headline, exibida no README e em Codecov)
   - **Customer coverage** (métrica por cliente, complementar)
   - Prefixo `customer_<name>` nos relatórios de cobertura para separação fácil em Grafana/Codecov.
5. **Execução em CI**:
   - Testes platform: rodam em **todo PR** (falha bloqueia merge)
   - Testes customer: rodam em **nightly** OU em PRs com mudanças em código cliente-specific (detectado via path filter no GitHub Actions)

#### Como adicionar testes de um novo cliente

1. Criar `tests-customers/<client-slug>/` com `README.md` descrevendo o contexto do cliente.
2. Criar `tests-customers/<client-slug>/fixtures/` com amostras de dados anonimizados.
3. Implementar a fixture `customer_db_url` que retorna `None` (skip) quando `SKIP_IF_NO_CUSTOMER_DATA=true` ou quando a connection string não está configurada.
4. Todos os testes devem usar `pytest.mark.customer_<client-slug>` para filtragem.
5. Adicionar job `tests-customer-<client-slug>-backend` ao `.github/workflows/ci.yml` com trigger em `nightly` + path filter para mudanças em `tests-customers/<client-slug>/`.
6. Registrar ground-truth values no README do cliente com data de última verificação.
7. Nunca commitar dados reais não-anonimizados — usar factories ou snapshots com PII removido.
8. Testes de ground-truth (ex: `throughput(60d) ≈ 5044`) devem ter tolerância de ±5% para acomodar drift de dados no ambiente de staging.
9. Documentar no README do cliente quais squads/projetos/repos são cobertos pelos testes.
10. Registrar a adição do cliente no CHANGELOG da estratégia de testes.

---

## 3. Camadas de Teste — Tabela Mestra

| # | Camada | Ferramenta | Escopo | Onde Roda | Owner | Critério de Sucesso | Custo |
|---|--------|------------|--------|-----------|-------|---------------------|-------|
| 1 | **Unit BE — domínio** | Pytest 8 + pytest-cov | Funções puras: `dora.py`, `cycle_time.py`, `lean.py`, `sprint.py`, `throughput.py` | Local + CI (unit job) | pulse-test-engineer | Cobertura ≥ 95%; todos os edge cases + anti-surveillance passando; execução < 5s | Free |
| 2 | **Unit BE — routes/services** | Pytest + httpx AsyncClient | Routes FastAPI sem banco; services com mocks de repository | Local + CI (unit job) | pulse-engineer | Cobertura ≥ 80%; 400/422 validados; RLS setado em todos os endpoints | Free |
| 3 | **Unit FE — utilities** | Vitest 2 | `transforms.ts`, `formatDuration.ts`, `api/metrics.ts` (parsing) | Local + CI | pulse-test-engineer | Cobertura ≥ 80%; atualmente 55 testes — expandir para ~120 | Free |
| 4 | **Unit FE — componentes** | Vitest + RTL (React Testing Library) | `MetricCard`, `FilterBar`, `TrendChart`, `PipelineStep`, `DiscoveryStatus` | Local + CI | pulse-test-engineer | Cobertura ≥ 80%; todos os 6 estados (loading/empty/healthy/degraded/error/partial) | Free |
| 5 | **Unit FE — hooks** | Vitest + RTL + MSW | `useMetrics`, `useGlobalFilters`, `useCapabilities`, `usePipelineHealth` | Local + CI | pulse-test-engineer | Cobertura ≥ 80%; testa estados de erro e loading; mock via MSW (não jest.mock) | Free |
| 6 | **Integration BE — API** | Pytest + httpx + Testcontainers (PostgreSQL 16) | Endpoints reais contra banco real; testa RLS, filtros, períodos | CI (integration job) | pulse-test-engineer | ≥ 70% dos endpoints cobertos; RLS isolation testado; squad UUID regex validado | Free (Docker obrigatório) |
| 7 | **Integration BE — Data/Worker** | Pytest + Testcontainers (PostgreSQL + Kafka) | Metrics Worker end-to-end: evento Kafka → calculo → snapshot no banco | CI (integration job) | pulse-data-engineer | Throughput 60d ≠ 90d ≠ 120d; INC-001/002 não regressam | Free (Docker) |
| 8 | **Contract — Zod** | Vitest + Zod schemas | Respostas da API validadas contra os schemas Zod do frontend (ex: `HomeMetricsResponse`) | CI (unit job) | pulse-test-engineer | Zero respostas reais violando schema Zod; campo `assignee` ausente em todos os payloads | Free |
| 9 | **E2E** | Playwright 1.44+ | 8-10 jornadas críticas (ver Seção 5); multi-browser (Chrome + Firefox) | CI (nightly + smoke em PR merge) | pulse-test-engineer | Todas as jornadas passando; smoke (3 jornadas) < 3 min | Free (OSS) |
| 10 | **Visual Regression** | Playwright screenshot comparison | Home dashboard, DORA drill-down, Pipeline Monitor, Lean CFD | CI (nightly) | pulse-test-engineer | Delta < 0.1% pixel; snapshots versionados em git | Free (Playwright built-in) |
| 11 | **A11y** | axe-core via Playwright + `@axe-core/playwright` | Todas as rotas frontend: 0 violações WCAG AA | CI (pr-merge job) | pulse-test-engineer | Zero violações de nível critical/serious em todas as rotas | Free |
| 12 | **Perf Benchmark BE** | pytest-benchmark | Funções de cálculo com `large_volume` fixture: calculate_dora_metrics, calculate_throughput, etc. | CI (nightly) | pulse-test-engineer | P95 < 200ms para dataset Webmotors (10k issues); regressão de ≥ 20% bloqueia | Free |
| 13 | **Load** | k6 (OSS) | Cenário Webmotors: 50 usuários simultâneos, 10 min sustentado, todos os endpoints `/metrics/*` | CI (nightly/weekly) | pulse-test-engineer | P95 < 500ms; erro rate < 1% | Free (k6 OSS) |
| 14 | **Stress** | k6 | Ramp-up até 200 usuários (4x normal); identifica ponto de quebra | CI (semanal) | pulse-test-engineer | Sistema degrada graciosamente; sem OOM; sem corrupção de dados | Free |
| 15 | **Spike** | k6 | 0 → 200 usuários em 10s; 0 → 500 issues processados em burst pelo worker | Manual / CI semanal | pulse-test-engineer | Tempo de recuperação < 60s após spike; sem perda de requests enfileirados | Free |
| 16 | **Soak** | k6 | 30 usuários por 2h; detecta memory leak no worker Python e connection pool exhaustion | CI (semanal) | pulse-test-engineer | Sem degradação > 10% no P95 entre minuto 1 e minuto 120 | Free |
| 17 | **SAST** | Bandit (Python) + Semgrep + ESLint-plugin-security (TS) | Todo código em `pulse/packages/`; regras: SQL injection, hardcoded secrets, eval, SSRF patterns | CI (pr build) | pulse-ciso | Zero findings HIGH ou CRITICAL não-suprimidos | Free |
| 18 | **SCA** | pip-audit + npm audit + Trivy (SCA mode) | `requirements*.txt`, `package-lock.json`, `pyproject.toml` | CI (pr build) | pulse-ciso | Zero vulnerabilidades HIGH/CRITICAL sem mitigação documentada | Free |
| 19 | **Container Security** | Trivy (image scan) | Images Docker: `pulse-data`, `pulse-api`, `pulse-web` | CI (build job) | pulse-ciso | Zero HIGH/CRITICAL CVEs; usuário não-root; sem secrets em layers | Free |
| 20 | **DAST** | OWASP ZAP (Baseline Scan mode) | API FastAPI em ambiente de staging; scan passivo + active rules selecionadas | CI (nightly) | pulse-ciso | Zero findings MEDIUM+ sem mitigação; relatório gerado automaticamente | Free (OSS) |
| 21 | **Secrets** | Gitleaks | Todo o histórico git + novos commits; hooks pre-commit + CI | CI (pr build) | pulse-ciso | Zero secrets detectados; baseline de falsos positivos documentado | Free |
| 22 | **Anti-surveillance Contract Gate** | Pytest (BE) + Vitest (FE) | Todos os endpoints e schemas: nenhum campo `assignee`, `author_name`, `developer`, `committer` em payloads de métricas | CI (unit job) | pulse-test-engineer | Zero campos proibidos detectados automaticamente; gate bloqueia PR | Free |

---

## 4. Mapa de Cobertura por Surface

> **Legenda de escopo:** `[P]` = Platform test (roda em todo PR, counts toward platform coverage). `[C:wm]` = Customer-specific test Webmotors (roda em nightly + path filter).

### 4.1 Endpoints Backend

| Endpoint | Unit | Integration | Contract | Load | DAST | Escopo | Prioridade | Owner |
|----------|------|-------------|----------|------|------|--------|------------|-------|
| `GET /data/v1/metrics/home` | Sim (services) | Sim (snapshot drift) | Sim (Zod) | Sim | Sim | `[P]` | P0 — home é a primeira tela |pulse-test-engineer |
| `GET /data/v1/metrics/dora` | Sim (domain) | Sim (RLS) | Sim | Sim | Sim | P0 | pulse-test-engineer |
| `GET /data/v1/metrics/cycle-time` | Sim (domain) | Sim (first_commit_at proxy INC-003) | Sim | Sim | Sim | P0 | pulse-test-engineer |
| `GET /data/v1/metrics/throughput` | Sim (domain) | Sim (períodos 60d≠90d≠120d INC-001) | Sim | Sim | Sim | P0 | pulse-test-engineer |
| `GET /data/v1/metrics/lean` | Sim (domain) | Sim | Sim | Sim | Sim | P0 | pulse-test-engineer |
| `GET /data/v1/metrics/sprints` | Sim (domain) | Sim (squad_key filter INC-UUID) | Sim | Sim | Sim | P1 | pulse-test-engineer |
| `GET /data/v1/metrics/recalculate` | Sim (service) | Sim (background task) | Nao | Nao | Sim | P1 | pulse-engineer |
| `GET /data/v1/pipeline/health` | Sim | Sim (split_part bug INC-FONTES) | Sim | Sim | Sim | P0 | pulse-test-engineer |
| `GET /data/v1/pipeline/coverage` | Sim | Sim | Sim | Sim | Sim | P1 | pulse-test-engineer |
| `GET /data/v1/pipeline/timeline` | Sim | Sim | Sim | Nao | Sim | P1 | pulse-test-engineer |
| `GET /data/v1/pipeline/steps` | Sim | Sim | Sim | Nao | Sim | P1 | pulse-test-engineer |
| `GET /data/v1/engineering/pull-requests` | Sim | Sim (filtro squad UUID regex INC-422) | Sim | Sim | Sim | P0 | pulse-test-engineer |
| `GET /data/v1/engineering/issues` | Sim | Sim | Sim | Sim | Sim | P1 | pulse-test-engineer |
| `GET /data/v1/engineering/integrations` | Sim | Sim | Sim | Nao | Sim | P2 | pulse-test-engineer |
| `GET /data/v1/tenant/capabilities` | Sim | Sim (squad_key scoped) | Sim | Nao | Sim | P1 | pulse-test-engineer |
| `POST /data/v1/admin/jira/discovery/trigger` | Sim (unit/mock) | Sim (idempotencia) | Nao | Nao | Sim (authZ) | P1 | pulse-ciso |
| `GET /data/v1/admin/jira/projects` | Sim | Sim | Sim | Nao | Sim | P1 | pulse-test-engineer |
| `PUT /data/v1/admin/jira/projects/{id}/mode` | Sim | Sim | Nao | Nao | Sim (authZ) | P1 | pulse-ciso |
| **Anti-surveillance gate** | Sim (todos os schemas acima) | Sim | Sim | N/A | Sim | P0 | pulse-test-engineer |

### 4.2 Rotas Frontend

| Rota | Component Tests | Hook Tests | E2E | A11y | Visual Reg. | Prioridade |
|------|----------------|------------|-----|------|-------------|------------|
| `/` (Home Dashboard) | Sim (MetricCard x6, FilterBar) | Sim (useMetrics, useGlobalFilters) | Sim (jornada 1) | Sim | Sim | P0 |
| `/metrics/dora` | Sim (DoraCard, ClassificationBadge, TrendChart) | Sim (useMetrics) | Sim (jornada 2) | Sim | Sim | P0 |
| `/metrics/cycle-time` | Sim (BreakdownBar, PhaseChart) | Sim | Sim (jornada 3) | Sim | Sim | P0 |
| `/metrics/throughput` | Sim (ThroughputChart, PrTable) | Sim | Sim (jornada 3) | Sim | Sim | P0 |
| `/metrics/lean` | Sim (CFD, Scatterplot, WipGauge) | Sim | Sim (jornada 4) | Sim | Sim | P0 |
| `/metrics/sprints` | Sim (SprintCard, VelocityChart) | Sim | Sim (jornada 5) | Sim | Sim | P1 |
| `/pipeline-monitor` | Sim (StepRow, TeamHealthTable, SourceBadge) | Sim | Sim (jornada 6) | Sim | Sim | P0 |
| `/integrations` (lista) | Sim | Nao | Sim (jornada 7) | Sim | Nao | P1 |
| `/integrations/jira` (config) | Sim (ModeSelector, DiscoveryStatus) | Sim | Sim (jornada 8) | Sim | Nao | P1 |
| `/integrations/jira/catalog` | Sim (ProjectCatalogTable — ja existe) | Nao | Sim (parcial) | Sim | Nao | P2 |
| `/integrations/jira/audit` | Sim | Nao | Nao | Sim | Nao | P2 |

### 4.3 Workers (Eventos Kafka / Background Tasks)

| Worker | Unit (domain) | Integration | Regressao | Prioridade |
|--------|---------------|-------------|-----------|------------|
| `metrics_worker.py` — calculo throughput por período | Sim (ja existe domain) | Sim (INC-001: 60d≠90d≠120d devem diferir) | Sim — ground truth: 5044/7341/9007 | P0 |
| `metrics_worker.py` — snapshot upsert por período | Nao | Sim (INC-002: snapshot drift após restart) | Sim | P0 |
| `metrics_worker.py` — cycle time first_commit_at | Sim | Sim (INC-003: P50 não pode ser < 1h quando PRs levam dias) | Sim | P0 |
| `devlake_sync.py` — description backfill 100-item limit | Nao | Sim (INC-backfill: deve processar além de 100) | Sim | P1 |
| `discovery_scheduler.py` — Jira dynamic discovery | Sim (ja existe) | Sim (guardrails, idempotencia) | Sim | P1 |
| Workers — PII masking no log | Nao | Sim (assertar que logs nao contem assignee names) | Nao | P1 |

---

## 5. Performance, Load & Stress (Detalhado)

### 5.1 Cenario Base Webmotors

- **50 EMs** acessando o dashboard simultaneamente (pico: daily standup, reuniao de PI)
- **200 devs** com acesso eventual (não simultâneo)
- **27 squads** — filtros de squad triggering queries independentes
- **Workload de pico:** segunda-feira 09:00 — abertura da semana, todos os EMs checando métricas ao mesmo tempo
- **Batch background:** metrics_worker recalculando 374k issues enquanto usuários acessam API

### 5.2 SLOs Propostos por Endpoint

| Endpoint / Surface | P50 | P95 | Erro Rate Max | Notas |
|-------------------|-----|-----|---------------|-------|
| `GET /metrics/home` | < 200ms | < 500ms | < 0.5% | Cache agressivo (snapshots pre-calculados) |
| `GET /metrics/dora` | < 300ms | < 800ms | < 0.5% | On-demand com on_demand service |
| `GET /metrics/cycle-time` | < 300ms | < 800ms | < 0.5% | |
| `GET /metrics/throughput` | < 300ms | < 800ms | < 0.5% | Crítico — historicamente com INC-001 |
| `GET /metrics/lean` | < 400ms | < 1s | < 0.5% | CFD é o mais pesado |
| `GET /pipeline/health` | < 500ms | < 1.5s | < 1% | Query complexa com JOINs |
| `POST /admin/jira/discovery` | < 2s | < 5s | < 2% | Dispara background task |
| `GET /tenant/capabilities` | < 50ms | < 150ms | < 0.1% | Redis cache 5min |
| Recalculo completo (background) | — | < 60s | — | SLO interno do worker |

### 5.3 Web Vitals Targets (Frontend)

| Metrica | Target | Ferramenta de Medicao |
|---------|--------|-----------------------|
| FCP (First Contentful Paint) | < 1.5s | Playwright + Lighthouse CI |
| LCP (Largest Contentful Paint) | < 2.5s | Lighthouse CI |
| TBT (Total Blocking Time) | < 300ms | Lighthouse CI |
| CLS (Cumulative Layout Shift) | < 0.1 | Playwright + `web-vitals` |
| TTI (Time to Interactive) | < 3.5s | Lighthouse CI |

### 5.4 Tipos de Teste de Performance

**Smoke (< 5 min)** — Executado em todo PR merge para garantir que nenhuma mudança introduziu regressao catastrófica. Cenário: 5 usuários, 1 min, apenas os 3 endpoints mais críticos (home, dora, pipeline/health).

**Load (< 20 min)** — Cenário completo Webmotors: ramp-up 0→50 usuários em 2 min, sustentado por 10 min, ramp-down 2 min. Todos os 8 endpoints de métricas. Valida SLOs acima. Executado nightly.

**Stress (< 30 min)** — 0→200 usuários (4x capacidade nominal). Objetivo: identificar ponto de quebra e comportamento sob sobrecarga. Espera-se degradação gracefull (HTTP 503 com Retry-After), nunca corrupção de dados ou crash. Executado semanalmente.

**Spike (< 15 min)** — 0→200 usuários em 10 segundos (simula abertura do dashboard no all-hands). Valida que a aplicação volta ao SLO dentro de 60s após o pico. Executado semanalmente.

**Soak (2h)** — 30 usuários por 2 horas contínuas. Objetivo: detectar memory leak no worker Python, connection pool exhaustion no PostgreSQL, e degradação lenta de P95. Se o P95 no minuto 120 for > 10% acima do minuto 1, o teste falha. Executado semanalmente (sexta à noite).

**Capacity Benchmark (trimestral)** — Determina o número máximo de tenants simultâneos antes de saturar o banco. Input para decisões de infra/scaling.

### 5.5 Justificativa k6 vs Alternativas

**k6** foi escolhido sobre Locust e Gatling pelos seguintes motivos:

- **k6 vs Locust:** k6 tem DSL em JavaScript (mesma linguagem do frontend — menor barreira para o time), é compilado em Go (muito mais eficiente em CPU por virtual user), e tem suporte nativo a thresholds que falham o CI automaticamente. Locust é Python puro mas o GIL limita o throughput real de VUs.
- **k6 vs Gatling:** Gatling requer Scala/Java, é mais complexo de configurar, e o relatório HTML detalhado é pago (Gatling Enterprise). k6 tem integração gratuita com Grafana Cloud para dashboards de load test.
- **k6 vs Artillery:** Artillery tem boa integração com AWS mas é menos maduro para stress e soak de longa duração. k6 tem ecossistema maior e melhor suporte para WebSockets se o PULSE adicionar streaming no futuro.

---

## 6. Segurança (Detalhado)

### 6.1 Threat Model por Superficie

**Superficie 1 — AuthZ + RLS Multi-Tenant Isolation**
Risco: tenant A lê dados do tenant B por SQL injection, misconfiguration de `app.current_tenant`, ou bypass de middleware. Controle: testes de integração com dois tenants distintos assertam que queries com tenant_A_id nunca retornam rows do tenant_B. Gate automatizado em CI via Pytest + Testcontainers.

**Superficie 2 — Anti-Surveillance Contract Gate**
Risco: um desenvolvedor inadvertidamente adiciona campo `assignee` ou `author_name` em um schema de métricas, expondo dados individuais. Controle: teste automatizado que inspeciona todos os schemas Pydantic de resposta e todos os schemas Zod do frontend, verificando ausencia de campos proibidos (lista: `assignee`, `author`, `author_name`, `developer`, `committer`, `user_id` em contextos de métrica). Gate bloqueia PR.

**Superficie 3 — SQL Injection**
Risco: inputs de usuário não sanitizados em queries SQLAlchemy. Controle: SQLAlchemy com parametros bindados (ORM e text() com bindparams) — nunca f-string em SQL. SAST com Bandit (B608: hardcoded_sql_expressions) e Semgrep rule `python.sqlalchemy.security.sqlalchemy-execute-raw-query`. Testes de integração com payloads de SQLi (`'; DROP TABLE --`) nos filtros de squad/period.

**Superficie 4 — XSS via Descriptions Jira**
Risco: o backfill de descriptions processa markup HTML/Wiki do Jira que pode conter `<script>` tags, payloads de event handlers, ou CSS injection. Essas descriptions são potencialmente exibidas no frontend. Controle: sanitizacao obrigatória no worker antes de persistir (DOMPurify no frontend, bleach/nh3 no Python). Testes: payload `<script>alert(1)</script>` em description → assertar que output é texto plain ou HTML sanitizado sem tags executáveis.

**Superficie 5 — SSRF (Server-Side Request Forgery) via Connectors**
Risco: endpoints de admin que aceitam URLs de Jira/Jenkins como input podem ser apontados para metadados de AWS (169.254.169.254), serviços internos, ou localhost. Controle: validação de URL com whitelist de hosts permitidos (só dominios configurados no connections.yaml). SAST Semgrep rule `python.requests.security.ssrf`. Teste: tentar configurar Jira URL como `http://169.254.169.254/` e assertar HTTP 400.

**Superficie 6 — Secrets Management**
Risco: tokens de Jira/Jenkins/GitHub em variáveis de ambiente vazando em logs, respostas de API, ou commits. Controle: Gitleaks em pre-commit hook e CI. Variáveis sensíveis nunca logadas (masked no Python logging). Testes: assertar que nenhuma resposta de API inclui campos como `api_token`, `password`, `secret`. AWS Secrets Manager como destino final (R2+).

**Superficie 7 — Container Security**
Risco: imagens Docker rodando como root, com pacotes vulneráveis, ou com secrets em layers de build. Controle: Trivy image scan em CI (bloqueia HIGH/CRITICAL). Dockerfile com `USER nonroot`. Multi-stage build para minimizar superficie. `.dockerignore` exclui `.env` e `*.pem`. Testes: assertar `whoami != root` via `docker run --entrypoint whoami`.

**Superficie 8 — Supply Chain**
Risco: dependências Python/npm com CVEs conhecidos. Controle: `pip-audit` + `npm audit` em CI (bloqueia HIGH/CRITICAL). Trivy em modo SCA. Dependabot configurado para PRs automáticos de update semanal. SBOM gerado em releases via `cyclonedx-bom`.

**Superficie 9 — Logging PII Masking**
Risco: logs de aplicacao (Uvicorn, SQLAlchemy query log em DEBUG) contendo nomes de usuários, emails, ou assignee names de issues. Controle: filtro de logging customizado que mascara padrões de email e campos conhecidos de PII antes de escrever. Teste: processar issue com assignee `"João Silva <joao@webmotors.com.br>"` e assertar que o log de saida nao contém nem o nome nem o email.

**Superficie 10 — Rate Limiting**
Risco: endpoints de admin (discovery trigger, recalculate) sem proteção contra abuso — um usuario pode triggerar recalculo infinito e saturar o banco. Controle: rate limiting em `/admin/*` (max 10 req/min por IP) e `/data/v1/metrics/recalculate` (max 1 req/min por tenant). Implementado via middleware (SlowAPI ou nginx rate limit). Teste: 20 requests em sequência ao endpoint de recalculo — assertar que os últimos recebem HTTP 429.

**Superficie 11 — Security Headers**
Risco: ausência de headers defensivos permite clickjacking, MIME sniffing, e ataques de informação. Controle: Helmet.js (NestJS), headers manuais (FastAPI) — `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'self'`, `Strict-Transport-Security: max-age=31536000`, `X-Content-Type-Options: nosniff`. Teste via ZAP passive scan e teste unitário de middleware assertando headers em toda resposta.

### 6.2 Alinhamento OWASP

O threat model acima cobre explicitamente as seguintes categorias do **OWASP Top 10 2021**:

| OWASP 2021 | Superficie PULSE coberta |
|------------|--------------------------|
| A01 — Broken Access Control | RLS multi-tenant (#1), Admin authZ (#10) |
| A02 — Cryptographic Failures | Secrets management (#6), HTTPS/HSTS (#11) |
| A03 — Injection | SQL Injection (#3), XSS via Jira (#4) |
| A05 — Security Misconfiguration | Container security (#7), Security headers (#11) |
| A06 — Vulnerable Components | SCA pip-audit/npm-audit (#8) |
| A07 — Identification/Auth Failures | RLS tenant isolation (#1) |
| A08 — Software/Data Integrity | Supply chain SBOM (#8), Gitleaks (#6) |
| A09 — Logging/Monitoring Failures | PII masking (#9) |
| A10 — SSRF | SSRF connectors (#5) |

O alinhamento com **OWASP ASVS Level 2** está contemplado em todas as superficies acima. ASVS L3 (requisito para sistemas críticos de segurança) é out-of-scope para MVP mas deve ser avaliado antes de abrir para multi-tenant público.

### 6.3 Pen Test

Recomendação: **pen-test manual anual** conduzido por terceiro especializado, com foco em multi-tenant isolation e SSRF. Antes do pen-test anual, executar **pen-test interno semestral** usando OWASP ZAP Active Scan em ambiente de staging com dados sintéticos. O primeiro pen-test deve acontecer antes do go-live multi-tenant (Release 2+).

---

## 7. CI/CD Pipeline Integration

### 7.1 Estrutura de Workflows

**Esclarecimento importante sobre Jenkins vs GitHub Actions:**
O arquivo de memória `project_jenkins_cicd.md` documenta que a **Webmotors** (cliente-âncora) usa **Jenkins** para CI/CD das *próprias* aplicações dela (webmotors-next-ui, webmotors-private/*, etc.). Isso é correto e não muda. O **PULSE** (o SaaS que monitora a Webmotors) usa **GitHub Actions** para o *próprio* pipeline de CI/CD — o workflow já existe em `pulse/.github/workflows/ci.yml`. Jenkins é um sistema que o PULSE *monitora* como fonte de dados de deployment; ele não executa o pipeline do PULSE em si.

O PULSE usa **GitHub Actions** para CI/CD. Os stages abaixo são workflows GitHub Actions implementados em `pulse/.github/workflows/`.

**Stage: `ci` (PR build, alvo < 10 minutos)**
- Lint: Ruff + Black (Python), ESLint + Prettier (TypeScript)
- Type-check: mypy (Python strict), tsc --noEmit (TypeScript)
- Unit tests: Pytest unit (backend), Vitest (frontend)
- Anti-surveillance gate: schema inspection automatizada
- SAST: Bandit + Semgrep (Python), ESLint-security (TS)
- Secrets scan: Gitleaks
- SCA: pip-audit + npm audit (bloqueia HIGH/CRITICAL)
- Build: Docker image (sem push)
- Trivy image scan

**Stage: `pr-merge` (apos aprovacao e merge, alvo < 20 minutos)**
- Tudo do `ci` +
- Integration tests: Pytest + Testcontainers (PostgreSQL + Kafka)
- Contract tests: Zod schema validation contra respostas reais
- E2E smoke: 3 jornadas criticas no Playwright (Chromium only)
- A11y: axe-core nas 5 rotas principais
- Push Docker image para registry (tag: `sha-{commit}`)

**Stage: `nightly` (todo dia às 01:00, alvo < 60 minutos)**
- E2E full: todas as 8-10 jornadas, Chromium + Firefox
- Visual regression: screenshot comparison contra baseline
- Perf benchmark BE: pytest-benchmark com dataset grande
- Load test: k6 cenario Webmotors (50 VUs, 10 min)
- DAST: OWASP ZAP Baseline Scan
- Relatório consolidado por email/Slack

**Stage: `weekly` (sexta-feira, alvo < 3 horas)**
- Tudo do nightly +
- Stress test: k6 ramp ate 200 VUs
- Spike test: k6 burst 200 VUs em 10s
- Soak test parcial: 30 VUs por 30 min (soak completo: 2h, executado manualmente ou mensalmente)
- Lighthouse CI Web Vitals report
- SCA audit completo com relatório de CVEs

**Stage: `release` (antes de qualquer tag de versao)**
- E2E completo + visual regression
- Perf baseline capturado e commitado como artefato
- DAST full scan
- Trivy image scan do artefato final
- Soak test completo 2h
- Aprovacao manual obrigatória antes do deploy

### 7.2 Quality Gates por Stage

| Gate | `ci` | `pr-merge` | `nightly` | `release` |
|------|------|------------|-----------|-----------|
| Unit coverage BE ≥ 85% | Bloqueia | Bloqueia | — | Bloqueia |
| Unit coverage FE ≥ 80% | Bloqueia | Bloqueia | — | Bloqueia |
| SAST zero HIGH/CRITICAL | Bloqueia | Bloqueia | — | Bloqueia |
| SCA zero HIGH/CRITICAL | Bloqueia | Bloqueia | — | Bloqueia |
| Secrets: zero findings | Bloqueia | Bloqueia | — | Bloqueia |
| Anti-surveillance gate | Bloqueia | Bloqueia | — | Bloqueia |
| E2E smoke (3 jornadas) | — | Bloqueia | — | Bloqueia |
| A11y zero violations WCAG AA | — | Bloqueia | — | Bloqueia |
| Integration tests | — | Bloqueia | — | Bloqueia |
| Contract tests (Zod) | — | Bloqueia | — | Bloqueia |
| Load SLO P95 < 500ms | — | — | Aviso | Bloqueia |
| E2E full (todas jornadas) | — | — | Aviso | Bloqueia |
| Visual regression delta | — | — | Aviso | Bloqueia |
| DAST zero MEDIUM+ | — | — | Aviso | Bloqueia |

### 7.3 Cache Strategy

- **pip install:** cache do virtualenv por hash do `requirements.txt` (CI cache layer)
- **npm install:** cache do `node_modules` por hash do `package-lock.json`
- **Docker layers:** base images cacheadas; apenas layers da aplicacao sao rebuiltadas
- **Playwright browsers:** cache do diretório `~/.cache/ms-playwright` (pesado: ~600MB)
- **Testcontainers:** images PostgreSQL e Kafka pre-pulled em nodes de CI (evita pull em runtime)

---

## 8. Roadmap de Implementacao (6 Sprints)

> Estimativas: XS = 1-2h, S = 3-5h, M = 6-12h, L = 13-20h, XL = 20h+

### Sprint 1 — Foundation (estimativa total: ~50h)

**Objetivo:** infraestrutura de testes + 6 testes retroativos dos bugs escapados.

| Tarefa | Tamanho | Owner | Dependencia |
|--------|---------|-------|-------------|
| Setup Vitest RTL + MSW no pulse-web | S | pulse-test-engineer | Nenhuma |
| Setup Playwright com fixtures de seed | M | pulse-test-engineer | Docker rodando |
| Setup Zod contract test harness | S | pulse-test-engineer | Nenhuma |
| Anti-surveillance gate (schema inspection Pytest + Vitest) | M | pulse-test-engineer | Nenhuma |
| Retroativo INC-001: throughput 60d≠90d≠120d (integration) | M | pulse-test-engineer | Testcontainers Postgres |
| Retroativo INC-002: snapshot drift apos restart (integration) | M | pulse-test-engineer | Testcontainers |
| Retroativo INC-003: cycle time P50 > 1h quando PRs levam dias | S | pulse-test-engineer | Nenhuma (unit) |
| Retroativo INC-FONTES: split_part repo retorna NULL (integration) | S | pulse-test-engineer | Testcontainers Postgres |
| Retroativo INC-422: squad UUID regex valida UUIDs corretos | S | pulse-test-engineer | Nenhuma (unit) |
| Retroativo INC-backfill: description backfill processa > 100 | S | pulse-test-engineer | Testcontainers |
| Gitleaks pre-commit hook | XS | pulse-ciso | Nenhuma |
| Bandit + pip-audit no stage ci | XS | pulse-ciso | Nenhuma |

### Sprint 2 — Frontend Coverage 80% (estimativa total: ~60h)

**Objetivo:** component tests, hook tests com MSW, atingir 80% coverage FE.

| Tarefa | Tamanho | Owner | Dependencia |
|--------|---------|-------|-------------|
| Component tests: MetricCard (6 estados) | M | pulse-test-engineer | Sprint 1 setup |
| Component tests: FilterBar (squad + period selectors) | M | pulse-test-engineer | Sprint 1 setup |
| Component tests: TrendChart, ClassificationBadge | M | pulse-test-engineer | Sprint 1 setup |
| Component tests: Pipeline StepRow, TeamHealthBadge | M | pulse-test-engineer | Sprint 1 setup |
| Component tests: Jira ModeSelector, DiscoveryStatus | S | pulse-test-engineer | Sprint 1 setup |
| Hook tests: useMetrics (loading/error/success/stale) | L | pulse-test-engineer | MSW handlers |
| Hook tests: useGlobalFilters (squad change → refetch) | M | pulse-test-engineer | MSW handlers |
| Hook tests: useCapabilities (sprint/kanban flags) | S | pulse-test-engineer | MSW handlers |
| A11y: axe-core em todas as rotas (CI integration) | M | pulse-test-engineer | Playwright |
| Expand Vitest utilities coverage para 80%+ | S | pulse-test-engineer | Sprint 1 setup |

### Sprint 3 — E2E Happy Paths + Visual Regression (estimativa total: ~55h)

**Objetivo:** 8-10 jornadas criticas Playwright + baseline de screenshots.

| Jornada E2E | Tamanho | Prioridade |
|-------------|---------|------------|
| J1: Home → ver 6 MetricCards com data → navegar para DORA | M | P0 |
| J2: DORA drill-down → badges de classificacao → trend charts | M | P0 |
| J3: Filtro squad → cards atualizam → mudar periodo → graficos atualizam | L | P0 |
| J4: Lean CFD → tooltip → Scatterplot → linhas de percentil | M | P0 |
| J5: Pipeline Monitor → step breakdown → team health → source badge nao FONTES zerado | M | P0 |
| J6: PR list → ordenar por age → badges de cor → paginacao | M | P1 |
| J7: Cycle Time breakdown → bottleneck phase highlighted | S | P1 |
| J8: Jira Settings → trigger discovery → status badge atualiza | M | P1 |
| Visual regression baseline: Home, DORA, Pipeline, Lean CFD | M | P1 |

### Sprint 4 — Performance Baseline (estimativa total: ~40h)

**Objetivo:** k6 load tests + pytest-benchmark + Web Vitals.

| Tarefa | Tamanho | Owner |
|--------|---------|-------|
| k6 script: smoke (5 VUs, 1 min) | S | pulse-test-engineer |
| k6 script: load (50 VUs, 10 min, todos endpoints) | M | pulse-test-engineer |
| k6 script: stress (ramp 200 VUs) | M | pulse-test-engineer |
| k6 script: spike (200 VUs em 10s) | S | pulse-test-engineer |
| k6 script: soak (30 VUs, 2h) | S | pulse-test-engineer |
| pytest-benchmark: funções domain com large_volume fixture | M | pulse-test-engineer |
| Lighthouse CI Web Vitals no Playwright | M | pulse-test-engineer |
| Integrar k6 no nightly CI stage | S | pulse-test-engineer |
| Definir e documentar SLO baseline (valores medidos) | S | pulse-test-engineer |

### Sprint 5 — Security Hardening (estimativa total: ~45h)

**Objetivo:** SAST full, container scanning, DAST baseline, pen-test prep.

| Tarefa | Tamanho | Owner |
|--------|---------|-------|
| Semgrep rules customizadas (SSRF, SQL injection patterns PULSE) | M | pulse-ciso |
| ESLint-plugin-security configurado no pulse-web | S | pulse-ciso |
| Trivy image scan integrado no CI com threshold | S | pulse-ciso |
| Testes de integracao de segurança: RLS isolation (2 tenants) | L | pulse-test-engineer |
| Testes de integracao: SSRF em endpoints de configuracao | M | pulse-test-engineer |
| Testes de integracao: SQLi payloads em filtros | M | pulse-test-engineer |
| Testes de integracao: XSS via Jira description → sanitizacao | M | pulse-test-engineer |
| OWASP ZAP Baseline Scan no nightly | M | pulse-ciso |
| Logging PII masking test | S | pulse-test-engineer |
| Rate limiting test (429 apos threshold) | S | pulse-test-engineer |
| Security headers test (middleware assertion) | S | pulse-test-engineer |

### Sprint 6 — Stress, Soak & DAST Automation (estimativa total: ~50h)

**Objetivo:** testes de carga extremos, DAST automatizado, pen-test preparatorio.

| Tarefa | Tamanho | Owner |
|--------|---------|-------|
| Soak test completo 2h integrado no weekly CI | M | pulse-test-engineer |
| Capacity benchmark: max tenants simultâneos | L | pulse-test-engineer |
| DAST ZAP Active Scan (staging) — curadoria de regras | L | pulse-ciso |
| Pen-test externo: escopo, RFP, briefing | M | pulse-ciso (coordenacao) |
| Mutation testing: mutmut/pytest-mutagen em domain functions | L | pulse-test-engineer |
| Dashboard de qualidade (Grafana): coverage, flakiness, perf trends | M | pulse-engineer |
| Retrospectiva da estrategia e revisao dos targets de coverage | S | pulse-test-engineer |

---

## 9. Metricas de Qualidade (Dashboards)

As seguintes metricas sao capturadas automaticamente em CI e expostas em Grafana (ou equivalente):

### 9.1 Coverage

| Metrica | Target | Frequencia de medicao |
|---------|--------|-----------------------|
| BE unit coverage (%) | ≥ 85% | Cada PR |
| FE unit + component coverage (%) | ≥ 80% | Cada PR |
| Integration test coverage (linhas de rota cobertas) | ≥ 70% | Cada merge |
| E2E jornadas passando (de N) | 100% smoke, 90% full | Nightly |

### 9.2 Velocidade de Feedback

| Metrica | Target |
|---------|--------|
| Tempo total stage `ci` | < 10 min |
| Tempo total stage `pr-merge` | < 20 min |
| Tempo total stage `nightly` | < 60 min |
| Tempo total stage `release` | < 3h |

### 9.3 Qualidade de Testes

| Metrica | Target |
|---------|--------|
| Flakiness rate (14 dias) | < 1% |
| Bugs escapados para producao por mes | ≤ 1 |
| Tempo médio de deteccao (MTTD) | < 1 dia |
| Testes em quarentena (@flaky) | ≤ 3 simultaneos |

### 9.4 Segurança

| Metrica | Target |
|---------|--------|
| SAST HIGH/CRITICAL abertos | 0 |
| SCA HIGH/CRITICAL abertos | 0 |
| DAST MEDIUM+ abertos sem mitigacao | 0 |
| Dias medios para fechar finding CRITICAL | < 1 dia |
| Dias medios para fechar finding HIGH | < 7 dias |
| Dias medios para fechar finding MEDIUM | < 30 dias |

### 9.5 Performance Trends

SLO compliance rate (% de medicoes nightly dentro do SLO) registrado em serie temporal. Alertas se < 95% em qualquer endpoint em janela de 7 dias.

---

## 10. Riscos, Dependencias e Gaps

### 10.1 Test Data sem PII

**Risco alto.** O cenario Webmotors tem 374k issues com assignees reais e 57k PRs com nomes de desenvolvedores reais. Testes de integracao que precisam de dados realistas (ex: throughput de 27 squads) precisam de fixtures sinteticas geradas de forma deterministica — nunca um dump de producao. Decisao necessaria: quem gera e mantem o conjunto de fixtures grandes (large_volume)? Estimativa: 2 dias de trabalho inicial para criar o gerador de fixtures, 1h/sprint para manter.

### 10.2 Ambiente de Staging

**Risco medio.** DAST ativo, soak test, e pen-test externo precisam de um ambiente isolado com dados sinteticos. O PULSE atualmente nao tem staging documentado. Decisao necessaria: provisionar staging? Custo: instância RDS small (~USD 50/mes). Alternativa sem staging: executar DAST contra localhost em Docker Compose isolado (limitacao: sem TLS real, sem balanceamento).

### 10.3 Tooling Cost

| Ferramenta | Custo | Alternativa Free |
|------------|-------|------------------|
| Playwright | Free (OSS) | — |
| k6 OSS | Free | Artillery (alternativa) |
| Grafana Cloud (metrics CI) | Free tier (10k series) | Prometheus + Grafana self-hosted |
| Chromatic (visual regression) | Pago (~USD 149/mes) | Playwright screenshots (built-in, menos sofisticado) |
| Percy (visual regression) | Pago (~USD 399/mes) | Playwright screenshots |
| BackstopJS | Free (OSS) | Alternativa a Chromatic |
| Semgrep Pro | Pago | Semgrep OSS (menos regras) |
| OWASP ZAP | Free (OSS) | — |
| Gitleaks | Free (OSS) | — |
| Trivy | Free (OSS) | — |

**Recomendacao:** usar Playwright screenshots built-in para visual regression (free), BackstopJS se precisar de UI dedicada. Evitar Chromatic/Percy por ora — custo nao justificado para equipe pequena.

### 10.4 Skill Gaps

- **Pen-test:** nenhum membro da equipe com certificacao OSCP ou equivalente. Recomendacao: pen-test anual terceirizado (USD 5-15k por engajamento). Internamente: usar OWASP ZAP + checklist ASVS L2 como substituto parcial.
- **k6 avancado:** scripts de spike e soak requerem familiaridade com k6 executors (ramping-arrival-rate). Estimativa: 4h de onboarding por engenheiro.
- **Testcontainers Kafka:** setup mais complexo que PostgreSQL. Estimativa adicional: 1 dia para primeira integracao funcionando.

### 10.5 Realismo do Roadmap

O roadmap completo de 6 sprints assume ~300h de esforco total distribuido entre pulse-test-engineer (principal) e contribuicoes de pulse-engineer e pulse-ciso. Se a equipe for menor ou o teste nao for prioridade full-time, a versao "skinny" a seguir entrega o maximo de valor em 3 sprints:

**Versao Skinny (3 sprints, ~150h):**
- Sprint 1: Quick wins retroativos + anti-surveillance gate + Playwright setup + Zod contracts
- Sprint 2: Component/hook tests FE + E2E smoke (3 jornadas) + A11y
- Sprint 3: Load test (k6 load scenario) + SAST + Trivy + Gitleaks

Isso nao cobre stress/soak/DAST/visual regression, mas elimina os vetores de bug mais comuns e cria a fundacao para os sprints 4-6 posteriores.

---

## 11. Anti-patterns a Evitar

**1. Testes dependentes de ordem de execucao.** Cada teste deve ser capaz de rodar isoladamente com `pytest test_foo.py::TestBar::test_specific` sem setup externo. Pytest-randomly detecta dependencias de ordem.

**2. `time.sleep()` em qualquer camada.** Proibido absolutamente. Causa flakiness e torna o feedback mais lento. Substituto: `asyncio.wait_for()`, `wait_until()` do Playwright, ou polling com backoff.

**3. Mock em excesso no backend.** Mockar o repositório inteiro apenas para testar uma route handler destrói o valor do teste — nada é validado de fato. Preferir Testcontainers para testes de integração. Mockar apenas clientes externos reais (Jira API, Jenkins API).

**4. Snapshot massivo sem revisao.** Snapshots Vitest/Jest sao uteis para outputs pequenos e bem definidos. Nao usar snapshots para objetos grandes (ex: snapshot do payload inteiro de `/metrics/home` com 50 campos) — sao difíceis de revisar e aceitam regressoes silenciosamente.

**5. E2E cobrindo logica de negocio.** E2E testa jornadas de usuario, nao algoritmos. Se um teste E2E verifica que `deploy_frequency_per_day == 7.13`, ele esta no lugar errado — isso e responsabilidade do unit test de dominio.

**6. Compartilhar banco entre testes de integracao.** Cada test session tem seu proprio Testcontainer. Nunca apontar testes para um banco compartilhado (staging, dev) — os dados mudam e os testes se tornam nao-determinísticos.

**7. `waitForTimeout()` no Playwright.** Proibido. Equivalente ao `sleep()`. Usar `waitForSelector()`, `waitForResponse()`, ou `waitForLoadState('networkidle')` com timeout maximo explicito.

**8. Ignorar testes falhos em vez de corrigir.** Nenhum teste pode ser marcado `@pytest.mark.skip` sem issue associado e data limite de resolucao. `xfail` e aceitavel para bugs conhecidos documentados, nunca como atalho.

**9. Testar o mock em vez da logica.** Ex: `assert mock_repository.get.called == True` — nao testa nada do comportamento real. Usar mocks apenas para assertar efeitos colaterais externos (ex: Kafka producer foi chamado com o payload correto).

**10. Gigantic test files.** Arquivo de teste com 1000+ linhas e um sinal de que os testes nao estao bem organizados. Separar por contexto (ex: `test_dora_deploy_frequency.py`, `test_dora_lead_time.py`) melhora legibilidade e localiza falhas mais rapidamente.

**11. Coverage como unica metrica de qualidade.** 85% de coverage pode mascarar testes que nao assertam nada significativo. Coverage e necessario mas nao suficiente. Usar mutation testing (mutmut) no Sprint 6 para validar a qualidade dos asserts.

**12. Testes de segurança apenas manuais.** Qualquer check de segurança que so existe como checklist manual vai ser pulado sob pressao de prazo. SAST, SCA, Gitleaks e anti-surveillance gate devem bloquear o PR automaticamente.

---

## 12. Top-5 Quick Wins

Os 5 testes que, se implementados hoje, teriam capturado os bugs ja escapados:

**QW-1 — Throughput difere por período (INC-001/002)**
Testa que `GET /metrics/throughput?period=60d` retorna resultado numericamente diferente de `?period=90d` e `?period=120d`. Ground truth: 5044, 7341, 9007 respectivamente. Ferramenta: Pytest + Testcontainers (banco com dados de 120 dias). Estimativa: 4h.

**QW-2 — Squad UUID regex nao rejeita UUIDs validos (INC-422)**
Testa que `GET /metrics/home?squad_id={valid_uuid}` retorna HTTP 200, nao 422. Testa tambem que valores invalidos retornam 422. Ferramenta: Pytest (unit, sem banco). Estimativa: 1h.

**QW-3 — Pipeline FONTES nao retorna NULL (INC-FONTES)**
Testa que `GET /pipeline/health` retorna objeto em que o campo `sources` de cada repositório nunca e `null` nem string vazia quando o repositório tem ingestao configurada. Ferramenta: Pytest + Testcontainers (PostgreSQL com fixture de pipelines configurados). Estimativa: 3h.

**QW-4 — Cycle Time P50 realista (INC-003)**
Testa que quando PRs têm `first_commit_at` = `created_at` (proxy), o sistema documenta isso como limitacao conhecida E o P50 nao pode ser absurdamente baixo (< 5 minutos) para PRs que levam dias entre criacao e merge. Adicionalmente, o gateway de integracao deve rejeitar PRs com cycle_time_hours < 0. Ferramenta: Pytest (unit domain). Estimativa: 2h.

**QW-5 — Anti-surveillance gate automatico**
Inspeciona todos os schemas Pydantic (`from src.contexts.metrics.schemas import *`) e verifica que nenhum campo nos modelos de resposta contem os nomes proibidos: `assignee`, `author`, `author_name`, `developer`, `committer`. Ferramenta: Pytest (meta-test de schemas, zero dependencias de infraestrutura). Estimativa: 2h.

**Total Quick Wins: ~12h de implementacao. Valor: elimina os 5 categorias de bug mais frequentes ate hoje.**

---

## 13. Proximo Passo Proposto

Apos aprovacao desta estrategia, a sequencia recomendada e:

**Semana 1 (imediato, mesmo antes de Sprint 1 formal):**
Implementar os 5 Quick Wins acima. Eles nao requerem nenhuma infraestrutura nova alem do que ja existe (Pytest + Testcontainers ja configurado). Estimativa: 12h. Resultado: os bugs INC-001, INC-002, INC-003, INC-422 e INC-FONTES passam a ter cobertura automatica permanente.

**Sprint 1 formal:**
Setup de Playwright (instalacao, fixtures de seed, configuracao multi-browser) e Vitest RTL + MSW no pulse-web. Anti-surveillance gate Zod no frontend. Gitleaks + Bandit no CI. Estas sao as fundacoes sem as quais os sprints 2-6 nao conseguem executar.

**Decisao humana necessaria antes do Sprint 2:**
Confirmar a abordagem de visual regression: Playwright screenshots built-in (free, menos ergonomico) vs BackstopJS (free OSS, mais configuracao) vs Chromatic/Percy (pago). A resposta afeta o planejamento de Sprint 3.

**Decisao humana necessaria antes do Sprint 5:**
Confirmar se ha ambiente de staging disponivel para DAST ativo e pen-test. Sem staging, o DAST ativo precisara rodar em Docker Compose isolado com limitacoes (sem TLS real).

---

*Documento criado por `pulse-test-engineer`. Versao inicial para aprovacao do time.*
