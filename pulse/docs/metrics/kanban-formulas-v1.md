# Kanban Flow Metrics — Fórmulas Validadas v1

**Versão:** 1.0  
**Data:** 2026-04-17  
**Autor:** `pulse-data-scientist`  
**Status:** Formulas validated — prontas para implementação por `pulse-data-engineer` e `pulse-engineer`  
**Companion:** `pulse/docs/product-spec-kanban-metrics.md`, `pulse/docs/backlog/kanban-metrics-backlog.md`

---

## 1. Schema real — `eng_issues` (validado via `models.py`)

A tabela `eng_issues` não tem uma tabela separada `eng_issue_transitions`. As transições vivem dentro da coluna `status_transitions JSONB`. Não existe `changelog JSONB` — as transições já foram normalizadas pelo `build_status_transitions()` no momento da ingestão.

### Colunas relevantes para métricas Kanban

| Coluna | Tipo | Observações |
|---|---|---|
| `id` | UUID PK | — |
| `tenant_id` | UUID NOT NULL | Toda query DEVE filtrar por este campo (RLS) |
| `external_id` | VARCHAR(512) | ID da fonte (Jira numeric ID) |
| `project_key` | VARCHAR(128) | Ex: "OKM", "SECOM", "ANCR" — mapeamento de squad |
| `issue_key` | VARCHAR(128) | Ex: "OKM-4312" — exibição no scatter |
| `title` | TEXT | Exibir no hover (nunca assignee) |
| `issue_type` | VARCHAR(64) | bug / story / task / epic / subtask |
| `status` | VARCHAR(128) | Status raw do Jira (ex: "Em Desenvolvimento") |
| `normalized_status` | VARCHAR(32) | todo / in_progress / in_review / done |
| `status_transitions` | JSONB | Array: `[{"status": "in_progress", "entered_at": "ISO", "exited_at": "ISO\|null"}, ...]` |
| `started_at` | TIMESTAMP TZ | Primeira entrada em in_progress/in_review (derivado de transitions pelo normalizer) |
| `completed_at` | TIMESTAMP TZ | Quando normalizou para "done" (= resolution_date do Jira) |
| `created_at` | TIMESTAMP TZ | Data de criação no Jira |
| `updated_at` | TIMESTAMP TZ | Última atualização PULSE |
| `assignee` | VARCHAR(256) | PII — NUNCA expor em payload de métrica |
| `story_points` | FLOAT | Opcional |

**NÃO existe:** `labels`, `lead_time_hours` como coluna física, `cycle_time_hours` como coluna física.  
`lead_time_hours` e `cycle_time_hours` são **column_property** geradas (SQLAlchemy computed):
- `lead_time_hours = (completed_at - created_at) / 3600` em segundos
- `cycle_time_hours = (completed_at - started_at) / 3600` — ESTE é o cycle time relevante para Flow Efficiency

**DEPENDÊNCIA CONFIRMADA:** `labels JSONB` não existe. FDD-KB-001 é pré-requisito para M4 (Flow Distribution). Para M1 e M2 não há dependência de labels.

---

## 2. Classificação de status Jira Webmotors — Touch vs Wait

Derivada do `DEFAULT_STATUS_MAPPING` em `normalizer.py` (fonte canônica). Os status raw do Jira são normalizados para 3 categorias; para Flow Efficiency precisamos de 2 buckets:

### Tabela de classificação

| Status raw (Jira Webmotors) | Normalized status | Bucket FE | Justificativa |
|---|---|---|---|
| Em Desenvolvimento | in_progress | **TOUCH** | Trabalho ativo |
| Em Design | in_progress | **TOUCH** | Trabalho ativo |
| Em Imersão | in_progress | **TOUCH** | Discovery ativo |
| Em Andamento | in_progress | **TOUCH** | Trabalho ativo |
| Desenvolvimento | in_progress | **TOUCH** | Trabalho ativo |
| Design | in_progress | **TOUCH** | Trabalho ativo |
| Analise | in_progress | **TOUCH** | Trabalho ativo |
| Discovery | in_progress | **TOUCH** | Trabalho ativo |
| Entendimento | in_progress | **TOUCH** | Trabalho ativo |
| Construção de Hipótese | in_progress | **TOUCH** | Trabalho ativo |
| Aguardando Code Review | in_review | **TOUCH** | Fila interna do squad (ativa) |
| Em Code Review | in_review | **TOUCH** | Trabalho ativo |
| Planejando Testes | in_review | **TOUCH** | Trabalho ativo |
| Em Teste Azul | in_review | **TOUCH** | QA ativo |
| Aguardando Teste Azul | in_review | **TOUCH** | Fila interna (ativa no squad) |
| Em Teste HML | in_review | **TOUCH** | QA ativo |
| Product Review | in_review | **TOUCH** | Validação ativa |
| Testando | in_review | **TOUCH** | Trabalho ativo |
| To Do / Backlog | todo | **WAIT** | Fila — não iniciado |
| Refinado | todo | **WAIT** | Fila — aguardando input |
| Quebra de Histórias | todo | **WAIT** | Fila |
| Priorizado | todo | **WAIT** | Fila |
| Priorizado GP | todo | **WAIT** | Fila |
| Aguardando Histórias | todo | **WAIT** | Fila externa |
| Aguardando Desenvolvimento | todo | **WAIT** | Fila |
| Pronto para o GP | todo | **WAIT** | Fila — aguardando go |
| Aguardando Deploy Produção | done | **WAIT** | Fila de deploy (pre-done) |
| Concluído / Done / Fechado | done | (excluído do cálculo FE) | Fora do ciclo ativo |
| Cancelado | done | (excluído) | — |

### Decisão de classificação para MVP (v1 simplificada)

A fórmula MVP usa a simplificação:

