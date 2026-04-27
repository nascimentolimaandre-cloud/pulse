"""PULSE — deterministic dev fixture seed.

Populates a CLEAN dev DB with realistic-looking fake data so a fresh
clone renders a working dashboard in <15 min after `make onboard`.

==============================================================================
SAFETY (D3=realistic data has higher confusion risk; 5 layers of defense)
==============================================================================

This script REFUSES to run unless ALL of these hold:

  1. --confirm-local flag passed (CLI gate)
  2. PULSE_ENV != production (env gate)
  3. DATABASE_URL host is localhost / postgres / 127.0.0.1 (host gate)
  4. Target tenant is the reserved dev tenant `00000000-...0001` (tenant gate)
  5. Either tenant is empty OR --reset is passed AND user confirms (data gate)

Every row inserted has external_id prefixed with `seed_dev:` so the dataset
is trivially filterable for cleanup, audit, and to detect "did real data
leak in here?" via SQL.

==============================================================================
ARCHITECTURE
==============================================================================

Single file, organized in sections:

  CONFIG       — tenants, seeds, squad/repo/tribo definitions
  GUARDS       — 5-layer safety check
  GENERATORS   — squads → repos → PRs → issues → deploys → sprints → snapshots
  RESET        — DELETE-by-marker for re-seed
  ORCHESTRATOR — main() ties it together
  CLI          — argparse + entry point

==============================================================================
DATA VOLUME (default)
==============================================================================

  - 15 squads across 4 tribes
  - 80 repos
  - ~2k PRs (90d window, log-normal distribution per squad)
  - ~5k issues (status mix: 15% todo / 20% in_progress / 10% in_review / 55% done)
  - ~300 deploys (jenkins-style, weekly cadence with gaps)
  - ~60 sprints (10 squads with capability=sprint, 6 sprints each)
  - Pre-computed snapshots for periods 30d/60d/90d/120d to avoid the
    on-demand 50× cold-path discovered in the 2026-04-24 incident.

Total runtime: ~60-90s on a warm Postgres.

==============================================================================
DETERMINISM
==============================================================================

Uses `random.Random(seed)` (seed=42 by default, configurable via --seed).
Same seed → same data, byte-for-byte. Allows reproducing user-visible
test scenarios across machines.

==============================================================================
USAGE
==============================================================================

  # Inside the pulse-data container:
  python -m scripts.seed_dev --confirm-local

  # With reset (wipes existing dev tenant data, then seeds):
  python -m scripts.seed_dev --confirm-local --reset

  # From the host via Make:
  make seed-dev          # equivalent to first invocation above
  make seed-reset        # equivalent to second
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.config import settings
from src.database import async_session_factory, engine

logger = logging.getLogger("seed_dev")


# =============================================================================
# CONFIG
# =============================================================================

# The reserved dev tenant. Production tenants are real UUIDs; this one is
# all-zeros-with-1, deliberately recognizable. Code paths that detect this
# tenant can mark UI as "DEV FIXTURE" (PR #3).
DEV_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

# Default RNG seed. Change only if you intentionally want a different shape;
# CI and onboarding rely on identical output across machines.
DEFAULT_SEED = 42

# Marker for every row we insert. Used by the data-gate guard to detect
# contamination, by --reset to know what to delete, and by SQL audits.
SEED_MARKER_PREFIX = "seed_dev:"
SEED_VERSION = "1.0"

# Email domain reserved by RFC 6761 (and friends) for tests / examples.
# Never collides with real users.
FAKE_EMAIL_DOMAIN = "example.invalid"


# Tribos and the squads inside each.
# Squad keys are 3-letter codes that look like real Jira project keys but
# are clearly synthetic (no real organization uses these exact combos).
TRIBES: dict[str, list[str]] = {
    "Payments":      ["PAY", "BILL", "CHK"],
    "Core Platform": ["AUTH", "API", "INFRA", "OBS"],
    "Growth":        ["MKT", "SEO", "CRO", "RET"],
    "Product":       ["UI", "MOB", "DSGN", "QA"],
}

# Squads that have Sprint capability (the rest are Kanban-only — covers
# the FID+PTURB-vs-others split observed in real Webmotors data).
SPRINT_CAPABLE_SQUADS = {"PAY", "AUTH", "API", "MKT", "CRO", "UI", "MOB", "DSGN", "QA", "RET"}

# Repos per squad, with realistic-looking naming.
REPO_PATTERNS: dict[str, list[str]] = {
    "PAY":   ["payments-api", "payments-web", "payments-worker"],
    "BILL":  ["billing-api", "billing-cron", "invoice-pdf"],
    "CHK":   ["checkout-web", "checkout-api", "checkout-mobile-sdk"],
    "AUTH":  ["auth-service", "auth-web", "session-mgr", "mfa-broker"],
    "API":   ["public-api", "internal-gateway", "schema-registry", "graphql-edge", "rate-limiter"],
    "INFRA": ["infra-terraform", "k8s-manifests", "ci-cd-shared", "secrets-rotator"],
    "OBS":   ["obs-pipeline", "log-router", "metrics-aggregator", "tracing-collector"],
    "MKT":   ["mkt-site", "campaign-engine", "email-templates"],
    "SEO":   ["seo-toolkit", "sitemap-builder", "schema-org-helper"],
    "CRO":   ["cro-experiments", "ab-config", "cro-dashboard"],
    "RET":   ["retention-jobs", "lifecycle-emails", "win-back-flows"],
    "UI":    ["design-tokens", "ui-components", "icon-library", "storybook-host"],
    "MOB":   ["mobile-app-ios", "mobile-app-android", "mobile-shared"],
    "DSGN":  ["design-system-docs", "design-figma-sync"],
    "QA":    ["qa-automation", "qa-fixtures", "test-reporter", "e2e-runner"],
}


# Distribution profiles per squad. Each squad gets a "DORA archetype" so the
# dashboard surfaces contrasting badges (Elite/High/Medium/Low) across the
# ranking — not all squads in the same bucket.
@dataclass
class SquadProfile:
    """Statistical fingerprint that drives PR/deploy/issue generation."""

    key: str
    tribe: str
    archetype: str  # 'elite' | 'high' | 'medium' | 'low' | 'degraded' | 'empty'
    pr_count: int
    deploy_count: int
    issue_count: int
    has_sprints: bool

    @property
    def lead_time_hours_mean(self) -> float:
        # Lead time ≈ first_commit → deployed_at, in hours.
        return {
            "elite":    18.0,
            "high":     72.0,
            "medium":   336.0,   # 14d
            "low":      720.0,   # 30d
            "degraded": 480.0,
            "empty":    72.0,    # irrelevant — no PRs anyway
        }[self.archetype]

    @property
    def deploy_freq_per_week(self) -> float:
        return {
            "elite":    7.0,    # multiple deploys/day
            "high":     3.0,
            "medium":   1.0,
            "low":      0.3,
            "degraded": 1.5,
            "empty":    0.0,
        }[self.archetype]

    @property
    def change_failure_rate(self) -> float:
        return {
            "elite":    0.05,
            "high":     0.10,
            "medium":   0.20,
            "low":      0.40,
            "degraded": 0.30,
            "empty":    0.0,
        }[self.archetype]


# Fixed archetype assignment for a contrasting-but-stable dashboard.
SQUAD_ARCHETYPES: dict[str, str] = {
    "PAY": "elite", "API": "elite",
    "AUTH": "high", "CHK": "high", "UI": "high",
    "BILL": "medium", "INFRA": "medium", "MKT": "medium", "MOB": "medium", "RET": "medium",
    "OBS": "low", "SEO": "low", "CRO": "low",
    "QA":   "degraded",  # data atrasado / cobertura parcial
    "DSGN": "empty",     # sem PRs no período (testa empty state)
}

# Realistic-but-fake PR title templates — reusable patterns devs see in real
# projects but with clearly invented feature names.
# PR titles intentionally embed `<KEY>-NNN` (Jira-style ticket reference)
# because /pipeline/teams uses regex `[A-Za-z][A-Za-z0-9]+-\d+` to derive
# the active-squads list from PR titles. Without the embedded key, the
# pipeline endpoint reports "0 squads" even though we seeded 15.
PR_TITLE_TEMPLATES = [
    "feat({scope}): {KEY}-{N} add {feat}",
    "fix({scope}): {KEY}-{N} handle null when {edge}",
    "fix({scope}): {KEY}-{N} {edge} regression",
    "chore({scope}): {KEY}-{N} bump {dep} to latest",
    "refactor({scope}): {KEY}-{N} extract {feat} into module",
    "perf({scope}): {KEY}-{N} cache {feat} lookups",
    "test({scope}): {KEY}-{N} add coverage for {feat}",
    "docs({scope}): {KEY}-{N} update {feat} README",
]
PR_FEAT_NOUNS = [
    "filter", "sorting", "pagination", "validation", "dry-run mode",
    "retry logic", "rate-limit headers", "request id propagation",
    "tracing spans", "feature flag", "user preference", "cache layer",
    "audit log", "webhook handler", "csv export", "bulk delete",
]
PR_EDGE_NOUNS = [
    "empty result set", "concurrent updates", "stale cache", "missing tenant",
    "timezone offset", "unicode in label", "very long title", "deleted user",
]
PR_DEP_NAMES = [
    "axios", "react-query", "fastapi", "sqlalchemy", "pydantic",
    "playwright", "vitest", "eslint-plugin-react",
]

# Issue title templates similar to PR but more product-shaped.
ISSUE_TITLE_TEMPLATES = [
    "[{scope}] As a user, I want to {action}",
    "[{scope}] {scope_noun} should {action}",
    "[{scope}] Bug: {bug}",
    "[{scope}] Investigate {area} performance",
    "[{scope}] Spike: evaluate {tech} for {area}",
    "[{scope}] Tech debt: refactor {area}",
]
ISSUE_ACTIONS = [
    "see my recent activity", "filter by date range", "export to CSV",
    "receive a notification", "edit my profile", "undo last action",
    "view audit history", "share via link",
]
ISSUE_BUGS = [
    "404 on direct link refresh", "race condition on save", "broken on Safari 17",
    "infinite spinner when offline", "timezone display incorrect",
    "missing translation in form errors",
]
ISSUE_AREAS = [
    "search", "checkout", "auth flow", "navigation", "onboarding",
    "settings panel", "data export",
]
ISSUE_TECHS = [
    "OpenTelemetry", "k6", "Tanstack Query v5", "Recharts", "Zustand",
]


# =============================================================================
# GUARDS — 5-layer safety check. ANY failure aborts before touching the DB.
# =============================================================================

class GuardError(RuntimeError):
    """Raised when a safety check fails. Always fatal."""


def _guard_1_cli_flag(args: argparse.Namespace) -> None:
    """Layer 1: --confirm-local must be passed explicitly."""
    if not args.confirm_local:
        raise GuardError(
            "Safety guard: --confirm-local is REQUIRED to run seed_dev.\n"
            "    This script writes ~7000 rows to the dev tenant. Pass\n"
            "    --confirm-local to acknowledge you intend this on a LOCAL DB."
        )


def _guard_2_env() -> None:
    """Layer 2: env var PULSE_ENV must NOT be production."""
    env = os.environ.get("PULSE_ENV", "development").lower()
    if env in {"production", "prod", "staging", "stg"}:
        raise GuardError(
            f"Safety guard: PULSE_ENV='{env}' — refusing to seed.\n"
            f"    This script is for local dev only. Set PULSE_ENV=development."
        )


def _guard_3_host() -> None:
    """Layer 3: DB host must be localhost / postgres / 127.0.0.1."""
    url = settings.async_database_url
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = {"localhost", "127.0.0.1", "postgres", "::1"}
    if host not in allowed:
        raise GuardError(
            f"Safety guard: DB host='{host}' — refusing to seed.\n"
            f"    Only {sorted(allowed)} are permitted. If you really need to\n"
            f"    seed against a non-local DB, do it manually — there is no\n"
            f"    flag to bypass this guard, by design."
        )


def _guard_4_tenant(tenant_id: UUID) -> None:
    """Layer 4: target tenant must be the reserved dev tenant."""
    if tenant_id != DEV_TENANT_ID:
        raise GuardError(
            f"Safety guard: target tenant {tenant_id} != dev tenant {DEV_TENANT_ID}.\n"
            f"    seed_dev only writes to the reserved dev tenant. Production\n"
            f"    tenants must NEVER be the target."
        )


async def _guard_5_data_state(reset: bool) -> None:
    """Layer 5: tenant must be empty OR --reset must be set.

    Detects contamination: if rows exist in the tenant that DO NOT have the
    seed marker, refuse — that means real data is mixed in and would be lost.
    """
    async with async_session_factory() as s:
        # Bypass RLS by setting tenant explicitly + counting all the things.
        await s.execute(text(f"SET app.current_tenant = '{DEV_TENANT_ID}'"))

        # Count both seed and non-seed rows across the main tables.
        counts = {}
        for table in ("eng_pull_requests", "eng_issues", "eng_deployments", "eng_sprints"):
            row = await s.execute(text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE external_id LIKE '{SEED_MARKER_PREFIX}%')   AS seed_rows,
                    COUNT(*) FILTER (WHERE external_id NOT LIKE '{SEED_MARKER_PREFIX}%') AS real_rows
                FROM {table}
                WHERE tenant_id = '{DEV_TENANT_ID}'
            """))
            seed_n, real_n = row.one()
            counts[table] = (seed_n, real_n)

        seed_total = sum(s for s, _ in counts.values())
        real_total = sum(r for _, r in counts.values())

        if real_total > 0 and not reset:
            details = "\n".join(
                f"        {t}: {real_n} real rows, {seed_n} seed rows"
                for t, (seed_n, real_n) in counts.items()
                if real_n > 0
            )
            raise GuardError(
                f"Safety guard: dev tenant has {real_total} non-seed rows already.\n"
                f"    Running seed_dev would mix synthetic with real-looking data.\n"
                f"    To proceed, pass --reset (which wipes BOTH seed and non-seed\n"
                f"    rows from the dev tenant before re-seeding).\n"
                f"\n"
                f"    Current state:\n{details}"
            )

        if seed_total > 0 and not reset:
            raise GuardError(
                f"Safety guard: dev tenant already has {seed_total} seed rows.\n"
                f"    Running again without --reset would create duplicates with\n"
                f"    different external_ids. Pass --reset to clear and re-seed."
            )


