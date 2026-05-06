"""FDD-OBS-001 PR 2 — admin & public schemas for observability routes.

DTOs are Pydantic v2 models so FastAPI generates an honest OpenAPI
schema and we reject malformed input at the parse boundary (CISO L-003
defense-in-depth alongside the credential_service allowlist).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.contexts.observability.services.credential_service import VALID_SITES


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------


class DatadogValidateRequest(BaseModel):
    """Body of `POST /admin/integrations/datadog/validate`.

    The `site` allowlist is enforced at the schema layer (rejects
    malformed input with HTTP 422 before any encryption / network call).
    Same allowlist is also enforced at the service layer
    (`credential_service._ensure_valid_site`) and at the DB
    (migration 020 CHECK constraint) — three defenses, each independent.
    """

    api_key: str = Field(..., min_length=10, max_length=512)
    app_key: str | None = Field(default=None, min_length=10, max_length=512)
    site: str = Field(..., min_length=4, max_length=64)
    persist: bool = Field(
        default=False,
        description=(
            "When True, persist the encrypted credential after a "
            "successful validation. When False, only validate (the key "
            "is held in memory for the probe and discarded)."
        ),
    )

    @field_validator("site")
    @classmethod
    def _site_in_allowlist(cls, v: str) -> str:
        if v not in VALID_SITES:
            raise ValueError(
                f"site={v!r} is not in the Datadog/NR allowlist. "
                f"Allowed sites: {sorted(VALID_SITES)}"
            )
        return v

    @field_validator("api_key", "app_key")
    @classmethod
    def _no_whitespace_in_key(cls, v: str | None) -> str | None:
        # Datadog API keys are 32 hex chars; defensive check rejects
        # accidental whitespace/newlines from copy-paste.
        if v is None:
            return v
        stripped = v.strip()
        if stripped != v:
            raise ValueError("API key must not contain leading/trailing whitespace")
        return stripped


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------


class DatadogValidateResponse(BaseModel):
    """Result of a validation attempt. Never contains the plaintext key."""

    valid: bool
    persisted: bool = False
    site: str
    key_fingerprint: str | None = None
    validated_at: datetime | None = None
    message: str | None = None


class CredentialMetadataResponse(BaseModel):
    """Response of `GET /admin/integrations/<provider>/metadata`. Public-safe
    — never includes plaintext keys."""

    provider: str
    site: str
    has_app_key: bool
    validated_at: datetime | None
    last_rotated_at: datetime
    key_fingerprint: str
    status: Literal["validated", "pending_validation", "expired"]
