"""CISO FIND-001 — regression guard against `logger.exception` in obs code.

`logger.exception(...)` attaches `exc_info=True` under the hood, which
serializes the full traceback — local variable bindings, chained
exceptions via `__traceback__`. Driver-level exceptions (asyncpg) can
carry bound parameter values; that's exactly what the T1.4
`SanitizingExceptionMiddleware` was built to close, but only handles
exceptions that escape the route. Calls to `logger.exception` INSIDE a
handler (or inside a worker's catch-all wrapper) bypass the middleware
entirely and dump raw traceback to logs.

Use `logger.error("... err_class=%s", type(exc).__name__)` instead.

This test fails if anyone re-introduces `logger.exception(` or
`log.exception(` under the observability surface.
"""

from __future__ import annotations

import re
from pathlib import Path


_FORBIDDEN_RE = re.compile(r"\b(?:logger|log)\.exception\s*\(")


def _iter_obs_python_files() -> list[Path]:
    """Same roots as the anti-surveillance scan (T1.6) plus the shared
    exception middleware that all obs traffic flows through."""
    repo_root = Path(__file__).resolve().parents[2]
    roots = [
        repo_root / "src" / "contexts" / "observability",
        repo_root / "src" / "connectors" / "observability",
    ]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)

    workers_root = repo_root / "src" / "workers"
    if workers_root.exists():
        files.extend(
            p for p in workers_root.glob("obs_*.py")
            if "__pycache__" not in p.parts
        )

    middleware = repo_root / "src" / "shared" / "exception_middleware.py"
    if middleware.exists():
        files.append(middleware)

    return files


class TestNoLoggerExceptionInObs:
    def test_no_logger_exception_calls(self) -> None:
        files = _iter_obs_python_files()
        assert len(files) > 0, (
            "No observability files found — test paths broken; "
            "scan would always pass vacuously."
        )

        offenders: list[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                # Strip end-of-line comments so docstrings/comments
                # mentioning `logger.exception` (e.g. the rationale comment
                # next to the fix) don't trigger the guard.
                code = line.split("#", 1)[0]
                if _FORBIDDEN_RE.search(code):
                    offenders.append(f"{path}:{lineno}: {line.strip()}")

        assert not offenders, (
            "Found `logger.exception(...)` calls in observability code "
            "(CISO FIND-001). `exc_info=True` serializes the full traceback "
            "incl. local var bindings; driver excs may carry bound params. "
            "Use `logger.error('... err_class=%s', type(exc).__name__)` "
            "instead.\n\nOffenders:\n  " + "\n  ".join(offenders)
        )
