# PULSE E2E — Platform Tests

Testes de jornada de usuário que funcionam em **qualquer tenant** do PULSE SaaS.
Implementados com Playwright. Nenhum dado hardcoded de Webmotors aqui.

---

## O que e "platform" vs "customer"?

| Camada | Diretório | Exemplos |
|---|---|---|
| Platform | `tests/e2e/platform/` | "Dashboard carrega", "Filtro de squad muda os cards" |
| Customer | `tests-customers/webmotors/e2e/` | "Card Sprints aparece para FID", "Squad PF-OEM existe" |

Platform tests validam o comportamento universal da UI — qualquer instância
PULSE instalada deve passá-los. Customer tests validam dados e configurações
específicas de um cliente.

---

## Pre-requisitos para rodar localmente

```bash
# 1. Backend (API + DB + workers)
cd pulse && docker compose up -d

# 2. Esperar o backend estar healthy (~30s na primeira vez)
docker compose ps

# 3. Na raiz do pulse-web, rodar o smoke
cd packages/pulse-web
npm run test:e2e -- tests/e2e/platform/home-dashboard-smoke.spec.ts
```

O Playwright inicia o Vite dev server automaticamente (`webServer` no config).
Se o Vite ja estiver rodando na porta 5173, ele reusa sem restart.

---

## Comandos

```bash
# Rodar todos os E2E platform (headless, chromium + firefox)
npm run test:e2e

# Rodar so um arquivo
npm run test:e2e -- tests/e2e/platform/home-dashboard-smoke.spec.ts

# Modo UI interativo (recomendado para debug local)
npm run test:e2e:ui

# Modo debug com inspector (pausa em cada step)
npm run test:e2e:debug

# Somente chromium (mais rapido para iterar)
npm run test:e2e -- --project=chromium
```

---

## CI (futuro Sprint 1.2 passo 6)

Os E2E ainda nao estao no pipeline CI. Quando forem, a sequencia sera:

1. `docker compose up -d` (servicos)
2. `npm run test:e2e` com `CI=true` (workers=1, retries=2)
3. Upload do `playwright-report/` como artefato

---

## Como adicionar uma jornada nova

1. Crie `tests/e2e/platform/<journey-name>.spec.ts`
2. Regra de nomenclatura: `<pagina>-<acao>.spec.ts`
   - `home-dashboard-smoke.spec.ts` — carregamento basico
   - `dora-drill-down.spec.ts` — navegacao para detalhe DORA
   - `filter-flow.spec.ts` — mudanca de squad e periodo
3. Use `test.describe` com nome descritivo da jornada
4. Inclua o guard de backend offline (`test.skip`) se o teste depender de API

Siga a ordem de preferencia de seletores (RTL-style):
1. `getByRole` — semantico e resistente a refatoracao
2. `getByLabel` — para inputs com label associado
3. `getByText` — para textos estaticos
4. `locator('#id')` — para IDs estaveis e intencionais (ex: `#dash-team-trigger`)
5. `getByTestId` — ultimo recurso, so se os anteriores falharem

**E2E nao testa logica de negocio** — isso e responsabilidade de unit/integration tests.
E2E valida que o usuario consegue completar a jornada ponta a ponta.

---

## Convencoes anti-surveillance

Nenhum teste deve verificar:
- Rankings ou scores de desenvolvedores individuais
- `assignee` ou `author` de PRs/issues no nivel de pessoa
- Leaderboards

Todas as metricas sao no nivel de squad ou acima.
