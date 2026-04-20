# Webmotors — Customer-Specific Frontend Tests

Testes E2E que validam a UI com premissas específicas da Webmotors.

## Estrutura

```
webmotors/
└── e2e/
    ├── webmotors-squad-names.spec.ts    ← squads aparecem com nomes reais ("PF - OEM Integração")
    ├── webmotors-fid-sprints.spec.ts    ← FID tem sprints visíveis
    └── webmotors-flow-health.spec.ts    ← 27 cards de squad na Flow Health section
```

## Quando rodar

Path-filter no CI: se um PR toca em `tests-customers/webmotors/` OU em componentes
sabidamente customer-specific, esses testes viram bloqueador.
Caso contrário: rodam nightly.

## Pré-requisitos

- Stack PULSE rodando local: `make up`
- Frontend em `http://localhost:5173`
- Backend em `http://localhost:8000`
- DB Webmotors populado (374k issues, 27 squads)

Ver `pulse/docs/testing-playbook.md` seção 6 pra fail-open quando ambiente não
satisfaz pré-requisitos.
