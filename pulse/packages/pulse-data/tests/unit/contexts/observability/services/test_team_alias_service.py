"""FDD-OBS-001 PR 3.5 — team_alias_service unit tests.

Validates:
  - Normalization: lowercase + strip on vendor_team_value.
  - set_alias rejects unknown squad_key BEFORE DB write (delegates to SquadDirectory).
  - bulk_import rejects per-row (typos counted, not failing batch).
  - load_alias_map returns dict for inference consumption.
  - delete_alias returns False when row absent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.contexts.observability.services import team_alias_service
from src.contexts.observability.services.squad_directory import (
    InvalidSquadKeyError,
)
from src.contexts.observability.services.team_alias_service import (
    BulkImportResult,
    TeamAlias,
    bulk_import,
    delete_alias,
    list_aliases,
    load_alias_map,
    set_alias,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session_cm(execute_mock: AsyncMock) -> MagicMock:
    session = AsyncMock()
    session.execute = execute_mock
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _row(**kwargs) -> MagicMock:
    r = MagicMock()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


# ---------------------------------------------------------------------------
# Normalization (vendor_team_value lowercase + strip)
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_lowercase_and_strip(self):
        assert team_alias_service._normalize_vendor_team("  Agenda-FACIL  ") == "agenda-facil"

    def test_empty_returns_empty_after_strip(self):
        assert team_alias_service._normalize_vendor_team("   ") == ""
        assert team_alias_service._normalize_vendor_team("") == ""


# ---------------------------------------------------------------------------
# load_alias_map
# ---------------------------------------------------------------------------


class TestLoadAliasMap:
    @pytest.mark.asyncio
    async def test_returns_dict_of_pairs(self):
        result = MagicMock()
        result.all.return_value = [
            _row(vendor_team_value="agenda-facil", squad_key="FID"),
            _row(vendor_team_value="iazi", squad_key="IAZI"),
        ]
        execute = AsyncMock(return_value=result)

        with patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            map_ = await load_alias_map(_TENANT, "datadog")

        assert map_ == {"agenda-facil": "FID", "iazi": "IAZI"}

    @pytest.mark.asyncio
    async def test_empty_when_no_aliases(self):
        result = MagicMock()
        result.all.return_value = []
        execute = AsyncMock(return_value=result)

        with patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            map_ = await load_alias_map(_TENANT, "datadog")
        assert map_ == {}


# ---------------------------------------------------------------------------
# set_alias
# ---------------------------------------------------------------------------


class TestSetAlias:
    @pytest.mark.asyncio
    async def test_invalid_squad_raises_before_db(self):
        with patch(
            "src.contexts.observability.services.team_alias_service."
            "SquadDirectory.assert_valid_squad",
            new=AsyncMock(side_effect=InvalidSquadKeyError("GHOST")),
        ), patch.object(
            team_alias_service, "get_session",
        ) as session_mock:
            with pytest.raises(InvalidSquadKeyError):
                await set_alias(_TENANT, "datadog", "agenda-facil", "GHOST")
            session_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_vendor_team_rejected(self):
        with patch(
            "src.contexts.observability.services.team_alias_service."
            "SquadDirectory.assert_valid_squad",
            new=AsyncMock(),
        ):
            with pytest.raises(ValueError, match="empty"):
                await set_alias(_TENANT, "datadog", "   ", "FID")

    @pytest.mark.asyncio
    async def test_happy_path_normalizes_and_returns_row(self):
        now = datetime.now(timezone.utc)
        result = MagicMock()
        result.first.return_value = _row(
            vendor_team_value="agenda-facil",
            squad_key="FID",
            created_at=now,
            updated_at=now,
        )
        execute = AsyncMock(return_value=result)

        with patch(
            "src.contexts.observability.services.team_alias_service."
            "SquadDirectory.assert_valid_squad",
            new=AsyncMock(return_value=None),
        ), patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            alias = await set_alias(_TENANT, "datadog", "  Agenda-FACIL  ", "FID")

        params = execute.await_args.args[1]
        # Normalized to lowercase + stripped
        assert params["vendor_team"] == "agenda-facil"
        assert isinstance(alias, TeamAlias)
        assert alias.squad_key == "FID"


# ---------------------------------------------------------------------------
# delete_alias
# ---------------------------------------------------------------------------


class TestDeleteAlias:
    @pytest.mark.asyncio
    async def test_returns_true_when_deleted(self):
        result = MagicMock()
        result.first.return_value = _row(vendor_team_value="agenda-facil")
        execute = AsyncMock(return_value=result)
        with patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            assert await delete_alias(_TENANT, "datadog", "agenda-facil") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        result = MagicMock()
        result.first.return_value = None
        execute = AsyncMock(return_value=result)
        with patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            assert await delete_alias(_TENANT, "datadog", "missing") is False

    @pytest.mark.asyncio
    async def test_empty_input_returns_false_without_db(self):
        with patch.object(team_alias_service, "get_session") as session_mock:
            assert await delete_alias(_TENANT, "datadog", "  ") is False
            session_mock.assert_not_called()


# ---------------------------------------------------------------------------
# bulk_import
# ---------------------------------------------------------------------------


class TestBulkImport:
    @pytest.mark.asyncio
    async def test_rejects_invalid_squads_per_row(self):
        """Typos in squad_key get counted, not blowing up the batch."""
        execute = AsyncMock()
        execute.return_value = MagicMock()
        execute.return_value.first = MagicMock(return_value=_row(inserted=True))

        with patch(
            "src.contexts.observability.services.team_alias_service."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID", "OKM"})),
        ), patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            result = await bulk_import(
                _TENANT, "datadog",
                mappings=[
                    ("agenda-facil", "FID"),     # ok
                    ("iazi", "GHOST"),           # invalid squad
                    ("billing", "OKM"),          # ok
                ],
            )

        assert isinstance(result, BulkImportResult)
        assert result.total_submitted == 3
        assert result.rejected_invalid_squad == 1
        assert result.applied == 2
        assert execute.await_count == 2  # only valid rows hit the DB

    @pytest.mark.asyncio
    async def test_rejects_empty_per_row(self):
        execute = AsyncMock()
        execute.return_value = MagicMock()
        execute.return_value.first = MagicMock(return_value=_row(inserted=True))

        with patch(
            "src.contexts.observability.services.team_alias_service."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ), patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            result = await bulk_import(
                _TENANT, "datadog",
                mappings=[
                    ("", "FID"),                 # empty vendor
                    ("agenda-facil", "  "),       # empty squad
                    ("agenda-facil", "FID"),     # ok
                ],
            )

        assert result.rejected_empty == 2
        assert result.applied == 1

    @pytest.mark.asyncio
    async def test_inserted_vs_updated_count(self):
        """xmax=0 in RETURNING signals an INSERT (vs UPDATE)."""
        # First call: insert; second call: update (xmax != 0)
        results = []
        for inserted in (True, False):
            r = MagicMock()
            r.first = MagicMock(return_value=_row(inserted=inserted))
            results.append(r)
        execute = AsyncMock(side_effect=results)

        with patch(
            "src.contexts.observability.services.team_alias_service."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ), patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            result = await bulk_import(
                _TENANT, "datadog",
                mappings=[("a", "FID"), ("b", "FID")],
            )

        assert result.inserted == 1
        assert result.updated == 1


# ---------------------------------------------------------------------------
# list_aliases
# ---------------------------------------------------------------------------


class TestListAliases:
    @pytest.mark.asyncio
    async def test_returns_dataclasses_ordered(self):
        now = datetime.now(timezone.utc)
        result = MagicMock()
        result.all.return_value = [
            _row(vendor_team_value="a", squad_key="FID", created_at=now, updated_at=now),
            _row(vendor_team_value="b", squad_key="OKM", created_at=now, updated_at=now),
        ]
        execute = AsyncMock(return_value=result)

        with patch.object(
            team_alias_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            aliases = await list_aliases(_TENANT, "datadog")

        assert len(aliases) == 2
        assert all(isinstance(a, TeamAlias) for a in aliases)
        sql = str(execute.await_args.args[0])
        assert "ORDER BY vendor_team_value" in sql
