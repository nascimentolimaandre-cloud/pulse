"""FDD-OBS-001 PR 4a — Tier 2 ownership inference (repo-intersection).

ADR-022 Tier-2: when a service has no `team:` tag (or the alias didn't
resolve), infer ownership by intersecting the service's `repo_url`
against `eng_pull_requests.repo` — the squad whose PRs most-frequently
touch that repo is the owner.

Algorithm (architect-validated):
  For each service with `inferred_squad_key IS NULL`:
    if `repo_url` is set:
      normalize to canonical `repo_name` (lowercase, strip .git, strip path)
      query: top squad among PRs touching this repo in the last 90d,
             where squad is extracted from `pr.title` via the same
             ``\\m([A-Z]+)-\\d+`` regex used by ``test_webmotors_fontes_coverage.py``
      gates:
        - min_pr_count: 5 (filter experimental repos)
        - dominance_ratio: 60% (top squad must own > 60% of qualifying PRs)
        - tie window: top 2 within 10% → ambiguous, skip
        - squad must be in qualified_squads (drop typos)
      if all gates pass:
        upsert with `inferred_squad_key=<top>`, `inferred_confidence='heuristic'`

NEVER overwrites:
  - `override_squad_key` (Tier 3 admin override)
  - existing rows where `inferred_confidence` is already 'tag' or 'alias'
    (Tier 1 wins over Tier 2)

Anti-surveillance:
  Reads only `pr.title` and `pr.repo` — no author / reviewer fields.
  The regex extracts the Jira project key (squad), which is squad-level
  metadata, not individual.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import text

from src.contexts.observability.services.squad_directory import SquadDirectory
from src.database import get_session

logger = logging.getLogger(__name__)


# Tunables (architect-validated). Documented as public so tests can
# import + assert against them — values changing in main without test
# update would silently shift every Webmotors squad's coverage.
MIN_PR_COUNT: int = 5
DOMINANCE_RATIO: float = 0.60
TIE_WINDOW: float = 0.10
LOOKBACK_DAYS: int = 90


@dataclass(frozen=True)
class Tier2Result:
    """Outcome counters returned to the orchestrator (rollup_service)."""

    candidates_seen: int            # services with inferred_squad_key NULL + repo
    inferred: int                    # rows updated to confidence='heuristic'
    skipped_no_repo: int             # candidate had no repo_url
    skipped_low_pr_count: int        # repo had < MIN_PR_COUNT PRs in 90d
    skipped_no_dominant_squad: int   # top squad < DOMINANCE_RATIO
    skipped_ambiguous: int           # top 2 within TIE_WINDOW
    skipped_unqualified_squad: int   # top squad not in tenant's qualified set


# ---------------------------------------------------------------------------
# Repo URL normalization
# ---------------------------------------------------------------------------


def normalize_repo(url: str | None) -> str | None:
    """Reduce a vendor-supplied repo URL to the `org/name` form used in
    `eng_pull_requests.repo` (e.g. `webmotors-private/checkout`).

    Tolerates HTTPS (`https://github.com/org/name[.git]`),
    SSH (`git@github.com:org/name.git`), and plain `org/name`. Returns
    None if it can't extract org+name. Lowercases for stable matching.
    """
    if not url:
        return None
    url = url.strip()
    if not url:
        return None

    # Strip trailing slashes / .git
    if url.endswith("/"):
        url = url[:-1]
    if url.endswith(".git"):
        url = url[:-4]

    # SSH form: `git@github.com:org/name`
    if url.startswith("git@"):
        try:
            _, after_colon = url.split(":", 1)
            parts = after_colon.split("/")
            if len(parts) >= 2:
                return f"{parts[-2]}/{parts[-1]}".lower()
        except ValueError:
            return None
        return None

    # HTTPS form
    if url.startswith(("http://", "https://")):
        try:
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            parts = path.split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}".lower()
        except ValueError:
            return None
        return None

    # Plain `org/name`
    parts = url.split("/")
    if len(parts) == 2 and parts[0] and parts[1]:
        return f"{parts[0]}/{parts[1]}".lower()

    return None


# ---------------------------------------------------------------------------
# Tier 2 sync
# ---------------------------------------------------------------------------


# SQL extracts squad keys from PR titles using the same regex as the
# squad-qualification service. Counts PRs per (repo, squad) over the
# lookback window. Repo names matched case-insensitively.
_TIER2_SQL = """
WITH pr_squads AS (
    SELECT
        lower(pr.repo) AS repo,
        UPPER((regexp_match(pr.title, '\\m([A-Za-z][A-Za-z0-9]+)-\\d+'))[1]) AS squad
    FROM eng_pull_requests pr
    WHERE pr.tenant_id = :tenant_id
      AND pr.created_at >= NOW() - (:lookback_days || ' days')::interval
      AND pr.title IS NOT NULL
      AND pr.repo IS NOT NULL
)
SELECT
    repo,
    squad,
    COUNT(*) AS pr_count
