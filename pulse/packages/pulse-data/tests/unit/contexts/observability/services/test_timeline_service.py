"""FDD-OBS-001 PR 4b — timeline_service unit tests.

Validates:
  - Squad timeline aggregates worst severity per hour, lists deploys.
  - Service timeline returns raw per-service buckets (no aggregation).
  - Default lookback is 7 days.
  - Anti-surveillance: SQL queries DO NOT select `author` column.
  - Empty repos → no deploys (no error).
  - Service with no ownership row → empty result, no error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.contexts.observability.services import timeline_service
from src.contexts.observability.services.timeline_service import (
    DeployMarkerDTO,
    HealthBucket,
    TimelineResponse,
    get_service_timeline,
    get_squad_timeline,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session_cm(execute_results: list) -> MagicMock:
    """Returns an async-context-managed session whose execute returns
    each result in sequence."""
    session = AsyncMock()
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


def _result_with_rows(rows: list) -> MagicMock:
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


def _result_with_first(row) -> MagicMock:
    result = MagicMock()
    result.first = MagicMock(return_value=row)
    result.all = MagicMock(return_value=[row] if row else [])
    return result


# ---------------------------------------------------------------------------
# Squad timeline
# ---------------------------------------------------------------------------


class TestGetSquadTimeline:
    @pytest.mark.asyncio
    async def test_default_lookback_is_7_days(self):
        """When `since` is omitted, the query uses now - 7 days."""
        # 3 SELECTs: ownership repos, buckets, deploys
        ownership_result = _result_with_rows([])
        buckets_result = _result_with_rows([])
        deploys_result = _result_with_rows([])

        # Need 2 sessions: 1 for ownership, 1 for buckets+deploys (2 selects)
        # But _resolve_squad_repos uses its own session, get_squad_timeline
        # uses 2 more. Total: 3 separate get_session() calls.
        sessions: list = []

        def _get_session_factory():
            session = AsyncMock()
            calls = [ownership_result, buckets_result, deploys_result]
            call_idx = {"i": 0}

            async def _execute(stmt, params=None):
                idx = call_idx["i"]
                call_idx["i"] += 1
                # Return whichever is appropriate based on call order
                # across all sessions.
                return calls[len(sessions) - 1] if sessions else ownership_result

            session.execute = _execute
            sessions.append(session)
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=None)
            return cm

        # Cleaner: collect all execute calls' params and assert on `since`
        captured_params: list = []

        async def _capture_execute(stmt, params=None):
            captured_params.append(params)
            n = len(captured_params)
            if n == 1:
                return ownership_result
            if n == 2:
                return buckets_result
            return deploys_result

        session = AsyncMock()
        session.execute = _capture_execute
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(timeline_service, "get_session", return_value=cm):
            await get_squad_timeline(_TENANT, "FID")

        # `since` in the buckets query should be ~7 days before `until`
        buckets_params = captured_params[1]
        delta = buckets_params["until"] - buckets_params["since"]
        assert 6.9 < delta.total_seconds() / 86400 < 7.1  # 7 days ± rounding

    @pytest.mark.asyncio
    async def test_aggregates_worst_severity_per_hour(self):
        """SQL uses MAX(value) so the bucket reflects worst service in
        the hour. Verify the SELECT statement contains MAX."""
        captured_sql: list = []

        async def _capture(stmt, params=None):
            captured_sql.append(str(stmt))
            n = len(captured_sql)
            if n == 1:
                return _result_with_rows([])  # ownership
            if n == 2:
                return _result_with_rows([])  # buckets
            return _result_with_rows([])  # deploys

        session = AsyncMock()
        session.execute = _capture
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(timeline_service, "get_session", return_value=cm):
            await get_squad_timeline(_TENANT, "FID")

        # buckets SQL is the 2nd one
        buckets_sql = captured_sql[1]
        assert "MAX(value)" in buckets_sql
        assert "GROUP BY hour_bucket" in buckets_sql

    @pytest.mark.asyncio
    async def test_anti_surveillance_no_author_column_in_deploys_select(self):
        """ADR-025: deploy markers must NEVER include the `author`
        column. Verify the SELECT lists exact columns and `author` is
        absent."""
        captured_sql: list = []

        async def _capture(stmt, params=None):
            captured_sql.append(str(stmt))
            n = len(captured_sql)
            if n == 1:
                return _result_with_rows([
                    _row(service_name="x", repo_url="https://github.com/wm/checkout"),
                ])
            if n == 2:
                return _result_with_rows([])
            return _result_with_rows([])

        session = AsyncMock()
        session.execute = _capture
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(timeline_service, "get_session", return_value=cm):
            await get_squad_timeline(_TENANT, "FID")

        # Find the deploys SQL (3rd execute)
        deploys_sql = captured_sql[2]
        assert "FROM eng_deployments" in deploys_sql
        # The deploy SQL must NOT mention `author`. (Catches a future
        # refactor that accidentally re-adds the author field.)
        assert "author" not in deploys_sql.lower(), (
            f"Deploys SELECT must not include `author` (anti-surveillance). "
            f"SQL was: {deploys_sql!r}"
        )

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self):
        """No services + no deploys → has_data=False, empty lists."""
        async def _empty(stmt, params=None):
            return _result_with_rows([])

        session = AsyncMock()
        session.execute = _empty
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(timeline_service, "get_session", return_value=cm):
            result = await get_squad_timeline(_TENANT, "FID")

        assert isinstance(result, TimelineResponse)
        assert result.scope == "squad"
        assert result.has_data is False
        assert result.buckets == []
        assert result.deploys == []
        assert result.services_in_squad == 0

    @pytest.mark.asyncio
    async def test_returns_buckets_and_deploys_when_present(self):
        """Happy path: 1 service, 2 buckets, 1 deploy."""
        ts1 = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc)
        deploy_at = datetime(2026, 5, 8, 10, 30, tzinfo=timezone.utc)

        async def _execute(stmt, params=None):
            sql = str(stmt)
            if "service_squad_ownership" in sql and "GROUP BY" not in sql:
                # ownership query
                return _result_with_rows([
                    _row(service_name="checkout", repo_url="https://github.com/wm/checkout"),
                ])
            if "MAX(value)" in sql:
                # buckets
                return _result_with_rows([
                    _row(hour_bucket=ts1, severity=0.0, samples_count=2, metric="monitor_health"),
                    _row(hour_bucket=ts2, severity=2.0, samples_count=2, metric="monitor_health"),
                ])
            if "FROM eng_deployments" in sql:
                return _result_with_rows([
                    _row(
                        deployed_at=deploy_at,
                        repo="wm/checkout",
                        environment="prod",
                        sha="abc123",
                        is_failure=False,
                        url="https://github.com/wm/checkout/actions/runs/1",
                    ),
                ])
            return _result_with_rows([])

        session = AsyncMock()
        session.execute = _execute
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(timeline_service, "get_session", return_value=cm):
            result = await get_squad_timeline(_TENANT, "FID")

        assert result.has_data is True
        assert len(result.buckets) == 2
        assert result.buckets[1].severity == 2.0  # ALERT
        assert len(result.deploys) == 1
        assert result.deploys[0].repo == "wm/checkout"
        assert result.deploys[0].is_failure is False


# ---------------------------------------------------------------------------
# Service timeline
# ---------------------------------------------------------------------------


class TestGetServiceTimeline:
    @pytest.mark.asyncio
    async def test_no_ownership_row_returns_empty_clean(self):
        """Service not in `service_squad_ownership` → empty timeline,
        not an exception."""
        async def _execute(stmt, params=None):
            sql = str(stmt)
            if "service_squad_ownership" in sql and "LIMIT 1" in sql:
                return _result_with_first(None)
            return _result_with_rows([])

        session = AsyncMock()
        session.execute = _execute
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(timeline_service, "get_session", return_value=cm):
            result = await get_service_timeline(_TENANT, "unknown-svc")

        assert result.scope == "service"
        assert result.service == "unknown-svc"
        assert result.has_data is False
        assert result.squad_key is None

    @pytest.mark.asyncio
    async def test_per_service_buckets_no_aggregation(self):
        """Service-level: rows returned as-is (no MAX, no GROUP BY)."""
        captured_sql: list = []
        ts = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)

        async def _execute(stmt, params=None):
            sql = str(stmt)
            captured_sql.append(sql)
            if "service_squad_ownership" in sql and "LIMIT 1" in sql:
                return _result_with_first(_row(
                    service_name="checkout",
                    repo_url="https://github.com/wm/checkout",
                    squad_key="FID",
                ))
            if "obs_metric_snapshots" in sql:
                return _result_with_rows([
                    _row(hour_bucket=ts, value=1.0, samples_count=3, metric="monitor_health"),
                ])
            return _result_with_rows([])

        session = AsyncMock()
        session.execute = _execute
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(timeline_service, "get_session", return_value=cm):
            result = await get_service_timeline(_TENANT, "checkout")

        # Find the buckets SQL (2nd execute call)
        buckets_sql = captured_sql[1]
        # Service-level — no MAX or GROUP BY (just SELECT raw rows)
        assert "MAX(value)" not in buckets_sql
        assert "GROUP BY" not in buckets_sql
        assert result.scope == "service"
        assert len(result.buckets) == 1
        assert result.buckets[0].service == "checkout"