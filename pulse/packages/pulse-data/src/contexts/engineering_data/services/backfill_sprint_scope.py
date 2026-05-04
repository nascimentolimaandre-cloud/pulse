"""INC-006 — Sprint scope creep backfill service.

Recomputes `committed_items`, `added_items`, `removed_items` for sprints
based on the now-populated `eng_issues.sprint_transitions` data
(populated by `extract_sprint_transitions_inline` in the sync worker).

Idempotent: re-running on the same scope is safe — overwrites the same
values. Recomputes both `added_items` AND `committed_items` so legacy
rows (where committed was based on current membership) get aligned with
the new "joined within grace window" definition.

Scopes:
  - 'all'       — every sprint with started_at populated
  - 'closed'    — only sprints with status='closed' (faster, historical
                  sprints that won't change again)
  - 'last-90d'  — sprints whose started_at is in the last 90 days

READ-ONLY on external systems — operates entirely on PULSE DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text

from src.contexts.engineering_data.services.calculate_sprint_scope import (
    DEFAULT_PLANNING_GRACE_DAYS,
    calculate_sprint_scope,
)
from src.database import get_session

logger = logging.getLogger(__name__)

Scope = Literal["all", "closed", "last-90d"]


@dataclass
class SprintScopeBackfillResult:
    scope: Scope
    planning_grace_days: int
    dry_run: bool
    sprints_scanned: int = 0
    sprints_updated: int = 0
    sprints_unchanged: int = 0
    sprints_skipped: int = 0
    duration_sec: float = 0.0
    sample_diffs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_FETCH_SPRINTS_SQL = """
SELECT id, external_id, name, started_at, completed_at, status,
       committed_items, added_items, removed_items
FROM eng_sprints
WHERE tenant_id = :tenant_id
  AND started_at IS NOT NULL
  {scope_filter}
ORDER BY started_at DESC
"""


_FETCH_TOUCHING_ISSUES_SQL = """
SELECT id, external_id, sprint_transitions
FROM eng_issues
WHERE tenant_id = :tenant_id
  AND sprint_transitions @> CAST(:sprint_filter AS jsonb)
"""


_UPDATE_SPRINT_SQL = """
UPDATE eng_sprints
SET committed_items = :committed_items,
    added_items     = :added_items,
    removed_items   = :removed_items,
    updated_at      = now()
WHERE tenant_id = :tenant_id
  AND id = :sprint_id
"""


def _build_scope_filter(scope: Scope) -> str:
    if scope == "closed":
        return "AND status = 'closed'"
    if scope == "last-90d":
        return "AND started_at >= (now() - INTERVAL '90 days')"
    # scope == "all"
    return ""


async def run_backfill(
    tenant_id: UUID,
    scope: Scope = "all",
    *,
    planning_grace_days: int = DEFAULT_PLANNING_GRACE_DAYS,
    dry_run: bool = False,
    max_sprints: int | None = None,
) -> SprintScopeBackfillResult:
    """Recompute sprint scope counts from the issue sprint_transitions log.

    Args:
        tenant_id: Tenant UUID (RLS).
        scope: Which sprints to recompute.
        planning_grace_days: Tolerance window for "committed" classification.
        dry_run: Compute + sample without writing.
        max_sprints: Cap processed sprints (smoke testing).

    Returns:
        SprintScopeBackfillResult with counts + sample diffs.
    """
    started = datetime.now(timezone.utc)
    result = SprintScopeBackfillResult(
        scope=scope,
        planning_grace_days=planning_grace_days,
        dry_run=dry_run,
    )

    scope_filter = _build_scope_filter(scope)
    fetch_sql = _FETCH_SPRINTS_SQL.format(scope_filter=scope_filter)

    logger.warning(
        "[backfill INC-006] start tenant=%s scope=%s grace_days=%d dry_run=%s",
        tenant_id, scope, planning_grace_days, dry_run,
    )

    async with get_session(tenant_id) as session:
        sprint_rows = await session.execute(
            text(fetch_sql), {"tenant_id": str(tenant_id)},
        )
        sprints = list(sprint_rows.mappings().all())

    result.sprints_scanned = len(sprints)
    if max_sprints is not None:
        sprints = sprints[:max_sprints]

    logger.info("[backfill INC-006] sprints_to_process=%d", len(sprints))

    samples_collected = 0
    SAMPLE_CAP = 10

    for sprint in sprints:
        sprint_external_id = sprint["external_id"]
        sprint_db_id = sprint["id"]

        # Fetch all issues whose changelog touched this sprint. The
        # `@>` containment query uses the GIN index from migration 015.
        async with get_session(tenant_id) as session:
            issue_rows = await session.execute(
                text(_FETCH_TOUCHING_ISSUES_SQL),
                {
                    "tenant_id": str(tenant_id),
                    "sprint_filter": f'[{{"sprint_id":"{sprint_external_id}"}}]',
                },
            )
            issues = [dict(r) for r in issue_rows.mappings().all()]

        if not issues:
            # Sprint never appears in any changelog. Could be:
            #   1. Pre-INC-006 sprint — never had transitions populated
            #   2. Sprint actually empty
            # Either way, skip — don't zero out legacy committed counts.
            result.sprints_skipped += 1
            continue

        scope_result = calculate_sprint_scope(
            sprint_id=sprint_external_id,
            sprint_started_at=sprint["started_at"],
            sprint_ended_at=sprint["completed_at"],
            issues=issues,
            planning_grace_days=planning_grace_days,
        )

        # Only update when something actually changed.
        unchanged = (
            scope_result.committed_items == (sprint["committed_items"] or 0)
            and scope_result.added_items == (sprint["added_items"] or 0)
            and scope_result.removed_items == (sprint["removed_items"] or 0)
        )
        if unchanged:
            result.sprints_unchanged += 1
            continue

        if samples_collected < SAMPLE_CAP:
            result.sample_diffs.append({
                "external_id": sprint_external_id,
                "name": sprint["name"],
                "before": {
                    "committed": sprint["committed_items"] or 0,
                    "added": sprint["added_items"] or 0,
                    "removed": sprint["removed_items"] or 0,
                },
                "after": {
                    "committed": scope_result.committed_items,
                    "added": scope_result.added_items,
                    "removed": scope_result.removed_items,
                },
                "issues_considered": scope_result.issues_considered,
            })
            samples_collected += 1

        if not dry_run:
            try:
                async with get_session(tenant_id) as session:
                    await session.execute(
                        text(_UPDATE_SPRINT_SQL),
                        {
                            "tenant_id": str(tenant_id),
                            "sprint_id": sprint_db_id,
                            "committed_items": scope_result.committed_items,
                            "added_items": scope_result.added_items,
                            "removed_items": scope_result.removed_items,
                        },
                    )
                    await session.commit()
                result.sprints_updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "[backfill INC-006] update failed sprint=%s",
                    sprint_external_id,
                )
                result.errors.append(f"{sprint_external_id}: {exc}")
        else:
            result.sprints_updated += 1

    result.duration_sec = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
    logger.warning(
        "[backfill INC-006] done scanned=%d updated=%d unchanged=%d skipped=%d "
        "errors=%d duration=%.2fs",
        result.sprints_scanned, result.sprints_updated,
        result.sprints_unchanged, result.sprints_skipped,
        len(result.errors), result.duration_sec,
    )
    return result
