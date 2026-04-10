"""Unit tests for ResilientHTTPClient.

Tests the retry logic, rate-limit handling, pagination, and auth configuration
without making any real HTTP calls. All network I/O is replaced by AsyncMock
patching httpx.AsyncClient.request.

Key behaviours under test:
- Successful GET/POST returns parsed JSON.
- 429 responses trigger a wait (honouring Retry-After / X-RateLimit-Reset)
  and then retry.
- 5xx responses trigger exponential backoff and retry.
- 4xx responses (except 429) raise httpx.HTTPStatusError immediately.
- Timeout / connection errors trigger backoff retry.
- Exhausting all retries raises ConnectionError.
- Link-header pagination (GitHub-style) aggregates pages correctly.
- Offset-based pagination (Jira-style) aggregates pages correctly.
- Auth config produces the correct Authorization header / BasicAuth.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.shared.http_client import ResilientHTTPClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int,
    json_data: Any = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a mock httpx.Response with the minimum API surface used by the client."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = httpx.Headers(headers or {})
    response.json.return_value = json_data if json_data is not None else {}
    response.request = MagicMock(spec=httpx.Request)

    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=response.request,
            response=response,
        )
    else:
        response.raise_for_status.return_value = None

    return response


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestResilientHTTPClient:
    """Tests for ResilientHTTPClient: retry, rate-limit, pagination, auth."""

    # ------------------------------------------------------------------
    # Successful requests
    # ------------------------------------------------------------------

    async def test_get_returns_parsed_json(self) -> None:
        """A 200 GET response returns the parsed JSON body directly."""
        payload = [{"id": 1, "title": "PR Alpha"}, {"id": 2, "title": "PR Beta"}]
        mock_response = _make_response(200, payload)

        async with ResilientHTTPClient(base_url="https://api.example.com") as client:
            with patch.object(client._client, "request", new=AsyncMock(return_value=mock_response)):
                result = await client.get("/pulls")

        assert result == payload

    async def test_post_sends_json_body_and_returns_parsed_json(self) -> None:
        """A 201 POST encodes json_body and returns parsed JSON."""
        request_body = {"title": "New PR", "base": "main"}
        response_payload = {"id": 99, "status": "open"}
        mock_response = _make_response(201, response_payload)

        async with ResilientHTTPClient(base_url="https://api.example.com") as client:
            with patch.object(
                client._client, "request", new=AsyncMock(return_value=mock_response)
            ) as mock_req:
                result = await client.post("/pulls", json_body=request_body)

        assert result == response_payload
        call_kwargs = mock_req.call_args
        assert call_kwargs.kwargs.get("json") == request_body or (
            len(call_kwargs.args) >= 4 and call_kwargs.args[3] == request_body
        )

    # ------------------------------------------------------------------
    # Rate limiting (429)
    # ------------------------------------------------------------------

    async def test_retries_on_429_with_retry_after_header(self) -> None:
        """On 429 with Retry-After header the client sleeps the specified seconds then retries."""
        rate_limit_response = _make_response(429, headers={"Retry-After": "5"})
        ok_response = _make_response(200, {"data": "ok"})

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(side_effect=[rate_limit_response, ok_response])
            with (
                patch.object(client._client, "request", new=mock_request),
                patch("src.shared.http_client.asyncio.sleep", new=AsyncMock()) as mock_sleep,
            ):
                result = await client.get("/endpoint")

        assert result == {"data": "ok"}
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once_with(5.0)

    async def test_retries_on_429_with_x_rate_limit_reset_header(self) -> None:
        """On 429 with X-RateLimit-Reset (Unix timestamp) the client waits until reset time."""
        future_reset = str(int(time.time()) + 10)  # 10 seconds from now
        rate_limit_response = _make_response(429, headers={"X-RateLimit-Reset": future_reset})
        ok_response = _make_response(200, {"data": "ok"})

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(side_effect=[rate_limit_response, ok_response])
            with (
                patch.object(client._client, "request", new=mock_request),
                patch("src.shared.http_client.asyncio.sleep", new=AsyncMock()) as mock_sleep,
            ):
                result = await client.get("/endpoint")

        assert result == {"data": "ok"}
        assert mock_request.call_count == 2
        # sleep was called with a positive wait duration derived from the reset timestamp
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg >= 1.0  # _parse_retry_after enforces max(wait, 1.0)

    # ------------------------------------------------------------------
    # 5xx retry with exponential backoff
    # ------------------------------------------------------------------

    async def test_retries_on_server_error_with_backoff(self) -> None:
        """5xx responses trigger exponential backoff; success on the third attempt."""
        server_error_500 = _make_response(500)
        server_error_503 = _make_response(503)
        ok_response = _make_response(200, {"data": "recovered"})

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(side_effect=[server_error_500, server_error_503, ok_response])
            with (
                patch.object(client._client, "request", new=mock_request),
                patch("src.shared.http_client.asyncio.sleep", new=AsyncMock()) as mock_sleep,
            ):
                result = await client.get("/endpoint")

        assert result == {"data": "recovered"}
        assert mock_request.call_count == 3
        # Backoff calls: attempt 1 → 1.0s, attempt 2 → 2.0s
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 2.0

    # ------------------------------------------------------------------
    # 4xx — no retry
    # ------------------------------------------------------------------

    async def test_raises_immediately_on_non_retryable_4xx(self) -> None:
        """404 and other 4xx (except 429) raise HTTPStatusError without retrying."""
        not_found = _make_response(404)

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(return_value=not_found)
            with patch.object(client._client, "request", new=mock_request):
                with pytest.raises(httpx.HTTPStatusError):
                    await client.get("/missing")

        # Must not retry — only one call
        assert mock_request.call_count == 1

    async def test_raises_immediately_on_401_unauthorized(self) -> None:
        """401 is not retried; raises HTTPStatusError immediately."""
        unauthorized = _make_response(401)

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(return_value=unauthorized)
            with patch.object(client._client, "request", new=mock_request):
                with pytest.raises(httpx.HTTPStatusError):
                    await client.get("/secure")

        assert mock_request.call_count == 1

    # ------------------------------------------------------------------
    # Timeout retry
    # ------------------------------------------------------------------

    async def test_retries_on_timeout_with_backoff(self) -> None:
        """TimeoutException triggers retry with exponential backoff."""
        timeout_error = httpx.TimeoutException("timed out")
        ok_response = _make_response(200, {"data": "ok"})

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(side_effect=[timeout_error, timeout_error, ok_response])
            with (
                patch.object(client._client, "request", new=mock_request),
                patch("src.shared.http_client.asyncio.sleep", new=AsyncMock()) as mock_sleep,
            ):
                result = await client.get("/slow")

        assert result == {"data": "ok"}
        assert mock_request.call_count == 3
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_calls[0] == 1.0  # attempt 1: base * 2^0
        assert sleep_calls[1] == 2.0  # attempt 2: base * 2^1

    # ------------------------------------------------------------------
    # Connection error retry
    # ------------------------------------------------------------------

    async def test_retries_on_connection_error_with_backoff(self) -> None:
        """ConnectError triggers retry with exponential backoff."""
        conn_error = httpx.ConnectError("refused")
        ok_response = _make_response(200, {"data": "ok"})

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(side_effect=[conn_error, ok_response])
            with (
                patch.object(client._client, "request", new=mock_request),
                patch("src.shared.http_client.asyncio.sleep", new=AsyncMock()) as mock_sleep,
            ):
                result = await client.get("/endpoint")

        assert result == {"data": "ok"}
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once_with(1.0)

    # ------------------------------------------------------------------
    # Retries exhausted
    # ------------------------------------------------------------------

    async def test_raises_connection_error_when_all_retries_exhausted(self) -> None:
        """ConnectionError is raised after max_retries consecutive failures."""
        conn_error = httpx.ConnectError("refused")

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(side_effect=conn_error)
            with (
                patch.object(client._client, "request", new=mock_request),
                patch("src.shared.http_client.asyncio.sleep", new=AsyncMock()),
            ):
                with pytest.raises(ConnectionError) as exc_info:
                    await client.get("/unreachable")

        assert "3 attempts" in str(exc_info.value)
        assert mock_request.call_count == 3

    async def test_raises_connection_error_after_exhausted_5xx_retries(self) -> None:
        """ConnectionError is raised when every attempt returns a 5xx."""
        server_error = _make_response(503)

        async with ResilientHTTPClient(base_url="https://api.example.com", max_retries=3) as client:
            mock_request = AsyncMock(return_value=server_error)
            with (
                patch.object(client._client, "request", new=mock_request),
                patch("src.shared.http_client.asyncio.sleep", new=AsyncMock()),
            ):
                with pytest.raises(ConnectionError):
                    await client.get("/unstable")

        assert mock_request.call_count == 3

    # ------------------------------------------------------------------
    # Link-header pagination (GitHub-style)
    # ------------------------------------------------------------------

    async def test_get_paginated_link_follows_next_links(self) -> None:
        """get_paginated_link aggregates items from all pages by following rel=next."""
        page1 = MagicMock(spec=httpx.Response)
        page1.status_code = 200
        page1.headers = httpx.Headers(
            {"Link": '<https://api.example.com/pulls?page=2>; rel="next"'}
        )
        page1.json.return_value = [{"id": 1}, {"id": 2}]
        page1.raise_for_status.return_value = None

        page2 = MagicMock(spec=httpx.Response)
        page2.status_code = 200
        page2.headers = httpx.Headers({})  # No Link header — last page
        page2.json.return_value = [{"id": 3}]
        page2.raise_for_status.return_value = None

        async with ResilientHTTPClient(base_url="https://api.example.com") as client:
            mock_request = AsyncMock(side_effect=[page1, page2])
            with patch.object(client._client, "request", new=mock_request):
                result = await client.get_paginated_link("/pulls", page_size=2)

        assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert mock_request.call_count == 2

    async def test_get_paginated_link_stops_when_page_not_full(self) -> None:
        """get_paginated_link stops early when a page has fewer items than page_size."""
        page1 = MagicMock(spec=httpx.Response)
        page1.status_code = 200
        page1.headers = httpx.Headers(
            {"Link": '<https://api.example.com/pulls?page=2>; rel="next"'}
        )
        page1.json.return_value = [{"id": 1}]  # Only 1 item, page_size=5 → stop
        page1.raise_for_status.return_value = None

        async with ResilientHTTPClient(base_url="https://api.example.com") as client:
            mock_request = AsyncMock(return_value=page1)
            with patch.object(client._client, "request", new=mock_request):
                result = await client.get_paginated_link("/pulls", page_size=5)

        assert result == [{"id": 1}]
        assert mock_request.call_count == 1

    async def test_get_paginated_link_stops_when_no_next_link(self) -> None:
        """get_paginated_link stops immediately when Link rel=next is absent."""
        page1 = MagicMock(spec=httpx.Response)
        page1.status_code = 200
        page1.headers = httpx.Headers({})  # No Link header at all
        page1.json.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
        page1.raise_for_status.return_value = None

        async with ResilientHTTPClient(base_url="https://api.example.com") as client:
            mock_request = AsyncMock(return_value=page1)
            with patch.object(client._client, "request", new=mock_request):
                result = await client.get_paginated_link("/pulls", page_size=3)

        assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert mock_request.call_count == 1

    # ------------------------------------------------------------------
    # Offset-based pagination (Jira-style)
    # ------------------------------------------------------------------

    async def test_get_paginated_offset_aggregates_all_pages(self) -> None:
        """get_paginated_offset collects items across multiple pages using startAt."""
        async with ResilientHTTPClient(base_url="https://jira.example.com") as client:
            # We patch `get` because get_paginated_offset calls self.get internally
            mock_get = AsyncMock(
                side_effect=[
                    {"values": [{"id": "ISSUE-1"}, {"id": "ISSUE-2"}], "total": 3, "startAt": 0},
                    {"values": [{"id": "ISSUE-3"}], "total": 3, "startAt": 2},
                ]
            )
            with patch.object(client, "get", new=mock_get):
                result = await client.get_paginated_offset("/rest/agile/issues", page_size=2)

        assert result == [{"id": "ISSUE-1"}, {"id": "ISSUE-2"}, {"id": "ISSUE-3"}]
        assert mock_get.call_count == 2

    async def test_get_paginated_offset_stops_when_offset_reaches_total(self) -> None:
        """get_paginated_offset stops as soon as offset >= total."""
        async with ResilientHTTPClient(base_url="https://jira.example.com") as client:
            mock_get = AsyncMock(
                return_value={"values": [{"id": "ISSUE-1"}], "total": 1, "startAt": 0}
            )
            with patch.object(client, "get", new=mock_get):
                result = await client.get_paginated_offset("/rest/agile/issues", page_size=50)

        assert result == [{"id": "ISSUE-1"}]
        assert mock_get.call_count == 1

    async def test_get_paginated_offset_uses_issues_key_as_fallback(self) -> None:
        """get_paginated_offset falls back to 'issues' key when 'values' is absent."""
        async with ResilientHTTPClient(base_url="https://jira.example.com") as client:
            mock_get = AsyncMock(
                return_value={"issues": [{"key": "PROJ-1"}], "total": 1, "startAt": 0}
            )
            with patch.object(client, "get", new=mock_get):
                result = await client.get_paginated_offset("/rest/api/2/search", page_size=50)

        assert result == [{"key": "PROJ-1"}]

    # ------------------------------------------------------------------
    # Auth header configuration
    # ------------------------------------------------------------------

    async def test_auth_token_sets_authorization_header(self) -> None:
        """auth={'token': '...'} produces 'token <value>' Authorization header."""
        client = ResilientHTTPClient(
            base_url="https://api.github.com",
            auth={"token": "ghp_secrettoken"},
        )
        try:
            assert client._client.headers["Authorization"] == "token ghp_secrettoken"
        finally:
            await client.close()

    async def test_auth_bearer_sets_bearer_authorization_header(self) -> None:
        """auth={'bearer': '...'} produces 'Bearer <value>' Authorization header."""
        client = ResilientHTTPClient(
            base_url="https://api.example.com",
            auth={"bearer": "my_jwt_token"},
        )
        try:
            assert client._client.headers["Authorization"] == "Bearer my_jwt_token"
        finally:
            await client.close()

    async def test_auth_basic_configures_httpx_basic_auth(self) -> None:
        """auth={'basic': (user, pass)} configures httpx.BasicAuth on the underlying client."""
        client = ResilientHTTPClient(
            base_url="https://jira.example.com",
            auth={"basic": ("admin", "p@ssw0rd")},
        )
        try:
            # BasicAuth is set as the httpx client's auth attribute
            assert client._client.auth is not None
            assert isinstance(client._client.auth, httpx.BasicAuth)
            # Authorization header must NOT be set for basic auth (httpx handles it per-request)
            assert "Authorization" not in client._client.headers
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # Internal helper — _parse_retry_after
    # ------------------------------------------------------------------

    async def test_parse_retry_after_returns_header_seconds(self) -> None:
        """_parse_retry_after returns the numeric value from Retry-After header."""
        response = _make_response(429, headers={"Retry-After": "30"})
        client = ResilientHTTPClient(base_url="https://api.example.com")
        try:
            wait = client._parse_retry_after(response)
            assert wait == 30.0
        finally:
            await client.close()

    async def test_parse_retry_after_defaults_to_60_when_no_header(self) -> None:
        """_parse_retry_after returns 60.0 when neither header is present."""
        response = _make_response(429)
        client = ResilientHTTPClient(base_url="https://api.example.com")
        try:
            wait = client._parse_retry_after(response)
            assert wait == 60.0
        finally:
            await client.close()

    async def test_parse_retry_after_uses_x_rate_limit_reset_timestamp(self) -> None:
        """_parse_retry_after computes wait from X-RateLimit-Reset Unix timestamp."""
        future_ts = str(int(time.time()) + 45)
        response = _make_response(429, headers={"X-RateLimit-Reset": future_ts})
        client = ResilientHTTPClient(base_url="https://api.example.com")
        try:
            wait = client._parse_retry_after(response)
            # Should be approximately 45 seconds, but at least 1
            assert 1.0 <= wait <= 46.0
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def test_async_context_manager_closes_client(self) -> None:
        """The async context manager calls close() on exit.

        We patch close() on the ResilientHTTPClient instance directly (not the
        underlying httpx client) so the patch is in place when __aexit__ fires.
        """
        client = ResilientHTTPClient(base_url="https://api.example.com")
        mock_close = AsyncMock()
        with patch.object(client, "close", new=mock_close):
            async with client:
                pass  # __aexit__ calls self.close()

        mock_close.assert_called_once()
