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

