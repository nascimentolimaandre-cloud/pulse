"""FDD-KB-013 — Backfill `eng_issues.description` with plain-text content
from Jira.

V2 rewrite (2026-04-17): switched from per-issue `GET /issue/{key}` fetches
to **bulk JQL search** via `POST /rest/api/3/search/jql`. Each request now
returns up to 100 issues instead of 1 — empirical ~100× speedup. V1 was
pacing at ~113 issues/min (55h for Webmotors' 374k issues); V2 targets
~10k issues/min.

Architecture
------------
1. Load the active + discovered projects from `jira_project_catalog`.
2. For each project, issue a scoped JQL query (e.g.
   `project = "OKM" AND description is EMPTY`) and paginate with
   `nextPageToken` until the project is exhausted.
3. For each returned issue, extract the plain-text description using the
   connector's existing ADF parser (`_extract_description_text`) and queue
   an UPSERT. Flush every DB_UPDATE_CHUNK rows.
4. Jira filters *at the source* whenever possible — e.g. `scope='stale'`
   becomes `description is EMPTY` so we never pull rows we'd discard.

Scopes
------
- `stale` — Jira: `description is EMPTY` (server-side filter, cheapest).
- `last-90d`  — Jira: `updated >= -90d`.
- `last-180d` — Jira: `updated >= -180d`.
- `in_progress` — Jira: `statusCategory = "In Progress"` (priority scope —
  populates issues visible in the Flow Health drawer first).
- `all` — no filter (expensive, cap with max_issues).

READ-ONLY Jira contract — this service only issues POST to /search/jql
(read op) and never writes, transitions, or comments on any issue.

Anti-surveillance
-----------------
- We only request `description` from Jira. Even though the response
  envelope exposes assignee/reporter by default, we ignore everything
  except `id`, `key`, and `fields.description`.
- We never log description bodies (may contain PII).
- JQL never filters by a specific assignee.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, text, update

from src.connectors.jira_connector import (
    DESCRIPTION_MAX_CHARS,
    JiraConnector,
)
from src.contexts.engineering_data.models import EngIssue
from src.database import get_session

logger = logging.getLogger(__name__)

# Jira Cloud `POST /search/jql` caps `maxResults` at 100.
JIRA_PAGE_SIZE = 100

# Pacing between pages. At 100 issues/page, a 0.2s pause keeps us well
# below Jira Cloud's ~10 req/s soft limit (effective ~5 req/s = 500 iss/s).
# The ResilientHTTPClient still handles 429 via Retry-After transparently.
JIRA_PAGE_PAUSE_SEC = 0.2

# DB flush size — larger = fewer commits but longer locks. 200 is a sweet
# spot at 100-issue pages (every 2 API pages).
DB_UPDATE_CHUNK = 100

Scope = Literal["stale", "last-90d", "last-180d", "in_progress", "all"]


@dataclass
class BackfillResult:
    scope: Scope
    dry_run: bool
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)
    duration_sec: float = 0.0
    projects_scanned: int = 0
    pages_fetched: int = 0


# ---------------------------------------------------------------------------
# Project catalog lookup
# ---------------------------------------------------------------------------

async def _load_catalog_projects(tenant_id: UUID) -> list[str]:
    """Return project keys marked `active` or `discovered` for the tenant.

    We include `discovered` (not only `active`) so newly-surfaced projects
    that haven't been promoted yet still get their descriptions captured.
    Archived/rejected projects are excluded.

    Uses a raw SQL SELECT against `jira_project_catalog` — avoids coupling
    this service to the discovery context's ORM / repository layer.
    """
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT project_key
                  FROM jira_project_catalog
                 WHERE tenant_id = :tid
                   AND status IN ('active', 'discovered')
                 ORDER BY project_key
                """
            ),
            {"tid": tenant_id},
        )
        keys = [row[0] for row in result.all() if row[0]]
    return keys


# ---------------------------------------------------------------------------
# JQL builder
# ---------------------------------------------------------------------------

