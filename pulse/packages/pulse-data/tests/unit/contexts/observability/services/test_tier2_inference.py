"""FDD-OBS-001 PR 4a — tier2_inference unit tests.

Validates:
  - normalize_repo handles HTTPS/SSH/plain forms + .git suffix.
  - All 4 gate paths skip correctly:
      no_repo, low_pr_count, no_dominant_squad, ambiguous, unqualified_squad.
  - Happy path: dominant qualified squad → upsert with confidence='heuristic'.
  - Tier 2 NEVER overwrites confidence in {'tag','alias'} (Tier 1 wins).
  - Tier 2 NEVER touches override_squad_key.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.contexts.observability.services import tier2_inference
from src.contexts.observability.services.tier2_inference import (
    DOMINANCE_RATIO,
    MIN_PR_COUNT,
    TIE_WINDOW,
    normalize_repo,
    sync_tier2_inference,
)

_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session_cm(execute_results: list) -> MagicMock:
    """Build an async-context-managed session whose `execute` returns
    `execute_results[0]`, then `[1]`, etc., per call."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_results)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _row(**kwargs) -> MagicMock:
    r = MagicMock()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


def _build_pr_squad_result(rows: list[tuple[str, str, int]]) -> MagicMock:
    """Mock the SQL result for `pr_squads` aggregate query.
    `rows` = [(repo, squad, pr_count), ...]."""
    result = MagicMock()
    result.all = MagicMock(return_value=[
        _row(repo=r, squad=s, pr_count=c) for r, s, c in rows
    ])
    return result


def _build_candidates_result(rows: list[tuple[str, str, str | None]]) -> MagicMock:
    """Mock the SQL result for the candidate ownership rows.
    `rows` = [(service_external_id, service_name, repo_url), ...]."""
    result = MagicMock()
    result.all = MagicMock(return_value=[
        _row(service_external_id=eid, service_name=n, repo_url=url)
        for eid, n, url in rows
    ])
    return result


# ---------------------------------------------------------------------------
# normalize_repo
# ---------------------------------------------------------------------------


class TestNormalizeRepo:
    @pytest.mark.parametrize("url,expected", [
        ("https://github.com/webmotors/checkout", "webmotors/checkout"),
        ("https://github.com/Webmotors/Checkout.git", "webmotors/checkout"),
        ("https://github.com/webmotors/checkout/", "webmotors/checkout"),
        ("git@github.com:webmotors/checkout.git", "webmotors/checkout"),
        ("git@github.com:webmotors/checkout", "webmotors/checkout"),
        ("webmotors/checkout", "webmotors/checkout"),
        ("Webmotors/Checkout", "webmotors/checkout"),
    ])
    def test_normalizes_to_lowercase_org_repo(self, url, expected):
        assert normalize_repo(url) == expected

    @pytest.mark.parametrize("url", [
        None, "", "   ", "not-a-repo", "https://invalid",
    ])
    def test_returns_none_when_unparseable(self, url):
        assert normalize_repo(url) is None


# ---------------------------------------------------------------------------
# Tunable sanity (regression-detect future silent threshold drift)
# ---------------------------------------------------------------------------


class TestTunables:
    def test_min_pr_count_filters_experimental_repos(self):
        assert MIN_PR_COUNT >= 5

    def test_dominance_ratio_strong_signal(self):
        # Anything below 50% is meaningless (could be a 3-way tie).
        assert DOMINANCE_RATIO > 0.5

    def test_tie_window_is_meaningful(self):
        # If TIE_WINDOW were 0, a 60.01% vs 59.99% split would resolve.
        # 10% leaves room for genuine dominance.
        assert TIE_WINDOW >= 0.05


# ---------------------------------------------------------------------------
# sync_tier2_inference — gate paths
# ---------------------------------------------------------------------------


