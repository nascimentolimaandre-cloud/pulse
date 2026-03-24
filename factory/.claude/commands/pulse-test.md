---
description: Run or write tests. Supports TDD workflow. Routes to pulse-test-engineer.
argument-hint: <scope> (e.g., "dora", "lean", "api", "web", "e2e", "all")
---
# PULSE Tests — Scope: **$ARGUMENTS**

Delegate to **pulse-test-engineer**.

**Metric scopes** (dora, lean, cycle-time, throughput, sprint): TDD — write tests FIRST in `tests/unit/test_<scope>.py`, then implement to make them pass. Target ≥95%.

**API scope**: Integration tests with Testcontainers. `pytest tests/integration -v`. Target ≥70%.

**Web scope**: `npx vitest run`. Component + hook tests. Target ≥80%.

**E2E scope**: `npx playwright test`. 5 critical journeys (Home, DORA, Filter, Lean, PRs).

**All scope**: `make test` — lint + unit + integration for all packages.

**TDD order**: Write test (RED) → Implement (GREEN) → Refactor (keep GREEN).
