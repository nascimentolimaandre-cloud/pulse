---
description: Bootstrap PULSE infrastructure in phases. Phase 1 = skeleton+Docker+CI, Phase 2 = data pipeline, Phase 3 = metrics+dashboards.
argument-hint: [phase-number] (default: 1)
---
# Bootstrap PULSE — Phase $ARGUMENTS

## Phase 1 — Infrastructure (default)
Delegate to **pulse-engineer**: monorepo structure, package skeletons (NestJS+FastAPI+React), Docker Compose (9 services), Makefile, DB migrations, CI pipeline, ADRs, README.
Then **pulse-ciso**: review security foundation (RLS, secrets, headers, Trivy, non-root Docker).
Then **pulse-test-engineer**: test infrastructure, fixtures, CI quality gates.

## Phase 2 — Data Pipeline
**pulse-data-engineer**: ConfigLoaderService, DevLake bootstrap, sync worker, metrics worker, Kafka topics.
**pulse-data-scientist**: metric calculation formulas (provide to data-engineer).
**pulse-test-engineer**: pipeline integration tests, data accuracy tests (TDD for metrics).

## Phase 3 — Metrics + Dashboards
**pulse-data-scientist**: validate formulas and visualization specs.
**pulse-engineer**: API routes + React dashboard pages.
**pulse-frontend**: prototype pages (if needed).
**pulse-test-engineer**: E2E journeys, visual regression, a11y.
**pulse-product-director**: validate against acceptance criteria.

## Verify per phase
- Phase 1: `docker compose up` works, health 200, CI passes
- Phase 2: Data flows DevLake→Kafka→PULSE DB, metrics calculated correctly
- Phase 3: API returns metrics, dashboards render, E2E pass