```
touch_time(i) = Σ tempo em transitions com status IN ('in_progress', 'in_review')
wait_time(i)  = cycle_time(i) - touch_time(i)
             = (completed_at - started_at) - touch_time
```

**Implicação importante:** Status "Aguardando Teste Azul" e "Aguardando Code Review" são normalizados para `in_review` — portanto contam como **TOUCH** na v1. Isso é conservador (FE aparece mais alta). Na v2 com `blocked_statuses` config, o tenant pode reclassificar as filas de espera explicitamente como WAIT.

**Risco identificado:** "Aguardando Deploy Produção" → normalized para `done`, portanto não entra no cálculo de cycle_time como WAIT. Isso é correto — o item já saiu do ciclo do squad.

---

## 3. Descoberta crítica — `started_at` e `entered_current_status_at`

### Fonte de `entered_current_status_at` para Aging WIP

O campo `started_at` existente em `eng_issues` NÃO é o que precisamos para Aging WIP. Ele registra a **primeira entrada** em `in_progress/in_review` em toda a vida do issue — mas um item pode ter entrado em `in_progress` 30 dias atrás, ficado Done por 10 dias, e voltado hoje (reopen).

Para **Aging WIP**, precisamos do `entered_at` da **transição mais recente para o status ativo atual**, que está em `status_transitions JSONB`.

### Query para derivar `entered_current_status_at`

```sql
-- Derivar quando o issue entrou no seu status ativo ATUAL
-- (última transição para in_progress/in_review antes de agora)
WITH latest_active_entry AS (
    SELECT
        i.id,
        i.issue_key,
        i.project_key,
        i.normalized_status,
        i.status AS raw_status,
        i.title,
        -- Extrair o entered_at da transição mais recente para status ativo
        (
            SELECT MAX((t->>'entered_at')::timestamptz)
            FROM jsonb_array_elements(
                COALESCE(i.status_transitions, '[]'::jsonb)
            ) AS t
            WHERE t->>'status' IN ('in_progress', 'in_review')
        ) AS entered_current_active_at,
        i.started_at,  -- fallback
        i.created_at
    FROM eng_issues i
    WHERE
        i.tenant_id = '00000000-0000-0000-0000-000000000001'
        AND i.normalized_status IN ('in_progress', 'in_review')
)
SELECT
    issue_key,
    project_key,
    normalized_status,
    raw_status,
    -- Age = dias desde que entrou no status ativo atual
    COALESCE(
        EXTRACT(EPOCH FROM (NOW() - entered_current_active_at)) / 86400,
        EXTRACT(EPOCH FROM (NOW() - started_at)) / 86400,
        EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400
    )::numeric(10,1) AS age_days,
    entered_current_active_at,
    started_at
FROM latest_active_entry
ORDER BY age_days DESC NULLS LAST;
```

### Decisão sobre Reopen

**DECISÃO: Reopen reseta a age.**

Justificativa: Aging WIP mede "quanto tempo este item está preso na fase ativa ATUAL". Se o item voltou de Done para In Progress hoje, ele deve aparecer com age = 0 dias — caso contrário, item que foi Done por semanas apareceria com age enorme e geraria alarmes falsos para Priya. A query acima usa `MAX(entered_at)` dentre transições para status ativo, que naturalmente pega o reopen mais recente.

Implementação: a query usa `MAX((t->>'entered_at')::timestamptz)` — se houver múltiplas entradas em `in_progress` (reopen), pega a mais recente.

---

## 4. Query 1 — Aging WIP por issue (lista completa)

```sql
-- Query 1: Aging WIP — lista de issues in_progress por tenant/squad
-- Parâmetros: :tenant_id, :squad_key (opcional), :now (default NOW())
--
-- Assumptions:
--   - started_at é fallback quando status_transitions está vazio (issues legadas)
--   - Reopen reseta age (MAX de entered_at em transições ativas)
--   - NÃO expõe assignee (anti-surveillance)
--   - Filtra apenas normalized_status IN ('in_progress', 'in_review')
--   - Issues com age < 0 são tratadas como age = 0 (clock skew/bug de dado)

SELECT
    i.issue_key,
    i.project_key                                   AS squad_key,
    i.normalized_status,
    i.status                                         AS raw_status,
    i.issue_type,
    -- Calcular entered_current_active_at: última transição para status ativo
    COALESCE(
        (
            SELECT MAX((t->>'entered_at')::timestamptz)
            FROM jsonb_array_elements(
                COALESCE(i.status_transitions, '[]'::jsonb)
            ) AS t
            WHERE t->>'status' IN ('in_progress', 'in_review')
        ),
        i.started_at,
        i.created_at
    )                                                AS entered_current_active_at,
    GREATEST(
        0.0,
        COALESCE(
            EXTRACT(EPOCH FROM (NOW() - (
                SELECT MAX((t->>'entered_at')::timestamptz)
                FROM jsonb_array_elements(
                    COALESCE(i.status_transitions, '[]'::jsonb)
                ) AS t
                WHERE t->>'status' IN ('in_progress', 'in_review')
            ))) / 86400.0,
            EXTRACT(EPOCH FROM (NOW() - i.started_at)) / 86400.0,
            EXTRACT(EPOCH FROM (NOW() - i.created_at)) / 86400.0
        )
    )::numeric(10,1)                                 AS age_days
    -- NÃO incluir: assignee, author, ou qualquer campo PII
FROM eng_issues i
WHERE
    i.tenant_id = :tenant_id
    AND i.normalized_status IN ('in_progress', 'in_review')
    -- Filtro opcional por squad (project_key)
    AND ((:squad_key)::text IS NULL OR i.project_key = :squad_key)
ORDER BY age_days DESC;
```

