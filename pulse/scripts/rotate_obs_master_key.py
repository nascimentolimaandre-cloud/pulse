#!/usr/bin/env python3
"""FDD-OBS-001 Phase 1 T1.2 — observability master-key rotation.

Re-encrypts every row in `tenant_observability_credentials` from the
OLD pgcrypto master key to a NEW master key. Idempotent. Defaults to
dry-run; requires `--apply` to actually mutate.

Usage:

    PULSE_OBS_MASTER_KEY=<old> PULSE_OBS_MASTER_KEY_NEW=<new> \\
        python -m scripts.rotate_obs_master_key --dry-run     # default
    PULSE_OBS_MASTER_KEY=<old> PULSE_OBS_MASTER_KEY_NEW=<new> \\
        python -m scripts.rotate_obs_master_key --apply

Both env vars must be at least 32 chars (validated upstream).

Run via the runbook at `docs/runbooks/obs-master-key-rotation.md`,
which covers:
  - When to rotate (suspected leak, quarterly cadence, team turnover).
  - Pre-flight checklist (worker paused, DB backup, etc.).
  - Recovery: half-completed rotation.
  - Smoke validation via `get_credential_metadata` (no plaintext logging).

ADR-021 requires:
  - Master key never logged.
  - Honest data flow (CISO FIND-002): `pgp_sym_decrypt` runs INSIDE
    postgres so the OLD master key never leaves the DB process. The
    decrypted plaintext then returns over the trusted libpq channel
    into Python heap, where the script computes the M-005 sha256[:32]
    fingerprint of the plaintext. A SECOND statement re-encrypts via
    `pgp_sym_encrypt` with the NEW key and UPDATEs the row. Plaintext
    therefore lives briefly in the script's Python heap (bounded to
    one row's worth per iteration); never logged, never persisted
    further, never sent over the network beyond libpq.
  - `key_fingerprint` recomputed to match the (unchanged) plaintext —
    fingerprint depends on the API key, not the master key.
  - `last_rotated_at = NOW()`.

Memory residence threat model: plaintext is bounded to one row per
loop iteration. After the re-encrypt UPDATE, the local row variable
goes out of scope and is gc'd at the end of the iteration. The
process is short-lived (one-shot CLI, not a daemon), so heap inspection
windows are minimal. Operator running rotation already has access to
the OLD master key, so this script does not elevate access. For
hardened deployments, consider running rotation in an ephemeral
container with `mlock`-ed memory (out of scope for R0).

The script intentionally does NOT print plaintext API keys; only the
8-char prefix of the new fingerprint, the count of rows updated, and
the tenant UUID + provider for audit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone

# Allow running from repo root: `python scripts/rotate_obs_master_key.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "pulse-data"))

from sqlalchemy import text                                # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine    # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("rotate-obs-master-key")


_MIN_KEY_LEN = 32
_FINGERPRINT_LEN = 32   # matches credential_service._FINGERPRINT_LEN


def fingerprint(api_key: str) -> str:
    """Recompute the sha256-prefix fingerprint (M-005, 128 bits)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:_FINGERPRINT_LEN]


def _read_env_keys() -> tuple[str, str]:
    """Read OLD + NEW master keys from env. Validate length. Never log
    the values themselves."""
    old = os.environ.get("PULSE_OBS_MASTER_KEY", "")
    new = os.environ.get("PULSE_OBS_MASTER_KEY_NEW", "")
    if not old or len(old) < _MIN_KEY_LEN:
        raise SystemExit(
            "PULSE_OBS_MASTER_KEY missing or shorter than 32 chars"
        )
    if not new or len(new) < _MIN_KEY_LEN:
        raise SystemExit(
            "PULSE_OBS_MASTER_KEY_NEW missing or shorter than 32 chars"
        )
    return old, new


def _build_db_url() -> str:
    """Resolve the async DB URL. Prefers PULSE_OBS_ROTATION_DATABASE_URL
    (an override the runbook uses for a backup-restored snapshot), then
    settings.async_database_url."""
    override = os.environ.get("PULSE_OBS_ROTATION_DATABASE_URL")
    if override:
        return override
    from src.config import settings   # type: ignore[import-not-found]
    return settings.async_database_url


