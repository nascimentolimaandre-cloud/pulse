"""FDD-OBS-001 Phase 1 T1.4 — SanitizingExceptionMiddleware tests.

Validates that an exception raised in a route handler:
  1. Is caught by the middleware (returns 500, not propagated).
  2. Logs the exception CLASS name + request method + path + request_id.
  3. Does NOT log the exception's str/repr/args (which may contain
     bound-param values like API keys or pgcrypto master keys).
  4. Returns an opaque JSON body to the client (no internal details).
"""

from __future__ import annotations

import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.shared.exception_middleware import SanitizingExceptionMiddleware


# A fake secret pattern we'll embed in the raised exception's message
# AND in the request path. The test asserts neither leaks into log
# records.
_FAKE_SECRET = "DD-API-KEY=abc123def456ghi789jkl012"
_FAKE_MASTER = "PULSE_OBS_MASTER_KEY=" + "x" * 64


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app wired with ONLY our middleware so the
    test exercises it in isolation."""
    app = FastAPI()
    app.add_middleware(SanitizingExceptionMiddleware)

    @app.get("/boom")
    async def boom() -> dict:
        # The exception message contains a fake secret pattern. Under
        # the OLD behaviour (no middleware) FastAPI would let it bubble
        # and a typical logging.exception() in upstream code would
        # write `str(exc)` to logs. We assert this doesn't happen.
        raise RuntimeError(
            f"asyncpg.DataError: bound param leak [parameters: "
            f"({_FAKE_SECRET}, {_FAKE_MASTER})]"
        )

    @app.get("/ok")
    async def ok() -> dict:
        return {"status": "ok"}

    return app


def test_exception_returns_500_with_opaque_body(caplog) -> None:
    """The middleware catches the exception and returns a 500 with an
    opaque JSON body — no internal exception details bleed through."""
    client = TestClient(_build_app(), raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert "detail" in body
    assert body["detail"] == "Internal server error"
    assert "request_id" in body
    # No traceback, no exception args, no SQL.
    body_text = response.text
    assert _FAKE_SECRET not in body_text, (
        "Fake secret leaked into HTTP response body — middleware failed."
    )


def test_log_record_does_not_contain_exception_message(caplog) -> None:
    """The captured log record contains ONLY the exception class, method,
    path, and request_id. The exception's message (and the fake secret
    pattern within it) MUST NOT appear in any log record."""
    client = TestClient(_build_app(), raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        response = client.get("/boom")

    assert response.status_code == 500
    # Find OUR log record (skip any unrelated framework noise).
    our_records = [
        r for r in caplog.records
        if "RuntimeError" in r.getMessage()
    ]
    assert our_records, (
        "No log record from the middleware. "
        f"All records: {[r.getMessage() for r in caplog.records]!r}"
    )

    # Validate the structured format.
    formatted = " ".join(r.getMessage() for r in our_records)
    assert "RuntimeError" in formatted  # class name OK
    assert "GET" in formatted             # method OK
    assert "/boom" in formatted           # path OK
    assert "request_id=" in formatted

    # Assert the secret does NOT appear anywhere in any log record,
    # including the message, args, or exc_info.
    for record in caplog.records:
        full = (
            record.getMessage()
            + " "
            + str(getattr(record, "args", "") or "")
            + " "
            + str(getattr(record, "exc_info", "") or "")
            + " "
            + str(getattr(record, "exc_text", "") or "")
        )
        assert _FAKE_SECRET not in full, (
            f"Fake secret pattern leaked into log record:\n"
            f"  level={record.levelname}\n"
            f"  logger={record.name}\n"
            f"  message={record.getMessage()!r}\n"
            f"  exc_info={record.exc_info!r}\n"
        )
        assert _FAKE_MASTER not in full, (
            f"Fake master-key pattern leaked into log record:\n  "
            f"{record.getMessage()!r}"
        )


def test_successful_request_passes_through_unchanged() -> None:
    """The middleware does not affect non-exception paths."""
    client = TestClient(_build_app())
    response = client.get("/ok")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_unique_per_invocation() -> None:
    """Each captured 500 gets a fresh request_id (UUID4) so operators
    can correlate the response with the log line."""
    client = TestClient(_build_app(), raise_server_exceptions=False)
    a = client.get("/boom").json()
    b = client.get("/boom").json()
    assert a["request_id"] != b["request_id"]
    # Roughly UUID4-shaped
    assert re.match(r"^[0-9a-f-]{36}$", a["request_id"])