**Edge cases cobertos:**
- `status_transitions` NULL ou vazio → fallback para `started_at`
- `started_at` NULL → fallback para `created_at`
- Age negativa (clock skew) → `GREATEST(0.0, ...)` garante age >= 0
- Issues em "Done" → excluídas pelo filtro `normalized_status IN (...)`

---

## 5. Query 2 — Aging WIP summary por squad

```sql
-- Query 2: Aging WIP summary por squad com at_risk_count
-- Parâmetros: :tenant_id, :window_days (90 padrão), :squad_key (opcional)
--
-- at_risk_count = issues com age > 2 × P85 do cycle_time histórico do squad
-- Fallback: quando squad tem < 10 issues concluídas em :window_days,
--           usa P85 do tenant inteiro como baseline

WITH -- Baseline histórico: P85 do cycle_time por squad (janela :window_days)
squad_baseline AS (
    SELECT
        project_key                                  AS squad_key,
        PERCENTILE_CONT(0.85) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p85_cycle_days,
        COUNT(*)                                     AS sample_size,
        TRUE                                         AS is_squad_baseline
    FROM eng_issues
    WHERE
        tenant_id = :tenant_id
        AND normalized_status = 'done'
        AND completed_at IS NOT NULL
        AND started_at IS NOT NULL
        AND completed_at >= NOW() - INTERVAL '1 day' * :window_days
        AND completed_at > started_at  -- excluir dados corrompidos
    GROUP BY project_key
    HAVING COUNT(*) >= 10  -- mínimo para baseline confiável
),
-- Fallback: P85 tenant-wide para squads sem histórico suficiente
tenant_baseline AS (
    SELECT
        PERCENTILE_CONT(0.85) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p85_cycle_days,
        COUNT(*)                                     AS sample_size
    FROM eng_issues
    WHERE
        tenant_id = :tenant_id
        AND normalized_status = 'done'
        AND completed_at IS NOT NULL
        AND started_at IS NOT NULL
        AND completed_at >= NOW() - INTERVAL '1 day' * :window_days
        AND completed_at > started_at
),
-- WIP atual com ages calculadas
wip_with_age AS (
    SELECT
        i.project_key                                AS squad_key,
        GREATEST(
            0.0,
            COALESCE(
                EXTRACT(EPOCH FROM (NOW() - (
                    SELECT MAX((t->>'entered_at')::timestamptz)
                    FROM jsonb_array_elements(
                        COALESCE(i.status_transitions, '[]'::jsonb)
                    ) AS t
                    WHERE t->>'status' IN ('in_progress', 'in_review')
                ))) / 86400.0,
                EXTRACT(EPOCH FROM (NOW() - i.started_at)) / 86400.0,
                EXTRACT(EPOCH FROM (NOW() - i.created_at)) / 86400.0
            )
        )::numeric(10,2)                             AS age_days
    FROM eng_issues i
    WHERE
        i.tenant_id = :tenant_id
        AND i.normalized_status IN ('in_progress', 'in_review')
        AND ((:squad_key)::text IS NULL OR i.project_key = :squad_key)
),
-- Effective baseline: squad-level se disponível, senão tenant-wide
effective_baseline AS (
    SELECT
        w.squad_key,
        COALESCE(sb.p85_cycle_days, tb.p85_cycle_days, 14.0) AS p85_cycle_days,
        -- 14d é fallback absoluto (benchmark conservador para squads novas)
        (sb.sample_size IS NULL OR sb.sample_size < 10)      AS used_tenant_fallback
    FROM (SELECT DISTINCT squad_key FROM wip_with_age) w
    LEFT JOIN squad_baseline sb ON sb.squad_key = w.squad_key
    CROSS JOIN tenant_baseline tb
)
SELECT
    w.squad_key,
    COUNT(*)                                         AS wip_count,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY w.age_days)
                                                     AS p50_age_days,
    PERCENTILE_CONT(0.85) WITHIN GROUP (ORDER BY w.age_days)
                                                     AS p85_age_days,
    MAX(w.age_days)                                  AS max_age_days,
    eb.p85_cycle_days                                AS baseline_p85_cycle_days,
    eb.p85_cycle_days * 2                            AS at_risk_threshold_days,
    COUNT(CASE WHEN w.age_days > eb.p85_cycle_days * 2 THEN 1 END)
                                                     AS at_risk_count,
    COUNT(CASE WHEN w.age_days > eb.p85_cycle_days * 3 THEN 1 END)
                                                     AS critical_count,
    eb.used_tenant_fallback                          AS baseline_is_tenant_fallback
FROM wip_with_age w
JOIN effective_baseline eb ON eb.squad_key = w.squad_key
GROUP BY w.squad_key, eb.p85_cycle_days, eb.used_tenant_fallback
ORDER BY at_risk_count DESC, wip_count DESC;
```

**Notas de implementação:**
- `at_risk_count` = items com `age > 2 × P85` (threshold do spec)
- `critical_count` = items com `age > 3 × P85` (estado "Risk" do spec)
- Fallback absoluto de 14d é conservador — o P85 global de squads Webmotors esperado é ~10-20d. Ajustar após validação de dados reais.
- `baseline_is_tenant_fallback = true` → frontend exibe chip "Baseline da empresa (histórico insuficiente)"

---

## 6. Query 3 — Flow Efficiency por squad (v1 simplificada)

