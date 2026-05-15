"""FDD-OBS-001 Phase 1 T1.4 — Driver-level exception sanitization middleware.

CISO H-002 wired `hide_parameters=True` on the SQLAlchemy engine, which
strips bound-parameter values from EXCEPTION messages that SA itself
formats. But asyncpg / psycopg sometimes raise BEFORE SA gets a chance
to wrap the exception (e.g. on protocol-level mishaps, AmbiguousParameter
errors that bubble up via `__cause__`, or `DataError` at the driver
parse step). Those raw exceptions can contain the prepared statement
text + parameter VALUES — which for `credential_service.upsert_credential`
includes the pgcrypto master key and the plaintext API key.

This middleware sits at the FastAPI boundary and:
  1. Catches every unhandled `Exception` (after FastAPI's own handlers).
  2. Logs a SANITIZED record — exception class name, request method,
     path, and a sanitized identifier. NEVER `str(exc)`, `repr(exc)`,
     `exc.args`, or any traceback (which may include argspec).
  3. Returns a clean opaque 500 to the client.

Pattern is intentionally OPINIONATED: we don't try to be clever
("redact the bits that look like secrets, log the rest"). The
exception MESSAGE is treated as untrusted bytes and dropped wholesale.
If an operator needs to debug, they get the exception class + the
request shape + the timestamp, and can correlate against the
service's own structured logs (which are subject to the existing
`hide_parameters=True` + `_anti_surveillance.py` controls).

Defense in depth — does NOT replace `hide_parameters=True`. Both layers
must remain in place.
"""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class SanitizingExceptionMiddleware(BaseHTTPMiddleware):
    """Catches uncaught exceptions and emits a SANITIZED log line +
    opaque 500.

    The log line format:

        [<class_name>] <METHOD> <PATH> request_id=<uuid>

    Notably absent: the exception message, args, traceback, or any
    derivative of `str(exc)`. The class name alone (`asyncpg.exceptions.AmbiguousParameterError`)
    plus the request shape is enough for an operator to grep + reproduce.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            return await call_next(request)
        except StarletteHTTPException:
            # CISO FIND-003: FastAPI's HTTPException subclasses Starlette's.
            # Catching bare Exception below would swallow legitimate 4xx
            # (Pydantic 422, InvalidSiteError 422, get_provider_metadata
            # 404, rotation 503) and convert them to opaque sanitized 500s.
            # Let FastAPI's default handler emit the proper status + detail.
            raise
        except Exception as exc:
            request_id = str(uuid.uuid4())
            # IMPORTANT: NEVER include str(exc), repr(exc), exc.args, or
            # exc_info — any of those can leak bound parameter values.
            logger.error(
                "[%s] %s %s request_id=%s",
                type(exc).__name__,
                request.method,
                request.url.path,
                request_id,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "request_id": request_id,
                },
            )
