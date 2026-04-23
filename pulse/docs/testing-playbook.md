# PULSE Testing Playbook

Guia prático para escrever, organizar e executar testes no PULSE — cobrindo a
separação entre **testes de plataforma** (universais, rodam em qualquer tenant) e
**testes customer-specific** (validam premissas de um cliente específico do SaaS).

---

## 1. Princípio arquitetural (TL;DR)

O PULSE é um SaaS multi-tenant. Nosso cliente-âncora hoje é a **Webmotors**, mas a
arquitetura precisa suportar múltiplos clientes com especificidades de domínio
(convenções de Jira, taxonomia de squads, padrões de CI/CD, regras de negócio).

Por isso dividimos os testes em duas árvores:

```
pulse/packages/<service>/tests/              ← PLATAFORMA (universal)
pulse/packages/<service>/tests-customers/    ← CUSTOMER-SPECIFIC
  └── webmotors/
  └── <proximo-cliente>/
```

### Regra de ouro

> **Teste de plataforma** = funciona em QUALQUER cliente com QUALQUER dado sintético.
> **Teste customer** = depende de premissas/dados específicos de UM cliente.

Se você está tentado a fazer um teste de plataforma usando um valor mágico como
`assert throughput == 5044`, **pare**. Esse valor é Webmotors-específico.
O teste de plataforma é a invariante (`assert throughput_60d != throughput_120d`).
O teste customer guarda o número absoluto (`assert throughput_60d == 5044 ± 5%`).

---

## 2. Estrutura de diretórios

### Backend (Python — pulse-data, pulse-api)

```
pulse/packages/pulse-data/
├── tests/                              ← PLATAFORMA
│   ├── unit/                           ← funções puras, domain, fórmulas canônicas
│   │   ├── metrics/                    ← domain/{dora,lean,cycle_time,sprint,throughput}
│   │   ├── connectors/
│   │   └── contexts/
│   ├── integration/                    ← API + DB, Testcontainers ou docker-compose
│   │   └── contexts/
│   └── contract/                       ← schemas Pydantic, anti-surveillance gate
│
└── tests-customers/                    ← CUSTOMER-SPECIFIC
    └── webmotors/
        ├── README.md                   ← contexto Webmotors
        ├── conftest.py                 ← fixtures Webmotors (ex: conexão ao DB real)
        ├── test_webmotors_*.py         ← testes com premissas Webmotors
        └── fixtures/                   ← dados anonimizados específicos
```

### Frontend (TypeScript — pulse-web)

```
pulse/packages/pulse-web/
├── tests/                              ← PLATAFORMA
│   ├── unit/                           ← utilities, formatters, transforms
│   ├── component/                      ← React components (RTL)
│   ├── hook/                           ← TanStack Query hooks (MSW mocks)
│   ├── contract/                       ← schemas Zod matching backend Pydantic
│   └── e2e/
│       └── platform/                   ← jornadas universais (Playwright)
│
└── tests-customers/                    ← CUSTOMER-SPECIFIC
    └── webmotors/
        └── e2e/                        ← jornadas com dados/premissas Webmotors
```

---

## 3. Convenções de nomenclatura

### Arquivos de teste

| Padrão | Uso | Exemplo |
|---|---|---|
| `test_<feature>.py` | Plataforma backend | `test_cycle_time_breakdown.py` |
| `test_<customer>_<feature>.py` | Customer backend | `test_webmotors_squad_taxonomy.py` |
| `<feature>.test.ts` | Plataforma frontend | `formatDuration.test.ts` |
| `<feature>.spec.ts` | Plataforma E2E | `home-dashboard.spec.ts` |
| `<customer>-<feature>.spec.ts` | Customer E2E | `webmotors-fid-sprints.spec.ts` |

### Nomes de testes (descritivos, inglês)

```python
def test_throughput_monotonically_increases_with_period():
    """Platform: throughput(30d) < throughput(60d) < throughput(120d)."""
    ...

def test_webmotors_throughput_60d_matches_production_value():
    """Customer: Webmotors historical 60d throughput ≈ 5044 PRs (±5%)."""
    ...
```