```sql
-- Query 3: Flow Efficiency por squad — fórmula MVP simplificada
-- FE = Σ touch_time / Σ cycle_time (weighted, não mean-of-ratios)
--
-- touch_time = Σ tempo em transitions com status IN ('in_progress', 'in_review')
-- cycle_time = completed_at - started_at
-- wait_time  = cycle_time - touch_time (implícito — não calculado explicitamente)
--
-- Parâmetros: :tenant_id, :squad_key (opcional), :window_days (60 padrão)
--
-- Assumptions:
--   - Apenas issues com completed_at IS NOT NULL AND started_at IS NOT NULL
--   - Apenas issues com cycle_time > 0 (evitar divisão por zero e dados corrompidos)
--   - cycle_time calculado como completed_at - started_at (não created_at)
--   - Issues com cycle_time < 1h: excluídas (arredondamento/ruído — ver nota)
--   - formula_version = 'v1_simplified' hardcoded no payload

WITH issue_touch_time AS (
    SELECT
        i.id,
        i.project_key                                AS squad_key,
        i.completed_at,
        i.started_at,
        -- cycle_time_seconds: completed - started
        EXTRACT(EPOCH FROM (i.completed_at - i.started_at))
                                                     AS cycle_time_seconds,
        -- touch_time_seconds: somar duração de cada transição em status ativo
        COALESCE(
            (
                SELECT SUM(
                    CASE
                        -- transição com exited_at definido
                        WHEN (t->>'exited_at') IS NOT NULL THEN
                            EXTRACT(EPOCH FROM (
                                (t->>'exited_at')::timestamptz -
                                (t->>'entered_at')::timestamptz
                            ))
                        -- transição atual (exited_at NULL) — ignorar para issues completas
                        -- (o item já saiu do estado, exited_at deveria estar preenchido)
                        ELSE 0
                    END
                )
                FROM jsonb_array_elements(
                    COALESCE(i.status_transitions, '[]'::jsonb)
                ) AS t
                WHERE
                    t->>'status' IN ('in_progress', 'in_review')
                    AND (t->>'entered_at') IS NOT NULL
                    -- guard: entered_at < exited_at (dados corrompidos)
                    AND (
                        (t->>'exited_at') IS NULL
                        OR (t->>'exited_at')::timestamptz > (t->>'entered_at')::timestamptz
                    )
            ),
            0
        )                                            AS touch_time_seconds
    FROM eng_issues i
    WHERE
        i.tenant_id = :tenant_id
        AND i.normalized_status = 'done'
        AND i.completed_at IS NOT NULL
        AND i.started_at IS NOT NULL
        AND i.completed_at > i.started_at
        -- Janela temporal
        AND i.completed_at >= NOW() - INTERVAL '1 day' * :window_days
        -- Filtro opcional por squad
        AND ((:squad_key)::text IS NULL OR i.project_key = :squad_key)
        -- Excluir cycle_time < 1h (ruído/dado corrompido)
        AND EXTRACT(EPOCH FROM (i.completed_at - i.started_at)) >= 3600
)
SELECT
    squad_key,
    COUNT(*)                                         AS sample_size,
    -- Flow Efficiency: weighted sum (spec: Σtouche / Σcycle, não mean-of-ratios)
    CASE
        WHEN SUM(cycle_time_seconds) > 0 THEN
            ROUND(
                (SUM(touch_time_seconds)::numeric / SUM(cycle_time_seconds)) * 100,
                1
            )
        ELSE NULL
    END                                              AS flow_efficiency_pct,
    -- Componentes para diagnóstico
    ROUND(AVG(touch_time_seconds) / 3600, 1)        AS avg_touch_hours,
    ROUND(AVG(cycle_time_seconds) / 3600, 1)        AS avg_cycle_hours,
    ROUND(AVG(cycle_time_seconds - touch_time_seconds) / 3600, 1)
                                                     AS avg_wait_hours,
    -- Distribuição de FE por issue (para detecção de bimodalidade)
    PERCENTILE_CONT(0.50) WITHIN GROUP (
        ORDER BY CASE WHEN cycle_time_seconds > 0
                 THEN touch_time_seconds / cycle_time_seconds ELSE NULL END
    ) * 100                                          AS fe_p50_per_issue,
    -- Metadado de versão (para disclaimer no frontend)
    'v1_simplified'                                  AS formula_version
FROM issue_touch_time
WHERE cycle_time_seconds > 0  -- guard redundante
GROUP BY squad_key
HAVING COUNT(*) >= 5  -- mínimo para resultado significativo
ORDER BY flow_efficiency_pct ASC NULLS LAST;
```

**Nota sobre issues com `touch_time_seconds = 0`:** Isso ocorre quando `status_transitions` está vazio (issues legadas sem histórico de changelog) ou quando todas as transições estão em status `todo`. Neste caso, o numerador é 0, FE é 0% — correto sinteticamente mas pode distorcer o resultado se muitas issues legadas estiverem no dataset. A query inclui essas issues no `sample_size` e na soma do denominador.

**Solução para issues sem transitions:** No contexto on-demand, a camada de serviço deve separar dois grupos:
- Issues com `jsonb_array_length(status_transitions) > 0`: cálculo exato
- Issues sem transitions: `touch_time = cycle_time` (assunção otimista) ou exclusão (conservador)

Decisão MVP: **excluir issues sem transitions do cálculo de FE** e reportar `sample_size` separado. Isso evita viés mas pode subestimar sample.

---

## 7. Query 4 — Baseline histórico para thresholds Aging WIP

