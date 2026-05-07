"""FDD-OBS-001 PR 3 — observability provider factory.

`build_for_tenant(tenant_id, provider_id)` constructs a concrete
`ObservabilityProvider` (today: `DatadogProvider`) wired to the
encrypted credentials stored for the tenant.

The factory lives in the BC (`contexts/observability/`) — NOT in
`connectors/` — because it depends on `credential_service`, which is
internal to this BC. Connectors (`connectors/observability/`) stay pure
infra: HTTP + DSL translation, no DB awareness.

PR 4 (rollup worker) will reuse this factory unchanged — same
construction path for every per-tenant provider call.
"""

from __future__ import annotations

import logging
from uuid import UUID

from src.connectors.observability.base import ObservabilityProvider
from src.connectors.observability.datadog_connector import DatadogProvider
from src.contexts.observability.services import credential_service

logger = logging.getLogger(__name__)


class ProviderNotConfiguredError(LookupError):
    """Raised when no credential row exists for (tenant, provider)."""


class UnknownProviderError(ValueError):
    """Raised when the requested `provider_id` has no adapter mapped."""


# Provider id → adapter constructor. Add NewRelic / Grafana here when
# the adapters land. Mapping is module-level (not class) so the factory
# stays a thin functional surface.
_PROVIDER_ADAPTERS: dict[str, type] = {
    "datadog": DatadogProvider,
}


async def build_for_tenant(
    tenant_id: UUID,
    provider_id: str,
) -> ObservabilityProvider:
    """Return a configured `ObservabilityProvider` for (tenant, provider).

    Reads the encrypted credential via `credential_service` (decrypts
    inline through pgcrypto, plaintext lives in memory for the duration
    of the caller's request). Reads metadata to recover `site` (the
    adapter needs it to pin `https://api.<site>` as the base URL).

    Caller is responsible for `aclose()`-ing the returned provider
    (or using it as `async with ...`). The factory does NOT manage
    lifetime — that's per-call, scoped to the request that needs it.

    Raises:
      `UnknownProviderError`        — provider_id has no adapter.
      `ProviderNotConfiguredError`  — tenant has no credential.
    """
    adapter_cls = _PROVIDER_ADAPTERS.get(provider_id)
    if adapter_cls is None:
        raise UnknownProviderError(
            f"provider_id={provider_id!r} has no adapter. "
            f"Configured: {sorted(_PROVIDER_ADAPTERS.keys())}"
        )

    keys = await credential_service.get_credential_keys(tenant_id, provider_id)
    if keys is None:
        raise ProviderNotConfiguredError(
            f"No credential configured for tenant={tenant_id} provider={provider_id!r}. "
            f"POST /admin/integrations/{provider_id}/validate?persist=true first."
        )
    api_key, app_key = keys

    metadata = await credential_service.get_credential_metadata(tenant_id, provider_id)
    if metadata is None:
        # Should be impossible — keys row exists but metadata SELECT
        # returned None. Defensive raise so the caller never builds
        # a provider with `site=None`.
        raise ProviderNotConfiguredError(
            f"Credential row exists but metadata read failed for "
            f"tenant={tenant_id} provider={provider_id!r}."
        )

    logger.info(
        "[obs-factory] built provider tenant=%s provider=%s site=%s fp=%s",
        tenant_id, provider_id, metadata.site, metadata.key_fingerprint[:8],
    )
    # Adapter constructor is provider-specific; today we only have
    # Datadog so the explicit kwargs map 1:1.
    return adapter_cls(
        api_key=api_key,
        app_key=app_key,
        site=metadata.site,
    )
