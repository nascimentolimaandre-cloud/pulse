---
name: pulse-test-engineer
description: PULSE testing context. Use when writing tests, designing test strategy, or configuring CI quality gates.
---
# PULSE Test Engineer Skill
## Pyramid: Unit 70% (Vitest/Pytest) → Integration 25% (Testcontainers) → E2E 5% (Playwright).
## Coverage: Metrics ≥95% TDD, Components ≥80%, API routes ≥80%, Integration ≥70%.
## 5 E2E Journeys: Home dashboard, DORA drill-down, Filter flow, Lean metrics, PR review.
## Factories: createPullRequest(), createIssue(), createDeployment(), createSprint(). Known inputs → expected outputs.
## CI Gates: Lint → Unit → Integration → Build → Security (Trivy) → E2E smoke.
## Tools: Vitest (TS), Pytest (Python), Jest+Supertest (NestJS integration), Playwright (E2E), k6 (perf), axe-core (a11y).
## Anti-surveillance: Test that NO endpoint returns individual dev rankings.
