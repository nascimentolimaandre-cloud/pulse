"""ModeResolver — single source of truth for which Jira projects to sync.

Reads the tenant's discovery mode from tenant_jira_config and resolves
the list of active project keys based on mode semantics and catalog state.

Invariant: ``blocked`` projects are ALWAYS excluded regardless of mode.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.contexts.integrations.jira.discovery.repository import (
    DiscoveryRepository,
    jira_project_catalog,
)

logger = logging.getLogger(__name__)

# Status sets per mode (before blocked exclusion)
_MODE_ALLOWED_STATUSES: dict[str, list[str]] = {
    "auto": ["discovered", "active"],
    "allowlist": ["active"],
    "blocklist": ["discovered", "active", "paused"],
    "smart": ["active"],  # discovered are conditionally included via threshold
}


class ModeResolver:
    """Resolves which Jira projects should be synced for a tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DiscoveryRepository(session)

    async def resolve_active_projects(self, tenant_id: UUID) -> list[str]:
        """Return the list of project keys to sync now, based on mode.

        Invariant: blocked projects are never returned.
        """
        config = await self._repo.get_tenant_config(tenant_id)
        if not config:
            logger.warning(
                "No tenant_jira_config found for %s — returning empty project list",
                tenant_id,
            )
            return []

        mode = config["mode"]
        logger.info("Resolving active projects for tenant %s in mode=%s", tenant_id, mode)

        if mode == "smart":
            return await self._resolve_smart(tenant_id, config)

        allowed_statuses = _MODE_ALLOWED_STATUSES.get(mode, ["active"])

        result = await self._session.execute(
            select(jira_project_catalog.c.project_key).where(
                and_(
                    jira_project_catalog.c.tenant_id == tenant_id,
                    jira_project_catalog.c.status.in_(allowed_statuses),
                    jira_project_catalog.c.status != "blocked",
                )
            )
        )
        keys = [row[0] for row in result.all()]
        logger.info("Resolved %d active projects for tenant %s (mode=%s)", len(keys), tenant_id, mode)
        return keys

    async def _resolve_smart(self, tenant_id: UUID, config: dict) -> list[str]:
        """Smart mode: active + discovered with enough PR references."""
        threshold = config.get("smart_min_pr_references", 3)

        result = await self._session.execute(
            select(jira_project_catalog.c.project_key).where(
                and_(
                    jira_project_catalog.c.tenant_id == tenant_id,
                    jira_project_catalog.c.status != "blocked",
                    # active always included; discovered only if meets threshold
                    (
                        (jira_project_catalog.c.status == "active")
                        | (
                            (jira_project_catalog.c.status == "discovered")
                            & (jira_project_catalog.c.pr_reference_count >= threshold)
                        )
                    ),
                )
            )
        )
        keys = [row[0] for row in result.all()]
        logger.info(
            "Resolved %d active projects for tenant %s (mode=smart, threshold=%d)",
            len(keys), tenant_id, threshold,
        )
        return keys
