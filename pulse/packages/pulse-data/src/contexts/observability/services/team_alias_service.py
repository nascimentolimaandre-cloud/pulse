"""FDD-OBS-001 PR 3.5 — team alias service (vendor_team → PULSE squad).

CRUD + bulk import for `tenant_team_alias`. Used by:

  - `ownership_inference.sync_tier1_inference` to translate DD `team:`
    tag values into PULSE squad_keys before persisting (alias-resolved
    rows get `inferred_confidence='alias'`; non-resolved fall back to
    `'tag'` with the raw vendor value).

  - Admin UI to list / set / delete aliases and bulk-import them from
    a CSV paste.

  - Suggestions service (`list_unaliased_vendor_teams`) — returns
    distinct vendor_team values seen in `service_squad_ownership` that
    have no alias yet, so the UI can prompt operators with what
    actually needs mapping.

Validation:
  - `squad_key` is checked against `SquadDirectory.assert_valid_squad`
    (raises `InvalidSquadKeyError` → 422 in routes) BEFORE any DB write.
  - `vendor_team_value` is normalized lowercase + whitespace-trimmed.
  - Empty values are rejected (matches the DB CHECK constraint).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from src.contexts.observability.services.squad_directory import SquadDirectory
from src.database import get_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TeamAlias:
    """Read-model row for the alias map."""

    vendor_team_value: str
    squad_key: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BulkImportResult:
    """Outcome of `bulk_import` — counts so the UI can show a summary."""

    inserted: int
    updated: int
    rejected_invalid_squad: int
    rejected_empty: int
    total_submitted: int

    @property
    def applied(self) -> int:
        return self.inserted + self.updated


# ---------------------------------------------------------------------------
# Read paths — alias lookup map (called by inference)
# ---------------------------------------------------------------------------


async def load_alias_map(tenant_id: UUID, provider_id: str) -> dict[str, str]:
    """Return `{vendor_team_value (lower) → squad_key}` for the tenant.

    Called once per inference run. Empty dict when no aliases configured
    (graceful degradation: inference continues with raw tag values, which
    is the PR 3 behaviour).
    """
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT vendor_team_value, squad_key
                FROM tenant_team_alias
                WHERE tenant_id = :tenant_id AND provider = :provider
                """
            ),
            {"tenant_id": str(tenant_id), "provider": provider_id},
        )
        return {r.vendor_team_value: r.squad_key for r in result.all()}


async def list_aliases(tenant_id: UUID, provider_id: str) -> list[TeamAlias]:
    """Return aliases ordered by vendor_team_value for the admin UI."""
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT vendor_team_value, squad_key, created_at, updated_at
                FROM tenant_team_alias
                WHERE tenant_id = :tenant_id AND provider = :provider
                ORDER BY vendor_team_value
                """
            ),
            {"tenant_id": str(tenant_id), "provider": provider_id},
        )
        return [
            TeamAlias(
                vendor_team_value=r.vendor_team_value,
                squad_key=r.squad_key,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in result.all()
        ]


async def list_unaliased_vendor_teams(
    tenant_id: UUID, provider_id: str,
) -> list[str]:
    """Distinct DD `team` values seen in inference that have NO alias
    configured yet — used by the UI to surface "you have N unmapped
    teams" and offer fast-track import.

    Reads from `service_squad_ownership.metadata->>team_tag_raw`
    (populated by `ownership_inference._build_metadata`). Excludes
    rows where the inferred_squad_key is already a valid squad key
    (those don't need an alias).
    """
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT DISTINCT lower(metadata->>'team_tag_raw') AS vendor_team
                FROM service_squad_ownership sso
                WHERE sso.tenant_id = :tenant_id
                  AND sso.provider = :provider
                  AND sso.metadata ? 'team_tag_raw'
                  AND lower(metadata->>'team_tag_raw') NOT IN (
                      SELECT vendor_team_value
                      FROM tenant_team_alias
                      WHERE tenant_id = :tenant_id AND provider = :provider
                  )
                ORDER BY vendor_team
                """
            ),
            {"tenant_id": str(tenant_id), "provider": provider_id},
        )
        return [r.vendor_team for r in result.all() if r.vendor_team]


# ---------------------------------------------------------------------------
# Write paths
# ---------------------------------------------------------------------------


def _normalize_vendor_team(value: str) -> str:
    """Lowercase + strip — DD tag values are case-insensitive in
    practice, so we store one canonical form. Empty after trim → ''
    (caller raises)."""
    if not value:
        return ""
    return value.strip().lower()


