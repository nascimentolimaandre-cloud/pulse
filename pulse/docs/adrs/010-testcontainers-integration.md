# ADR-010: Testcontainers for Integration Testing

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE's integration tests need to verify behavior against real PostgreSQL (with RLS policies, migrations, and indexes) and real Kafka (with topic creation, serialization, and consumer group behavior). Mocking these dependencies in tests leads to false confidence -- a test might pass with a mock but fail against the real service due to SQL dialect differences, RLS enforcement, or Kafka serialization issues.

The alternatives are: shared test databases (flaky, state leaks between tests), Docker Compose in CI (slow startup, hard to parallelize), or Testcontainers (ephemeral containers per test suite).

## Decision

Use Testcontainers for all integration tests across both runtimes:

- **Python (Pytest):** `testcontainers-python` spins up PostgreSQL 16 and Kafka containers. Each test suite gets a fresh database with migrations applied. Tests run against real RLS policies.
- **TypeScript (Jest):** `@testcontainers/postgresql` and `@testcontainers/kafka` provide the same ephemeral container lifecycle for NestJS integration tests.

Containers are started once per test suite (not per test) and torn down after the suite completes. Database state is reset between tests using transaction rollback or truncation.

## Consequences

**Positive:**
- Tests run against real PostgreSQL with real RLS policies, catching issues that mocks would miss.
- Tests run against real Kafka, validating serialization, topic routing, and consumer behavior.
- Each test suite is isolated: no shared state, no flaky failures from parallel runs.
- Same test code runs locally and in CI with no configuration changes.

**Negative:**
- Integration tests are slower than unit tests (container startup adds 5-10 seconds per suite).
- CI runners need Docker-in-Docker or a Docker socket, which adds CI configuration complexity.
- Testcontainers requires Docker Desktop (or compatible runtime) on developer machines.
- Resource-intensive: running many test suites in parallel may exhaust CI runner memory.