def _build_jql(project_key: str, scope: Scope) -> str:
    """Build a scoped JQL query for a single project.

    Per-project querying (vs. `project IN (a,b,c,...)`) gives us finer-grain
    cursoring and keeps each request small enough to avoid Jira's 1000-char
    JQL length cap when project lists are long (69 projects at Webmotors).
    """
    # Project keys may contain only [A-Z0-9_], but some are reserved JQL
    # words (e.g. "DESC"). Always quote.
    base = f'project = "{project_key}"'

    if scope == "stale":
        # Server-side filter for missing descriptions — the big win.
        return f'{base} AND description is EMPTY ORDER BY updated DESC'
    if scope == "last-90d":
        return f'{base} AND updated >= -90d ORDER BY updated DESC'
    if scope == "last-180d":
        return f'{base} AND updated >= -180d ORDER BY updated DESC'
    if scope == "in_progress":
        # Priority scope — populates issues surfaced in Flow Health drawer.
        # `statusCategory` is Jira's stable canonical grouping (To Do /
        # In Progress / Done), resilient to tenant-specific status name
        # variations.
        return (
            f'{base} AND statusCategory = "In Progress" '
            f'ORDER BY updated DESC'
        )
    # scope == "all"
    return f'{base} ORDER BY updated DESC'


# ---------------------------------------------------------------------------
# DB flush
# ---------------------------------------------------------------------------

async def _flush_updates(
    tenant_id: UUID,
    updates: list[tuple[str, str | None]],
) -> None:
    """Apply a batch of `(issue_key, description)` updates.

    Match is by (tenant_id, issue_key) — issue_key is indexed and unique
    per tenant for Jira-sourced rows.
    """
    if not updates:
        return
    async with get_session(tenant_id) as session:
        now = datetime.now(timezone.utc)
        for issue_key, new_desc in updates:
            await session.execute(
                update(EngIssue)
                .where(
                    EngIssue.tenant_id == tenant_id,
                    EngIssue.source == "jira",
                    EngIssue.issue_key == issue_key,
                )
                .values(description=new_desc, updated_at=now)
            )
        await session.commit()


# ---------------------------------------------------------------------------
# Existing-description lookup (for idempotency)
# ---------------------------------------------------------------------------

async def _load_existing_descriptions(
    tenant_id: UUID,
    issue_keys: list[str],
) -> dict[str, str | None]:
    """Fetch current `description` for the given keys.

    Used to detect no-op writes (idempotency counter) and skip unchanged
    rows from the DB flush batch. Returns `{key: description_or_None}`.
    Keys absent from the result (e.g. issue synced to Jira but not yet to
    PULSE) are treated as "unknown"; we still queue the UPDATE — it becomes
    a no-op if 0 rows match.
    """
    if not issue_keys:
        return {}
    async with get_session(tenant_id) as session:
        stmt = select(EngIssue.issue_key, EngIssue.description).where(
            EngIssue.tenant_id == tenant_id,
            EngIssue.source == "jira",
            EngIssue.issue_key.in_(issue_keys),
        )
        result = await session.execute(stmt)
        return {key: desc for key, desc in result.all()}


# ---------------------------------------------------------------------------
# Public entry point — signature preserved for backward compat with routes.py
# ---------------------------------------------------------------------------

