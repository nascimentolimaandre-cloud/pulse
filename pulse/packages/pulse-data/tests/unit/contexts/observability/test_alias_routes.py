"""FDD-OBS-001 PR 3.5 — alias admin routes tests.

Validates:
  - GET /aliases returns list + total.
  - PUT 422 on InvalidSquadKey, 400 on path/body mismatch.
  - DELETE 204 on success, 404 on miss.
  - POST /import returns counts; rejects > 2000 (Pydantic enforced).
  - GET /suggestions returns distinct unaliased vendor_teams.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.contexts.observability.services.squad_directory import (
    InvalidSquadKeyError,
)
from src.contexts.observability.services.team_alias_service import (
    BulkImportResult,
    TeamAlias,
)
from src.main import app


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _alias(vendor: str = "agenda-facil", squad: str = "FID") -> TeamAlias:
    now = datetime.now(timezone.utc)
    return TeamAlias(
        vendor_team_value=vendor,
        squad_key=squad,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# GET /aliases
# ---------------------------------------------------------------------------


class TestList:
    def test_returns_aliases_and_total(self, client):
        with patch(
            "src.contexts.observability.routes.team_alias_service.list_aliases",
            new=AsyncMock(return_value=[
                _alias("agenda-facil", "FID"),
                _alias("iazi", "IAZI"),
            ]),
        ):
            response = client.get("/data/v1/admin/integrations/datadog/aliases")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["aliases"][0]["vendor_team_value"] == "agenda-facil"
        assert body["aliases"][0]["squad_key"] == "FID"


# ---------------------------------------------------------------------------
# PUT /aliases/{vendor_team}
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_happy_path(self, client):
        with patch(
            "src.contexts.observability.routes.team_alias_service.set_alias",
            new=AsyncMock(return_value=_alias()),
        ):
            response = client.put(
                "/data/v1/admin/integrations/datadog/aliases/agenda-facil",
                json={"vendor_team_value": "agenda-facil", "squad_key": "FID"},
            )
        assert response.status_code == 200
        assert response.json()["squad_key"] == "FID"

    def test_path_body_mismatch_returns_400(self, client):
        response = client.put(
            "/data/v1/admin/integrations/datadog/aliases/agenda-facil",
            json={"vendor_team_value": "iazi", "squad_key": "FID"},
        )
        assert response.status_code == 400

    def test_path_body_match_case_insensitive(self, client):
        """`Agenda-FACIL` in body should match `agenda-facil` in path —
        case-insensitive comparison; service normalizes anyway."""
        with patch(
            "src.contexts.observability.routes.team_alias_service.set_alias",
            new=AsyncMock(return_value=_alias()),
        ):
            response = client.put(
                "/data/v1/admin/integrations/datadog/aliases/agenda-facil",
                json={"vendor_team_value": "Agenda-FACIL", "squad_key": "FID"},
            )
        assert response.status_code == 200

    def test_invalid_squad_returns_422(self, client):
        with patch(
            "src.contexts.observability.routes.team_alias_service.set_alias",
            new=AsyncMock(side_effect=InvalidSquadKeyError("GHOST")),
        ):
            response = client.put(
                "/data/v1/admin/integrations/datadog/aliases/agenda-facil",
                json={"vendor_team_value": "agenda-facil", "squad_key": "GHOST"},
            )
        assert response.status_code == 422

    def test_empty_squad_rejected_by_pydantic(self, client):
        response = client.put(
            "/data/v1/admin/integrations/datadog/aliases/agenda-facil",
            json={"vendor_team_value": "agenda-facil", "squad_key": "  "},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /aliases/{vendor_team}
# ---------------------------------------------------------------------------


class TestDelete:
    def test_204_on_success(self, client):
        with patch(
            "src.contexts.observability.routes.team_alias_service.delete_alias",
            new=AsyncMock(return_value=True),
        ):
            response = client.delete(
                "/data/v1/admin/integrations/datadog/aliases/agenda-facil",
            )
        assert response.status_code == 204

    def test_404_when_not_found(self, client):
        with patch(
            "src.contexts.observability.routes.team_alias_service.delete_alias",
            new=AsyncMock(return_value=False),
        ):
            response = client.delete(
                "/data/v1/admin/integrations/datadog/aliases/missing",
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /aliases/import
# ---------------------------------------------------------------------------


class TestBulkImport:
    def test_returns_import_summary(self, client):
        result = BulkImportResult(
            inserted=2, updated=0,
            rejected_invalid_squad=1, rejected_empty=0,
            total_submitted=3,
        )
        with patch(
            "src.contexts.observability.routes.team_alias_service.bulk_import",
            new=AsyncMock(return_value=result),
        ):
            response = client.post(
                "/data/v1/admin/integrations/datadog/aliases/import",
                json={
                    "mappings": [
                        {"vendor_team_value": "agenda-facil", "squad_key": "FID"},
                        {"vendor_team_value": "iazi", "squad_key": "OKM"},
                        {"vendor_team_value": "billing", "squad_key": "GHOST"},
                    ],
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["inserted"] == 2
        assert body["rejected_invalid_squad"] == 1
        assert body["total_submitted"] == 3

    def test_rejects_more_than_2000_mappings(self, client):
        """Pydantic max_length=2000 enforced as the hard cap."""
        big = [
            {"vendor_team_value": f"team-{i}", "squad_key": "FID"}
            for i in range(2001)
        ]
        response = client.post(
            "/data/v1/admin/integrations/datadog/aliases/import",
            json={"mappings": big},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /aliases/suggestions
# ---------------------------------------------------------------------------


class TestSuggestions:
    def test_returns_distinct_unaliased(self, client):
        with patch(
            "src.contexts.observability.routes.team_alias_service.list_unaliased_vendor_teams",
            new=AsyncMock(return_value=["agenda-facil", "iazi", "marketplace"]),
        ):
            response = client.get(
                "/data/v1/admin/integrations/datadog/aliases/suggestions",
            )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert "agenda-facil" in body["vendor_teams"]
