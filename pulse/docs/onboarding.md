# PULSE — developer onboarding

Get a working PULSE dev environment on a fresh clone in **under 15 minutes**.

> **Status:** this is an incremental guide being built PR by PR.
> PR #1 (this document) ships `make doctor` + `make verify-dev`.
> PR #2 will ship `make seed-dev` (realistic fake data).
> PR #3 will ship `make onboard` (one-shot orchestrator).
> PR #5 will ship the optional real-data overlay via Doppler.

---

## TL;DR (the happy path, once all PRs land)

```bash
git clone <repo> && cd pulse
make doctor      # 30s — validates host tools + ports
make onboard     # ~12 min — docker build + migrate + seed + verify
make dev         # starts Vite at http://localhost:5173
```

If `make verify-dev` returns `✓ Stack is healthy`, you're ready.

---

## Today (PR #1 only): what works vs. what's coming

### What works today

```bash
cd pulse

# 1. Validate your machine CAN run PULSE
make doctor
```

`doctor` checks (in order):
- **Platform**: macOS, Linux, WSL2 (not native Windows)
- **Tools**: Docker 24+, Compose v2+, Node 20+, Python 3.9+ host, Git, Bash
- **Optional tools**: Gitleaks (for pre-commit), Doppler CLI (future real-data overlay), GitHub CLI
- **Free ports**: 3000, 5173, 5432, 6379, 8000, 9092
  - If PULSE stack is already up, doctor recognizes "bound by PULSE stack (ok)"
- **Resources**: ≥15 GB disk, ≥4 GB Docker memory allocation

Each check prints either ✓ (pass), ! (warning, onboard can proceed), or ✗ (hard fail, fix first). Every ✗ comes with an actionable fix line.

Exit codes:
- `0` all pass
- `1` hard fails present
- `2` only warnings

### After the stack is up and seeded (works today with a pre-seeded DB)

```bash
# 2. Confirm everything's responding with real data
make verify-dev
```

`verify-dev` checks:
- `pulse-api /api/v1/health` → 200
- `pulse-data /health` → 200
- `/data/v1/metrics/home` returns non-null `deployment_frequency` (60s timeout — can take time on first call until metrics-worker caches a snapshot)
- `/data/v1/pipeline/teams` returns ≥ 10 squads
- Vite dev server at :5173 (skipped if not running)

Exit: `0` on all pass, `1` on any failure.

### What's coming (next PRs)

- **PR #2** — `make seed-dev` populates 15 fake squads, ~2k PRs, ~5k issues deterministically. Safety-guarded: refuses to run against a remote DB or a tenant that already has real data. Includes `--scale=large` mode (FDD-OPS-010) for perf testing.
- **PR #3** — persistent UI banner when the dev tenant is detected (impossible to mistake a seed screenshot for prod).
- **PR #4** — **expanded scope after 2026-04-24 incident**:
  - `make onboard` orchestrator (doctor → build → up → migrate → seed → verify → print URL)
  - **Backend-in-CI + smoke E2E as blocking PR gate** (FDD-OPS-004) — fixes the gap that let `/metrics/home` regress 50× without the CI catching it
  - **Performance budget assertions in smoke** (FDD-OPS-006) — smoke now fails on `/metrics/home` taking > 8s
  - Branch protection updated with the new required check
- **PR #5** — optional Doppler overlay: `doppler run -- make ingest-real` triggers a live, scoped ingestion (last 30d, top-5 repos) using shared read-only service-account creds. Secrets never touch disk.

After PR #5, three follow-up FDDs close the perf/scale gap completely:
- **FDD-OPS-007** Cold-cache test mode
- **FDD-OPS-008** Per-endpoint perf contract suite
- **FDD-OPS-009** DB query plan regression tests
- **FDD-OPS-011** Synthetic monitoring (before first prod deploy)

See `docs/testing-playbook.md` §10 for the full "tests we don't have (yet)" roadmap.

---

## Troubleshooting

### `doctor` says my port is in use but I haven't started PULSE yet

Common culprits:
- **5432** — Postgres.app or Homebrew postgres: `brew services stop postgresql`
- **6379** — Homebrew redis: `brew services stop redis`
- **3000** — another Node dev server (Next.js, etc.): `lsof -i :3000` then kill
- **5173** — lingering Vite from a previous session: `pkill -f vite`

If you can't stop the conflicting service, change the port in `pulse/.env`.

### `doctor` says Docker memory is too low

Docker Desktop → Settings → Resources → Memory → set to **≥ 4 GB** (8 GB recommended if you'll run the full stack + tests in parallel).

### `verify-dev` says `pulse-api /health` HTTP 404 or 000

- `000` means the container isn't listening yet. Check: `docker compose logs pulse-api | tail -30`.
- `404` usually means the NestJS `globalPrefix` changed. The health path is `/api/v1/health` — if it moved, update `scripts/verify-dev.sh`.

### `verify-dev` passes but UI shows blank page

- Vite dev server not running: `cd packages/pulse-web && npm run dev`
- Or the DB is empty (no seed yet). Run `make seed-dev` (once PR #2 lands).

### Python 3.9 on host (macOS default) — is this a problem?

No. The container runs its own Python 3.12. Host Python is only used for JSON parsing in `verify-dev.sh`. If you want to run `pytest` directly on the host (bypassing docker), install 3.12 via pyenv.

### I'm on native Windows

PULSE uses shell scripts and Docker bind mounts that assume a POSIX layout. **Use WSL2.** Installation guide: https://learn.microsoft.com/en-us/windows/wsl/install. Then clone PULSE inside the WSL filesystem (`/home/<user>/...`) for correct file permissions.

---

## Real data (future, PR #5)

Two paths will coexist:

1. **Fake seed (default)** — PR #2 ships `make seed-dev`. Works for anyone without external credentials.
2. **Real ingestion (opt-in)** — PR #5 adds `doppler run -- make ingest-real`. Requires:
   - A Doppler account linked to the PULSE dev project
   - A service-account token provisioned by the repo admin
   - No manual copy-paste of secrets into `.env`

Never paste tokens into chat with AI tools or into the repo itself. The gitleaks pre-commit hook (Sprint 1.2) blocks commits with secrets, but can't block leaks via screen-share or chat history. See `testing-playbook.md` §8.9 for the secret-rotation runbook.

---

## Related docs

- `testing-playbook.md` — how to write and run tests (Vitest, Playwright, contract, a11y, coverage gates)
- `.github/workflows/README.md` — CI pipeline layout and branch-protection checks to enable
- `backlog/ops-backlog.md` — ops/infrastructure FDDs (secret rotation runbook, design-system contrast audit, etc.)

---

## Changelog

- **2026-04-24** — PR #1: doctor + verify-dev scripts, Makefile targets, this document.
- **2026-04-24** — Roadmap update: PR #4 scope expanded post-incident to include backend-in-CI smoke gate (FDD-OPS-004) + perf budget assertions (FDD-OPS-006). 6 new FDDs (OPS-004..011) added to ops-backlog covering perf/scale gaps. See `testing-playbook.md` §10.