async def run_guards(args: argparse.Namespace) -> None:
    """Run all 5 layers in order. Each prints its own decision."""
    print("→ Guard 1/5: --confirm-local flag …", end=" ", flush=True)
    _guard_1_cli_flag(args)
    print("ok")

    print("→ Guard 2/5: PULSE_ENV is dev …", end=" ", flush=True)
    _guard_2_env()
    print("ok")

    print("→ Guard 3/5: DB host is local …", end=" ", flush=True)
    _guard_3_host()
    print("ok")

    print("→ Guard 4/5: target tenant is reserved dev tenant …", end=" ", flush=True)
    _guard_4_tenant(DEV_TENANT_ID)
    print("ok")

    print("→ Guard 5/5: tenant data state …", end=" ", flush=True)
    await _guard_5_data_state(reset=args.reset)
    print("ok")


# =============================================================================
# RESET — wipe by marker (only seeded rows) OR full tenant (when contaminated)
# =============================================================================

async def reset_tenant() -> None:
    """Wipe rows belonging to the dev tenant, fast.

    Strategy: for each table we check whether the dev tenant is the ONLY
    tenant with rows. If yes → TRUNCATE (instant, even at 10M rows). If
    other tenants share the table → DELETE WHERE tenant_id (correct but
    slow at scale).

    Real numbers from the dev box (2026-04-27): metrics_snapshots was
    7M rows; DELETE took 21+ min and was killed. TRUNCATE finished in
    <1s. The single-tenant guard makes this safe — we only TRUNCATE
    when SELECT DISTINCT tenant_id confirms no other data lives there.
    """
    print("→ resetting dev tenant …", flush=True)
    tables = [
        "metrics_snapshots",
        "eng_pull_requests",
        "eng_issues",
        "eng_deployments",
        "eng_sprints",
        "jira_project_catalog",
        "pipeline_watermarks",
        "tenant_jira_config",
        # iam_teams (squads) and connections also live per-tenant but we
        # don't recreate them by default — leave existing seed entries.
    ]
    async with async_session_factory() as s:
        await s.execute(text(f"SET app.current_tenant = '{DEV_TENANT_ID}'"))
        for t in tables:
            # Check tenant cardinality. Bypass RLS by using SET app.bypass_rls
            # is not configured; instead, use a session that doesn't filter.
            other = (await s.execute(text(
                f"SELECT COUNT(DISTINCT tenant_id) FROM {t} "
                f"WHERE tenant_id != '{DEV_TENANT_ID}'"
            ))).scalar_one()
            if other == 0:
                # Single-tenant: TRUNCATE is safe and ~1000× faster.
                await s.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
                print(f"   {t}: TRUNCATEd (single-tenant)")
            else:
                res = await s.execute(text(
                    f"DELETE FROM {t} WHERE tenant_id = '{DEV_TENANT_ID}'"
                ))
                print(f"   {t}: {res.rowcount} rows deleted (multi-tenant)")
        await s.commit()


