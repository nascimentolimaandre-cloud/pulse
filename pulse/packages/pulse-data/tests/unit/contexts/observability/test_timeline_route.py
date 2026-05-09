"""FDD-OBS-001 PR 4b — timeline route tests.

Validates:
  - GET /obs/timeline?squad_key=X → 200 with squad-scoped timeline.
  - GET /obs/timeline?service=Y → 200 with service-scoped timeline.
  - 400 when neither squad_key nor service is given.
  - 400 when BOTH are given.
  - Anti-surveillance: response NEVER contains `author` field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.contexts.observability.services.timeline_service import (
    DeployMarkerDTO,
    HealthBucket,
    TimelineResponse,
)
from src.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _sample_response(scope: str = "squad", with_data: bool = True) -> TimelineResponse:
    ts = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
    return TimelineResponse(
        scope=scope,
        squad_key="FID" if scope == "squad" else None,
        service="checkout" if scope == "service" else None,
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 8, tzinfo=timezone.utc),
        buckets=[
            HealthBucket(
                hour_bucket=ts, severity=2.0, samples_count=3,
                metric="monitor_health",
                service="checkout" if scope == "service" else None,
            ),
        ] if with_data else [],
        deploys=[
            DeployMarkerDTO(
                deployed_at=ts,
                repo="wm/checkout",
                environment="prod",
                sha="abc123",
                is_failure=False,
                url="https://github.com/wm/checkout/actions/runs/1",
            ),
        ] if with_data else [],
        services_in_squad=10 if scope == "squad" else 0,
        has_data=with_data,
    )


class TestParamValidation:
    def test_400_when_neither_squad_nor_service(self, client):
        response = client.get("/data/v1/obs/timeline")
        assert response.status_code == 400

    def test_400_when_both_squad_and_service(self, client):
        response = client.get(
            "/data/v1/obs/timeline?squad_key=FID&service=checkout",
        )
        assert response.status_code == 400


class TestSquadScope:
    def test_squad_returns_aggregated_timeline(self, client):
        with patch(
            "src.contexts.observability.routes.timeline_service.get_squad_timeline",
            new=AsyncMock(return_value=_sample_response(scope="squad")),
        ) as mock:
            response = client.get("/data/v1/obs/timeline?squad_key=FID")

        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "squad"
        assert body["squad_key"] == "FID"
        assert body["service"] is None
        assert body["has_data"] is True
        assert len(body["buckets"]) == 1
        assert len(body["deploys"]) == 1
        mock.assert_awaited_once()


class TestServiceScope:
    def test_service_returns_drilldown_timeline(self, client):
        with patch(
            "src.contexts.observability.routes.timeline_service.get_service_timeline",
            new=AsyncMock(return_value=_sample_response(scope="service")),
        ):
            response = client.get("/data/v1/obs/timeline?service=checkout")

        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "service"
        assert body["service"] == "checkout"
        assert body["squad_key"] is None


class TestAntiSurveillance:
    def test_response_does_not_carry_author_field(self, client):
        """Defense in depth: even if a future regression accidentally
        sneaks an `author` field into TimelineDeployMarker, the JSON
        response must not surface it.

        Verified by inspecting the response shape — the Pydantic model
        whitelists fields, so 'author' would have to be added intentionally."""
        with patch(
            "src.contexts.observability.routes.timeline_service.get_squad_timeline",
            new=AsyncMock(return_value=_sample_response(scope="squad")),
        ):
            response = client.get("/data/v1/obs/timeline?squad_key=FID")

        body = response.json()
        for deploy in body["deploys"]:
            assert "author" not in deploy, (
                "Deploy markers must NEVER include `author` "
                "(ADR-025 anti-surveillance)"
            )

    def test_squad_key_value_does_not_leak_via_error(self):
        """When the timeline service raises, FastAPI's default 500
        response must not echo back the user-supplied squad_key. Use
        `raise_app_exceptions=False` so we observe the real HTTP
        response (TestClient by default re-raises in tests)."""
        with TestClient(app, raise_server_exceptions=False) as test_client, patch(
            "src.contexts.observability.routes.timeline_service.get_squad_timeline",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = test_client.get(
                "/data/v1/obs/timeline?squad_key=ARBITRARY-INPUT-XYZ",
            )

        assert response.status_code == 500
        # The error response body must not echo the squad_key value
        # back to the caller — that protects against reflected-XSS
        # patterns when the response is shown unsanitized in a UI.
        assert "ARBITRARY-INPUT-XYZ" not in response.text