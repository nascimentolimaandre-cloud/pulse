"""Unit tests for scripts.seed_dev — guards + determinism + shape sanity.

These tests deliberately avoid hitting a real database. They cover:

  - Safety guards 1-4 (CLI, env, host, tenant) — pure functions
  - Determinism: same seed produces byte-identical output across two runs
  - Profile shape: 15 squads, 4 tribes, archetype distribution sane
  - Title generation: extracts a Jira-style key the /pipeline/teams endpoint
    can find via its regex

Guard 5 (data-state) requires a session and is covered by the smoke test
that runs `make seed-dev` end-to-end against the live DB. Skipping it here
keeps these tests fast (<100ms) and independent of postgres.
"""

from __future__ import annotations

import argparse
import re
from unittest.mock import patch

import pytest

from scripts.seed_dev import (
    DEV_TENANT_ID,
    SEED_MARKER_PREFIX,
    SPRINT_CAPABLE_SQUADS,
    SQUAD_ARCHETYPES,
    TRIBES,
    GuardError,
    SquadProfile,
    _build_squad_profiles,
    _gen_pr_title,
    _guard_1_cli_flag,
    _guard_2_env,
    _guard_3_host,
    _guard_4_tenant,
)


# ---------------------------------------------------------------- guards
class TestGuards:
    def test_guard_1_blocks_when_flag_missing(self):
        args = argparse.Namespace(confirm_local=False, reset=False, seed=42)
        with pytest.raises(GuardError, match="--confirm-local is REQUIRED"):
            _guard_1_cli_flag(args)

    def test_guard_1_passes_when_flag_set(self):
        args = argparse.Namespace(confirm_local=True, reset=False, seed=42)
        _guard_1_cli_flag(args)  # no raise

    @pytest.mark.parametrize("env", ["production", "prod", "staging", "stg", "PRODUCTION", "Stg"])
    def test_guard_2_blocks_non_dev_envs(self, env, monkeypatch):
        monkeypatch.setenv("PULSE_ENV", env)
        with pytest.raises(GuardError, match="refusing to seed"):
            _guard_2_env()

    @pytest.mark.parametrize("env", ["development", "dev", "DEV", "test", ""])
    def test_guard_2_allows_dev_envs(self, env, monkeypatch):
        monkeypatch.setenv("PULSE_ENV", env)
        _guard_2_env()  # no raise

    def test_guard_2_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("PULSE_ENV", raising=False)
        _guard_2_env()  # default = development

    def test_guard_3_allows_localhost(self):
        with patch("scripts.seed_dev.settings") as mock:
            mock.async_database_url = "postgresql+asyncpg://u:p@localhost:5432/d"
            _guard_3_host()

    def test_guard_3_allows_postgres_hostname(self):
        with patch("scripts.seed_dev.settings") as mock:
            mock.async_database_url = "postgresql+asyncpg://u:p@postgres:5432/d"
            _guard_3_host()

    def test_guard_3_blocks_remote_host(self):
        with patch("scripts.seed_dev.settings") as mock:
            mock.async_database_url = "postgresql+asyncpg://u:p@db.prod.example.com:5432/d"
            with pytest.raises(GuardError, match="refusing to seed"):
                _guard_3_host()

    def test_guard_4_passes_for_dev_tenant(self):
        _guard_4_tenant(DEV_TENANT_ID)

    def test_guard_4_blocks_random_tenant(self):
        from uuid import UUID
        prod = UUID("12345678-1234-5678-1234-567812345678")
        with pytest.raises(GuardError, match="seed_dev only writes to the reserved"):
            _guard_4_tenant(prod)


