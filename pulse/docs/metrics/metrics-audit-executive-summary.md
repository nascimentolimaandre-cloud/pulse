# PULSE Metrics Audit — Executive Summary

**Date:** 2026-04-16  
**Auditor:** pulse-data-scientist  
**Scope:** All 13 indicators computed and displayed by PULSE

---

## Os indicadores estao corretos?

**PARCIALMENTE. 5 de 13 indicadores OK como apresentados. 5 com erros P0 (numeros errados). 3 com P1 (numeros conservadores).**

| Indicador | Status | Nivel |
|-----------|--------|-------|
| Deploy Frequency | Formula correta, periodo pode estar errado (60d → mostra 90d) | P0 |
| Lead Time for Changes | Formula errada (proxy PR-open em vez de primeiro commit; usa merged_at nao deployed_at) | P0 |
| Change Failure Rate | Formula correta, sem filtro de ambiente | P1 |
| MTTR / Time to Restore | Sem dados — sempre null. DORA overall calculado com 3 de 4 metricas | P0 (documentado) |
| Cycle Time P50 | Formula correta, janela de dados errada (created_at, nao merged_at) | P0 |
| Cycle Time P85 | Idem | P0 |
| Cycle Time Breakdown | Deploy phase sempre null; 3 fases em vez de 4 | P1 |
| WIP | Formula correta | OK |
| Throughput | Contagem errada — usa PRs criados no periodo, nao PRs mergidos no periodo | P0 |
| CFD | Nao estritamente cumulativo; issues pre-periodo excluidas | P1 |
| Lead Time Distribution | Sample bias: exclui issues de ciclo longo | P1 |
| Scatterplot | Formula correta | OK |
| Sprint Overview | Scope creep sempre 0% (dado estruturalmente ausente) | P0 |
| Sprint Comparison | Velocity trend correto (nao normaliza duracao de sprint) | OK |

---

## Principais achados (3 de alto valor)

**1. O filtro de janela temporal esta errado para todos os indicadores baseados em PR e Issue.**  
Throughput, Lead Time e Cycle Time sao calculados com dados filtrados por `created_at` (quando o item abriu) em vez de `merged_at`/`completed_at` (quando o item fechou). Em equipes com ciclo de 5+ dias, um periodo de 7d mostrara zero items completados mesmo que a equipe tenha mergido trabalho. O bias piora para periodos curtos e equipes com ciclos mais longos. Este unico fix corrigi 4 indicadores simultaneamente.

**2. O periodo "60 dias" retorna dados de "90 dias".**  
O Metrics Worker so calcula snapshots para [7d, 14d, 30d, 90d]. Quando o usuario seleciona 60d ou 120d, a API retorna silenciosamente o snapshot de 90d. O header da pagina diz "60 dias" mas os calculos sao baseados em 90 dias. Isso invalida qualquer comparacao periodo-a-periodo feita pelo usuario com esses filtros.

**3. Scope Creep e sempre 0% — um dos indicadores de saude de sprint mais importantes esta estruturalmente quebrado.**  
O normalizador seta `added_items = 0` e `removed_items = 0` para todos os sprints. A formula de calculo esta correta, mas sem o dado de entrada, o output e sempre zero. Isso significa que o dashboard reporta zero mudanca de escopo em todos os sprints, o que e factualmente incorreto para qualquer equipe agil.

---

## Acoes imediatas sugeridas

O que bloqueia o uso do dashboard para tomar decisao real hoje:

1. **Fix INC-001 (P0 — 1 dia de `pulse-data-engineer`):** Alterar fetchers do Metrics Worker para usar `merged_at`/`completed_at` como filtro de janela em vez de `created_at`. Este e o fix de maior impacto.

2. **Fix INC-002 (P0 — 4 horas de `pulse-data-engineer`):** Adicionar periodos 60d e 120d ao `_PERIODS` do worker. Mudanca de 2 linhas.

3. **Fix INC-006 (P0 — 1-2 sprints de `pulse-data-engineer` + `pulse-engineer`):** Implementar tracking de mudancas de escopo mid-sprint (snapshot de issues por sprint no inicio vs. fim). Requer modelagem nova.

