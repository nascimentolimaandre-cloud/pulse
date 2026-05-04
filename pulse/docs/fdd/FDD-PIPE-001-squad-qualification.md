# FDD-PIPE-001 — Squad Qualification + Activity Tier

**Status:** ✅ Phase 1 shipped (2026-05-04)
**Owner:** `pulse-data-engineer` (heuristic) + `pulse-engineer` (UI)
**Stacked on:** PR #11 (FDD-DSH-050 MTTR Phase 1) — depends on migration `013` chain.

## 1. Problem

After ativar 60 projetos Jira (`/loop` plano `ethereal-doodling-sunbeam.md`), o
endpoint `/data/v1/pipeline/teams` passou a retornar **38 squads**, dos quais
~10 eram falsos positivos: nomes de projeto Jira **não-existentes**
extraídos por regex de PR titles (RC, CVE, REDIRECTS, RELEASE, RELASE,
AXIOS, USO, ANUN, APP, UTF). O combobox da home ficou poluído, pages com
visão por squad mostravam linhas vazias, e operadores não tinham
mecanismo de exclusão pontual quando a heurística errava.

## 2. Insight

A diferença entre falso positivo e squad real é **um único sinal**: os
falsos positivos têm `jira_project_catalog.name = ''` (porque a Jira API
nunca confirmou existência do projeto — discovery dinâmico criou a
linha mas o enrichment falhou). Squads reais com baixa atividade (CEU,
LPMKT, PAIN, AQ, PDSIG) têm `name` populado.

## 3. Goal

Filtrar **automaticamente** os falsos positivos sem hardcodar regras
específicas da Webmotors no código, **sem excluir** squads reais com
baixa atividade, e **dando ao operador** uma porta de saída quando a
heurística erra.

## 4. Design — duas dimensões ortogonais

### Q1 — Qualification (gate binário, exclui)

```
qualified = has_metadata AND has_any_activity
where
  has_metadata     = catalog.name IS NOT NULL AND name != ''
  has_any_activity = issue_count >= 1 OR pr_count_90d >= 1
```

`has_metadata` é o gate forte: filtra todos os falsos positivos por
construção, porque eles **só existem como discovery via regex**, sem
nunca terem batido com um projeto real na Jira API.

`has_any_activity` é generoso: 1 PR ou 1 issue já basta. A intenção é
**não confundir "squad sem atividade" com "squad excluso"** — o tier
classifica isso separadamente (§5).

### Q2 — Activity tier (rótulo, não exclui)

```
tier = 'active'   if pr_count_90d >= min_prs_90d_active_tier  (default 5)
tier = 'marginal' if 1 <= pr_count_90d < min_prs_90d_active_tier
tier = 'dormant'  if pr_count_90d == 0 AND issue_count >= 1
tier = 'marginal' (fallback)
```

O tier é **propagado para a UI** (badge + sort order no combobox), mas
nunca exclui da lista. Permite ao usuário ver squads marginais sem que
elas dominem a visualização.

### Override (operator escape hatch)

```
qualification_override IN ('qualified', 'excluded', NULL)
```

- `'qualified'` — força inclusão (ex.: squad real cujo `name` ainda não
  veio da Jira API por gap de sync).
- `'excluded'` — força exclusão (ex.: tribe-tag que casou com regex e o
  `name` veio populado por engano).
- `NULL` — heurística automática (default).

Override **vence** a heurística sempre. O `qualification_source` no
response (`'auto'` | `'override'`) deixa transparente para o usuário /
auditoria como cada squad qualificou.

## 5. Por que `name` é o gate suficiente (e não exigimos `issue_count >= 1`)