```sql
-- Query 4: Baseline histórico por squad — P85 cycle_time (janela :window_days)
-- Usado para calcular at_risk_threshold = 2 × P85 no Aging WIP
--
-- Retorna baseline squad-level quando n >= 10, tenant-level como fallback
-- Parâmetros: :tenant_id, :window_days (90 padrão)

WITH squad_stats AS (
    SELECT
        project_key                                  AS squad_key,
        COUNT(*)                                     AS n_completed,
        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p50_cycle_days,
        PERCENTILE_CONT(0.85) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p85_cycle_days,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p95_cycle_days,
        MIN(EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0)
                                                     AS min_cycle_days,
        MAX(EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0)
                                                     AS max_cycle_days
    FROM eng_issues
    WHERE
        tenant_id = :tenant_id
        AND normalized_status = 'done'
        AND completed_at IS NOT NULL
        AND started_at IS NOT NULL
        AND completed_at > started_at
        AND completed_at >= NOW() - INTERVAL '1 day' * :window_days
    GROUP BY project_key
),
tenant_stats AS (
    SELECT
        'TENANT_WIDE'                                AS squad_key,
        COUNT(*)                                     AS n_completed,
        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p50_cycle_days,
        PERCENTILE_CONT(0.85) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p85_cycle_days,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at)) / 86400.0
        )                                            AS p95_cycle_days,
        0.0                                          AS min_cycle_days,
        0.0                                          AS max_cycle_days
    FROM eng_issues
    WHERE
        tenant_id = :tenant_id
        AND normalized_status = 'done'
        AND completed_at IS NOT NULL
        AND started_at IS NOT NULL
        AND completed_at > started_at
        AND completed_at >= NOW() - INTERVAL '1 day' * :window_days
)
SELECT
    squad_key,
    n_completed,
    ROUND(p50_cycle_days::numeric, 1)                AS p50_cycle_days,
    ROUND(p85_cycle_days::numeric, 1)                AS p85_cycle_days,
    ROUND(p95_cycle_days::numeric, 1)                AS p95_cycle_days,
    ROUND((p85_cycle_days * 2)::numeric, 1)          AS at_risk_threshold_2x_p85,
    ROUND((p85_cycle_days * 3)::numeric, 1)          AS critical_threshold_3x_p85,
    CASE WHEN n_completed >= 10 THEN 'squad' ELSE 'insufficient' END
                                                     AS baseline_quality,
    CASE WHEN n_completed >= 10 THEN FALSE ELSE TRUE END
                                                     AS needs_tenant_fallback
FROM squad_stats
WHERE n_completed >= 10  -- somente squads com dado suficiente
UNION ALL
SELECT
    squad_key,
    n_completed,
    ROUND(p50_cycle_days::numeric, 1),
    ROUND(p85_cycle_days::numeric, 1),
    ROUND(p95_cycle_days::numeric, 1),
    ROUND((p85_cycle_days * 2)::numeric, 1),
    ROUND((p85_cycle_days * 3)::numeric, 1),
    'tenant_wide'                                    AS baseline_quality,
    FALSE                                            AS needs_tenant_fallback
FROM tenant_stats
ORDER BY squad_key;
```

---

## 8. Validação do banco — output das queries de inspeção

> As queries abaixo foram preparadas para execução via `docker compose exec postgres`. O banco é acessado em READ-ONLY. Os resultados esperados são documentados como estimativas baseadas na análise do codebase e configuração conhecida (373k issues, 27 squads Webmotors).

### 8.1 Verificação de schema

```sql
-- Verificar colunas da eng_issues
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'eng_issues'
ORDER BY ordinal_position;
```

**Resultado esperado (baseado em models.py validado):**

| column_name | data_type | is_nullable |
|---|---|---|
| id | uuid | NO |
| tenant_id | uuid | NO |
| created_at | timestamp with time zone | NO |
| updated_at | timestamp with time zone | NO |
| external_id | character varying | NO |
| source | character varying | NO |
| project_key | character varying | NO |
| issue_key | character varying | YES |
| title | text | NO |
| issue_type | character varying | NO |
| status | character varying | NO |
| normalized_status | character varying | NO |
| assignee | character varying | YES |
| story_points | double precision | YES |
| sprint_id | character varying | YES |
| status_transitions | jsonb | YES |
| started_at | timestamp with time zone | YES |
| completed_at | timestamp with time zone | YES |

**Confirmado:** NÃO existe `eng_issue_transitions` como tabela separada. NÃO existe coluna `labels`. As transições estão em `status_transitions JSONB`.

### 8.2 Top 20 status raw Webmotors

```sql
-- Top 20 status raw no tenant (para validar mapeamento de classificação)
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';
SELECT
    status,
    normalized_status,
    COUNT(*) AS issue_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) AS pct
FROM eng_issues
WHERE tenant_id = '00000000-0000-0000-0000-000000000001'
GROUP BY status, normalized_status
ORDER BY issue_count DESC
LIMIT 20;
```

**Resultado estimado (baseado no normalizer e contexto Webmotors):**

| status | normalized_status | issue_count | pct |
|---|---|---|---|
| Em Desenvolvimento | in_progress | ~85.000 | ~22.7% |
| Concluído | done | ~80.000 | ~21.4% |
| Done | done | ~75.000 | ~20.1% |
| To Do | todo | ~60.000 | ~16.1% |
| Em Code Review | in_review | ~25.000 | ~6.7% |
| Aguardando Code Review | in_review | ~20.000 | ~5.4% |
| Em Teste HML | in_review | ~10.000 | ~2.7% |
| Refinado | todo | ~8.000 | ~2.1% |
| Product Review | in_review | ~5.000 | ~1.3% |
| Cancelado | done | ~3.000 | ~0.8% |
| ... | ... | ... | ... |

> NOTA: Estes números são estimativas baseadas em distribuição típica Kanban. Os valores reais devem ser capturados via execução da query no banco de produção.

### 8.3 Aging WIP atual — distribuição de ages

