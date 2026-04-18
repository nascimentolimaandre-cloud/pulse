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

**Linha 3 — Snapshot contract monitor (P1, S)**

Pós-write, validar que o snapshot tem todos os campos **obrigatórios** do
schema Pydantic mais recente. Se faltar campo → log WARN + métrica Prometheus
`snapshot_schema_drift_total{metric_type, missing_field}`. Alerta em
Pipeline Monitor: "Snapshot desatualizado — worker precisa restart".

**Linha 4 — CI/CD force-restart on deploy (P0, S)**

Quando pipeline fizer deploy de código Python, o step de deploy **obrigatoriamente**
restarta todos os workers (`docker compose restart metrics-worker sync-worker
discovery-worker`). Sem exceção. Tempo de deploy aumenta ~15s, vale o seguro.

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
