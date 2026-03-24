# ADR-013: RDS Proxy Mandatory for Lambda Connection Pooling

**Status:** Accepted
**Date:** 2026-03-24

## Context

AWS Lambda functions are ephemeral: each invocation may run in a new execution environment, and concurrent invocations run in separate environments. Each environment opens its own database connection. PostgreSQL has a hard limit on concurrent connections (default ~100 for db.t4g.micro), and Lambda can easily exhaust this limit during traffic spikes.

Without connection pooling, 100 concurrent Lambda invocations would open 100 database connections. A traffic burst could exceed PostgreSQL's connection limit, causing connection refused errors and cascading failures across all Lambda functions sharing the database.

## Decision

RDS Proxy is mandatory for all Lambda-to-PostgreSQL communication. Both pulse-api and pulse-data Lambda functions connect to the RDS Proxy endpoint instead of the RDS instance directly.

RDS Proxy provides:
- **Connection pooling:** Multiplexes hundreds of Lambda connections into a small pool of persistent database connections.
- **Connection reuse:** Lambda execution environments that are reused (warm starts) benefit from already-established proxy connections.
- **Graceful failover:** During RDS failover events, RDS Proxy routes connections to the new primary automatically, reducing failover downtime from minutes to seconds.

The Sync Worker and Metrics Worker Lambdas also connect through RDS Proxy, since they can scale with event volume and create concurrent connections.

## Consequences

**Positive:**
- Eliminates connection exhaustion: RDS Proxy can handle thousands of concurrent Lambda connections with a pool of 10-20 actual database connections.
- Reduces Lambda cold-start latency: establishing a connection to RDS Proxy is faster than a full TLS handshake to RDS.
- Automatic failover improves availability during RDS maintenance windows.
- IAM authentication support allows Lambdas to authenticate to the database without storing credentials.

**Negative:**
- Additional cost of approximately $15/month for the smallest configuration.
- Adds a network hop between Lambda and RDS, introducing 1-2ms of additional latency per query (negligible for our use case).
- Some PostgreSQL features (e.g., advisory locks, session-level settings) behave differently through RDS Proxy due to connection multiplexing. The `SET app.current_tenant` for RLS must be issued per-transaction, not per-session.
- RDS Proxy configuration adds complexity to the infrastructure setup.
