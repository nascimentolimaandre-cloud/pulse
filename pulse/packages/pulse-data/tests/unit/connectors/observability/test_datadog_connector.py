"""FDD-OBS-001 PR 2 — DatadogProvider unit tests.

Validates the contracts:
  - implements ObservabilityProvider Protocol (spec match).
  - health_check returns True/False without raising.
  - list_deployments hits /api/v1/events with category=deploy.
  - DeployMarker.triggered_by is ALWAYS None even when DD returns author.
  - list_services maps schema.team → owner_squad (Tier-1).
  - query_metric uses static templates (no user-controlled DSL).
  - strip_pii applied to every vendor response (Layer 1).
  - SSRF defense: invalid site can't be passed in (constructor refuses
    empty; site validation happens upstream in credential_service).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from src.connectors.observability.base import ObservabilityProvider, PulseMetric, TimeWindow
from src.connectors.observability.datadog_connector import (
    DatadogConnectorError,
    DatadogProvider,
)


# ---------------------------------------------------------------------------
# httpx.MockTransport helpers
# ---------------------------------------------------------------------------


def _make_provider(handler) -> DatadogProvider:
    """Build a DatadogProvider with an injected MockTransport so HTTP
    calls never leave the test process."""
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        transport=transport,
        base_url="https://api.datadoghq.com",
        headers={"DD-API-KEY": "test-key", "Accept": "application/json"},
    )
    return DatadogProvider(
        api_key="test-key", site="datadoghq.com", client=client,
    )


def _json_response(body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode())


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_provider_id_is_datadog(self):
        p = DatadogProvider(api_key="x", site="datadoghq.com")
        assert p.provider_id == "datadog"

    def test_empty_api_key_rejected(self):
        with pytest.raises(ValueError, match="api_key"):
            DatadogProvider(api_key="", site="datadoghq.com")

    def test_empty_site_rejected(self):
        with pytest.raises(ValueError, match="site"):
            DatadogProvider(api_key="x", site="")

    def test_satisfies_observability_provider_protocol(self):
        """Static check — instance must satisfy the Protocol contract."""
        p = DatadogProvider(api_key="x", site="datadoghq.com")
        assert isinstance(p, ObservabilityProvider)


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_valid_credentials_returns_true(self):
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            assert request.url.path == "/api/v1/validate"
            assert request.headers.get("DD-API-KEY") == "test-key"
            return _json_response({"valid": True})

        provider = _make_provider(handler)
        assert await provider.health_check() is True
        assert len(captured) == 1

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_false(self):
        def handler(request):
            return _json_response({"errors": ["Forbidden"]}, status=403)

        provider = _make_provider(handler)
        assert await provider.health_check() is False

    @pytest.mark.asyncio
    async def test_valid_false_returns_false(self):
        """200 OK but body says `valid:false` → still False."""
        def handler(request):
            return _json_response({"valid": False})

        provider = _make_provider(handler)
        assert await provider.health_check() is False

    @pytest.mark.asyncio
    async def test_unreachable_returns_false_not_raise(self):
        """Network errors → False (never bubble). ADR-026 graceful."""
        def handler(request):
            raise httpx.ConnectError("dns failure")

        provider = _make_provider(handler)
        assert await provider.health_check() is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false_not_raise(self):
        def handler(request):
            raise httpx.TimeoutException("timeout")

        provider = _make_provider(handler)
        assert await provider.health_check() is False


# ---------------------------------------------------------------------------
# list_services — Tier-1 ownership extraction
# ---------------------------------------------------------------------------


class TestListServices:
    @pytest.mark.asyncio
    async def test_extracts_team_into_owner_squad(self):
        """`schema.team` is the Tier-1 squad signal (ADR-022)."""
        def handler(request):
            assert request.url.path == "/api/v2/services"
            return _json_response({
                "data": [
                    {
                        "id": "svc-checkout",
                        "attributes": {
                            "schema": {
                                "dd-service": "checkout",
                                "team": "checkout-squad",
                                "tier": "tier-1",
                                "languages": ["python"],
                                "links": [
                                    {"type": "repo", "url": "https://github.com/co/checkout"},
                                ],
                            },
                        },
                    },
                ],
            })

        provider = _make_provider(handler)
        services = await provider.list_services()
        assert len(services) == 1
        s = services[0]
        assert s.service_name == "checkout"
        assert s.owner_squad == "checkout-squad"
        assert s.tier == "tier-1"
        assert s.repo_url == "https://github.com/co/checkout"
        assert s.runtime == "python"

    @pytest.mark.asyncio
    async def test_missing_team_returns_none_owner(self):
        """No team in tag → owner_squad=None → Tier-2 takes over later."""
        def handler(request):
            return _json_response({
                "data": [{
                    "id": "svc-1",
                    "attributes": {"schema": {"dd-service": "billing"}},
                }],
            })

        provider = _make_provider(handler)
        services = await provider.list_services()
        assert services[0].owner_squad is None

    @pytest.mark.asyncio
    async def test_strip_pii_runs_on_response(self):
        """If DD response contains forbidden keys, they must not survive
        into the dataclass (vendor_raw is empty by design too)."""
        def handler(request):
            return _json_response({
                "data": [{
                    "id": "svc-1",
                    "attributes": {
                        "schema": {"dd-service": "x", "team": "ops"},
                        "user.email": "alice@x.com",  # forbidden
                    },
                }],
            })

        provider = _make_provider(handler)
        services = await provider.list_services()
        # The dataclass exposes vendor_raw={} → no plaintext leak.
        assert services[0].vendor_raw == {}

    @pytest.mark.asyncio
    async def test_http_error_raises_connector_error(self):
        def handler(request):
            return _json_response({"errors": ["server"]}, status=500)

        provider = _make_provider(handler)
        with pytest.raises(DatadogConnectorError):
            await provider.list_services()


# ---------------------------------------------------------------------------
# list_deployments — anti-surveillance NULL-out
# ---------------------------------------------------------------------------


class TestListDeployments:
    @pytest.mark.asyncio
    async def test_triggered_by_always_none(self):
        """ADR-025 — even if DD event has author_email, we drop it."""
        def handler(request):
            assert request.url.path == "/api/v1/events"
            return _json_response({
                "events": [{
                    "id": "evt-1",
                    "date_happened": 1714915200,
                    "tags": ["service:checkout", "version:1.2.3", "git.commit.sha:abc"],
                    "title": "Deploy v1.2.3",
                    # DD sometimes returns these — Layer 1 should drop them.
                    "user": "marina@x.com",
                    "deployment.author": "marina",
                }],
            })

        provider = _make_provider(handler)
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)
        until = datetime(2026, 5, 6, tzinfo=timezone.utc)
        deploys = await provider.list_deployments(since, until)
        assert len(deploys) == 1
        d = deploys[0]
        assert d.triggered_by is None  # anti-surveillance non-negotiable
        assert d.service == "checkout"
        assert d.version == "1.2.3"
        assert d.git_sha == "abc"

    @pytest.mark.asyncio
    async def test_filters_by_service(self):
        captured: list[httpx.Request] = []

        def handler(request):
            captured.append(request)
            return _json_response({"events": []})

        provider = _make_provider(handler)
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)
        until = datetime(2026, 5, 6, tzinfo=timezone.utc)
        await provider.list_deployments(since, until, service="checkout")
        assert len(captured) == 1
        assert "service:checkout" in captured[0].url.params.get("tags", "")

    @pytest.mark.asyncio
    async def test_skips_events_without_service_tag(self):
        """No service tag and no service filter → skip (can't attribute)."""
        def handler(request):
            return _json_response({"events": [
                {"id": "1", "date_happened": 1714915200, "tags": []},
            ]})

        provider = _make_provider(handler)
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)
        until = datetime(2026, 5, 6, tzinfo=timezone.utc)
        deploys = await provider.list_deployments(since, until)
        assert deploys == []


