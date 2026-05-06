# Ops & Infrastructure Backlog

Feature-Driven Development cards for operational/infrastructure debt that
affects developer velocity, deployment reliability, and production
observability. Ordered by impact × frequency.

---

## FDD-OPS-001 · Eliminar drift "código deployado × runtime em execução" nos workers Python

**Epic:** Operational Reliability · **Release:** R1 (antes de onboarding SaaS)
**Priority:** **P0** · **Persona:** Toda a equipe de engenharia (dev velocity)
**Owner class:** `pulse-engineer` + `pulse-data-engineer`

### Problema (pain confirmada em 3 incidentes)

Cada vez que mudamos código de domain/service Python e fazemos commit, os
**workers Python continuam rodando o código antigo em memória** até alguém
lembrar de fazer `docker compose restart` explicitamente. Resultado:
snapshots gravados com lógica obsoleta, bugs visíveis em produção local, e
depuração dolorosa ("o código está certo, por que o dado está errado?").

### Histórico de incidentes conhecidos

| Data | Sintoma | Causa raiz | Tempo perdido |
|---|---|---|---|
| 2026-04-16 | INC-001/002: Throughput igual em 30d/60d/90d/120d | `metrics-worker` em memória usava `_PERIODS=[7,14,30,90]` e fetch por `created_at`; commit já tinha corrigido | ~30min debug + restart |
| 2026-04-17 | Métricas com 0 valor após fixes de INC-003/004 | Recalc rodou com código velho; precisou restart + recalc explícito | ~15min |
| 2026-04-18 | Card "Lead Time" sumiu após split strict/inclusive | Worker escreveu snapshot tenant-wide sem os campos `lead_time_for_changes_hours_strict`/`eligible`/`total` | ~20min |

**Padrão comum**: usuário ou dev percebe discrepância visual → investigação
revela snapshot no banco com campos faltantes → restart worker + recalc →
resolve. Sempre reativo, nunca preventivo.

### Impacto

- **Dev velocity**: a cada commit de domain/service, 5-15 minutos perdidos em
  restart + recalc manual
- **Confiança nos dados**: usuários veem números inconsistentes e perdem fé
- **Onboarding SaaS (roadmap R1)**: em ambiente multi-tenant, drift
  código→runtime vira incidente de cliente, não só pain interna
- **CI/CD futuro**: não podemos fazer deploy contínuo com esse gap — cada
  rollout silenciosamente mantém lógica antiga até restart

### Solução — 4 linhas de defesa complementares

**Linha 1 — Hot-reload em dev (P0, XS)**

Workers Python em desenvolvimento devem auto-reload em mudança de arquivo,
igual ao `uvicorn --reload` do `pulse-data`. Implementar via:
- `watchdog` + `importlib.reload` no `base_worker.py`
- OU `python-devtools` com `--reload` flag
- OU `docker compose watch` (nativo) configurado pra metrics-worker e
  sync-worker

**Linha 2 — Admin recalc force-reload (P0, XS)**

Endpoint `/admin/metrics/recalculate` já existente deve chamar
`importlib.reload()` nos módulos de domain/service antes de executar. Garantia
idempotente: mesmo se o worker em background estiver com código velho, o
recalc manual sempre usa código atualizado.

**Linha 3 — Snapshot contract monitor (SHIPPED 2026-04-23)**

Pós-write, valida que o snapshot tem todos os campos do **domain dataclass**
mais recente (fonte da verdade do payload persistido, não do Pydantic
de resposta). Campo faltando → log WARN estruturado com tag
`FDD-OPS-001/L3` + contador Prometheus `pulse_snapshot_schema_drift_total
{metric_type, metric_name}` (no-op se `prometheus_client` ausente) + anota
`_schema_drift` no JSONB do snapshot. Pipeline Monitor consome via
`GET /data/v1/pipeline/schema-drift?hours=N` (≤168h), agrupado por
`(metric_type, metric_name, missing_fields)`. Registrados na v1:
`dora/all`, `cycle_time/breakdown`, `lean/lead_time_distribution`,
`throughput/pr_analytics` (os quatro payloads que fazem `asdict(dataclass)`
direto — wrappers `{"points": [...]}` não são validados). 20 testes
unitários cobrem o registry e a detecção.

**Linha 4 — CI/CD force-restart on deploy (SHIPPED 2026-04-23 — TEMPLATE)**

Novo workflow `pulse/.github/workflows/deploy.yml` (gatilho
`workflow_dispatch` com input `environment`). Após build/rollout, força
restart dos 4 workers Python (`pulse-data metrics-worker sync-worker
discovery-worker`), espera ficarem healthy, roda um dry-run de recalc
(Linha 2 força reload de módulos), e consulta `/pipeline/schema-drift`
(Linha 3) pós-deploy. `concurrency.cancel-in-progress=false` para nunca
derrubar rollout em curso. Passos `Build/push` e `Roll out` estão como
`# TODO:` porque deploy hoje é manual no Webmotors — quando automatizarmos,
é trocar comandos docker pelo `kubectl`/`aws ecs` equivalentes.
`actionlint` passa limpo.

### Acceptance Criteria (BDD)

```
Given a developer commits a change in pulse-data/src/contexts/metrics/domain/*.py
 When docker compose watch is running in dev
 Then metrics-worker auto-reloads within 5 seconds
  And next event processed uses the new code
  And no manual restart is required

Given a snapshot is written with a schema missing required fields
 When the snapshot_schema_drift monitor runs
 Then a WARN log is emitted with metric_type and missing_field
  And a Prometheus counter increments
  And Pipeline Monitor shows an amber banner "Snapshot stale — restart worker"

Given a CI/CD pipeline deploys new Python code
 When the deploy step runs
 Then docker compose restart {metrics-worker, sync-worker, discovery-worker}
      is executed automatically
  And the pipeline waits for workers to report healthy before marking
      the deploy successful

Given a user triggers POST /admin/metrics/recalculate
 When the endpoint starts
 Then importlib.reload is called on domain and service modules
  And the recalc uses the freshest code on disk regardless of worker state
```

**Anti-surveillance check:** PASS — mudança de infraestrutura, sem impacto em
dados.
**Dependencies:** nenhuma — pure tooling
**Estimate:** **M total** (Linha 1: XS 1h, Linha 2: XS 1h, Linha 3: S 3h,
Linha 4: S 2h). Pode ser entregue em 4 PRs separados ou 1 big PR.
**Analytics events:** N/A (ops metric)

### Riscos de não fazer

- SaaS multi-tenant (R1) vai expor isso como incidente de cliente, não pain
  interna
- Cada novo colaborador vai pisar nessa mina até aprender o truque manual
- Testes E2E (FDD-DSH-070) não detectam esse gap porque CI roda workers
  do zero — só fica visível em longo runtime
- Confiança em métricas erode: "será que o número está certo ou o worker
  está velho?"

### Ordem de entrega sugerida

1. **Linha 2 primeiro** (admin recalc force-reload) — XS, não requer mudança
   de infra, mitiga 80% dos casos porque todo fix grande envolve recalc
   manual de qualquer jeito
2. **Linha 1** (hot-reload dev) — XS, melhora dev velocity imediatamente
3. **Linha 4** (CI/CD restart) — S, necessário antes de qualquer rollout
   automatizado
4. **Linha 3** (contract monitor) — S, defense-in-depth para casos onde
   as 3 primeiras falham

---

## FDD-OPS-002 · Completar backfill histórico de descriptions Jira ✅ DONE 2026-04-23

**Epic:** Data Quality · **Release:** Shipped
**Priority:** P2 · **Persona:** Operacional (Lucas — Data Platform)
**Owner class:** `pulse-data-engineer` (executado via curl admin)

### Resultado final (execução de 2026-04-23)

Rodamos `scope=all` via endpoint admin existente:

```bash
POST /data/v1/admin/issues/refresh-descriptions?scope=all
```

Resultado:
- **260.088 issues processadas** em 43min39s
- **72.102 issues atualizadas** com descrição nova
- **187.986 unchanged** (já tinham description OU vazias no Jira)
- 1 erro transient (search project=BG page=780, Server disconnected)
- Throughput observado: **5.960 issues/min**
- Recalc automático de todas as métricas (81 snapshots em 5,7s)

**Cobertura final**: **231.694 / 375.297** issues com description (**61,74%**)

### Histórico de execuções (contexto)

Em 2026-04-20 reescrevemos `backfill_descriptions.py` pra usar bulk JQL
(100 issues/request) ganhando 65× em throughput (7.300 issues/min vs
113 issues/min da versão REST per-issue). Três primeiras runs:

- `scope='in_progress'`: 2.230 issues processadas, 1.028 atualizadas
- `scope='stale'` (description is EMPTY no Jira): 74.260 processadas, 0
  atualizadas (esperado — tickets genuinamente vazios no Jira)
- `scope='last-180d'`: 171.125 processadas, 390 atualizadas
- `scope='all'` (2026-04-23): 260.088 processadas, 72.102 atualizadas ← fechamento

**Cobertura anterior**: 163.223 / 374.688 (43,56%)
**Cobertura final**: 231.694 / 375.297 (61,74%)

### Teto realista alcançado

Os ~38% restantes (143k issues) são tickets que **não têm description
no próprio Jira** — sub-tasks, automação (release tickets), tickets
antigos minimais, bots. Não há o que popular; o backfill não pode
melhorar isso. A cobertura-teto estimada em 70% foi corretamente
projetada; ficamos em 61,74% porque: (a) tickets Jira reais da
Webmotors têm descrições ausentes em proporção maior que o sample
inicial de 60d sugeria, (b) projeto BG teve 1 página perdida no
transient.

Se quiser ir além, requer **processo de ticket-hygiene** na Webmotors
(template Jira obrigatório de description), não código PULSE.

### O que falta

~211.465 issues ainda não processadas — majoritariamente tickets com
`updated_at` anterior a 180 dias. Esperamos que ~60% delas tenham
description populável no Jira (mesma proporção observada no sample), ou
seja, ganho potencial de +125k issues chegando a ~75% de cobertura
total.

### Por que NÃO é urgente

Na UI do Flow Health (drawer de squad), itens mostrados são os **em
progresso** (normalized_status='in_progress' OR 'in_review'). Esses
já têm cobertura de 49,65%. Tickets Done/Fechados antigos não
aparecem na UI, então a cobertura histórica é nice-to-have.

### Como rodar quando quiser

```bash
TOKEN=$(grep INTERNAL_API_TOKEN pulse/.env | cut -d= -f2-)

# Opção A: rápido (~30 min, full scope)
curl -X POST -H "X-Admin-Token: $TOKEN" \
  "http://localhost:8000/data/v1/admin/issues/refresh-descriptions?scope=all"

# Opção B: conservador (meio-termo, ~20 min)
curl -X POST -H "X-Admin-Token: $TOKEN" \
  "http://localhost:8000/data/v1/admin/issues/refresh-descriptions?scope=last-365d"
```

### Acceptance Criteria

```
Given the admin runs scope='all' on a pulse-data instance with Jira
  connectivity
 When the endpoint completes
 Then description coverage for eng_issues (source='jira') is ≥ 70%
  AND the remaining issues are verified as `description is EMPTY`
      in Jira itself (not a bug — genuine empty tickets)
  AND the run completes in under 45 minutes at current Webmotors scale
      (~374k issues total)
```

### Estimate
**XS (0 hours coding)** — endpoint existe e funciona. Só rodar curl e
aguardar. Se quiser automatizar via cron semanal, S (~2h).

### Dependências
Nenhuma — endpoint já está LIVE desde testing-foundation-v1.0.

### Riscos

- Nenhum. Backfill é idempotente, READ-ONLY em Jira, UPSERT no PULSE.
- Pode coexistir com sync normal sem conflito.
- Rate limit: 10 req/s soft cap respeitado via pacing interno.

### Notas de produto

Issues genuinamente sem description no Jira (~74k hoje confirmadas)
**nunca serão populadas** por esse backfill — a descrição não existe
no source. Se quiser aumentar essa cobertura, é conversa com
processo de ticket/compliance na Webmotors, não infra PULSE.

---

## FDD-OPS-003 · A11y design-system contrast review (rule `color-contrast`)

