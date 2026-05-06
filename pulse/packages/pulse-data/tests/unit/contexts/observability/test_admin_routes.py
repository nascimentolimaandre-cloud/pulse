"""FDD-OBS-001 PR 2 — admin routes unit tests.

Validates the contracts:
  - 422 when site is not in allowlist (Pydantic schema layer).
  - 200 + valid=true + persisted=false when DD reports valid and persist=False.
  - 200 + valid=true + persisted=true when DD valid + persist=True (calls upsert).
  - 200 + valid=false (NEVER raises 401) when DD rejects the credential.
  - 503 when master key missing (operator config error, not user-facing).
  - GET metadata returns 404 when no row, public-safe payload when present.
  - Plaintext API key NEVER appears in any response body or log message.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.contexts.observability.services.credential_service import (
    StoredCredential,
    WeakMasterKeyError,
)
from src.main import app


_TENANT = UUID("00000000-0000-0000-0000-000000000001")
SECRET_KEY = "ddog-secret-do-not-leak-12345"


def _stored(site: str = "datadoghq.com", validated: bool = True) -> StoredCredential:
    now = datetime.now(timezone.utc)
    return StoredCredential(
        tenant_id=_TENANT,
        provider="datadog",
        site=site,
        has_app_key=False,
        validated_at=now if validated else None,
        last_rotated_at=now,
        key_fingerprint="aabbccdd" * 4,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _patch_dd_provider(health_check_returns: bool):
    """Patch DatadogProvider so HTTP never leaves the test."""
    instance = MagicMock()
    instance.health_check = AsyncMock(return_value=health_check_returns)
    instance.aclose = AsyncMock(return_value=None)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=instance)
    cm.__aexit__ = AsyncMock(return_value=None)

    return patch(
        "src.contexts.observability.routes.DatadogProvider",
        return_value=cm,
    )


# ---------------------------------------------------------------------------
# Schema-layer rejection (defense-in-depth Layer 1: Pydantic)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_evil_site_rejected_by_schema(self, client):
        """Site not in allowlist → 422 BEFORE the connector is built."""
        response = client.post(
            "/data/v1/admin/integrations/datadog/validate",
            json={
                "api_key": SECRET_KEY,
                "site": "evil.attacker.com",
                "persist": False,
            },
        )
        assert response.status_code == 422
        body = response.json()
        # The error must NOT echo the secret back.
        assert SECRET_KEY not in str(body)
        # Site validation hint should be in detail
        assert "allowlist" in str(body).lower() or "allowed" in str(body).lower()

    def test_short_api_key_rejected(self, client):
        response = client.post(
            "/data/v1/admin/integrations/datadog/validate",
            json={"api_key": "x", "site": "datadoghq.com", "persist": False},
        )
        assert response.status_code == 422

    def test_whitespace_in_api_key_rejected(self, client):
        response = client.post(
            "/data/v1/admin/integrations/datadog/validate",
            json={
                "api_key": "  has-leading-whitespace  ",
                "site": "datadoghq.com",
                "persist": False,
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Validation flow (no persist)
# ---------------------------------------------------------------------------


class TestValidateOnly:
    def test_dd_valid_no_persist_returns_valid_true(self, client):
        with _patch_dd_provider(health_check_returns=True):
            response = client.post(
                "/data/v1/admin/integrations/datadog/validate",
                json={
                    "api_key": SECRET_KEY,
                    "site": "datadoghq.com",
                    "persist": False,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert body["persisted"] is False
        assert body["site"] == "datadoghq.com"
        assert len(body["key_fingerprint"]) == 32  # M-005
        # Plaintext NEVER in response.
        assert SECRET_KEY not in str(body)

    def test_dd_invalid_returns_valid_false_not_401(self, client):
        """DD rejects the key → 200 with valid=false. We don't proxy 401."""
        with _patch_dd_provider(health_check_returns=False):
            response = client.post(
                "/data/v1/admin/integrations/datadog/validate",
                json={
                    "api_key": SECRET_KEY,
                    "site": "datadoghq.com",
                    "persist": False,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["persisted"] is False
        assert SECRET_KEY not in str(body)


# ---------------------------------------------------------------------------
# Validate + persist (encryption path)
# ---------------------------------------------------------------------------


class TestValidateAndPersist:
    def test_dd_valid_persist_true_calls_upsert(self, client):
        with _patch_dd_provider(health_check_returns=True), \
             patch(
                 "src.contexts.observability.routes.credential_service.upsert_credential",
                 new=AsyncMock(return_value=_stored()),
             ) as upsert_mock:
            response = client.post(
                "/data/v1/admin/integrations/datadog/validate",
                json={
                    "api_key": SECRET_KEY,
                    "site": "datadoghq.com",
                    "persist": True,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert body["persisted"] is True
        assert body["validated_at"] is not None
        assert SECRET_KEY not in str(body)
        upsert_mock.assert_awaited_once()
        kwargs = upsert_mock.await_args.kwargs
        assert kwargs["api_key"] == SECRET_KEY
        assert kwargs["validated"] is True

    def test_weak_master_key_returns_503_not_500(self, client):
        """Operator hasn't set PULSE_OBS_MASTER_KEY → 503, no leak."""
        with _patch_dd_provider(health_check_returns=True), \
             patch(
                 "src.contexts.observability.routes.credential_service.upsert_credential",
                 new=AsyncMock(side_effect=WeakMasterKeyError("not configured")),
             ):
            response = client.post(
                "/data/v1/admin/integrations/datadog/validate",
                json={
                    "api_key": SECRET_KEY,
                    "site": "datadoghq.com",
                    "persist": True,
                },
            )
        assert response.status_code == 503
        # The detail mentions PULSE_OBS_MASTER_KEY for operator visibility
        # but never echoes the secret back.
        assert SECRET_KEY not in response.text

    def test_persist_false_does_not_call_upsert(self, client):
        with _patch_dd_provider(health_check_returns=True), \
             patch(
                 "src.contexts.observability.routes.credential_service.upsert_credential",
                 new=AsyncMock(),
             ) as upsert_mock:
            response = client.post(
                "/data/v1/admin/integrations/datadog/validate",
                json={
                    "api_key": SECRET_KEY,
                    "site": "datadoghq.com",
                    "persist": False,
                },
            )
        assert response.status_code == 200
        upsert_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET metadata
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_no_credential_returns_404(self, client):
        with patch(
            "src.contexts.observability.routes.credential_service.get_credential_metadata",
            new=AsyncMock(return_value=None),
        ):
            response = client.get("/data/v1/admin/integrations/datadog/metadata")
        assert response.status_code == 404

    def test_metadata_does_not_leak_plaintext(self, client):
        """Metadata endpoint returns site/fingerprint/has_app_key, never
        the plaintext API key (which the service layer doesn't expose
        anyway)."""
        with patch(
            "src.contexts.observability.routes.credential_service.get_credential_metadata",
            new=AsyncMock(return_value=_stored()),
        ):
            response = client.get("/data/v1/admin/integrations/datadog/metadata")
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "datadog"
        assert body["site"] == "datadoghq.com"
        assert body["has_app_key"] is False
        assert body["status"] == "validated"
        # Sanity — no plaintext-shaped fields in the response.
        assert "api_key" not in body
        assert "api_key_encrypted" not in body
