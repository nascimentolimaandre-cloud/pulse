"""Integration test: Guardrails against a real PostgreSQL instance.

Covers:
1. Project cap: 15 active projects with max_active_projects=10 → 5 lowest-ref get paused.
2. Auto-pause: 5 consecutive sync failures → project auto-paused + audit emitted.
3. Blocked immunity: blocked projects cannot be modified by guardrails.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    insert_catalog_project,
    insert_tenant_config,
)


@pytest.mark.asyncio
async def test_project_cap_pauses_5_lowest_ref_projects(session: AsyncSession):
    """15 active projects (max=10) → 5 lowest pr_reference_count become paused."""
    from src.contexts.integrations.jira.discovery.guardrails import Guardrails
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(session, mode="auto", max_active_projects=10)

    # Insert 15 active projects with distinct pr_reference_count values 0..14
    for i in range(15):
        await insert_catalog_project(
            session,
            f"CAP{i:02d}",
            status="active",
            pr_reference_count=i,  # CAP00..CAP04 have lowest counts (0-4)
        )

    guardrails = Guardrails(session, redis_client=None)
    paused_count = await guardrails.enforce_project_cap(TENANT_ID)

    assert paused_count == 5, f"Expected 5 paused, got {paused_count}"

    repo = DiscoveryRepository(session)
    items, _ = await repo.list_projects(TENANT_ID, status="paused", limit=100)
    paused_keys = {p["project_key"] for p in items}

    # The 5 lowest-ref projects (CAP00–CAP04, refs 0–4) should be paused
    expected_paused = {f"CAP{i:02d}" for i in range(5)}
    assert paused_keys == expected_paused, (
        f"Wrong projects paused. Expected {expected_paused}, got {paused_keys}"
    )

    # Remaining 10 should still be active
    items_active, _ = await repo.list_projects(TENANT_ID, status="active", limit=100)
    assert len(items_active) == 10


@pytest.mark.asyncio
async def test_project_cap_emits_audit_events(session: AsyncSession):
    """Each paused project from cap enforcement must have a project_cap_enforced audit event."""
    from src.contexts.integrations.jira.discovery.guardrails import Guardrails
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(session, mode="auto", max_active_projects=3)

    for i in range(5):
        await insert_catalog_project(
            session, f"AUDIT{i}", status="active", pr_reference_count=i
        )

    guardrails = Guardrails(session, redis_client=None)
    await guardrails.enforce_project_cap(TENANT_ID)

    repo = DiscoveryRepository(session)
    audit_items, _ = await repo.list_audit(
        TENANT_ID, event_type="project_cap_enforced", limit=100
    )

    assert len(audit_items) == 2, (
        f"Expected 2 cap-enforced audit events (5 active - 3 cap = 2 paused), "
        f"got {len(audit_items)}"
    )
    for item in audit_items:
        assert item["actor"] == "system"
        assert item["after_value"]["status"] == "paused"


@pytest.mark.asyncio
async def test_5_consecutive_failures_auto_pause_project(session: AsyncSession):
    """5 consecutive sync failures trigger auto-pause with audit event."""
    from src.contexts.integrations.jira.discovery.guardrails import Guardrails
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(session, mode="auto")
    await insert_catalog_project(session, "FLAKY", status="active")

    guardrails = Guardrails(session, redis_client=None)

    # Record 4 failures — should NOT trigger auto-pause yet
    for _ in range(4):
        await guardrails.record_sync_outcome(
            TENANT_ID, "FLAKY", success=False, error="Connection timeout"
        )

    repo = DiscoveryRepository(session)
    project = await repo.get_project(TENANT_ID, "FLAKY")
    assert project["status"] == "active", "Should not be paused after only 4 failures"
    assert project["consecutive_failures"] == 4

    # 5th failure → auto-pause
    await guardrails.record_sync_outcome(
        TENANT_ID, "FLAKY", success=False, error="Connection timeout"
    )

    project = await repo.get_project(TENANT_ID, "FLAKY")
    assert project["status"] == "paused", "Should be paused after 5 consecutive failures"
    assert project["consecutive_failures"] == 5

    # Audit event must exist
    audit_items, _ = await repo.list_audit(
        TENANT_ID, event_type="project_auto_paused", project_key="FLAKY"
    )
    assert len(audit_items) >= 1
    audit = audit_items[0]
    assert audit["actor"] == "system"
    assert audit["after_value"]["status"] == "paused"


@pytest.mark.asyncio
async def test_successful_sync_resets_failure_counter(session: AsyncSession):
    """A successful sync outcome after failures resets consecutive_failures to 0."""
    from src.contexts.integrations.jira.discovery.guardrails import Guardrails
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(session, mode="auto")
    await insert_catalog_project(session, "PARTIAL", status="active")

    guardrails = Guardrails(session, redis_client=None)

    # Record 3 failures
    for _ in range(3):
        await guardrails.record_sync_outcome(
            TENANT_ID, "PARTIAL", success=False, error="Timeout"
        )

    # Then a success
    await guardrails.record_sync_outcome(TENANT_ID, "PARTIAL", success=True)

    repo = DiscoveryRepository(session)
    project = await repo.get_project(TENANT_ID, "PARTIAL")
    assert project["consecutive_failures"] == 0
    assert project["last_sync_status"] == "success"
    assert project["status"] == "active", "Should remain active after recovery"


@pytest.mark.asyncio
async def test_blocked_project_is_immune_to_guardrails(session: AsyncSession):
    """Guardrails must not modify a blocked project's status, even via cap enforcement."""
    from src.contexts.integrations.jira.discovery.guardrails import Guardrails
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    # max_active_projects=0 would normally pause everything — blocked must survive
    await insert_tenant_config(session, mode="auto", max_active_projects=0)

    # Insert a blocked project
    await insert_catalog_project(session, "IMMUTABLE", status="blocked")

    # Also insert an active project to confirm cap enforcement runs at all
    await insert_catalog_project(session, "PAUSABLE", status="active", pr_reference_count=99)

    guardrails = Guardrails(session, redis_client=None)
    await guardrails.enforce_project_cap(TENANT_ID)

    repo = DiscoveryRepository(session)
    immutable = await repo.get_project(TENANT_ID, "IMMUTABLE")
    assert immutable["status"] == "blocked", (
        "Blocked project status must not change during cap enforcement"
    )

    # record_sync_outcome on a blocked project must be a no-op
    await guardrails.record_sync_outcome(
        TENANT_ID, "IMMUTABLE", success=False, error="any error"
    )
    immutable_after = await repo.get_project(TENANT_ID, "IMMUTABLE")
    assert immutable_after["status"] == "blocked"
    assert immutable_after["consecutive_failures"] == 0, (
        "consecutive_failures must not increment for a blocked project"
    )
