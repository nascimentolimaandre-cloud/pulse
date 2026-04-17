"""Unit tests for tenant capability heuristics.

These test the pure boolean evaluators plus the compute_capabilities path
with a mocked DB session. The goal is to prove:

  * Webmotors scenario (0 sprints, thousands of in-progress issues)
    => has_sprints=False, has_kanban=True.
  * Sprint-heavy tenant (e.g. 12 sprints, 5 in-progress)
    => has_sprints=True, has_kanban=False.
  * Threshold edges: exactly SPRINT_THRESHOLD / KANBAN_THRESHOLD flip the flag.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.contexts.tenant.service import (
    KANBAN_THRESHOLD,
    SPRINT_THRESHOLD,
    _normalize_squad_key,
    compute_capabilities,
    evaluate_has_kanban,
    evaluate_has_sprints,
)


# ---------------------------------------------------------------------------
# Pure heuristic boundary tests
# ---------------------------------------------------------------------------


class TestEvaluateHasSprints:
    def test_zero_sprints_is_false(self) -> None:
        assert evaluate_has_sprints(0) is False

    def test_just_below_threshold_is_false(self) -> None:
        assert evaluate_has_sprints(SPRINT_THRESHOLD - 1) is False

    def test_at_threshold_is_true(self) -> None:
        assert evaluate_has_sprints(SPRINT_THRESHOLD) is True

    def test_way_above_threshold_is_true(self) -> None:
        assert evaluate_has_sprints(100) is True


class TestEvaluateHasKanban:
    def test_zero_in_progress_is_false(self) -> None:
        assert evaluate_has_kanban(0) is False

    def test_just_below_threshold_is_false(self) -> None:
        assert evaluate_has_kanban(KANBAN_THRESHOLD - 1) is False

    def test_at_threshold_is_true(self) -> None:
        assert evaluate_has_kanban(KANBAN_THRESHOLD) is True

    def test_webmotors_scale_is_true(self) -> None:
        # ~18k in-progress issues (Webmotors scale) must always be True
        assert evaluate_has_kanban(18_000) is True


# ---------------------------------------------------------------------------
# compute_capabilities — mocks DB layer via patching session helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


class _FakeSession:
    """Stub async session that returns queued scalar values for execute()."""

    def __init__(self, scalar_values: list[int]) -> None:
        self._scalars = list(scalar_values)

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        value = self._scalars.pop(0)
        result = AsyncMock()
        result.scalar = lambda: value  # sync call — matches SQLAlchemy Result API
        return result


class _FakeCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_webmotors_scenario_has_kanban_no_sprints(tenant_id: uuid.UUID) -> None:
    """Webmotors: 0 sprints, 18234 in-progress issues, 18234 issues in 30d."""
    session = _FakeSession(scalar_values=[0, 18234, 18234])

    with patch("src.contexts.tenant.service.get_session", lambda _tid: _FakeCtx(session)):
        caps = await compute_capabilities(tenant_id)

    assert caps.has_sprints is False
    assert caps.has_kanban is True
    assert caps.sprint_count == 0
    assert caps.issue_count_30d == 18234


@pytest.mark.asyncio
async def test_sprint_heavy_tenant(tenant_id: uuid.UUID) -> None:
    """Sprint-heavy tenant: 12 sprints, only 5 in-progress items."""
    session = _FakeSession(scalar_values=[12, 5, 120])

    with patch("src.contexts.tenant.service.get_session", lambda _tid: _FakeCtx(session)):
        caps = await compute_capabilities(tenant_id)

    assert caps.has_sprints is True
    assert caps.has_kanban is False
    assert caps.sprint_count == 12


@pytest.mark.asyncio
async def test_mixed_tenant_both_flags(tenant_id: uuid.UUID) -> None:
    """Tenant running hybrid Scrum+Kanban: both flags true."""
    session = _FakeSession(scalar_values=[6, 250, 1000])

    with patch("src.contexts.tenant.service.get_session", lambda _tid: _FakeCtx(session)):
        caps = await compute_capabilities(tenant_id)

    assert caps.has_sprints is True
    assert caps.has_kanban is True


class TestNormalizeSquadKey:
    def test_uppercases_valid_key(self) -> None:
        assert _normalize_squad_key("fid") == "FID"

    def test_accepts_digits_after_first_letter(self) -> None:
        assert _normalize_squad_key("A1") == "A1"

    def test_rejects_separator_injection(self) -> None:
        assert _normalize_squad_key("fid;drop") is None
        assert _normalize_squad_key("FID OR 1=1") is None

    def test_rejects_empty_and_too_short(self) -> None:
        assert _normalize_squad_key("") is None
        assert _normalize_squad_key("A") is None  # requires >= 2 chars

    def test_rejects_leading_digit(self) -> None:
        assert _normalize_squad_key("1FID") is None

    def test_strips_whitespace(self) -> None:
        assert _normalize_squad_key("  fid  ") == "FID"


@pytest.mark.asyncio
async def test_db_failure_returns_safe_defaults(tenant_id: uuid.UUID) -> None:
    """If the DB throws, we return has_sprints=False/has_kanban=False — never crash."""
    def _boom(_tid: uuid.UUID):  # noqa: ANN202
        class _Ctx:
            async def __aenter__(self):
                raise RuntimeError("db down")

            async def __aexit__(self, *_):
                return None

        return _Ctx()

    with patch("src.contexts.tenant.service.get_session", _boom):
        caps = await compute_capabilities(tenant_id)

    assert caps.has_sprints is False
    assert caps.has_kanban is False
    assert caps.sprint_count == 0
    assert caps.issue_count_30d == 0