**Epic:** Accessibility · **Release:** R1
**Priority:** **P1** · **Persona:** Todos os usuários (WCAG AA é compromisso)
**Owner class:** `pulse-frontend` + `pulse-ux-reviewer`

### Problema

A gate de a11y (Sprint 1.2 passo 4) detectou **172 nós** violando `color-contrast`
na home do dashboard quando rodada contra WCAG 2.1 AA. Os nós atingidos envolvem
tokens do design system (ex. `.text-brand-primary`), radio buttons do period
selector e outros componentes recorrentes — ou seja, é um problema sistêmico
do design system, não de uma página específica.

Por isso a regra `color-contrast` está **temporariamente desabilitada** em
`tests/e2e/a11y/_helpers.ts` / specs. Todas as outras regras WCAG AA continuam
ativas e bloqueando merge. Fixar manualmente 172 nós sem uma passada de design
review é contraprodutivo.

### Solução

1. **Audit dos tokens de contraste** do design system (tokens.css) — especialmente:
   - `text-brand-primary` sobre `surface-primary` / `surface-secondary`
   - `text-content-tertiary` sobre todos os surfaces
   - Estados `hover`/`selected` em controles (period selector, botões fantasma)
2. **Ajustar tokens** para atingir ≥4.5:1 (texto normal) ou ≥3:1 (texto grande / UI).
3. Re-habilitar a regra `color-contrast` removendo o `disableRules(['color-contrast'])`
   dos specs em `tests/e2e/a11y/`.
4. Rodar `npm run test:a11y` — deve passar em 0 críticos + 0 serious.

### Acceptance Criteria

```
Given the a11y gate runs against /, /metrics/dora, /metrics/cycle-time
 When the color-contrast rule is re-enabled
 Then zero violations of severity critical or serious are reported
  And all tokens in tokens.css meet WCAG 2.1 AA contrast ratios
```

**Estimate:** M (4-6h — audit + token adjustments + visual QA).
**Dependencies:** nenhuma.
**Riscos de não fazer:** usuários com baixa visão não conseguem ler KPIs e
labels; bloqueia posicionamento "acessível por padrão" no mercado.

---

## FDD-OPS-004 · Backend-in-CI + smoke E2E como gate bloqueante

**Epic:** Quality / DX · **Release:** R1 (antes de qualquer merge sério em main)
**Priority:** **P0** · **Persona:** Toda a equipe (regression safety net)
**Owner class:** `pulse-test-engineer` + `pulse-engineer`
**Trigger:** Incidente de 2026-04-24 — dashboard caiu por 50× perf regression
no `/metrics/home`. O smoke E2E que existe (`tests/e2e/platform/home-dashboard-smoke.spec.ts`)
teria pego, mas hoje só roda via `workflow_dispatch` ou cron noturno
(arquivo `.github/workflows/e2e-a11y.yml`), nunca como gate de PR.

### Problema

Hoje o `ci.yml` no root cobre só lint + unit + secrets + build. O smoke
E2E + a11y suite estão num workflow separado que tem este aviso explícito
no início:

```yaml
# E2E + a11y specs need a live backend (docker compose) and are heavier
# to run, so they're NOT wired as blocking PR gates yet — promote to
# ci.yml once the backend-in-CI infrastructure is ready
```

A consequência: bugs que só aparecem em runtime real (queries lentas,
endpoint quebrado, frontend pegando timeout) **passam o CI e quebram
local depois**. Foi exatamente o que aconteceu hoje.

### Solução

Adicionar um job `e2e-smoke` ao `.github/workflows/ci.yml` que:

1. Sobe o stack docker-compose dentro do runner GitHub Actions
2. Aguarda postgres + pulse-api + pulse-data healthy (wait-for-it ou
   `docker compose up --wait` com timeout)
3. Roda migrations (Alembic + TypeORM)
4. Executa um seed mínimo (subset do `seed_dev.py` do PR #2 — ~50 PRs
   suficientes pra renderizar dashboard sem skeletons)
5. Inicia o pulse-web (Vite preview do build)
6. Roda `npx playwright test tests/e2e/platform tests/e2e/a11y --project=chromium`
7. Se qualquer teste falhar → bloqueia merge

Branch protection é atualizado pra incluir o novo check como required.

### Acceptance Criteria (BDD)

```
Given a PR is opened against main or develop
 When the CI workflow runs
 Then a job named "E2E smoke + a11y" starts
  And it provisions a backend stack inside the runner
  And it executes the home smoke spec + 10 a11y specs against real services
  And merge is blocked if any of these fail
  And the job completes in under 8 minutes (warm cache)

Given an a11y or smoke regression is introduced
 When the PR runs CI
 Then the job fails with a clear actionable message
  And Playwright HTML report is uploaded as artifact
  And screenshots/traces are attached for failed tests
```

**Anti-surveillance check:** PASS — gate de qualidade, sem dados de
usuário.
**Dependencies:** PR #2 (`seed_dev.py` precisa de modo "minimal seed"
< 30s) ou seed inline próprio.
**Estimate:** M (4-6h — workflow yaml + seed minimal + cache de imagens
docker no runner + tuning).
**Risco de não fazer:** todo bug emergente em runtime (perf, integração,
config) continua passando despercebido até alguém abrir o app local.

---

## FDD-OPS-005 · `make migrate` quebrado (typeorm/dist) bloqueia onboarding

**Epic:** DX · **Release:** R1
**Priority:** **P2** · **Persona:** Dev novo + dev rotacionado entre projetos
**Owner class:** `pulse-engineer`
**Trigger:** Tentativa de aplicar migration 009 (partial index) hoje —
`make migrate` falhou antes de chegar no Alembic.

### Problema

```
$ make migrate
Error during migration run:
Error: Unable to open file: "/app/dist/common/database/typeorm.config.js".
Cannot find module '/app/dist/common/database/typeorm.config.js'
```

`make migrate` corre TypeORM (pulse-api) primeiro, depois Alembic
(pulse-data). O TypeORM precisa de `dist/` (build de produção), mas o
container roda em modo dev (sem build). Resultado: target oficial de
migration é não-funcional.

Hoje, migrations rodam via `compose exec pulse-data alembic upgrade head`
manualmente OU via boot script do container. Funciona, mas não é o que
o `Makefile help` documenta. Dev novo seguindo as docs vai bater nesse
erro logo no `make setup`.

### Solução

Duas opções (decidir com `pulse-engineer`):

**Opção A** — `make migrate` invoca via boot do container:
```make
migrate:
    $(COMPOSE) exec pulse-api npm run migration:run -- --transaction each
    $(COMPOSE) exec -w /app pulse-data sh -c 'cd /app && python -m alembic -c alembic/alembic.ini upgrade head'
```
+ ajustar paths/imports do alembic env.py pra funcionar com `python -m`.

**Opção B** — adicionar `npm run build` (apenas typeorm config) ao
Dockerfile do pulse-api OU criar imagem dedicada `pulse-api-migrator`
que tem o dist/ buildado.

### Acceptance Criteria

```
Given a fresh clone with `make setup` completed
 When `make migrate` is invoked
 Then both TypeORM and Alembic migrations apply successfully
  And exit code is 0
  And `make verify-dev` continues to pass
```

**Estimate:** S (2-3h investigation + fix).
**Dependencies:** nenhuma.
**Riscos de não fazer:** dev novo bate no erro no primeiro `make setup`,
perde 30-60min debugging algo que não é problema dele.

---

## FDD-OPS-006 · Performance budget assertions no smoke E2E

**Epic:** Quality / DX · **Release:** R1
**Priority:** **P0** · **Persona:** Toda a equipe (perf regression detection)
**Owner class:** `pulse-test-engineer`
**Trigger:** Incidente de 2026-04-24 — `/metrics/home` regrediu pra 54s
sem ninguém perceber porque cache local mascarava.

### Problema

O smoke spec atual valida **render correto** (h1 visível, KPI presente,
sidebar) mas **não valida tempo**. Test timeout é 60s. Resultado: dash
podia levar 50s pra carregar (o que é completamente quebrado pra UX) e
o smoke ainda passaria.

Pirâmide otimizou pra correção lógica, não pra viability operacional.

### Solução

Adicionar performance budgets ao smoke existente
(`tests/e2e/platform/home-dashboard-smoke.spec.ts`):

```typescript
test('home loads within performance budget', async ({ page }) => {
  const navStart = Date.now();
  await page.goto('/', { waitUntil: 'load', timeout: 10_000 });
  const navMs = Date.now() - navStart;
  expect(navMs, 'page navigation budget').toBeLessThan(5_000);

  // Time to first KPI with data (cold cache assumed)
  const kpiStart = Date.now();
  await waitForFirstKpiWithData(page);
  const kpiMs = Date.now() - kpiStart;
  expect(kpiMs, 'first KPI render budget').toBeLessThan(8_000);

  // Total interactive — sidebar + topbar + main content all rendered
  expect(navMs + kpiMs, 'total interactive budget').toBeLessThan(10_000);
});
```

Budgets sugeridos (ajustar conforme baseline observado):
- Navigation (DOM ready): < 5s
- First KPI with real data: < 8s (cold) / < 2s (warm)
- Total interactive: < 10s (cold) / < 3s (warm)

**Importante**: budgets devem ser MEDIDOS (não chutados). Primeira
versão coleta P95 sobre 10 runs e fixa em `P95 + 30%` margem.

### Acceptance Criteria

```
Given the smoke spec runs in CI against the seeded backend
 When `/metrics/home` takes longer than 8s to return KPI data
 Then the smoke spec fails with a clear "performance budget exceeded"
   message including measured ms and budget ms

Given a perf regression is introduced (e.g. missing index)
 When PR runs CI
 Then the smoke fails BEFORE merge — not after deploy
```

**Anti-surveillance check:** PASS.
**Dependencies:** FDD-OPS-004 (smoke precisa rodar em CI bloqueante).
**Estimate:** XS (30min — adendo no smoke existente após FDD-OPS-004).
**Risco de não fazer:** classe de bug "queries lentas" continua invisível
até produção.

---

## FDD-OPS-007 · Cold-cache test mode (perf realista)

**Epic:** Quality · **Release:** R1
**Priority:** **P1** · **Persona:** Toda a equipe (catch warm-cache false negatives)
**Owner class:** `pulse-test-engineer` + `pulse-data-engineer`

### Problema

Smoke + perf tests rodam contra Postgres com buffer pool **cheio** —
queries que seq-scan podem retornar em <1s simplesmente porque as páginas
estão cacheadas. Em produção, primeira request do dia pega cache frio e
demora 10-50× mais.

Hoje a mitigação é "esperar a CI rodar do zero" mas isso não força cold
cache do DB — só da imagem docker.

### Solução

Adicionar endpoint admin de teste:

```python
# pulse-data/src/contexts/admin/routes.py (test-only)
@router.post("/admin/test/reset-cache")
async def reset_db_cache(token: str = Header(...)):
    # SELECT pg_buffercache + DISCARD ALL + restart connection pool
    ...
```

E flag CLI no smoke:
```bash
PULSE_TEST_COLD_CACHE=1 npx playwright test tests/e2e/platform
```

Quando flag está ON, o smoke chama `/admin/test/reset-cache` antes de
navegar e mede tempos com cache frio.

CI roda 1 ciclo warm + 1 ciclo cold. Budgets diferentes pra cada.

### Acceptance Criteria

```
Given PULSE_TEST_COLD_CACHE=1 is set
 When the smoke spec navigates to /
 Then DB cache is reset before measurement
  And cold-cache budgets apply (< 12s total interactive)
  And warm-cache budget is also validated in a second pass
```

**Estimate:** S (2-3h — endpoint + smoke wrapper + CI matrix).
**Dependencies:** FDD-OPS-006.
**Risco de não fazer:** budgets passam local com cache quente, falham
na primeira request real do dia em produção.

---

## FDD-OPS-008 · Per-endpoint performance contract suite

**Epic:** Quality · **Release:** R1
**Priority:** **P1** · **Persona:** Engineering (regression detection)
**Owner class:** `pulse-test-engineer`

### Problema

Smoke E2E mede experiência de página (navigation + render). Não valida
endpoints individuais. Quando alguém adiciona um novo endpoint pesado, a
regressão só aparece quando o usuário abre a tela — talvez semanas
depois.

### Solução

