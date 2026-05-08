"""FDD-OBS-001 PR 3 — admin ownership routes tests.

Validates:
  - POST /sync calls provider_factory + ownership_inference, returns summary.
  - POST /sync returns 409 if no credential, 502 on provider error.
  - PUT /override 422 on invalid squad, 404 on missing service.
  - PUT /override null clears, non-null sets.
  - GET / returns coverage_pct + rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.connectors.observability.datadog_connector import DatadogConnectorError
from src.contexts.observability.services.ownership_inference import (
    InferenceResult,
    OwnershipRow,
)
from src.contexts.observability.services.provider_factory import (
    ProviderNotConfiguredError,
)
from src.contexts.observability.services.squad_directory import (
    InvalidSquadKeyError,
)
from src.main import app


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _row(
    service_external_id: str = "svc-1",
    service_name: str = "checkout",
    inferred: str | None = "FID",
    override: str | None = None,
    qualified: bool = True,
) -> OwnershipRow:
    effective = override or inferred
    return OwnershipRow(
        service_external_id=service_external_id,
        service_name=service_name,
        repo_url=None,
        inferred_squad_key=inferred,
        inferred_confidence="tag" if inferred else "none",
        override_squad_key=override,
        effective_squad_key=effective,
        last_inference_at=datetime.now(timezone.utc),
        is_qualified_squad=qualified,
    )


def _patch_provider_cm():
    """Return a patch context for `routes.provider_factory.build_for_tenant`
    that yields a MagicMock async-context-managed adapter."""
    adapter = MagicMock()
    adapter.aclose = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=adapter)
    cm.__aexit__ = AsyncMock(return_value=None)
    # build_for_tenant returns the adapter; the route uses `async with adapter:`
    return adapter, cm


# ---------------------------------------------------------------------------
# POST /sync
# ---------------------------------------------------------------------------


class TestSync:
    def test_happy_path_returns_summary(self, client):
        adapter, _ = _patch_provider_cm()
        result = InferenceResult(
            services_seen=3, inferred_with_tag=2, inferred_none=1,
            unchanged=0, duration_ms=42,
        )

        with patch(
            "src.contexts.observability.routes.provider_factory.build_for_tenant",
            new=AsyncMock(return_value=adapter),
        ), patch(
            "src.contexts.observability.routes.ownership_inference.sync_tier1_inference",
            new=AsyncMock(return_value=result),
        ):
            response = client.post(
                "/data/v1/admin/integrations/datadog/ownership/sync",
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["services_seen"] == 3
        assert body["inferred_with_tag"] == 2
        assert body["inferred_none"] == 1
        assert body["duration_ms"] == 42

    def test_no_credential_returns_409(self, client):
        with patch(
            "src.contexts.observability.routes.provider_factory.build_for_tenant",
            new=AsyncMock(side_effect=ProviderNotConfiguredError("no row")),
        ):
            response = client.post(
                "/data/v1/admin/integrations/datadog/ownership/sync",
            )
        assert response.status_code == 409

    def test_provider_error_returns_502(self, client):
        adapter, _ = _patch_provider_cm()
        with patch(
            "src.contexts.observability.routes.provider_factory.build_for_tenant",
            new=AsyncMock(return_value=adapter),
        ), patch(
            "src.contexts.observability.routes.ownership_inference.sync_tier1_inference",
            new=AsyncMock(side_effect=DatadogConnectorError("DD 500")),
        ):
            response = client.post(
                "/data/v1/admin/integrations/datadog/ownership/sync",
            )
        assert response.status_code == 502


# ---------------------------------------------------------------------------
# PUT /override
# ---------------------------------------------------------------------------


class TestOverride:
    def test_set_override_returns_updated_row(self, client):
        with patch(
            "src.contexts.observability.routes.ownership_inference.set_override",
            new=AsyncMock(return_value=_row(override="FID")),
        ):
            response = client.put(
                "/data/v1/admin/integrations/datadog/ownership/svc-1/override",
                json={"squad_key": "FID"},
            )
        assert response.status_code == 200
        assert response.json()["override_squad_key"] == "FID"
        assert response.json()["effective_squad_key"] == "FID"

    def test_clear_override_with_null(self, client):
        with patch(
            "src.contexts.observability.routes.ownership_inference.clear_override",
            new=AsyncMock(return_value=_row(override=None, inferred="FID")),
        ) as clear_mock:
            response = client.put(
                "/data/v1/admin/integrations/datadog/ownership/svc-1/override",
                json={"squad_key": None},
            )
        assert response.status_code == 200
        clear_mock.assert_awaited_once()
        body = response.json()
        assert body["override_squad_key"] is None
        assert body["effective_squad_key"] == "FID"

    def test_invalid_squad_returns_422(self, client):
        with patch(
            "src.contexts.observability.routes.ownership_inference.set_override",
            new=AsyncMock(side_effect=InvalidSquadKeyError("GHOST")),
        ):
            response = client.put(
                "/data/v1/admin/integrations/datadog/ownership/svc-1/override",
                json={"squad_key": "GHOST"},
            )
        assert response.status_code == 422

    def test_unknown_service_returns_404(self, client):
        with patch(
            "src.contexts.observability.routes.ownership_inference.set_override",
            new=AsyncMock(side_effect=LookupError("not found")),
        ):
            response = client.put(
                "/data/v1/admin/integrations/datadog/ownership/missing/override",
                json={"squad_key": "FID"},
            )
        assert response.status_code == 404

    def test_empty_string_squad_rejected_by_pydantic(self, client):
        response = client.put(
            "/data/v1/admin/integrations/datadog/ownership/svc-1/override",
            json={"squad_key": "  "},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


class TestList:
    def test_empty_returns_zero_coverage(self, client):
        with patch(
            "src.contexts.observability.routes.ownership_inference.list_for_tenant",
            new=AsyncMock(return_value=[]),
        ):
            response = client.get(
                "/data/v1/admin/integrations/datadog/ownership",
            )
        assert response.status_code == 200
        body = response.json()
        assert body["services"] == []
        assert body["coverage_pct"] == 0.0

    def test_coverage_pct_computed(self, client):
        rows = [
            _row("a", "checkout", inferred="FID", qualified=True),
            _row("b", "billing", inferred="OKM", qualified=True),
            _row("c", "ghost", inferred="GHOST", qualified=False),
            _row("d", "orphan", inferred=None, qualified=False),
        ]
        with patch(
            "src.contexts.observability.routes.ownership_inference.list_for_tenant",
            new=AsyncMock(return_value=rows),
        ):
            response = client.get(
                "/data/v1/admin/integrations/datadog/ownership",
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body["services"]) == 4
        # 2 of 4 qualified → 0.5
        assert body["coverage_pct"] == 0.5
