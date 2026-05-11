"""FDD-OBS-001 Phase 1 T1.5 — recursive PII trigger smoke test.

Migration 023 hardens `obs_no_pii_in_metadata()` from a top-level-only
`?` check into a recursive walk over the JSONB tree. This integration
test exercises the trigger end-to-end against the live postgres:

  1. Inserts a row with deeply-nested PII like
        `{"deep": {"nested": {"user.email": "x@y.com"}}}`
     and asserts the INSERT raises `check_violation`.
  2. Inserts a row with PII inside a JSONB array element
        `{"items": [{"creator": "bob"}]}`
     and asserts the INSERT raises.
  3. Inserts a row with TOP-LEVEL PII (the migration-018 case)
        `{"user.email": "x@y.com"}`
     to confirm the trigger still blocks the original case.
  4. Inserts a clean row and asserts it succeeds — no false positives.

Uses an isolated `tenant_id` derived from the test run so multiple
test runs don't collide. Rolls back at the end to leave the table
clean.
"""

from __future__ import annotations

import os
import uuid

import psycopg2
import pytest


# Mirrors `_anti_surveillance.FORBIDDEN_FIELD_NAMES`. Adding any of
# these at ANY depth in the metadata JSONB must trigger the guard.
_FORBIDDEN_KEYS = (
    "user", "user_id", "user.id", "user.email",
    "deployment.author", "alert.assignee", "incident.assignee",
    "owner.email", "ack_by", "resolved_by", "creator",
    "modified_by", "trace.user_id", "rum.user_id", "usr.email",
)


@pytest.fixture(scope="module")
def sync_db_url() -> str:
    """Sync DSN to inspect / mutate the schema directly."""
    explicit = os.environ.get("PULSE_DRIFT_TEST_DATABASE_URL")
    if explicit:
        return explicit
    try:
        from src.config import settings
    except ImportError:
        pytest.skip(
            "src.config.settings unimportable — set "
            "PULSE_DRIFT_TEST_DATABASE_URL to run"
        )
    db_url = getattr(settings, "database_url", None)
    if not db_url:
        pytest.skip("settings.database_url not set")
    return (
        db_url
        .replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("+asyncpg", "", 1)
    )


@pytest.fixture
def db_conn(sync_db_url):
    """psycopg2 connection with `app.current_tenant` set so RLS allows
    the test's INSERTs.

    Rolls back any changes at end-of-fixture so the table stays clean.
    """
    conn = psycopg2.connect(sync_db_url)
    tenant_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config('app.current_tenant', %s, true)",
            (str(tenant_id),),
        )
    yield conn, tenant_id
    conn.rollback()
    conn.close()


def _make_row(metadata_sql_literal: str) -> tuple:
    """Build a unique service_squad_ownership row payload."""
    return (
        "datadog",                          # provider
        f"svc-{uuid.uuid4().hex[:12]}",     # service_external_id
        "test-svc",                         # service_name
        metadata_sql_literal,
    )


class TestRecursivePiiTrigger:
    @pytest.mark.parametrize("forbidden_key", _FORBIDDEN_KEYS)
    def test_trigger_blocks_top_level_pii(self, db_conn, forbidden_key):
        """Migration-018 behaviour preserved: top-level forbidden key
        blocks INSERT (every key in the forbidden set)."""
        conn, tenant_id = db_conn
        provider, sid, name, _meta = _make_row("")
        # Build JSON safely via psycopg2 so the dotted-keys don't trip
        # the SQL parser.
        metadata_json = f'{{"{forbidden_key}": "leak@x.com"}}'

        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO service_squad_ownership
                        (tenant_id, provider, service_external_id,
                         service_name, metadata)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (str(tenant_id), provider, sid, name, metadata_json),
                )

    def test_trigger_blocks_deeply_nested_pii(self, db_conn):
        """RISK-7 — the bug migration 023 fixes. A `user.email` buried
        3 levels deep MUST be blocked at INSERT time."""
        conn, tenant_id = db_conn
        provider, sid, name, _ = _make_row("")
        metadata_json = (
            '{"deep": {"nested": {"user.email": "alice@webmotors.com"}}}'
        )
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO service_squad_ownership
                        (tenant_id, provider, service_external_id,
                         service_name, metadata)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (str(tenant_id), provider, sid, name, metadata_json),
                )

    def test_trigger_blocks_pii_inside_array_element(self, db_conn):
        """PII inside a JSONB array element is also caught."""
        conn, tenant_id = db_conn
        provider, sid, name, _ = _make_row("")
        metadata_json = '{"items": [{"creator": "bob"}, {"version": "1.0"}]}'
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO service_squad_ownership
                        (tenant_id, provider, service_external_id,
                         service_name, metadata)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (str(tenant_id), provider, sid, name, metadata_json),
                )

    def test_trigger_allows_clean_metadata(self, db_conn):
        """No false positives — a row with only allowed keys inserts
        cleanly, even at multiple depths."""
        conn, tenant_id = db_conn
        provider, sid, name, _ = _make_row("")
        metadata_json = (
            '{"runtime": "python", "tags": ["prod"], '
            '"settings": {"region": "us-east-1", "tier": "tier-1"}}'
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO service_squad_ownership
                    (tenant_id, provider, service_external_id,
                     service_name, metadata)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (str(tenant_id), provider, sid, name, metadata_json),
            )
            # If the trigger had wrongly raised, the line above would
            # have thrown. Reaching here is the assertion.
            cur.execute(
                "SELECT 1 FROM service_squad_ownership "
                "WHERE tenant_id = %s AND service_external_id = %s",
                (str(tenant_id), sid),
            )
            assert cur.fetchone() == (1,)

    def test_trigger_blocks_pii_in_update(self, db_conn):
        """Trigger fires on UPDATE too — operator can't sneak PII in
        via a later patch."""
        conn, tenant_id = db_conn
        provider, sid, name, _ = _make_row("")
        with conn.cursor() as cur:
            # Clean insert first.
            cur.execute(
                """
                INSERT INTO service_squad_ownership
                    (tenant_id, provider, service_external_id,
                     service_name, metadata)
                VALUES (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (str(tenant_id), provider, sid, name),
            )
            # Update to inject deeply-nested PII → must raise.
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    UPDATE service_squad_ownership
                    SET metadata = %s::jsonb
                    WHERE tenant_id = %s AND provider = %s
                      AND service_external_id = %s
                    """,
                    (
                        '{"layer1": {"creator": "bob"}}',
                        str(tenant_id),
                        provider,
                        sid,
                    ),
                )
