"""Integration test: SmartPrioritizer scores from real eng_pull_requests rows.

Setup:
- Insert fake eng_pull_requests with Jira keys in titles:
    PROJ1: 5 PRs
    PROJ2: 2 PRs  (below threshold=3 → stays discovered)
    PROJ3: 10 PRs
- Insert 3 matching catalog rows as status='discovered'.
- Set smart_min_pr_references=3.
- Call SmartPrioritizer.score_projects then auto_activate.

Assertions:
- PROJ2 stays discovered (below threshold).
- PROJ1 and PROJ3 become active with activation_source='smart_pr_scan'.
- Audit rows with event_type='project_activated' and actor='smart_auto' exist for each.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    insert_catalog_project,
    insert_tenant_config,
)

_SMART_THRESHOLD = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _insert_prs_for_project(
    session: AsyncSession,
    project_key: str,
    count: int,
    tenant_id: uuid.UUID = TENANT_ID,
) -> None:
    """Insert `count` eng_pull_requests rows whose titles reference `project_key`.

    Uses raw SQL to avoid coupling to ORM layer which may not be migrated
    identically in the test container.
    """
    for i in range(count):
        external_id = f"{project_key}-pr-{i}"
        title = f"feat({project_key}-{i + 1}): implement feature {i}"
        await session.execute(
            text(
                """
                INSERT INTO eng_pull_requests (
                    id, tenant_id, external_id, source, repo, title, author,
                    state, is_merged, additions, deletions, files_changed,
                    commits_count, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :tenant_id, :external_id, 'github',
                    'org/backend', :title, 'testbot', 'merged', true,
                    10, 2, 1, 1, now(), now()
                )
                ON CONFLICT (tenant_id, external_id) DO NOTHING
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "external_id": external_id,
                "title": title,
            },
        )


@pytest.mark.asyncio
async def test_smart_prioritizer_scores_and_activates_above_threshold(session: AsyncSession):
    """PROJ1 (5 refs) and PROJ3 (10 refs) activate; PROJ2 (2 refs) stays discovered."""
    from src.contexts.integrations.jira.discovery.smart_prioritizer import SmartPrioritizer
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(
        session,
        mode="smart",
        smart_min_pr_references=_SMART_THRESHOLD,
        smart_pr_scan_days=365,  # wide window ensures all inserted PRs are counted
    )

    # Insert catalog rows as 'discovered'
    for key in ("PROJ1", "PROJ2", "PROJ3"):
        await insert_catalog_project(session, key, status="discovered", pr_reference_count=0)

    # Insert PR rows referencing each project key in their titles
    await _insert_prs_for_project(session, "PROJ1", count=5)
    await _insert_prs_for_project(session, "PROJ2", count=2)
    await _insert_prs_for_project(session, "PROJ3", count=10)

    prioritizer = SmartPrioritizer(session)
    scores = await prioritizer.score_projects(TENANT_ID)

    # Scores must be non-zero for all three
    assert scores.get("PROJ1", 0) == 5
    assert scores.get("PROJ2", 0) == 2
    assert scores.get("PROJ3", 0) == 10

    activated_count = await prioritizer.auto_activate(TENANT_ID)
    assert activated_count == 2, "Expected PROJ1 and PROJ3 to be activated"

    repo = DiscoveryRepository(session)

    proj1 = await repo.get_project(TENANT_ID, "PROJ1")
    assert proj1 is not None
    assert proj1["status"] == "active"
    assert proj1["activation_source"] == "smart_pr_scan"

    proj2 = await repo.get_project(TENANT_ID, "PROJ2")
    assert proj2 is not None
    assert proj2["status"] == "discovered", "PROJ2 is below threshold — must stay discovered"

    proj3 = await repo.get_project(TENANT_ID, "PROJ3")
    assert proj3 is not None
    assert proj3["status"] == "active"
    assert proj3["activation_source"] == "smart_pr_scan"


@pytest.mark.asyncio
async def test_audit_rows_exist_for_smart_activated_projects(session: AsyncSession):
    """Audit log must contain project_activated rows with actor='smart_auto' for each activation."""
    from src.contexts.integrations.jira.discovery.smart_prioritizer import SmartPrioritizer
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(
        session,
        mode="smart",
        smart_min_pr_references=_SMART_THRESHOLD,
        smart_pr_scan_days=365,
    )

    for key in ("PROJ1", "PROJ3"):
        await insert_catalog_project(session, key, status="discovered", pr_reference_count=0)

    await _insert_prs_for_project(session, "PROJ1", count=5)
    await _insert_prs_for_project(session, "PROJ3", count=10)

    prioritizer = SmartPrioritizer(session)
    await prioritizer.score_projects(TENANT_ID)
    await prioritizer.auto_activate(TENANT_ID)

    repo = DiscoveryRepository(session)
    audit_items, total = await repo.list_audit(
        TENANT_ID, event_type="project_activated", limit=100
    )

    activated_keys = {item["project_key"] for item in audit_items if item["actor"] == "smart_auto"}
    assert "PROJ1" in activated_keys, "Audit missing project_activated for PROJ1"
    assert "PROJ3" in activated_keys, "Audit missing project_activated for PROJ3"


@pytest.mark.asyncio
async def test_smart_does_not_activate_below_threshold(session: AsyncSession):
    """If all discovered projects are below threshold, none activate."""
    from src.contexts.integrations.jira.discovery.smart_prioritizer import SmartPrioritizer
    from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository

    await insert_tenant_config(
        session,
        mode="smart",
        smart_min_pr_references=10,  # high threshold
        smart_pr_scan_days=365,
    )

    for key in ("LOW1", "LOW2"):
        await insert_catalog_project(session, key, status="discovered", pr_reference_count=0)

    # Only 2 PRs each — below threshold of 10
    await _insert_prs_for_project(session, "LOW1", count=2)
    await _insert_prs_for_project(session, "LOW2", count=2)

    prioritizer = SmartPrioritizer(session)
    await prioritizer.score_projects(TENANT_ID)
    activated = await prioritizer.auto_activate(TENANT_ID)

    assert activated == 0

    repo = DiscoveryRepository(session)
    low1 = await repo.get_project(TENANT_ID, "LOW1")
    low2 = await repo.get_project(TENANT_ID, "LOW2")
    assert low1["status"] == "discovered"
    assert low2["status"] == "discovered"
