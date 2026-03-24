---
description: Review code quality. Routes to the correct agent based on review type.
argument-hint: [path-or-review-type] (e.g., "pulse-ui/", "packages/", "security", "data-quality")
---
# Review: **$ARGUMENTS**

## Routing
- **pulse-ui/** → `pulse-frontend`: design tokens, semantic HTML, a11y, skeleton states
- **packages/** → `pulse-engineer`: architecture compliance, TypeScript strict, Python types, DDD boundaries
- **security** → `pulse-ciso`: RLS, secrets, headers, container security, metadata-only enforcement
- **data-quality** → `pulse-data-engineer`: pipeline idempotency, schema versioning, data observability
- **metrics** → `pulse-data-scientist`: formula correctness, anti-surveillance, edge cases
- **tests** → `pulse-test-engineer`: coverage, flakiness, TDD compliance, fixture quality

## Output: File:Line | Category | Severity (Critical/Warning/Suggestion) | Fix. Summary with quality score 0-100.