---

## 4. Como adicionar testes — Playbook por cenário

### Cenário A: "Descobri um bug novo"

1. **Escreva teste primeiro** que reproduz o bug (TDD invertido)
2. Classifique: plataforma ou customer?
   - **Bug na fórmula/lógica** → plataforma
   - **Bug em valor específico/taxonomia cliente** → customer (+ talvez também plataforma)
3. Coloque no diretório correto
4. Implemente o fix
5. Confirma teste passa

### Cenário B: "Estou implementando feature nova"

1. **Teste unit de plataforma primeiro** (domain/invariant)
2. **Teste de integração de plataforma** (API → DB com fixture sintética)
3. **Component test de plataforma** (React, se UI)
4. **E2E de plataforma** (se jornada nova)
5. **Teste customer só se feature tem comportamento diferente por cliente**

### Cenário C: "Adicionando novo cliente ao SaaS"

1. Criar `pulse/packages/<service>/tests-customers/<cliente>/` com README.md documentando:
   - Context do cliente (quantos squads, Jira projects, CI/CD, etc.)
   - Premissas específicas que os testes validam
   - Como rodar (credenciais, config)
2. Copiar template de `tests-customers/webmotors/conftest.py` como ponto de partida
3. Adicionar job CI `tests-customer-<cliente>-backend` / `-frontend`
4. Documentar em `pulse/docs/test-strategy.md` seção de coverage

### Cenário D: "Webmotors mudou de Kanban pra Sprint em alguns squads"

1. Atualizar `tests-customers/webmotors/test_webmotors_sprint_taxonomy.py`
2. NÃO toque em `tests/` (plataforma) — a plataforma já testa "se tem sprint X" e "se tem Kanban Y", cliente diz quais squads são X ou Y
3. Se plataforma precisar mudar para suportar caso novo, add teste em `tests/` e depois customer

---

## 5. Coverage reporting

### Dois indicadores separados

```
Platform coverage:   85% (target)   ← headline, todos os clientes se beneficiam
Customer coverage:
  - Webmotors:       78% (informal)  ← complementar, por cliente
```

### Como gerar

```bash
# Plataforma
cd pulse/packages/pulse-data
pytest tests/ --cov=src --cov-report=html --cov-report=term

# Customer Webmotors
pytest tests-customers/webmotors/ --cov=src --cov-report=html --cov-report=term \
  --cov-config=tests-customers/webmotors/.coveragerc

# Agregado (reports separados)
```

### CI integration

O CI do PULSE (`pulse/.github/workflows/ci.yml`) tem jobs separados:

| Job | O que roda | Bloqueador de PR? |
|---|---|---|
| `tests-platform-backend` | `pytest tests/` (backend) | **Sim** |
| `tests-platform-frontend` | `vitest run tests/` (frontend) | **Sim** |
| `tests-customer-webmotors-backend` | `pytest tests-customers/webmotors/` | **Não** (nightly) |
| `tests-customer-webmotors-frontend` | `playwright test tests-customers/webmotors/` | **Não** (nightly) |

**Path-filter** opcional: se um PR toca em `tests-customers/webmotors/` ou em código
comprovadamente Webmotors-específico (ex: connector de Jira com taxonomia WM), então
os jobs customer **viram bloqueadores** para aquele PR específico.

---

## 6. Fail-open para tests-customers

Testes customer frequentemente dependem de:
- Conexão ao DB de produção ou staging do cliente
- Credenciais privadas (VPN, tokens)
- Volume mínimo de dados

Se o ambiente não tem esses pré-requisitos, **pule com mensagem clara**:

```python
@pytest.fixture(scope="session")
def webmotors_db_available():
    try:
        async with get_session(WEBMOTORS_TENANT_ID) as s:
            r = await s.execute(text("SELECT COUNT(*) FROM eng_issues"))
            return r.scalar() > 10000
    except Exception:
        return False

@pytest.mark.skipif(not webmotors_db_available, reason="Webmotors DB not reachable")
def test_webmotors_throughput_historical_values():
    ...
```

