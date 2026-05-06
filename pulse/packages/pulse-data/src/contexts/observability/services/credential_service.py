"""FDD-OBS-001 PR 2 — Per-tenant observability credentials encryption.

Encrypts/decrypts API keys for `tenant_observability_credentials` via
Postgres `pgp_sym_encrypt` / `pgp_sym_decrypt`. The master key lives
in `settings.pulse_obs_master_key` (validated to ≥ 32 chars by the
config validator from CISO H-001).

CISO M-005 — `key_fingerprint` truncated to 32 hex chars (16 bytes /
128 bits) instead of 16. Aligns with the column width and gives
comfortable uniqueness headroom.

CISO L-003 — `site` argument is validated against `_VALID_SITES`
allowlist BEFORE writing. Defense in depth (DB has the same CHECK
constraint via migration 020, but raising in Python gives a better
error message before round-tripping).

Design notes:
  - Encryption + decryption happen in SQL (`pgp_sym_encrypt(plain, key)`)
    rather than Python because Postgres handles the algorithmic detail
    and avoids leaking plaintext into application logs / heap dumps.
  - The master key is passed as a bound parameter (never logged).
  - Validation calls (PR 2 admin endpoint) hold the plaintext key in
    memory only for the duration of the HTTP probe + single SQL
    transaction; never persisted as plaintext.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from sqlalchemy import text

from src.config import settings
from src.database import get_session

logger = logging.getLogger(__name__)


# CISO L-003 + ADR-021. Authoritative allowlist for the `site` column;
# mirrored in migration 020 as a DB CHECK constraint. Update both in
# lockstep.
VALID_SITES: Final[frozenset[str]] = frozenset({
    # Datadog
    "datadoghq.com",
    "datadoghq.eu",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "ap1.datadoghq.com",
    "ddog-gov.com",
    # New Relic — pre-registered for R3
    "api.newrelic.com",
    "api.eu.newrelic.com",
})


# CISO M-005 — full 32-char hex slice of sha256 (16 bytes / 128 bits).
_FINGERPRINT_LEN: Final[int] = 32


class CredentialServiceError(Exception):
    """Raised on validation, encryption, or persistence errors."""


class WeakMasterKeyError(CredentialServiceError):
    """Raised when `settings.pulse_obs_master_key` is empty or too short.

    Distinct from CredentialServiceError so callers can show a specific
    operator-facing message ("set PULSE_OBS_MASTER_KEY in env").
    """


class InvalidSiteError(CredentialServiceError):
    """Raised when `site` is not in `VALID_SITES` (CISO L-003)."""


@dataclass(frozen=True)
class StoredCredential:
    """Output of `get_credential` — never includes the plaintext key."""

    tenant_id: UUID
    provider: str
    site: str
    has_app_key: bool
    validated_at: datetime | None
    last_rotated_at: datetime
    key_fingerprint: str


def _ensure_master_key() -> str:
    """Return the master key or raise. Single chokepoint that PR 2's
    admin endpoint invokes before any encryption."""
    key = settings.pulse_obs_master_key
    if not key or len(key) < 32:
        raise WeakMasterKeyError(
            "PULSE_OBS_MASTER_KEY is not set or shorter than 32 chars. "
            "Configure it before storing observability credentials."
        )
    return key


def _ensure_valid_site(site: str) -> str:
    """Validate `site` against allowlist or raise (CISO L-003 Layer 1).

    The DB has the same CHECK constraint, but raising in Python gives
    a richer error message and avoids burning a SQL transaction on
    invalid input.
    """
    if site not in VALID_SITES:
        raise InvalidSiteError(
            f"site={site!r} is not in the allowed set. "
            f"Allowed: {sorted(VALID_SITES)}"
        )
    return site


def fingerprint(api_key: str) -> str:
    """CISO M-005 — sha256(api_key) truncated to 32 hex chars (128 bits).

    Used for audit/diff tracking only — NEVER for any security
    decision. 128 bits gives 2^64 expected collisions, plenty for
    rotation tracking.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:_FINGERPRINT_LEN]


