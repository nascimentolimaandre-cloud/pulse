# ADR-005: Polyglot Backend -- NestJS for CRUD, FastAPI for Data

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE has two distinct backend workloads:

1. **CRUD/Application layer** -- Organizations, teams, integrations, connections, notifications. Standard REST resources with validation, guards, and relational queries.
2. **Data/Analytics layer** -- Metric calculations (DORA, Lean, Sprint), time-series queries, statistical functions, and future ML/forecasting features.

A single language could serve both, but each workload has a natural ecosystem fit. Node.js/TypeScript excels at structured API development with strong typing and decorator-based DI. Python excels at data manipulation with libraries like pandas, numpy, scipy, and the broader ML/data science ecosystem.

## Decision

Use two backend runtimes unified behind AWS API Gateway:

- **NestJS 10+ (TypeScript)** for `pulse-api`: Identity, Integration, and Notification bounded contexts. Runs as a Lambda via `@vendia/serverless-express`.
- **FastAPI (Python 3.12+)** for `pulse-data`: Engineering Data and Metrics bounded contexts, plus worker functions. Runs as a Lambda via Mangum adapter.

API Gateway routes `/api/v1/*` to the NestJS Lambda and `/data/v1/*` to the FastAPI Lambda. The frontend sees a single origin; the polyglot split is invisible to clients.

## Consequences

**Positive:**
- Each runtime plays to its strengths: TypeScript for structured APIs, Python for data and analytics.
- Python data ecosystem (pandas, numpy, scipy) is available natively for metric calculations and future ML features.
- Teams can hire specialists for each domain rather than requiring full-stack polyglot developers.
- API Gateway provides a single entry point, hiding the polyglot implementation.

**Negative:**
- Two runtimes means two dependency management systems (npm + pip), two linting configs (ESLint + Ruff), and two test frameworks (Jest + Pytest).
- Shared types between NestJS and FastAPI require a separate `pulse-shared` package (TypeScript) and Pydantic models (Python) that must stay in sync.
- Onboarding new developers requires familiarity with both ecosystems.
- CI pipeline is more complex, building and testing two different runtimes.
