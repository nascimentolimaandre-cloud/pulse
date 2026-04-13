"""Integration test: mode switching reroutes which projects are included in sync.

Scenario:
- 5 projects with distinct statuses: active, paused, blocked, discovered, archived.
- Iterate through all 4 operational modes.
- For each mode, assert resolve_active_projects returns the exact expected set.

Mode semantics (from ADR-014 and ModeResolver implementation):
    auto       -> discovered + active (never blocked)
    allowlist  -> active only (never blocked)
    blocklist  -> discovered + active + paused (never blocked)
    smart      -> active always + discovered if pr_reference_count >= threshold
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    insert_catalog_project,
    insert_tenant_config,
)

# Project keys to be seeded with specific statuses
KEY_ACTIVE = "ACTIVE"
KEY_PAUSED = "PAUSED"
KEY_BLOCKED = "BLOCKED"
KEY_DISCOVERED = "DISC"
KEY_ARCHIVED = "ARCHIVE"

# smart_min_pr_references = 3; DISC has 1 reference so it stays out of smart set.
# To include DISC in smart mode the reference count would need to meet threshold.
_SMART_THRESHOLD = 3


@pytest.fixture(autouse=True)
async def seed_projects(session: AsyncSession):
    """Seed catalog with 5 projects covering all status values."""
    await insert_tenant_config(
        session,
        mode="allowlist",  # starting mode — each test overrides via upsert
        smart_min_pr_references=_SMART_THRESHOLD,
    )
    await insert_catalog_project(session, KEY_ACTIVE, status="active")
    await insert_catalog_project(session, KEY_PAUSED, status="paused")
    await insert_catalog_project(session, KEY_BLOCKED, status="blocked")
    await insert_catalog_project(session, KEY_DISCOVERED, status="discovered", pr_reference_count=1)
    await insert_catalog_project(session, KEY_ARCHIVED, status="archived")


async def _switch_mode(session: AsyncSession, mode: str) -> None:
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository
    repo = DiscoveryRepository(session)
    await repo.upsert_tenant_config(TENANT_ID, mode=mode)


async def _resolve(session: AsyncSession) -> set[str]:
    from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver
    resolver = ModeResolver(session)
    return set(await resolver.resolve_active_projects(TENANT_ID))


@pytest.mark.asyncio
async def test_auto_mode_returns_discovered_and_active_not_blocked(session: AsyncSession):
    """auto: discovered + active; paused/blocked/archived excluded."""
    await _switch_mode(session, "auto")
    active = await _resolve(session)

    assert KEY_ACTIVE in active
    assert KEY_DISCOVERED in active
    assert KEY_BLOCKED not in active
    assert KEY_PAUSED not in active
    assert KEY_ARCHIVED not in active


@pytest.mark.asyncio
async def test_allowlist_mode_returns_only_active(session: AsyncSession):
    """allowlist: only explicitly active projects; nothing else."""
    await _switch_mode(session, "allowlist")
    active = await _resolve(session)

    assert active == {KEY_ACTIVE}


@pytest.mark.asyncio
async def test_blocklist_mode_returns_discovered_active_paused_not_blocked(session: AsyncSession):
    """blocklist: discovered + active + paused; blocked/archived excluded."""
    await _switch_mode(session, "blocklist")
    active = await _resolve(session)

    assert KEY_ACTIVE in active
    assert KEY_DISCOVERED in active
    assert KEY_PAUSED in active
    assert KEY_BLOCKED not in active
    assert KEY_ARCHIVED not in active


@pytest.mark.asyncio
async def test_smart_mode_returns_active_and_high_ref_discovered(session: AsyncSession):
    """smart: active always included; discovered only if pr_reference_count >= threshold.

    DISC has 1 reference (< threshold 3) → excluded.
    To verify the inclusion path: insert HIGHREF project with count >= threshold.
    """
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    # Add a discovered project with enough PR refs to meet smart threshold
    repo = DiscoveryRepository(session)
    await repo.upsert_project(
        TENANT_ID,
        "HIGHREF",
        project_id="ID-HIGHREF",
        name="High Reference Project",
        project_type="software",
        status="discovered",
        pr_reference_count=5,  # >= _SMART_THRESHOLD (3)
    )

    await _switch_mode(session, "smart")
    active = await _resolve(session)

    # Active is always included
    assert KEY_ACTIVE in active
    # HIGHREF meets threshold → included
    assert "HIGHREF" in active
    # DISC has 1 ref → below threshold → excluded
    assert KEY_DISCOVERED not in active
    # Blocked is always excluded
    assert KEY_BLOCKED not in active
    # Archived is never included
    assert KEY_ARCHIVED not in active
    # Paused is not in smart mode allowed set
    assert KEY_PAUSED not in active


@pytest.mark.asyncio
async def test_blocked_invariant_holds_across_all_modes(session: AsyncSession):
    """The blocked project must never appear in resolve output regardless of mode."""
    for mode in ("auto", "allowlist", "blocklist", "smart"):
        await _switch_mode(session, mode)
        active = await _resolve(session)
        assert KEY_BLOCKED not in active, (
            f"Blocked project appeared in resolve output for mode={mode}"
        )