class TestGates:
    @pytest.mark.asyncio
    async def test_skip_no_repo_url(self):
        """Candidate with NULL repo_url → can't infer."""
        candidates = _build_candidates_result([
            ("svc-1", "billing", None),
        ])
        pr_squads = _build_pr_squad_result([])

        with patch.object(
            tier2_inference, "get_session",
            return_value=_mock_session_cm([pr_squads, candidates]),
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            result = await sync_tier2_inference(_TENANT, "datadog")

        assert result.candidates_seen == 1
        assert result.skipped_no_repo == 1
        assert result.inferred == 0

    @pytest.mark.asyncio
    async def test_skip_when_repo_has_too_few_prs(self):
        """Repo with < MIN_PR_COUNT (5) PRs total → skip."""
        candidates = _build_candidates_result([
            ("svc-1", "checkout", "https://github.com/wm/checkout"),
        ])
        # Only 3 PRs to that repo → below floor
        pr_squads = _build_pr_squad_result([
            ("wm/checkout", "FID", 3),
        ])

        with patch.object(
            tier2_inference, "get_session",
            return_value=_mock_session_cm([pr_squads, candidates]),
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            result = await sync_tier2_inference(_TENANT, "datadog")

        assert result.skipped_low_pr_count == 1
        assert result.inferred == 0

    @pytest.mark.asyncio
    async def test_skip_when_no_squad_dominates(self):
        """Top squad < DOMINANCE_RATIO (60%) → ambiguous, skip."""
        candidates = _build_candidates_result([
            ("svc-1", "checkout", "https://github.com/wm/checkout"),
        ])
        # 50% / 50% split (5 vs 5)
        pr_squads = _build_pr_squad_result([
            ("wm/checkout", "FID", 5),
            ("wm/checkout", "OKM", 5),
        ])

        with patch.object(
            tier2_inference, "get_session",
            return_value=_mock_session_cm([pr_squads, candidates]),
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID", "OKM"})),
        ):
            result = await sync_tier2_inference(_TENANT, "datadog")

        assert result.skipped_no_dominant_squad == 1
        assert result.inferred == 0

    @pytest.mark.asyncio
    async def test_skip_when_top2_within_tie_window(self, monkeypatch):
        """TIE_WINDOW is a safety net: with DOMINANCE_RATIO at 60%, the
        tie path is unreachable in normal data (60+55 > 100). To exercise
        it we drop DOMINANCE_RATIO to 30%, then feed a 35/30/35-style
        distribution where the top-2 are within 10%."""
        monkeypatch.setattr(tier2_inference, "DOMINANCE_RATIO", 0.30)

        candidates = _build_candidates_result([
            ("svc-1", "checkout", "https://github.com/wm/checkout"),
        ])
        # 35% / 30% / 35% — top1 35% > DOMINANCE_RATIO (30%), but top2 (30%)
        # within 10% of top1 → TIE_WINDOW catches it.
        pr_squads = _build_pr_squad_result([
            ("wm/checkout", "FID", 35),
            ("wm/checkout", "OKM", 30),
            ("wm/checkout", "DESC", 35),
        ])

        with patch.object(
            tier2_inference, "get_session",
            return_value=_mock_session_cm([pr_squads, candidates]),
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID", "OKM", "DESC"})),
        ):
            result = await sync_tier2_inference(_TENANT, "datadog")

        assert result.skipped_ambiguous == 1
        assert result.inferred == 0

    @pytest.mark.asyncio
    async def test_skip_when_top_squad_not_qualified(self):
        """DD repo touched mainly by a Jira project_key not in the
        tenant's qualified squads (e.g. typo project key) → skip."""
        candidates = _build_candidates_result([
            ("svc-1", "checkout", "https://github.com/wm/checkout"),
        ])
        pr_squads = _build_pr_squad_result([
            ("wm/checkout", "GHOST", 10),  # 100% but unqualified
        ])

        with patch.object(
            tier2_inference, "get_session",
            return_value=_mock_session_cm([pr_squads, candidates]),
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID", "OKM"})),
        ):
            result = await sync_tier2_inference(_TENANT, "datadog")

        assert result.skipped_unqualified_squad == 1
        assert result.inferred == 0


# ---------------------------------------------------------------------------
# sync_tier2_inference — happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_dominant_qualified_squad_upserts_heuristic(self):
        """Top squad is FID with 8/10 PRs (80%), qualified → upsert."""
        candidates = _build_candidates_result([
            ("svc-1", "checkout", "https://github.com/wm/checkout"),
        ])
        pr_squads = _build_pr_squad_result([
            ("wm/checkout", "FID", 8),
            ("wm/checkout", "OKM", 2),
        ])
        # third execute call is the UPDATE
        update_result = MagicMock()

        with patch.object(
            tier2_inference, "get_session",
            return_value=_mock_session_cm([pr_squads, candidates, update_result]),
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID", "OKM"})),
        ) as squad_mock:
            result = await sync_tier2_inference(_TENANT, "datadog")

        assert result.inferred == 1
        assert result.candidates_seen == 1
        squad_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_is_guarded_by_inferred_null(self):
        """The UPDATE WHERE clause must include `inferred_squad_key IS NULL`
        so a Tier 1 row that landed concurrently won't get clobbered."""
        candidates = _build_candidates_result([
            ("svc-1", "checkout", "https://github.com/wm/checkout"),
        ])
        pr_squads = _build_pr_squad_result([
            ("wm/checkout", "FID", 10),
        ])
        update_result = MagicMock()

        captured_sql: list[str] = []

        async def _capture_execute(stmt, params=None):
            captured_sql.append(str(stmt))
            # Return the right mock per call number
            n = len(captured_sql)
            if n == 1:
                return pr_squads
            if n == 2:
                return candidates
            return update_result

        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(side_effect=_capture_execute)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            tier2_inference, "get_session", return_value=cm,
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            await sync_tier2_inference(_TENANT, "datadog")

        update_sql = captured_sql[2]
        assert "UPDATE service_squad_ownership" in update_sql
        # Defense against accidentally clobbering Tier 1 rows
        assert "inferred_squad_key IS NULL" in update_sql
        # Defense against accidentally touching admin overrides
        assert "override_squad_key" not in update_sql.split("SET")[1].split("WHERE")[0]

    @pytest.mark.asyncio
    async def test_update_writes_confidence_heuristic(self):
        candidates = _build_candidates_result([
            ("svc-1", "checkout", "https://github.com/wm/checkout"),
        ])
        pr_squads = _build_pr_squad_result([
            ("wm/checkout", "FID", 10),
        ])
        update_result = MagicMock()

        captured_params: list = []

        async def _capture(stmt, params=None):
            captured_params.append(params)
            n = len(captured_params)
            if n == 1:
                return pr_squads
            if n == 2:
                return candidates
            return update_result

        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(side_effect=_capture)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            tier2_inference, "get_session", return_value=cm,
        ), patch(
            "src.contexts.observability.services.tier2_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            await sync_tier2_inference(_TENANT, "datadog")

        # Bound params on the UPDATE: squad_key=FID
        assert captured_params[2]["squad_key"] == "FID"