**Nunca** faça um teste customer `FAIL` quando o ambiente não tem dados.
Sempre `SKIP` com razão.

---

## 7. Anti-patterns (não faça)

- ❌ **Valores mágicos em testes de plataforma** (`assert count == 5044`). Esses valores mudam com ingestão; teste invariantes, não fotografias.
- ❌ **Testes customer acessando dados reais de PII**. Sempre anonimize (`author = "user-{uuid}"` se necessário testar multi-tenant).
- ❌ **Compartilhar fixtures entre platform e customer**. Se você precisa do mesmo payload nos dois, extraia pra `tests/fixtures/` ou duplique (custo < acoplamento).
- ❌ **Testes customer que falham o CI de plataforma**. Customer roda separado, sempre.
- ❌ **Testar lógica cliente na plataforma**. Se sua função `calculate_sprint_velocity` tem `if tenant == 'webmotors'`, refatore imediatamente.

---

## 8. Frontend: como adicionar testes de component, hook e contract

### Infra instalada (Sprint 1.2 passo 1)

- `@testing-library/react@^16` + `@testing-library/user-event@^14` — render e interação
- `@testing-library/jest-dom@^6` — matchers (`toBeInTheDocument`, `toBeVisible`, etc.)
- `msw@^2` — interceptor de rede para hooks TanStack Query
- `zod@^3` — validação de schema para contract tests
- `jsdom@^25` — ambiente DOM no Vitest
- Entrypoints: `tests/setup.ts` (lifecycle MSW) + `tests/msw-server.ts` (instância shared)
- Vitest configurado em `vitest.config.ts` com `include: ['src/**', 'tests/**']`

### Como adicionar um component test

Crie o arquivo em `tests/component/<ComponentName>.test.tsx`.

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MyComponent } from '@/components/path/MyComponent';