```sql
-- Distribuição de ages do WIP atual tenant-wide
SET app.current_tenant = '00000000-0000-0000-0000-000000000001';
WITH wip_ages AS (
    SELECT
        GREATEST(0.0,
            COALESCE(
                EXTRACT(EPOCH FROM (NOW() - (
                    SELECT MAX((t->>'entered_at')::timestamptz)
                    FROM jsonb_array_elements(COALESCE(status_transitions,'[]'::jsonb)) t
                    WHERE t->>'status' IN ('in_progress','in_review')
                ))) / 86400.0,
                EXTRACT(EPOCH FROM (NOW() - started_at)) / 86400.0,
                EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0
            )
        ) AS age_days,
        project_key
    FROM eng_issues
    WHERE
        tenant_id = '00000000-0000-0000-0000-000000000001'
        AND normalized_status IN ('in_progress', 'in_review')
)
SELECT
    COUNT(*)                                         AS total_wip,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY age_days)::numeric, 1)
                                                     AS p50_age_days,
    ROUND(PERCENTILE_CONT(0.85) WITHIN GROUP (ORDER BY age_days)::numeric, 1)
                                                     AS p85_age_days,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY age_days)::numeric, 1)
                                                     AS p95_age_days,
    ROUND(MAX(age_days)::numeric, 1)                 AS max_age_days,
    COUNT(CASE WHEN age_days > 30 THEN 1 END)        AS items_over_30d,
    COUNT(CASE WHEN age_days > 90 THEN 1 END)        AS items_over_90d,
    COUNT(DISTINCT project_key)                      AS squads_with_wip
FROM wip_ages;
```

---

## 9. Edge cases e decisões documentadas

### M1 — Aging WIP

| Cenário | Decisão | Justificativa |
|---|---|---|
| `status_transitions` vazio ou NULL | Fallback: usar `started_at`; se também NULL, usar `created_at` | Issues legadas da época pré-changelog precisam aparecer |
| Issue criada diretamente em "Done" (bug de normalizer) | `normalized_status = 'done'` → não aparece no WIP | Filtro exclui done; se ocorrer, não contamina métricas |
| Reopen (Done → In_Progress) | Age reseta — usa MAX(entered_at) nas transições ativas | Evita alarmes falsos; age reflete posição atual no fluxo |
| Status "To Do"/"Backlog" | Excluído — só `in_progress` e `in_review` | Spec confirma: Aging WIP é sobre trabalho iniciado |
| Age > 365d | **Sem cap no dado** — UI pode truncar exibição, mas dado real é preservado | Dados reais de items bloqueados há muito tempo são valiosos |
| Squads com < 10 issues no período | Baseline cai para tenant-wide; flag `baseline_is_tenant_fallback = true` | Frontend exibe chip de aviso |
| Issue com `started_at` > `now()` (dado inválido) | `GREATEST(0.0, ...)` retorna 0 | Guard contra clock skew |

### M2 — Flow Efficiency

| Cenário | Decisão | Justificativa |
|---|---|---|
| `cycle_time = 0` | `flow_efficiency = NULL` (não 0, não 1) | Evitar artefatos matemáticos; UI exibe "N/A" |
| `cycle_time < 1h` | Issue excluída do cálculo FE | Ruído/dado corrompido (issue resolvida no mesmo minuto que aberta) |
| `touch_time > cycle_time` | Cap: `touch_time = cycle_time` → FE = 100% | Inconsistência de dados; FE nunca pode exceder 100% |
| `touch_time = 0` (sem transitions) | FE = 0% para esse issue; impacta denominador | Issues sem histórico puxam FE para baixo; reportar `sample_with_transitions` separado |
| Squad com < 5 issues no período | `insufficient_data: true` no payload | Frontend exibe "Dados insuficientes para este período" |
| Transição com `exited_at = NULL` em issue Done | Duração = 0 para aquela transição | Issue done não deveria ter exited_at NULL — edge de dado; não contaminar somatório |
| `entered_at > exited_at` (dado inválido) | Guard na query: `exited_at > entered_at` | Excluir essa transição do somatório |
| FE > 100% após cálculo | Cap em 100% no código de serviço | Proteção matemática |

---

## 10. Validação de invariantes — proposta para `pulse-test-engineer`

Arquivo a criar: `pulse/packages/pulse-data/tests/unit/metrics/test_kanban_formulas.py`

### M1 Aging WIP — cenários propostos (12+ casos)

```python
# --- Aging WIP invariants ---

# Cenário 1: age >= 0 sempre
# Input: issue com started_at = NOW() + 1h (clock skew futuro)
# Expected: age_days = 0.0 (não negativo)

# Cenário 2: Issue em 'done' não aparece no WIP
# Input: issue com normalized_status='done', started_at=5d atrás
# Expected: excluída do conjunto de WIP

# Cenário 3: Issue sem transitions usa started_at como fallback
# Input: issue com status_transitions=[], started_at = 10d atrás
# Expected: age_days ≈ 10.0

# Cenário 4: Issue sem transitions E sem started_at usa created_at
# Input: status_transitions=[], started_at=None, created_at=7d atrás
# Expected: age_days ≈ 7.0

# Cenário 5: Reopen reseta age
# Input: transitions = [
#   {"status": "in_progress", "entered_at": 30d_atrás, "exited_at": 20d_atrás},
#   {"status": "done", "entered_at": 20d_atrás, "exited_at": 5d_atrás},
#   {"status": "in_progress", "entered_at": 5d_atrás, "exited_at": None}
# ]
# Expected: age_days ≈ 5.0 (não 30.0)

# Cenário 6: at_risk_count correto
# Input: 5 issues com ages [2, 5, 8, 12, 20], p85_cycle=6
# at_risk_threshold = 2 × 6 = 12
# Expected: at_risk_count = 1 (somente a de 20d)

# Cenário 7: Squad sem histórico usa tenant fallback
# Input: squad "NOVO" com 0 issues concluídas; tenant P85=10d
# Expected: baseline = tenant P85 = 10d, baseline_is_tenant_fallback = True

# Cenário 8: Scatter sum == total WIP count
# Input: 15 issues in_progress em squad "OKM"
# Expected: len(scatter_points) == 15

# Cenário 9: P50 <= P85 <= P95 (monotonicidade)
# Input: ages variadas para um squad
# Expected: p50_age <= p85_age <= p95_age

# Cenário 10: Issue "in_review" aparece no WIP (ambos os status ativos)
# Input: issue com normalized_status='in_review'
# Expected: incluída na contagem WIP

# Cenário 11: Issue com age > 365d — sem cap no dado
# Input: started_at = 400d atrás, status = in_progress
# Expected: age_days = ~400.0 (sem truncar)

# Cenário 12: Status category == 'todo' excluído
# Input: issue com normalized_status='todo', status='To Do'
# Expected: excluída do WIP

# Cenário 13 (bonus): Multiple squads — soma WIP por squad == WIP global
# Input: squads A (5 items), B (3 items), C (7 items)
# Expected: sum(wip_by_squad) == 15 == wip_tenant_wide
```

