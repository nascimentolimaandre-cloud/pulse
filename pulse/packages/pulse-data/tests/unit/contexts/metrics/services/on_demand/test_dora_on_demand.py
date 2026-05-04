"""INC-015 — DORA on-demand service against a mocked repository.

Validates that the service correctly maps repo output → domain dataclasses
→ calculator → asdict. No DB. No live session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.contexts.metrics.services.on_demand.dora import compute_dora_on_demand


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _pr(merged_at, deployed_at=None, first_commit_at=None):
    """Minimal PR-like row that domain.PullRequestData can wrap."""
    return SimpleNamespace(
        id="pr-1",
        first_commit_at=first_commit_at,
        first_review_at=None,
        approved_at=None,
        merged_at=merged_at,
        deployed_at=deployed_at,
        title="OKM-1: foo",
        repo="webmotors-private/repo",
        additions=10,
        deletions=2,
        files_changed=1,
        reviewers=[],
    )


def _deploy(deployed_at, is_failure=False, recovery=None):
    return SimpleNamespace(
        deployed_at=deployed_at,
        is_failure=is_failure,
        recovery_time_hours=recovery,
        environment="production",
        repo="repo",
    )


@pytest.fixture
def fake_session_ctx():
    """Patch get_session to yield a mock session — service should never
    instantiate one, but if it did, this catches it."""
    fake = AsyncMock()
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=None)
    return fake


class TestDoraOnDemand:
    @pytest.mark.asyncio
    async def test_passes_squad_filter_through_to_repo(self, fake_session_ctx):
        """squad_key is propagated to MetricsRepository methods."""
        with patch("src.contexts.metrics.services.on_demand.dora.get_session", return_value=fake_session_ctx):
            with patch("src.contexts.metrics.services.on_demand.dora.MetricsRepository") as MockRepo:
                instance = MockRepo.return_value
                instance.get_prs_in_window = AsyncMock(return_value=[])
                instance.get_deployments_by_squad = AsyncMock(return_value=[])

                start = datetime(2026, 4, 1, tzinfo=timezone.utc)
                end = datetime(2026, 4, 30, tzinfo=timezone.utc)
                await compute_dora_on_demand(
                    _TENANT, period_start=start, period_end=end, squad_key="OKM",
                )
                # Squad key was UPPERCASED and forwarded to BOTH fetchers.
                instance.get_prs_in_window.assert_awaited_once()
                instance.get_deployments_by_squad.assert_awaited_once()
                # squad_key is the kwarg
                pr_call = instance.get_prs_in_window.await_args
                deploy_call = instance.get_deployments_by_squad.await_args
                assert pr_call.kwargs.get("squad_key") == "OKM"
                assert deploy_call.kwargs.get("squad_key") == "OKM"

    @pytest.mark.asyncio
    async def test_squad_key_lowercase_input_normalized_to_upper(self, fake_session_ctx):
        with patch("src.contexts.metrics.services.on_demand.dora.get_session", return_value=fake_session_ctx):
            with patch("src.contexts.metrics.services.on_demand.dora.MetricsRepository") as MockRepo:
                instance = MockRepo.return_value
                instance.get_prs_in_window = AsyncMock(return_value=[])
                instance.get_deployments_by_squad = AsyncMock(return_value=[])

                await compute_dora_on_demand(
                    _TENANT,
                    period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
                    period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
                    squad_key="okm",  # lowercase
                )
                assert instance.get_prs_in_window.await_args.kwargs["squad_key"] == "OKM"

    @pytest.mark.asyncio
    async def test_squad_key_none_propagates_as_none(self, fake_session_ctx):
        with patch("src.contexts.metrics.services.on_demand.dora.get_session", return_value=fake_session_ctx):
            with patch("src.contexts.metrics.services.on_demand.dora.MetricsRepository") as MockRepo:
                instance = MockRepo.return_value
                instance.get_prs_in_window = AsyncMock(return_value=[])
                instance.get_deployments_by_squad = AsyncMock(return_value=[])

                await compute_dora_on_demand(
                    _TENANT,
                    period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
                    period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
                    squad_key=None,
                )
                assert instance.get_prs_in_window.await_args.kwargs["squad_key"] is None
                assert instance.get_deployments_by_squad.await_args.kwargs["squad_key"] is None

    @pytest.mark.asyncio
    async def test_returns_dora_dict_shape(self, fake_session_ctx):
        """Output dict must contain the keys the route handler reads from
        (mirrors snapshot.value JSONB layout)."""
        deploys = [
            _deploy(datetime(2026, 4, 5, tzinfo=timezone.utc), is_failure=False),
            _deploy(datetime(2026, 4, 10, tzinfo=timezone.utc), is_failure=True, recovery=2.5),
            _deploy(datetime(2026, 4, 15, tzinfo=timezone.utc), is_failure=False),
        ]
        prs = [
            _pr(
                merged_at=datetime(2026, 4, 5, 12, tzinfo=timezone.utc),
                first_commit_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
                deployed_at=datetime(2026, 4, 5, 14, tzinfo=timezone.utc),
            ),
        ]
        with patch("src.contexts.metrics.services.on_demand.dora.get_session", return_value=fake_session_ctx):
            with patch("src.contexts.metrics.services.on_demand.dora.MetricsRepository") as MockRepo:
                instance = MockRepo.return_value
                instance.get_prs_in_window = AsyncMock(return_value=prs)
                instance.get_deployments_by_squad = AsyncMock(return_value=deploys)

                result = await compute_dora_on_demand(
                    _TENANT,
                    period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
                    period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
                    squad_key="OKM",
                )

        # Sanity: the keys the route handler reads (per _build_dora_response_from_value)
        for required_key in (
            "deployment_frequency_per_day",
            "change_failure_rate",
            "df_level",
        ):
            assert required_key in result, f"missing key {required_key!r}"

    @pytest.mark.asyncio
    async def test_calculator_failure_returns_empty_dict(self, fake_session_ctx):
        """When the domain calculator raises, service returns {} instead of
        bubbling. Same defensive pattern as the home_on_demand legacy."""
        with patch("src.contexts.metrics.services.on_demand.dora.get_session", return_value=fake_session_ctx):
            with patch("src.contexts.metrics.services.on_demand.dora.MetricsRepository") as MockRepo:
                instance = MockRepo.return_value
                instance.get_prs_in_window = AsyncMock(return_value=[])
                instance.get_deployments_by_squad = AsyncMock(return_value=[])

                with patch(
                    "src.contexts.metrics.services.on_demand.dora.calculate_dora_metrics",
                    side_effect=RuntimeError("boom"),
                ):
                    result = await compute_dora_on_demand(
                        _TENANT,
                        period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
                        period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
                        squad_key="OKM",
                    )
                assert result == {}
