# ADR-003: Apache DevLake as Internal Pipeline Engine

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE needs to ingest, normalize, and unify data from GitHub, GitLab, Jira, and Azure DevOps. Three approaches were evaluated (documented in architecture-analysis.md):

1. **DevLake as Data Core** -- Use DevLake end-to-end, including its database as the application store. Blocked by DevLake's lack of native multi-tenancy.
2. **Build from scratch (AWS-native)** -- Custom connectors for every source. Estimated 28-38 weeks for the data layer alone, far exceeding the 12-16 week MVP target.
3. **Hybrid: DevLake as accelerator** -- Use DevLake exclusively for ingestion and normalization, then ETL the domain-layer data into PULSE's own multi-tenant PostgreSQL database.

Hypothesis 3 scored highest across time-to-MVP, extensibility, and risk balance.

## Decision

Adopt the hybrid approach (Hypothesis 3). DevLake runs as an internal pipeline engine on ECS Fargate. It ingests raw data from source tools via its mature plugin system (GitHub, GitLab, Jira, Azure DevOps) and normalizes it into its domain layer schema.

A Sync Worker (Lambda, cron every 15 minutes) reads DevLake's domain layer tables, transforms records into PULSE's own schema with `organization_id`, and publishes events to Kafka. The user never interacts with DevLake directly; PULSE's backend configures DevLake programmatically via its REST API.

This gives us an exit strategy: any DevLake plugin can be replaced by a custom connector that writes directly to Kafka, with zero impact on downstream consumers.

## Consequences

**Positive:**
- Four production-ready connectors from day one, saving 12-16 weeks of connector development.
- DevLake's domain model covers approximately 80% of our MVP data needs.
- Exit strategy is built-in: DevLake is behind an abstraction boundary and can be replaced incrementally.
- DORA metrics are partially pre-calculated in DevLake, useful for validation.

**Negative:**
- Additional moving part: DevLake container + its own PostgreSQL database.
- Dependency on an Apache Incubator project; if the project loses momentum, we carry maintenance risk.
- ETL from DevLake DB to PULSE DB adds latency (mitigated by 15-minute sync cycle being acceptable for analytics).
- DevLake's Go codebase is outside the team's primary expertise.