Originalmente propus `qualified = has_metadata AND issue_count >= 1`,
mas quem testou (André) detectou que squad CEU (real, name="PJ -
Cockpit e Universidade", 0 issues no PULSE) ficaria de fora.

`issue_count = 0` pode significar duas coisas indistinguíveis em SQL:

1. Squad genuinamente sem tickets (legítimo)
2. Squad com tickets mas que o PULSE ainda não sincronizou (gap de
   cobertura nosso, não do squad)

Filtrar por `issue_count` puniria o caso (2). Já o `name` é
**sempre** populado pela Jira API quando o projeto existe — não há
caso (2) ali. Por isso o gate único correto é `has_metadata + qualquer
sinal de vida`.

## 6. Configuração por tenant

Em `tenant_jira_config.squad_qualification_config` (JSONB):

```json
{
  "min_prs_90d_active_tier": 5,
  "include_data_only_squads": true,
  "qualification_requires_metadata": true,
  "qualification_requires_any_activity": true
}
```

Defaults (estritos) escolhidos para SaaS-ready. Tenants podem afrouxar
sem mudanças em código:

- `min_prs_90d_active_tier` — threshold para tier `active`. Tenants com
  squads de altíssimo volume podem aumentar; tenants menores podem
  baixar.
- `qualification_requires_metadata=false` — desativa o gate de Jira
  metadata (use com cuidado — readmite regex noise).
- `qualification_requires_any_activity=false` — admite projetos
  totalmente inativos (não recomendado).

## 7. Schema

### Migration `014_squad_qualification`

| Tabela | Coluna | Tipo | Default | Notas |
|--------|--------|------|---------|-------|
| `jira_project_catalog` | `qualification_override` | `VARCHAR(16)` | `NULL` | CHECK enforces valid set |
| `tenant_jira_config` | `squad_qualification_config` | `JSONB NOT NULL` | defaults acima | Per-tenant tunables |

CHECK constraint:
```sql
qualification_override IS NULL OR qualification_override IN ('qualified','excluded')
```

Sem ENUM (mesmo motivo de `incident_status` em FDD-DSH-050) — `VARCHAR(16) + CHECK` evolui sem migration heavyweight.

## 8. Pipeline

### `GET /data/v1/pipeline/teams`

Refatorado de `agg_rows = SELECT FROM eng_pull_requests` para um CTE
pipeline:

```
config        → lê tenant_jira_config.squad_qualification_config
pr_refs       → regex extract de PR titles (90d)
pr_aggregated → agrega por project_key
candidates    → LEFT JOIN catalog × pr_aggregated (admite squads
                  data-only — INC-015 em parte)
classified    → calcula has_metadata, has_activity, tier
SELECT        → resolve qualification (override → heuristic) + source
```

A query é executada **uma vez** por request, ~80ms para 80 catalog
rows. Sem caching adicional.

### `POST /data/v1/admin/squads/{key}/qualification`

X-Admin-Token, body `?override=qualified|excluded|null`. Retorna
`{previous_override, current_override}` para auditoria.

## 9. Frontend

### Combobox (TopBar `TeamCombobox`)

- **Sort:** active first, marginal/dormant after, all by descending PR
  count within tier.
- **Badge:** `Marginal` (amber chip) / `Dormante` (slate chip) ao lado
  do nome. Badge `active` é null (sem ruído).
- **Search:** agora também casa `squadKey` (não só `name`/`tribe`).

### Admin UI (DEFERRED — follow-up PR)

O endpoint `POST /admin/squads/{key}/qualification` está pronto e
testável via curl. A UI de toggle por linha em
`/settings/integrations/jira/projects` será implementada em PR
seguinte, juntamente com o proxy correspondente em pulse-api (NestJS
controller já tem o pattern em `jira-admin.controller.ts`).

Issue criado: ver `docs/backlog/ops-backlog.md` `FDD-PIPE-001-FOLLOWUP`.

## 10. Resultado live (Webmotors, 2026-05-03)

```
Antes: 38 squads (lixo: RC, CVE, REDIRECTS, RELEASE, RELASE, AXIOS, USO, ANUN, APP, UTF)
Depois: 28 squads (24 active + 4 marginal)
```

**24 active:** OKM (266 PRs), SDI (244), DESC (231), SECOM (204), PF (193),
ENO (193), SALES (130), DSP (96 — data-only ✅), BG (87), ANCR (85), CPA
(64), CRMC (62), CRW (61), CKP (56), PUSO (43), APPF (43), SEO (43), ESTQ
(37), FACIL (33), MONEY (25), PDSIG (22), APPJ (21), FID (21), INTG (16).

**4 marginal:** PAIN (4 PRs), CEU (2 ✅ — was the bug we fixed!), LPMKT
(1), AQ (1).

## 11. Tests

`pytest tests/unit/test_squad_qualification.py -q` → **18 passed**:

- `TestRealSquads` (5) — high-volume / low-volume / data-only / boundary
- `TestRegexNoise` (4) — RELEASE / CVE / AXIOS / whitespace-only
- `TestNoActivityCases` (1) — metadata + zero activity
- `TestOverrides` (3) — force-qualify / force-exclude / no override
- `TestConfigKnobs` (4) — lower / higher threshold + disable flags
- `TestDefaultConfig` (1) — defaults match migration 014 (SaaS contract)

Live admin smoke:
- `excluded` DSP → 27 squads, DSP some
- `qualified` USO (no metadata) → 28 squads, USO present with `qualification_source='override'`
- Clear both → 28 squads (back to baseline)

Full backend regression: **200/200 pass**.
Frontend: **163/163 pass**, tsc clean.

## 12. SaaS contract

✅ **Sem regras específicas Webmotors no código.** A heurística trabalha
com sinais genéricos (Jira name, issue_count, pr_count). Defaults
configuráveis por tenant via `tenant_jira_config`. Override per-squad
via `jira_project_catalog`. Heuristic Python reference em
`pipeline/services/squad_qualification.py` é a SSOT — SQL CTE em
`pipeline/routes.py` deve permanecer alinhada (parity verificada por
testes de boundary).

## 13. Files changed

| File | Change |
|------|--------|
| `alembic/versions/014_squad_qualification.py` | NEW migration |
| `src/contexts/pipeline/schemas.py` | TeamHealth + `tier` + `qualification_source` |
| `src/contexts/pipeline/routes.py` | `get_teams()` refactor + `squad_admin_router` |
| `src/contexts/pipeline/services/squad_qualification.py` | NEW Python reference impl |
| `src/main.py` | Mount squad_admin_router |
| `tests/unit/test_squad_qualification.py` | NEW 18 tests |
| `pulse-web/src/types/pipeline.ts` | TeamHealth + SquadTier + QualificationSource |
| `pulse-web/src/components/dashboard/TeamCombobox.tsx` | Sort by tier + tier badge |
| `docs/fdd/FDD-PIPE-001-squad-qualification.md` | This doc |
