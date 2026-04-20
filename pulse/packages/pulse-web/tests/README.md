# PULSE Web — Platform Tests

Testes frontend que funcionam em **qualquer cliente** do SaaS PULSE.

## Estrutura

```
tests/
├── unit/          ← Vitest — utilities, formatters, transforms
├── component/     ← Vitest + React Testing Library — components isolados
├── hook/          ← Vitest + RTL + MSW — TanStack Query hooks, filterStore
├── contract/      ← Vitest + Zod — valida schemas backend não-regressivos
└── e2e/
    └── platform/  ← Playwright — jornadas universais
```

## Customer-specific?

Testes que dependem de dados/padrões Webmotors (ex: "card PF - OEM Integração
aparece") vão em [`../tests-customers/webmotors/`](../tests-customers/webmotors/).

## Convenções

- **Unit/Component**: `<feature>.test.ts` ou `<Component>.test.tsx`
- **E2E**: `<journey>.spec.ts`
- Zero hardcoded values de produção
- Fixtures em `tests/fixtures/` (sintéticas, deterministas)
- Anti-surveillance: nenhum teste valida exibição de `assignee`/`author` individual

Ver `pulse/docs/testing-playbook.md` para regra completa de platform vs customer.