`tests/perf/test_endpoint_budgets.py` (pytest-benchmark):

```python
ENDPOINTS = [
    ("/data/v1/metrics/home?period=30d",   p95_seconds=2.0),
    ("/data/v1/metrics/dora?period=30d",   p95_seconds=1.5),
    ("/data/v1/pipeline/teams",            p95_seconds=0.5),
    ("/data/v1/pipeline/health",           p95_seconds=0.5),
    ("/data/v1/metrics/flow-health?period=30d", p95_seconds=2.0),
]

@pytest.mark.parametrize("path,p95_budget", ENDPOINTS)
def test_endpoint_p95_within_budget(client, benchmark, path, p95_budget):
    result = benchmark.pedantic(
        lambda: client.get(path),
        rounds=10,
        iterations=1,
    )
    assert result.stats["p95"] < p95_budget, (
        f"{path} P95={result.stats['p95']:.2f}s > budget {p95_budget}s"
    )
```

Roda nightly (cron) + em PRs que tocam `routes.py`, `services/*`,
`repositories.py`, ou migrations.

### Acceptance Criteria

```
Given the perf suite runs against a seed-loaded DB
 When any endpoint's P95 exceeds its budget
 Then the suite fails with a clear "<path> P95=Xs > Ys" message
  And the offending PR cannot merge

Given a new endpoint is added without a budget entry
 Then a unit-level test fails with "Add a budget entry to ENDPOINTS"
```

**Estimate:** M (4-6h — suite skeleton + 5 endpoints + CI wire + budget
tuning). XS por endpoint adicional.
**Dependencies:** FDD-OPS-004 (backend-in-CI), FDD-OPS-010 (scale fixtures).
**Risco de não fazer:** N+1 queries, joins ruins, missing indexes ficam
escondidos até afetar UX.

---

## FDD-OPS-009 · DB query plan regression tests

**Epic:** Quality · **Release:** R1
**Priority:** **P1** · **Persona:** Backend engineering
**Owner class:** `pulse-data-engineer` + `pulse-test-engineer`

### Problema

Schema evolution (nova migration, ALTER TABLE, drop index acidental) pode
silenciosamente reintroduzir Seq Scan em queries críticas. Perf suite
(FDD-OPS-008) pega o sintoma com lag (P95 sobe). Plan regression test
pega a causa imediatamente.

### Solução

`tests/db/test_query_plans.py`:

```python
CRITICAL_QUERIES = {
    "home_latest_lean": (
        "SELECT * FROM metrics_snapshots "
        "WHERE tenant_id=:t AND metric_type='lean' AND team_id IS NULL "
        "ORDER BY calculated_at DESC LIMIT 200",
        {"t": DEV_TENANT},
        {"max_seq_scans": 0, "max_total_cost": 1000},
    ),
    "flow_health_active_issues": (...),
    # ...
}

@pytest.mark.parametrize("name,sql,params,limits", CRITICAL_QUERIES.items())
def test_query_plan_within_limits(session, name, sql, params, limits):
    plan = session.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"), params).scalar()
    seq_scans = count_node_type(plan, "Seq Scan")
    total_cost = plan[0]["Plan"]["Total Cost"]
    assert seq_scans <= limits["max_seq_scans"], (
        f"Query {name}: {seq_scans} seq scans (max allowed {limits['max_seq_scans']})"
    )
    assert total_cost <= limits["max_total_cost"]
```

Roda **após cada migration** no CI. Se uma migration acidentalmente dropa
um índice, este teste falha imediatamente.

### Acceptance Criteria

```
Given a critical query has its supporting index dropped
 When the plan test runs
 Then it fails with "Seq Scan detected" + offending query name
  And points to the migration commit that introduced the regression

Given a new critical query is added to the codebase
 Then a unit-level test reminds devs to add it to CRITICAL_QUERIES
```

**Estimate:** S (3-4h — fixtures + 5 critical queries + parser de plan
JSON + CI step pós-migration).
**Dependencies:** FDD-OPS-010.
**Risco de não fazer:** missing index regressions ficam escondidas até
DB crescer o suficiente pra dor virar visível (caso real de hoje).

---

## FDD-OPS-010 · Scale fixtures (`seed_dev --scale=large`)

**Epic:** Quality / DX · **Release:** R1
**Priority:** **P2** · **Persona:** Test engineering
**Owner class:** `pulse-test-engineer` + `pulse-data-engineer`

### Problema

`seed_dev.py` (PR #2) gera ~2k PRs / ~5k issues — bom pra UX exploration,
muito pequeno pra detectar regressões de scale. Bug de hoje só apareceu
com 7M rows em `metrics_snapshots`. Fixture pequeno = false sense of
security.

### Solução

Adicionar flag `--scale=large` ao `seed_dev.py` que multiplica volumes
em 50×:
- 100k PRs
- 250k issues
- 500k metrics_snapshots
- ~5min pra rodar

Usado em:
- Perf suite (FDD-OPS-008) — sempre rola contra `--scale=large`
- Query plan tests (FDD-OPS-009) — idem
- Smoke E2E nightly — opcionalmente roda contra scale-large 1× por dia

Dev local continua usando default (`--scale=medium`, ~2k PRs).

### Acceptance Criteria

```
Given `seed_dev.py --scale=large --confirm-local` runs
 When seed completes
 Then DB has at least 100k PRs, 250k issues, 500k snapshots
  And takes < 10min to populate
  And `make verify-dev` still passes

Given perf suite runs after scale-large seed
 Then budgets reflect production-like data sizes
```

**Estimate:** XS as add-on ao PR #2 (~2h adicional sobre o trabalho base
do `seed_dev.py`).
**Dependencies:** PR #2 (seed_dev base implementation).

---

## FDD-OPS-011 · Synthetic monitoring em produção

**Epic:** Operations · **Release:** **bloqueia first prod deploy**
**Priority:** **P0** (antes de deploy) · **Persona:** SRE / on-call
**Owner class:** `pulse-ciso` + `pulse-engineer`

### Problema

CI pega regressão antes de merge. Synthetic monitoring pega regressão
em runtime real (depois de deploy). Sem isso, primeira pessoa a saber
que `/` está fora é o usuário — caso real de hoje, em pequena escala
local. Em produção, é incidente.

### Solução

Configurar checks externos via UptimeRobot, Better Stack ou
healthchecks.io (free tier suficiente pra 50 checks):

| Check | Endpoint | Frequência | Alerta se |
|---|---|---|---|
| Home health | `https://app.pulse.tld/api/v1/health` | 5min | HTTP != 200 ou > 2s |
| Data API | `https://app.pulse.tld/data/v1/metrics/home?period=30d` | 5min | HTTP != 200 ou > 5s |
| Pipeline status | `https://app.pulse.tld/data/v1/pipeline/health` | 5min | HTTP != 200 |
| UI | `https://app.pulse.tld/` | 5min | HTTP != 200 ou > 5s |

Alertas via Slack `#pulse-alerts` + email pra 2 on-call. SLO inicial:
99% uptime, P95 < 3s.

### Acceptance Criteria

```
Given PULSE is deployed to production
 When the data API exceeds 5s P95 for > 10min
 Then a Slack alert fires in #pulse-alerts
  And the SLO dashboard shows the breach
  And on-call is paged

Given a deploy introduces a 500 error on /metrics/home
 When the synthetic check next runs
 Then alert fires within 10min (worst case)
```

**Estimate:** S (2-3h — configurar provider + 4 checks + Slack webhook +
runbook do on-call). Sem infra de código.
**Dependencies:** primeiro deploy em ambiente público (staging ou prod).
**Risco de não fazer:** primeiros incidentes em produção descobertos por
clientes, não pela equipe.

---

## FDD-OPS-012 · Issue sync — batch-per-project (simetria com PRs)

**Epic:** Data Pipeline Reliability · **Release:** R1
**Priority:** **P1** · **Persona:** Engineering (visibility + memory safety)
**Owner class:** `pulse-data-engineer`
**Trigger:** 2026-04-28 — full re-ingestion travada por horas em fase
"search/jql" sem nenhuma issue persistida no DB. Diagnóstico: arquitetura
do `_sync_issues()` é bulk-fetch-then-persist, enquanto `_sync_pull_requests()`
foi migrada pra batch-per-repo em 2026-04-23 (commit `7f9f339`). Issues
ficou pra trás.

### Problema

`packages/pulse-data/src/workers/devlake_sync.py:_sync_issues()` segue o
padrão antigo:

```python
raw_issues = await self._reader.fetch_issues(...)            # ← BLOQUEIA até paginar TUDO
changelogs = await self._reader.fetch_issue_changelogs(ids)  # ← + N calls extras
normalized = [normalize_issue(...) for raw in raw_issues]    # ← TUDO em RAM
count = await self._upsert_issues(normalized)                # ← upsert único
```

Para 32 projetos × ~12k issues médias = ~376k issues:
- **Tempo até primeira linha persistida**: 2-5h (pagination + changelogs serial)
- **Pico de memória**: ~1-2 GB de issue dicts (no atual setup, OK; se Webmotors crescer pra 1M+, OOM)
- **Visibilidade zero durante fetch**: `eng_issues.COUNT()` fica em 0 por horas — operadores acham que travou
- **Recovery se sync abortar mid-fetch**: zero progress preserved (toda paginação se perde)

PRs já resolveram isso em `7f9f339`:

```python
# devlake_sync.py:_sync_pull_requests() (post-7f9f339)
async for repo_name, raw_prs in self._reader.fetch_pull_requests_batched(since=since):
    # 1 repo at a time → normalize → upsert → progress signal
```

Resultado: PRs persistem em batches de ~100 a cada poucos segundos, operador
vê COUNT crescendo, recovery preserva 95%+ do trabalho em caso de crash.

### Solução

Espelhar o padrão de PRs em issues:

1. **Refactor `JiraConnector.fetch_issues()` em `fetch_issues_batched()`** —
   AsyncIterator que yielda `(project_key, batch_of_issues)` por página JQL
   (ou por projeto, granularidade a definir).

2. **Refactor `_sync_issues()` em devlake_sync.py** — loop async sobre
   batches, normaliza + upsert por batch, atualiza progress, publica Kafka
   por batch.

3. **Manter changelog fetch inline com expand=changelog** — não fazer call
   separada `fetch_issue_changelogs(ids)`. JQL já suporta `expand=changelog`
   inline (veja `jira_connector.py:212`). Verificar se está sendo usado.

4. **Watermark batch-aware** — atualizar watermark a cada N batches (ex: 10),
   não só no final. Permite resume após crash sem perder muito.

### Acceptance Criteria

```
Given a fresh re-ingestion against a Webmotors-scale tenant (32 projects, 376k issues)
 When _sync_issues() runs
 Then eng_issues.COUNT() starts growing within 60 seconds (not after hours)
  AND each batch persists ~100-500 issues
  AND total memory peak stays below 800 MB (vs 2 GB current)
  AND if the worker crashes mid-sync, ≥80% of fetched issues are already in DB

Given the new batch-per-project mode is enabled
 When operator queries `SELECT COUNT(*) FROM eng_issues` repeatedly
 Then count increases monotonically during the sync (not 0 → 376k jump)

Given Pipeline Monitor exposes /pipeline/ingestion-progress
 When _sync_issues() is mid-run
 Then progress endpoint shows current_source = "<project_key>" and
      records_ingested updates per batch (parity with PR sync)
```

### Anti-surveillance check
PASS — sem mudança em payload de métrica. Refactor é puramente sobre
fluxo de ingestão.

### Dependencies
Nenhuma. Pode ser implementado isoladamente.

### Estimate
**M (4-6h)**:
- 1.5h refactor `JiraConnector.fetch_issues_batched()`
- 1.5h refactor `_sync_issues()` em devlake_sync.py
- 1h ajustar progress tracking + watermarks
- 1-2h tests (unit pra batched fetcher + integration test contra fixture mock)

### Riscos de não fazer

- Cada full re-ingestion futura leva 3-5h cega (igual hoje)
- Quando Webmotors crescer ou primeiro tenant 2× maior chegar, OOM
- Operador não tem visibilidade durante o fetch — mascarando travas como
  a que aconteceu hoje (cycle 2 falhou silenciosamente em 21:23 e ninguém
  notou por 14h)

### Bonus

