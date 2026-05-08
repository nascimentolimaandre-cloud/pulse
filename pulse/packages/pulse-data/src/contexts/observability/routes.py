"""FDD-OBS-001 PR 2 — admin endpoint for observability credentials.

Exposes:
  POST /data/v1/admin/integrations/datadog/validate
       Validates a Datadog API key against `<site>/api/v1/validate`.
       When `persist=true`, the (encrypted) credential is upserted via
       `credential_service.upsert_credential`. The plaintext key is
       held in memory ONLY for the duration of the HTTP probe + single
       SQL transaction; never logged.

  GET  /data/v1/admin/integrations/<provider>/metadata
       Returns metadata only — no plaintext, no fingerprint of the
       encrypted column. Used by the admin UI to render the "currently
       configured" panel.

Security:
  - Tenant scoped via `get_tenant_id` (TenantMiddleware injects).
  - Site allowlist enforced 3× (schema → service → DB CHECK).
  - Connector instantiated per-request; client closed after each call
    (no long-lived secrets in process memory).
  - Errors map to non-leaky HTTP responses (no API key in body).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.connectors.observability.datadog_connector import (
    DatadogConnectorError,
    DatadogProvider,
)
from src.contexts.observability.schemas import (
    CredentialMetadataResponse,
    DatadogValidateRequest,
    DatadogValidateResponse,
    OverrideRequest,
    OwnershipListResponse,
    OwnershipRowResponse,
    OwnershipSyncResponse,
)
from src.contexts.observability.services import (
    credential_service,
    ownership_inference,
    provider_factory,
)
from src.contexts.observability.services.credential_service import (
    InvalidSiteError,
    WeakMasterKeyError,
)
from src.contexts.observability.services.provider_factory import (
    ProviderNotConfiguredError,
    UnknownProviderError,
)
from src.contexts.observability.services.squad_directory import (
    InvalidSquadKeyError,
)
from src.shared.tenant import get_tenant_id

logger = logging.getLogger(__name__)


admin_router = APIRouter(
    prefix="/data/v1/admin/integrations",
    tags=["Observability — Admin"],
)


# ---------------------------------------------------------------------------
# Datadog
# ---------------------------------------------------------------------------


@admin_router.post(
    "/datadog/validate",
    response_model=DatadogValidateResponse,
    summary="Validate (and optionally persist) a Datadog API credential",
)
async def validate_datadog_credential(
    body: DatadogValidateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
) -> DatadogValidateResponse:
    """Validate a DD API key against `<site>/api/v1/validate` and, when
    `persist=True`, upsert the encrypted credential.

    Failure modes are non-leaky:
      - Bad master key (operator config) → 503 "Server not configured…"
      - Site not allowlisted → 422 (handled by Pydantic, never reaches here)
      - Invalid DD key → 200 with `valid=false`, NEVER 401 (we don't echo
        upstream auth status to the client because /validate is
        admin-side and the operator should see the actual reason).
    """
    # Build the connector — short-lived (closes at end of request).
    async with DatadogProvider(
        api_key=body.api_key,
        app_key=body.app_key,
        site=body.site,
    ) as provider:
        try:
            ok = await provider.health_check()
        except Exception as exc:  # defensive — health_check shouldn't raise
            logger.exception(
                "[obs-admin] datadog validate unexpected error tenant=%s site=%s",
                tenant_id, body.site,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not reach Datadog. Check site/network and try again.",
            ) from exc

    if not ok:
        return DatadogValidateResponse(
            valid=False,
            persisted=False,
            site=body.site,
            message=(
                "Datadog rejected the credential. Verify the API key, "
                "Application key (if used), and site URL."
            ),
        )

    # Validation succeeded. Optionally persist.
    if not body.persist:
        return DatadogValidateResponse(
            valid=True,
            persisted=False,
            site=body.site,
            key_fingerprint=credential_service.fingerprint(body.api_key),
            validated_at=datetime.now(timezone.utc),
            message="Credential is valid. Set persist=true to store it.",
        )

    try:
        stored = await credential_service.upsert_credential(
            tenant_id=tenant_id,
            provider="datadog",
            api_key=body.api_key,
            app_key=body.app_key,
            site=body.site,
            validated=True,
        )
    except WeakMasterKeyError:
        # Operator config is wrong (PULSE_OBS_MASTER_KEY missing/weak).
        # Don't leak this to a tenant-side error — return 503 telling
        # the operator to fix server config.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Server is not configured to store credentials. Contact "
                "your administrator (PULSE_OBS_MASTER_KEY)."
            ),
        )
    except InvalidSiteError:
        # Should be impossible because Pydantic schema rejects bad sites,
        # but defense-in-depth: if it ever fires, return 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"site={body.site!r} is not in the allowlist.",
        )

    logger.info(
        "[obs-admin] datadog validate+persist tenant=%s site=%s fp=%s",
        tenant_id, stored.site, stored.key_fingerprint[:8],
    )
    return DatadogValidateResponse(
        valid=True,
        persisted=True,
        site=stored.site,
        key_fingerprint=stored.key_fingerprint,
        validated_at=stored.validated_at,
        message="Credential validated and stored.",
    )


# ---------------------------------------------------------------------------
# Read-only metadata (any provider)
# ---------------------------------------------------------------------------


@admin_router.get(
    "/{provider}/metadata",
    response_model=CredentialMetadataResponse,
    summary="Public-safe metadata for the configured credential (no plaintext).",
)
async def get_provider_metadata(
    provider: str,
    tenant_id: UUID = Depends(get_tenant_id),
) -> CredentialMetadataResponse:
    """Returns metadata for the (tenant, provider) credential or 404 if
    none configured. NEVER returns plaintext API keys or the encrypted
    blob."""
    metadata = await credential_service.get_credential_metadata(tenant_id, provider)
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No credential configured for provider={provider!r}.",
        )

    if metadata.validated_at is None:
        cred_status = "pending_validation"
    else:
        # Future: expire after 90d (out of scope for PR 2).
        cred_status = "validated"

    return CredentialMetadataResponse(
        provider=metadata.provider,
        site=metadata.site,
        has_app_key=metadata.has_app_key,
        validated_at=metadata.validated_at,
        last_rotated_at=metadata.last_rotated_at,
        key_fingerprint=metadata.key_fingerprint,
        status=cred_status,
    )


# ---------------------------------------------------------------------------
# FDD-OBS-001 PR 3 — Service Ownership Map (Tier 1 + Tier 3)
# ---------------------------------------------------------------------------


def _row_to_response(row: ownership_inference.OwnershipRow) -> OwnershipRowResponse:
    return OwnershipRowResponse(
        service_external_id=row.service_external_id,
        service_name=row.service_name,
        repo_url=row.repo_url,
        inferred_squad_key=row.inferred_squad_key,
        inferred_confidence=row.inferred_confidence,
        override_squad_key=row.override_squad_key,
        effective_squad_key=row.effective_squad_key,
        last_inference_at=row.last_inference_at,
        is_qualified_squad=row.is_qualified_squad,
    )


@admin_router.post(
    "/{provider}/ownership/sync",
    response_model=OwnershipSyncResponse,
    summary="Run Tier-1 (vendor tag) ownership inference",
)
async def sync_ownership(
    provider: str,
    tenant_id: UUID = Depends(get_tenant_id),
) -> OwnershipSyncResponse:
    """Trigger a Tier-1 inference run (sync). Reads the provider's
    service catalog, upserts `service_squad_ownership` rows with
    `inferred_*` fields. NEVER touches `override_squad_key`.

    Idempotent: a re-run with no DD-side changes returns
    `unchanged == services_seen`.
    """
    try:
        adapter = await provider_factory.build_for_tenant(tenant_id, provider)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    async with adapter:
        try:
            result = await ownership_inference.sync_tier1_inference(
                tenant_id, provider, adapter,
            )
        except DatadogConnectorError as exc:
            logger.warning(
                "[obs-ownership] sync failed tenant=%s provider=%s err=%s",
                tenant_id, provider, exc,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Provider call failed: {exc}",
            ) from exc

    return OwnershipSyncResponse(
        services_seen=result.services_seen,
        inferred_with_tag=result.inferred_with_tag,
        inferred_none=result.inferred_none,
        unchanged=result.unchanged,
        duration_ms=result.duration_ms,
    )


@admin_router.put(
    "/{provider}/ownership/{service_external_id}/override",
    response_model=OwnershipRowResponse,
    summary="Set or clear Tier-3 admin override for a service's squad",
)
async def upsert_override(
    provider: str,
    service_external_id: str,
    body: OverrideRequest,
    tenant_id: UUID = Depends(get_tenant_id),
) -> OwnershipRowResponse:
    """`squad_key=null` clears the override; non-null sets it after
    validating against the tenant's qualified-squads set."""
    try:
        if body.squad_key is None:
            row = await ownership_inference.clear_override(
                tenant_id, provider, service_external_id,
            )
        else:
            row = await ownership_inference.set_override(
                tenant_id, provider, service_external_id, body.squad_key,
            )
    except InvalidSquadKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        ) from exc

    return _row_to_response(row)


@admin_router.get(
    "/{provider}/ownership",
    response_model=OwnershipListResponse,
    summary="List the service ownership map",
)
async def list_ownership(
    provider: str,
    tenant_id: UUID = Depends(get_tenant_id),
) -> OwnershipListResponse:
    """Returns ownership rows ordered by service_name. Includes a
    derived `coverage_pct` (% of services whose effective squad maps
    to a qualified tenant squad) for quick health-glance in the UI."""
    rows = await ownership_inference.list_for_tenant(tenant_id, provider)
    if not rows:
        return OwnershipListResponse(services=[], coverage_pct=0.0)

    qualified_count = sum(1 for r in rows if r.is_qualified_squad)
    coverage = qualified_count / len(rows)

    return OwnershipListResponse(
        services=[_row_to_response(r) for r in rows],
        coverage_pct=round(coverage, 4),
    )