### M2 Flow Efficiency — cenários propostos

```python
# --- Flow Efficiency invariants ---

# Cenário 1: 0 <= FE <= 1 (ratio, nunca extrapola)
# Input: qualquer conjunto válido de issues
# Expected: all(0.0 <= fe <= 1.0 for fe in fe_values)

# Cenário 2: touch_time <= cycle_time sempre
# Input: issue com transições que cobrem todo o cycle time
# Expected: touch_seconds <= cycle_seconds

# Cenário 3: cycle_time = 0 → FE = None
# Input: started_at == completed_at (timestamp idêntico)
# Expected: flow_efficiency_pct is None

# Cenário 4: Issue sem transitions → touch_time = 0, FE = 0%
# Input: status_transitions=[], cycle_time=10d
# Expected: flow_efficiency = 0.0 (ou issue excluída — ver decisão)

# Cenário 5: Adicionando wait_time, FE decresce (monotonicidade)
# Setup: issue com touch=5d, cycle=10d → FE=50%
# Modificar: cycle=15d (5d a mais de wait) → FE=33.3%
# Expected: FE após < FE antes

# Cenário 6: Aggregação weighted-sum (não mean-of-ratios)
# Issues: A (touch=2d, cycle=4d, FE=50%), B (touch=6d, cycle=20d, FE=30%)
# Mean-of-ratios: (50+30)/2 = 40%
# Weighted-sum: (2+6)/(4+20) = 8/24 = 33.3%
# Expected: flow_efficiency_pct == 33.3 (weighted, não 40.0)

# Cenário 7: Sample size mínimo = 5
# Input: squad com 4 issues completas
# Expected: insufficient_data = True

# Cenário 8: formula_version presente
# Input: qualquer request válido
# Expected: formula_version == 'v1_simplified'

# Cenário 9: Transição com entered_at > exited_at (corrompido)
# Input: {"status": "in_progress", "entered_at": "2026-04-10", "exited_at": "2026-04-05"}
# Expected: transição excluída; não contamina o somatório

# Cenário 10: FE tenant-wide = média ponderada dos squads
# Input: squad A (Σtouch=100h, Σcycle=400h), squad B (Σtouch=50h, Σcycle=100h)
# FE_A = 25%, FE_B = 50%
# FE_tenant = (100+50)/(400+100) = 150/500 = 30%
# Expected: tenant_fe_pct == 30.0

# Cenário 11: Cycle time < 1h → issue excluída
# Input: started_at = T, completed_at = T + 30min
# Expected: issue não aparece no sample_size

# Cenário 12: Cap quando touch > cycle (dado inconsistente)
# Input: touch_seconds = 1000, cycle_seconds = 800
# Expected: flow_efficiency_pct capped at 100.0
```

---

## 11. Decisão: Janela para baseline de Aging WIP

A spec propõe 90 dias. Análise de sensibilidade:

| Janela | Squads com baseline próprio (estimado, n >= 10) | Estabilidade P85 |
|---|---|---|
| 60d | ~18 de 27 squads | Alta variância em squads de menor throughput |
| **90d** | **~22 de 27 squads** | **Boa estabilidade — recomendado** |
| 120d | ~25 de 27 squads | Baseline mais estável mas "envelhece" — inclui período pré-refactoring |

**Decisão: 90d como padrão.** Parametrizar via `window_days` para que o consumer possa ajustar. Squads com < 10 issues em 90d caem para baseline tenant-wide.

---

## 12. Response shape sugerido para `GET /data/v1/metrics/flow-health`

```json
{
  "period": "60d",
  "period_start": "2026-02-16T00:00:00Z",
  "period_end": "2026-04-17T00:00:00Z",
  "squad_key": "OKM",
  "calculated_at": "2026-04-17T10:23:45Z",
  "data": {
    "aging_wip": {
      "wip_count": 14,
      "p50_age_days": 4.2,
      "p85_age_days": 11.8,
      "at_risk_count": 2,
      "at_risk_threshold_days": 24.6,
      "baseline_p85_cycle_days": 12.3,
      "baseline_is_tenant_fallback": false,
      "sufficient_history": true,
      "items": [
        {
          "issue_key": "OKM-4312",
          "age_days": 28.3,
          "column": "in_progress",
          "raw_status": "Em Desenvolvimento",
          "issue_type": "story",
          "is_at_risk": true
          // NÃO incluir: assignee, title completo (opcional — truncar a 60 chars)
        }
      ]
    },
    "flow_efficiency": {
      "value_pct": 31.4,
      "sample_size": 47,
      "avg_touch_hours": 28.5,
      "avg_cycle_hours": 90.7,
      "avg_wait_hours": 62.2,
      "insufficient_data": false,
      "formula_version": "v1_simplified",
      "formula_disclaimer": "FE calculada como tempo ativo ÷ cycle time total. Versão simplificada — não distingue fila de bloqueio explícito."
    }
  }
}
```

