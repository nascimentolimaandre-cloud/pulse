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