# =============================================================================
# GENERATORS
# =============================================================================

def _build_squad_profiles() -> list[SquadProfile]:
    """Materialize the 15 squads with their archetype-driven targets."""
    profiles: list[SquadProfile] = []
    for tribe, squad_keys in TRIBES.items():
        for key in squad_keys:
            archetype = SQUAD_ARCHETYPES[key]
            # Volumes scale with archetype: elite gets more PRs/deploys.
            base_pr = {
                "elite":    220, "high": 170, "medium":  130,
                "low":       80, "degraded": 90, "empty":    0,
            }[archetype]
            base_dep = {
                "elite":    35, "high": 22, "medium":  10,
                "low":       4, "degraded": 8, "empty":    0,
            }[archetype]
            base_iss = {
                "elite":    420, "high": 380, "medium":  340,
                "low":      280, "degraded": 320, "empty": 50,
            }[archetype]

            profiles.append(SquadProfile(
                key=key,
                tribe=tribe,
                archetype=archetype,
                pr_count=base_pr,
                deploy_count=base_dep,
                issue_count=base_iss,
                has_sprints=key in SPRINT_CAPABLE_SQUADS,
            ))
    return profiles


def _fake_author(rng: random.Random, squad: str) -> str:
    """Generate a clearly-synthetic author email per squad."""
    archetypes = ["alpha", "bravo", "charlie", "delta", "echo", "fox", "golf", "hotel"]
    n = rng.randint(1, 8)
    return f"dev.{archetypes[n % len(archetypes)]}.{squad.lower()}@{FAKE_EMAIL_DOMAIN}"


