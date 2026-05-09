"""FDD-OBS-001 PR 2 — Datadog adapter implementing ObservabilityProvider.

ADR-023 + ADR-025 contract:
  - Three coarse query methods + `health_check`.
  - Every vendor record passes through `strip_pii()` BEFORE mapping into
    `DeployMarker` / `MetricSeries` / `ServiceEntity` (Layer 1).
  - `DeployMarker.triggered_by` is unconditionally None — anti-surveillance.
  - Datadog tag `owner` (or `team`) is the Tier-1 squad signal (ADR-022).

Endpoints used:
  - `GET  /api/v1/validate`          → health check
  - `GET  /api/v1/events`            → deploy events (filtered category=deploy)
  - `GET  /api/v1/query`             → metric time-series
  - `GET  /api/v2/services`          → service catalog (with tags)

Site is bound at construction (validated against `VALID_SITES` allowlist
upstream by `credential_service._ensure_valid_site`); the adapter never
takes a site string from caller-controlled input — it reads what was
already validated and persisted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Final

import httpx

from src.connectors.observability._anti_surveillance import strip_pii
from src.connectors.observability.base import (
    MONITOR_DEFAULT_SEVERITY,
    MONITOR_SEVERITY_MAP,
    DeployMarker,
    MetricSeries,
    MonitorState,
    PulseMetric,
    ServiceEntity,
    TimeWindow,
)

logger = logging.getLogger(__name__)


# Datadog metric DSL — `PulseMetric → DD query template`. The {service}
# placeholder is interpolated by the adapter; never user-controlled.
_METRIC_QUERIES: Final[dict[PulseMetric, str]] = {
    PulseMetric.ERROR_RATE: (
        "sum:trace.servlet.request.errors{{service:{service}}}.as_rate()"
    ),
    PulseMetric.P95_LATENCY_MS: (
        "p95:trace.servlet.request{{service:{service}}}"
    ),
    PulseMetric.P99_LATENCY_MS: (
        "p99:trace.servlet.request{{service:{service}}}"
    ),
    PulseMetric.APDEX: (
        "avg:trace.servlet.request.apdex{{service:{service}}}"
    ),
    PulseMetric.THROUGHPUT_RPS: (
        "sum:trace.servlet.request.hits{{service:{service}}}.as_rate()"
    ),
    PulseMetric.ALERT_COUNT: (
        # DD doesn't have a "count alerts" metric; routes that need this
        # call /api/v1/monitor/search instead. For PR 2 the placeholder is
        # not exercised; PR 4 (rollup worker) wires the dedicated path.
        ""
    ),
}


_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0

# DD `/api/v2/services/definitions` pagination tunables. Page size 100
# is the documented max; defensive cap on page count prevents a runaway
# loop if the API ever returns full pages indefinitely.
_SERVICE_DEFINITION_PAGE_SIZE: Final[int] = 100
_MAX_SERVICE_DEFINITION_PAGES: Final[int] = 50  # 5,000 services hard cap


class DatadogConnectorError(Exception):
    """Raised on auth, rate-limit, or transport failures the caller
    should handle (rather than blow up the request)."""


class DatadogProvider:
    """ObservabilityProvider implementation for Datadog (R2).

    Construction is cheap (no I/O); the first network call happens when
    a method is awaited. Use as an async context manager when possible
    so `httpx.AsyncClient` cleans up.

    Threading: not safe — instantiate once per request scope (NOT
    module-global), since httpx.AsyncClient binds to the active loop.
    """

    provider_id: str = "datadog"

    def __init__(
        self,
        api_key: str,
        site: str,
        app_key: str | None = None,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DatadogProvider requires a non-empty api_key")
        if not site:
            raise ValueError("DatadogProvider requires a non-empty site")

        self._api_key = api_key
        self._app_key = app_key
        self._site = site
        self._base_url = f"https://api.{site}"
        self._owns_client = client is None

        headers = {"DD-API-KEY": api_key, "Accept": "application/json"}
        if app_key:
            headers["DD-APPLICATION-KEY"] = app_key

        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )

    # ---- lifecycle -----------------------------------------------------

    async def __aenter__(self) -> "DatadogProvider":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying client if we own it. No-op when an
        external client was injected (caller owns the lifecycle)."""
        if self._owns_client:
            await self._client.aclose()

    # ---- health check (PR 2 admin endpoint) ----------------------------

    async def health_check(self) -> bool:
        """Verify credentials + site reachable.

        Hits `/api/v1/validate` — DD's documented endpoint for API key
        verification. 200 + `{"valid": true}` → healthy. 403 / 401 →
        invalid key. Network errors → False (non-raising contract per
        ADR-026 graceful degradation).
        """
        try:
            response = await self._client.get("/api/v1/validate")
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(
                "[datadog] health_check unreachable site=%s err=%s",
                self._site, type(exc).__name__,
            )
            return False
        except httpx.HTTPError as exc:
            logger.warning(
                "[datadog] health_check transport error site=%s err=%s",
                self._site, type(exc).__name__,
            )
            return False

        if response.status_code != 200:
            logger.info(
                "[datadog] health_check http=%d site=%s",
                response.status_code, self._site,
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            return False

        return bool(payload.get("valid") is True)

    # ---- catalog -------------------------------------------------------

    async def list_services(self) -> list[ServiceEntity]:
        """Return the service catalog with vendor tags normalized.

        Uses Datadog `GET /api/v2/services/definitions` (the schema-based
        Service Definition catalog) — NOT `/api/v2/services`, which
        requires the paid Service Catalog product. The definitions
        endpoint requires the `apm_service_catalog_read` scope only,
        which is included in standard APM plans.

        Each entry: `data[].attributes.schema` has `dd-service`, `team`,
        optional `tier`, `languages`, `links`.

        Pagination: DD uses `page[number]` + `page[size]`. We page
        until an empty `data` (or hit `_MAX_PAGES` to avoid runaway).

        Anti-surveillance: every record goes through `strip_pii` before
        being mapped into `ServiceEntity`. Vendor-raw is intentionally
        empty in the dataclass to avoid leaking unexpected fields.

        403 surfaces with a hint pointing at the missing scope so
        operators don't have to grep DD docs.
        """
        services: list[ServiceEntity] = []
        page_number = 0

        while page_number < _MAX_SERVICE_DEFINITION_PAGES:
            try:
                response = await self._client.get(
                    "/api/v2/services/definitions",
                    params={
                        "page[size]": _SERVICE_DEFINITION_PAGE_SIZE,
                        "page[number]": page_number,
                    },
                )
            except httpx.HTTPError as exc:
                raise DatadogConnectorError(
                    f"list_services transport: {exc}"
                ) from exc

            if response.status_code == 403:
                raise DatadogConnectorError(
                    "list_services HTTP 403 — Application Key likely missing "
                    "the `apm_service_catalog_read` scope. Edit the App Key in "
                    "Datadog UI (Organization Settings → Application Keys) and "
                    "add Service Catalog read permission."
                )
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise DatadogConnectorError(f"list_services failed: {exc}") from exc

            payload = strip_pii(response.json())
            entries = payload.get("data", []) or []
            if not entries:
                break

            for entry in entries:
                attrs = entry.get("attributes", {}) or {}
                schema = attrs.get("schema", {}) or {}
                languages = schema.get("languages") or []
                services.append(
                    ServiceEntity(
                        service_name=(
                            schema.get("dd-service") or attrs.get("name") or ""
                        ),
                        external_id=str(entry.get("id") or ""),
                        owner_squad=self._normalize_ownership(schema, attrs),
                        repo_url=self._extract_repo_url(schema),
                        runtime=languages[0] if languages else None,
                        tier=schema.get("tier"),
                        vendor_raw={},  # never expose unmapped fields
                    )
                )

            # Stop early when the page came back partial — definitive
            # last page even if the API doesn't return pagination metadata.
            if len(entries) < _SERVICE_DEFINITION_PAGE_SIZE:
                break
            page_number += 1

        return services

    @staticmethod
    def _normalize_ownership(schema: dict, attrs: dict) -> str | None:
        """Tier-1 squad inference (ADR-022) — reads `team` then `owner`
        from the dd-service schema. Anything else → None (Tier-2 takes
        over later).

        The team string IS NOT a person identifier (it's a squad/group
        name like "checkout"), but we still pass it through `strip_pii`
        upstream as a defense-in-depth measure.
        """
        team = schema.get("team") or attrs.get("team")
        if team and isinstance(team, str) and team.strip():
            return team.strip()
        return None

    @staticmethod
    def _extract_repo_url(schema: dict) -> str | None:
        """Pull a github URL from dd-service schema's `links` array if
        present. Vendor format: `[{"name": "...", "type": "repo", "url": ...}]`."""
        for link in schema.get("links", []) or []:
            if not isinstance(link, dict):
                continue
            if (link.get("type") or "").lower() == "repo":
                url = link.get("url")
                if isinstance(url, str) and url.startswith("https://"):
                    return url
        return None

    # ---- deployments ---------------------------------------------------

    async def list_deployments(
        self,
        since: datetime,
        until: datetime,
        service: str | None = None,
    ) -> list[DeployMarker]:
        """List deployment events in [since, until).

        Datadog deploys land as events with `category=deploy` (the
        official Datadog deployment marker convention). We page over
        `/api/v1/events` then map → DeployMarker.

        Anti-surveillance: `triggered_by` is unconditionally None, even
        if the event payload has `author_email` / `author_name`.
        """
        params: dict[str, Any] = {
            "start": int(since.timestamp()),
            "end": int(until.timestamp()),
            "category": "deploy",
        }
        if service:
            params["tags"] = f"service:{service}"

        try:
            response = await self._client.get("/api/v1/events", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DatadogConnectorError(f"list_deployments failed: {exc}") from exc

        payload = strip_pii(response.json())
        deploys: list[DeployMarker] = []
        for event in payload.get("events", []) or []:
            tags = event.get("tags", []) or []
            svc = self._tag_value(tags, "service") or service or ""
            if not svc:
                continue
            deploys.append(
                DeployMarker(
                    external_id=str(event.get("id") or ""),
                    service=svc,
                    deployed_at=datetime.fromtimestamp(
                        int(event.get("date_happened") or 0), tz=timezone.utc,
                    ),
                    version=self._tag_value(tags, "version"),
                    git_sha=self._tag_value(tags, "git.commit.sha"),
                    triggered_by=None,  # anti-surveillance: always None
                    vendor_raw={},
                )
            )
        return deploys

    @staticmethod
    def _tag_value(tags: list[str], key: str) -> str | None:
        """Datadog tag format: `key:value`. Returns the FIRST value or
        None if the key isn't present."""
        prefix = f"{key}:"
        for tag in tags:
            if isinstance(tag, str) and tag.startswith(prefix):
                return tag[len(prefix):]
        return None

    # ---- metrics -------------------------------------------------------

    async def query_metric(
        self,
        metric: PulseMetric,
        service: str,
        window: TimeWindow,
    ) -> MetricSeries:
        """Query a single PULSE-normalized metric for one service.

        PULSE never builds raw DD query strings from user input — the DSL
        templates are static (`_METRIC_QUERIES`) and only the service name
        (validated server-side as a service catalog entry) is interpolated.
        """
        template = _METRIC_QUERIES.get(metric)
        if not template:
            return MetricSeries(metric=metric, service=service, points=[], has_data=False)

        query = template.format(service=service)
        params = {
            "from": int(window.start.timestamp()),
            "to": int(window.end.timestamp()),
            "query": query,
        }

        try:
            response = await self._client.get("/api/v1/query", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DatadogConnectorError(f"query_metric failed: {exc}") from exc

        payload = strip_pii(response.json())
        series_list = payload.get("series", []) or []
        if not series_list:
            return MetricSeries(metric=metric, service=service, points=[], has_data=False)

        # DD `series[0].pointlist` is `[[ts_ms, value], ...]`.
        first_series = series_list[0]
        points: list[tuple[datetime, float]] = []
        for ts_ms, value in first_series.get("pointlist", []) or []:
            try:
                points.append(
                    (
                        datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc),
                        float(value),
                    )
                )
            except (TypeError, ValueError):
                continue

        return MetricSeries(
            metric=metric,
            service=service,
            points=points,
            has_data=bool(points),
            stale=False,
        )

    # ---- monitors (FDD-OBS-001 PR 4a.5 — Query API fallback) -----------

    async def list_monitors_for_service(
        self, service: str,
    ) -> list[MonitorState]:
        """List all DD monitors that target a given service tag, with
        their current state normalized to a PULSE severity score.

        Used as the fallback signal when the tenant's DD plan doesn't
        include the Query API (RISK-19). Hits `/api/v1/monitor` with
        `monitor_tags=service:<name>` filter. NEVER reads `creator`,
        `notification` or `message` fields (those carry author emails
        + Slack handles + on-call rotations — anti-surveillance).

        Pagination: DD returns up to 1000 monitors per page (default
        50). For Webmotors at ~100 services × ~10 monitors avg, that's
        ~1000 monitors — within one page. Defensive cap at 5 pages
        (5000 monitors) just in case.

        404 → empty list (no monitors for this service yet).
        Other HTTP errors → DatadogConnectorError (caller decides
        whether to skip or fail the cycle).
        """
        per_page = 100
        max_pages = 5
        results: list[MonitorState] = []

        for page in range(max_pages):
            params = {
                "monitor_tags": f"service:{service}",
                "page_size": per_page,
                "page": page,
            }
            try:
                response = await self._client.get("/api/v1/monitor", params=params)
            except httpx.HTTPError as exc:
                raise DatadogConnectorError(
                    f"list_monitors_for_service transport: {exc}"
                ) from exc

            if response.status_code == 404:
                # No monitors for this service tag — clean empty.
                break
            if response.status_code == 403:
                # Different from query_metric: monitors are usually
                # included in APM Pro. A 403 here is unusual; surface
                # the hint so operators know to grant `monitors_read`.
                raise DatadogConnectorError(
                    "list_monitors_for_service HTTP 403 — Application Key "
                    "likely missing the `monitors_read` scope. Edit the "
                    "App Key in Datadog UI and add Monitors read permission."
                )
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise DatadogConnectorError(
                    f"list_monitors_for_service failed: {exc}"
                ) from exc

            payload = strip_pii(response.json())
            # DD returns a list directly (not wrapped in `data:`) for v1.
            entries = payload if isinstance(payload, list) else []
            if not entries:
                break

            for monitor in entries:
                results.append(self._build_monitor_state(monitor, service))

            # If page came back partial, no more pages.
            if len(entries) < per_page:
                break

        return results

    @staticmethod
    def _build_monitor_state(monitor: dict, service: str) -> MonitorState:
        """Project a DD monitor dict (post strip_pii) onto MonitorState.

        DD v1 monitor schema:
          - `id` (int)
          - `name` (string)
          - `overall_state` ('OK'|'Warn'|'Alert'|'No Data'|...)
          - `modified` (ISO timestamp)
          - `tags` (list — already filtered by monitor_tags query)

        We DELIBERATELY skip:
          - `creator` (carries name + email — RISK-17)
          - `message` (carries on-call mentions / paging routes — PII)
          - `notification` (Slack handles, emails)
          - `query` (carries internal DD query DSL — not PII but noisy)
          - `options.notify_audit`, etc. (config, not state)
        """
        state_str = monitor.get("overall_state") or "No Data"
        severity = MONITOR_SEVERITY_MAP.get(state_str, MONITOR_DEFAULT_SEVERITY)

        last_modified: datetime | None = None
        modified_raw = monitor.get("modified")
        if modified_raw:
            try:
                # DD modified timestamps are ISO-8601 with offset
                last_modified = datetime.fromisoformat(
                    str(modified_raw).replace("Z", "+00:00"),
                )
            except ValueError:
                last_modified = None

        return MonitorState(
            monitor_id=int(monitor.get("id") or 0),
            name=str(monitor.get("name") or "")[:200],  # cap length
            service=service,
            severity=severity,
            state=str(state_str),
            last_modified=last_modified,
            vendor_raw={},  # never expose unmapped fields
        )
