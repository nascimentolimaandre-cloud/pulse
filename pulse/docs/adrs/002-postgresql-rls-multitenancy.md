# ADR-002: PostgreSQL Row-Level Security for Multi-Tenancy

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE is a multi-tenant SaaS platform. Each customer (organization) must see only their own data. The three common approaches are: database-per-tenant (expensive to operate at scale), schema-per-tenant (migration complexity grows linearly), and shared-schema with row-level isolation.

We need tenant isolation that is secure by default, simple to implement, and cost-effective for a startup that may have 50+ tenants on a single RDS instance.

## Decision

Use PostgreSQL Row-Level Security (RLS) on a shared schema. Every tenant-scoped table includes an `organization_id` column. RLS policies restrict all SELECT, INSERT, UPDATE, and DELETE operations to rows matching the current tenant.

The tenant context is set per-request via:

```sql
SET app.current_tenant = '<organization_id>';
```

This is executed by middleware (NestJS guard / FastAPI middleware) at the start of every database transaction, before any query runs. The RLS policy references `current_setting('app.current_tenant')` to filter rows transparently.

In the MVP, a single default tenant is seeded from YAML configuration. Multi-tenant onboarding is deferred to R2+.

## Consequences

**Positive:**
- Tenant isolation is enforced at the database level, making it impossible to leak data even if application code has bugs.
- Single schema means one set of migrations for all tenants.
- No additional infrastructure cost: RLS is a built-in PostgreSQL feature.
- Queries remain simple; developers write normal SQL without WHERE tenant filters.

**Negative:**
- Forgetting to set `app.current_tenant` before a query would either fail (if enforced) or return no rows, requiring careful middleware design.
- RLS adds a small query planning overhead, though negligible for our scale.
- Noisy-neighbor risk on shared resources (mitigated by query timeouts and connection limits per tenant in R2+).
