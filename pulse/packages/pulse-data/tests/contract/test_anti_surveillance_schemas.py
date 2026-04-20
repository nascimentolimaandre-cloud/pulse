"""Anti-surveillance contract gate (QW-5).

Guarantees that no Pydantic response schema exposes individual-author fields
(assignee, author, reporter, committer, email, etc.) in any metric, pipeline
or tenant endpoint.

PULSE is anti-surveillance by design: aggregations are always squad/team/repo/
project-level. Individual developer data is NEVER exposed in metrics payloads.

This test inspects every Pydantic BaseModel declared in:
  - src/contexts/metrics/schemas.py
  - src/contexts/pipeline/schemas.py
  - src/contexts/tenant/schemas.py

And fails if any field name (recursive through nested models) matches a
forbidden pattern.

Why this exists:
- Prevents accidental regression when a future schema migration adds a field
  like `author_name` to an item list
- Runs in CI (unit job) as a blocking PR gate
- Zero external dependencies — pure meta-test on schemas

Classification: PLATFORM (universal, applies to any tenant)
"""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from typing import Any, Type, get_args, get_origin, get_type_hints

import pytest

# This test imports the pulse-data `src.*` modules directly. It must run with
# the pulse-data package root on PYTHONPATH — i.e., inside the pulse-data
# container, or with `cd pulse/packages/pulse-data && pytest`. When run from
# the repo root with plain `pytest`, `src.` isn't discoverable — we skip
# gracefully instead of erroring.
try:
    importlib.import_module("src.contexts.metrics.schemas")
    PULSE_DATA_IMPORTABLE = True
except ImportError:
    PULSE_DATA_IMPORTABLE = False

pytestmark = pytest.mark.skipif(
    not PULSE_DATA_IMPORTABLE,
    reason=(
        "Run this test from pulse/packages/pulse-data/ directory, or inside "
        "the pulse-data container — `src.contexts.*` must be importable."
    ),
)

from pydantic import BaseModel  # noqa: E402 — after skipif guard

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Modules whose *response* schemas must not expose individual-author fields.
# Persistence-layer ORM models (SQLAlchemy) are OUT OF SCOPE — it's legitimate
# to persist `eng_issues.assignee`. What we forbid is EXPOSING that field in
# public metric/pipeline/tenant responses.
SCHEMA_MODULES = [
    "src.contexts.metrics.schemas",
    "src.contexts.pipeline.schemas",
    "src.contexts.tenant.schemas",
]

# Forbidden field names in response schemas.
# Matched case-insensitively against field names (not values).
FORBIDDEN_FIELD_PATTERNS = [
    r"^assignee$",
    r"^assignee_[a-z_]+$",  # assignee_name, assignee_email, assignee_id
    r"^author$",
    r"^author_[a-z_]+$",
    r"^reporter$",
    r"^reporter_[a-z_]+$",
    r"^developer$",
    r"^developer_[a-z_]+$",
    r"^committer$",
    r"^committer_[a-z_]+$",
    r"^user$",
    r"^user_[a-z_]+$",  # user_id, user_email, user_name
    r"^login$",
    r"^email$",
    r"^[a-z_]+_email$",  # e.g. contact_email — cautious by default
]

# Explicit allow-list for cases where a field named like above is legitimate.
# Must include rationale. Empty by default — if you add here, document WHY.
EXPLICIT_ALLOWLIST: set[tuple[str, str]] = {
    # (qualified_schema_name, field_name) — rationale REQUIRED in comment
    #
    # IssueItem and PullRequestItem are raw-data listing schemas exposed by
    # /data/v1/engineering/pull-requests and /data/v1/engineering/issues.
    # These endpoints are for admin/debug/drill-down of specific records,
    # NOT for metric aggregation or dashboards. They mirror eng_issues /
    # eng_pull_requests columns 1:1 for data explorer use cases.
    #
    # CONSTRAINT: these schemas must NOT be consumed by any metric-rendering
    # component in pulse-web. Frontend linting should forbid importing
    # IssueItem/PullRequestItem into dashboard/metric pages.
    ("src.contexts.metrics.schemas.IssueItem", "assignee"),
    ("src.contexts.metrics.schemas.PullRequestItem", "author"),
}

