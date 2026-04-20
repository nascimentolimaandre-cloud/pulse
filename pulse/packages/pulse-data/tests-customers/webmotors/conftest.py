"""Shared fixtures for Webmotors customer tests.

All tests in `tests-customers/webmotors/` are SKIPPED automatically when:
- Postgres is unreachable
- Webmotors tenant has insufficient data (e.g., CI without prod-like fixture)
- `SKIP_CUSTOMER_TESTS=true` env var is set (manual override)

This guarantees customer tests NEVER fail builds due to environment absence —
they either validate the customer's data OR they skip gracefully with a
clear reason message.
"""

from __future__ import annotations

import os
import subprocess

import pytest

TENANT_ID = os.environ.get(
    "WEBMOTORS_TENANT_ID", "00000000-0000-0000-0000-000000000001"
)

MIN_PRS_FOR_TESTS = 1000  # below this threshold, tenant is too small


def _repo_root() -> str:
    path = os.path.abspath(__file__)
    while path != "/":
        if os.path.isdir(os.path.join(path, "pulse")):
            return path
        path = os.path.dirname(path)
    raise RuntimeError("Could not find repo root")


def _psql(query: str, timeout: int = 10) -> str | None:
    cmd = [
        "docker", "compose",
        "-f", os.path.join(_repo_root(), "pulse/docker-compose.yml"),
        "exec", "-T", "postgres",
        "psql", "-U", "pulse", "-d", "pulse",
        "-t", "-A", "-c",
        f"SET app.current_tenant='{TENANT_ID}'; {query}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return None
        lines = [line for line in r.stdout.splitlines() if line.strip()]
        return lines[-1] if lines else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _webmotors_data_available() -> bool:
    """Check if Webmotors tenant has enough data for customer tests."""
    if os.environ.get("SKIP_CUSTOMER_TESTS", "").lower() in ("true", "1", "yes"):
        return False
    result = _psql(
        "SELECT COUNT(*) FROM eng_pull_requests WHERE is_merged = true;"
    )
    if result is None:
        return False
    try:
        return int(result) >= MIN_PRS_FOR_TESTS
    except (ValueError, TypeError):
        return False


# Module-scoped check — runs once per test session
WEBMOTORS_AVAILABLE = _webmotors_data_available()


@pytest.fixture(scope="session")
def webmotors_tenant_id() -> str:
    return TENANT_ID


@pytest.fixture(scope="session")
def psql():
    """Fixture that returns the _psql helper for direct SQL queries."""
    return _psql


# Auto-skip all tests in this tree if Webmotors data unavailable
def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if WEBMOTORS_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(
        reason=(
            "Webmotors customer data not available — tenant has <1000 merged PRs, "
            "DB unreachable, or SKIP_CUSTOMER_TESTS=true is set. "
            "These tests are fail-open by design (see testing-playbook.md §6)."
        )
    )
    for item in items:
        item.add_marker(skip_marker)
