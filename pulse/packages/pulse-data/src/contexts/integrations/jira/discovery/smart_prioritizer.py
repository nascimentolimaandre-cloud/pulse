"""SmartPrioritizer — scores Jira projects by PR reference frequency.

Scans eng_pull_requests for Jira issue key patterns (e.g., BACK-123) in
title, _head_ref, and _base_ref. Aggregates unique-PR-count per project
prefix and writes results to jira_project_catalog.pr_reference_count.

In ``smart`` mode, auto-activates discovered projects that meet the
minimum PR reference threshold.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.contexts.engineering_data.models import EngPullRequest
from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

logger = logging.getLogger(__name__)

# Regex to extract Jira issue keys: 2+ uppercase letters, optional digits, dash, digits.
_JIRA_KEY_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")


def _extract_project_prefixes(text: str) -> set[str]:
    """Extract unique Jira project prefixes from text.

    Example: "feat(BACK-123): fix DESC-42 bug" -> {"BACK", "DESC"}
    """
    if not text:
        return set()
    keys = _JIRA_KEY_RE.findall(text)
    return {k.split("-")[0] for k in keys}


class SmartPrioritizer:
    """Scores and auto-activates Jira projects based on PR references."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DiscoveryRepository(session)

    async def score_projects(self, tenant_id: UUID) -> dict[str, int]:
        """Scan PRs and count unique-PR references per Jira project prefix.

        Looks back ``smart_pr_scan_days`` from tenant config (default 90).
        Writes results to catalog via repository.upsert_project.

        Returns: dict mapping project_key -> pr_reference_count.
        """
        config = await self._repo.get_tenant_config(tenant_id)
        scan_days = config.get("smart_pr_scan_days", 90) if config else 90

        since = datetime.now(timezone.utc) - timedelta(days=scan_days)

        # Fetch PR title and branch refs from the lookback window.
        result = await self._session.execute(
            select(
                EngPullRequest.external_id,
                EngPullRequest.title,
            ).where(
                and_(
                    EngPullRequest.tenant_id == tenant_id,
                    EngPullRequest.created_at >= since,
                )
            )
        )
        rows = result.all()

        # Aggregate: per project prefix, count unique PRs referencing it.
        prefix_prs: dict[str, set[str]] = defaultdict(set)
        for external_id, title in rows:
            prefixes: set[str] = set()
            prefixes.update(_extract_project_prefixes(title or ""))
            # Dedupe per PR: each PR counts once per prefix even if multiple keys
            for prefix in prefixes:
                prefix_prs[prefix].add(str(external_id))

        scores: dict[str, int] = {
            prefix: len(pr_ids) for prefix, pr_ids in prefix_prs.items()
        }

        # Write scores to catalog
        for prefix, count in scores.items():
            await self._repo.upsert_project(
                tenant_id, prefix, pr_reference_count=count,
            )

        logger.info(
            "Scored %d project prefixes from %d PRs (lookback=%d days) for tenant %s",
            len(scores), len(rows), scan_days, tenant_id,
        )
        return scores

    async def auto_activate(self, tenant_id: UUID) -> int:
        """In smart mode, flip discovered -> active for projects meeting threshold.

        Returns count of newly activated projects.
        """
        config = await self._repo.get_tenant_config(tenant_id)
        if not config or config["mode"] != "smart":
            logger.debug(
                "auto_activate skipped: mode is not smart for tenant %s", tenant_id,
            )
            return 0

        threshold = config.get("smart_min_pr_references", 3)

        # Find discovered projects meeting threshold
        candidates, _ = await self._repo.list_projects(
            tenant_id, status="discovered", limit=10000, offset=0,
        )

        activated = 0
        for proj in candidates:
            pr_count = proj.get("pr_reference_count") or 0
            # Skip PII-flagged projects — they require manual admin approval
            proj_metadata = proj.get("metadata") or {}
            if proj_metadata.get("pii_flag"):
                logger.debug(
                    "Skipping PII-flagged project %s for smart auto-activate",
                    proj["project_key"],
                )
                continue
            if pr_count >= threshold:
                await self._repo.update_project_status(
                    tenant_id,
                    proj["project_key"],
                    status="active",
                    source="smart_pr_scan",
                    actor="smart_auto",
                    reason=f"PR reference count {pr_count} >= threshold {threshold}",
                )
                activated += 1

        if activated:
            logger.info(
                "Smart auto-activated %d projects for tenant %s (threshold=%d)",
                activated, tenant_id, threshold,
            )
        return activated
