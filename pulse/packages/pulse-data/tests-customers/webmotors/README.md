# Webmotors — Customer-Specific Tests

Testes backend que validam premissas específicas da **Webmotors** (cliente-âncora
do PULSE). Não rodam em CI de PR por padrão — nightly ou via path filter.

## Contexto Webmotors

- **Volume**: ~374k issues Jira, ~57k PRs, 1.469 deployments/90d
- **Squads**: 27 ativos (padrão de código 2-5 chars maiúsculos — ex: `OKM`, `FID`, `SECOM`)
- **Projetos Jira**: 69 ativos (discovery mode dinâmico ligado)
- **CI cliente**: Jenkins (Webmotors) — monitorado pelo PULSE via connector
  - PULSE em si usa GitHub Actions
- **Fluxo**: 25 squads Kanban puro, 2 usam Sprint (FID - Fidelidade, PTURB - Motor VN)
- **Taxonomia de status Jira** (relevante pra Flow Efficiency):
  - "Em Desenvolvimento" → `in_progress` (touch)
  - "Aguardando Code Review" → `in_review` (tratado como touch na v1 simplified)
  - "Aguardando Teste Azul" → `in_review` (idem)
  - "Concluído" / "Fechado" → `done`
- **Padrão repo GitHub**: `webmotors-private/<repo-name>` (sempre com prefixo)
- **Padrão repo Jenkins `eng_deployments.repo`**: `<repo-name>` (sem prefixo — motivo do INC-FONTES)

## O que os testes validam

| Teste | O que valida |
|---|---|
| `test_webmotors_throughput_values.py` | Valores históricos Throughput (INC-001 regression) |
| `test_webmotors_fontes_coverage.py` | FONTES retorna contagem para os 27 squads (INC-FONTES) |
| `test_webmotors_squad_taxonomy.py` | Squad codes seguem padrão 2-5 chars uppercase |
| `test_webmotors_data_quality.py` | Zumbis Jira > 365d são detectados (higiene) |
| `test_webmotors_sprint_projects.py` | FID e PTURB são os únicos squads com sprint ativo |

## Como rodar

```bash
cd pulse/packages/pulse-data

# Roda tudo (fail-open se DB não tiver dados)
pytest tests-customers/webmotors/ -v

# Forçar skip se ambiente não é Webmotors
SKIP_IF_NO_CUSTOMER_DATA=true pytest tests-customers/webmotors/ -v

# Rodar apenas 1 teste
pytest tests-customers/webmotors/test_webmotors_throughput_values.py -v
```

## Pré-requisitos

- Docker Compose up (`make up`)
- DB Postgres acessível em `localhost:5432` com dados Webmotors populados
- Tenant default configurado (`00000000-0000-0000-0000-000000000001`)

## Anti-surveillance

Os testes **nunca** fazem `SELECT author, assignee, email` em plain text. Usam
COUNT, aggregations ou anonymize fields (`md5(email)`) quando inevitável.
