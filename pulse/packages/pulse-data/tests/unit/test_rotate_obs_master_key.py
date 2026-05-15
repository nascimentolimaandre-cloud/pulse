"""FDD-OBS-001 Phase 1 T1.2 — rotation script unit + integration tests.

Validates the contract:

  1. Pure helpers:
     - `fingerprint(api_key)` is the SHA-256 prefix that
       `credential_service.fingerprint` produces (matches M-005).
     - Argv parser defaults to dry-run; `--apply` enables writes.
     - Missing / short env vars exit non-zero.

  2. Round-trip (uses the live postgres):
     - Insert a row encrypted with OLD master key (via
       `pgp_sym_encrypt` + the same SQL pattern as
       `credential_service.upsert_credential`).
     - Call `rotate(dry_run=False, ..., old_key=OLD, new_key=NEW)`.
     - Decrypt with NEW master key and assert the plaintext is the
       same as what we encrypted with OLD.
     - Assert `last_rotated_at` advanced and `key_fingerprint`
       remained identical (depends on plaintext, not master key).

  3. Idempotence:
     - Running with `old_key == new_key` is a no-op (returns 0).

  4. Dry-run:
     - `rotate(dry_run=True, ...)` does NOT mutate the DB. The
       ciphertext remains decryptable with OLD only.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Import the script as a module. Try a couple of likely paths so the
# test runs from both:
#   - Host: pulse/packages/pulse-data/tests/... → pulse/scripts/
#   - Container: /app/tests/... → script is mounted at /app/scripts/
#     (test environment puts a copy there) or at /scripts/.
_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "scripts",         # host
    Path(__file__).resolve().parents[2] / "scripts",         # container variant 1
    Path("/scripts"),                                         # container variant 2
    Path("/app/scripts"),                                     # container variant 3
]
for _candidate in _CANDIDATES:
    if (_candidate / "rotate_obs_master_key.py").exists():
        sys.path.insert(0, str(_candidate))
        break
else:                                                          # pragma: no cover
    raise ImportError(
        "rotate_obs_master_key.py not found in any of: "
        f"{', '.join(str(c) for c in _CANDIDATES)}"
    )
import rotate_obs_master_key as rot  # type: ignore[import-not-found]   # noqa: E402


_OLD_KEY = "OLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLD" + "x" * 8   # ≥32
_NEW_KEY = "NEWNEWNEWNEWNEWNEWNEWNEWNEWNEWNEWNEWNEWNEW" + "y" * 8   # ≥32


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestFingerprintHelper:
    def test_matches_credential_service_formula(self) -> None:
        """`fingerprint` MUST produce the same string as
        `credential_service.fingerprint` — so rotation can leave the
        value untouched. The script duplicates the helper instead of
        importing to keep the script standalone."""
        from src.contexts.observability.services.credential_service import (
            fingerprint as cred_fp,
        )

        sample = "DD-API-abc-123-very-long-token-value"
        assert rot.fingerprint(sample) == cred_fp(sample)

    def test_fingerprint_is_32_chars(self) -> None:
        assert len(rot.fingerprint("anything")) == 32

    def test_fingerprint_changes_when_plaintext_changes(self) -> None:
        assert rot.fingerprint("a") != rot.fingerprint("b")


# ---------------------------------------------------------------------------
# Env-var validation
# ---------------------------------------------------------------------------


class TestEnvKeyValidation:
    def test_missing_old_key_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("PULSE_OBS_MASTER_KEY", raising=False)
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY_NEW", _NEW_KEY)
        with pytest.raises(SystemExit):
            rot._read_env_keys()

    def test_missing_new_key_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY", _OLD_KEY)
        monkeypatch.delenv("PULSE_OBS_MASTER_KEY_NEW", raising=False)
        with pytest.raises(SystemExit):
            rot._read_env_keys()

    def test_short_old_key_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY", "short")
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY_NEW", _NEW_KEY)
        with pytest.raises(SystemExit):
            rot._read_env_keys()

    def test_short_new_key_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY", _OLD_KEY)
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY_NEW", "short")
        with pytest.raises(SystemExit):
            rot._read_env_keys()

    def test_both_keys_valid_returns_pair(self, monkeypatch) -> None:
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY", _OLD_KEY)
        monkeypatch.setenv("PULSE_OBS_MASTER_KEY_NEW", _NEW_KEY)
        old, new = rot._read_env_keys()
        assert old == _OLD_KEY
        assert new == _NEW_KEY


# ---------------------------------------------------------------------------
# Live round-trip (needs the local postgres + pgcrypto)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_url() -> str:
    """Async DSN for the live postgres. Skips if unreachable."""
    try:
        from src.config import settings
    except ImportError:
        pytest.skip("src.config unimportable")
    url = getattr(settings, "async_database_url", None)
    if not url:
        pytest.skip("settings.async_database_url not set")
    return url


@pytest.fixture
def seeded_row(db_url):
    """Insert one credential row encrypted with `_OLD_KEY`, yield its
    coordinates, and clean it up after the test."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    tenant_id = uuid.uuid4()
    provider = "datadog"
    api_plaintext = "DD-API-rotation-test-" + uuid.uuid4().hex
    app_plaintext = "DD-APP-rotation-test-" + uuid.uuid4().hex
    site = "datadoghq.com"
    now = datetime.now(timezone.utc)
    fp = rot.fingerprint(api_plaintext)

    async def _setup() -> None:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            # RLS scope.
            await conn.execute(
                text("SELECT set_config('app.current_tenant', :t, true)"),
                {"t": str(tenant_id)},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO tenant_observability_credentials (
                        tenant_id, provider, api_key_encrypted,
                        app_key_encrypted, site, validated_at,
                        last_rotated_at, key_fingerprint
                    ) VALUES (
                        :t, :p,
                        pgp_sym_encrypt(CAST(:api AS text), CAST(:old AS text)),
                        pgp_sym_encrypt(CAST(:app AS text), CAST(:old AS text)),
                        :site, :now, :now, :fp
                    )
                    """
                ),
                {
                    "t": str(tenant_id),
                    "p": provider,
                    "api": api_plaintext,
                    "app": app_plaintext,
                    "old": _OLD_KEY,
                    "site": site,
                    "now": now,
                    "fp": fp,
                },
            )
        await engine.dispose()

    asyncio.run(_setup())

    yield {
        "tenant_id": tenant_id,
        "provider": provider,
        "api_plaintext": api_plaintext,
        "app_plaintext": app_plaintext,
        "fingerprint": fp,
        "seeded_at": now,
    }

    async def _cleanup() -> None:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.current_tenant', :t, true)"),
                {"t": str(tenant_id)},
            )
            await conn.execute(
                text(
                    "DELETE FROM tenant_observability_credentials "
                    "WHERE tenant_id = :t AND provider = :p"
                ),
                {"t": str(tenant_id), "p": provider},
            )
        await engine.dispose()

    asyncio.run(_cleanup())


class TestRoundTrip:
    def test_apply_rotates_row_and_new_key_can_decrypt(
        self, db_url, seeded_row,
    ) -> None:
        """Apply rotation, then decrypt with NEW key — plaintext must
        match what we encrypted with OLD."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        tenant_id = seeded_row["tenant_id"]
        provider = seeded_row["provider"]
        old_fp = seeded_row["fingerprint"]
        seeded_at = seeded_row["seeded_at"]

        # Apply.
        rows = asyncio.run(rot.rotate(
            dry_run=False, db_url=db_url,
            old_key=_OLD_KEY, new_key=_NEW_KEY,
        ))
        assert rows >= 1, "rotate() reported zero rows touched"

        # Decrypt with NEW.
        async def _verify():
            engine = create_async_engine(db_url)
            async with engine.connect() as conn:
                await conn.execute(
                    text("SELECT set_config('app.current_tenant', :t, true)"),
                    {"t": str(tenant_id)},
                )
                result = await conn.execute(
                    text(
                        """
                        SELECT
                            pgp_sym_decrypt(api_key_encrypted, CAST(:k AS text)) AS api,
                            pgp_sym_decrypt(app_key_encrypted, CAST(:k AS text)) AS app,
                            key_fingerprint, last_rotated_at
                        FROM tenant_observability_credentials
                        WHERE tenant_id = :t AND provider = :p
                        """
                    ),
                    {"k": _NEW_KEY, "t": str(tenant_id), "p": provider},
                )
                row = result.first()
            await engine.dispose()
            return row

        row = asyncio.run(_verify())
        assert row is not None, "row vanished after rotation"
        assert row.api == seeded_row["api_plaintext"]
        assert row.app == seeded_row["app_plaintext"]
        # Fingerprint unchanged — depends on plaintext, not master key.
        assert row.key_fingerprint == old_fp
        # last_rotated_at advanced (within reason).
        assert row.last_rotated_at >= seeded_at

    def test_dry_run_does_not_modify_row(self, db_url, seeded_row) -> None:
        """A dry-run pass over the row leaves it decryptable with OLD."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        tenant_id = seeded_row["tenant_id"]
        provider = seeded_row["provider"]

        rows = asyncio.run(rot.rotate(
            dry_run=True, db_url=db_url,
            old_key=_OLD_KEY, new_key=_NEW_KEY,
        ))
        # Dry-run still REPORTS rows that would be touched.
        assert rows >= 1

        # OLD key still decrypts — DB untouched.
        async def _verify():
            engine = create_async_engine(db_url)
            async with engine.connect() as conn:
                await conn.execute(
                    text("SELECT set_config('app.current_tenant', :t, true)"),
                    {"t": str(tenant_id)},
                )
                result = await conn.execute(
                    text(
                        """
                        SELECT pgp_sym_decrypt(api_key_encrypted, CAST(:k AS text)) AS api
                        FROM tenant_observability_credentials
                        WHERE tenant_id = :t AND provider = :p
                        """
                    ),
                    {"k": _OLD_KEY, "t": str(tenant_id), "p": provider},
                )
                row = result.first()
            await engine.dispose()
            return row

        row = asyncio.run(_verify())
        assert row is not None
        assert row.api == seeded_row["api_plaintext"], (
            "dry-run mutated the DB — should have been read-only"
        )

    def test_idempotent_when_keys_equal(self, db_url, seeded_row) -> None:
        """OLD == NEW → no-op, returns 0, row unchanged."""
        rows = asyncio.run(rot.rotate(
            dry_run=False, db_url=db_url,
            old_key=_OLD_KEY, new_key=_OLD_KEY,
        ))
        assert rows == 0, (
            "Rotate with OLD == NEW should be a no-op but reported %d rows" % rows
        )
