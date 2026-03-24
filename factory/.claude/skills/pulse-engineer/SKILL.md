---
name: pulse-engineer
description: PULSE production engineering context. Use when working on packages/, Docker, CI/CD, migrations.
---
# PULSE Engineer Skill
## Monorepo: packages/pulse-api (NestJS), pulse-data (FastAPI), pulse-web (React+Vite), pulse-shared (types).
## Docker Services (9): pulse-api(:3000), pulse-data(:8000), sync-worker, metrics-worker, postgres(:5432), redis(:6379), kafka(:9092), devlake(:8080,:4000), devlake-pg(:5433). pulse-web runs OUTSIDE Docker.
## Phases: 1-Bootstrap (skeleton+Docker+CI), 2-Pipeline (DevLake+Kafka+workers), 3-Dashboards (API+React pages).
## DB: TypeORM migrations for IAM tables (pulse-api). Alembic for eng_* + metrics_snapshots (pulse-data). ALL tables have tenant_id + RLS.
## MVP: NO login/auth, NO onboarding, NO settings UI. Home dashboard is entry point.