def _gen_pr_title(rng: random.Random, scope: str, ticket_n: int) -> str:
    template = rng.choice(PR_TITLE_TEMPLATES)
    return template.format(
        scope=scope.lower(),
        KEY=scope.upper(),
        N=ticket_n,
        feat=rng.choice(PR_FEAT_NOUNS),
        edge=rng.choice(PR_EDGE_NOUNS),
        dep=rng.choice(PR_DEP_NAMES),
    )


def _gen_issue_title(rng: random.Random, scope: str) -> str:
    template = rng.choice(ISSUE_TITLE_TEMPLATES)
    return template.format(
        scope=scope.upper(),
        scope_noun=scope.lower(),
        action=rng.choice(ISSUE_ACTIONS),
        bug=rng.choice(ISSUE_BUGS),
        area=rng.choice(ISSUE_AREAS),
        tech=rng.choice(ISSUE_TECHS),
    )


def _hours_lognormal(rng: random.Random, mean: float) -> float:
    """Sample from log-normal so the mean is roughly `mean` and we get
    realistic right-skew (most PRs fast, some outliers very slow)."""
    # log-normal with mu so that exp(mu + sigma^2/2) ≈ mean.
    sigma = 0.9
    import math
    mu = math.log(mean) - (sigma ** 2) / 2
    return rng.lognormvariate(mu, sigma)


@dataclass
class SeedCounts:
    """Tally for the orchestrator."""
    squads: int = 0
    repos: int = 0
    prs: int = 0
    issues: int = 0
    deploys: int = 0
    sprints: int = 0
    snapshots: int = 0
    catalog_entries: int = 0
    watermarks: int = 0


async def gen_jira_config(s) -> None:
    """One-shot upsert of tenant_jira_config so the discovery layer behaves."""
    await s.execute(text("""
        INSERT INTO tenant_jira_config (
            tenant_id, mode, discovery_enabled, max_active_projects,
            max_issues_per_hour, smart_pr_scan_days, smart_min_pr_references
        ) VALUES (
            :tid, 'allowlist', true, 100, 20000, 90, 3
        )
        ON CONFLICT (tenant_id) DO NOTHING
    """), {"tid": str(DEV_TENANT_ID)})


async def gen_jira_catalog(s, profiles: list[SquadProfile]) -> int:
    """Create one jira_project_catalog row per squad (status=active)."""
    n = 0
    for p in profiles:
        await s.execute(text("""
            INSERT INTO jira_project_catalog (
                tenant_id, project_key, name, project_type, status,
                activation_source, issue_count
            ) VALUES (
                :tid, :key, :name, 'software', 'active', 'seed_dev', :ic
            )
            ON CONFLICT DO NOTHING
        """), {
            "tid": str(DEV_TENANT_ID),
            "key": p.key,
            "name": f"{p.tribe} — {p.key}",
            "ic": p.issue_count,
        })
        n += 1
    return n


async def gen_watermarks(s) -> int:
    """Watermarks make pipeline-monitor show 'recently synced' state."""
    now = datetime.now(timezone.utc)
    n = 0
    for entity in ("github_prs", "jira_issues", "jenkins_deploys", "jira_sprints"):
        await s.execute(text("""
            INSERT INTO pipeline_watermarks (
                tenant_id, entity_type, last_synced_at, records_synced
            ) VALUES (
                :tid, :etype, :ts, :n
            )
            ON CONFLICT DO NOTHING
        """), {
            "tid": str(DEV_TENANT_ID),
            "etype": entity,
            "ts": now - timedelta(minutes=5),
            "n": 1234,
        })
        n += 1
    return n


