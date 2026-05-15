"""FDD-OBS-001 PR 1 — ADR-025 Layer 4 anti-surveillance lint.

Source-grep test that scans every Python file under
`src/connectors/observability/` and `src/contexts/observability/`
for forbidden references in CODE (not docstrings/comments). Modeled
on the structural test in `test_mttr_calculation.py::TestAntiSurveillance`.

If a future change introduces business code that reads `user.email`,
`deployment.author`, or any other PII field, this test fails the
build at PR time — before the code can ship.

The forbidden list is duplicated 3 times across the codebase:
  - `connectors/observability/_anti_surveillance.py` (FORBIDDEN_FIELD_NAMES)
  - migration 018's PL/pgSQL function (DB trigger)
  - this test (the lint)

Duplication is INTENTIONAL — defense in depth (ADR-025).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


# Forbidden refs to grep for in code. The strings need to be tokens that
# would only appear in business logic — bare `user.email`, NOT the safer
# names like `email_field`. We strip docstrings/comments before scanning,
# so docs / ADRs that mention these terms don't break the test.
FORBIDDEN_REFS = (
    "user.email",
    "user.id",
    "deployment.author",
    "alert.assignee",
    "incident.assignee",
    "owner.email",
    "ack_by",
    "resolved_by",
    "trace.user_id",
    "rum.user_id",
    "usr.email",
)


# Files allowed to mention these refs in code (the strip-pii utility,
# the test itself, and documentation files). These are the **only**
# legitimate consumers of the forbidden-field literals.
ALLOWLIST = {
    "_anti_surveillance.py",                       # the strip helper
    "test_obs_anti_surveillance.py",               # this test
    "test_strip_pii.py",                           # parametrized strip tests
}


def _strip_strings_and_comments(source: str) -> str:
    """Remove triple-quoted strings, single-line strings, and # comments
    so the scan only sees actual code references.

    Order matters: docstrings first (greedy-safe), then strings, then
    comments. We use a character-by-character walker rather than naive
    regex because regex can't handle nested quotes correctly.
    """
    # Remove triple-quoted strings (docstrings) — both """ and '''
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    source = re.sub(r"'''[\s\S]*?'''", "", source)
    # Remove single-line strings — both " and '
    source = re.sub(r'"[^"\n\\]*(?:\\.[^"\n\\]*)*"', "", source)
    source = re.sub(r"'[^'\n\\]*(?:\\.[^'\n\\]*)*'", "", source)
    # Remove # comments to end-of-line
    source = re.sub(r"#[^\n]*", "", source)
    return source


def _iter_observability_python_files() -> list[Path]:
    """All .py files under the observability roots (excluding __pycache__).

    FDD-OBS-001 T1.6 (RISK-12) — the scan ALSO walks `src/workers/`
    for any file matching `obs_*.py`. The obs-rollup worker is the
    largest moving piece of business logic in the bounded context;
    leaving it out of the scan meant a future regression (e.g. an
    engineer adds `pr.author` to a rollup query) would not be caught
    at PR time. Cheap to widen, defense in depth.
    """
    repo_root = Path(__file__).resolve().parents[2]
    roots = [
        repo_root / "src" / "connectors" / "observability",
        repo_root / "src" / "contexts" / "observability",
    ]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)

    # Worker modules — scan only files matching `obs_*.py` to keep the
    # blast radius narrow (other workers have their own bounded contexts).
    workers_root = repo_root / "src" / "workers"
    if workers_root.exists():
        files.extend(
            p for p in workers_root.glob("obs_*.py")
            if "__pycache__" not in p.parts
        )
    return files


class TestAntiSurveillanceCodeScan:
    def test_observability_modules_have_no_pii_refs(self) -> None:
        """ADR-025 Layer 4: business code under connectors/observability/
        and contexts/observability/ MUST NOT reference forbidden PII
        field names in code (docstrings + comments allowed)."""
        files = _iter_observability_python_files()
        # Sanity — at least the foundation files (PR 1) must be picked up.
        # If this is zero, the test paths are wrong and we'd be silently
        # green for the wrong reason.
        assert len(files) > 0, (
            "No observability Python files found — test paths broken; "
            "scan would always pass vacuously."
        )

        violations: list[tuple[str, str]] = []
        for path in files:
            if path.name in ALLOWLIST:
                continue
            source = path.read_text()
            stripped = _strip_strings_and_comments(source)
            for ref in FORBIDDEN_REFS:
                if ref in stripped:
                    violations.append((str(path), ref))

        assert not violations, (
            "ADR-025 Layer 4 violation — forbidden PII references found in code:\n"
            + "\n".join(f"  {p}: {ref!r}" for p, ref in violations)
        )

    @pytest.mark.parametrize("forbidden_ref", FORBIDDEN_REFS)
    def test_forbidden_ref_present_in_strip_pii_set(self, forbidden_ref: str) -> None:
        """Every entry in FORBIDDEN_REFS must also be in
        FORBIDDEN_FIELD_NAMES (Layer 1) — the lint and the strip
        utility share the same forbidden set."""
        from src.connectors.observability._anti_surveillance import FORBIDDEN_FIELD_NAMES
        assert forbidden_ref in FORBIDDEN_FIELD_NAMES, (
            f"{forbidden_ref!r} is in the lint scan but not in "
            f"FORBIDDEN_FIELD_NAMES — Layer 1 strip wouldn't catch it"
        )


class TestForbiddenSqlColumnsScan:
    """FDD-OBS-001 T1.6 (RISK-13) — guard against observability business
    code introducing SELECTs for individual-level columns from the
    engineering-data tables (`pr.author`, `pr.merge_by`, etc.).

    The engineering-data domain genuinely needs these columns (Lean
    metrics, MTTR pairing). The observability domain MUST NOT — even
    indirectly via JOINs. Scan tier2_inference, rollup_service,
    timeline_service, and any future obs SQL builder.
    """

    def test_no_forbidden_sql_columns_in_observability_code(self) -> None:
        from src.connectors.observability._anti_surveillance import (
            FORBIDDEN_SQL_COLUMNS,
        )

        files = _iter_observability_python_files()
        violations: list[tuple[str, str]] = []
        for path in files:
            if path.name in ALLOWLIST:
                continue
            source = path.read_text()
            stripped = _strip_strings_and_comments(source)
            for col in FORBIDDEN_SQL_COLUMNS:
                if col in stripped:
                    violations.append((str(path), col))

        assert not violations, (
            "ADR-025 Layer 4 (RISK-13) violation — observability code "
            "must not reference individual-level engineering-data "
            "columns:\n"
            + "\n".join(f"  {p}: {col!r}" for p, col in violations)
        )

    def test_forbidden_sql_columns_set_has_expected_entries(self) -> None:
        """Contract: the set MUST contain the five named columns from
        the T1.6 task. Catches accidental removal."""
        from src.connectors.observability._anti_surveillance import (
            FORBIDDEN_SQL_COLUMNS,
        )

        for expected in (
            "pr.author",
            "pr.author_id",
            "pr.merge_by",
            "pr.reviewer",
            "pr.reviewers",
        ):
            assert expected in FORBIDDEN_SQL_COLUMNS, (
                f"{expected!r} missing from FORBIDDEN_SQL_COLUMNS — "
                f"RISK-13 protection partially removed"
            )


class TestNestedPiiPairs:
    """FDD-OBS-001 T1.6 (RISK-17) — Layer 1 `strip_pii` MUST drop
    parent subtrees whose child key is a known PII attribute.

    The original CISO M-001 fix handled `usr.*`, `user.*`, etc.
    T1.6 adds four more shapes we've observed in DD monitor payloads,
    Jira-derived metadata, and GitHub-derived metadata."""

    @pytest.mark.parametrize(
        "parent,child",
        [
            ("creator", "email"),
            ("creator", "name"),
            ("modified_by", "email"),
            ("author", "email"),
        ],
    )
    def test_strip_pii_drops_parent_with_pii_child(
        self, parent: str, child: str,
    ) -> None:
        """`{<parent>: {<child>: "..."}}` MUST be entirely removed."""
        from src.connectors.observability._anti_surveillance import strip_pii

        payload = {"service": "checkout", parent: {child: "leak@x.com"}}
        result = strip_pii(payload)
        assert parent not in result, (
            f"Layer 1 didn't drop {parent!r} subtree even though it "
            f"contains forbidden child {child!r}. "
            f"Result: {result!r}"
        )
        assert result == {"service": "checkout"}

    @pytest.mark.parametrize(
        "parent,child",
        [
            ("creator", "email"),
            ("creator", "name"),
            ("modified_by", "email"),
            ("author", "email"),
        ],
    )
    def test_pair_present_in_forbidden_set(
        self, parent: str, child: str,
    ) -> None:
        """Lock the contract: each pair is in
        `FORBIDDEN_PARENT_CHILD_PAIRS`."""
        from src.connectors.observability._anti_surveillance import (
            FORBIDDEN_PARENT_CHILD_PAIRS,
        )
        assert (parent, child) in FORBIDDEN_PARENT_CHILD_PAIRS

    def test_strip_pii_keeps_safe_neighbours(self) -> None:
        """A `<parent>: {<safe_child>}` payload survives when neither
        the parent nor the pair is forbidden.

        Uses `author` as the parent because `author` is NOT in
        `FORBIDDEN_FIELD_NAMES` (only the pair `("author","email")`
        is forbidden). `creator` / `modified_by` ARE top-level
        forbidden, so they always get dropped regardless of child.
        """
        from src.connectors.observability._anti_surveillance import strip_pii

        # `author` with a safe child key survives.
        payload = {
            "author": {"display_name": "Squad ABC"},  # squad-level, not PII
            "service": "checkout",
        }
        result = strip_pii(payload)
        assert result == {
            "author": {"display_name": "Squad ABC"},
            "service": "checkout",
        }

    def test_top_level_creator_still_dropped_regardless_of_child(self) -> None:
        """`creator` is BOTH a top-level forbidden key AND a forbidden
        parent in `(creator, email)` / `(creator, name)`. The
        top-level rule fires first, so any `creator: {...}` is dropped
        whatever the child contents are.
        """
        from src.connectors.observability._anti_surveillance import strip_pii

        # Even with a safe-looking child, top-level `creator` is forbidden.
        payload = {"creator": {"id": "abc"}, "service": "checkout"}
        result = strip_pii(payload)
        assert "creator" not in result
        assert result == {"service": "checkout"}


class TestPiiTriggerMatchesPythonSet:
    """CISO FIND-004 — contract test: the SQL trigger's forbidden keys
    (migration 023) and the Python `FORBIDDEN_FIELD_NAMES` frozenset
    (connectors/observability/_anti_surveillance.py) must be identical.

    They're kept in lockstep by comments in both files, but no test
    enforces it. They match today (15 keys); the moment someone updates
    one side, the layers silently diverge.

    This test parses the migration as AST (no SQL execution required)
    and asserts set-equality with the Python frozenset.
    """

    def test_migration_023_forbidden_keys_match_python_set(self) -> None:
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "alembic"
            / "versions"
            / "023_obs_pii_trigger_recursive.py"
        )
        assert migration_path.exists(), (
            f"Migration not found at {migration_path}. If it was renamed, "
            f"update this contract test to point at the new file."
        )

        tree = ast.parse(migration_path.read_text(encoding="utf-8"))

        # Find the module-level assignment to `_FORBIDDEN_KEYS`.
        sql_keys: set[str] | None = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_FORBIDDEN_KEYS":
                    if not isinstance(node.value, ast.Tuple):
                        pytest.fail(
                            "_FORBIDDEN_KEYS in migration 023 is no longer a "
                            "tuple literal — update this contract test."
                        )
                    extracted: set[str] = set()
                    for elt in node.value.elts:
                        if not isinstance(elt, ast.Constant) or not isinstance(
                            elt.value, str
                        ):
                            pytest.fail(
                                "Non-string constant in _FORBIDDEN_KEYS tuple — "
                                "unexpected migration shape."
                            )
                        extracted.add(elt.value)
                    sql_keys = extracted
                    break
            if sql_keys is not None:
                break

        assert sql_keys is not None, (
            "Could not locate `_FORBIDDEN_KEYS = (...)` module-level "
            "assignment in migration 023."
        )

        from src.connectors.observability._anti_surveillance import (
            FORBIDDEN_FIELD_NAMES,
        )

        py_keys = set(FORBIDDEN_FIELD_NAMES)

        only_in_sql = sql_keys - py_keys
        only_in_py = py_keys - sql_keys

        assert sql_keys == py_keys, (
            "CISO FIND-004: the SQL trigger forbidden-keys tuple "
            "(migration 023) and Python `FORBIDDEN_FIELD_NAMES` frozenset "
            "(connectors/observability/_anti_surveillance.py) have "
            "drifted. Update BOTH sides simultaneously.\n\n"
            f"  Keys only in SQL trigger: {sorted(only_in_sql) or '(none)'}\n"
            f"  Keys only in Python set:  {sorted(only_in_py) or '(none)'}"
        )
