# ADR-009: Single Monorepo with Shared Types

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE consists of four packages (pulse-api, pulse-data, pulse-web, pulse-shared), infrastructure configuration, documentation, and CI/CD pipelines. The codebase could be organized as separate repositories per package (polyrepo) or a single repository containing everything (monorepo).

With a small team and frequent cross-cutting changes (e.g., adding a new metric touches the Python calculation, NestJS API route, TypeScript types, and React dashboard page), polyrepo would mean coordinating multiple PRs across repositories for a single feature.

## Decision

Organize all code in a single monorepo under `pulse/`:

```
pulse/
  packages/
    pulse-api/        # NestJS (TypeScript)
    pulse-data/       # FastAPI (Python)
    pulse-web/        # React + Vite (TypeScript)
    pulse-shared/     # Shared TypeScript types and schemas
  infra/              # Terraform, Docker configs
  config/             # connections.yaml, seed data
  docs/               # ADRs, architecture documentation
  docker-compose.yml
  Makefile
  .github/workflows/
```

The `pulse-shared` package exports TypeScript interfaces and Zod schemas consumed by both pulse-api and pulse-web. Python Pydantic models in pulse-data are maintained separately but aligned with shared type definitions.

CI runs a unified pipeline that detects which packages changed and runs only the relevant lint, test, and build steps.

## Consequences

**Positive:**
- Atomic PRs: a feature spanning API + frontend + types ships as one reviewable change.
- Shared types in `pulse-shared` prevent drift between frontend and backend contracts.
- Single CI pipeline simplifies build configuration and ensures cross-package compatibility.
- Refactoring across packages is straightforward with full-repo search and replace.

**Negative:**
- CI must be smart about change detection to avoid rebuilding everything on every commit.
- Repository size grows over time; clone times increase (mitigated by shallow clones in CI).
- Python and TypeScript tooling coexist in the same repo, requiring clear directory boundaries to avoid confusion.
- Independent package versioning and deployment requires per-package build scripts.