# ---------------------------------------------------------------- profiles
class TestSquadProfiles:
    def test_15_squads_across_4_tribes(self):
        profiles = _build_squad_profiles()
        assert len(profiles) == 15
        assert {p.tribe for p in profiles} == set(TRIBES.keys())
        assert {p.tribe for p in profiles} == {"Payments", "Core Platform", "Growth", "Product"}

    def test_each_squad_has_archetype(self):
        profiles = _build_squad_profiles()
        for p in profiles:
            assert p.archetype in {"elite", "high", "medium", "low", "degraded", "empty"}
            assert p.archetype == SQUAD_ARCHETYPES[p.key]

    def test_sprint_capable_squads_match_constant(self):
        profiles = _build_squad_profiles()
        capable = {p.key for p in profiles if p.has_sprints}
        assert capable == SPRINT_CAPABLE_SQUADS

    def test_archetype_drives_volume(self):
        profiles = {p.key: p for p in _build_squad_profiles()}
        # Elite produces more PRs than Low.
        assert profiles["PAY"].pr_count > profiles["OBS"].pr_count
        # Empty produces zero PRs.
        assert profiles["DSGN"].pr_count == 0
        # Elite has higher deploy frequency.
        elite = SquadProfile("X", "X", "elite", 0, 0, 0, False)
        low = SquadProfile("X", "X", "low", 0, 0, 0, False)
        assert elite.deploy_freq_per_week > low.deploy_freq_per_week
        # Elite has lower change failure rate.
        assert elite.change_failure_rate < low.change_failure_rate

    def test_distribution_covers_all_dora_classifications(self):
        archetypes = set(SQUAD_ARCHETYPES.values())
        # We need at least one of each so the dashboard ranking shows
        # contrasting badges (otherwise UX is monotone).
        assert "elite" in archetypes
        assert "high" in archetypes
        assert "medium" in archetypes
        assert "low" in archetypes
        # Plus the edge-case states.
        assert "degraded" in archetypes
        assert "empty" in archetypes


# ---------------------------------------------------------------- determinism
class TestDeterminism:
    def test_pr_title_deterministic_for_same_seed(self):
        import random
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        for n in range(100):
            t_a = _gen_pr_title(rng_a, "PAY", ticket_n=n)
            t_b = _gen_pr_title(rng_b, "PAY", ticket_n=n)
            assert t_a == t_b, f"title diverged at iter {n}: {t_a!r} != {t_b!r}"

    def test_pr_title_differs_across_seeds(self):
        import random
        rng_a = random.Random(42)
        rng_b = random.Random(99)
        diffs = 0
        for n in range(50):
            if _gen_pr_title(rng_a, "PAY", n) != _gen_pr_title(rng_b, "PAY", n):
                diffs += 1
        # Different seeds → most should differ. Some collisions are OK,
        # but >40 of 50 should be different.
        assert diffs > 40


# ---------------------------------------------------------------- shape
class TestPrTitleShape:
    """The /pipeline/teams endpoint extracts squads via this regex.

    If the seed PR titles ever stop matching, /pipeline/teams returns
    "0 squads" and the smoke E2E fails with no obvious cause.
    Lock the format with a test.
    """

    PIPELINE_TEAMS_REGEX = re.compile(r"\b([A-Za-z][A-Za-z0-9]+)-\d+")

    def test_title_contains_jira_style_key(self):
        import random
        rng = random.Random(42)
        for squad in ("PAY", "AUTH", "OBS", "DSGN"):
            for _ in range(20):
                title = _gen_pr_title(rng, squad, ticket_n=rng.randint(1, 500))
                m = self.PIPELINE_TEAMS_REGEX.search(title)
                assert m is not None, f"no Jira key in: {title!r}"
                assert m.group(1).upper() == squad, f"key={m.group(1)} squad={squad} title={title!r}"


# ---------------------------------------------------------------- marker
def test_seed_marker_prefix_is_distinctive():
    """The marker must be:
      - filterable by simple LIKE prefix (cleanup queries)
      - distinct from any legitimate external_id format from real connectors
        (github numeric, jira PROJECT-N, jenkins build URLs)
    """
    assert SEED_MARKER_PREFIX == "seed_dev:"
    assert ":" in SEED_MARKER_PREFIX, "must contain ':' so it doesn't collide with regular IDs"
    assert SEED_MARKER_PREFIX.startswith("seed_"), "prefix must declare intent"
