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
    """All .py files under the two observability roots (excluding __pycache__)."""
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