async def run_backfill(
    tenant_id: UUID,
    scope: Scope = "stale",
    dry_run: bool = False,
    max_issues: int | None = None,
) -> BackfillResult:
    """Populate `eng_issues.description` via bulk JQL search.

    Signature preserved — the admin route in `routes.py` continues to call
    this unchanged.
    """
    started = datetime.now(timezone.utc)
    result = BackfillResult(scope=scope, dry_run=dry_run)

    # Connector gives us the authenticated HTTP client + ADF parser.
    try:
        connector = JiraConnector()
    except ValueError as exc:
        result.errors.append(f"Jira not configured: {exc}")
        return result

    try:
        project_keys = await _load_catalog_projects(tenant_id)
        if not project_keys:
            result.errors.append(
                "No projects in jira_project_catalog (status in active/discovered). "
                "Run `/jira/discovery/scan` first."
            )
            result.duration_sec = round(
                (datetime.now(timezone.utc) - started).total_seconds(), 2
            )
            return result

        result.projects_scanned = len(project_keys)
        logger.info(
            "[backfill FDD-KB-013 V2] tenant=%s scope=%s projects=%d dry_run=%s max=%s",
            tenant_id, scope, len(project_keys), dry_run, max_issues,
        )

        pending: list[tuple[str, str | None]] = []
        reached_cap = False

        for proj_idx, project_key in enumerate(project_keys, start=1):
            if reached_cap:
                break

            jql = _build_jql(project_key, scope)
            next_page_token: str | None = None
            page_num = 0

            while True:
                body: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": JIRA_PAGE_SIZE,
                    # Minimal payload — we only need description.
                    "fields": ["description"],
                }
                if next_page_token:
                    body["nextPageToken"] = next_page_token

                try:
                    data = await connector._client.post(  # noqa: SLF001 — intentional reuse
                        "/rest/api/3/search/jql",
                        json_body=body,
                    )
                except Exception as exc:  # noqa: BLE001
                    msg = (
                        f"search failed for project={project_key} "
                        f"page={page_num}: {exc}"
                    )
                    logger.warning(msg)
                    result.errors.append(msg)
                    # Don't abort the whole run — move on to next project.
                    break

                page_num += 1
                result.pages_fetched += 1
                issues = data.get("issues") or []
                if not issues and not next_page_token:
                    # Empty project for this scope.
                    break

                # --- Process this page ----------------------------------
                # Extract descriptions first.
                keys_this_page: list[str] = []
                new_descs: dict[str, str | None] = {}
                for issue in issues:
                    key = issue.get("key")
                    if not key:
                        continue
                    fields = issue.get("fields") or {}
                    raw_desc = fields.get("description")
                    new_desc = JiraConnector._extract_description_text(raw_desc)
                    # Strip NUL bytes (\x00) — Postgres rejects them in TEXT
                    # columns (CharacterNotInRepertoireError). Some Jira
                    # descriptions contain stray NULs from copy-pasted binary
                    # content; drop them rather than abort the page.
                    if new_desc and "\x00" in new_desc:
                        new_desc = new_desc.replace("\x00", "")
                        if not new_desc:
                            new_desc = None
                    keys_this_page.append(key)
                    new_descs[key] = new_desc

                # Pull current DB values in a single SELECT — idempotency.
                existing = await _load_existing_descriptions(
                    tenant_id, keys_this_page
                )

                for key in keys_this_page:
                    result.processed += 1
                    new_desc = new_descs[key]
                    old_desc = existing.get(key)

                    if (new_desc or None) == (old_desc or None):
                        result.unchanged += 1
                    else:
                        if len(result.sample) < 3 and new_desc:
                            result.sample.append({
                                "issue_key": key,
                                "had_description": old_desc is not None,
                                "new_length": len(new_desc),
                                "preview": new_desc[:120] + (
                                    "..." if len(new_desc) > 120 else ""
                                ),
                            })
                        if not dry_run:
                            pending.append((key, new_desc))
                        result.updated += 1

                    if max_issues is not None and result.processed >= max_issues:
                        reached_cap = True
                        break

                # Flush DB batch if threshold hit.
                if len(pending) >= DB_UPDATE_CHUNK:
                    await _flush_updates(tenant_id, pending)
                    pending = []

                if reached_cap:
                    break

                # Advance cursor; exit when Jira says no more pages.
                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break

                # Light pacing — keep us comfortably under rate limit.
                await asyncio.sleep(JIRA_PAGE_PAUSE_SEC)

            logger.info(
                "[backfill FDD-KB-013 V2] project=%s (%d/%d) pages=%d "
                "processed=%d updated=%d unchanged=%d",
                project_key, proj_idx, len(project_keys), page_num,
                result.processed, result.updated, result.unchanged,
            )

        # Final flush for the tail.
        if not dry_run and pending:
            await _flush_updates(tenant_id, pending)

    finally:
        await connector.close()

    # Guardrail: underlying parser caps at DESCRIPTION_MAX_CHARS. Keep the
    # reference here so linters don't flag the import.
    _ = DESCRIPTION_MAX_CHARS

    result.duration_sec = round(
        (datetime.now(timezone.utc) - started).total_seconds(), 2,
    )
    logger.info(
        "[backfill FDD-KB-013 V2] done scope=%s projects=%d pages=%d "
        "processed=%d updated=%d unchanged=%d skipped=%d errors=%d duration=%.1fs",
        scope, result.projects_scanned, result.pages_fetched,
        result.processed, result.updated, result.unchanged,
        result.skipped, len(result.errors), result.duration_sec,
    )
    return result