FROM pr_squads
WHERE squad IS NOT NULL
GROUP BY repo, squad
ORDER BY repo, pr_count DESC
"""


async def sync_tier2_inference(
    tenant_id: UUID,
    provider_id: str,
) -> Tier2Result:
    """Run Tier-2 repo-intersection inference for every candidate row in
    `service_squad_ownership`. Returns counters; never raises (workers
    must keep cycling)."""

    candidates_seen = 0
    inferred = 0
    skipped_no_repo = 0
    skipped_low_pr_count = 0
    skipped_no_dominant_squad = 0
    skipped_ambiguous = 0
    skipped_unqualified_squad = 0

    qualified_squads = await SquadDirectory.list_qualified_squads(tenant_id)

    async with get_session(tenant_id) as session:
        # 1. Build the {repo: [(squad, count), ...]} map for this tenant.
        # One query covers every repo; far cheaper than per-service queries.
        result = await session.execute(
            text(_TIER2_SQL),
            {"tenant_id": str(tenant_id), "lookback_days": str(LOOKBACK_DAYS)},
        )
        repo_squads: dict[str, list[tuple[str, int]]] = {}
        for row in result.all():
            if not row.squad:
                continue
            repo_squads.setdefault(row.repo, []).append((row.squad, row.pr_count))

        # 2. Find candidates: services with NULL inferred_squad_key.
        result = await session.execute(
            text(
                """
                SELECT service_external_id, service_name, repo_url
                FROM service_squad_ownership
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND inferred_squad_key IS NULL
                """
            ),
            {"tenant_id": str(tenant_id), "provider": provider_id},
        )
        candidates = result.all()
        candidates_seen = len(candidates)

        # 3. For each candidate, evaluate the gates.
        for cand in candidates:
            repo_norm = normalize_repo(cand.repo_url)
            if repo_norm is None:
                skipped_no_repo += 1
                continue

            squads = repo_squads.get(repo_norm, [])
            total_prs = sum(c for _, c in squads)
            if total_prs < MIN_PR_COUNT:
                skipped_low_pr_count += 1
                continue

            # squads is already ORDER BY pr_count DESC from the SQL.
            top_squad, top_count = squads[0]
            top_ratio = top_count / total_prs

            if top_ratio < DOMINANCE_RATIO:
                skipped_no_dominant_squad += 1
                continue

            # Tie check: only when there's a runner-up.
            if len(squads) >= 2:
                _, second_count = squads[1]
                second_ratio = second_count / total_prs
                if (top_ratio - second_ratio) < TIE_WINDOW:
                    skipped_ambiguous += 1
                    continue

            if top_squad not in qualified_squads:
                skipped_unqualified_squad += 1
                continue

            # All gates passed — upsert as 'heuristic'.
            await session.execute(
                text(
                    """
                    UPDATE service_squad_ownership
                    SET inferred_squad_key  = :squad_key,
                        inferred_confidence = 'heuristic',
                        last_inference_at   = NOW(),
                        updated_at          = NOW()
                    WHERE tenant_id = :tenant_id
                      AND provider = :provider
                      AND service_external_id = :external_id
                      AND inferred_squad_key IS NULL
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "provider": provider_id,
                    "external_id": cand.service_external_id,
                    "squad_key": top_squad,
                },
            )
            inferred += 1

        await session.commit()

    logger.info(
        "[obs-tier2] tenant=%s provider=%s candidates=%d inferred=%d "
        "no_repo=%d low_pr=%d no_dominant=%d ambiguous=%d unqualified=%d",
        tenant_id, provider_id, candidates_seen, inferred,
        skipped_no_repo, skipped_low_pr_count, skipped_no_dominant_squad,
        skipped_ambiguous, skipped_unqualified_squad,
    )
    return Tier2Result(
        candidates_seen=candidates_seen,
        inferred=inferred,
        skipped_no_repo=skipped_no_repo,
        skipped_low_pr_count=skipped_low_pr_count,
        skipped_no_dominant_squad=skipped_no_dominant_squad,
        skipped_ambiguous=skipped_ambiguous,
        skipped_unqualified_squad=skipped_unqualified_squad,
    )
