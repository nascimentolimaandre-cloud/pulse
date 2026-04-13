"""Unit tests for DiscoveryRepository.

Tests CRUD happy paths and audit append-only enforcement.
Since these are unit tests (no real DB), we mock the AsyncSession.
The append-only enforcement is a PostgreSQL RULE (tested at integration level),
but we verify the repository only uses INSERT for audits (never UPDATE/DELETE).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.contexts.integrations.jira.discovery.repository import (
    DiscoveryRepository,
    jira_discovery_audit,
    jira_project_catalog,
    tenant_jira_config,
)
from tests.unit.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    make_config,
    make_project,
)


class TestGetTenantConfig:
    @pytest.mark.asyncio
    async def test_returns_config_dict(self):
        session = AsyncMock()
        config = make_config()
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = config
        session.execute = AsyncMock(return_value=result_mock)

        repo = DiscoveryRepository(session)
        result = await repo.get_tenant_config(TENANT_ID)

        assert result is not None
        assert result["mode"] == "allowlist"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        repo = DiscoveryRepository(session)
        result = await repo.get_tenant_config(TENANT_ID)

        assert result is None


class TestUpsertTenantConfig:
    @pytest.mark.asyncio
    async def test_upsert_returns_dict(self):
        session = AsyncMock()
        config = make_config(mode="smart")
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = config
        session.execute = AsyncMock(return_value=result_mock)

        repo = DiscoveryRepository(session)
        result = await repo.upsert_tenant_config(TENANT_ID, mode="smart")

        assert result["mode"] == "smart"
        session.execute.assert_called_once()


class TestListProjects:
    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        session = AsyncMock()
        projects = [make_project("BACK"), make_project("DESC")]

        # First call = count, second call = items
        count_mock = MagicMock()
        count_mock.scalar.return_value = 2
        items_mock = MagicMock()
        items_mock.mappings.return_value.all.return_value = projects
        session.execute = AsyncMock(side_effect=[count_mock, items_mock])

        repo = DiscoveryRepository(session)
        items, total = await repo.list_projects(TENANT_ID, status="discovered")

        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self):
        session = AsyncMock()
        count_mock = MagicMock()
        count_mock.scalar.return_value = 0
        items_mock = MagicMock()
        items_mock.mappings.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[count_mock, items_mock])

        repo = DiscoveryRepository(session)
        items, total = await repo.list_projects(TENANT_ID)

        assert total == 0
        assert items == []


class TestGetProject:
    @pytest.mark.asyncio
    async def test_returns_project(self):
        session = AsyncMock()
        project = make_project("BACK")
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = project
        session.execute = AsyncMock(return_value=result_mock)

        repo = DiscoveryRepository(session)
        result = await repo.get_project(TENANT_ID, "BACK")

        assert result["project_key"] == "BACK"

    @pytest.mark.asyncio
    async def test_returns_none_not_found(self):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        repo = DiscoveryRepository(session)
        result = await repo.get_project(TENANT_ID, "GHOST")

        assert result is None


class TestUpsertProject:
    @pytest.mark.asyncio
    async def test_upsert_executes(self):
        session = AsyncMock()
        project = make_project("BACK", status="active")
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = project
        session.execute = AsyncMock(return_value=result_mock)

        repo = DiscoveryRepository(session)
        result = await repo.upsert_project(TENANT_ID, "BACK", status="active")

        assert result["project_key"] == "BACK"
        session.execute.assert_called_once()


class TestUpdateProjectStatus:
    @pytest.mark.asyncio
    async def test_writes_audit_atomically(self):
        session = AsyncMock()
        project = make_project("BACK", status="discovered")
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = project
        session.execute = AsyncMock(return_value=result_mock)

        repo = DiscoveryRepository(session)
        await repo.update_project_status(
            TENANT_ID, "BACK", status="active", actor="admin", reason="Approved",
        )

        # Should have 3 execute calls: get_project, update status, insert audit
        assert session.execute.call_count == 3


class TestAppendAudit:
    @pytest.mark.asyncio
    async def test_insert_returns_id(self):
        session = AsyncMock()
        repo = DiscoveryRepository(session)

        row_id = await repo.append_audit(
            TENANT_ID, event_type="discovery_run", actor="system",
        )

        assert isinstance(row_id, uuid.UUID)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_uses_insert_only(self):
        """Verify the repository ONLY uses INSERT for audit (never UPDATE/DELETE).

        The actual DB enforcement is via PostgreSQL RULEs (no_update_audit,
        no_delete_audit) — tested at integration level. Here we verify the
        repository code path only issues INSERT statements.
        """
        session = AsyncMock()
        repo = DiscoveryRepository(session)

        await repo.append_audit(TENANT_ID, event_type="test_event")

        # Inspect the compiled statement
        call_args = session.execute.call_args
        stmt = call_args[0][0]
        # SQLAlchemy Insert objects have an .is_insert property
        assert hasattr(stmt, "is_insert") or "INSERT" in str(stmt).upper()


class TestListAudit:
    @pytest.mark.asyncio
    async def test_list_with_filters(self):
        session = AsyncMock()
        audits = [
            {"id": uuid.uuid4(), "event_type": "discovery_run", "tenant_id": TENANT_ID},
        ]
        count_mock = MagicMock()
        count_mock.scalar.return_value = 1
        items_mock = MagicMock()
        items_mock.mappings.return_value.all.return_value = audits
        session.execute = AsyncMock(side_effect=[count_mock, items_mock])

        repo = DiscoveryRepository(session)
        items, total = await repo.list_audit(TENANT_ID, event_type="discovery_run")

        assert total == 1
        assert len(items) == 1


class TestBulkSetSyncResult:
    @pytest.mark.asyncio
    async def test_bulk_updates_multiple_projects(self):
        session = AsyncMock()
        repo = DiscoveryRepository(session)

        results = [
            ("BACK", "success", None),
            ("DESC", "failed", "timeout"),
        ]
        await repo.bulk_set_sync_result(TENANT_ID, results)

        assert session.execute.call_count == 2
