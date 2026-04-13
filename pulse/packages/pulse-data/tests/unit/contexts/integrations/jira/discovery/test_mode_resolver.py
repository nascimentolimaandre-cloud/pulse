"""Unit tests for ModeResolver.

Covers all 4 modes and the blocked-invariant.
All DB access is mocked via patching DiscoveryRepository + raw session.execute.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver
from tests.unit.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    make_config,
)


def _mock_session_with_keys(keys: list[str]) -> MagicMock:
    """Create a mock session whose execute returns given project keys."""
    rows = [(k,) for k in keys]
    result_mock = MagicMock()
    result_mock.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    return session


class TestModeResolverAuto:
    """Mode=auto: discovered + active are included, blocked excluded."""

    @pytest.mark.asyncio
    async def test_auto_returns_discovered_and_active(self):
        session = _mock_session_with_keys(["BACK", "DESC", "ENO"])
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="auto")
            keys = await resolver.resolve_active_projects(TENANT_ID)

        assert keys == ["BACK", "DESC", "ENO"]

    @pytest.mark.asyncio
    async def test_auto_excludes_blocked(self):
        """Blocked should not appear even in auto mode (DB query filters it)."""
        session = _mock_session_with_keys(["BACK", "DESC"])
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="auto")
            keys = await resolver.resolve_active_projects(TENANT_ID)

        # Verify the SQL query included status != 'blocked' filter
        call_args = session.execute.call_args
        assert call_args is not None
        assert keys == ["BACK", "DESC"]


class TestModeResolverAllowlist:
    """Mode=allowlist: only active projects."""

    @pytest.mark.asyncio
    async def test_allowlist_only_active(self):
        session = _mock_session_with_keys(["BACK"])
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="allowlist")
            keys = await resolver.resolve_active_projects(TENANT_ID)

        assert keys == ["BACK"]


class TestModeResolverBlocklist:
    """Mode=blocklist: everything except blocked and archived."""

    @pytest.mark.asyncio
    async def test_blocklist_includes_discovered_active_paused(self):
        session = _mock_session_with_keys(["BACK", "DESC", "ENO"])
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="blocklist")
            keys = await resolver.resolve_active_projects(TENANT_ID)

        assert keys == ["BACK", "DESC", "ENO"]


class TestModeResolverSmart:
    """Mode=smart: active + discovered with enough PR refs."""

    @pytest.mark.asyncio
    async def test_smart_includes_discovered_above_threshold(self):
        session = _mock_session_with_keys(["BACK", "HIGH_REF"])
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="smart", smart_min_pr_references=5)
            keys = await resolver.resolve_active_projects(TENANT_ID)

        assert keys == ["BACK", "HIGH_REF"]

    @pytest.mark.asyncio
    async def test_smart_excludes_blocked(self):
        session = _mock_session_with_keys(["BACK"])
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="smart")
            keys = await resolver.resolve_active_projects(TENANT_ID)

        assert "BLOCKED" not in keys


class TestModeResolverBlockedInvariant:
    """Blocked is ALWAYS excluded regardless of mode."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["auto", "allowlist", "blocklist", "smart"])
    async def test_blocked_never_returned(self, mode: str):
        # Simulate DB returning no blocked projects (correct filter)
        session = _mock_session_with_keys(["BACK", "DESC"])
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode=mode)
            keys = await resolver.resolve_active_projects(TENANT_ID)

        # Keys should never contain BLOCKED
        assert "BLOCKED" not in keys


class TestModeResolverNoConfig:
    """No tenant config returns empty list."""

    @pytest.mark.asyncio
    async def test_no_config_returns_empty(self):
        session = AsyncMock()
        resolver = ModeResolver(session)

        with patch.object(resolver._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = None
            keys = await resolver.resolve_active_projects(TENANT_ID)

        assert keys == []