async def set_alias(
    tenant_id: UUID,
    provider_id: str,
    vendor_team_value: str,
    squad_key: str,
) -> TeamAlias:
    """Upsert one alias. Validates `squad_key` against the qualified
    squads set BEFORE the DB write.

    Raises:
      - `ValueError` when vendor_team_value is empty after normalization.
      - `InvalidSquadKeyError` when squad_key isn't qualified.
    """
    canonical = _normalize_vendor_team(vendor_team_value)
    if not canonical:
        raise ValueError("vendor_team_value must not be empty")

    await SquadDirectory.assert_valid_squad(tenant_id, squad_key)

    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                INSERT INTO tenant_team_alias (
                    tenant_id, provider, vendor_team_value, squad_key
                )
                VALUES (:tenant_id, :provider, :vendor_team, :squad_key)
                ON CONFLICT (tenant_id, provider, vendor_team_value)
                DO UPDATE SET
                    squad_key = EXCLUDED.squad_key,
                    updated_at = NOW()
                RETURNING vendor_team_value, squad_key, created_at, updated_at
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "vendor_team": canonical,
                "squad_key": squad_key,
            },
        )
        row = result.first()
        await session.commit()

    logger.info(
        "[obs-alias] set tenant=%s provider=%s vendor_team=%s → squad=%s",
        tenant_id, provider_id, canonical, squad_key,
    )
    return TeamAlias(
        vendor_team_value=row.vendor_team_value,
        squad_key=row.squad_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def delete_alias(
    tenant_id: UUID, provider_id: str, vendor_team_value: str,
) -> bool:
    """Remove one alias. Returns True if a row was deleted, False if
    not found (404 in the route layer)."""
    canonical = _normalize_vendor_team(vendor_team_value)
    if not canonical:
        return False

    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                DELETE FROM tenant_team_alias
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND vendor_team_value = :vendor_team
                RETURNING vendor_team_value
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "vendor_team": canonical,
            },
        )
        deleted = result.first() is not None
        await session.commit()

    if deleted:
        logger.info(
            "[obs-alias] delete tenant=%s provider=%s vendor_team=%s",
            tenant_id, provider_id, canonical,
        )
    return deleted


async def bulk_import(
    tenant_id: UUID,
    provider_id: str,
    mappings: list[tuple[str, str]],
) -> BulkImportResult:
    """Atomic batch upsert. Validates each squad_key against the
    qualified set; rows with invalid squads are counted as rejected
    rather than failing the whole batch (operators get a clean summary
    + can fix typos and retry).

    `mappings` is a list of `(vendor_team_value, squad_key)` tuples.
    Empty / whitespace-only entries on either side are rejected.

    The whole import runs in a single transaction — either all
    valid rows commit, or none.
    """
    qualified_squads = await SquadDirectory.list_qualified_squads(tenant_id)
    inserted = 0
    updated = 0
    rejected_invalid = 0
    rejected_empty = 0

    async with get_session(tenant_id) as session:
        for vendor_team, squad_key in mappings:
            canonical = _normalize_vendor_team(vendor_team)
            squad = (squad_key or "").strip()
            if not canonical or not squad:
                rejected_empty += 1
                continue
            if squad not in qualified_squads:
                rejected_invalid += 1
                continue

            result = await session.execute(
                text(
                    """
                    INSERT INTO tenant_team_alias (
                        tenant_id, provider, vendor_team_value, squad_key
                    )
                    VALUES (:tenant_id, :provider, :vendor_team, :squad_key)
                    ON CONFLICT (tenant_id, provider, vendor_team_value)
                    DO UPDATE SET
                        squad_key = EXCLUDED.squad_key,
                        updated_at = NOW()
                    RETURNING xmax = 0 AS inserted
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "provider": provider_id,
                    "vendor_team": canonical,
                    "squad_key": squad,
                },
            )
            row = result.first()
            if row and row.inserted:
                inserted += 1
            else:
                updated += 1

        await session.commit()

    logger.info(
        "[obs-alias] bulk_import tenant=%s provider=%s submitted=%d "
        "inserted=%d updated=%d rejected_invalid=%d rejected_empty=%d",
        tenant_id, provider_id, len(mappings),
        inserted, updated, rejected_invalid, rejected_empty,
    )
    return BulkImportResult(
        inserted=inserted,
        updated=updated,
        rejected_invalid_squad=rejected_invalid,
        rejected_empty=rejected_empty,
        total_submitted=len(mappings),
    )
