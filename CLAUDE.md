# PULSE — Engineering Intelligence Platform

## CRITICAL SAFETY RULES

**NEVER modify, trigger, create, delete, or execute ANY action on external systems (Jenkins, Jira, GitHub, DevLake instances, etc.) in production or staging environments.** PULSE agents are READ-ONLY consumers of external systems. All interactions with Jenkins, Jira, GitHub APIs etc. must be limited to **read/query operations only** (GET requests, API reads, listing jobs, fetching build info). Never POST, PUT, DELETE, or trigger builds/pipelines/deployments on any external system.

## Project Overview

PULSE is an Engineering Intelligence SaaS providing DORA, Lean/Agile, and Sprint analytics. The project has two parallel workstreams: a high-fidelity HTML/CSS/JS prototype and a full production stack.

## Directory Structure

```
02 - Main Application/                   ← Git root, Claude Code runs HERE
├── .git/
├── .gitignore
├── CLAUDE.md                            ← This file (orchestrator)
├── .claude/                             ← Agents, commands, skills
│
├── factory/                             ← Reference & documentation (read-only)
│   ├── agents/                          (original agent prompts — read-only reference)
│   ├── commands/                        (original command files — read-only reference)
│   ├── skills/                          (original skill files — read-only reference)
│   ├── MANUAL.md                        (usage manual)
│   └── README.md                        (architecture docs)
│
└── pulse/                               ← ALL CODE GOES HERE (deployable)
    ├── pulse-ui/                        (HTML/CSS/JS prototype)
    ├── packages/                        (production code)
    │   ├── pulse-api/                   (NestJS)
    │   ├── pulse-data/                  (FastAPI)
    │   ├── pulse-web/                   (React + Vite)
    │   └── pulse-shared/               (TypeScript types)
    ├── infra/                           (Terraform)
    ├── config/                          (connections.yaml)
    ├── docs/                            (ADRs, architecture)
    ├── docker-compose.yml
    ├── Makefile
    ├── .github/workflows/
    └── README.md
```

**CRITICAL PATH RULE:** All code, configs, and application files MUST be created inside `pulse/`. Never write application files to the root or to `factory/`.

## Team — 8 Specialized Agents

```
                              ┌─────────────────────────┐
                              │      ORCHESTRATOR        │
                              │     (main session)       │
                              │                          │
                              │  Architecture decisions  │
                              │  Task breakdown & plan   │
                              │  Git & PR coordination   │
                              │  Cross-agent conflicts   │
                              └────────┬────────────────-┘
           ┌───────────┬───────────┬───┼──────┬───────────┬──────────┐
           ▼           ▼           ▼   ▼      ▼           ▼          ▼
    ┌────────────┐┌──────────┐┌─────────┐┌────────┐┌──────────┐┌──────────┐┌────────────┐
    │  product-  ││ frontend ││   ux-    ││engineer││  data-   ││  data-   ││   test-    │
    │  director  ││          ││ reviewer ││        ││ engineer ││scientist ││  engineer  │
    │            ││HTML/CSS/ ││          ││NestJS  ││Pipelines ││Analytics ││QA & auto-  │
    │Strategy,   ││JS proto  ││Principal ││FastAPI ││DevLake   ││ML models ││mation      │
    │UX, specs   ││Chart.js  ││designer  ││React   ││Kafka     ││Metrics   ││Playwright  │
    │pricing     ││pulse-ui/ ││concepts+ ││Docker  ││Schema    ││formulas  ││coverage    │
    │            ││          ││specs+FDD ││        ││          ││          ││            │
    └────────────┘└──────────┘└─────────┘└────────┘└──────────┘└──────────┘└────────────┘
                                                                                 │
                                                                      ┌──────────┘
                                                                      ▼
                                                               ┌────────────┐
                                                               │    ciso     │
                                                               │Security,   │
                                                               │compliance, │
                                                               │IAM, WAF    │
                                                               └────────────┘
```

## Routing Rules — FOLLOW STRICTLY

**ALL paths below are relative to `pulse/`.**