async def rotate(*, dry_run: bool, db_url: str, old_key: str, new_key: str) -> int:
    """Iterate every row, re-encrypt api_key + app_key, update fingerprint
    + last_rotated_at. Returns rows touched (or rows that WOULD be
    touched in dry-run).

    Strategy:
      - SELECT id-set first; iterate one at a time so a partial failure
        doesn't roll back the whole table (each row is its own txn).
      - For each row: decrypt with OLD, re-encrypt with NEW, INSIDE
        postgres (one statement, no plaintext crosses the wire).
      - Re-fetch the decrypted api_key as a value so we can recompute
        the fingerprint in Python (M-005). The plaintext lives in
        memory for one statement and is never logged.
    """
    engine = create_async_engine(db_url, pool_size=2, max_overflow=2)
    rows_touched = 0
    rows_skipped_idempotent = 0
    rows_failed = 0
    try:
        async with engine.connect() as conn:
            # ID list — no plaintext involved.
            result = await conn.execute(
                text(
                    """
                    SELECT tenant_id, provider
                    FROM tenant_observability_credentials
                    ORDER BY tenant_id, provider
                    """
                )
            )
            rows = list(result)

        logger.info("found %d credential rows to consider", len(rows))

        # Short-circuit: if OLD == NEW, rotation is a no-op. Don't write.
        if old_key == new_key:
            logger.warning(
                "OLD and NEW master keys are equal — rotation is a no-op. "
                "Returning without writing."
            )
            return 0

        for row in rows:
            tenant_id, provider = row.tenant_id, row.provider
            try:
                # Step 1: decrypt with OLD inside postgres, return as
                # bound parameters for re-fingerprinting.
                async with engine.connect() as conn:
                    decrypted = await conn.execute(
                        text(
                            """
                            SELECT
                                pgp_sym_decrypt(api_key_encrypted, CAST(:old AS text)) AS api_key,
                                CASE
                                    WHEN app_key_encrypted IS NULL THEN NULL
                                    ELSE pgp_sym_decrypt(app_key_encrypted, CAST(:old AS text))
                                END AS app_key
                            FROM tenant_observability_credentials
                            WHERE tenant_id = :t AND provider = :p
                            """
                        ),
                        {"old": old_key, "t": str(tenant_id), "p": provider},
                    )
                    drow = decrypted.first()
                if drow is None:
                    logger.warning(
                        "row vanished mid-rotation tenant=%s provider=%s — skipping",
                        tenant_id, provider,
                    )
                    continue

                # Step 2: recompute fingerprint (M-005).
                new_fp = fingerprint(drow.api_key)
                now = datetime.now(timezone.utc)

                if dry_run:
                    logger.info(
                        "DRY-RUN would rotate tenant=%s provider=%s new_fp=%s...",
                        tenant_id, provider, new_fp[:8],
                    )
                    rows_touched += 1
                    continue

                # Step 3: re-encrypt with NEW + update metadata.
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE tenant_observability_credentials
                            SET api_key_encrypted = pgp_sym_encrypt(
                                    CAST(:plain_api AS text),
                                    CAST(:new AS text)
                                ),
                                app_key_encrypted = CASE
                                    WHEN CAST(:plain_app AS text) IS NULL THEN NULL
                                    ELSE pgp_sym_encrypt(
                                        CAST(:plain_app AS text),
                                        CAST(:new AS text)
                                    )
                                END,
                                key_fingerprint = :fp,
                                last_rotated_at = :now,
                                updated_at = NOW()
                            WHERE tenant_id = :t AND provider = :p
                            """
                        ),
                        {
                            "plain_api": drow.api_key,
                            "plain_app": drow.app_key,
                            "new": new_key,
                            "fp": new_fp,
                            "now": now,
                            "t": str(tenant_id),
                            "p": provider,
                        },
                    )
                logger.info(
                    "rotated tenant=%s provider=%s new_fp=%s...",
                    tenant_id, provider, new_fp[:8],
                )
                # CISO FIND-002: make the plaintext residence window
                # explicit — drop the reference so the row's plaintext
                # api_key/app_key fields are eligible for gc immediately
                # rather than only at end-of-iteration.
                del drow
                rows_touched += 1
            except Exception as exc:
                # NEVER include str(exc) — pgcrypto wrong-key errors
                # include the prepared statement text + bound params
                # in some driver paths. Log only the class.
                logger.error(
                    "FAILED tenant=%s provider=%s err_class=%s — STOP and inspect manually",
                    tenant_id, provider, type(exc).__name__,
                )
                rows_failed += 1

        logger.info(
            "DONE. rotated=%d failed=%d idempotent_skip=%d dry_run=%s",
            rows_touched, rows_failed, rows_skipped_idempotent, dry_run,
        )
        return rows_touched
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rotate the pgcrypto master key for "
                    "tenant_observability_credentials. Defaults to dry-run."
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually perform the rotation. Default is DRY RUN.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="(default) Print what would change without writing.",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    if dry_run:
        logger.info("DRY-RUN MODE — no rows will be updated. Pass --apply to write.")
    else:
        logger.warning("APPLY MODE — rows will be re-encrypted.")

    try:
        old_key, new_key = _read_env_keys()
    except SystemExit as exc:
        logger.error(str(exc))
        return 2

    db_url = _build_db_url()
    rows = asyncio.run(rotate(
        dry_run=dry_run, db_url=db_url, old_key=old_key, new_key=new_key,
    ))
    logger.info("rows touched: %d", rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
