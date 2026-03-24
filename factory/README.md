# PULSE — Claude Code Multi-Agent Setup (7 Agents)

## Architecture

```
pulse-project/
├── CLAUDE.md                                          # 🎯 Orchestrator
├── .claude/
│   ├── agents/
│   │   ├── pulse-product-director.md                  # 📋 Product & Design Director
│   │   ├── pulse-frontend.md                          # 🎨 Frontend Design Engineer
│   │   ├── pulse-engineer.md                          # ⚙️ Full-Stack Engineer
│   │   ├── pulse-data-engineer.md                     # 🔧 Data Engineer
│   │   ├── pulse-data-scientist.md                    # 📊 Data Scientist
│   │   ├── pulse-test-engineer.md                     # 🧪 Test Engineer
│   │   └── pulse-ciso.md                              # 🔒 CISO / Security
│   ├── skills/  (7 SKILL.md files — auto-discovered context)
│   └── commands/
│       ├── pulse-build.md                             # /pulse-build <target>
│       ├── pulse-bootstrap.md                         # /pulse-bootstrap [phase]
│       ├── pulse-implement.md                         # /pulse-implement <story>
│       ├── pulse-test.md                              # /pulse-test <scope>
│       ├── pulse-review.md                            # /pulse-review [path|type]
│       ├── pulse-status.md                            # /pulse-status
│       └── pulse-spec.md                              # /pulse-spec <feature>
└── README.md
```

## The 7 Agents

| Agent | Persona | Domain | Model |
|---|---|---|---|
| **pulse-product-director** | VP Product & Design | Strategy, specs, personas, BDD, pricing, UX, GTM | Opus |
| **pulse-frontend** | Sr. Design Engineer | HTML/CSS/JS prototype in `pulse-ui/` | Opus |
| **pulse-engineer** | Sr. Full-Stack Engineer | Production code in `packages/`, Docker, CI | Opus |
| **pulse-data-engineer** | Principal Data Engineer | DevLake, Kafka, workers, DB schema, pipelines | Opus |
| **pulse-data-scientist** | Chief Data Scientist | Metric formulas, stats, ML, visualization rules | Sonnet |
| **pulse-test-engineer** | Sr. QA Architect | TDD, Playwright, Testcontainers, CI gates | Sonnet |
| **pulse-ciso** | CISO & Cloud Security | Security, IAM, encryption, compliance | Sonnet |

## How Routing Works

The orchestrator (`CLAUDE.md`) reads every message and routes to the right agent:

```
"Define the DORA classification thresholds"
  → pulse-data-scientist (metric formulas)

"Build the MetricCard component for the prototype"
  → pulse-frontend (pulse-ui/)

"Create the NestJS health endpoint"
  → pulse-engineer (packages/pulse-api)

"Set up the Kafka sync worker"
  → pulse-data-engineer (pipeline)

"Write unit tests for DORA calculations"
  → pulse-test-engineer (TDD)

"Review RLS policies for security"
  → pulse-ciso (security)

"Write the user story for CFD"
  → pulse-product-director (spec)

"Build DORA metrics end-to-end"
  → Orchestrator breaks into 6 sub-tasks across agents
```

## Slash Commands

| Command | What it does |
|---|---|
| `/pulse-build metric-card prototype` | Routes to the right agent and builds |
| `/pulse-bootstrap` | Phase 1: infra skeleton + Docker + CI |
| `/pulse-bootstrap 2` | Phase 2: data pipeline + DevLake |
| `/pulse-bootstrap 3` | Phase 3: metrics + dashboards |
| `/pulse-implement MVP-2.1.1` | End-to-end feature across all agents |
| `/pulse-implement DORA metrics` | Full stack: formula → pipeline → API → React → tests |
| `/pulse-test dora` | TDD: write tests first, then implement |
| `/pulse-test e2e` | Run Playwright journeys |
| `/pulse-review security` | CISO reviews the codebase |
| `/pulse-review packages/` | Engineer reviews production code |
| `/pulse-status` | MVP progress dashboard |
| `/pulse-spec WIP Monitor` | Create feature spec with BDD criteria |

## Setup

```bash
# 1. Unzip into your project root
unzip pulse-claude-code-setup.zip -d /path/to/pulse/

# 2. Open Claude Code
cd /path/to/pulse
claude

# 3. Start building
> /pulse-bootstrap
```

## Recommended Workflow

```bash
# Phase 1 — Infrastructure
/pulse-bootstrap                       # Skeleton, Docker, CI
/pulse-status                          # Check progress

# Phase 2 — Data Pipeline
/pulse-bootstrap 2                     # DevLake, Kafka, workers
/pulse-test dora                       # TDD for DORA calculations
/pulse-review data-quality             # Pipeline quality check

# Phase 3 — Metrics + Dashboards
/pulse-implement DORA metrics          # End-to-end (6 agents coordinated)
/pulse-implement Lean metrics          # CFD, WIP, Lead Time, Scatterplot
/pulse-review security                 # CISO sign-off
/pulse-test e2e                        # Playwright journeys

# Feature development
/pulse-spec "Sprint Comparison"        # Product director writes spec
/pulse-implement "Sprint Comparison"   # Engineers build it
/pulse-review packages/                # Code quality
```

## Explicit Agent Invocation

```bash
# Force a specific agent
> Use the pulse-data-scientist to define Monte Carlo simulation approach
> Use the pulse-ciso to review the Docker Compose security
> Use the pulse-product-director to write BDD for the filter bar
```

## Adding New Agents

Create `.claude/agents/new-agent.md` with YAML frontmatter (name, description, tools, model) + markdown system prompt. Then add routing rules to `CLAUDE.md`.

## Agent vs Skill vs Command

| | Agent | Skill | Command |
|---|---|---|---|
| **Context** | Own (isolated) | Main session | Main session |
| **Invocation** | Auto or explicit | Auto-discovered | `/command-name` |
| **Best for** | Heavy work with persona | Quick reference context | Manual workflow triggers |