### `pulse-product-director` — Strategy, specs, UX design
- Product spec updates, feature definitions, persona stories
- Pricing strategy, competitive analysis, GTM
- Information architecture, UX patterns, wireframe specs
- Release planning, scope changes, hypothesis definitions
- BDD acceptance criteria authoring
- Design system direction (not implementation)
- Analytics event definitions, North Star metrics

### `pulse-frontend` — HTML/CSS/JS prototype
- Anything inside `pulse/pulse-ui/`
- Chart.js visualizations, sparklines, vanilla JavaScript
- Design tokens implementation (tokens.css), utilities, animations
- Skeleton states, empty states, transitions in the prototype
- Accessibility (WCAG AA) in the prototype

### `pulse-ux-reviewer` — Principal designer / UX & UI review (global)
- Review or redesign the UX/UI of any PULSE page, journey, component or state
- Produces **three editorial concepts** + final recommendation with 3 pre-dev adjustments
- Always delivers the three mandatory artefacts:
  1. Runnable frontend code (HTML/CSS/JS) under `pulse/pulse-ui/`
  2. Implementation spec at `pulse/docs/ux-specs/<page>-impl-spec.md` (hand-off to `pulse-engineer`)
  3. FDD backlog at `pulse/docs/backlog/<page>-backlog.md` (hand-off to `pulse-product-director`)
- Enforces: real-scale design (283 repos / 69 projects / 373k issues), WCAG AA,
  anti-surveillance, all 6 states (loading / empty / healthy / degraded / error / partial),
  responsive (desktop ≥1280 / tablet / mobile), PT-BR copy, tokens-only (no hardcoded hex)
- Invoke via `/pulse-ux-review <page-or-journey>`

### `pulse-engineer` — Full-stack production code
- Anything inside `pulse/packages/`
- NestJS modules, FastAPI routes, React+Vite components/routes
- `pulse/docker-compose.yml`, Dockerfiles, Makefile
- Database migrations (TypeORM, Alembic)
- CI/CD pipelines (`pulse/.github/workflows/`)
- ADR documents, README

### `pulse-data-engineer` — Data platform & pipelines
- DevLake configuration, plugins, blueprint management
- Kafka topics, producers, consumers, schema design
- Sync Worker (DevLake → normalize → Kafka)
- Metrics Worker (Kafka → calculate → DB)
- Database schema design, indexes, materialized views
- Data quality validation, pipeline monitoring
- Connector implementation (GitHub, Jira, GitLab, ADO)
- ETL/ELT patterns, incremental sync, watermarks

### `pulse-data-scientist` — Analytics, ML, metrics math
- DORA metric formulas and classification logic
- Lean metric calculations (CFD, WIP, Lead Time Distribution, Scatterplot)
- Cycle Time breakdown math, Sprint metrics
- Statistical analysis, anomaly detection (R1+)
- Monte Carlo simulation for forecasting (R2+)
- AI/LLM features strategy (R4+)
- Visualization recommendations (which chart for which data)
- Anti-surveillance validation on all metrics

### `pulse-test-engineer` — QA & test automation
- Test strategy and pyramid design
- Unit tests for metrics (TDD — write FIRST)
- Integration tests with Testcontainers
- E2E tests with Playwright
- Performance benchmarks with k6
- Accessibility audits (axe-core)
- Visual regression tests
- CI quality gates
- Test data factories and fixtures

### `pulse-ciso` — Security & compliance
- Security architecture review per release
- IAM design, RBAC policies, RLS enforcement
- Secrets management (local .env → AWS Secrets Manager)
- Metadata-only enforcement (NEVER source code)
- Container security (Trivy, non-root, read-only)
- Security headers (Helmet.js, HSTS, CSP)
- WAF, DDoS protection, VPC hardening (R2+)
- SOC 2 Type II, GDPR, LGPD compliance roadmap (R4)
- Incident response plan

### MAIN SESSION (do NOT delegate)
- Architecture decisions affecting multiple bounded contexts
- Task breakdown, sprint planning, prioritization
- Git operations, branching, PR creation
- Cross-agent coordination and conflict resolution
- Phase planning (Phase 1 → 2 → 3)
- Top-level documentation

