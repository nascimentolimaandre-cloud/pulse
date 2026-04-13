"""Unit tests for Guardrails.

Covers: cap enforcement order, rate budget token bucket, auto-pause at 5 failures,
blocked-immunity invariant.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.contexts.integrations.jira.discovery.guardrails import Guardrails
from tests.unit.contexts.integrations.jira.discovery.conftest import (
    TENANT_ID,
    make_config,
    make_project,
)


# ---------------------------------------------------------------------------
# Project cap enforcement
# ---------------------------------------------------------------------------

class TestEnforceProjectCap:
    @pytest.mark.asyncio
    async def test_cap_pauses_lowest_scoring(self):
        """When over cap, lowest pr_reference_count projects are paused first."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        with patch.object(guardrails._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(max_active_projects=2)

            # Mock active count = 4 (over cap of 2)
            count_mock = MagicMock()
            count_mock.scalar.return_value = 4

            # Mock the select for lowest-scoring projects
            to_pause_mock = MagicMock()
            to_pause_mock.all.return_value = [("LOW1",), ("LOW2",)]

            session.execute = AsyncMock(side_effect=[count_mock, to_pause_mock])

            with patch.object(
                guardrails._repo, "update_project_status", new_callable=AsyncMock
            ) as mock_status:
                with patch.object(
                    guardrails._repo, "append_audit", new_callable=AsyncMock
                ):
                    paused = await guardrails.enforce_project_cap(TENANT_ID)

        assert paused == 2
        # Verify paused projects were the lowest scoring
        paused_keys = {c.args[1] for c in mock_status.call_args_list}
        assert paused_keys == {"LOW1", "LOW2"}

    @pytest.mark.asyncio
    async def test_cap_not_exceeded_no_action(self):
        """When under cap, no projects are paused."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        with patch.object(guardrails._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(max_active_projects=100)

            count_mock = MagicMock()
            count_mock.scalar.return_value = 50
            session.execute = AsyncMock(return_value=count_mock)

            paused = await guardrails.enforce_project_cap(TENANT_ID)

        assert paused == 0

    @pytest.mark.asyncio
    async def test_cap_no_config(self):
        session = AsyncMock()
        guardrails = Guardrails(session)

        with patch.object(guardrails._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = None
            paused = await guardrails.enforce_project_cap(TENANT_ID)

        assert paused == 0


# ---------------------------------------------------------------------------
# Rate budget (token bucket via Redis)
# ---------------------------------------------------------------------------

class TestEnforceRateBudget:
    @pytest.mark.asyncio
    async def test_budget_allowed(self):
        """Token bucket returns 1 (allowed)."""
        session = AsyncMock()
        redis_mock = AsyncMock()
        redis_mock.eval = AsyncMock(return_value=1)
        guardrails = Guardrails(session, redis_client=redis_mock)

        with patch.object(guardrails._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(max_issues_per_hour=20000)
            allowed = await guardrails.enforce_rate_budget(TENANT_ID, 100)

        assert allowed is True

    @pytest.mark.asyncio
    async def test_budget_denied(self):
        """Token bucket returns 0 (denied)."""
        session = AsyncMock()
        redis_mock = AsyncMock()
        redis_mock.eval = AsyncMock(return_value=0)
        guardrails = Guardrails(session, redis_client=redis_mock)

        with patch.object(guardrails._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(max_issues_per_hour=100)
            allowed = await guardrails.enforce_rate_budget(TENANT_ID, 200)

        assert allowed is False

    @pytest.mark.asyncio
    async def test_budget_no_config_allows(self):
        """No config = no guardrails = allow."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        with patch.object(guardrails._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = None
            allowed = await guardrails.enforce_rate_budget(TENANT_ID, 100)

        assert allowed is True

    @pytest.mark.asyncio
    async def test_budget_passes_correct_lua_args(self):
        """Verify the Lua script receives correct bucket parameters."""
        session = AsyncMock()
        redis_mock = AsyncMock()
        redis_mock.eval = AsyncMock(return_value=1)
        guardrails = Guardrails(session, redis_client=redis_mock)

        with patch.object(guardrails._repo, "get_tenant_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = make_config(max_issues_per_hour=10000)
            await guardrails.enforce_rate_budget(TENANT_ID, 500)

        redis_mock.eval.assert_called_once()
        args = redis_mock.eval.call_args
        assert args[0][1] == 1  # number of keys
        assert args[0][2] == f"jira:ratebudget:{TENANT_ID}"
        assert args[0][3] == "500"  # requested
        assert args[0][4] == "10000"  # max_tokens


# ---------------------------------------------------------------------------
# Sync outcome + auto-pause
# ---------------------------------------------------------------------------

class TestRecordSyncOutcome:
    @pytest.mark.asyncio
    async def test_success_resets_failures(self):
        """Successful sync resets consecutive_failures to 0."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        project = make_project("BACK", status="active", consecutive_failures=3)
        with patch.object(guardrails._repo, "get_project", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = project
            with patch.object(
                guardrails._repo, "upsert_project", new_callable=AsyncMock
            ) as mock_upsert:
                await guardrails.record_sync_outcome(TENANT_ID, "BACK", success=True)

        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        assert kwargs.get("consecutive_failures") == 0

    @pytest.mark.asyncio
    async def test_failure_increments_count(self):
        """Each failure increments consecutive_failures."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        project = make_project("BACK", status="active", consecutive_failures=2)
        with patch.object(guardrails._repo, "get_project", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = project
            with patch.object(
                guardrails._repo, "upsert_project", new_callable=AsyncMock
            ) as mock_upsert:
                with patch.object(
                    guardrails._repo, "update_project_status", new_callable=AsyncMock
                ):
                    with patch.object(
                        guardrails._repo, "append_audit", new_callable=AsyncMock
                    ):
                        await guardrails.record_sync_outcome(
                            TENANT_ID, "BACK", success=False, error="timeout",
                        )

        mock_upsert.assert_called_once()
        kwargs = mock_upsert.call_args.kwargs
        assert kwargs.get("consecutive_failures") == 3

    @pytest.mark.asyncio
    async def test_auto_pause_at_5_failures(self):
        """Project is paused after 5 consecutive failures."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        project = make_project("BACK", status="active", consecutive_failures=4)
        with patch.object(guardrails._repo, "get_project", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = project
            with patch.object(
                guardrails._repo, "upsert_project", new_callable=AsyncMock
            ):
                with patch.object(
                    guardrails._repo, "update_project_status", new_callable=AsyncMock
                ) as mock_status:
                    with patch.object(
                        guardrails._repo, "append_audit", new_callable=AsyncMock
                    ) as mock_audit:
                        await guardrails.record_sync_outcome(
                            TENANT_ID, "BACK", success=False, error="500",
                        )

        # Should pause (failures went from 4 to 5)
        mock_status.assert_called_once()
        assert mock_status.call_args.kwargs["status"] == "paused"

        # Should write project_auto_paused audit event
        audit_calls = [c for c in mock_audit.call_args_list if c.kwargs.get("event_type") == "project_auto_paused"]
        assert len(audit_calls) == 1

    @pytest.mark.asyncio
    async def test_blocked_immune_to_sync_outcome(self):
        """Blocked projects are never modified by record_sync_outcome."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        project = make_project("SECURE", status="blocked", consecutive_failures=10)
        with patch.object(guardrails._repo, "get_project", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = project
            with patch.object(
                guardrails._repo, "upsert_project", new_callable=AsyncMock
            ) as mock_upsert:
                await guardrails.record_sync_outcome(
                    TENANT_ID, "SECURE", success=False, error="fail",
                )

        mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_project_not_found(self):
        """Non-existent project is a no-op."""
        session = AsyncMock()
        guardrails = Guardrails(session)

        with patch.object(guardrails._repo, "get_project", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            with patch.object(
                guardrails._repo, "upsert_project", new_callable=AsyncMock
            ) as mock_upsert:
                await guardrails.record_sync_outcome(
                    TENANT_ID, "GHOST", success=False, error="fail",
                )

        mock_upsert.assert_not_called()