describe('MyComponent', () => {
  it('renders expected text', () => {
    render(<MyComponent label="Foo" value={42} />);
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('responds to user interaction', async () => {
    const user = userEvent.setup();
    render(<MyComponent label="Foo" value={42} />);
    await user.click(screen.getByRole('button', { name: /foo/i }));
    expect(screen.getByText('clicked')).toBeVisible();
  });
});
```

Regras:
- Use `screen.getByRole` / `getByText` / `getByLabelText` — nunca `getByTestId` como primeira opção.
- Envolva o componente nos providers que ele precisa (`QueryClientProvider`, router, etc.).
- Props sintéticas — sem valores mágicos de produção (ex: `value={5044}` é aceitável aqui porque testa lógica de render, não dado real).

### Como adicionar um hook test com MSW

Crie o arquivo em `tests/hook/<hookName>.test.tsx`.

```tsx
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../msw-server';
import { useMyHook } from '@/hooks/useMyHook';

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useMyHook', () => {
  it('returns data on success', async () => {
    server.use(
      http.get('/data/v1/some-endpoint', () =>
        HttpResponse.json({ value: 99 }),
      ),
    );
    const { result } = renderHook(() => useMyHook(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.value).toBe(99);
  });
});
```

Regras:
- O padrão de URL do MSW é **relativo** (`'/data/v1/...'`), não absoluto.
  Isso porque axios em jsdom resolve relative baseURLs e o MSW node interceptor
  vê o path sem `http://localhost`.
- `retry: false` no QueryClient — sem retry, os erros surfaceiam imediatamente.
- `server.use()` dentro do teste: o `afterEach` em `tests/setup.ts` faz `resetHandlers()` automaticamente.
- Para capturar query params: use `new URL(request.url).searchParams` dentro do handler.

### Como adicionar um contract test com Zod

Crie o arquivo em `tests/contract/<schema-name>-contract.test.ts`.

```ts
import { z } from 'zod';

const MyResponseSchema = z.object({
  value: z.number().nullable(),
  unit: z.string(),
  // adicione apenas os campos que o frontend LÊ
});

describe('MyResponse contract', () => {
  it('validates a structurally correct payload', () => {
    const result = MyResponseSchema.safeParse({ value: 42, unit: 'hours' });
    expect(result.success).toBe(true);
  });

  it('rejects payload missing required field', () => {
    const result = MyResponseSchema.safeParse({ value: 42 }); // unit ausente
    expect(result.success).toBe(false);
  });
});
```

Regras:
- O schema Zod aqui é do FRONTEND — só lista os campos que quebram a UI se ausentes.
  Campos extras que o backend retorna (e o frontend ignora) não precisam constar.
- Não fazer chamada real ao backend. O contrato é validado localmente.
- Quando o backend alterar um campo obrigatório, esse teste deve falhar ANTES de
  qualquer crash em produção — é a função principal dessa camada.
- Os schemas Zod de contract devem estar em `tests/contract/`, não em `src/`.

### 8.4 Como adicionar contract test para novo endpoint (Sprint 1.2 passo 3+)

A partir do Sprint 1.2 passo 3 os schemas Zod estão organizados em `tests/contract/schemas/`.
Ao adicionar cobertura para um novo endpoint `/metrics/*`, siga este template.

**Estrutura de arquivos**

```
tests/contract/
├── schemas/
│   ├── _common.ts               ← envelope + FORBIDDEN_FIELD_PATTERNS + extractAllKeys
│   ├── <endpoint>.schema.ts     ← NOVO: defina o schema aqui
│   └── ...
├── anti-surveillance-schemas.test.ts  ← adicionar novo schema no SCHEMA_REGISTRY
└── <endpoint>-contract.test.ts        ← NOVO: testes A/B/C/D/E
```

**1. Criar o schema em `tests/contract/schemas/<endpoint>.schema.ts`**

```ts
import { z } from 'zod';
import { MetricsEnvelopeSchema } from './_common';

// Espelhe o shape EXATO do que o backend retorna (snake_case, wire format).
// Consulte pulse/packages/pulse-data/src/contexts/metrics/schemas.py

const MyEndpointDataSchema = z.object({
  some_value: z.number().nullable().optional(),
  some_count: z.number().int(),
  // ...
});

export const MyEndpointResponseSchema = MetricsEnvelopeSchema.extend({
  data: MyEndpointDataSchema,
});
```

Observações:
- Use `MetricsEnvelopeSchema.extend({})` para endpoints padrão (que herdam `period`, `period_start`, etc.)
- Para endpoints sem envelope (ex: `/metrics/sprints`), use `z.object({})` diretamente
- Marque todos os campos nullable com `.nullable()` e opcionais com `.optional()`
- Campos `list[dict]` do Python viram `z.array(z.record(z.unknown()))` (opaque)
- Campos `dict[str, Any]` viram `z.record(z.unknown())` (opaque)

**2. Criar os testes em `tests/contract/<endpoint>-contract.test.ts`**

Cinco testes mínimos:

```ts
import { describe, it, expect } from 'vitest';
import { MyEndpointResponseSchema } from './schemas/<endpoint>.schema';

// Fixture mínima válida
const VALID_RESPONSE = { /* ... */ };

describe('MyEndpointResponse contract (Zod)', () => {
  // A — fixture válida parseia sem erro
  it('A: validates a well-formed response', () => {
    expect(MyEndpointResponseSchema.safeParse(VALID_RESPONSE).success).toBe(true);
  });

  // B — campo obrigatório ausente é rejeitado
  it('B: rejects response missing `data` field', () => {
    const { data: _, ...noData } = VALID_RESPONSE;
    expect(MyEndpointResponseSchema.safeParse(noData).success).toBe(false);
  });

  // C — tipo errado é rejeitado
  it('C: rejects string where number expected', () => {
    const bad = { ...VALID_RESPONSE, data: { ...VALID_RESPONSE.data, some_value: 'nope' } };
    expect(MyEndpointResponseSchema.safeParse(bad).success).toBe(false);
  });

  // D — anti-surveillance: campo proibido é stripped (Zod default = strip mode)
  it('D: anti-surveillance — assignee injected into data is stripped', () => {
    const withAssignee = { ...VALID_RESPONSE, data: { ...VALID_RESPONSE.data, assignee: 'x' } };
    const result = MyEndpointResponseSchema.safeParse(withAssignee);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(Object.keys(result.data.data)).not.toContain('assignee');
    }
  });

  // E — (skip se backend offline) parseia resposta real
  it('E: (skip if backend offline) parses real API response', async () => {
    let ok = false;
    try { ok = (await fetch('http://localhost:8000/data/v1/metrics/<endpoint>', { signal: AbortSignal.timeout(2000) })).ok; } catch {}
    if (!ok) { console.info('Backend offline — skipping'); return; }
    const json = await (await fetch('http://localhost:8000/data/v1/metrics/<endpoint>')).json();
    const result = MyEndpointResponseSchema.safeParse(json);
    if (!result.success) console.error(result.error.issues);
    expect(result.success).toBe(true);
  });
});
```

**3. Registrar no meta-test anti-surveillance**

Em `tests/contract/anti-surveillance-schemas.test.ts`, adicionar à lista `SCHEMA_REGISTRY`:

```ts
import { MyEndpointResponseSchema } from './schemas/<endpoint>.schema';

const SCHEMA_REGISTRY = [
  // ...existentes...
  { name: 'MyEndpointResponse', schema: MyEndpointResponseSchema },
];
```

**4. Rodar**

```bash
cd pulse/packages/pulse-web
npm test -- --run tests/contract/
# Esperado: N+6 tests passing (onde N = testes anteriores)
```

### 8.5 Como adicionar um E2E platform test (Playwright)

Instalado em Sprint 1.2 passo 2. Playwright 1.59 com Chromium + Firefox.

**Pre-requisitos antes de rodar:**

```bash
# Backend (API + DB)
cd pulse && docker compose up -d

# Rodar smoke (Vite sobe automaticamente via webServer no playwright.config.ts)
cd packages/pulse-web
npm run test:e2e
```

**Criar uma nova jornada:**

```
tests/e2e/platform/<pagina>-<acao>.spec.ts
```

Exemplo mínimo:

```ts
import { test, expect } from '@playwright/test';

test.describe('Minha jornada', () => {
  test('usuário consegue completar X', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'PULSE Dashboard' })).toBeVisible();
    // ... demais steps
  });
});
```

**Regras:**

- E2E valida **jornadas de usuário ponta a ponta** — não lógica de negócio (isso é unit/integration).
- Ordem de preferência de seletores: `getByRole` > `getByLabel` > `getByText` > `locator('#id-estável')` > `getByTestId`.
- Se o teste depende de backend, adicione guard: `test.skip(backendOffline, 'reason')`.
- Timeout padrão: 30s por teste, `expect` timeout: 15s. Para renders pesados, passe `{ timeout: 15_000 }` no `toBeVisible`.
- Nenhum teste de E2E deve verificar ranking de desenvolvedor individual (anti-surveillance).
- Arquivo de configuração: `pulse/packages/pulse-web/playwright.config.ts`.
- Docs da pasta: `tests/e2e/platform/README.md`.

**Comandos disponíveis:**

```bash
npm run test:e2e              # todos os E2E (headless, chromium + firefox)
npm run test:e2e:ui           # modo UI interativo (debug local)
npm run test:e2e:debug        # inspector passo a passo
npm run test:e2e -- --project=chromium   # só chromium (mais rápido)
```

---

## 8.6 Secret scanning (Gitleaks pre-commit — Sprint 1.2 passo 5)

### O que é

Hook pre-commit que bloqueia qualquer commit contendo secrets (API tokens,
chaves AWS/GCP, senhas hardcoded, connection strings com senha, etc.).
Usa [gitleaks](https://github.com/gitleaks/gitleaks) com o ruleset default
(AWS, GitHub, Atlassian, Slack, Stripe, JWT...) + regras PULSE-específicas
(`INTERNAL_API_TOKEN`, `DEVLAKE_DB_URL`...).

**Por que importa**: uma vez que um token entra em `git push`, já vazou
— revogar não apaga do histórico do GitHub. O hook bloqueia antes de sair
da máquina.

### Setup (uma vez por clone)

```bash
# 1. Instalar gitleaks
brew install gitleaks          # macOS
# ou: docker pull zricethezav/gitleaks

# 2. Ativar o hook (aponta git pro diretório versionado .githooks/)
git config core.hooksPath .githooks
```

Depois disso todo `git commit` roda `gitleaks protect --staged` antes de
finalizar. Se detectar um secret, o commit é rejeitado com a linha/regra
identificada (secret redigido no output).

### Arquivos envolvidos

- `.githooks/pre-commit` — shell script executado por git (versionado)
- `.gitleaks.toml` — config: `[extend] useDefault = true` + regras PULSE
  + `[allowlist]` paths (`.env`, `.claude/settings.local.json`, lockfiles,
  `tests/fixtures/`...)

### Como adicionar nova regra ou allowlist

**Regra nova** (novo formato de token interno):

```toml
[[rules]]
id = "pulse-novo-token"
description = "Descrição curta"
regex = '''(?i)novo[_-]?token\s*=\s*['"]?([A-Za-z0-9_\-]{20,})'''
secretGroup = 1
keywords = ["novo_token", "novo-token"]
```

**Allowlist** (false positive confirmado):

```toml
# Em .gitleaks.toml, seção [allowlist]:
paths = [
  ...existentes...,
  '''pulse/packages/pulse-web/tests/fixtures/fake-secrets\.json''',
]

# Ou por regex de conteúdo:
regexes = [
  ...existentes...,
  '''TOKEN_OBVIAMENTE_FALSO_123''',
]
```

Sempre commit o `.gitleaks.toml` **antes** do arquivo com o false positive,
senão o hook do próprio commit da allowlist vai falhar.

### Como testar localmente

```bash
# Simular finding:
printf 'GITHUB_TOKEN=ghp_K8JdnS82mQrX94HaL3P7vYtZ2wBcDfEg6NmQ\n' > /tmp/t.txt
git add /tmp/t.txt
./.githooks/pre-commit   # deve sair com código 1

# Limpar
git reset HEAD /tmp/t.txt && rm /tmp/t.txt
```

Full-repo scan (fora do hook, útil para CI ou auditoria periódica):

```bash
gitleaks detect --no-git --source . --config .gitleaks.toml --verbose
```

### Bypass (emergência)

```bash
git commit --no-verify
```

Só use se:
1. Você confirmou que é false positive **e** não dá tempo de atualizar
   allowlist agora, OU
2. Você está offline e o finding é num arquivo que nunca vai pra remote.

Regra informal: se usar `--no-verify`, abra issue explicando o motivo
na mesma hora. O CI (passo 6) vai re-scanear de qualquer jeito.

### Limitações conhecidas

- **Entropia baixa passa**: tokens sequenciais (`abcd...xyz`) ficam abaixo
  do threshold e não são detectados. Isso é bom — reduz false positives
  em docs/exemplos — mas significa que tokens "test" muito óbvios não
  bloqueiam. CI scan completo pega, hook local não.
- **History antiga**: hook só olha staged diff. Para auditar history
  toda, rode `gitleaks detect` (sem `--no-git`) no CI periodicamente.

---

## 8.7 A11y gate (axe-core + Playwright — Sprint 1.2 passo 4)

### O que é

Audit automatizado de acessibilidade rodado via [axe-core](https://github.com/dequelabs/axe-core)
dentro do Playwright. Cada spec navega pra uma página, espera o estado estável,
e chama `runA11yAudit(page, testInfo, { context: 'home' })`. Qualquer violação
de severidade **critical** ou **serious** contra WCAG 2.1 AA bloqueia o teste.

**Por que importa**: WCAG AA é compromisso do design-doc. Sem gate automatizado,
regressão de contraste/teclado/labels passa sem ninguém ver até um cliente
reportar — e aí é retrabalho mais caro que prevenir.

### Layout

```
tests/e2e/a11y/
  _helpers.ts        ← runA11yAudit + devServerIsDown helpers (compartilhados)
  home.spec.ts       ← audit /
  dora.spec.ts       ← audit /metrics/dora
  cycle-time.spec.ts ← audit /metrics/cycle-time
  # Adicione novos specs conforme o template abaixo.
```

### Política de gate

| Severidade axe-core | Comportamento |
|---|---|
| `critical`          | **Fail** — bloqueia merge |
| `serious`           | **Fail** — bloqueia merge |
| `moderate`          | Warn no log, anexa JSON, **não** falha |
| `minor`             | Warn no log, anexa JSON, **não** falha |
| tag `best-practice` | Excluído do ruleset (advisory, não é WCAG) |

`moderate`/`minor` são logados para construir baseline e apertar o gate
depois sem "big-bang fix session".

### Como rodar

```bash
# Requer vite dev server em http://localhost:5173 (Playwright auto-inicia se preciso)
npm run test:a11y              # chromium apenas, rápido
# ou:
npm run test:e2e -- tests/e2e/a11y   # todos browsers configurados
```

Reports: `playwright-report/` contém HTML interativo; cada violação vem com
URL do Deque University explicando a regra + como consertar. JSON completo
é attachment em cada teste (`a11y-<context>.json`) para triagem.

### Como adicionar audit de uma página nova (template)

```typescript
// tests/e2e/a11y/minha-pagina.spec.ts
import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Minha Página', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo');

    await page.goto('/minha-pagina', { waitUntil: 'load', timeout: 20_000 });

    // Espere o estado estável. Padrão pragmático: h1 visível + 3s de settle.
    // Páginas com skeleton precisam esperar que resolva (pode usar toPass
    // em um seletor de "conteúdo carregado").
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });
    // eslint-disable-next-line playwright/no-wait-for-timeout
    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'minha-pagina',
      // TEMP: enquanto FDD-OPS-003 (design-system contrast) não ship, essa regra fica off.
      disableRules: ['color-contrast'],
    });
  });
});
```

### Como allowlistar uma violação específica

**Regra global** (um bug conhecido do design system, válido em todas as páginas):

Passe `disableRules: ['nome-da-regra']` no `runA11yAudit` E documente inline
com link pro FDD que vai consertar. Revisar a lista a cada sprint — não
deixar drift.

**Nó específico** (terceiro que não controlamos, ex: chart lib):

Passe `exclude: ['.meu-seletor']` no `runA11yAudit`. Prefira fixar a
violação — `exclude` é último recurso.

### Débito técnico atual

- **`color-contrast` desabilitado em todas as specs** → **FDD-OPS-003**
  (design-system contrast review, P1). 172 nós impactados na home — é
  problema sistêmico de tokens, não de componente individual.
- `best-practice` tags fora do ruleset por design (heading-order,
  landmark-one-main etc. são advisory, gerariam ruído sem ganho claro
  para WCAG). Revisar em Sprint 3.

### Gotchas

- **Não audite skeleton state**: espere o conteúdo real renderizar. axe-core
  testa o DOM vivo — se o card ainda está em `animate-pulse`, você audita
  o skeleton, não o conteúdo.
- **`<dl>` só aceita `<dt>`/`<dd>` ou `<div>` como filhos diretos**.
  Wrapping com `<span>` quebra a regra `definition-list`. Trocar pra `<div
  className="inline-flex">` mantém o layout e fica válido.
- **SVG de charts precisa de `<title>` + `role="img"`** ou `aria-label`
  descrevendo o dado. Recharts/Chart.js não adicionam automaticamente —
  configure via props do componente.

---

## 9. Próximos clientes (roadmap)

Quando o segundo cliente SaaS chegar, esperamos:

1. Criar `tests-customers/<cliente-2>/` espelhando a estrutura Webmotors
2. Ajustar `test-strategy.md` com coverage per-customer para `<cliente-2>`
3. CI job novo `tests-customer-<cliente-2>-*`
4. Validar que `tests/` (plataforma) continua passando sem mudanças — **prova** de que a plataforma é de fato multi-cliente

Se algum teste de plataforma precisar de condicionais por cliente, é sinal de que o
código de produção também tem esse acoplamento — escale pro pulse-engineer refatorar.
