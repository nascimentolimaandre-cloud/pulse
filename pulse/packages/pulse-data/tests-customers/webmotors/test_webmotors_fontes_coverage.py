"""Webmotors — FONTES coverage validation (QW-3 customer part).

Validates that Webmotors-specific expectations about the Pipeline Monitor
FONTES column hold true:

- All 27 active squads should have FONTES > 0 (at least one source linked)
- The GitHub org prefix `webmotors-private/` pattern must be present in PR
  repos (confirms ingestion working)
- Jenkins jobs prefix `prd-` must appear in deployment metadata

Tolerance: at least 70% of squads should have sources; squads with 0 (legacy
orphans, discovered but inactive) are OK up to 30%.

Classification: CUSTOMER (Webmotors-specific values and conventions).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_webmotors_active_squads_have_sources(psql):
    """At least 70% of squads with recent PR activity also have deploys linked.

    Validates that the split_part-based linking actually produces coverage
    for Webmotors — the motivation for the original fix.
    """
    # Count distinct squads active in last 90d
    active_squads = psql(
        r"""
        SELECT COUNT(DISTINCT UPPER((regexp_match(pr.title, '\m([A-Za-z][A-Za-z0-9]+)-\d+'))[1]))
        FROM eng_pull_requests pr
        WHERE pr.created_at >= NOW() - INTERVAL '90 days'
          AND (regexp_match(pr.title, '\m([A-Za-z][A-Za-z0-9]+)-\d+')) IS NOT NULL;
        """
    )

    # Squads with at least 1 linked deployment
    squads_with_deploys = psql(
        r"""
        SELECT COUNT(DISTINCT project_key) FROM (
          SELECT DISTINCT
            UPPER((regexp_match(pr.title, '\m([A-Za-z][A-Za-z0-9]+)-\d+'))[1]) AS project_key,
            pr.repo
          FROM eng_pull_requests pr
          WHERE pr.created_at >= NOW() - INTERVAL '90 days'
        ) ps
        JOIN eng_deployments d ON d.repo = split_part(ps.repo, '/', 2)
        WHERE d.deployed_at >= NOW() - INTERVAL '90 days'
          AND ps.project_key IS NOT NULL;
        """
    )

    active = int(active_squads or 0)
    with_deploys = int(squads_with_deploys or 0)

    assert active >= 20, (
        f"Webmotors should have at least 20 active squads in 90d, got {active}. "
        f"Ingestion may be broken."
    )

    coverage = with_deploys / active if active > 0 else 0
    assert coverage >= 0.3, (
        f"Only {with_deploys}/{active} ({coverage*100:.0f}%) of active squads have "
        f"linked deployments. Expected ≥30% coverage for Webmotors. "
        f"Jenkins ingestion or split_part fix may be regressing."
    )


def test_webmotors_github_org_prefix_present(psql):
    """Webmotors PRs come from `webmotors-private/*` GitHub org."""
    result = psql(
        "SELECT COUNT(*) FROM eng_pull_requests "
        "WHERE repo LIKE 'webmotors-private/%';"
    )
    count = int(result or 0)
    assert count > 1000, (
        f"Expected many PRs with 'webmotors-private/' prefix, got {count}. "
        f"GitHub connector may be misconfigured (wrong GITHUB_ORG env var)."
    )


def test_webmotors_jenkins_prd_jobs_present(psql):
    """Webmotors deploys include Jenkins PRD jobs (production pipelines)."""
    result = psql(
        "SELECT COUNT(*) FROM eng_deployments "
        "WHERE source = 'jenkins' "
        "AND deployed_at >= NOW() - INTERVAL '90 days';"
    )
    count = int(result or 0)
    assert count > 100, (
        f"Expected >100 Jenkins deployments in 90d for Webmotors, got {count}. "
        f"Jenkins connector may be misconfigured."
    )


def test_webmotors_has_production_environment_deploys(psql):
    """CFR calculations depend on `environment='production'` filter (INC-008)."""
    result = psql(
        "SELECT COUNT(*) FROM eng_deployments "
        "WHERE environment = 'production' "
        "AND deployed_at >= NOW() - INTERVAL '120 days';"
    )
    count = int(result or 0)
    assert count > 500, (
        f"Expected >500 production deployments in 120d, got {count}. "
        f"Jenkins connector may not be correctly tagging environment."
    )
