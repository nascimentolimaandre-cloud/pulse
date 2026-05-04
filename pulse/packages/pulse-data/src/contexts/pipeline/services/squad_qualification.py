"""FDD-PIPE-001 — Squad qualification heuristic (Python reference impl).

This module is the **canonical specification** of the qualification rule.
The actual implementation in production is the SQL CTE inside
`pipeline/routes.py:get_teams()` for performance reasons (single round-trip
vs. row-by-row Python). This module exists so the rule has:

  1. A pure-Python implementation that's unit-testable in isolation
     (no DB needed, no fixtures).
  2. A single source of truth that the SQL must match. If the rule ever
     changes, **both** must be updated together — the test suite enforces
     parity by exercising boundary cases that the SQL must also satisfy.

Read the docstring of `qualify_squad()` for the full rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Default config — must match the JSONB default in migration 014
# ---------------------------------------------------------------------------

DEFAULT_QUALIFICATION_CONFIG = {
    "min_prs_90d_active_tier": 5,
    "include_data_only_squads": True,
    "qualification_requires_metadata": True,
    "qualification_requires_any_activity": True,
}


Tier = Literal["active", "marginal", "dormant"]
Override = Literal["qualified", "excluded"]
QualificationSource = Literal["auto", "override"]


@dataclass(frozen=True)
class SquadCandidate:
    """Inputs needed to classify a single squad."""

    project_key: str
    name: str | None
    issue_count: int
    prs_referenced_90d: int
    qualification_override: Override | None = None


@dataclass(frozen=True)
class QualificationResult:
    """Outputs of the heuristic."""

    qualified: bool
    tier: Tier
    qualification_source: QualificationSource
    has_metadata: bool
    has_activity: bool


def qualify_squad(
    candidate: SquadCandidate,
    config: dict | None = None,
) -> QualificationResult:
    """Classify a single squad. The rule:

    1. **Override wins.** If `qualification_override='qualified'` →
       `qualified=True, source='override'`. If `'excluded'` →
       `qualified=False, source='override'`. The tier is still computed
       so admin UI can show "this squad would normally be tier X".

    2. **Heuristic gate (`source='auto'`):**
       - `has_metadata = name is not None and name != ''`
         (Jira API confirmed the project exists. Filters regex noise like
         RC, CVE, REDIRECTS, RELEASE — names empty because the discovery
         worker never found a real project.)
       - `has_activity = issue_count >= 1 or prs_referenced_90d >= 1`
         (Some sign of engineering life — issues OR PRs.)
       - `qualified = has_metadata AND has_activity`

       When `qualification_requires_metadata=False`, the metadata gate
       is skipped (some tenants might not enrich). When
       `qualification_requires_any_activity=False`, the activity gate
       is skipped.

    3. **Activity tier (orthogonal — never excludes):**
       - `active`   if `prs_referenced_90d >= min_prs_90d_active_tier`
       - `marginal` if `1 <= prs_referenced_90d < min_prs_90d_active_tier`
       - `dormant`  if `prs_referenced_90d == 0 AND issue_count >= 1`
       - `marginal` (fallback) for the empty case.
    """
    cfg = config or DEFAULT_QUALIFICATION_CONFIG
    min_active = int(cfg.get("min_prs_90d_active_tier", 5))
    req_metadata = bool(cfg.get("qualification_requires_metadata", True))
    req_activity = bool(cfg.get("qualification_requires_any_activity", True))

    has_metadata = bool(candidate.name) and candidate.name.strip() != ""
    has_activity = candidate.issue_count >= 1 or candidate.prs_referenced_90d >= 1

    # Tier computation (always runs — even on excluded squads)
    if candidate.prs_referenced_90d >= min_active:
        tier: Tier = "active"
    elif candidate.prs_referenced_90d >= 1:
        tier = "marginal"
    elif candidate.issue_count >= 1:
        tier = "dormant"
    else:
        tier = "marginal"

    # Override wins.
    if candidate.qualification_override == "excluded":
        return QualificationResult(
            qualified=False,
            tier=tier,
            qualification_source="override",
            has_metadata=has_metadata,
            has_activity=has_activity,
        )
    if candidate.qualification_override == "qualified":
        return QualificationResult(
            qualified=True,
            tier=tier,
            qualification_source="override",
            has_metadata=has_metadata,
            has_activity=has_activity,
        )

    # Heuristic.
    qualified_auto = True
    if req_metadata and not has_metadata:
        qualified_auto = False
    if req_activity and not has_activity:
        qualified_auto = False

    return QualificationResult(
        qualified=qualified_auto,
        tier=tier,
        qualification_source="auto",
        has_metadata=has_metadata,
        has_activity=has_activity,
    )