async def gen_prs(
    s, rng: random.Random, profiles: list[SquadProfile], window_days: int = 90
) -> tuple[int, int]:
    """Generate PRs across the time window.

    Returns (pr_count, repo_count). External_ids are seed_dev:pr:<n> so they
    don't collide with real GitHub IDs and are trivially filterable.
    """
    now = datetime.now(timezone.utc)
    pr_idx = 0
    repos_seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for p in profiles:
        repos = REPO_PATTERNS[p.key]
        repos_seen.update(repos)

        for _ in range(p.pr_count):
            repo = rng.choice(repos)
            # Spread across the window with weight toward recent (so trends
            # show meaningful "last 30d" spikes).
            offset_days = rng.betavariate(2.0, 5.0) * window_days
            created = now - timedelta(days=offset_days)
            lt_hours = _hours_lognormal(rng, p.lead_time_hours_mean)

            first_commit = created - timedelta(hours=rng.uniform(0.5, 6))
            first_review = created + timedelta(hours=rng.uniform(0.5, 24))

            # Some PRs are still open (~10%), most merged, ~5% closed.
            r = rng.random()
            if r < 0.85:
                state, is_merged = "merged", True
                merged = first_review + timedelta(hours=rng.uniform(0.5, 24))
                deployed = first_commit + timedelta(hours=lt_hours)
                approved = first_review + timedelta(hours=rng.uniform(0.1, 4))
                closed = None
            elif r < 0.95:
                state, is_merged = "open", False
                merged = None
                deployed = None
                approved = None
                closed = None
            else:
                state, is_merged = "closed", False
                merged = None
                deployed = None
                approved = None
                closed = first_review + timedelta(hours=rng.uniform(1, 48))

            additions = max(1, int(rng.lognormvariate(4.0, 1.0)))
            deletions = max(0, int(rng.lognormvariate(3.5, 1.0)))

            rows.append({
                "tenant_id": str(DEV_TENANT_ID),
                "external_id": f"{SEED_MARKER_PREFIX}pr:{pr_idx:06d}",
                "source": "github",
                "repo": f"acme-dev/{repo}",
                "title": _gen_pr_title(rng, p.key, ticket_n=rng.randint(1, p.issue_count)),
                "author": _fake_author(rng, p.key),
                "state": state,
                # `created_at` is canonical "PR opened" — required by /pipeline/teams
                # which filters PRs in the last 90d. Without it, the endpoint sees
                # zero squads even though PRs exist (NULL fails > comparison).
                "created_at": created,
                "first_commit_at": first_commit,
                "first_review_at": first_review,
                "approved_at": approved,
                "merged_at": merged,
                "deployed_at": deployed,
                "closed_at": closed,
                "additions": additions,
                "deletions": deletions,
                "files_changed": rng.randint(1, 20),
                "commits_count": rng.randint(1, 8),
                "is_merged": is_merged,
                "linked_issue_ids": "[]",
                "reviewers": "[]",
                "url": f"https://github.example.invalid/acme-dev/{repo}/pull/{pr_idx}",
            })
            pr_idx += 1

    # Bulk insert via raw SQL (faster than ORM bulk_insert with this volume).
    if rows:
        await s.execute(text("""
            INSERT INTO eng_pull_requests (
                tenant_id, external_id, source, repo, title, author, state,
                created_at, first_commit_at, first_review_at, approved_at,
                merged_at, deployed_at, closed_at, additions, deletions,
                files_changed, commits_count, is_merged, linked_issue_ids,
                reviewers, url
            ) VALUES (
                :tenant_id, :external_id, :source, :repo, :title, :author, :state,
                :created_at, :first_commit_at, :first_review_at, :approved_at,
                :merged_at, :deployed_at, :closed_at, :additions, :deletions,
                :files_changed, :commits_count, :is_merged,
                CAST(:linked_issue_ids AS jsonb), CAST(:reviewers AS jsonb), :url
            )
        """), rows)

    return pr_idx, len(repos_seen)


async def gen_issues(
    s, rng: random.Random, profiles: list[SquadProfile], window_days: int = 90
) -> int:
    """Generate issues across the time window.

    Status mix: 15% todo / 20% in_progress / 10% in_review / 55% done.
    Issues drive Lean/Flow metrics (WIP, lead-time distribution, CFD).
    """
    now = datetime.now(timezone.utc)
    iss_idx = 0
    rows: list[dict[str, Any]] = []

    for p in profiles:
        statuses = (
            ["todo"] * int(p.issue_count * 0.15) +
            ["in_progress"] * int(p.issue_count * 0.20) +
            ["in_review"] * int(p.issue_count * 0.10) +
            ["done"] * int(p.issue_count * 0.55)
        )
        # Pad to exactly issue_count via "done" if rounding short.
        while len(statuses) < p.issue_count:
            statuses.append("done")
        rng.shuffle(statuses)

        for status in statuses:
            offset_days = rng.betavariate(2.0, 5.0) * window_days
            created = now - timedelta(days=offset_days)
            started: datetime | None = None
            completed: datetime | None = None

            if status in ("in_progress", "in_review", "done"):
                started = created + timedelta(hours=rng.uniform(2, 72))
            if status == "done":
                cycle_h = _hours_lognormal(rng, p.lead_time_hours_mean * 0.7)
                completed = (started or created) + timedelta(hours=cycle_h)

            jira_status = {
                "todo": "To Do",
                "in_progress": "In Progress",
                "in_review": "In Review",
                "done": "Done",
            }[status]

            issue_key = f"{p.key}-{iss_idx + 1}"
            priority = rng.choices(
                ["Highest", "High", "Medium", "Low"],
                weights=[10, 25, 50, 15],
            )[0]
            issue_type = rng.choices(
                ["Story", "Task", "Bug", "Tech Debt"],
                weights=[40, 30, 20, 10],
            )[0]

            rows.append({
                "tenant_id": str(DEV_TENANT_ID),
                "external_id": f"{SEED_MARKER_PREFIX}issue:{iss_idx:06d}",
                "source": "jira",
                "project_key": p.key,
                "issue_type": issue_type,
                "title": _gen_issue_title(rng, p.key),
                "status": jira_status,
                "normalized_status": status,
                "priority": priority,
                "assignee": _fake_author(rng, p.key),
                "story_points": rng.choice([1.0, 2.0, 3.0, 5.0, 8.0, 13.0, None]),
                "created_at": created,
                "started_at": started,
                "completed_at": completed,
                "sprint_id": None,
                "status_transitions": "[]",
                "linked_pr_ids": "[]",
                "url": f"https://jira.example.invalid/browse/{issue_key}",
                "issue_key": issue_key,
                "description": None,
            })
            iss_idx += 1

    # Insert in batches of 1000 to keep memory + transaction size sane.
    BATCH = 1000
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        await s.execute(text("""
            INSERT INTO eng_issues (
                tenant_id, external_id, source, project_key, issue_type,
                title, status, normalized_status, priority, assignee,
                story_points, created_at, started_at, completed_at,
                sprint_id, status_transitions, linked_pr_ids, url, issue_key,
                description
            ) VALUES (
                :tenant_id, :external_id, :source, :project_key, :issue_type,
                :title, :status, :normalized_status, :priority, :assignee,
                :story_points, :created_at, :started_at, :completed_at,
                :sprint_id, CAST(:status_transitions AS jsonb),
                CAST(:linked_pr_ids AS jsonb), :url, :issue_key, :description
            )
        """), batch)

    return iss_idx


