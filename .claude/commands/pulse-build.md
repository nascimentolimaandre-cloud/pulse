---
description: Build a PULSE component, page, service, or pipeline element. Routes to the correct agent based on what's being built.
argument-hint: <what-to-build> (e.g., "metric-card prototype", "DORA api route", "sync worker", "DORA formula")
---
# Build PULSE Element

Target: **$ARGUMENTS**

## Routing

**→ `pulse-product-director`** if: feature spec, persona story, BDD criteria, pricing, UX pattern
**→ `pulse-ux-reviewer`** if: UX/UI review of a page or journey, 3-concept exploration, design editorial hand-off (delivers HTML/CSS/JS + impl spec + FDD backlog)
**→ `pulse-frontend`** if: pulse/pulse-ui/, prototype, HTML/CSS/JS, Chart.js, design tokens
**→ `pulse-engineer`** if: packages/, NestJS, FastAPI, React+Vite, Docker, CI/CD, migrations, Makefile
**→ `pulse-data-engineer`** if: DevLake, Kafka, sync worker, metrics worker, DB schema, pipeline, connectors
**→ `pulse-data-scientist`** if: metric formula, classification thresholds, visualization type, statistical model
**→ `pulse-test-engineer`** if: test, TDD, fixture, factory, Playwright, coverage, CI gate
**→ `pulse-ciso`** if: security review, IAM, encryption, RLS audit, container hardening, compliance

If ambiguous, ask: "Which domain does this belong to?"

## Protocol
Include in delegation: scope (files), spec reference, dependencies, acceptance criteria, MVP constraints.
