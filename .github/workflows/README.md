# GitHub Actions workflows — root vs pulse/

This repo has workflows in **two** locations. The split is intentional.

## `/.github/workflows/` (this directory — **ACTIVE**)

Runs on every push + PR. These are the real gates enforced by branch
protection. Scope is the full monorepo (root-level).

| File | Trigger | What it does |
|---|---|---|
| `ci.yml` | PR + push to main/develop | Gitleaks secrets scan, ESLint + TSC pulse-web, Vitest (139+ tests incl. contract), Vite build |
| `e2e-a11y.yml` | manual + nightly cron | Playwright smoke + axe-core a11y. No-op until backend CI infra is wired — see testing-playbook.md §8.8 |

## `/pulse/.github/workflows/` (sub-directory — **DORMANT**)

Workflows prepared for the day `pulse/` is extracted into its own git
repo (SaaS productization). They expect `pulse/` to be the repo root, so
`cd packages/...` works directly. They do **not** run today because
GitHub Actions only looks at `.github/workflows/` at the actual repo
root.

| File | Purpose |
|---|---|
| `ci.yml` | Full backend + frontend CI (Jest, Pytest with anti-surveillance gate, Docker builds) — runs when pulse/ is standalone |
| `deploy.yml` | Release rollout template (manual dispatch) — TODO steps for kubectl/ECS |

When you extract `pulse/` to its own repo, `git mv pulse/.github/workflows/*.yml
.github/workflows/` and delete these root workflows.

## Branch protection (set once in GitHub Settings)

For `ci.yml` to actually block merges, turn on branch protection for
`main` (and `develop` if used) with these required status checks:

- `Secrets scan (gitleaks)`
- `Lint & typecheck (pulse-web)`
- `Unit tests (pulse-web Vitest)`
- `Build (pulse-web Vite)`

UI path: Settings → Branches → Branch protection rules → Add rule →
"Require status checks to pass before merging" → pick the 4 above.
