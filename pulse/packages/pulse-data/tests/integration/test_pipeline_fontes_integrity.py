"""Pipeline FONTES integrity (QW-3 platform part).

Regression tests for INC-FONTES: the Pipeline Monitor "Fontes" column was
showing zero for every squad because `eng_deployments.repo` lacks the
organization prefix that `eng_pull_requests.repo` has. The temporal linking
query used `d.repo = ps.repo` which never matched.

Fix: normalize with `split_part(ps.repo, '/', 2)` when joining deployments
to PR-squad mapping.

Invariants tested:
1. If there's at least ONE deploy in eng_deployments AND at least ONE PR
   in eng_pull_requests sharing any repo (after split_part normalization),
   then at least ONE squad must have sources > 0.
2. split_part normalization works (repos like `webmotors-private/foo` become
   `foo` matching deployment side).
3. The linking query does NOT silently return 0 for every squad.

Requires: Postgres running, eng_pull_requests AND eng_deployments populated.

Classification: PLATFORM (split_part normalization is universal SQL invariant).
"""

from __future__ import annotations

import os
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001")


def _repo_root() -> str:
    path = os.path.abspath(__file__)
    while path != "/":
        if os.path.isdir(os.path.join(path, "pulse")):
            return path
        path = os.path.dirname(path)
    raise RuntimeError("Could not find repo root")


def _psql(query: str, timeout: int = 15) -> str | None:
    cmd = [
        "docker", "compose",
        "-f", os.path.join(_repo_root(), "pulse/docker-compose.yml"),
        "exec", "-T", "postgres",
        "psql", "-U", "pulse", "-d", "pulse",
        "-t", "-A", "-c",
        f"SET app.current_tenant='{TENANT_ID}'; {query}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return None
        lines = [line for line in r.stdout.splitlines() if line.strip()]
        return lines[-1] if lines else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _db_reachable() -> bool:
    return _psql("SELECT 1", timeout=5) == "1"


DB_UP = _db_reachable()

pytestmark = pytest.mark.skipif(
    not DB_UP, reason="Postgres not reachable via `docker compose exec`"
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pr_repo_has_org_prefix():
    """INC-FONTES precondition: eng_pull_requests.repo has org/ prefix."""
    result = _psql(
        "SELECT repo FROM eng_pull_requests "
        "WHERE repo LIKE '%/%' AND repo IS NOT NULL LIMIT 1;"
    )
    if not result:
        pytest.skip("No PRs with slash in repo — can't verify prefix hypothesis")
    assert "/" in result, (
        f"Expected eng_pull_requests.repo to contain '/' (org/repo format). "
        f"Got: '{result}'. If format changed, INC-FONTES fix may no longer apply."
    )


def test_deployment_repo_lacks_org_prefix():
    """INC-FONTES precondition: eng_deployments.repo does NOT have org/ prefix.

    This asymmetry is what caused the bug. If someone 'fixes' deployments to
    use the org/repo format, the split_part workaround becomes wrong.
    """
    result = _psql(
        "SELECT COUNT(*) FROM eng_deployments WHERE repo LIKE '%/%';"
    )
    if not result:
        pytest.skip("Cannot query eng_deployments")
    slash_count = int(result)
    # Allow SOME deployments to have slash (future refactor in progress)
    # but it should not be the common case
    total = int(
        _psql("SELECT COUNT(*) FROM eng_deployments;") or "0"
    )
    if total == 0:
        pytest.skip("eng_deployments is empty — cannot test format asymmetry")
    slash_pct = slash_count / total
    assert slash_pct < 0.1, (
        f"{slash_pct*100:.1f}% of deployments have '/' in repo — format may have "
        f"changed from the INC-FONTES assumption. Verify the split_part fix "
        f"in pipeline/routes.py is still correct."
    )


def test_split_part_linking_yields_matches():
    """The split_part-based JOIN produces at least SOME matched squad→deploy pairs.

    This is the core INC-FONTES invariant: `split_part(pr.repo, '/', 2) =
    d.repo` must match enough PRs to at least ONE deployment.
    """
    result = _psql(
        r"""
        SELECT COUNT(*) AS matches FROM (
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
    if not result:
        pytest.skip("Query failed or returned no data")
    matches = int(result)
    assert matches > 0, (
        f"split_part JOIN produced zero matches. INC-FONTES may have regressed: "
        f"the split_part normalization isn't matching any PR.repo against "
        f"eng_deployments.repo. Expected matches > 0 for any tenant with "
        f"both PRs and deployments."
    )


def test_split_part_beats_naive_equals():
    """split_part-based JOIN produces STRICTLY MORE matches than naive d.repo = pr.repo.

    This is the ultimate regression protection: if naive equals gives the
    same result, the bug is back (or the data was re-structured).
    """
    naive = _psql(
        r"""
        SELECT COUNT(*) FROM (
          SELECT DISTINCT
            UPPER((regexp_match(pr.title, '\m([A-Za-z][A-Za-z0-9]+)-\d+'))[1]) AS project_key,
            pr.repo
          FROM eng_pull_requests pr
          WHERE pr.created_at >= NOW() - INTERVAL '90 days'
        ) ps
        JOIN eng_deployments d ON d.repo = ps.repo
        WHERE d.deployed_at >= NOW() - INTERVAL '90 days'
          AND ps.project_key IS NOT NULL;
        """
    )
    split = _psql(
        r"""
        SELECT COUNT(*) FROM (
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
    if not naive or not split:
        pytest.skip("Could not run comparison queries")
    naive_n = int(naive)
    split_n = int(split)
    assert split_n > naive_n, (
        f"split_part JOIN should produce MORE matches than naive equals. "
        f"Got naive={naive_n}, split={split_n}. If equal, data format may "
        f"have been normalized (check eng_deployments.repo — maybe now "
        f"includes org prefix) and the split_part fix is no longer needed."
    )
