# Customer-Specific Tests (Backend)

Testes que validam **premissas específicas de um cliente** do SaaS PULSE.

Estes testes **não bloqueiam** PRs de plataforma — rodam em nightly OU em PRs que
tocam em código cliente-específico (via path filter no CI).

## Clientes atuais

- [`webmotors/`](./webmotors/) — cliente-âncora (374k issues, 27 squads, Jira+Jenkins+GitHub)

## Como adicionar novo cliente

Ver `pulse/docs/testing-playbook.md` seção 4 Cenário C.

## Convenções

- Arquivos: `test_<customer>_<feature>.py`
- Fail-open: se ambiente não tem dados, `pytest.skip` com razão clara
- Zero PII: anonimize usuários, emails, assignees
- READ-ONLY no DB do cliente em produção local