async def upsert_credential(
    tenant_id: UUID,
    provider: str,
    *,
    api_key: str,
    app_key: str | None = None,
    site: str,
    validated: bool,
) -> StoredCredential:
    """Encrypt + UPSERT credentials for (tenant, provider). Plaintext
    keys never leave this function — Postgres `pgp_sym_encrypt` handles
    encryption inline, the master key is a bound parameter (not
    logged), and the response only contains metadata.

    `validated=True` updates `validated_at = now()`. PR 2's admin
    endpoint calls this only after the live `/validate` HTTP probe
    succeeds.
    """
    master_key = _ensure_master_key()
    site = _ensure_valid_site(site)

    fp = fingerprint(api_key)
    now = datetime.now(timezone.utc)

    async with get_session(tenant_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO tenant_observability_credentials (
                    tenant_id, provider,
                    api_key_encrypted, app_key_encrypted,
                    site, validated_at, last_rotated_at, key_fingerprint
                )
                VALUES (
                    :tenant_id, :provider,
                    pgp_sym_encrypt(:api_key, :master_key),
                    CASE
                        WHEN :app_key IS NULL THEN NULL
                        ELSE pgp_sym_encrypt(:app_key, :master_key)
                    END,
                    :site, :validated_at, :now, :fp
                )
                ON CONFLICT (tenant_id, provider) DO UPDATE SET
                    api_key_encrypted = EXCLUDED.api_key_encrypted,
                    app_key_encrypted = EXCLUDED.app_key_encrypted,
                    site              = EXCLUDED.site,
                    validated_at      = EXCLUDED.validated_at,
                    last_rotated_at   = EXCLUDED.last_rotated_at,
                    key_fingerprint   = EXCLUDED.key_fingerprint,
                    updated_at        = NOW()
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider,
                "api_key": api_key,
                "app_key": app_key,
                "master_key": master_key,
                "site": site,
                "validated_at": now if validated else None,
                "now": now,
                "fp": fp,
            },
        )
        await session.commit()

    logger.info(
        "[obs-creds] upsert tenant=%s provider=%s site=%s fingerprint=%s validated=%s",
        tenant_id, provider, site, fp[:8], validated,
    )
    return StoredCredential(
        tenant_id=tenant_id,
        provider=provider,
        site=site,
        has_app_key=app_key is not None,
        validated_at=now if validated else None,
        last_rotated_at=now,
        key_fingerprint=fp,
    )


async def get_credential_keys(tenant_id: UUID, provider: str) -> tuple[str, str | None] | None:
    """Decrypt + return (api_key, app_key) for (tenant, provider).

    Returns None if no row exists. Plaintext keys are returned for the
    HTTP-client construction call site only — must not be logged or
    persisted further.
    """
    master_key = _ensure_master_key()

    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT
                    pgp_sym_decrypt(api_key_encrypted, :master_key) AS api_key,
                    CASE
                        WHEN app_key_encrypted IS NULL THEN NULL
                        ELSE pgp_sym_decrypt(app_key_encrypted, :master_key)
                    END AS app_key
                FROM tenant_observability_credentials
                WHERE tenant_id = :tenant_id AND provider = :provider
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider,
                "master_key": master_key,
            },
        )
        row = result.first()
        if row is None:
            return None
        return (row.api_key, row.app_key)


async def get_credential_metadata(
    tenant_id: UUID, provider: str,
) -> StoredCredential | None:
    """Public-safe credential metadata (no plaintext keys). Used by
    admin UI / capability detection."""
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT
                    site,
                    validated_at,
                    last_rotated_at,
                    key_fingerprint,
                    (app_key_encrypted IS NOT NULL) AS has_app_key
                FROM tenant_observability_credentials
                WHERE tenant_id = :tenant_id AND provider = :provider
                """
            ),
            {"tenant_id": str(tenant_id), "provider": provider},
        )
        row = result.first()
        if row is None:
            return None
        return StoredCredential(
            tenant_id=tenant_id,
            provider=provider,
            site=row.site,
            has_app_key=bool(row.has_app_key),
            validated_at=row.validated_at,
            last_rotated_at=row.last_rotated_at,
            key_fingerprint=row.key_fingerprint,
        )
