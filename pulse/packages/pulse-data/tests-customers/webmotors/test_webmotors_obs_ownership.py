"""Webmotors — Observability ownership coverage validation (FDD-OBS-001 PR 3.5).

Validates that the Webmotors-specific outcome of the alias mapping work
holds true:

- Datadog credential is configured (skip otherwise — fresh CI has none).
- The DD Service Definition catalog has been synced and surfaces the
  expected ballpark of services (≥ 200 — Webmotors had 473 at PR 3 live).
- Tier-1 ownership coverage (effective_squad ∈ qualified_squads) is
  ≥ 80%. We hit 90.9% on 2026-05-08 with 11 aliases; 80% leaves margin
  for vendor team additions on the DD side (a few new services tagged
  to a new vendor team would dip coverage temporarily).
- The 11 known DD vendor teams from the 2026-05-08 mapping session are
  all aliased — guards against accidental migration / wipe.
- The top-5 known squads (CRW, SALES, INTG, ENO, ESTQ) all have at
  least one DD-tracked service. Catches regressions where the alias
  for one of these squads gets dropped or an inference run wipes
  inferred_squad_key for them.

Tests are READ-ONLY — they NEVER call Datadog directly. They inspect
the state left by the most recent operator sync. That keeps the suite
deterministic and fast (no flaky network).

Tests are auto-skipped (per the conftest pattern) when:
- Webmotors data isn't loaded (CI / fresh dev env)
- No DD credential is configured (test-local skip below)
- SKIP_CUSTOMER_TESTS=true

Classification: CUSTOMER (Webmotors-specific values + DD taxonomy).
"""

from __future__ import annotations

import pytest


# Vendor teams the operator mapped during the 2026-05-08 PR 3.5 session.
# Adding to this set is a deliberate operation: when Webmotors's DD adds
# a new team, this list should grow + the test fails until aliased.
_EXPECTED_ALIASED_VENDOR_TEAMS = frozenset({
    "agenda-facil",
    "anunciar",
    "arquitetura",
    "cockpit",
    "crm",
    "encontrar-oferta",
    "estoque",
    "integrações",
    "money",
    "pi-sales",
    "universidade",
})

# Top-5 squads by DD-service count after 2026-05-08 alias mapping.
# These represent the bulk of Webmotors's DD coverage (≈ 91% combined).
# Regression guard: each must keep at least one DD-tracked service.
_TOP_5_DD_BACKED_SQUADS = ("CRW", "SALES", "INTG", "ENO", "ESTQ")

# Coverage floor: real measurement was 0.909 on 2026-05-08. 0.80 leaves
# absorption for new DD services tagged to a yet-unmapped vendor team.
_MIN_COVERAGE_PCT = 0.80

# Service-count floor: Webmotors had 473 at PR 3 live test. 200 is a
# conservative threshold catching "DD pagination broken / sync produced
# zero" regressions without flapping on org changes.
_MIN_SERVICES_SEEN = 200

# Alias-count floor: we set 11 aliases on 2026-05-08. 10 catches a
# silent migration drop or accidental DELETE while leaving room for
# operator to remove one alias intentionally.
_MIN_ALIAS_COUNT = 10


