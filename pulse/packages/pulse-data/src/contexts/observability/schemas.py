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


# ---------------------------------------------------------------------------
# FDD-OBS-001 PR 3 — Service Ownership Map
# ---------------------------------------------------------------------------


class OwnershipSyncResponse(BaseModel):
    """Result of `POST /admin/integrations/{provider}/ownership/sync`.

    FDD-OBS-001 PR 3.5: added `inferred_with_alias` to track services
    whose DD team tag was translated through `tenant_team_alias`.
    `inferred_with_tag` now counts only services whose raw vendor team
    survived (no alias configured → UI yellow badge).
    """

    services_seen: int
    inferred_with_tag: int
    inferred_with_alias: int = 0
    inferred_none: int
    unchanged: int
    duration_ms: int


class OverrideRequest(BaseModel):
    """Body of `PUT /admin/integrations/{provider}/ownership/{id}/override`.

    `squad_key=null` clears the override. Squad-key allowlist is
    enforced at the service layer (`SquadDirectory.assert_valid_squad`)
    against the tenant's qualified squads, so we don't pin to a static
    Literal here.
    """

    squad_key: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Squad key from `jira_project_catalog`. Pass null to clear "
            "the override (effective owner falls back to inferred)."
        ),
    )

    @field_validator("squad_key")
    @classmethod
    def _no_whitespace(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if stripped != v or not stripped:
            raise ValueError(
                "squad_key must not be empty / contain leading-trailing whitespace"
            )
        return stripped


class OwnershipRowResponse(BaseModel):
    """One service row in the ownership map. Frontend consumes
    `effective_squad_key` directly — no client-side COALESCE."""

    service_external_id: str
    service_name: str
    repo_url: str | None
    inferred_squad_key: str | None
    inferred_confidence: Literal["tag", "alias", "heuristic", "none"] | None
    override_squad_key: str | None
    effective_squad_key: str | None
    last_inference_at: datetime
    is_qualified_squad: bool


class OwnershipListResponse(BaseModel):
    """Wrapper around `OwnershipRowResponse[]` so we can carry summary
    fields (squad coverage %) alongside without breaking versioning."""

    services: list[OwnershipRowResponse]
    coverage_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of services whose effective_squad_key maps to a "
            "qualified tenant squad. 1.0 = full coverage."
        ),
    )


# ---------------------------------------------------------------------------
# FDD-OBS-001 PR 3.5 — Team Alias Map
# ---------------------------------------------------------------------------


class AliasMapping(BaseModel):
    """One vendor_team → squad_key mapping. Used in single-PUT and bulk
    import payloads."""

    vendor_team_value: str = Field(..., min_length=1, max_length=128)
    squad_key: str = Field(..., min_length=1, max_length=64)

    @field_validator("vendor_team_value", "squad_key")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("must not be empty after trim")
        return s


class AliasResponse(BaseModel):
    """Read-model for the alias map. `vendor_team_value` is always the
    lowercase canonical form (set/lookup are case-insensitive)."""

    vendor_team_value: str
    squad_key: str
    created_at: datetime
    updated_at: datetime


class AliasListResponse(BaseModel):
    aliases: list[AliasResponse]
    total: int


class AliasBulkImportRequest(BaseModel):
    """Body for `POST /admin/integrations/{provider}/aliases/import`.

    Atomic batch — all-or-nothing on the SQL transaction, but rows
    individually rejected for invalid squad keys (typos) get counted
    in the response so operators can fix and retry."""

    mappings: list[AliasMapping] = Field(..., max_length=2000)


class AliasBulkImportResponse(BaseModel):
    inserted: int
    updated: int
    rejected_invalid_squad: int
    rejected_empty: int
    total_submitted: int


class AliasSuggestionsResponse(BaseModel):
    """Distinct vendor_team values seen in inference but not yet aliased.

    UI uses this to surface "you have N unmapped teams" + offer the
    fast-track import flow."""

    vendor_teams: list[str]
    total: int


# ---------------------------------------------------------------------------
# FDD-OBS-001 PR 4b — Deploy Health Timeline
# ---------------------------------------------------------------------------


class TimelineHealthBucket(BaseModel):
    """One hour-bucket of health severity on the timeline."""

    hour_bucket: datetime
    severity: float = Field(..., ge=0.0, le=3.0)
    samples_count: int = Field(..., ge=0)
    metric: str
    service: str | None = None  # null on squad-aggregated rows


class TimelineDeployMarker(BaseModel):
    """Deploy event for the timeline.

    ANTI-SURVEILLANCE (ADR-025): NEVER includes `author`. The
    underlying `eng_deployments` table has the column, but the
    timeline service explicitly omits it from the SELECT. If a
    future refactor adds it back, the source-grep CI test
    (`test_obs_anti_surveillance.py`) will catch it.
    """

    deployed_at: datetime
    repo: str
    environment: str | None
    sha: str | None
    is_failure: bool
    url: str | None
    service: str | None = None


class TimelineResponseDTO(BaseModel):
    scope: Literal["squad", "service"]
    squad_key: str | None
    service: str | None
    since: datetime
    until: datetime
    buckets: list[TimelineHealthBucket]
    deploys: list[TimelineDeployMarker]
    services_in_squad: int = Field(..., ge=0)
    has_data: bool
