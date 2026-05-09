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
    async def test_uses_service_definitions_endpoint(self):
        """list_services hits /api/v2/services/definitions (schema-based
        catalog), NOT /api/v2/services (paid Service Catalog product)."""
        captured: list[httpx.Request] = []

        def handler(request):
            captured.append(request)
            return _json_response({"data": []})

        provider = _make_provider(handler)
        await provider.list_services()
        assert len(captured) >= 1
        assert captured[0].url.path == "/api/v2/services/definitions"

    @pytest.mark.asyncio
    async def test_extracts_team_into_owner_squad(self):
        """`schema.team` is the Tier-1 squad signal (ADR-022)."""
        def handler(request):
            return _json_response({
                "data": [
                    {
                        "id": "svc-checkout",
                        "type": "service-definition",
                        "attributes": {
                            "schema": {
                                "schema-version": "v2.2",
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

    @pytest.mark.asyncio
    async def test_403_includes_app_key_scope_hint(self):
        """Live-caught (PR 3 smoke 2026-05-07): DD returns 403 when the
        Application Key lacks `apm_service_catalog_read`. Adapter must
        decorate the error so operators don't have to grep DD docs."""
        def handler(request):
            return _json_response({"errors": ["forbidden"]}, status=403)

        provider = _make_provider(handler)
        with pytest.raises(DatadogConnectorError, match="apm_service_catalog_read"):
            await provider.list_services()

    @pytest.mark.asyncio
    async def test_pagination_loops_until_partial_page(self):
        """DD pages by `page[number]`. Loop continues until a page returns
        fewer than page_size entries — stops cleanly even when DD doesn't
        report pagination metadata."""
        from src.connectors.observability.datadog_connector import (
            _SERVICE_DEFINITION_PAGE_SIZE,
        )

        def _make_entries(count: int, prefix: str) -> list[dict]:
            return [
                {
                    "id": f"{prefix}-{i}",
                    "attributes": {
                        "schema": {"dd-service": f"svc-{prefix}-{i}", "team": prefix},
                    },
                }
                for i in range(count)
            ]

        # Page 0: full page (= page_size). Page 1: partial → stop.
        page_responses = [
            _make_entries(_SERVICE_DEFINITION_PAGE_SIZE, "p0"),
            _make_entries(7, "p1"),
        ]
        call_count = {"n": 0}

        def handler(request):
            n = call_count["n"]
            call_count["n"] += 1
            page_num_param = request.url.params.get("page[number]")
            assert page_num_param == str(n), f"expected page[number]={n}, got {page_num_param}"
            return _json_response({"data": page_responses[n] if n < len(page_responses) else []})

        provider = _make_provider(handler)
        services = await provider.list_services()
        assert len(services) == _SERVICE_DEFINITION_PAGE_SIZE + 7
        assert call_count["n"] == 2  # stops after partial page

    @pytest.mark.asyncio
    async def test_pagination_stops_on_empty_page(self):
        """Empty data array on first page → 0 services, no further calls."""
        call_count = {"n": 0}

        def handler(request):
            call_count["n"] += 1
            return _json_response({"data": []})

        provider = _make_provider(handler)
        services = await provider.list_services()
        assert services == []
        assert call_count["n"] == 1


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


# ---------------------------------------------------------------------------
# list_monitors_for_service (FDD-OBS-001 PR 4a.5 — Query API fallback)
# ---------------------------------------------------------------------------


class TestListMonitorsForService:
    @pytest.mark.asyncio
    async def test_filters_by_service_tag(self):
        captured: list[httpx.Request] = []

        def handler(request):
            captured.append(request)
            return _json_response([])

        provider = _make_provider(handler)
        await provider.list_monitors_for_service("checkout-api")

        assert len(captured) >= 1
        assert captured[0].url.path == "/api/v1/monitor"
        # `monitor_tags=service:<name>` is the documented DD filter for
        # narrowing monitors to a specific service.
        assert "service:checkout-api" in captured[0].url.params.get("monitor_tags")

    @pytest.mark.asyncio
    async def test_maps_overall_state_to_pulse_severity(self):
        """OK→0.0, Warn→1.0, Alert→2.0, No Data→3.0."""
        def handler(request):
            return _json_response([
                {"id": 1, "name": "OK monitor", "overall_state": "OK"},
                {"id": 2, "name": "Warn monitor", "overall_state": "Warn"},
                {"id": 3, "name": "Alert monitor", "overall_state": "Alert"},
                {"id": 4, "name": "No data monitor", "overall_state": "No Data"},
            ])

        provider = _make_provider(handler)
        monitors = await provider.list_monitors_for_service("svc")

        assert len(monitors) == 4
        sev = {m.monitor_id: m.severity for m in monitors}
        assert sev[1] == 0.0
        assert sev[2] == 1.0
        assert sev[3] == 2.0
        assert sev[4] == 3.0

    @pytest.mark.asyncio
    async def test_unknown_state_falls_back_to_no_data_severity(self):
        """Defensive — DD has occasionally added new states; unknown
        ones are treated as No Data (severity=3.0)."""
        def handler(request):
            return _json_response([
                {"id": 1, "name": "future state", "overall_state": "QuantumSuperposition"},
            ])

        provider = _make_provider(handler)
        monitors = await provider.list_monitors_for_service("svc")
        assert monitors[0].severity == 3.0

    @pytest.mark.asyncio
    async def test_strips_pii_from_creator_and_message(self):
        """ADR-025 / RISK-17: monitor payload typically includes
        `creator.{name,email}` and `message` (oncall mentions). After
        the explicit allowlist in `_build_monitor_state`, MonitorState
        carries no person identifier and `vendor_raw` stays empty."""
        def handler(request):
            return _json_response([
                {
                    "id": 1,
                    "name": "monitor",
                    "overall_state": "OK",
                    "creator": {
                        "name": "Operator Person",
                        "email": "operator@webmotors.com.br",
                    },
                    "message": "@oncall-team alert details",
                },
            ])

        provider = _make_provider(handler)
        monitors = await provider.list_monitors_for_service("svc")

        assert monitors[0].vendor_raw == {}
        ms_str = repr(monitors[0])
        assert "operator@webmotors.com.br" not in ms_str
        assert "@oncall-team" not in ms_str

    @pytest.mark.asyncio
    async def test_403_includes_monitors_read_scope_hint(self):
        """Same UX pattern as the services 403 — operator-friendly hint
        pointing at the missing scope."""
        def handler(request):
            return _json_response({"errors": ["forbidden"]}, status=403)

        provider = _make_provider(handler)
        with pytest.raises(DatadogConnectorError, match="monitors_read"):
            await provider.list_monitors_for_service("svc")

    @pytest.mark.asyncio
    async def test_404_returns_empty_list(self):
        """No monitors for this service tag → clean empty (NOT raise)."""
        def handler(request):
            return _json_response({"errors": ["not found"]}, status=404)

        provider = _make_provider(handler)
        monitors = await provider.list_monitors_for_service("svc")
        assert monitors == []

    @pytest.mark.asyncio
    async def test_pagination_loops_through_full_pages(self):
        """Page 0 returns full (100). Page 1 returns partial → stop."""
        def _make(n: int, page_id: str):
            return [
                {"id": i, "name": f"{page_id}-{i}", "overall_state": "OK"}
                for i in range(n)
            ]

        page_responses = [_make(100, "p0"), _make(5, "p1")]
        call_n = {"i": 0}

        def handler(request):
            i = call_n["i"]
            call_n["i"] += 1
            assert request.url.params.get("page") == str(i)
            return _json_response(page_responses[i])

        provider = _make_provider(handler)
        monitors = await provider.list_monitors_for_service("svc")
        assert len(monitors) == 105
        assert call_n["i"] == 2

    @pytest.mark.asyncio
    async def test_long_monitor_name_capped_at_200_chars(self):
        """Defensive — DD allows 500-char names. We cap at 200 to keep
        log lines + DB rows reasonable."""
        long_name = "X" * 500
        def handler(request):
            return _json_response([
                {"id": 1, "name": long_name, "overall_state": "OK"},
            ])

        provider = _make_provider(handler)
        monitors = await provider.list_monitors_for_service("svc")
        assert len(monitors[0].name) == 200