## Delegation Protocol

When delegating to ANY agent, include:

1. **Phase** — Which build phase (1: Bootstrap, 2: Pipeline, 3: Metrics+Dashboards)
2. **Scope** — Exact files/directories to create or modify (always under `pulse/`)
3. **Spec reference** — Doc section, epic, or story ID
4. **Dependencies** — Existing files to read first
5. **Acceptance criteria** — What "done" looks like
6. **Constraints** — MVP scope boundaries (what NOT to build)

## Cross-Agent Coordination

### Full-stack feature (e.g., "DORA metrics end-to-end"):
1. `pulse-data-scientist` → Define formulas, thresholds, edge cases
2. `pulse-data-engineer` → Pipeline: DevLake → Kafka → metrics_snapshots
3. `pulse-engineer` → API routes + React pages
4. `pulse-test-engineer` → TDD for calculations, integration + E2E tests
5. `pulse-frontend` → Prototype update (if needed)
6. `pulse-ciso` → Security review of data flow

### New feature spec:
1. `pulse-product-director` → Feature definition, persona, BDD criteria
2. `pulse-data-scientist` → Analytics model, visualization recommendation
3. Then implementation agents in sequence above

### UX/UI review or redesign of a page/journey:
1. `pulse-ux-reviewer` → 3 concepts + recommendation + runnable HTML/CSS/JS in
   `pulse/pulse-ui/` + impl spec in `pulse/docs/ux-specs/` + FDD backlog in
   `pulse/docs/backlog/`
2. `pulse-product-director` → Prioritise the FDD backlog against the release plan
3. `pulse-engineer` → Consume the impl spec, break HTML into design-system
   components, implement in `pulse/packages/pulse-web/`
4. `pulse-test-engineer` → a11y audit (axe-core), visual regression, E2E journey

### Security review:
1. `pulse-ciso` → Review architecture, identify risks
2. `pulse-engineer` → Implement security controls
3. `pulse-test-engineer` → Security test automation

## Phase Plan

### Phase 1 — Infrastructure Bootstrap
- `pulse-engineer`: Monorepo, Docker, Makefile, skeletons, migrations, CI
- `pulse-ciso`: Security foundation (RLS, secrets, headers, Trivy)
- `pulse-test-engineer`: Test infrastructure, fixtures, CI quality gates

### Phase 2 — Data Pipeline (Epic 1)
- `pulse-data-engineer`: DevLake bootstrap, sync worker, metrics worker, Kafka
- `pulse-data-scientist`: Metric calculation formulas (TDD)
- `pulse-test-engineer`: Pipeline integration tests, data accuracy tests

### Phase 3 — Metrics + Dashboards (Epics 2-3)
- `pulse-engineer`: API routes + React dashboard pages
- `pulse-frontend`: Prototype pages
- `pulse-test-engineer`: E2E journeys, visual regression, a11y
- `pulse-product-director`: Validate against acceptance criteria

## Context Documents

Reference docs (read from `factory/` or `pulse/docs/`):
- `pulse/docs/frontend-design-doc.md` — Design tokens, component specs, wireframes
- `pulse/docs/revised-releases.md` — MVP scope, epic/story mapping, BDD criteria
- `pulse/docs/product-spec.md` — Feature descriptions, personas, pricing
- `pulse/docs/tech-architecture.md` — Tech decisions, DB schema, API contracts
- `pulse/docs/architecture-analysis.md` — Data architecture decision (DevLake hybrid)
- `pulse/docs/devex-market-research.md` — Competitive landscape, positioning
- `pulse/docs/deep-dive-features.md` — Competitor feature deep dive

## Key Commands

```bash
# Run from pulse/
cd pulse

make up              # Start Docker services
make test            # Run all tests
make test-unit       # Fast unit tests only
make migrate         # Run DB migrations
make logs            # Tail service logs
make setup           # First-time setup

cd packages/pulse-web && npm run dev   # Vite on :5173
cd pulse-ui && python3 -m http.server 8080   # Prototype
```