async def gen_deploys(
    s, rng: random.Random, profiles: list[SquadProfile], window_days: int = 90
) -> int:
    """Generate deployments. Source = jenkins (matches Webmotors reality)."""
    now = datetime.now(timezone.utc)
    dep_idx = 0
    rows: list[dict[str, Any]] = []

    for p in profiles:
        repos = REPO_PATTERNS[p.key]
        for _ in range(p.deploy_count):
            offset_days = rng.uniform(0, window_days)
            deployed = now - timedelta(days=offset_days)
            is_failure = rng.random() < p.change_failure_rate
            repo = rng.choice(repos)

            rows.append({
                "tenant_id": str(DEV_TENANT_ID),
                "external_id": f"{SEED_MARKER_PREFIX}deploy:{dep_idx:06d}",
                "source": "jenkins",
                "repo": f"acme-dev/{repo}",
                "environment": "production",
                "deployed_at": deployed,
                "is_failure": is_failure,
                "recovery_time_hours": (
                    _hours_lognormal(rng, 4.0) if is_failure else None
                ),
                "trigger_type": "scm",
                "trigger_ref": f"refs/heads/main",
                "url": f"https://jenkins.example.invalid/job/{repo}/build/{dep_idx}",
                "sha": f"{rng.randrange(0, 16**40):040x}",
                "author": _fake_author(rng, p.key),
            })
            dep_idx += 1

    if rows:
        await s.execute(text("""
            INSERT INTO eng_deployments (
                tenant_id, external_id, source, repo, environment,
                deployed_at, is_failure, recovery_time_hours, trigger_type,
                trigger_ref, url, sha, author
            ) VALUES (
                :tenant_id, :external_id, :source, :repo, :environment,
                :deployed_at, :is_failure, :recovery_time_hours, :trigger_type,
                :trigger_ref, :url, :sha, :author
            )
        """), rows)

    return dep_idx


async def gen_sprints(
    s, rng: random.Random, profiles: list[SquadProfile]
) -> int:
    """Generate sprints for sprint-capable squads (10 squads × 6 sprints)."""
    now = datetime.now(timezone.utc)
    spr_idx = 0
    rows: list[dict[str, Any]] = []

    for p in profiles:
        if not p.has_sprints:
            continue
        # 6 fortnightly sprints over the last 90d.
        for sprint_n in range(6):
            start = now - timedelta(days=14 * (6 - sprint_n))
            end = start + timedelta(days=14)
            committed = rng.randint(20, 40)
            completed = max(0, committed - rng.randint(0, 8))
            added = rng.randint(0, 5)
            removed = rng.randint(0, 3)
            carried = max(0, committed + added - completed - removed)

            rows.append({
                "tenant_id": str(DEV_TENANT_ID),
                "external_id": f"{SEED_MARKER_PREFIX}sprint:{spr_idx:06d}",
                "source": "jira",
                "board_id": f"{SEED_MARKER_PREFIX}board:{p.key}",
                "name": f"{p.key} Sprint {sprint_n + 1}",
                "status": "closed" if end < now else "active",
                "goal": f"Deliver {p.key.lower()}-related work for sprint {sprint_n + 1}",
                "started_at": start,
                "completed_at": end if end < now else None,
                "committed_items": committed,
                "committed_points": float(committed * 3),
                "added_items": added,
                "removed_items": removed,
                "completed_items": completed,
                "completed_points": float(completed * 3),
                "carried_over_items": carried,
            })
            spr_idx += 1

    if rows:
        await s.execute(text("""
            INSERT INTO eng_sprints (
                tenant_id, external_id, source, board_id, name, status, goal,
                started_at, completed_at, committed_items, committed_points,
                added_items, removed_items, completed_items, completed_points,
                carried_over_items
            ) VALUES (
                :tenant_id, :external_id, :source, :board_id, :name, :status, :goal,
                :started_at, :completed_at, :committed_items, :committed_points,
                :added_items, :removed_items, :completed_items, :completed_points,
                :carried_over_items
            )
        """), rows)

    return spr_idx


# =============================================================================
# SNAPSHOTS — pre-compute so /metrics/home doesn't hit cold path
# =============================================================================

