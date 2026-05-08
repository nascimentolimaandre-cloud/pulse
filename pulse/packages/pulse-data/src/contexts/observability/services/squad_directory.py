"""FDD-OBS-001 PR 3 — qualified-squads directory.

`SquadDirectory` is the canonical source for "which squad keys are
valid in this tenant?". Reads from `jira_project_catalog`, the same
table used by the squad-qualification service (`contexts/pipeline/`).

Used by:
  - `OwnershipInferenceService` to flag DD `team:<x>` tags that point
    to squads not in the tenant (yellow badge in the UI — operator
    decides if it's a typo or a new squad to qualify).
  - `routes.py` admin override path to validate `squad_key` before
    persisting (raises `InvalidSquadKeyError` → HTTP 422).

Why a service (not a Pydantic frozenset): the squad list is
**tenant-scoped and dynamic** — it changes when projects get qualified
or excluded via the squad-qualification service. A static
`Literal[...]` would lock R2 to one tenant's squads.

NOT a repository: this is a thin read-model (one method, one query)
that doesn't merit a full repo abstraction. Adding a repo just to host
this single SELECT would be ceremony.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text

from src.database import get_session

logger = logging.getLogger(__name__)


class InvalidSquadKeyError(ValueError):
    """Raised when a caller-supplied squad_key isn't in the tenant's
    qualified-squads set."""


class SquadDirectory:
    """Read-only directory of valid squad keys per tenant."""

    @staticmethod
    async def list_qualified_squads(tenant_id: UUID) -> frozenset[str]:
        """Return the set of `project_key` values that are active OR
        discovered AND not explicitly excluded by `qualification_override`.

        Excludes:
          - status NOT IN ('active', 'discovered')
          - qualification_override = 'excluded'

        Includes everything else (treats NULL `qualification_override`
        as "default to active discovery rules"). Mirrors the gate used
        by `contexts.pipeline.services.squad_qualification`.

        Returns frozenset for cheap repeated `in` checks during
        inference (called once per service in the catalog).
        """
        async with get_session(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT project_key
                    FROM jira_project_catalog
                    WHERE tenant_id = :tenant_id
                      AND status IN ('active', 'discovered')
                      AND (qualification_override IS NULL
                           OR qualification_override <> 'excluded')
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
            keys = {row.project_key for row in result.all()}
        return frozenset(keys)

    @classmethod
    async def is_valid_squad(cls, tenant_id: UUID, squad_key: str) -> bool:
        """True iff `squad_key` is in the tenant's qualified set."""
        if not squad_key:
            return False
        squads = await cls.list_qualified_squads(tenant_id)
        return squad_key in squads

    @classmethod
    async def assert_valid_squad(cls, tenant_id: UUID, squad_key: str) -> None:
        """Raise `InvalidSquadKeyError` if `squad_key` isn't a valid
        squad in this tenant. Used by the admin-override endpoint to
        reject typos before persisting."""
        if not await cls.is_valid_squad(tenant_id, squad_key):
            raise InvalidSquadKeyError(
                f"squad_key={squad_key!r} is not a qualified squad in this tenant"
            )