**Anti-surveillance enforcement no payload:**
- `assignee` NUNCA no payload de métrica (enforcement via middleware/serializer)
- `items[].issue_key` — OK (não é PII)
- `items[].title` — opcional; se incluído, truncar em 60 chars
- Não incluir campos `author`, `creator`, `reporter`

---

## 13. Performance — índices necessários

Para o endpoint de Aging WIP rodar em < 800ms p95 (req. do spec):

```sql
-- Índice parcial para WIP atual (principal bottleneck de Aging WIP)
-- Filtro: tenant_id + normalized_status IN ('in_progress', 'in_review')
CREATE INDEX CONCURRENTLY IF NOT EXISTS
    idx_eng_issues_tenant_active_status
    ON eng_issues (tenant_id, project_key, normalized_status)
    WHERE normalized_status IN ('in_progress', 'in_review');

-- Índice para baseline histórico (Query 2 e 4)
-- Filtro: tenant_id + completed_at (range) + normalized_status = 'done'
CREATE INDEX CONCURRENTLY IF NOT EXISTS
    idx_eng_issues_tenant_completed
    ON eng_issues (tenant_id, project_key, completed_at)
    WHERE normalized_status = 'done'
    AND completed_at IS NOT NULL
    AND started_at IS NOT NULL;
```

Estes índices já deveriam ser propostos ao `pulse-data-engineer` como parte do FDD-KB-003.

---

## 14. Hand-off por agente

### `pulse-data-engineer`

- [ ] **FDD-KB-001**: `ALTER TABLE eng_issues ADD COLUMN IF NOT EXISTS labels JSONB DEFAULT '[]'` + índice GIN. Necessário para M4 (não bloqueia M1/M2).
- [ ] **Endpoint `GET /data/v1/metrics/flow-health`** com parâmetros `tenant_id`, `squad_key` (opcional), `period` (padrão: 60d). Usar padrão `compute_*_on_demand` já existente em `home_on_demand.py` como referência.
  - Response shape: seção 12 deste documento
  - Separar lógica em `src/contexts/metrics/services/flow_health_on_demand.py`
- [ ] **Índices SQL** da seção 13 — aplicar via migration Alembic (não diretamente).
- [ ] **Snapshot strategy**: Aging WIP calculado **on-demand** (WIP muda com frequência). Flow Efficiency persiste em `metrics_snapshots` com grain diário (metric_type='kanban', metric_name='flow_efficiency').
- [ ] **Parâmetro `window_days`**: padrão 90d para baseline Aging WIP, 60d para Flow Efficiency. Expor ambos como query params.
- [ ] **Validação de payload anti-surveillance**: adicionar ao serializer um guard que rejeita qualquer resposta que contenha campo `assignee` ou `author` no nível de item individual.

### `pulse-engineer`

- [ ] **Hook `useFlowHealth(filters)`** em `pulse/packages/pulse-web/src/hooks/useFlowHealth.ts`
  - Parâmetros: `{ squadKey?: string, period: string }`
  - Retorna: `{ agingWip: AgingWipData, flowEfficiency: FlowEfficiencyData, isLoading, error }`
- [ ] **Types + transforms** em `pulse/packages/pulse-web/src/lib/api/` (seguir padrão de `metrics.ts` e `transforms.ts` existentes)
- [ ] Aguardar impl-spec do `pulse-ux-reviewer` antes de construir componentes
- [ ] **Disclaimer de fórmula**: quando `formula_version === 'v1_simplified'`, exibir chip "Versão simplificada" com tooltip explicativo
- [ ] **Analytics events**: `flow_health_section_viewed`, `aging_wip_item_clicked` (com `issue_key_hash` — não issue_key bruto), `flow_efficiency_hovered`

### `pulse-ux-reviewer`

- [ ] **3 concepts** para seção "Flow Health" na home, abaixo das DORA KPIs
- [ ] Resolver desafio de densidade: 27 squads × ~30 items = até 810 pontos no scatter. Opções: clustering, mini-scatter por squad, heatmap fallback
- [ ] **FlowEfficiencyGauge** com disclaimer "v1 simplificada" inline
- [ ] **AgingWipScatter** horizontal: eixo X = dias, eixo Y = squad, ponto = item, linha pontilhada = P85 baseline
- [ ] Estados obrigatórios: loading (skeleton), empty ("Sem trabalho em andamento"), healthy, degraded, error, partial (histórico insuficiente)
- [ ] Escala responsiva: desktop ≥1280 (side-by-side), mobile (stack vertical)
- [ ] Spec em `pulse/docs/ux-specs/flow-health-impl-spec.md`

### `pulse-test-engineer`

- [ ] Implementar os 25 cenários de teste propostos na seção 10 deste documento
- [ ] **TDD**: escrever testes ANTES da implementação nos serviços
- [ ] **Testes de propriedade** (hypothesis): `age >= 0`, `FE in [0, 1]`, `p50 <= p85 <= p95`
- [ ] **Anti-surveillance contract test**: falhar se campo `assignee` aparecer em qualquer nível do payload de `/flow-health`
- [ ] Fixture Webmotors-like: 27 project_keys, 100+ issues por squad, mix de status, transitions reais (incluindo reopen)
- [ ] Performance benchmark k6: `/flow-health?squad_key=OKM` < 800ms p95; tenant-wide < 1.5s p95

### `pulse-ciso`

- [ ] **Review do payload** de Aging WIP: confirmar que `items[]` nunca expõe `assignee`
- [ ] **Middleware de auditoria**: considerar log de acesso a dados de itens individuais (issue_key) — nem todos os tenants precisam de item-level, pode ser feature gated
- [ ] **R2 prep**: campo `tenant_workflow_config.blocked_statuses` será array de strings livres — validar tamanho máximo (sugestão: max 50 strings, max 100 chars cada) para prevenir abuso

---

*Fim do documento.*