# These are the metric_name keys the /metrics/home endpoint reads. The
# `value` payload shapes mirror what metrics_worker writes (verified
# against a live snapshot in the dev DB — see commit message for query).
def _build_dora_snapshot(p_archetypes: list[str], rng: random.Random) -> dict[str, Any]:
    """Tenant-wide DORA aggregate. Deterministic per archetype mix."""
    # Compute weighted average of the per-squad archetype values to give a
    # plausible tenant-level DORA snapshot. Devs see contrasting badges
    # because team-level pages drill into specific squads.
    counts = {a: p_archetypes.count(a) for a in set(p_archetypes)}
    n = max(1, sum(counts.values()) - counts.get("empty", 0))

    df_per_week = sum(
        SquadProfile(key="X", tribe="X", archetype=a, pr_count=0,
                     deploy_count=0, issue_count=0, has_sprints=False).deploy_freq_per_week
        * cnt for a, cnt in counts.items()
    ) / n
    df_per_day = df_per_week / 7

    cfr = sum(
        SquadProfile(key="X", tribe="X", archetype=a, pr_count=0,
                     deploy_count=0, issue_count=0, has_sprints=False).change_failure_rate
        * cnt for a, cnt in counts.items()
    ) / n

    lt = sum(
        SquadProfile(key="X", tribe="X", archetype=a, pr_count=0,
                     deploy_count=0, issue_count=0, has_sprints=False).lead_time_hours_mean
        * cnt for a, cnt in counts.items()
    ) / n

    # DORA classification thresholds (2023):
    df_level = "elite" if df_per_day >= 1 else "high" if df_per_day >= 1/7 else "medium" if df_per_day >= 1/30 else "low"
    lt_level = "elite" if lt < 24 else "high" if lt < 168 else "medium" if lt < 720 else "low"
    cfr_level = "elite" if cfr <= 0.15 else "high" if cfr <= 0.20 else "medium" if cfr <= 0.30 else "low"

    return {
        "deployment_frequency_per_day": df_per_day,
        "deployment_frequency_per_week": df_per_week,
        "lead_time_for_changes_hours": lt,
        "lead_time_for_changes_hours_strict": lt * 1.6,  # strict is slower
        "lead_time_strict_total_count": int(n * 200),
        "lead_time_strict_eligible_count": int(n * 80),
        "change_failure_rate": cfr,
        "mean_time_to_recovery_hours": None,  # MTTR is FDD-DSH-050, not seeded
        "df_level": df_level,
        "lt_level": lt_level,
        "lt_strict_level": lt_level,
        "cfr_level": cfr_level,
        "mttr_level": None,
        "overall_level": min([df_level, lt_level, cfr_level],
                              key=lambda lvl: ["elite", "high", "medium", "low"].index(lvl)),
    }


def _build_cycle_time_breakdown(rng: random.Random) -> dict[str, Any]:
    """cycle_time/breakdown payload — uses total_p50, total_p85."""
    p50 = rng.uniform(8, 24)
    p85 = p50 * rng.uniform(2.5, 4.0)
    return {
        "total_p50": p50,
        "total_p85": p85,
        "phases": {
            "coding": {"p50": p50 * 0.4, "p85": p85 * 0.4},
            "pickup": {"p50": p50 * 0.15, "p85": p85 * 0.15},
            "review": {"p50": p50 * 0.25, "p85": p85 * 0.25},
            "merge_to_deploy": {"p50": p50 * 0.20, "p85": p85 * 0.20},
        },
        "bottleneck_phase": "review",
        "pr_count": 200,
    }


def _build_throughput_pr_analytics(profiles: list[SquadProfile]) -> dict[str, Any]:
    """throughput/pr_analytics — uses total_merged."""
    total_merged = int(sum(p.pr_count * 0.85 for p in profiles))
    return {
        "total_merged": total_merged,
        "avg_size_lines": 145,
        "first_review_p50_hours": 6.5,
        "review_turnaround_p50_hours": 18.0,
    }


def _build_lean_wip(profiles: list[SquadProfile]) -> dict[str, Any]:
    """lean/wip — uses wip_count."""
    wip = int(sum(p.issue_count * 0.20 for p in profiles))  # 20% in_progress
    return {
        "wip_count": wip,
        "wip_per_squad": {p.key: int(p.issue_count * 0.20) for p in profiles},
        "wip_threshold": 250,
    }


# Lean has multiple metric_names — the home endpoint only reads "wip" but
# the /metrics/lean dedicated page also reads cfd, throughput, lead_time_distribution,
# scatterplot. Stub them with minimal valid payloads so that page renders.
def _build_lean_stubs(profiles: list[SquadProfile], rng: random.Random) -> dict[str, dict[str, Any]]:
    return {
        "cfd": {"weeks": [{"week": i, "todo": rng.randint(40, 80),
                            "in_progress": rng.randint(20, 50),
                            "in_review": rng.randint(10, 30),
                            "done": rng.randint(50, 200)}
                          for i in range(12)]},
        "throughput": {"per_week": [rng.randint(20, 60) for _ in range(12)],
                       "trend": "stable"},
        "lead_time_distribution": {"p50": 48.0, "p85": 168.0, "p95": 336.0,
                                    "histogram": [{"bin_hours": h, "count": rng.randint(5, 50)}
                                                  for h in (24, 72, 168, 336, 720)]},
        "scatterplot": {"points": []},  # empty is fine for first render
    }


async def gen_snapshots(
    s, rng: random.Random, profiles: list[SquadProfile]
) -> int:
    """Pre-compute snapshots for periods 30d/60d/90d/120d to avoid the
    50× cold-path discovered in 2026-04-24.

    Writes both the home-essential metric_names and lean stubs so that
    the dashboard + /metrics/lean page render fast on first load.
    """
    now = datetime.now(timezone.utc)
    archetypes = [p.archetype for p in profiles]
    n = 0
    rows: list[dict[str, Any]] = []

    for period_days in (30, 60, 90, 120):
        period_end = now
        period_start = now - timedelta(days=period_days)
        # Snapshots used by /metrics/home (tenant-wide, team_id NULL).
        for metric_type, metric_name, builder in (
            ("dora", "all", lambda: _build_dora_snapshot(archetypes, rng)),
            ("cycle_time", "breakdown", lambda: _build_cycle_time_breakdown(rng)),
            ("throughput", "pr_analytics", lambda: _build_throughput_pr_analytics(profiles)),
            ("lean", "wip", lambda: _build_lean_wip(profiles)),
        ):
            value = builder()
            rows.append({
                "tenant_id": str(DEV_TENANT_ID),
                "team_id": None,
                "metric_type": metric_type,
                "metric_name": metric_name,
                "value": _json_dumps(value),
                "period_start": period_start,
                "period_end": period_end,
                "calculated_at": now,
            })
            n += 1

        # Lean stubs (used by the /metrics/lean dedicated page).
        for name, value in _build_lean_stubs(profiles, rng).items():
            rows.append({
                "tenant_id": str(DEV_TENANT_ID),
                "team_id": None,
                "metric_type": "lean",
                "metric_name": name,
                "value": _json_dumps(value),
                "period_start": period_start,
                "period_end": period_end,
                "calculated_at": now,
            })
            n += 1

    if rows:
        await s.execute(text("""
            INSERT INTO metrics_snapshots (
                tenant_id, team_id, metric_type, metric_name,
                value, period_start, period_end, calculated_at
            ) VALUES (
                :tenant_id, :team_id, :metric_type, :metric_name,
                CAST(:value AS jsonb), :period_start, :period_end, :calculated_at
            )
            ON CONFLICT (tenant_id, team_id, metric_type, metric_name, period_start, period_end)
            DO UPDATE SET value = EXCLUDED.value, calculated_at = EXCLUDED.calculated_at
        """), rows)

    return n


