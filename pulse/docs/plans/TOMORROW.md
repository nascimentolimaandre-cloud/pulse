# Tomorrow's pickup — FDD-OBS-001 Remediation

## Status (locked 2026-05-10 night)

User chose **Opção A** — close all FDD-OBS-001 R2 gaps to reach "friendly-tenant ready".
**All 4 decisions are locked.** Tomorrow morning's job: read this file, say "GO Phase 1".

## ✅ Decisões locked (2026-05-10 night)

| # | Decisão | Escolhido |
|---|---|---|
| D1 | Solo ou pair? | **PARALLEL** — paraleliza Phase 3 (frontend track) com Phase 2 (backend track) pra comprimir timeline de ~10-14d → ~8d |
| D2 | Stage gate após Phase 2? | **SIM** — CISO async review antes de começar React UI |
| D3 | Webmotors vê antes da Phase 5? | **WAIT** — protótipo só confunde, anchor vê o React final |
| D4 | R3 features no escopo? | **NÃO** — mantém R2 honesto, R3 separado depois |

## What to read first (in order)

1. **`docs/plans/FDD-OBS-001-remediation-master-plan.md`** — the master plan (everything)
2. **`docs/reviews/FDD-OBS-001-engineering-review.md`** — engineering critique that drove the plan
3. **`docs/reviews/FDD-OBS-001-frontend-review.md`** — frontend critique that drove the plan

## Parallel execution model (D1 = PARALLEL)

Two tracks share the work. Within main session, this means I dispatch the
right specialized agent for each track via the Agent tool, in parallel
where possible.

```
┌────────────────────────────────────────────────────────────────────────┐
│  TRACK A (backend)              TRACK B (frontend)                     │
│  agent: pulse-engineer          agent: pulse-engineer + pulse-frontend │
├────────────────────────────────────────────────────────────────────────┤
│  Day 1   Phase 1 fixes          Phase 3 design audit + prep            │
│  Day 2   Phase 1 finish + ⚠CISO Phase 3 primitives (Modal, Table…)     │
│  Day 3   Phase 2 proxy           Phase 3 Ownership page                │
│  Day 4   Phase 2 ⚠CISO + 🔍analysis  Phase 3 finish + Phase 4 start    │
│  Day 5   Phase 5 chart spike    Phase 4 Aliases                        │
│  Day 6   Phase 5 chart          Phase 5 a11y + data wiring             │
│  Day 7   Phase 5 integration + ux-reviewer (joint)                     │
│  Day 8   Phase 6 final + tag obs-001-v1.0                              │
└────────────────────────────────────────────────────────────────────────┘
```

Compressed from ~10-14 days → ~8 days.

## Where parallel actually applies (and where it doesn't)

- ✅ Phase 1 (backend fixes) || Phase 3 prep (design audit) — different files
- ✅ Phase 2 (proxy) || Phase 3 primitives — different packages (pulse-api vs pulse-web)
- ✅ Phase 4 (Aliases) || Phase 5 chart spike — different files
- ❌ Phase 1 must merge BEFORE Phase 2 ships (Phase 2 proxies the fixed code)
- ❌ Phase 3 primitives must merge BEFORE Phase 4 (Phase 4 reuses them)
- ❌ Pre-Phase 5 analysis is BLOCKING for Phase 5 final implementation

## Phase 1 detailed task plan (ready to dispatch)

When user says "manda Phase 1" tomorrow:

| Task | What | Estimate | Agent |
|---|---|---|---|
| T1.1 | Add `list_monitors_for_service` to ObservabilityProvider Protocol + ADR-023 amendment | 1h | pulse-engineer |
| T1.2 | Master key rotation: `scripts/rotate_obs_master_key.py` + runbook + smoke test | 5h | pulse-engineer + pulse-ciso pre-check |
| T1.3 | Replace f-string in `_set_tenant` with bound parameter + audit other sites | 0.5h | pulse-engineer |
| T1.4 | FastAPI exception middleware extending hide_parameters to driver errors | 2h | pulse-engineer |
| T1.5 | RISK-7: recursive jsonb PII trigger (alembic 023) | 2h | pulse-engineer |
| T1.6 | RISK-12/13/17: scan + FORBIDDEN_REFS + nested PII pairs | 1.5h | pulse-engineer |
| T1.R | Phase 1 PR review by pulse-ciso (async) | 2h | pulse-ciso |
| T1.M | Merge gate: all 274 obs tests pass + new tests + CISO sign-off | — | main session |

Parallel: while T1.1-T1.6 are running, Track B can start `pulse-frontend` design system audit (Phase 3 prep).

## How to start tomorrow

User just needs to say:

- **"GO Phase 1"** or **"manda"** → main session dispatches:
  - `pulse-engineer` (Track A) for T1.1 → T1.6 sequentially
  - `pulse-frontend` (Track B) for Phase 3 design system audit in parallel
  - `pulse-ciso` async review queued after T1.6
- **"espera, quero ajustar X"** → orchestrator answers questions before code

The parallel dispatch will happen in a single message with multiple
Agent tool calls — saves wall-clock time per CLAUDE.md guidance.

## Open invariants to preserve

- **Worker is still running** (`pulse-obs-rollup-worker` container) — accumulating
  `monitor_health` snapshots every 15 min. Don't restart unless necessary.
- **Webmotors data** is still in `obs_metric_snapshots` (736 rows at last check) +
  `service_squad_ownership` (473 services, 11 aliases, 90.9% coverage).
- **PR #29** (Timeline backend + prototype) is the latest merge. Local main is in sync.
- **All 274 obs tests** still pass (per last full regression).
- **No active branches** — clean main, ready for Phase 1 branch.

## Reminders

- User hates rework. Tomorrow's first task is the master plan review, NOT code.
- Always use the right agent per CLAUDE.md routing rules. The reviews flagged that
  I drifted on this (writing pulse-ui/ work without the impl-spec handoff to pulse-engineer).
  Don't repeat. Each UI PR has an impl spec deliverable.
- CISO review is async and BEFORE merge, not after.

## Memory hook

When the user wakes up and replies, write a short note to MEMORY.md:
`FDD-OBS-001 R2 — remediation started, Phase X in progress, friendly-tenant ETA ~10-14 days`