4. **Documentar os P1 ativos (imediato — documentacao):** Adicionar tooltips no dashboard indicando:
   - Lead Time usa PR open date como proxy do primeiro commit
   - MTTR aguardando pipeline de incidentes (FDD-DSH-050)
   - CFR inclui todos os ambientes (nao apenas producao)
   - Cycle Time Deploy phase sem dados (PR-to-deploy linking pendente)

---

## Prazo estimado para "gold standard"

| Fix | Agente | Esforco estimado |
|-----|--------|-----------------|
| INC-001 (filtro merged_at) | pulse-data-engineer | 1 dia |
| INC-002 (adicionar 60d/120d) | pulse-data-engineer | 4 horas |
| INC-003 (first commit real) | pulse-data-engineer + pulse-engineer | 3-5 dias (requer enrichment via GitHub API) |
| INC-004 (PR-to-deploy linking) | pulse-data-engineer + pulse-engineer | 5-8 dias |
| INC-005 (MTTR pipeline) | pulse-data-engineer | 2-3 sprints (novo bounded context) |
| INC-006 (scope creep tracking) | pulse-data-engineer | 3-5 dias |
| INC-007 (cycle_time no throughput) | pulse-data-engineer | 2 horas |
| INC-008 (filtro de ambiente) | pulse-data-engineer | 4 horas |
| INC-011 (WIP limit configuravel) | pulse-engineer | 1 dia (UI + API) |
| INC-012 (deploy phase) | dependente INC-004 | - |
| INC-013 (normalizar duracao sprint) | pulse-data-scientist + data-engineer | 2-3 dias |
| INC-014 (timezone CFD) | pulse-data-engineer | 2 horas |
| INC-015 (snapshots por equipe) | pulse-data-engineer | 2-3 dias |

**Total para P0s criticos (INC-001, 002, 006, 007, 008):** ~3-4 dias de engenharia  
**Total para gold standard completo:** ~8-10 semanas de trabalho

---

## Recomendacao: pode apresentar esses numeros para a lideranca hoje?

**SIM, com as seguintes qualificacoes obrigatorias:**

1. **Deploy Frequency e Change Failure Rate** podem ser apresentados como indicadores confiaveis de tendencia (formula correta), mas com a qualificacao de que incluem todos os ambientes (nao apenas producao) e que o periodo "60d" retorna dados de "90d".

2. **Lead Time for Changes** deve ser apresentado como "tempo de ciclo de PR" (PR opened → merged), nao como Lead Time DORA canonico. O numero subestima o Lead Time real porque nao inclui o tempo de desenvolvimento antes da abertura do PR.

3. **WIP** pode ser apresentado como numero correto (formula ok), mas com a nota de que e um agregado cross-squad e o threshold de classificacao (elite/high/medium/low) nao e calibrado para o tamanho da organizacao.

4. **Throughput** deve ser apresentado com cautela — o numero atual provavelmente subestima PRs mergidos para periodos curtos por causa do filtro `created_at`. Para periodos longos (90d), o erro e menor.

5. **Sprint Scope Creep = 0%** NAO deve ser apresentado — dado estruturalmente ausente. Omitir ou marcar explicitamente como "em breve".

6. **MTTR** esta corretamente sinalizado como indisponivel no dashboard. OK para apresentar como "roadmap R1".

**Recomendacao especifica:** Apresente deploy frequency, CFR e WIP como os indicadores mais confiaveis para a lideranca. Use Lead Time e Cycle Time como indicadores de tendencia relativa (e crescendo ou diminuindo?), nao como valores absolutos calibrados contra o DORA 2023.

---

*Arquivos de referencia:*  
- `pulse/docs/metrics/metrics-audit-2026-04-16.md` — Auditoria detalhada por indicador  
- `pulse/docs/metrics/metrics-inconsistencies.md` — Tabela de 19 inconsistencias com severidade  
- `pulse/docs/metrics/metrics-evidence-2026-04-16.md` — Queries SQL de ground truth  
- `pulse/packages/pulse-data/tests/unit/metrics/test_metrics_validation.py` — 60+ testes de mesa