# ---------------------------------------------------------------------------
# Local skip: DD credential must be configured (else nothing to validate)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _skip_if_no_dd_credential(psql):
    """Test-local skip: every test in this file requires a Datadog
    credential configured for the Webmotors tenant. Without it, the
    `service_squad_ownership` table will be empty and assertions
    would be misleading."""
    has_cred = psql(
        "SELECT COUNT(*) FROM tenant_observability_credentials "
        "WHERE provider = 'datadog'"
    )
    try:
        n = int(has_cred or 0)
    except (TypeError, ValueError):
        n = 0
    if n == 0:
        pytest.skip(
            "No Datadog credential configured for Webmotors tenant. "
            "Run POST /admin/integrations/datadog/validate?persist=true "
            "first."
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_webmotors_dd_service_catalog_synced(psql):
    """At least one inference sync has produced ≥ 200 ownership rows.
    Catches: DD pagination broken, /api/v2/services/definitions returns
    nothing, or the rollup wiped the table."""
    count = psql(
        "SELECT COUNT(*) FROM service_squad_ownership WHERE provider = 'datadog'"
    )
    try:
        n = int(count or 0)
    except (TypeError, ValueError):
        n = 0
    assert n >= _MIN_SERVICES_SEEN, (
        f"Webmotors DD ownership table has {n} rows, expected ≥ {_MIN_SERVICES_SEEN}. "
        f"Last operator sync may have failed mid-page or the table was reset. "
        f"Re-run POST /admin/integrations/datadog/ownership/sync."
    )


def test_webmotors_dd_ownership_coverage_at_least_floor(psql):
    """Effective squad maps to a qualified PULSE squad for ≥ 80% of
    DD services. Real measurement was 90.9% on 2026-05-08."""
    qualified_squads_subquery = (
        "SELECT project_key FROM jira_project_catalog "
        "WHERE status IN ('active', 'discovered') "
        "AND (qualification_override IS NULL OR qualification_override <> 'excluded')"
    )
    coverage_query = f"""
        WITH effective AS (
            SELECT COALESCE(override_squad_key, inferred_squad_key) AS squad
            FROM service_squad_ownership
            WHERE provider = 'datadog'
        ),
        counts AS (
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE squad IN ({qualified_squads_subquery})
                ) AS qualified
            FROM effective
        )
        SELECT
            total,
            qualified,
            CASE WHEN total = 0 THEN 0
                 ELSE ROUND((qualified::numeric / total) * 10000) / 10000
            END AS pct
        FROM counts
    """
    result = psql(coverage_query)
    assert result, "Coverage query returned no rows"
    parts = result.split("|")
    assert len(parts) == 3, f"Unexpected coverage result shape: {result!r}"
    total = int(parts[0])
    qualified = int(parts[1])
    pct = float(parts[2])

    assert total >= _MIN_SERVICES_SEEN, (
        f"DD service inventory too small ({total}); upstream test "
        f"`test_webmotors_dd_service_catalog_synced` should catch this first."
    )
    assert pct >= _MIN_COVERAGE_PCT, (
        f"Webmotors DD ownership coverage dropped to {pct:.2%} "
        f"({qualified}/{total} services). Floor: {_MIN_COVERAGE_PCT:.0%}. "
        f"Likely cause: a new DD vendor team was introduced and lacks an alias. "
        f"Check GET /admin/integrations/datadog/aliases/suggestions to see "
        f"unmapped teams; bulk-import the new mappings to restore coverage."
    )


def test_webmotors_known_alias_set_is_configured(psql):
    """All 11 vendor teams mapped on 2026-05-08 must still be aliased.
    Guards against accidental DELETE FROM tenant_team_alias or migration
    rollback removing the alias rows."""
    aliased_query = """
        SELECT string_agg(vendor_team_value, ',' ORDER BY vendor_team_value)
        FROM tenant_team_alias
        WHERE provider = 'datadog'
    """
    result = psql(aliased_query)
    aliased_set = set((result or "").split(",")) - {""}

    missing = _EXPECTED_ALIASED_VENDOR_TEAMS - aliased_set
    assert not missing, (
        f"Expected aliases for {sorted(_EXPECTED_ALIASED_VENDOR_TEAMS)}, "
        f"missing: {sorted(missing)}. Re-run the bulk import documented in "
        f"docs/runbooks/observability-bootstrap.md (or the PR 3.5 chat "
        f"history with the 11 mapping decisions from 2026-05-08)."
    )

    count_result = psql(
        "SELECT COUNT(*) FROM tenant_team_alias WHERE provider = 'datadog'"
    )
    try:
        n = int(count_result or 0)
    except (TypeError, ValueError):
        n = 0
    assert n >= _MIN_ALIAS_COUNT, (
        f"Webmotors alias count dropped to {n}, floor {_MIN_ALIAS_COUNT}. "
        f"An operator may have removed too many aliases."
    )


@pytest.mark.parametrize("squad", _TOP_5_DD_BACKED_SQUADS)
def test_webmotors_top5_squad_has_dd_services(psql, squad):
    """Each of the 5 squads with the largest DD footprint must keep
    at least one tracked service. Catches: an alias was deleted by
    mistake, or a Tier 3 override moved a critical squad's services."""
    count = psql(
        f"""
        SELECT COUNT(*)
        FROM service_squad_ownership
        WHERE provider = 'datadog'
          AND COALESCE(override_squad_key, inferred_squad_key) = '{squad}'
        """
    )
    try:
        n = int(count or 0)
    except (TypeError, ValueError):
        n = 0
    assert n >= 1, (
        f"Squad {squad!r} has zero DD-tracked services in Webmotors. "
        f"On 2026-05-08 it had 25+ (top-5 by service count). "
        f"Investigate: alias for the corresponding vendor team may have "
        f"been removed or rewritten."
    )


def test_webmotors_alias_inference_actually_resolves_services(psql):
    """At least 50% of services should be tagged with confidence='alias'
    (resolved via the alias map). If everything is 'tag' or 'none', the
    inference logic stopped consulting aliases — likely a regression in
    `ownership_inference.sync_tier1_inference`'s alias-loading code."""
    result = psql(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE inferred_confidence = 'alias') AS aliased
        FROM service_squad_ownership
        WHERE provider = 'datadog'
        """
    )
    parts = (result or "0|0").split("|")
    total = int(parts[0]) if parts[0] else 0
    aliased = int(parts[1]) if len(parts) > 1 and parts[1] else 0

    assert total > 0, "No DD ownership rows; upstream test should catch."
    pct = aliased / total
    assert pct >= 0.50, (
        f"Only {aliased}/{total} ({pct:.1%}) services have "
        f"inferred_confidence='alias'. On 2026-05-08 it was 91%. A drop "
        f"below 50% suggests `sync_tier1_inference` stopped consulting "
        f"the alias map (regression in `team_alias_service.load_alias_map`?)."
    )
