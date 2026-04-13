"""Integration test: full discovery run end-to-end against a real PostgreSQL instance.

Covers:
- run_discovery populates catalog with 10 rows
- mode=allowlist → resolve_active_projects returns 0 (none activated yet)
- Activating 3 projects → resolve returns 3
- Blocking 1 of those 3 → resolve returns 2
- Switching mode to auto → blocked project stays excluded

All assertions are on database state — no mocking of internal services.
Only JiraClient.fetch_all_accessible_projects is mocked (external API).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    insert_tenant_config,
    make_jira_project_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jira_client(project_keys: list[str]) -> MagicMock:
    """Return a mock JiraClient that yields the given project keys."""
    client = MagicMock()
    client.fetch_all_accessible_projects = AsyncMock(
        return_value=[make_jira_project_payload(k) for k in project_keys]
    )
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discovery_populates_catalog_with_10_rows(session: AsyncSession):
    """run_discovery with 10 Jira projects → 10 catalog rows inserted."""
    from src.contexts.integrations.jira.discovery.project_discovery_service import (
        ProjectDiscoveryService,
    )
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(session, mode="allowlist")

    project_keys = [f"PROJ{i}" for i in range(1, 11)]
    jira_client = _make_jira_client(project_keys)

    service = ProjectDiscoveryService(session=session, jira_client=jira_client)
    result = await service.run_discovery(TENANT_ID)

    assert result["discoveredCount"] == 10
    assert result["status"] in ("success", "partial")

    repo = DiscoveryRepository(session)
    items, total = await repo.list_projects(TENANT_ID, limit=100, offset=0)
    assert total == 10
    catalog_keys = {p["project_key"] for p in items}
    assert catalog_keys == set(project_keys)


@pytest.mark.asyncio
async def test_allowlist_mode_returns_zero_projects_when_none_active(session: AsyncSession):
    """mode=allowlist, no projects manually activated → resolve returns []."""
    from src.contexts.integrations.jira.discovery.project_discovery_service import (
        ProjectDiscoveryService,
    )
    from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver

    await insert_tenant_config(session, mode="allowlist")

    project_keys = [f"PROJ{i}" for i in range(1, 6)]
    jira_client = _make_jira_client(project_keys)

    service = ProjectDiscoveryService(session=session, jira_client=jira_client)
    await service.run_discovery(TENANT_ID)

    resolver = ModeResolver(session)
    active = await resolver.resolve_active_projects(TENANT_ID)

    assert active == [], (
        "In allowlist mode, discovered-only projects must not be returned by resolver"
    )


@pytest.mark.asyncio
async def test_activating_3_projects_returns_3_from_resolver(session: AsyncSession):
    """Activate 3 of 10 discovered projects → resolver returns exactly those 3."""
    from src.contexts.integrations.jira.discovery.project_discovery_service import (
        ProjectDiscoveryService,
    )
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository
    from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver

    await insert_tenant_config(session, mode="allowlist")

    project_keys = [f"PROJ{i}" for i in range(1, 11)]
    jira_client = _make_jira_client(project_keys)
    service = ProjectDiscoveryService(session=session, jira_client=jira_client)
    await service.run_discovery(TENANT_ID)

    repo = DiscoveryRepository(session)
    keys_to_activate = ["PROJ1", "PROJ2", "PROJ3"]
    for key in keys_to_activate:
        await repo.update_project_status(
            TENANT_ID, key, status="active", actor="test_user", reason="manual activation"
        )

    resolver = ModeResolver(session)
    active = await resolver.resolve_active_projects(TENANT_ID)

    assert sorted(active) == sorted(keys_to_activate)


@pytest.mark.asyncio
async def test_blocking_one_active_project_returns_2(session: AsyncSession):
    """Block 1 of 3 active projects → resolver returns only 2."""
    from src.contexts.integrations.jira.discovery.project_discovery_service import (
        ProjectDiscoveryService,
    )
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository
    from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver

    await insert_tenant_config(session, mode="allowlist")

    project_keys = [f"PROJ{i}" for i in range(1, 11)]
    jira_client = _make_jira_client(project_keys)
    service = ProjectDiscoveryService(session=session, jira_client=jira_client)
    await service.run_discovery(TENANT_ID)

    repo = DiscoveryRepository(session)
    for key in ["PROJ1", "PROJ2", "PROJ3"]:
        await repo.update_project_status(TENANT_ID, key, status="active", actor="test")

    # Block PROJ3
    await repo.update_project_status(TENANT_ID, "PROJ3", status="blocked", actor="test")

    resolver = ModeResolver(session)
    active = await resolver.resolve_active_projects(TENANT_ID)

    assert sorted(active) == ["PROJ1", "PROJ2"]
    assert "PROJ3" not in active, "Blocked project must never appear in resolved list"


@pytest.mark.asyncio
async def test_switching_to_auto_mode_still_excludes_blocked(session: AsyncSession):
    """Switch mode from allowlist to auto: blocked project remains excluded."""
    from src.contexts.integrations.jira.discovery.project_discovery_service import (
        ProjectDiscoveryService,
    )
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository
    from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver

    await insert_tenant_config(session, mode="allowlist")

    project_keys = ["ALPHA", "BETA", "GAMMA"]
    jira_client = _make_jira_client(project_keys)
    service = ProjectDiscoveryService(session=session, jira_client=jira_client)
    await service.run_discovery(TENANT_ID)

    repo = DiscoveryRepository(session)
    # Block GAMMA — should be immune regardless of mode
    await repo.update_project_status(TENANT_ID, "GAMMA", status="blocked", actor="test")

    # Switch mode to auto (discovers all except blocked)
    await repo.upsert_tenant_config(TENANT_ID, mode="auto")

    resolver = ModeResolver(session)
    active = await resolver.resolve_active_projects(TENANT_ID)

    # auto mode includes discovered + active, but never blocked
    assert "GAMMA" not in active, "Blocked project invariant violated after mode switch to auto"
    # ALPHA and BETA are in 'discovered' state → auto mode includes them
    assert "ALPHA" in active
    assert "BETA" in active
