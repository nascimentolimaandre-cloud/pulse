"""FDD-OBS-001 PR 3 — provider_factory unit tests.

Validates:
  - UnknownProviderError raised for unmapped provider_id.
  - ProviderNotConfiguredError raised when no credential row.
  - Happy path constructs DatadogProvider with site + keys from credential service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.connectors.observability.datadog_connector import DatadogProvider
from src.contexts.observability.services import provider_factory
from src.contexts.observability.services.credential_service import StoredCredential
from src.contexts.observability.services.provider_factory import (
    ProviderNotConfiguredError,
    UnknownProviderError,
    build_for_tenant,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _stored() -> StoredCredential:
    now = datetime.now(timezone.utc)
    return StoredCredential(
        tenant_id=_TENANT,
        provider="datadog",
        site="datadoghq.com",
        has_app_key=True,
        validated_at=now,
        last_rotated_at=now,
        key_fingerprint="aabbccdd" * 4,
    )


class TestUnknownProvider:
    @pytest.mark.asyncio
    async def test_unknown_id_raises(self):
        with pytest.raises(UnknownProviderError, match="newrelic"):
            await build_for_tenant(_TENANT, "newrelic")


class TestNotConfigured:
    @pytest.mark.asyncio
    async def test_no_credential_row_raises(self):
        with patch.object(
            provider_factory.credential_service, "get_credential_keys",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(ProviderNotConfiguredError, match="No credential"):
                await build_for_tenant(_TENANT, "datadog")

    @pytest.mark.asyncio
    async def test_keys_present_but_metadata_missing_raises(self):
        """Defensive — if keys SELECT succeeds but metadata SELECT
        returns None (impossible in normal flow), don't construct
        provider with site=None."""
        with patch.object(
            provider_factory.credential_service, "get_credential_keys",
            new=AsyncMock(return_value=("api", "app")),
        ), patch.object(
            provider_factory.credential_service, "get_credential_metadata",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(ProviderNotConfiguredError, match="metadata"):
                await build_for_tenant(_TENANT, "datadog")


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_datadog_provider_with_site_and_keys(self):
        with patch.object(
            provider_factory.credential_service, "get_credential_keys",
            new=AsyncMock(return_value=("dd-api-key", "dd-app-key")),
        ), patch.object(
            provider_factory.credential_service, "get_credential_metadata",
            new=AsyncMock(return_value=_stored()),
        ):
            adapter = await build_for_tenant(_TENANT, "datadog")

        assert isinstance(adapter, DatadogProvider)
        assert adapter.provider_id == "datadog"
        # Sanity — site went into the base_url
        assert adapter._site == "datadoghq.com"
        await adapter.aclose()