Esta FDD se conecta com **FDD-OPS-008** (per-endpoint perf budgets) — uma
vez que issues sync seja batched, fica viável adicionar performance
assertions: "batch persist deve completar em < 30s" → falha CI se regredir.

---

## FDD-OPS-013 · Eliminate redundant `fetch_issue_changelogs` call in `_sync_issues`

**Epic:** Data Pipeline Reliability · **Release:** R1 (P0 — fixes
24h+ blocking phase observed 2026-04-28)
**Priority:** **P0** · **Persona:** Data engineering, all customers
**Owner class:** `pulse-data-engineer`
**Trigger:** 2026-04-28 — full re-ingestion stuck for hours in
sequential `GET /rest/api/3/issue/{id}?expand=changelog` calls (~3
calls/sec for 250k+ issues = ~24h estimated). Diagnosed as redundant.

### Problema

`_sync_issues()` faz duas chamadas que sobrepõem 100%:

1. `fetch_issues()` — JQL search com `expand=changelog` inline. Já
   retorna a changelog completa em `raw["changelog"]`.
2. `fetch_issue_changelogs(ids)` — chama `GET /issue/{id}?expand=changelog`
   uma vez por issue.

Resultado: 376k issues × ~300ms latência = **~31 horas de chamadas
redundantes** + pressão sobre rate limit Atlassian.

O próprio connector documenta o problema (`jira_connector.py:267`):

```python
def fetch_issue_changelogs(...):
    """...
    Since fetch_issues already includes changelogs via expand=changelog,
    this method is used for issues fetched WITHOUT expand (e.g., sprint issues).
    """
```

Mas em `devlake_sync.py:614`:

```python
issue_ids = [str(raw["id"]) for raw in raw_issues]
changelogs_by_issue = await self._reader.fetch_issue_changelogs(issue_ids)  # ← redundante
```

E `normalize_issue` recebe `changelogs=changelogs_by_issue.get(id, [])` em
vez de extrair `raw["changelog"]` direto.

### Solução

**1 mudança código + 1 teste:**

```python
# devlake_sync.py:_sync_issues()
# REMOVER:
# issue_ids = [str(raw["id"]) for raw in raw_issues]
# changelogs_by_issue = await self._reader.fetch_issue_changelogs(issue_ids)

# SUBSTITUIR por:
# (changelogs já estão em raw["changelog"] via expand)
for raw in raw_issues:
    issue_changelogs = raw.get("changelog", {}).get("histories", [])
    issue_data = normalize_issue(
        raw, self._tenant_id, self._status_mapping,
        changelogs=issue_changelogs,
    )
    normalized.append(issue_data)
```

`fetch_issue_changelogs` permanece existindo — é usado SOMENTE para
sprint issues que vêm sem `expand` (esse caminho fica intocado).

### Acceptance Criteria

```
Given full re-ingestion against Webmotors (32 projects, 376k issues)
 When _sync_issues() runs
 Then NO calls are made to GET /rest/api/3/issue/{id}?expand=changelog
   (verify via httpx logs / mock)
  AND eng_issues.status_transitions JSONB is populated correctly
   (parity with current behavior — verified by domain-level tests)
  AND total wall time for issues phase drops from ~24h to ~5min

Given a fresh tenant has 1000 issues across 5 projects
 When sync runs
 Then changelogs are extracted from inline expand response
  AND status_transitions field has same content as before
```

### Regression test

Adicionar test em `packages/pulse-data/tests/integration/`:

```python
def test_sync_issues_uses_inline_changelogs_only():
    # Mock JiraConnector.fetch_issues returning raw with "changelog" inline
    # Mock fetch_issue_changelogs to record calls
    # Run _sync_issues
    # Assert mock_fetch_issue_changelogs.call_count == 0
    # Assert eng_issues.status_transitions populated correctly
```

Trava regressão futura (alguém pode "consertar" reintroduzindo a call).

### Anti-surveillance check
PASS — sem mudança em payload/normalização, só elimina I/O redundante.

### Estimate
**XS (1-2h)**:
- 30min: code change in `_sync_issues()`
- 30min: regression test
- 30min: validate against real Webmotors data (compare status_transitions before/after)
- ~30min margin

### Dependencies
Nenhuma. Pode ser shipped imediatamente.

### Risco de não fazer
Cada full re-ingestion (Webmotors hoje, novos tenants amanhã) leva 24h+
em vez de minutos. SaaS-blocker.

### Conexão com v2 architecture
Este é o "quick win Phase 1" do `docs/ingestion-architecture-v2.md`. Não
substitui Phases 2/3, mas elimina o pior gargalo single-handedly.

---

## FDD-OPS-014 · Per-source workers + per-scope watermarks

**Epic:** Data Pipeline Architecture · **Release:** R1
**Priority:** **P1** · **Persona:** SaaS engineering team
**Owner class:** `pulse-data-engineer` + `pulse-engineer`
**Trigger:** 2026-04-27/28 incidents — sync-worker monolítico travado
em Jenkins (VPN off) bloqueando GitHub e Jira que estavam saudáveis.
Global watermark causando full backfill ao adicionar projetos novos.

### Problema (dois sintomas, uma causa)

**Sintoma 1 — sem source isolation (AP-4):**

`DataSyncWorker` é um único processo que roda 4 fases sequenciais
(`issues → PRs → deploys → sprints`). Todas as 4 fontes (GitHub, Jira,
Jenkins) compartilham:

- Mesmo event loop
- Mesma cadence de sync
- Mesmo cycle order
- Mesmo failure handling

Consequência: **Jenkins offline (VPN drop)** ou **Jira blip** travam
todo o ciclo, mesmo que GitHub esteja saudável. Onboarding de GitLab/ADO
significa ainda mais código no mesmo loop monolítico.

A simétrica fica esquisita: `discovery-worker` JÁ é processo separado
(boa decisão em ADR-014). `sync-worker` ficou para trás.

**Sintoma 2 — global watermark (AP-3):**

`pipeline_watermarks` tem 1 row por `entity_type`, sem dimensão de
scope:

```sql
entity_type='issues', last_synced_at='2026-04-26'  -- aplica a TODOS os 32 projetos
```

Consequência: quando discovery ativa um novo projeto, a única forma de
backfill é resetar watermark para `2020-01-01`, o que **re-fetcha
TODOS os 200k+ issues dos projetos existentes** sem necessidade.

### Solução (2 partes coesas)

**Parte 1 — split sync-worker em 3 workers:**

```
docker-compose.yml:
  sync-worker         → REMOVE
  github-sync-worker  → NEW (apenas GitHub PRs)
  jira-sync-worker    → NEW (apenas Jira issues + sprints)
  jenkins-sync-worker → NEW (apenas Jenkins deploys)
```

Cada worker:
- Próprio event loop
- Cadence configurável independente
- Health-aware: pre-flight check antes de iniciar fase
- Logging com tag de source para grep/filter

**Parte 2 — per-scope watermarks:**

Migration nova adiciona `scope_key` em `pipeline_watermarks`:

```sql
ALTER TABLE pipeline_watermarks
  ADD COLUMN scope_key VARCHAR(255) NOT NULL DEFAULT '*';

-- Drop unique on entity_type alone, replace:
ALTER TABLE pipeline_watermarks
  ADD CONSTRAINT uq_watermark_scope
  UNIQUE (tenant_id, entity_type, scope_key);
```

Watermarks viram:

| tenant_id | entity_type | scope_key | last_synced_at |
|---|---|---|---|
| ...001 | issues | jira:project:BG | 2026-04-26 |
| ...001 | issues | jira:project:OKM | 2026-04-26 |
| ...001 | pull_requests | github:repo:foo/bar | 2026-04-26 |
| ...001 | deployments | jenkins:job:deploy-X | 2026-04-26 |

Connector-side: `fetch_issues(project_key=..., since=watermark[scope_key])`.

### Acceptance Criteria

```
Given Jenkins is unreachable (VPN off)
 When the daily ingestion cycle runs
 Then jenkins-sync-worker logs "unhealthy, skipping cycle"
  AND github-sync-worker continues normally
  AND jira-sync-worker continues normally
  AND VPN reconnect → jenkins-sync-worker resumes from last per-scope watermark

Given a NEW Jira project is auto-activated by discovery
 When jira-sync-worker runs the next cycle
 Then ONLY the new project's issues are backfilled (since 2020-01-01)
  AND existing projects' issues are NOT re-fetched
  AND pipeline_watermarks has a new row with scope_key=jira:project:NEW

Given Webmotors has 32 active Jira projects
 When jira-sync-worker runs incremental sync
 Then 32 watermarks are queried (1 per scope)
  AND each project syncs from its own last_synced_at
  AND total cycle time scales linearly with new data, not historical data
```

### Anti-surveillance check
PASS — sem mudança em campos persistidos.

### Estimate
**M-L (1 semana)**:
- 1 dia: extract per-source workers (refactor `DataSyncWorker`)
- 0.5 dia: docker-compose + Dockerfile per-source
- 1 dia: schema migration + watermark repo refactor
- 1 dia: connector-side scope filtering (Jira `project_keys` already there; GitHub repo-by-repo already there; Jenkins per-job)
- 1 dia: testes (especialmente o cenário VPN drop simulation)
- 0.5 dia: Pipeline Monitor UI per-source breakdown
- ~1 dia margin

### Dependencies
- FDD-OPS-013 (deve shipping antes pra simplificar refactor)
- FDD-OPS-012 (issue batch-per-project) idealmente ships antes — mas
  pode ser paralelo

### Risco de não fazer
- Cada outage de fonte (VPN, rate-limit, Atlassian incident) trava todo
  o pipeline
- Onboarding de GitLab/ADO/Linear adiciona código na monolita já
  frágil
- SaaS multi-tenant inviável sem isolation entre tenants → entre sources
  é o primeiro passo

### Conexão com v2 architecture
Este é o "Phase 2" de `docs/ingestion-architecture-v2.md`. Phase 3 (job
queue + worker pool) constrói em cima.

---

## FDD-OPS-015 · Observable ingestion: pre-flight estimates + per-scope progress + ETA

