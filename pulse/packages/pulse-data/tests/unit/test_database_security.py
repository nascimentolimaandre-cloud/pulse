"""FDD-OBS-001 Phase 1 T1.3 — `_set_tenant` SQL injection regression.

`_set_tenant` is the RLS gatekeeper on every DB session. It previously
used an f-string to splice `tenant_id` into a `SET app.current_tenant
= '...'` statement. That was safe in practice because every call site
typed the argument as `UUID` (which Pydantic enforces upstream), but
the pattern was H-severity-equivalent if a single caller ever passed
an arbitrary string.

This test locks the bound-parameter version (`SELECT set_config(...,
:t, true)`) so the f-string can't be reintroduced without breaking
the build, AND validates the call still works when the input is a
UUID (positive path).

We also assert at the function-signature level that the parameter is
typed `UUID` (defense at the boundary), so a future contributor can't
weaken the type to `str` without a test failure to notice.

Audit summary of OTHER `text(f"...")` sites in `src/`
(grep -rn 'text(f"' src/, 2026-05-11):
  - `src/contexts/metrics/services/flow_health_on_demand.py:450`
      `SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}`
      Splices a module-level INT constant (`3000`). `SET LOCAL` does
      not accept bound parameters in the value position; the value is
      not user-controlled. LEFT AS-IS.
  - `src/contexts/pipeline/routes.py:969`
      Splices pre-built fragment strings (`severity_filter`,
      `before_filter`). Both fragments contain ONLY bound-param
      placeholders (`:s0`, `:before`, etc.) whose names are derived
      from internal counters. The user input flows in as the bound
      VALUE, never as the SQL string. LEFT AS-IS.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from uuid import UUID
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import database


class TestSetTenantUsesBoundParameter:
    def test_set_tenant_signature_typed_uuid(self) -> None:
        """`_set_tenant`'s second parameter MUST be typed `UUID`.

        Weakening to `str` (or removing the annotation) would silently
        re-open the SQL-injection door — bound params save us at SQL
        level but the type system is the first line of defense.
        """
        sig = inspect.signature(database._set_tenant)
        params = sig.parameters
        assert "tenant_id" in params
        annot = params["tenant_id"].annotation
        # annot may be the class UUID or its string form depending on
        # `from __future__ import annotations`. Accept both.
        assert annot in (UUID, "UUID"), (
            f"_set_tenant.tenant_id is typed {annot!r}; must be UUID "
            f"to keep RLS injection-proof at the boundary."
        )

    def test_set_tenant_source_uses_set_config_and_bind(self) -> None:
        """The implementation MUST use `set_config(..., :t, ...)` with
        a bound parameter — NOT an f-string.

        This is a structural test: it greps the function's source. If
        a future contributor reintroduces an f-string (e.g.
        `text(f"SET app.current_tenant = '{tenant_id}'")`), this fails
        loudly at PR time.
        """
        source = inspect.getsource(database._set_tenant)
        # Negative: no f-string literal containing `SET app.current_tenant`
        # nor any other f-string text() call inside the function body.
        forbidden_patterns = [
            r'text\(f"',          # text(f"..."
            r"text\(f'",          # text(f'...'
        ]
        for pat in forbidden_patterns:
            assert not re.search(pat, source), (
                f"_set_tenant uses f-string SQL (pattern {pat!r}). "
                f"FDD-OBS-001 T1.3 reverted; restore the bound-param "
                f"`set_config('app.current_tenant', :t, true)` form."
            )
        # Positive: must use set_config with a bound :t parameter.
        assert "set_config('app.current_tenant'" in source, (
            "_set_tenant no longer calls `set_config('app.current_tenant', ...)` — "
            "ensure RLS still receives the tenant scope."
        )
        assert ":t" in source, (
            "_set_tenant should pass tenant_id as bound parameter `:t`"
        )

    @pytest.mark.asyncio
    async def test_set_tenant_calls_execute_with_bound_param_dict(self) -> None:
        """End-to-end: invoke `_set_tenant` with a mocked session and
        assert the SQL string + parameter dict shape."""
        session = MagicMock()
        session.execute = AsyncMock()

        tid = UUID("11111111-2222-3333-4444-555555555555")
        await database._set_tenant(session, tid)

        session.execute.assert_awaited_once()
        call_args = session.execute.await_args
        # First positional arg is the TextClause; second is the params dict.
        clause = call_args.args[0]
        params = call_args.args[1]

        # Validate the SQL string (TextClause exposes .text).
        assert "set_config" in str(clause), (
            "Expected `set_config(...)` form; got " + str(clause)
        )
        assert ":t" in str(clause)
        # Validate the bound parameter dict.
        assert params == {"t": str(tid)}, (
            f"Expected {{'t': str(tid)}}; got {params!r}"
        )

    @pytest.mark.asyncio
    async def test_set_tenant_rejects_string_with_sql_comment(self) -> None:
        """If a caller smuggles a SQL-injection string past the type
        system (e.g. `Any`-typed call), `_set_tenant` must NOT splice
        it into the SQL.

        With the bound-param form, the malicious string lands as a
        VALUE (and `set_config` will likely fail at the
        PostgreSQL-side parse of the value), never as SQL. This test
        asserts the value path — even with a hostile string, the
        SQL TEXT clause is the same constant.
        """
        session = MagicMock()
        session.execute = AsyncMock()

        # Hostile input: not a real UUID, contains a SQL comment that
        # would terminate the f-string and inject a payload under the
        # OLD implementation.
        hostile = "'; DROP TABLE eng_pull_requests; --"

        # Cast through Any to bypass the type checker (mimics the bad
        # call-site case we're guarding against).
        from typing import Any
        await database._set_tenant(session, hostile)  # type: ignore[arg-type]

        clause_text = str(session.execute.await_args.args[0])
        params = session.execute.await_args.args[1]

        # The SQL clause must be the SAME constant regardless of input.
        assert "DROP TABLE" not in clause_text
        assert clause_text == "SELECT set_config('app.current_tenant', :t, true)"
        # Hostile value lands as a bound parameter (escaped by the driver).
        assert params == {"t": hostile}


class TestNoFStringSqlInOtherSites:
    """Audit lint: list every `text(f"..."` site in `src/` and verify
    it matches the audited exceptions documented in the module
    docstring. New f-string SQL → PR fails."""

    KNOWN_EXCEPTIONS: frozenset[str] = frozenset({
        # Splices a module-level int constant; SET LOCAL doesn't accept
        # bound params in this position.
        "src/contexts/metrics/services/flow_health_on_demand.py",
        # Splices pre-built fragments with bound :s0..:sN placeholders;
        # the user input flows in as the bound VALUE, never the SQL.
        "src/contexts/pipeline/routes.py",
    })

    def test_no_new_fstring_sql_sites_introduced(self) -> None:
        """Walk `src/` and grep for `text(f"` patterns. If a NEW site
        appears that isn't in `KNOWN_EXCEPTIONS`, fail."""
        # The src dir is two levels above this file (tests/unit/...).
        src_root = Path(__file__).resolve().parents[2] / "src"
        assert src_root.exists(), f"src/ not found at {src_root}"

        pattern = re.compile(r"""text\(f["']""")
        offenders: list[str] = []
        for py in src_root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            text = py.read_text()
            if pattern.search(text):
                rel = py.relative_to(src_root.parent).as_posix()
                if rel not in self.KNOWN_EXCEPTIONS:
                    offenders.append(rel)

        assert not offenders, (
            "New `text(f\"...\")` SQL sites found that aren't in the "
            "audited exceptions list. Either rewrite with bound params "
            "or update KNOWN_EXCEPTIONS with justification:\n"
            + "\n".join(f"  - {o}" for o in offenders)
        )
