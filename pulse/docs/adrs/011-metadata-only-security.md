# ADR-011: Metadata-Only -- Never Store Source Code

**Status:** Accepted
**Date:** 2026-03-24

## Context

Engineering intelligence platforms must access development tool APIs to calculate metrics. This access could potentially expose sensitive intellectual property: source code, code diffs, commit message contents with business logic details, or secret values in configuration files.

Competitors that store source code face significant enterprise sales friction: security reviews are longer, compliance teams raise red flags, and some organizations outright reject tools that touch code. PULSE can turn this into a competitive advantage.

## Decision

PULSE stores only metadata. The system never persists, caches, or transmits source code, file contents, or code diffs. Specifically:

**What we store:**
- PR titles, PR numbers, branch names, merge timestamps, review counts
- Commit hashes (SHA), commit timestamps, author identifiers
- Issue keys, issue statuses, status transition timestamps, sprint assignments
- Deployment identifiers, deployment timestamps, success/failure status
- Repository names, organization identifiers

**What we never store:**
- Source code or file contents
- Code diffs or patches
- Commit message bodies (only hashes and timestamps)
- File paths within repositories
- Secret values, tokens, or credentials in any data table

This constraint is enforced at multiple levels: DevLake blueprint configuration (scope what is synced), Sync Worker transformation (strip any code-adjacent fields), and database schema design (no columns for code content).

## Consequences

**Positive:**
- Dramatically faster enterprise security reviews: no code access means minimal risk profile.
- Compliance with strict data governance policies (finance, healthcare, government sectors).
- Reduced storage costs and smaller database footprint.
- Clear differentiator against competitors who store code (Swarmia, LinearB).
- Simplifies GDPR/LGPD compliance since no personal intellectual property is retained.

**Negative:**
- Some advanced features become impossible: code churn analysis, complexity metrics, hot-file detection, AI code review summaries.
- Debugging data quality issues is harder without access to the source material.
- Marketing must clearly communicate what PULSE can and cannot analyze.