def _json_dumps(value: Any) -> str:
    """JSON-encode for raw SQL bind. Datetime-aware."""
    import json
    def default(o: Any) -> Any:
        if isinstance(o, (datetime,)):
            return o.isoformat()
        raise TypeError(f"not JSON-serializable: {type(o)}")
    return json.dumps(value, default=default)


# =============================================================================
# ORCHESTRATOR
# =============================================================================

async def main(args: argparse.Namespace) -> SeedCounts:
    print("=" * 72)
    print("PULSE — seed_dev")
    print(f"  tenant : {DEV_TENANT_ID}")
    print(f"  seed   : {args.seed}")
    print(f"  reset  : {args.reset}")
    print("=" * 72)

    # === GUARDS ===
    print("\n[1/3] Safety guards")
    await run_guards(args)

    # === RESET (if requested) ===
    if args.reset:
        print("\n[2/3] Reset")
        await reset_tenant()

    # === SEED ===
    print("\n[3/3] Generating fixture data")
    rng = random.Random(args.seed)
    profiles = _build_squad_profiles()
    counts = SeedCounts(squads=len(profiles))

    async with async_session_factory() as s:
        await s.execute(text(f"SET app.current_tenant = '{DEV_TENANT_ID}'"))

        print("→ tenant_jira_config …", end=" ", flush=True)
        await gen_jira_config(s)
        print("ok")

        print("→ jira_project_catalog …", end=" ", flush=True)
        counts.catalog_entries = await gen_jira_catalog(s, profiles)
        print(f"{counts.catalog_entries} rows")

        print("→ pipeline_watermarks …", end=" ", flush=True)
        counts.watermarks = await gen_watermarks(s)
        print(f"{counts.watermarks} rows")

        print("→ eng_pull_requests …", end=" ", flush=True)
        counts.prs, counts.repos = await gen_prs(s, rng, profiles)
        print(f"{counts.prs} PRs across {counts.repos} repos")

        print("→ eng_issues …", end=" ", flush=True)
        counts.issues = await gen_issues(s, rng, profiles)
        print(f"{counts.issues} issues")

        print("→ eng_deployments …", end=" ", flush=True)
        counts.deploys = await gen_deploys(s, rng, profiles)
        print(f"{counts.deploys} deploys")

        print("→ eng_sprints …", end=" ", flush=True)
        counts.sprints = await gen_sprints(s, rng, profiles)
        print(f"{counts.sprints} sprints")

        print("→ metrics_snapshots (pre-compute) …", end=" ", flush=True)
        counts.snapshots = await gen_snapshots(s, rng, profiles)
        print(f"{counts.snapshots} snapshots")

        await s.commit()

    print("\n" + "=" * 72)
    print("DONE — seed completed successfully")
    print(f"  squads             : {counts.squads}")
    print(f"  repos              : {counts.repos}")
    print(f"  PRs                : {counts.prs}")
    print(f"  issues             : {counts.issues}")
    print(f"  deploys            : {counts.deploys}")
    print(f"  sprints            : {counts.sprints}")
    print(f"  snapshots          : {counts.snapshots}")
    print(f"  catalog entries    : {counts.catalog_entries}")
    print(f"  watermarks         : {counts.watermarks}")
    print("=" * 72)
    print("\nNext: open http://localhost:5173 — dashboard should render fast.")
    print("      run `make verify-dev` to smoke-test the stack.\n")
    return counts


# =============================================================================
# CLI
# =============================================================================

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the PULSE dev DB with realistic fake data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety: this script REFUSES to run unless --confirm-local is set,\n"
            "PULSE_ENV is 'development', the DB host is localhost-class, the\n"
            "target tenant is the reserved dev tenant, and the tenant is empty\n"
            "(or --reset is also set).\n"
        ),
    )
    parser.add_argument(
        "--confirm-local", action="store_true",
        help="Required acknowledgement that this is a local dev DB.",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="DELETE all rows in the dev tenant before seeding (requires --confirm-local).",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"RNG seed for determinism (default: {DEFAULT_SEED}).",
    )
    return parser.parse_args(argv)


async def _async_entry(args: argparse.Namespace) -> int:
    """Async entry — keeps engine.dispose() in the same event loop as main()."""
    try:
        await main(args)
        return 0
    except GuardError as e:
        print(f"\n✖ {e}", file=sys.stderr)
        return 2
    except Exception as e:
        logger.exception("Seed failed: %s", e)
        return 1
    finally:
        # Dispose inside the same loop — running it under a fresh
        # `asyncio.run()` would try to close asyncpg connections from a
        # different loop and trigger "Event loop is closed" tracebacks.
        await engine.dispose()


def _entry_point() -> int:
    """Sync entry point usable by `python -m scripts.seed_dev`."""
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args()
    return asyncio.run(_async_entry(args))


if __name__ == "__main__":
    sys.exit(_entry_point())
