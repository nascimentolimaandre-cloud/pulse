"""FDD-OBS-001 PR 2 H-001 (CISO review).

Regression test for H-001: SQLAlchemy `echo` must NOT be wired to the
app-level `debug` flag. Flipping `DEBUG=true` for an unrelated reason
during a troubleshoot must never enable SQL parameter logging — that
log channel would emit pgcrypto bound params (the plaintext API key
and the master key) every time `credential_service.upsert_credential`
runs.

This test reads the source of `src/database.py` directly and asserts
the engine wiring uses `settings.sqlalchemy_echo`, not `settings.debug`.
A grep-style regression test is the right tool here because the
behavioural surface (does the engine log SQL?) is hard to mock without
spinning up a real Postgres connection — and the value of this guard
is exactly that it rejects a one-line refactor that re-wires it.
"""

from __future__ import annotations

from pathlib import Path

from src.config import Settings


_DATABASE_PY = Path(__file__).resolve().parents[2] / "src" / "database.py"


class TestSqlEchoIsolation:
    def test_settings_has_dedicated_sqlalchemy_echo(self):
        s = Settings()
        # Field exists and defaults to False (independent of `debug`).
        assert hasattr(s, "sqlalchemy_echo"), (
            "Settings must declare `sqlalchemy_echo` separately from `debug`"
        )
        assert s.sqlalchemy_echo is False

    def test_database_engine_does_not_use_debug_for_echo(self):
        """Source-level guard: database.py must not pass
        `echo=settings.debug` to create_async_engine."""
        source = _DATABASE_PY.read_text()
        assert "echo=settings.debug" not in source, (
            "CISO H-001: SQLAlchemy `echo` must not be wired to `debug`. "
            "Use `sqlalchemy_echo` so flipping app debug never logs "
            "pgcrypto bound parameters."
        )
        assert "echo=settings.sqlalchemy_echo" in source, (
            "CISO H-001: expected `echo=settings.sqlalchemy_echo` in "
            "src/database.py to isolate SQL parameter logging from "
            "app-level debug."
        )

    def test_debug_true_does_not_imply_sqlalchemy_echo(self):
        """A sysadmin flipping DEBUG=true must NOT silently enable SQL
        echo (which would log pgcrypto bound params)."""
        s = Settings(debug=True)
        assert s.debug is True
        assert s.sqlalchemy_echo is False