FORBIDDEN_RE = re.compile("|".join(f"({p})" for p in FORBIDDEN_FIELD_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _discover_pydantic_models(module_path: str) -> list[Type[BaseModel]]:
    """Import module and return all Pydantic BaseModel subclasses defined there."""
    module = importlib.import_module(module_path)
    models: list[Type[BaseModel]] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj is BaseModel:
            continue
        if not issubclass(obj, BaseModel):
            continue
        # Only consider models declared in this module (not imported from elsewhere)
        if obj.__module__ != module_path:
            continue
        models.append(obj)
    return models


def _walk_fields(model: Type[BaseModel], visited: set[Type[BaseModel]] | None = None) -> list[tuple[str, Type[BaseModel]]]:
    """Recursively yield (field_name, owning_model) tuples for every field
    accessible through the model's response tree (including nested Pydantic models)."""
    if visited is None:
        visited = set()
    if model in visited:
        return []
    visited.add(model)

    results: list[tuple[str, Type[BaseModel]]] = []
    hints = get_type_hints(model)

    for field_name, field_type in hints.items():
        results.append((field_name, model))

        # Recurse into nested Pydantic models (also inside list[...], dict[...], Optional[...])
        nested_models = _extract_nested_models(field_type)
        for nested in nested_models:
            results.extend(_walk_fields(nested, visited))
    return results


def _extract_nested_models(tp: Any) -> list[Type[BaseModel]]:
    """Return BaseModel types reachable from a type annotation.

    Handles: BaseModel subclass, list[BaseModel], dict[str, BaseModel],
    Optional[BaseModel], Union[BaseModel, None], etc.
    """
    found: list[Type[BaseModel]] = []

    # Direct BaseModel subclass
    if inspect.isclass(tp) and issubclass(tp, BaseModel):
        found.append(tp)
        return found

    # Generic types (list, dict, Optional, Union, etc.)
    origin = get_origin(tp)
    args = get_args(tp)
    if origin is not None and args:
        for arg in args:
            found.extend(_extract_nested_models(arg))
    return found


def _qualified_name(model: Type[BaseModel], field: str) -> str:
    return f"{model.__module__}.{model.__qualname__}.{field}"


def _is_forbidden(field_name: str) -> bool:
    return bool(FORBIDDEN_RE.match(field_name))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_model_fields() -> list[tuple[str, Type[BaseModel], str]]:
    """Collect (qualified_schema_name, model, field_name) for all response schemas."""
    all_fields: list[tuple[str, Type[BaseModel], str]] = []
    for module_path in SCHEMA_MODULES:
        models = _discover_pydantic_models(module_path)
        for model in models:
            for field_name, owner in _walk_fields(model):
                qname = f"{owner.__module__}.{owner.__qualname__}"
                all_fields.append((qname, owner, field_name))
    return all_fields


def test_no_forbidden_fields_in_response_schemas(all_model_fields):
    """No Pydantic response schema may expose individual-author fields."""
    violations: list[str] = []

    for qname, model, field_name in all_model_fields:
        if not _is_forbidden(field_name):
            continue
        # Check allow-list
        if (qname, field_name) in EXPLICIT_ALLOWLIST:
            continue
        violations.append(f"  - {qname}.{field_name}")

    assert not violations, (
        "Anti-surveillance contract violated! The following Pydantic response "
        "schemas expose individual-author fields:\n"
        + "\n".join(violations)
        + "\n\nRationale: PULSE is anti-surveillance by design. All metrics must be "
        "aggregated at squad/team/repo/project level. If this field is truly "
        "needed (e.g. legitimate persistence-layer ORM mirror), add an explicit "
        "entry to EXPLICIT_ALLOWLIST in this test file with a written rationale."
    )


def test_schema_modules_discoverable(all_model_fields):
    """Guarantee the test itself is actually inspecting something.

    Prevents a silent 'pass' if the module paths drift (typo, refactor, etc).
    """
    assert len(all_model_fields) > 0, (
        "No Pydantic models were discovered. Check SCHEMA_MODULES paths."
    )

    # Expected minimum model count — adjust when adding schemas
    MIN_EXPECTED_MODELS = 10
    unique_models = {qname for qname, _, _ in all_model_fields}
    assert len(unique_models) >= MIN_EXPECTED_MODELS, (
        f"Only {len(unique_models)} Pydantic models discovered. "
        f"Expected at least {MIN_EXPECTED_MODELS}. Schema modules may have "
        f"been removed or renamed."
    )


def test_forbidden_patterns_actually_catch_bad_fields():
    """Meta-test: ensure the regex itself works on known-bad examples.

    Defends against accidental regex regression (e.g. someone loosening the
    pattern with no coverage).
    """
    must_block = [
        "assignee",
        "assignee_name",
        "assignee_email",
        "author",
        "author_name",
        "reporter",
        "reporter_id",
        "committer",
        "committer_email",
        "developer",
        "user",
        "user_id",
        "user_email",
        "login",
        "email",
        "contact_email",
    ]
    for name in must_block:
        assert _is_forbidden(name), f"Pattern should block '{name}' but didn't"

    must_allow = [
        "squad_key",
        "squad_name",
        "team_id",
        "project_key",
        "repo",
        "issue_key",
        "title",
        "description",
        "status",
        "age_days",
        "wip_count",
        "lead_time_hours",
        "deploy_frequency_per_day",
        "covered",  # coverage.covered
    ]
    for name in must_allow:
        assert not _is_forbidden(name), f"Pattern should allow '{name}' but blocked"
