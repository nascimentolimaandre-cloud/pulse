"""FDD-OBS-001 PR 3 — SquadDirectory unit tests.

Validates:
  - list_qualified_squads queries jira_project_catalog with the right filter.
  - is_valid_squad / assert_valid_squad short-circuit on empty input.
  - InvalidSquadKeyError raised on miss.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.contexts.observability.services import squad_directory
from src.contexts.observability.services.squad_directory import (
    InvalidSquadKeyError,
    SquadDirectory,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session_cm(execute_mock: AsyncMock) -> MagicMock:
    session = AsyncMock()
    session.execute = execute_mock
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _row(project_key: str) -> MagicMock:
    r = MagicMock()
    r.project_key = project_key
    return r


class TestListQualifiedSquads:
    @pytest.mark.asyncio
    async def test_returns_distinct_set(self):
        """Each project_key should appear once even if duplicated in result."""
        result = MagicMock()
        result.all.return_value = [_row("FID"), _row("PTURB"), _row("OKM")]
        execute = AsyncMock(return_value=result)

        with patch.object(
            squad_directory, "get_session", return_value=_mock_session_cm(execute),
        ):
            squads = await SquadDirectory.list_qualified_squads(_TENANT)

        assert squads == frozenset({"FID", "PTURB", "OKM"})

    @pytest.mark.asyncio
    async def test_empty_when_no_qualified_projects(self):
        result = MagicMock()
        result.all.return_value = []
        execute = AsyncMock(return_value=result)
        with patch.object(
            squad_directory, "get_session", return_value=_mock_session_cm(execute),
        ):
            squads = await SquadDirectory.list_qualified_squads(_TENANT)
        assert squads == frozenset()

    @pytest.mark.asyncio
    async def test_query_filters_active_and_excludes_excluded(self):
        """SQL must filter status IN ('active','discovered') AND not excluded."""
        result = MagicMock()
        result.all.return_value = []
        execute = AsyncMock(return_value=result)
        with patch.object(
            squad_directory, "get_session", return_value=_mock_session_cm(execute),
        ):
            await SquadDirectory.list_qualified_squads(_TENANT)
        sql = str(execute.call_args.args[0])
        assert "status IN ('active', 'discovered')" in sql
        assert "qualification_override" in sql
        assert "'excluded'" in sql


class TestIsValidSquad:
    @pytest.mark.asyncio
    async def test_empty_returns_false_without_querying(self):
        with patch.object(
            squad_directory.SquadDirectory, "list_qualified_squads",
            new=AsyncMock(),
        ) as list_mock:
            assert await SquadDirectory.is_valid_squad(_TENANT, "") is False
        list_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_in_set_returns_true(self):
        with patch.object(
            squad_directory.SquadDirectory, "list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID", "OKM"})),
        ):
            assert await SquadDirectory.is_valid_squad(_TENANT, "FID") is True

    @pytest.mark.asyncio
    async def test_not_in_set_returns_false(self):
        with patch.object(
            squad_directory.SquadDirectory, "list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            assert await SquadDirectory.is_valid_squad(_TENANT, "GHOST") is False


class TestAssertValidSquad:
    @pytest.mark.asyncio
    async def test_raises_on_invalid(self):
        with patch.object(
            squad_directory.SquadDirectory, "list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            with pytest.raises(InvalidSquadKeyError, match="GHOST"):
                await SquadDirectory.assert_valid_squad(_TENANT, "GHOST")

    @pytest.mark.asyncio
    async def test_passes_on_valid(self):
        with patch.object(
            squad_directory.SquadDirectory, "list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            # Returns None (no exception) on success.
            assert await SquadDirectory.assert_valid_squad(_TENANT, "FID") is None
