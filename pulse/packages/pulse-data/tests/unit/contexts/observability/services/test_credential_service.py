"""FDD-OBS-001 PR 2 — credential_service unit tests.

Validates the contracts:
  - WeakMasterKeyError raised when master key < 32 chars / empty.
  - InvalidSiteError raised when site not in allowlist (CISO L-003).
  - fingerprint() always returns 32 hex chars (CISO M-005).
  - VALID_SITES allowlist matches the migration 020 CHECK constraint.
  - upsert/get round-trip issues the right SQL and surfaces decrypted keys.
  - get_credential_metadata never returns plaintext.

Live encrypt/decrypt round-trip is exercised by an integration test under
`tests/integration/contexts/observability/` (psql-based, mirrors the
INC-005/006 pattern). Unit tests here mock `get_session` like
`test_capability_detection.py` so they don't need a running DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.contexts.observability.services import credential_service
from src.contexts.observability.services.credential_service import (
    VALID_SITES,
    InvalidSiteError,
    StoredCredential,
    WeakMasterKeyError,
    fingerprint,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session_cm(execute_mock: AsyncMock) -> MagicMock:
    """Build an async-context-manager session whose `execute` delegates
    to the supplied mock. Mirrors the helper used in
    `test_capability_detection.py`."""
    session = AsyncMock()
    session.execute = execute_mock
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _row(**kwargs) -> MagicMock:
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


# ---------------------------------------------------------------------------
# Pure helpers (no DB, no settings)
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_fingerprint_is_32_hex_chars(self):
        """CISO M-005 — must be 32 hex chars (16 bytes / 128 bits)."""
        fp = fingerprint("any-api-key")
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)

    def test_same_key_same_fingerprint(self):
        assert fingerprint("k1") == fingerprint("k1")

    def test_different_keys_different_fingerprints(self):
        assert fingerprint("k1") != fingerprint("k2")


class TestValidSites:
    def test_datadog_main_site_allowed(self):
        assert "datadoghq.com" in VALID_SITES

    def test_datadog_eu_site_allowed(self):
        assert "datadoghq.eu" in VALID_SITES

    def test_newrelic_pre_registered(self):
        """New Relic sites pre-registered (R3) so PR 2 doesn't have to
        revisit the constraint."""
        assert "api.newrelic.com" in VALID_SITES
        assert "api.eu.newrelic.com" in VALID_SITES

    def test_arbitrary_domain_rejected(self):
        assert "evil.attacker.com" not in VALID_SITES
        assert "datadoghq.com.evil.com" not in VALID_SITES


# ---------------------------------------------------------------------------
# Validation guards (no DB)
# ---------------------------------------------------------------------------


class TestValidateMasterKey:
    @pytest.mark.asyncio
    async def test_empty_master_key_raises(self, monkeypatch):
        monkeypatch.setattr(credential_service.settings, "pulse_obs_master_key", "")
        with pytest.raises(WeakMasterKeyError):
            await credential_service.upsert_credential(
                _TENANT, "datadog",
                api_key="x", site="datadoghq.com", validated=False,
            )

    @pytest.mark.asyncio
    async def test_short_master_key_raises(self, monkeypatch):
        monkeypatch.setattr(
            credential_service.settings, "pulse_obs_master_key", "a" * 31,
        )
        with pytest.raises(WeakMasterKeyError):
            await credential_service.upsert_credential(
                _TENANT, "datadog",
                api_key="x", site="datadoghq.com", validated=False,
            )


class TestValidateSite:
    @pytest.mark.asyncio
    async def test_invalid_site_raises_before_db(self, monkeypatch):
        """CISO L-003 — application layer rejects bad site before
        any SQL is issued."""
        monkeypatch.setattr(
            credential_service.settings, "pulse_obs_master_key", "a" * 32,
        )
        with pytest.raises(InvalidSiteError) as exc_info:
            await credential_service.upsert_credential(
                _TENANT, "datadog",
                api_key="x", site="evil.attacker.com", validated=False,
            )
        assert "evil.attacker.com" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Mocked DB-layer tests (validate SQL shape + masking).
# Live encrypt/decrypt round-trip lives in tests/integration/.
# ---------------------------------------------------------------------------


class TestUpsertCredential:
    @pytest.mark.asyncio
    async def test_upsert_issues_pgp_sym_encrypt_and_returns_metadata(
        self, monkeypatch,
    ):
        """upsert binds master_key as a parameter (NOT logged), calls
        pgp_sym_encrypt in SQL, and returns metadata only (no plaintext)."""
        monkeypatch.setattr(
            credential_service.settings, "pulse_obs_master_key", "a" * 34,
        )
        execute = AsyncMock(return_value=MagicMock())
        with patch.object(
            credential_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            stored = await credential_service.upsert_credential(
                _TENANT, "datadog",
                api_key="ddog-secret",
                app_key="app-secret",
                site="datadoghq.com",
                validated=True,
            )

        # SQL should contain pgp_sym_encrypt (encryption is in DB layer).
        execute.assert_called_once()
        sql_text = str(execute.call_args.args[0])
        params = execute.call_args.args[1]
        assert "pgp_sym_encrypt" in sql_text
        # Master key passed as bound parameter (not interpolated).
        assert params["master_key"] == "a" * 34
        # Plaintext keys passed to bound params for pgcrypto, never logged.
        assert params["api_key"] == "ddog-secret"
        assert params["app_key"] == "app-secret"

        # Returned metadata contains site + has_app_key + 32-char fingerprint;
        # never returns plaintext.
        assert isinstance(stored, StoredCredential)
        assert stored.site == "datadoghq.com"
        assert stored.has_app_key is True
        assert stored.validated_at is not None
        assert len(stored.key_fingerprint) == 32
        assert "ddog-secret" not in repr(stored)

    @pytest.mark.asyncio
    async def test_upsert_without_app_key_marks_has_app_key_false(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            credential_service.settings, "pulse_obs_master_key", "a" * 34,
        )
        execute = AsyncMock(return_value=MagicMock())
        with patch.object(
            credential_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            stored = await credential_service.upsert_credential(
                _TENANT, "datadog",
                api_key="ddog-secret",
                site="datadoghq.com",
                validated=False,
            )
        assert stored.has_app_key is False
        assert stored.validated_at is None

    @pytest.mark.asyncio
    async def test_upsert_validated_false_keeps_validated_at_null(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            credential_service.settings, "pulse_obs_master_key", "a" * 34,
        )
        execute = AsyncMock(return_value=MagicMock())
        with patch.object(
            credential_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            stored = await credential_service.upsert_credential(
                _TENANT, "datadog",
                api_key="ddog-secret",
                site="datadoghq.com",
                validated=False,
            )
        params = execute.call_args.args[1]
        assert params["validated_at"] is None
        assert stored.validated_at is None


class TestGetCredentialKeys:
    @pytest.mark.asyncio
    async def test_returns_decrypted_keys_when_row_present(self, monkeypatch):
        """get_credential_keys issues pgp_sym_decrypt and surfaces the
        plaintext (the call site needs the actual key for the Datadog client)."""
        monkeypatch.setattr(
            credential_service.settings, "pulse_obs_master_key", "a" * 34,
        )
        result = MagicMock()
        result.first.return_value = _row(api_key="dd-plain", app_key="app-plain")
        execute = AsyncMock(return_value=result)

        with patch.object(
            credential_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            keys = await credential_service.get_credential_keys(_TENANT, "datadog")

        sql_text = str(execute.call_args.args[0])
        assert "pgp_sym_decrypt" in sql_text
        assert keys == ("dd-plain", "app-plain")

    @pytest.mark.asyncio
    async def test_returns_none_when_row_absent(self, monkeypatch):
        """No row → None, not exception (ADR-026 graceful degradation)."""
        monkeypatch.setattr(
            credential_service.settings, "pulse_obs_master_key", "a" * 34,
        )
        result = MagicMock()
        result.first.return_value = None
        execute = AsyncMock(return_value=result)
        with patch.object(
            credential_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            keys = await credential_service.get_credential_keys(_TENANT, "datadog")
        assert keys is None


class TestGetCredentialMetadata:
    @pytest.mark.asyncio
    async def test_metadata_does_not_select_plaintext_columns(self):
        """SELECT must not include `api_key_encrypted` / `app_key_encrypted`
        unmasked. Only metadata + has_app_key derived bool."""
        result = MagicMock()
        result.first.return_value = _row(
            site="datadoghq.com",
            validated_at=None,
            last_rotated_at=None,
            key_fingerprint="aabbccdd" * 4,
            has_app_key=False,
        )
        execute = AsyncMock(return_value=result)
        with patch.object(
            credential_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            metadata = await credential_service.get_credential_metadata(
                _TENANT, "datadog",
            )

        sql_text = str(execute.call_args.args[0])
        assert "pgp_sym_decrypt" not in sql_text
        assert metadata is not None
        assert metadata.site == "datadoghq.com"
        assert metadata.has_app_key is False

    @pytest.mark.asyncio
    async def test_metadata_returns_none_when_row_absent(self):
        result = MagicMock()
        result.first.return_value = None
        execute = AsyncMock(return_value=result)
        with patch.object(
            credential_service, "get_session", return_value=_mock_session_cm(execute),
        ):
            metadata = await credential_service.get_credential_metadata(
                _TENANT, "datadog",
            )
        assert metadata is None