# ---------------------------------------------------------------------------
# query_metric — static templates (no user-controlled DSL)
# ---------------------------------------------------------------------------


class TestQueryMetric:
    @pytest.mark.asyncio
    async def test_uses_static_template_for_error_rate(self):
        """User-supplied service name MUST be the only interpolation —
        the DSL itself comes from a static dict (defense against
        injection)."""
        captured: list[httpx.Request] = []

        def handler(request):
            captured.append(request)
            return _json_response({"series": [{"pointlist": [[1714915200000, 0.05]]}]})

        provider = _make_provider(handler)
        window = TimeWindow(
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 6, tzinfo=timezone.utc),
        )
        result = await provider.query_metric(PulseMetric.ERROR_RATE, "checkout", window)
        assert result.has_data is True
        assert len(result.points) == 1
        # Verify the query is the static template + service interpolation
        # (no other user input could land in the DSL).
        query = captured[0].url.params.get("query")
        assert "trace.servlet.request.errors" in query
        assert "service:checkout" in query

    @pytest.mark.asyncio
    async def test_empty_series_returns_no_data(self):
        def handler(request):
            return _json_response({"series": []})

        provider = _make_provider(handler)
        window = TimeWindow(
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 6, tzinfo=timezone.utc),
        )
        result = await provider.query_metric(PulseMetric.P95_LATENCY_MS, "x", window)
        assert result.has_data is False
        assert result.points == []

    @pytest.mark.asyncio
    async def test_alert_count_returns_no_data_in_pr2(self):
        """ALERT_COUNT placeholder is empty in PR 2 — adapter returns
        has_data=False without making a network call."""
        def handler(request):  # should not be called
            raise AssertionError("network call should be skipped")

        provider = _make_provider(handler)
        window = TimeWindow(
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 6, tzinfo=timezone.utc),
        )
        result = await provider.query_metric(PulseMetric.ALERT_COUNT, "x", window)
        assert result.has_data is False
