"""FDD-PIPE-001 — unit tests for squad qualification heuristic.

Tests the pure-Python reference implementation in
`pipeline/services/squad_qualification.py`. The SQL CTE in
`pipeline/routes.py:get_teams()` MUST stay aligned with this — every
boundary case here is a SQL contract.
"""

from __future__ import annotations

import pytest

from src.contexts.pipeline.services.squad_qualification import (
    DEFAULT_QUALIFICATION_CONFIG,
    SquadCandidate,
    qualify_squad,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate(
    *,
    project_key: str = "TEST",
    name: str | None = "Test Squad",
    issue_count: int = 100,
    prs: int = 50,
    override=None,
) -> SquadCandidate:
    return SquadCandidate(
        project_key=project_key,
        name=name,
        issue_count=issue_count,
        prs_referenced_90d=prs,
        qualification_override=override,
    )


# ---------------------------------------------------------------------------
# Real software squads (qualify automatically)
# ---------------------------------------------------------------------------

class TestRealSquads:
    def test_high_volume_squad_qualifies_active(self):
        """OKM-like: 266 PRs, 3470 issues, name populated → qualified, active."""
        result = qualify_squad(_candidate(name="PF - OEM Integração", prs=266, issue_count=3470))
        assert result.qualified is True
        assert result.tier == "active"
        assert result.qualification_source == "auto"
        assert result.has_metadata is True
        assert result.has_activity is True

    def test_low_volume_squad_qualifies_marginal(self):
        """CEU-like: 2 PRs, 0 issues, name populated → qualified (the bug we fixed!)."""
        result = qualify_squad(_candidate(name="PJ - Cockpit e Universidade", prs=2, issue_count=0))
        assert result.qualified is True
        assert result.tier == "marginal"
        assert result.qualification_source == "auto"

    def test_data_only_squad_qualifies_dormant(self):
        """Engenharia de Dados: 0 PRs in 90d but 6602 issues → qualified, dormant."""
        result = qualify_squad(_candidate(name="Eng e Gov Dados", prs=0, issue_count=6602))
        assert result.qualified is True
        assert result.tier == "dormant"

    def test_exact_active_threshold(self):
        """5 PRs (default min_prs=5) → active (boundary inclusive)."""
        result = qualify_squad(_candidate(prs=5))
        assert result.tier == "active"

    def test_one_below_active_threshold(self):
        """4 PRs → marginal (just below active boundary)."""
        result = qualify_squad(_candidate(prs=4))
        assert result.tier == "marginal"


# ---------------------------------------------------------------------------
# Regex noise (false positives — DON'T qualify)
# ---------------------------------------------------------------------------

class TestRegexNoise:
    def test_release_keyword_no_metadata_excluded(self):
        """RELEASE-like: 8 PRs but name='' (not a real Jira project) → excluded."""
        result = qualify_squad(_candidate(project_key="RELEASE", name="", prs=8, issue_count=0))
        assert result.qualified is False
        assert result.qualification_source == "auto"
        assert result.has_metadata is False
        assert result.has_activity is True  # has PRs, but no metadata kills it

    def test_cve_no_metadata_excluded(self):
        """CVE-2024-XXXX style → excluded by metadata gate."""
        result = qualify_squad(_candidate(project_key="CVE", name=None, prs=29, issue_count=0))
        assert result.qualified is False
        assert result.has_metadata is False

    def test_axios_no_metadata_excluded(self):
        """AXIOS (npm package bumps) → excluded."""
        result = qualify_squad(_candidate(project_key="AXIOS", name="", prs=7, issue_count=0))
        assert result.qualified is False

    def test_whitespace_only_name_treated_as_empty(self):
        """Defense: name=' ' (whitespace) → still no metadata."""
        result = qualify_squad(_candidate(name="   ", prs=5, issue_count=10))
        assert result.qualified is False
        assert result.has_metadata is False


# ---------------------------------------------------------------------------
# No-activity edge cases
# ---------------------------------------------------------------------------

class TestNoActivityCases:
    def test_metadata_but_zero_activity_excluded(self):
        """Real Jira project (name) but 0 PRs and 0 issues → excluded."""
        result = qualify_squad(_candidate(name="Stale Project", prs=0, issue_count=0))
        assert result.qualified is False
        assert result.has_metadata is True
        assert result.has_activity is False


# ---------------------------------------------------------------------------
# Operator overrides (force-qualify / force-exclude)
# ---------------------------------------------------------------------------

class TestOverrides:
    def test_force_qualified_includes_regex_noise(self):
        """Operator can override: forced 'qualified' on RELEASE-like → qualified."""
        result = qualify_squad(_candidate(name="", prs=8, issue_count=0, override="qualified"))
        assert result.qualified is True
        assert result.qualification_source == "override"

    def test_force_excluded_kicks_out_real_squad(self):
        """Operator can override: forced 'excluded' on real squad → not qualified."""
        result = qualify_squad(_candidate(name="Real Squad", prs=200, issue_count=1000, override="excluded"))
        assert result.qualified is False
        assert result.qualification_source == "override"
        # Tier still computed for UI
        assert result.tier == "active"

    def test_no_override_uses_heuristic(self):
        """Override=None → falls back to auto."""
        result = qualify_squad(_candidate(override=None))
        assert result.qualification_source == "auto"


# ---------------------------------------------------------------------------
# Per-tenant config knobs
# ---------------------------------------------------------------------------

class TestConfigKnobs:
    def test_lower_min_prs_active_tier(self):
        """Tenant sets min_prs_active=3 → 3 PRs becomes active (was marginal)."""
        result = qualify_squad(
            _candidate(prs=3),
            config={**DEFAULT_QUALIFICATION_CONFIG, "min_prs_90d_active_tier": 3},
        )
        assert result.tier == "active"

    def test_higher_min_prs_active_tier(self):
        """Tenant sets min_prs_active=10 → 5 PRs becomes marginal (was active)."""
        result = qualify_squad(
            _candidate(prs=5),
            config={**DEFAULT_QUALIFICATION_CONFIG, "min_prs_90d_active_tier": 10},
        )
        assert result.tier == "marginal"

    def test_disable_metadata_requirement(self):
        """When require_metadata=False, regex noise with PRs gets through (use with care)."""
        result = qualify_squad(
            _candidate(name="", prs=10, issue_count=0),
            config={
                **DEFAULT_QUALIFICATION_CONFIG,
                "qualification_requires_metadata": False,
            },
        )
        assert result.qualified is True

    def test_disable_activity_requirement(self):
        """When require_activity=False, dormant projects with metadata still pass."""
        result = qualify_squad(
            _candidate(name="Dormant Real", prs=0, issue_count=0),
            config={
                **DEFAULT_QUALIFICATION_CONFIG,
                "qualification_requires_any_activity": False,
            },
        )
        assert result.qualified is True


# ---------------------------------------------------------------------------
# Default config sanity
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def test_default_matches_migration(self):
        """Defaults must match what migration 014 sets — SaaS contract."""
        assert DEFAULT_QUALIFICATION_CONFIG == {
            "min_prs_90d_active_tier": 5,
            "include_data_only_squads": True,
            "qualification_requires_metadata": True,
            "qualification_requires_any_activity": True,
        }
