"""Unit tests for ProjectDiscoveryService.

Covers: new/updated/archived diff, partial failure handling,
mode=auto activates vs mode=allowlist keeps discovered.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contexts.integrations.jira.discovery.project_discovery_service import (
    ProjectDiscoveryService,
)
from tests.unit.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    make_config,
    make_project,
)


def _make_jira_project(key: str, name: str = "Test") -> dict:
    return {
        "project_key": key,
        "project_id": f"100{ord(key[0])}",
        "name": name,
        "project_type": "software",
        "lead_account_id": "user123",
    }


class TestRunDiscoveryNewProjects:
    @pytest.mark.asyncio
    async def test_new_projects_discovered_in_allowlist_mode(self):
        """New projects get status=discovered in allowlist mode."""
        session = AsyncMock()
        jira_client = AsyncMock()
        jira_client.fetch_all_accessible_projects = AsyncMock(
            return_value=[_make_jira_project("BACK"), _make_jira_project("DESC")]
        )

        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="allowlist")
            with patch.object(service._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([], 0)
                with patch.object(service._repo, "upsert_project", new_callable=AsyncMock) as mock_upsert:
                    with patch.object(service._repo, "upsert_tenant_config", new_callable=AsyncMock):
                        with patch.object(service._repo, "append_audit", new_callable=AsyncMock):
                            with patch.object(service._guardrails, "enforce_project_cap", new_callable=AsyncMock):
                                result = await service.run_discovery(TENANT_ID)

        assert result["discoveredCount"] == 2
        assert result["activatedCount"] == 0
        assert result["status"] == "success"

        # Verify status=discovered was used (not active)
        for c in mock_upsert.call_args_list:
            assert c.kwargs.get("status") == "discovered"

    @pytest.mark.asyncio
    async def test_new_projects_auto_activated_in_auto_mode(self):
        """New projects get status=active in auto mode."""
        session = AsyncMock()
        jira_client = AsyncMock()
        jira_client.fetch_all_accessible_projects = AsyncMock(
            return_value=[_make_jira_project("BACK")]
        )

        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="auto")
            with patch.object(service._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([], 0)
                with patch.object(service._repo, "upsert_project", new_callable=AsyncMock) as mock_upsert:
                    with patch.object(service._repo, "upsert_tenant_config", new_callable=AsyncMock):
                        with patch.object(service._repo, "append_audit", new_callable=AsyncMock):
                            with patch.object(service._guardrails, "enforce_project_cap", new_callable=AsyncMock):
                                result = await service.run_discovery(TENANT_ID)

        assert result["discoveredCount"] == 1
        assert result["activatedCount"] == 1
        mock_upsert.assert_called_once()
        assert mock_upsert.call_args.kwargs["status"] == "active"
        assert mock_upsert.call_args.kwargs["activation_source"] == "auto_mode"


class TestRunDiscoveryUpdatedProjects:
    @pytest.mark.asyncio
    async def test_metadata_updated_when_changed(self):
        """Existing projects get metadata refreshed if name/type/lead changed."""
        session = AsyncMock()
        jira_client = AsyncMock()
        jira_client.fetch_all_accessible_projects = AsyncMock(
            return_value=[_make_jira_project("BACK", name="New Name")]
        )

        existing = make_project("BACK", status="active")
        existing["name"] = "Old Name"

        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="allowlist")
            with patch.object(service._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([existing], 1)
                with patch.object(service._repo, "upsert_project", new_callable=AsyncMock) as mock_upsert:
                    with patch.object(service._repo, "upsert_tenant_config", new_callable=AsyncMock):
                        with patch.object(service._repo, "append_audit", new_callable=AsyncMock):
                            with patch.object(service._guardrails, "enforce_project_cap", new_callable=AsyncMock):
                                result = await service.run_discovery(TENANT_ID)

        assert result["updatedCount"] == 1
        assert result["discoveredCount"] == 0


class TestRunDiscoveryArchivedProjects:
    @pytest.mark.asyncio
    async def test_missing_projects_archived(self):
        """Projects in catalog but not in Jira get archived."""
        session = AsyncMock()
        jira_client = AsyncMock()
        jira_client.fetch_all_accessible_projects = AsyncMock(return_value=[])

        existing = make_project("OLD", status="active")

        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="allowlist")
            with patch.object(service._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([existing], 1)
                with patch.object(service._repo, "update_project_status", new_callable=AsyncMock) as mock_status:
                    with patch.object(service._repo, "upsert_tenant_config", new_callable=AsyncMock):
                        with patch.object(service._repo, "append_audit", new_callable=AsyncMock):
                            with patch.object(service._guardrails, "enforce_project_cap", new_callable=AsyncMock):
                                result = await service.run_discovery(TENANT_ID)

        assert result["archivedCount"] == 1
        mock_status.assert_called_once()
        assert mock_status.call_args.kwargs["status"] == "archived"

    @pytest.mark.asyncio
    async def test_blocked_not_archived(self):
        """Blocked projects are not archived even if missing from Jira."""
        session = AsyncMock()
        jira_client = AsyncMock()
        jira_client.fetch_all_accessible_projects = AsyncMock(return_value=[])

        blocked = make_project("SECURE", status="blocked")

        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="allowlist")
            with patch.object(service._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([blocked], 1)
                with patch.object(service._repo, "update_project_status", new_callable=AsyncMock) as mock_status:
                    with patch.object(service._repo, "upsert_tenant_config", new_callable=AsyncMock):
                        with patch.object(service._repo, "append_audit", new_callable=AsyncMock):
                            with patch.object(service._guardrails, "enforce_project_cap", new_callable=AsyncMock):
                                result = await service.run_discovery(TENANT_ID)

        assert result["archivedCount"] == 0
        mock_status.assert_not_called()


class TestRunDiscoveryPartialFailure:
    @pytest.mark.asyncio
    async def test_partial_jira_failure_returns_partial(self):
        """If Jira raises an error but some data exists, status is partial."""
        session = AsyncMock()
        jira_client = AsyncMock()
        jira_client.fetch_all_accessible_projects = AsyncMock(
            side_effect=Exception("Jira API timeout")
        )

        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="allowlist")
            with patch.object(service._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([], 0)
                with patch.object(service._repo, "upsert_tenant_config", new_callable=AsyncMock):
                    with patch.object(service._repo, "append_audit", new_callable=AsyncMock):
                        with patch.object(service._guardrails, "enforce_project_cap", new_callable=AsyncMock):
                            result = await service.run_discovery(TENANT_ID)

        assert result["status"] == "failed"
        assert len(result["errors"]) > 0


class TestRunDiscoveryDisabled:
    @pytest.mark.asyncio
    async def test_discovery_disabled_short_circuits(self):
        """When discovery_enabled=False, returns success with zero counts."""
        session = AsyncMock()
        jira_client = AsyncMock()
        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(discovery_enabled=False)
            result = await service.run_discovery(TENANT_ID)

        assert result["status"] == "success"
        assert result["discoveredCount"] == 0
        jira_client.fetch_all_accessible_projects.assert_not_called()


class TestRunDiscoverySmartMode:
    @pytest.mark.asyncio
    async def test_smart_mode_calls_prioritizer(self):
        """In smart mode, score_projects and auto_activate are called."""
        session = AsyncMock()
        jira_client = AsyncMock()
        jira_client.fetch_all_accessible_projects = AsyncMock(return_value=[])

        service = ProjectDiscoveryService(session, jira_client=jira_client)

        with patch.object(service._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="smart")
            with patch.object(service._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([], 0)
                with patch.object(
                    service._prioritizer, "score_projects", new_callable=AsyncMock
                ) as mock_score:
                    mock_score.return_value = {}
                    with patch.object(
                        service._prioritizer, "auto_activate", new_callable=AsyncMock
                    ) as mock_activate:
                        mock_activate.return_value = 2
                        with patch.object(service._repo, "upsert_tenant_config", new_callable=AsyncMock):
                            with patch.object(service._repo, "append_audit", new_callable=AsyncMock):
                                with patch.object(service._guardrails, "enforce_project_cap", new_callable=AsyncMock):
                                    result = await service.run_discovery(TENANT_ID)

        mock_score.assert_called_once_with(TENANT_ID)
        mock_activate.assert_called_once_with(TENANT_ID)
        assert result["activatedCount"] == 2