**Epic:** Data Pipeline / Ops Visibility · **Release:** R1
**Priority:** **P1** · **Persona:** Operators (you, on-call), data engineering
**Owner class:** `pulse-data-engineer` + `pulse-engineer` (UI)
**Trigger:** 2026-04-27/28 — 5 cycles where I gave estimates ("ETA
45min") that were wrong by 10×+. Operator (você) cannot answer "is it
stuck?" without diving into logs. `COUNT(*)` is useless during
bulk-fetch.

### Problema

Atualmente:

1. **Sem pre-flight count.** Worker não pergunta "quantas issues match
   esse JQL?" antes de iniciar. Apenas começa.
2. **Sem rate-aware ETA.** Pace medido (ex: 27 calls/min) não é
   usado pra calcular tempo restante.
3. **Sem per-scope progress.** Quando preso, impossível distinguir
   "BG (197k) ainda não terminou" de "estamos no projeto X".
4. **Pipeline Monitor mostra agregado per-entity_type**, não per-scope.

Consequência operacional: **5 falsos alarmes de progresso esta semana**.

### Solução (3 entregas coesas)

**1. Pre-flight estimate per scope:**

Em cada início de fase, o worker chama o source pra contar:

```python
# Jira: count via JQL count
estimate = await jira.count_issues(project_key=BG, since=watermark)
# logs: "[scope=jira:project:BG] estimated 12,450 issues since 2026-04-26"
```

Se a count call em si for muito cara (alguns sources não suportam),
heuristic: "X items since Y, extrapolated."

**2. Per-batch progress with rate-aware ETA:**

Cada batch persistido emite progress event:

```python
{
  "scope": "jira:project:BG",
  "phase": "fetching",
  "items_done": 1200,
  "items_total_estimate": 12450,
  "items_per_second": 18.5,
  "eta_seconds": 608,
  "started_at": "...",
  "current_high_water": "2026-04-27T10:23:00Z"
}
```

Tabela nova `pipeline_progress` (live + historical):

```sql
CREATE TABLE pipeline_progress (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    scope_key VARCHAR(255),
    entity_type VARCHAR(64),
    phase VARCHAR(32),  -- fetching | normalizing | persisting | done | failed
    items_done INT,
    items_estimate INT,
    items_per_second DOUBLE PRECISION,
    eta_seconds INT,
    started_at TIMESTAMPTZ,
    last_progress_at TIMESTAMPTZ,
    status VARCHAR(16),  -- running | done | failed | paused
    last_error TEXT
);
```

**3. Endpoint `/pipeline/jobs` + Pipeline Monitor UI per-scope:**

```
GET /data/v1/pipeline/jobs

[
  {
    "scope": "jira:project:BG",
    "entity_type": "issues",
    "status": "running",
    "items_done": 1200,
    "items_estimate": 12450,
    "progress_pct": 9.6,
    "eta_seconds": 608,
    "rate_per_sec": 18.5,
    "started_at": "...",
    "errors": []
  },
  ...
]
```

Pipeline Monitor UI ganha tab "Per-scope progress" com tabela tipo Top Hat:
scope, status, %, ETA, current rate, errors.

### Acceptance Criteria

```
Given a fresh ingestion against 32 projects
 When operator queries /pipeline/jobs after 30s
 Then response includes 32 rows (1 per active scope)
  AND each row has status, items_done, ETA, rate
  AND ETA accuracy: actual_completion_time within ±20% of estimate
   (measured: ETA at 10% complete vs actual completion at 100%)

Given an ingestion job stalls (network blip, source down)
 When 60 seconds pass without progress
 Then job's last_progress_at falls > 60s behind now()
  AND UI displays "stalled" badge
  AND on-call gets clear signal "scope X is stuck"

Given operator wants to investigate a slow source
 When opens Pipeline Monitor → Per-scope tab
 Then can sort by items_per_second
  AND can filter by entity_type/source
  AND can see error history per scope
```

### Anti-surveillance check
PASS — progress data is metadata about ingestion, not user activity.

### Estimate
**M (3-5 dias)**:
- 0.5 dia: schema migration `pipeline_progress`
- 1 dia: pre-flight count helpers (Jira count JQL, GitHub repo count, Jenkins job count)
- 1 dia: per-batch progress emission + ETA calculation
- 0.5 dia: `/pipeline/jobs` endpoint
- 1 dia: Pipeline Monitor UI tab per-scope
- 0.5 dia: tests + dashboard polish

### Dependencies
- FDD-OPS-014 (per-scope watermarks) é pré-requisito do per-scope
  progress
- FDD-OPS-012 (batch-per-project) facilita progress emit per-batch

### Riscos
- Pre-flight count aumenta tempo total se overhead alto. Mitigar: se
  count > 5s, usar heuristic
- Estimate ruim no início (até medir rate real) — aceitar e refinar a
  cada batch

### Conexão com v2 architecture
Este é o "Phase 1.5" de `docs/ingestion-architecture-v2.md`. Crítico
para evitar repetir o ciclo de "estimar 45min, esperar 4h, descobrir
que travou".

---

## FDD-OPS-016 · Effort estimation fallback chain (Story Points → T-shirt → Hours → Count)

**Epic:** Data Quality · **Release:** R1
**Priority:** **P1** · **Persona:** Data consumer / metric layer
**Owner class:** `pulse-data-engineer` · **Status:** SHIPPED 2026-04-28

### Problema confirmado

Panorama do Pulse DB em 2026-04-28 mostrou **`story_points = 0` em todas
as 311.007 issues**. Investigação na instância Jira da Webmotors revelou:

- **`customfield_10004` ("Story Points")**: 0% populado em todos os 69 projetos
- **`customfield_18524` ("Story point estimate")**: 0% populado também
- Webmotors **não usa Story Points como método de estimativa**

Distribuição real por projeto (amostra de 50 issues):

| Projeto | T-Shirt Size | Original Estimate (h) | Tamanho/Impacto | Padrão |
|---------|--------------|------------------------|------------------|--------|
| ENO     | 24%          | 52%                    | 4%               | Horas + tshirt |
| DESC    | 26%          | 34%                    | 6%               | Horas + tshirt |
| APPF    | 0%           | 12%                    | 0%               | Horas (raro) |
| OKM     | 4%           | 8%                     | 0%               | Quase Kanban |
| BG, FID, PTURB | 0%   | 0%                     | 0%               | **Kanban puro** |

Sem fallback, métricas de velocity, throughput-by-effort e forecast
ficavam zeradas para 100% das issues — bloqueando todo o pilar Lean.

### Solução implementada

Cadeia de fallback em `JiraConnector._extract_story_points`:

1. **Story Points / Story point estimate** (numérico) — uso direto
2. **T-Shirt Size** (option) — mapa Fibonacci: PP=1, P=2, M=3, G=5, GG=8, GGG=13
3. **Tamanho/Impacto** (option) — mesmo mapa
4. **`timeoriginalestimate`** (segundos) — buckets: ≤4h=1, ≤8h=2, ≤16h=3, ≤24h=5, ≤40h=8, ≤80h=13, >80h=21
5. **`None`** — issue genuinamente não estimada

Discovery automático via `_discover_custom_fields` casa por nome
("t-shirt size", "tamanho/impacto") — não hardcode customfield IDs.

Telemetria de origem (`_effort_source_counts`) loggada por batched run:
operadores conseguem ver se o squad migrou de horas pra t-shirt sem
combar logs.

### Quando `story_points = None` (Kanban puro)

Quando nada está populado, a métrica downstream **DEVE contar items**
em vez de somar pontos. Esta decisão fica na camada de métricas, **não**
no normalizer. O normalizer só extrai o que existe.

### Regras de mapeamento — escolhas e por quê

- **Fibonacci-aligned**: comum na indústria, métricas downstream já
  esperam essa escala
- **Hours buckets calibrados** contra valores observados na Webmotors
  (2h–124h, múltiplos de 4) — cada valor comum cai num bucket sensato
- **Skipa SP = 0**: sentinel comum para "não estimado", trata como falta

### Validação live

Projeto CRMC (1.375 issues, ingestão completa pós-fix):
- **52,3% com effort estimado** (719/1.375 issues)
- Distribuição de valores: 1, 2, 3, 5, 8 — confirma escala Fibonacci aplicada

### Migração dos 311k issues legados

Como o upsert sobrescreve `story_points` em re-sync, os 311k issues
existentes vão receber o effort correto **conforme cada projeto recebe
updates incrementais**. Para acelerar, op pode resetar watermarks
por projeto via SQL — custo: re-fetch da API Jira.

### Arquivos
- `pulse/packages/pulse-data/src/connectors/jira_connector.py`:
  - Constants `TSHIRT_TO_POINTS`, `_hours_to_points`, patterns
  - `_discover_custom_fields` agora detecta tshirt fields
  - `_extract_story_points` reescrito com cadeia de fallback
  - Telemetria via `_effort_source_counts` + log no fim de batched fetch
- `pulse/packages/pulse-data/tests/unit/test_effort_fallback_chain.py`:
  34 testes cobrindo cada hop, cada size, cada bucket de horas

### Anti-surveillance check
PASS — apenas valores agregados de effort são extraídos; nenhum dado
identificador de pessoa é coletado.

### Próximo passo (deferido)
Adicionar coluna `effort_source` em `eng_issues` para auditoria por
issue (qual hop produziu o valor). Útil para debugging mas não
bloqueante. Cobertura atual via telemetria batched é suficiente
para R1.

---

## FDD-OPS-017 · Status normalization with statusCategory fallback

**Epic:** Data Quality (foundational) · **Release:** R1
**Priority:** **P0** (corrupts every flow metric) · **Persona:** All metric consumers
**Owner class:** `pulse-data-engineer` · **Status:** SHIPPED 2026-04-29

### Problema confirmado

Audit do panorama em 2026-04-28 mostrou distribuição absurda de
`normalized_status` em 311k issues:

  - 96,5% `done` · 3,3% `todo` · 0,2% `in_progress` · 0,1% `in_review`

A Webmotors tem **104 status raw distintos** em workflows ativos. Nosso
`DEFAULT_STATUS_MAPPING` cobria ~50, então 50+ status caíam silenciosamente
no fallback "Unknown → todo" — incluindo:

| Status raw | Issues afetadas | Bucket atual | Bucket correto |
|---|---|---|---|
| `FECHADO EM PROD` | 2.881 | todo | done |
| `Em Progresso` | 6 | todo | in_progress |
| `Em desenv` | 4 | todo | in_progress |
| `Em Deploy Produção` | 14 | todo | in_progress |
| `Em Monitoramento Produção` | 3 | todo | done |
| `Homologação` | 9 | todo | in_review |
| `Em Verificação` | 4 | todo | in_review |
| ... | ... | ... | ... |

**Impacto em CASCATA**: status_transitions herdam a classificação errada,
então o último estado de uma issue concluída ficava registrado como
`todo`. Resultado:

- **Cycle Time** infinito (não há transição para `done`)
- **Throughput** sub-conta (issues entregues não aparecem)
- **WIP** super-conta (issues finalizadas continuam "em fluxo")
- **CFD** distorcido (área de "todo" inflada)
- **Lead Time** indeterminado

Sem o fix, **todo o pilar Lean** está comprometido para qualquer projeto
que use status PT-BR fora do nosso mapping.

### Solução implementada

**Estratégia híbrida** em 3 camadas:

1. **Mapping textual** (`DEFAULT_STATUS_MAPPING`) — preserva a
   granularidade `in_progress` vs `in_review` que as métricas curadas
   precisam. Expandido para cobrir os top 80+ status PT-BR observados.

2. **Fallback `statusCategory.key` da Jira** — fonte autoritativa para
   a dimensão `done` vs `não-done`. Descoberto via `/rest/api/3/status`
   (chamada única por lifetime do conector, ~326 status definitions na
   Webmotors).
   - `done` → `done`
   - `indeterminate` → `in_progress`
   - `new` → `todo`

3. **Default final** `todo` com WARN log — só atinge status sem
   categoria (extremamente raro).

### Arquivos modificados

- `pulse/packages/pulse-data/src/connectors/jira_connector.py`:
  - `_discover_status_categories()` — descobre + cacheia `name → category`
  - `_map_issue` anexa `status_category` (current) e
    `status_categories_map` (todos, para histórico de transitions)
- `pulse/packages/pulse-data/src/contexts/engineering_data/normalizer.py`:
  - `normalize_status(raw, mapping, status_category=...)` — assinatura nova
  - `build_status_transitions(..., status_categories_map=...)` — classifica
    cada `to_status` histórica via map
  - `DEFAULT_STATUS_MAPPING` expandido (~80 entradas novas PT-BR)
- `pulse/packages/pulse-data/tests/unit/test_status_normalization.py`:
  44 testes novos (textual ganha quando definido, category fallback,
  Webmotors regression cases, transitions integração)

### Validação live

Cross-check do mapping contra DB atual mostrou que **3.151 issues
reclassificarão** quando o sync re-tocar (1% do total):

  - 2.923 `todo → done` (FECHADO EM PROD/HML, etc.)
  - 161 `todo → in_review` (Homologação, Verificação, etc.)
  - 67 `todo → in_progress` (Em Progresso, Em desenv, etc.)

Esses 3.151 representam o "long tail" cuja má classificação distorcia
métricas individuais. Os ~300k issues `done` corretos continuam corretos.

### Backfill dos legados

Como o upsert sobrescreve `normalized_status` e `status_transitions`,
issues vão se reclassificar conforme cada projeto receber updates
incrementais. Para acelerar há duas opções:

1. **Reset watermark por projeto** (custo: re-fetch da API Jira)
2. **Migration script futuro** — recalcular `normalized_status` e
   `status_transitions[].status` direto via SQL (sem refetch). Decidido
   deixar para issue separada — muda dado em produção, requer plano.

### Anti-surveillance check
PASS — apenas valores de status agregados; nenhum dado pessoal.

### Test coverage
116/116 verde (44 novos + 72 existentes). Cobertura inclui:
- Textual mapping ganha sobre category mismatch
- Cada categoria Jira fallback (`done` / `indeterminate` / `new`)
- Casos PT-BR Webmotors regressão
- Backward compat (legacy callers sem category)
- `build_status_transitions` integrado com category map

### Decisão de produto registrada

`FECHADO EM HML` foi mapeado como `done` (segue Jira) em vez de
`in_review`. Workflow author classifica como done; respeitamos. Se
Webmotors quiser mantê-lo em fluxo, pode renomear para "Aguardando
Deploy Produção" (já mapeado como in_progress).

---

## FDD-OPS-018 · Sprint status pipeline — 4-layer cheese fix

**Epic:** Data Quality (sprint metrics) · **Release:** R1
**Priority:** **P1** · **Persona:** Sprint metric consumers
**Owner class:** `pulse-data-engineer` · **Status:** SHIPPED 2026-04-29

### Problema confirmado

100% das 216 sprints na Webmotors estavam com `status=''` no `eng_sprints`.
O `goal` também totalmente vazio. Investigação revelou um clássico
"swiss cheese alignment" — **4 bugs independentes** em camadas diferentes,
cada um sozinho garantia que o status nunca fosse populado:

| Camada | Bug | Sintoma sozinho |
|---|---|---|
| 1. Connector | `_map_sprint` mapeava OK (ACTIVE/CLOSED/FUTURE) | — |
| 2. Normalizer | `normalize_sprint` retornava dict SEM `status` | Status nunca chega no upsert |
| 3. Worker upsert | `_upsert_sprints` ON CONFLICT não atualizava `status`/`goal` | Sprints existentes nunca atualizam |
| 4. Connector watermark | `_fetch_board_sprints` filtrava por `started_date < since` | Sprints antigas nunca re-fetchadas |
| 5. ORM model | `EngSprint` no SQLAlchemy não tinha campo `status` (schema drift) | `Unconsumed column names: status` |

A camada 4 é particularmente insidiosa: sprint state transitions
(`active` → `closed`) acontecem em `endDate`, não `startDate`. Filtrar
por started_date significa que uma sprint que começou em março e
fechou em maio nunca tem o status atualizado depois de março.

### Impacto métrico (atual e futuro)

Atualmente nenhum métrico consome `eng_sprints.status` diretamente —
por isso o bug ficou silencioso. Mas:
- **Sprint Comparison / Velocity Trend** (já em código) precisa filtrar
  sprints `closed` para excluir sprints em andamento da regressão linear
- **Dashboard "current sprint"** (planejado) precisa de `status='active'`
- **Carryover Rate** já usa heurística de `endDate < now()` mas o ideal
  é confiar em status='closed'
- **Goal** é input visual importante para a página da sprint

### Solução implementada

**Fix em todas as 4 camadas**:

1. `JiraConnector._map_sprint` agora também passa `goal` adiante
2. `normalizer.normalize_sprint` inclui `status` (lowercase: `active`/
   `closed`/`future`/None) e `goal` (com strip de null bytes)
3. `_upsert_sprints` ON CONFLICT atualiza `status` + `goal`
4. `_fetch_board_sprints` removeu o filtro de watermark (volume baixo,
   sprints mudam estado ao longo do tempo, sempre re-fetch é correto)
5. `EngSprint` model adiciona `status: Mapped[str|None]` (corrige drift)

Helper `_normalize_sprint_status` mapeia aliases comuns (open→active,
completed→closed, planned→future) e devolve `None` para valores
desconhecidos — não bucketiza silenciosamente.

### Validação live

Após o fix + ad-hoc backfill direto:

| Status | Quantidade | Tem goal? |
|---|---|---|
| `closed` | 187 | sim |
| `active` | 3 | sim |
| `future` | 5 | sim |
| (vazio) | 22 | — board órfão 873 sem projeto ativo |

**195/217 = 89,9%** das sprints com status correto + 70% com goal real
(ex: "Gestão de banner no backoffice de CNC e TEMPO para novas
especificações técnicas"). As 22 vazias são de board órfão, fora do
escopo deste fix.

### Tests
- `tests/unit/test_sprint_normalization.py` — 26 testes novos:
  - status field presente no dict (5 cenários)
  - unknown values retornam None (4)
  - aliases (13 mapeamentos)
  - goal passthrough (3)
  - structural anti-regression: `_upsert_sprints.set_` inclui status + goal
- 142/142 verde (pyramid completo)

### Lição aprendida — guard against future drift

ORM model drift was the most insidious of the 4 bugs. The DB had the
column for ages; only the SQLAlchemy `EngSprint` was missing it. Any
upsert path that included `status` would crash; any path that omitted
it would silently produce empty data. Prevention going forward:

- Pyramid test step "schema introspection vs ORM model" (deferred —
  candidate for FDD-OPS-001 line of defense)
- Migration review checklist: every new column → corresponding
  Mapped column in SQLAlchemy model

### Anti-surveillance check
PASS — `goal` is squad/sprint-level free text, no individual attribution.

---

## FDD-OPS-019 · Investigate Jira JQL pagination cap on large projects (BG short-fetch)

**Epic:** Data Pipeline Reliability · **Release:** R1
**Priority:** **P1** (impacts data completeness on largest tenants) · **Persona:** Operators + downstream metric consumers
**Owner class:** `pulse-data-engineer`
**Status:** OPEN — observed 2026-04-30 during full backfill

### Sintoma observado

Durante o backfill comprehensive de 2026-04-30 (reset de watermarks `entity_type='issues'` para 2020-01-01 + restart sync-worker), o projeto **BG** terminou com `status='done'` mas **incomplete**:

| Métrica | Valor |
|---|---|
| `eng_issues WHERE issue_key LIKE 'BG-%'` | **197.760** (estável, do backfill original) |
| `count_issues_for_project(BG, since=None)` retorna | **197.762** (Jira approximate-count) |
| Items processed este cycle | **126.000** (`pipeline_progress.items_done`) |
| Coverage transitions BG após cycle | **125.911 / 197.760 (63,7%)** |
| Cycle duration estimado vs real | rate ~50/s × 197k = ~66min esperado; cycle terminou em ~46min |
| `last_error` no progress row | **NULL** — finalização limpa, sem exception |

`tracker.finish('done')` foi chamado normalmente — significa que o iterator `fetch_issues_batched` **terminou normalmente** (loop sai quando `nextPageToken` é vazio ou `issues=[]` no response). Não houve crash, retry, timeout, nem erro de rede.

### Hipóteses (a investigar)

1. **Hard cap interno da Jira em buscas com cursor pagination** quando ORDER BY `updated` é usado com `since` muito antigo. Possível cap em ~125k results por query.
2. **`approximate-count` over-conta** issues archived/deleted que não são retornadas pelo `/search/jql`. Mas `eng_issues WHERE issue_key LIKE 'BG-%'` mostra 197.760 issues que JÁ foram ingeridas algum dia, então elas existem.
3. **Race condition** — algum nextPageToken retornou empty prematuramente devido a refresh de índice durante o sweep.
4. **Limit não-documentado** no novo endpoint `/rest/api/3/search/jql` (que substituiu o deprecated `/search` em 2025).

### Reprodução

```bash
# 1. Reset BG watermark
docker compose exec postgres psql -U pulse -d pulse -c \
  "UPDATE pipeline_watermarks SET last_synced_at='2020-01-01' \
   WHERE entity_type='issues' AND scope_key='jira:project:BG';"

# 2. Trigger sync via restart
docker compose restart sync-worker

# 3. Tail logs, count "[batched] BG: complete" line — should report total_yielded
```

Se reproduzir 126k consistentemente, é cap determinístico. Se variar, é race.

### Investigation plan (proposed, scope: ~1d)

**Step 1 — Confirmar cap via instrumentação**:
- Adicionar log mais granular em `fetch_issues_batched`: a cada N páginas, logar `total_yielded` + quanto retornou
- Capturar resposta crua quando `nextPageToken` retorna vazio (ver se há `isLast: true` ou similar)

**Step 2 — Workaround comprovado: chunking por data**:
Se cap for confirmado, partir o JQL em janelas de tempo:

```python
# Em fetch_issues_batched, when projeto é "grande" (>50k pelo pre-flight):
date_chunks = [
    (None, "2022-01-01"),       # tudo antes de 2022
    ("2022-01-01", "2024-01-01"),
    ("2024-01-01", None),       # tudo após 2024
]
for start, end in date_chunks:
    jql_chunk = f'project = "{key}" AND updated >= "{start}"'
    if end: jql_chunk += f' AND updated < "{end}"'
    # paginate normally; merge results
```

Threshold para chunking: `count > 100k` no pre-flight.

**Step 3 — Atomic JQL counting**:
Validar via `cf-search-count` chunk: se `count_issues_for_project(BG, since="2024-01-01")` + `... since=null AND updated < 2024-01-01` somar = 197k, confirma que cap é por-query. Se não somar, é approximate-count que mente.

**Step 4 — Fallback em produção**:
Se cap não for resolvido, adicionar telemetria que detecta: `if items_done < items_estimate × 0.9 at end-of-stream`, log WARN + create event no `pipeline_events` para revisão.

### Workaround imediato

**Sem código novo**: aceitar coverage ~54% pós-backfill. Os ~72k BG issues "missing" têm dados antigos (`status_transitions=[]`, `story_points=NULL`) mas:
- Métricas downstream funcionam para os 240k issues que TÊM dados frescos
- Issues "missing" são do BG long-tail (issues antigas, raramente updated). Quando alguém edita uma delas no Jira, watermark incremental pega e corrige.
- Coverage cresce naturalmente ao longo do tempo via incremental sync.

### Acceptance Criteria

```
Given a Jira project with > 100k issues
 When sync_worker runs full backfill (since=2020)
 Then either:
   (a) all >99% issues are fetched and persisted, OR
   (b) a clear WARN log + pipeline_event identifies the under-fetch,
       AND the next cycle automatically retries the missing window

Given the date-chunking workaround is implemented
 When backfill runs on BG (197k issues)
 Then items_done >= 197000 (within 1% of items_estimate)
  AND total cycle duration < 90 min
  AND no batches lost or duplicated (idempotent upserts)
```

### Anti-surveillance check
PASS — investigation operates on ingestion mechanics, no individual data exposure.

### Estimate
**S (1 day)** — investigation steps 1-3 + chunking workaround if cap confirmed.

### Dependencies
- FDD-OPS-014 (per-scope watermarks) — already shipped, supports per-project chunking
- FDD-OPS-015 (per-scope progress) — already shipped, useful for monitoring chunked runs

### Notas
- **Não bloqueia R1** — coverage atual de 54% é suficiente para PoC e demos com Webmotors. Críticio para enterprise tenants com projetos >100k.
- Pode ser **resolvido inteiramente client-side** (date chunking) sem mudanças no backend Jira ou em outro source.
- Caso similar pode ocorrer em GitHub (org com >100k PRs) — mas hoje a `count_prs_for_repo` é per-repo, então o cap por-query não é dominante. Só vira problema se um único repo passar de 100k PRs.

---

## FDD-DEV-METRICS-001 · Codename "dev-metrics" — proprietary estimation & forecasting model

**Epic:** Product Differentiation · **Release:** R3+ (codename "dev-metrics")
**Priority:** **P3** (large-scope, visionary) · **Persona:** Eng Manager + Squad Lead
**Owner class:** `pulse-product-director` + `pulse-data-scientist` + `pulse-engineer`
**Status:** PLANNED — capture only, do not start

> **Marcador estratégico**: este FDD reserva o espaço no backlog do projeto
> codinome **"dev-metrics"**, que vai reescrever completamente a UX/UI do
> PULSE adicionando dezenas de features proprietárias e únicas na indústria.
> Documentação completa virá no próprio release plan do "dev-metrics" — esta
> entrada apenas garante que o tema **não se perde** entre R1 e R3.

### Por que existe este card

Hoje (R1) usamos uma cadeia de fallback **automática e implícita** para
extrair effort estimation (FDD-OPS-016). Isso resolve o problema imediato
mas **assume convenções** (Fibonacci scale, hours-bucket mapping). Squads
diferentes têm filosofias diferentes:

- "Story Points são nosso golden standard"
- "Horas são mais honestas"
- "Tamanho de camisa só é útil pra refinement, não pra forecast"
- "Não estimamos. Throughput by item é nosso único KPI"

Cada filosofia gera métricas diferentes. Hoje somos opinionados;
amanhã queremos ser **configuráveis** por squad e ainda **proativos**:
sugerir ao squad qual método cabe melhor com base no histórico real.

### Visão (R3 — projeto "dev-metrics")

1. **Per-squad estimation method** (admin UI):
   - Squad escolhe: SP nativo, T-shirt, Hours, Count-only, ou "Auto"
   - PULSE respeita a escolha em **toda** a métrica (velocity, forecast,
     CFD por effort, scatterplot)
   - Auto-mode: usa fallback chain atual + telemetria

2. **Modelo proprietário de previsão e insights** (vantagem competitiva):
   - Identifica drift de estimativa (squad marcando tudo como "M" há
     6 sprints)
   - Calibra automaticamente: "Vocês marcaram esse card como P, mas
     histórico de issues do tipo 'bug' com label 'auth' nesta squad
     teve 73% de chance de virar G/GG"
   - Insight de método: "73% das squads kanban-puras como vocês têm
     throughput estável; vocês não — possível causa: variabilidade no
     refinement"
   - Forecast com Monte Carlo usando o método nativo do squad
   - **Anti-surveillance**: insights são sobre o squad/processo,
     **nunca** sobre indivíduos

3. **UX completa rescritia**:
   - Dashboard reescrito ao redor do método escolhido
   - Painel "estimation health" novo
   - Drill-down comparativo: "como seria sua velocity se vocês tivessem
     adotado method X há 3 sprints?"

### Diferenciador

Concorrentes (LinearB, Jellyfish, Swarmia, Athenian) hoje são opinionados
em SP. PULSE será o **único** que respeita filosofia da squad e usa
isso como entrada de modelo, não como ruído a ser normalizado.

### Pré-requisitos (capturar agora)

Quando "dev-metrics" começar:
1. **`effort_source`** já estar em `eng_issues` (next step do
   FDD-OPS-016) — sem isso, modelo proprietário não tem feature de método
2. **Histórico estatístico** mínimo de ~6 sprints por squad (ou ~30
   ciclos de Cycle Time pra Kanban) — bootstrap funciona em paralelo
3. **Multi-tenant scope_key** (FDD-OPS-014) — consolidado, OK
4. **Anti-surveillance review** rigoroso — modelo NÃO pode personalizar
   por indivíduo, só por squad/repo

### Lembrete operacional (CRÍTICO)

**Não esquecer ao chegar em R2/R3.** Este FDD existe especificamente
para resgatar o tema. Reviewer de release plan deve checar:
- ✅ FDD-DEV-METRICS-001 ainda apontado no roadmap?
- ✅ `effort_source` adicionado antes do R3 começar?
- ✅ Telemetria do fallback chain ainda gerando dados utilizáveis?

### Anti-surveillance check
PASS by design — modelo opera em agregado por squad/issue-type, nunca
por pessoa. Precisa review formal do CISO antes do release.

### Estimate
**XL (multi-sprint, R3)** — escopo de release inteiro, não card único.

### Dependencies
- FDD-OPS-016 (effort fallback chain) — base hoje
- FDD-OPS-014 (per-scope) — entregue
- Future migration: adicionar coluna `effort_source` em `eng_issues`

---


## FDD-OPS-020 · Jira API token expired — blocking issue resync (INC-006 rollout)

**Epic:** Operational Reliability · **Release:** Imediato (R1 enabler)
**Priority:** **P0** (bloqueia INC-006 + INC-022/INC-023 backfills + qualquer
re-sync de Jira)
**Owner class:** Ops / Platform admin (não-código)
**Discovered:** 2026-05-04 durante INC-006 (PR #15) operational rollout

### Sintoma

Sync-worker chama `/rest/api/3/search/jql` por projeto, recebe `200 OK` mas
com `issues=[]` mesmo quando `since=2020-01-01`. Confirmado:

```
POST /rest/api/3/search/jql
  body: {"jql": "project = \"FID\"", "maxResults": 5}
  response: {"issues": [], "isLast": true}

POST /rest/api/3/search/approximate-count
  body: {"jql": "project = FID"}
  response: {"count": 0}

GET /rest/api/3/myself
  response: 401 Unauthorized

GET /rest/api/3/issue/FID-1
  response: 404 Not Found
```

`/myself` 401 confirma: o `JIRA_API_TOKEN` em `pulse/.env` está expirado
ou foi revogado. As chamadas autenticadas voltam vazias em vez de 401
porque o `/search/jql` é mais tolerante que `/myself` na resposta de
auth-fail.

### Impacto

- INC-006: rollout bloqueado. `eng_issues.sprint_transitions` permanece
  `[]` em 311.667 issues. `POST /admin/sprints/refresh-scope` retorna
  `sprints_skipped=217` (todos pulados — sem dados pra processar).
- Bug retrofit em backfills de status_transitions / story_points /
  description também ficam pausados.
- PRs e Jenkins continuam syncando (tokens separados, ainda válidos).

### Solução (operator action — Claude NÃO toca credenciais)

1. Rotacionar token na Jira:
   - https://id.atlassian.com/manage-profile/security/api-tokens
   - "Create API token" → label `pulse-data-{date}`
   - Copiar token (só aparece uma vez)
2. Editar `pulse/.env` localmente (NÃO colar no chat):
   ```
   JIRA_API_TOKEN=<novo-token>
   ```
3. Validar: `make rotate-secrets && make check-secrets`
4. `docker compose restart sync-worker pulse-data discovery-worker`
5. Smoke via diagnostic (sem expor o token):
   ```bash
   docker compose exec -T pulse-data python -c "
   import asyncio
   from src.connectors.jira_connector import JiraConnector, REST_API
   async def t():
       c = JiraConnector()
       try:
           m = await c._client.get(f'{REST_API}/myself')
           print('auth ok:', m.get('displayName',[:30])
       finally: await c.close()
   asyncio.run(t())
   "
   ```
6. Reset watermarks dos projetos com sprint:
   ```sql
   UPDATE pipeline_watermarks SET last_synced_at='2020-01-01 00:00+00'
   WHERE entity_type='issues';
   ```
7. Aguardar sync (~horas dependendo de volume — ~311k issues)
8. Rodar admin endpoint:
   ```
   POST /data/v1/admin/sprints/refresh-scope?scope=all&planning_grace_days=1
   ```

### Acceptance Criteria

```
Given the new token is active
 When sync-worker fetches issues for any project
 Then GET /search/jql returns issues > 0 (where they exist)

Given sync completes for FID + PTURB
 When the admin endpoint runs scope=all
 Then sprints_updated > 0
  And eng_sprints.added_items / removed_items reflect Jira changelog history
  And the Sprint Comparison page shows real Scope Creep numbers
```

### Riscos de não fazer

- Sprint Comparison page continua mostrando "Added (Scope Creep) 0 (0%)"
- Outros backfills históricos pendentes ficam parados
- Ingestão Jira congelada — qualquer issue criada/atualizada não chega ao DB

### Estimate

XS (operator only) — 5 min de rotação + horas de re-sync background.

### Dependencies

- Acesso ao painel Atlassian (id.atlassian.com)
- `pulse/.env` writable

### Notas

- INC-006 PR #15 está mergeado e validado por:
  - 28 unit tests
  - Synthetic data smoke: Sprint 144 com 4 transitions injetados →
    classificou exatamente como esperado (3 committed, 1 added, 1 removed)
- Quando o token rotacionar, o backfill é uma chamada curl — sem código novo.

---

## FDD-OBS-001-RISK-1 · Master encryption key blast radius (R4 KMS migration)

**Epic:** Observability integration · **Release:** R4 (trigger-driven)
**Priority:** P2 (deferred — accepted for R2-R3) · **Owner class:** `pulse-ciso` + `pulse-data-engineer`
**Source:** ADR-021 (per-tenant credentials)

### Problem

ADR-021 stores Datadog/NR credentials in Postgres with `pgcrypto` encryption,
master key in `PULSE_OBS_MASTER_KEY` env var. Compromise of the env var =
all tenants' observability credentials decryptable. Same risk profile as
`INTERNAL_API_TOKEN` today, **accepted while we're a single deployment unit**.

### Trigger conditions to migrate

Migrate to **AWS Secrets Manager** (or KMS-backed key) when ANY:

1. First regulated tenant onboards (HIPAA / PCI / SOC2 explicit requirement).
2. Tenant count exceeds 500 (operational rotation toil > $0.40/mo/tenant Secrets Manager cost).
3. CISO escalation about master-key blast radius (separate FDD).

### Migration plan (when triggered)

- Schema becomes `tenant_observability_credentials_secret_arn` (TEXT) replacing encrypted columns.
- Provider abstraction layer (ADR-023) hides the change from connectors.
- Pure data move — no business logic changes.

### Estimate

S — schema migration + secret backfill + connector rewire (~2 days).

---

## FDD-OBS-001-RISK-2 · Service Ownership data quality

**Epic:** Observability integration · **Release:** R2 (mitigation in MVP)
**Priority:** P0 (blocks MVP usefulness) · **Owner class:** `pulse-product-director` + `pulse-engineer`
**Source:** ADR-022 (ownership inference)

### Problem

If tenant doesn't tag services in Datadog (no `service.owner` / `team`),
the Service Ownership Map and ALL downstream Squad Reliability metrics
become useless. Real-world data: ~30% of services typically lack tags.

### Mitigation (R2)

1. **Onboarding flow**: when tenant connects Datadog, run inference + show
   Service Ownership Map FIRST. Block other Signals views until coverage > 50%.
2. **Heuristic Tier-2** (repo↔service intersection from PR titles) catches
   ~60% of unmapped services automatically.
3. **Bulk confirm action** in admin UI: "Confirm all heuristic-mapped" button
   promotes Tier-2 inferences to overrides in 1 click.
4. **Coverage % visible permanently** in `/settings/integrations/observability`
   so admin sees what's degraded.

### Acceptance Criteria

- [ ] After 30-day onboarding, average tenant has ≥80% service ownership coverage.
- [ ] Tenants with <50% coverage see contextual nudge in every Signals view.

### Estimate

M (already designed in ADR-022) — implementation lives within FDD-OBS-001 R2 scope.

---

## FDD-OBS-001-RISK-3 · Cost surprise from Datadog API consumption

**Epic:** Observability integration · **Release:** R2 (mitigation built into MVP)
**Priority:** P1 · **Owner class:** `pulse-engineer` + `pulse-data-engineer`
**Source:** ADR-024 (cache strategy)

### Problem

PULSE polls Datadog API on tenant's behalf. If naive, can spike DD billing
($0.05-$0.10 per indexed log query for some plans). Tenant may not realize
PULSE is consuming their org-level quota.

### Mitigation (R2)

1. **Hard cap**: rollup worker token-bucket per tenant (250 req/hr soft, 300/hr DD limit).
2. **Conservative defaults**: 5min granularity, 7-day window for ad-hoc drill-downs.
3. **Tenant-facing transparency**: `/settings/integrations/observability` shows
   "API calls today: X / 300 (Y%)" with explanatory tooltip.
4. **Power-user knob**: longer window queries possible but with explicit warning.

### Acceptance Criteria

- [ ] No tenant exceeds DD's 300 req/hr cap (soft alert at 80%, hard cap at 95%).
- [ ] Admin UI shows current consumption vs cap, refreshing every 60s.

### Estimate

S — covered in ADR-024 implementation.

---

## FDD-OBS-001-RISK-4 · Tenant tier disparity (DD Pro vs Enterprise)

**Epic:** Observability integration · **Release:** R2 (defensive, partial mitigation)
**Priority:** P1 · **Owner class:** `pulse-engineer`
**Source:** Product director risk inventory (FDD-OBS-001 §8)

### Problem

Datadog's free/Pro plan **does not expose Events API** or has limited
Service Catalog access. PULSE features may degrade silently for tenants on
lower DD tiers. New Relic similar (Standard tier has limited NRQL retention).

### Mitigation (R2)

1. **Capability detection** at validation time: PULSE attempts a minimal
   probe of each required API. Records which features the tenant's plan supports.
2. **Honest empty states** (per ADR-026 Principle 4): UI explicitly shows
   "Seu plano Datadog Standard não expõe Events API. Faça upgrade ou
   conecte alternative para Deploy Health Timeline."
3. **Feature flags per-tenant** based on detected capabilities — never
   silent failures.

### Acceptance Criteria

- [ ] Onboarding flow detects DD plan tier within 30s.
- [ ] Per-feature capability matrix visible in admin UI.
- [ ] No 5xx errors for unsupported plan tier — only graceful empty states.

### Estimate

M — capability probe + matrix + UI states.

---

## FDD-OBS-001-RISK-5 · Spurious correlation (deploy ↔ error spike)

**Epic:** Observability integration · **Release:** R2 (mathematical guards in MVP)
**Priority:** P1 (correctness blocker) · **Owner class:** `pulse-data-scientist`
**Source:** Data scientist analysis §4.1

### Problem

A deploy can correlate with an error spike that has nothing to do with the
deploy (concurrent deploy on dependency, traffic surge, external upstream).
If our enhanced metrics treat all coincidences as causation, we'll publish
false positives that destroy trust ("PULSE blamed my deploy for an outage
that was AWS!").

### Mitigation (R2)

1. **Causal window**: only consider error spikes within `[-2min, +30min]` of
   deploy. Spikes outside window → `not_attributable`.
2. **Concurrent deploy filter**: if ≥2 deploys hit the same service or
   dependent services within 15min, mark `ambiguous_causation = true` and
   exclude from CFR Enhanced + DCS calculation. Log the reason.
3. **Baseline comparison**: compare error rate post-deploy with **same
   day-of-week + hour-of-day** in last 7 days, not raw value. Normalizes
   sazonalidade.
4. **Always show method**: response includes `causation_method` field so
   UI can render "± confidence" in tooltip.

### Acceptance Criteria

- [ ] No deploy attributed to spike >30min later.
- [ ] CFR Enhanced excludes `ambiguous_causation = true` cases.
- [ ] Unit tests cover: no spike, spike attributable, spike outside window,
      concurrent deploy, baseline comparison.

### Estimate

M — already designed in data scientist's spec, ~2 days implementation.

---

## FDD-OBS-001-RISK-6 · Vendor concentration risk for R3 prioritization

**Epic:** Observability integration · **Release:** Post-R2 GA (validation gate moved)
**Priority:** P1 (gates R3 planning, no longer R2) · **Owner class:** `pulse-product-director`
**Source:** Product director risk inventory (FDD-OBS-001 §8)
**Decision (2026-05-06):** User chose **option C** — validate
post-implementation with real R2 tenants. Discovery moved from pre-R2
to post-R2 GA.

### Problem

If 60%+ of design partners are Datadog-only, R3 (New Relic) connector
becomes lower priority than expected, and we may delay committed customers.
Conversely, if NR adoption is higher than estimated, we may have shipped
DD-first wastefully.

### Trade-off accepted (option C)

We ship R2 with DD-first assumption locked based on market data
(DD ~60% LatAm enterprise share) and Webmotors as DD-confirmed anchor
partner — instead of running 5 discovery interviews upfront. **Risk
accepted:** if real tenant mix is unexpectedly NR-heavy, R3 start
delays by weeks. **Justified by:** faster R2 ship + ADR-023 abstraction
makes NR adapter a 1-file (~600 LoC) lift the day we decide.

### Mitigation (during R2 dev, no upfront discovery)

1. **Webmotors anchor partner** (DD-confirmed) de-risks the R2 path.
2. **ADR-023 abstraction** designed so adding NR is a 1-file lift,
   not a refactor. R3 can kick off the day post-R2 validation lands.
3. **Intent-capture telemetry** on `/settings/integrations/observability`:
   drop-down "I plan to connect: [Datadog | New Relic | Grafana | Other]"
   captured BEFORE the actual connect step. Gives us a quick mix signal
   from real users without upfront interviews.

### Acceptance Criteria (post-R2 GA)

- [ ] R2 ships with DD only.
- [ ] First 5 paying tenants interviewed within 30 days of GA
      (5 × 30min, mix questions about provider, tagging, services).
- [ ] If ≥3 NR-only / NR-primary tenants → R3 NR connector starts immediately.
- [ ] If ≥3 Grafana-primary → R4 Grafana connector elevated to R3.
- [ ] If DD-dominant (≥4 of 5) → confirm R3 NR ship target unchanged.

### Estimate

XS for ops (5 × 30min post-R2 interviews); R3 NR connector estimate
lives in its own future FDD card.

---

## FDD-OBS-001-RISK-7 · Layer 2 PII trigger uses `?` operator (top-level JSONB only)

**Epic:** Observability integration · **Release:** Pre-R2 GA (must fix)
**Priority:** P1 (CISO H-002 finding) · **Owner class:** `pulse-data-engineer`
**Source:** `docs/security-reviews/FDD-OBS-001-foundation-review.md` §H-002

### Problem

`obs_no_pii_in_metadata()` in migration 018 uses `NEW.metadata ? k`,
which checks **top-level JSONB keys only**. Nested PII bypasses Layer 2:

```sql
-- silently passes the trigger:
INSERT INTO service_squad_ownership (... metadata) VALUES
  (..., '{"attributes": {"user.email": "x"}}');
```

Layer 1 (`strip_pii`) and Layer 4 (CI lint) compensate **today**, but
the DB layer should be the last line of defense — not bypassable.

### Proposed fix (migration 020)

Replace scalar `?` with `jsonb_path_exists` + recursive jsonpath:

```sql
IF jsonb_path_exists(NEW.metadata, ('$..**.' || k)::jsonpath) THEN
    RAISE EXCEPTION 'PII key % blocked in obs metadata (ADR-025 L2)', k;
END IF;
```

Available since Postgres 12+. Add migration unit test exercising
`{"attributes":{"user.email":"x"}}` to confirm it raises.

### Acceptance Criteria

- [ ] Migration 020 replaces trigger function body with recursive check.
- [ ] Test in `tests/integration/test_obs_pii_trigger.py` validates
      nested PII raises (synthetic INSERT in fixture).
- [ ] ADR-025 Layer 2 section updated to reflect the fix.

### Estimate

XS — single migration + integration test (~1h).

---

## FDD-OBS-001-RISK-8 · Master key rotation runbook

**Epic:** Observability integration · **Release:** Pre-PR 2 GA (must exist)
**Priority:** P1 (CISO H-001 follow-up) · **Owner class:** `pulse-ciso` + ops
**Source:** `docs/security-reviews/FDD-OBS-001-foundation-review.md` §H-001

### Problem

ADR-021 mentions "rotated manually pre-R4" but no runbook exists.
Without documented rotation procedure, a leaked `PULSE_OBS_MASTER_KEY`
has permanent retrospective impact on all encrypted credentials.

### Proposed fix (doc-only)

Write `docs/security-reviews/obs-master-key-rotation-runbook.md`
covering:

1. Generate new key via `openssl rand -base64 32`.
2. Set `PULSE_OBS_MASTER_KEY_NEW` env var alongside old key.
3. Re-encryption script: decrypt with old, re-encrypt with new, single
   transaction per tenant.
4. Swap env var (delete old, promote new).
5. Verify with test tenant credential.
6. Audit: log old/new key fingerprints (sha256[:8]) for rotation history.

Pre-conditions:
- H-001 validator already in place (✅ shipped in this PR).
- Re-encryption script in `pulse/scripts/rotate_obs_master_key.py`.

### Acceptance Criteria

- [ ] Runbook committed.
- [ ] Re-encryption script committed + has dry-run mode.
- [ ] Smoke test rotates 1 test-tenant credential locally.

### Estimate

S — runbook (~1h) + script (~3h) + smoke test (~1h).

---

## FDD-OBS-001-RISK-9 · Other deferred CISO findings (M-001..M-006, L-001..L-005)

**Epic:** Observability integration · **Release:** Pre-PR 2 / R2 GA
**Priority:** P1-P2 (CISO Medium/Low findings) · **Owner class:** mixed
**Source:** `docs/security-reviews/FDD-OBS-001-foundation-review.md`

Bundled here so each item has a tracked acceptance gate. Severity in
parens; PR # in which they must be addressed.

### Pre-PR 2 must-fix

- **M-001 (PR 2)**: `strip_pii` Unicode look-alikes + dotted-key
  nesting (`{"usr": {"email": ...}}`). Extend `FORBIDDEN_PARENT_CHILD_PAIRS`
  + add test case before Datadog adapter ships.
- **M-005 (PR 2)**: `key_fingerprint` truncation 16 → 32 hex chars
  (one-liner in `CredentialService`).
- **L-003 (PR 2)**: `site` column SSRF — CHECK constraint restricting
  to known DD site domains + DTO validation. **HARD blocker for PR 2**.
- **L-004 (PR 2)**: `mock_observability_provider` — replace `MagicMock`
  with `create_autospec(ObservabilityProvider, instance=True)` for
  test fidelity.

### Pre-PR 4 must-fix

- **M-003 (PR 4)**: `capability_detection` queries — add
  `SET LOCAL statement_timeout = '2000'` to bound latency.
- **M-006 (R2 GA)**: `obs_metric_snapshots` retention policy —
  partition by `hour_bucket` or time-based cleanup proc.

### R1 follow-up

- **M-002**: Add PII trigger to `tenant_feature_flags.metadata` (or
  document explicit operator-only policy).
- **M-004**: `set_flag()` RBAC — comment in shared module + route
  guard at API layer.
- **L-005**: Audit log on feature flag changes (Kafka event or audit
  table).

### MVP-acceptable (document only)

- **L-001**: CI lint regex misses `r"..."` / `b"..."` prefix strings.
  Document limitation in `test_obs_anti_surveillance.py`.
- **I-005 inverse**: Add cross-validation test that every Layer 1
  forbidden key is in Layer 4 scan.

### Estimate

Bundled — total ~2 days spread across PR 2 / PR 4 / R1.


## FDD-OBS-001-RISK-10 · Deferred CISO findings from PR 2 review

**Epic:** Observability integration · **Release:** PR 4 / R1
**Priority:** P1-P2 · **Source:** `docs/security-reviews/FDD-OBS-001-pr2-datadog-review.md`

Items the CISO reviewer flagged in the PR 2 (Datadog connector) review
that are **not** must-fix-pre-merge but must close before R2 GA or R1
SaaS rollout. H-001 (sqlalchemy_echo isolation) was resolved in PR 2
itself.

### Pre-PR 4 must-fix

- **M-001 (PR 4)**: `provider` path parameter on
  `GET /admin/integrations/{provider}/metadata` is an unvalidated
  `str` (`routes.py:174`). Tighten to `Literal["datadog", "newrelic"]`
  before multi-provider GA so FastAPI rejects unknown values with 422
  instead of letting them flow into the 404 detail string.
- **M-002 (PR 4)**: DSL injection guard for `query_metric` — when the
  rollup worker starts calling Datadog's metric query API, add a regex
  guard `^[a-zA-Z0-9_.\-]{1,200}$` on the `service` argument before
  `template.format(service=...)`. Empirically demonstrated:
  `checkout}{env:prod` silently expands the Datadog filter scope.
  Today's exposure is theoretical because `query_metric` has no HTTP
  surface; PR 4 (rollup worker) makes it reachable.

### R1 SaaS hardening

- **I-001**: No auth gate on admin endpoints. Soft-recommended pattern
  for PR 3: introduce a `Depends(require_admin)` stub that returns
  `True` in R0 so the injection point is wired without a refactor when
  R1 ships SSO. Aligns with the existing R0-debt (single tenant, no
  AuthN/AuthZ) across the rest of `pulse-data`.
- **I-002**: No rate limit on `/validate`. Brute-force exposure is
  theoretical without auth, but ship `slowapi` at 10 req/min per
  tenant alongside I-001 (rate limit without auth is theatre).
- **L-001**: `logger.exception(...)` in `routes.py:90` (defensive
  catch around `health_check`) could serialize provider locals in a
  pathological failure path. Switch to
  `logger.error(..., exc_info=False)` in R1.
- **L-002**: Fingerprint oracle — `key_fingerprint` is sha256[:32]
  exposed via metadata endpoint. Pre-image search against the 32-hex
  prefix is computationally infeasible for high-entropy keys, but
  documented for completeness. R1 hardening: derive fingerprint via
  HMAC(server_secret, api_key) so it can't be precomputed.
- **L-003**: Permissive `api_key` Pydantic validator (10–512 chars).
  Tighten to provider-specific regex once Datadog/NR schemas split
  (DD = `^[0-9a-f]{32}$`, NR = different).

### Estimate

PR 4 work: ~2h (M-001 + M-002).
R1 hardening: ~1d (auth gate + rate limit + audit polish).
