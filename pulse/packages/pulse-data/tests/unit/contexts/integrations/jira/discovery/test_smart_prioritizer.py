"""Unit tests for SmartPrioritizer.

Covers: regex extraction, scoring aggregation, threshold gating,
auto_activate only in smart mode.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contexts.integrations.jira.discovery.smart_prioritizer import (
    SmartPrioritizer,
    _extract_project_prefixes,
)
from tests.unit.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    make_config,
    make_project,
)


# ---------------------------------------------------------------------------
# Regex extraction unit tests
# ---------------------------------------------------------------------------

class TestExtractProjectPrefixes:
    def test_single_key(self):
        assert _extract_project_prefixes("feat(BACK-123): fix login") == {"BACK"}

    def test_multiple_keys(self):
        result = _extract_project_prefixes("BACK-1 DESC-42 ENO-100")
        assert result == {"BACK", "DESC", "ENO"}

    def test_duplicate_keys_same_prefix(self):
        result = _extract_project_prefixes("BACK-1 BACK-2 BACK-3")
        assert result == {"BACK"}

    def test_no_match(self):
        assert _extract_project_prefixes("fix: update readme") == set()

    def test_empty_string(self):
        assert _extract_project_prefixes("") == set()

    def test_none(self):
        assert _extract_project_prefixes(None) == set()

    def test_key_in_branch_name(self):
        result = _extract_project_prefixes("feature/BACK-123-user-auth")
        assert result == {"BACK"}

    def test_alphanumeric_prefix(self):
        result = _extract_project_prefixes("CK2-45 and A1B-99")
        assert result == {"CK2", "A1B"}

    def test_lowercase_not_matched(self):
        result = _extract_project_prefixes("back-123")
        assert result == set()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestScoreProjects:
    @pytest.mark.asyncio
    async def test_score_aggregates_unique_prs(self):
        """Each PR counts once per prefix, even with multiple keys."""
        session = AsyncMock()
        prioritizer = SmartPrioritizer(session)

        # Mock config
        with patch.object(prioritizer._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(smart_pr_scan_days=90)

            # Mock PR query: 3 PRs referencing BACK, 1 referencing DESC
            rows = [
                ("pr-1", "feat(BACK-1): something"),
                ("pr-2", "fix(BACK-2, DESC-10): other"),
                ("pr-3", "BACK-3 in title"),
            ]
            result_mock = MagicMock()
            result_mock.all.return_value = rows
            session.execute = AsyncMock(return_value=result_mock)

            with patch.object(prioritizer._repo, "upsert_project", new_callable=AsyncMock) as mock_upsert:
                scores = await prioritizer.score_projects(TENANT_ID)

        assert scores["BACK"] == 3
        assert scores["DESC"] == 1
        assert mock_upsert.call_count == 2  # One per prefix

    @pytest.mark.asyncio
    async def test_score_empty_prs(self):
        """No PRs -> empty scores."""
        session = AsyncMock()
        prioritizer = SmartPrioritizer(session)

        with patch.object(prioritizer._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config()
            result_mock = MagicMock()
            result_mock.all.return_value = []
            session.execute = AsyncMock(return_value=result_mock)

            with patch.object(prioritizer._repo, "upsert_project", new_callable=AsyncMock):
                scores = await prioritizer.score_projects(TENANT_ID)

        assert scores == {}


# ---------------------------------------------------------------------------
# Auto-activate
# ---------------------------------------------------------------------------

class TestAutoActivate:
    @pytest.mark.asyncio
    async def test_auto_activate_in_smart_mode(self):
        """Discovered projects above threshold get activated."""
        session = AsyncMock()
        prioritizer = SmartPrioritizer(session)

        with patch.object(prioritizer._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="smart", smart_min_pr_references=3)

            candidates = [
                make_project("BACK", status="discovered", pr_reference_count=10),
                make_project("DESC", status="discovered", pr_reference_count=1),
                make_project("ENO", status="discovered", pr_reference_count=5),
            ]
            with patch.object(
                prioritizer._repo, "list_projects", new_callable=AsyncMock
            ) as mock_list:
                mock_list.return_value = (candidates, len(candidates))

                with patch.object(
                    prioritizer._repo, "update_project_status", new_callable=AsyncMock
                ) as mock_update:
                    activated = await prioritizer.auto_activate(TENANT_ID)

        # BACK (10) and ENO (5) meet threshold 3; DESC (1) does not
        assert activated == 2
        assert mock_update.call_count == 2
        activated_keys = {call.args[1] for call in mock_update.call_args_list}
        assert activated_keys == {"BACK", "ENO"}

    @pytest.mark.asyncio
    async def test_auto_activate_skips_non_smart_mode(self):
        """auto_activate is a no-op when mode is not smart."""
        session = AsyncMock()
        prioritizer = SmartPrioritizer(session)

        with patch.object(prioritizer._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="allowlist")
            activated = await prioritizer.auto_activate(TENANT_ID)

        assert activated == 0

    @pytest.mark.asyncio
    async def test_auto_activate_no_config(self):
        session = AsyncMock()
        prioritizer = SmartPrioritizer(session)

        with patch.object(prioritizer._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = None
            activated = await prioritizer.auto_activate(TENANT_ID)

        assert activated == 0

    @pytest.mark.asyncio
    async def test_auto_activate_uses_smart_pr_scan_source(self):
        """Verify activation_source is 'smart_pr_scan'."""
        session = AsyncMock()
        prioritizer = SmartPrioritizer(session)

        with patch.object(prioritizer._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(mode="smart", smart_min_pr_references=1)

            candidates = [make_project("BACK", status="discovered", pr_reference_count=5)]
            with patch.object(prioritizer._repo, "list_projects", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = (candidates, 1)
                with patch.object(
                    prioritizer._repo, "update_project_status", new_callable=AsyncMock
                ) as mock_update:
                    await prioritizer.auto_activate(TENANT_ID)

        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args
        assert call_kwargs.kwargs.get("source") == "smart_pr_scan"
        assert call_kwargs.kwargs.get("actor") == "smart_auto"
