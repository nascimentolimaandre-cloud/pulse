# PULSE -- Engineering Intelligence Platform

PULSE provides DORA, Lean/Agile, and Sprint analytics to help engineering teams measure and improve their delivery performance. It aggregates data from GitHub, GitLab, Jira, and Azure DevOps via Apache DevLake, calculates industry-standard metrics, and presents them in actionable dashboards.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker + Docker Compose | 24+ / v2+ | https://docs.docker.com/get-docker/ |
| Node.js | 20 LTS | https://nodejs.org/ |
| Python | 3.12+ | https://www.python.org/downloads/ |
| Make | any | Pre-installed on macOS/Linux |

## Quick Start

```bash
# 1. Clone and enter the project
cd pulse

# 2. First-time setup (installs deps, copies .env, starts Docker, runs migrations)
make setup

# 3. Start frontend dev server (separate terminal)
make dev

# 4. Open in browser
#    Frontend:  http://localhost:5173
#    API:       http://localhost:3000/health
#    Data API:  http://localhost:8000/health
#    DevLake:   http://localhost:8080
```

## Architecture Overview

```
                  Browser (:5173)
                      |
               Vite Dev Server
              (React 19 + Tailwind)
                /           \
    NestJS API (:3000)   FastAPI (:8000)
    [Identity, Integration]  [Metrics, Eng Data]
         |          |              |
    PostgreSQL   Redis          Kafka (KRaft)
      (:5432)   (:6379)        (:9092)
                                  |
                          +-------+-------+
                          |               |
                    Sync Worker    Metrics Worker
                          |
                    Apache DevLake (:8080)
                          |
                    DevLake PG (:5433)
```

**Bounded Contexts:**

| Context | Service | Tech | Responsibility |
|---------|---------|------|----------------|
| BC1 Identity | pulse-api | NestJS | Organizations, teams, memberships |
| BC2 Integration | pulse-api | NestJS | Connections, DevLake config, YAML loading |
| BC3 Engineering Data | pulse-data | FastAPI | Pull requests, issues, deployments, sprints |
| BC4 Metrics | pulse-data | FastAPI | DORA, Lean, Sprint metric calculations |

## Development Commands

| Command | Description |
|---------|-------------|
| `make up` | Start all backend services (Docker) |
| `make down` | Stop all services |
| `make dev` | Start frontend dev server (Vite on :5173) |
| `make logs` | Tail logs from all Docker services |
| `make test` | Run all tests (unit + integration) |
| `make test-unit` | Run unit tests only (Jest + Pytest + Vitest) |
| `make test-integration` | Run integration tests (spins up test containers) |
| `make migrate` | Run database migrations (TypeORM + Alembic) |
| `make seed` | Seed database from config/connections.yaml |
| `make lint` | Run all linters (ESLint + Ruff) |
| `make fmt` | Format all code (Prettier + Black + Ruff) |
| `make build` | Build all packages + Docker images |
| `make clean` | Stop services and remove all volumes |
| `make setup` | First-time setup (install, start, migrate) |

## Running Tests

```bash
# All tests
make test

# Unit tests only (fast, no Docker needed for these)
make test-unit

# Integration tests (starts ephemeral Docker services)
make test-integration

# Individual packages
cd packages/pulse-api && npm run test
cd packages/pulse-data && python -m pytest tests/unit -v
cd packages/pulse-web && npm run test
```

## Project Structure

```
pulse/
├── packages/
│   ├── pulse-api/          # NestJS API (BC1 Identity + BC2 Integration)
│   ├── pulse-data/         # FastAPI (BC3 Eng Data + BC4 Metrics) + Workers
│   ├── pulse-web/          # React 19 + Vite 6 SPA
│   └── pulse-shared/       # Shared TypeScript types (@pulse/shared)
├── pulse-ui/               # HTML/CSS/JS prototype (Chart.js)
├── config/
│   └── connections.yaml    # MVP integration configuration
├── docs/                   # Architecture docs, ADRs
├── infra/                  # Terraform (future)
├── .github/workflows/      # CI/CD pipelines
├── docker-compose.yml      # Local development stack
├── docker-compose.test.yml # CI integration test stack
├── Makefile                # Development commands
└── .env.example            # Environment variable template
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your connector tokens:

```bash
cp .env.example .env
```

At minimum, set `GITHUB_TOKEN` (or whichever source you want to connect) to start pulling data.

## Key Design Decisions

- **Kafka runs in KRaft mode** -- no Zookeeper dependency
- **Frontend runs outside Docker** for instant Vite HMR (hot module replacement)
- **Single PostgreSQL database** with Row-Level Security (RLS) for multi-tenancy
- **DevLake** handles the heavy lifting of pulling data from source systems
- **Workers** (sync + metrics) are separate processes sharing the pulse-data image
- **No auth in MVP** -- single default tenant, seeded from YAML config
