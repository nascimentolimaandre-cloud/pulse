---
description: Implement a feature or user story end-to-end, coordinating across agents. Use with story IDs or feature names.
argument-hint: <story-id-or-feature> (e.g., "MVP-2.1.1", "DORA metrics", "CFD component")
---
# Implement: **$ARGUMENTS**

## 1. Check MVP Scope
Verify feature is tagged MVP. If R1+ — STOP and inform user.

## 2. Sequence agents

**For a full-stack metric feature:**
1. `pulse-data-scientist` → Define formula, thresholds, edge cases, visualization type
2. `pulse-test-engineer` → Write metric tests FIRST (TDD)
3. `pulse-data-engineer` → Pipeline: schema, worker logic, Kafka events
4. `pulse-engineer` → API route + React page + hook
5. `pulse-test-engineer` → Integration + E2E tests
6. `pulse-frontend` → Prototype page update (if needed)
7. `pulse-ciso` → Security review of data flow

**For a frontend-only feature:**
1. `pulse-product-director` → Spec + acceptance criteria (if missing)
2. `pulse-engineer` → React implementation
3. `pulse-frontend` → Prototype (if needed)
4. `pulse-test-engineer` → Component + E2E tests

**For a data pipeline feature:**
1. `pulse-data-engineer` → Pipeline implementation
2. `pulse-test-engineer` → Integration tests
3. `pulse-ciso` → Security review (metadata-only enforcement)

## 3. Verify
- Tests pass, API returns correct shape, frontend renders, no MVP violations.
