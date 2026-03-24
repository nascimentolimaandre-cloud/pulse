# ADR-001: Modular Monolith in 2 Lambda Functions

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE needs to serve multiple bounded contexts (Identity, Integration, Engineering Data, Metrics) from day one. The team is small and velocity matters more than premature decomposition. Microservices would add network hops, deployment complexity, and operational overhead that a pre-product-market-fit startup cannot afford.

At the same time, we need clear boundaries so that extraction into separate services is straightforward when scale demands it.

## Decision

Deploy PULSE as a modular monolith packaged into two AWS Lambda functions:

- **pulse-api (NestJS):** Identity, Integration, and Notification modules. Handles CRUD operations, connection management, and organizational data.
- **pulse-data (FastAPI):** Engineering Data and Metrics contexts. Handles data queries, metric calculations, and serving analytics to the frontend.

Each bounded context lives in its own module/context directory with explicit interfaces. Cross-context communication happens through well-defined internal interfaces, not direct imports of internal classes. API Gateway routes requests to the appropriate Lambda based on path prefix (`/api/v1/*` vs `/data/v1/*`).

When a module outgrows its host Lambda, extraction requires only: creating a new Lambda, moving the module, and adding an API Gateway route. No code rewrite needed.

## Consequences

**Positive:**
- Minimal operational overhead: 2 deployable units instead of 5+.
- Shared database simplifies transactions during MVP.
- DDD module boundaries enforce separation without network overhead.
- Extraction to independent services is incremental and low-risk.

**Negative:**
- A bug in one module can affect the entire Lambda function.
- Deployment couples all modules within a Lambda (one change redeploys everything).
- Developers must maintain discipline to not violate module boundaries since there is no network enforcing isolation.
