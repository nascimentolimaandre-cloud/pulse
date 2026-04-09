"""Resilient HTTP client — httpx wrapper with retry, rate-limiting, and logging.

Used by all source connectors to call external APIs (GitHub, Jira, Jenkins).
Handles common concerns:
- Exponential backoff retry (configurable attempts)
- Rate limit awareness (respects X-RateLimit-* and Retry-After headers)
- Configurable timeout
- Structured logging of requests
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default retry config
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0  # seconds
DEFAULT_TIMEOUT = 30.0  # seconds


class ResilientHTTPClient:
    """Async HTTP client with retry, rate-limiting, and pagination support.

    Usage:
        async with ResilientHTTPClient(base_url="https://api.github.com", auth={"token": "..."}) as client:
            data = await client.get("/repos/owner/repo/pulls")
            all_pages = await client.get_paginated("/repos/owner/repo/pulls", page_size=100)
    """

    def __init__(
        self,
        base_url: str,
        auth: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "PULSE-Connector/1.0",
        }
        if extra_headers:
            headers.update(extra_headers)

        # Auth strategies
        if auth:
            if "token" in auth:
                headers["Authorization"] = f"token {auth['token']}"
            elif "bearer" in auth:
                headers["Authorization"] = f"Bearer {auth['bearer']}"
            elif "basic" in auth:
                # basic auth is handled via httpx auth param
                pass

        basic_auth = None
        if auth and "basic" in auth:
            username, password = auth["basic"]
            basic_auth = httpx.BasicAuth(username, password)

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            auth=basic_auth,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._backoff_base = DEFAULT_BACKOFF_BASE

    async def __aenter__(self) -> ResilientHTTPClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET request with retry and rate-limit handling.

        Returns parsed JSON response body.
        Raises httpx.HTTPStatusError on non-retryable errors (4xx except 429).
        """
        return await self._request("GET", path, params=params)

    async def post(
        self,
        path: str,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """POST request with retry."""
        return await self._request("POST", path, params=params, json_body=json_body)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        """Execute an HTTP request with retry and rate-limit handling."""
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.request(
                    method, path, params=params, json=json_body,
                )

                # Rate limited — wait and retry
                if response.status_code == 429:
                    retry_after = self._parse_retry_after(response)
                    logger.warning(
                        "Rate limited on %s %s — waiting %.1fs (attempt %d/%d)",
                        method, path, retry_after, attempt, self._max_retries,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                # Server error — retry with backoff
                if response.status_code >= 500:
                    wait = self._backoff_base * (2 ** (attempt - 1))
                    logger.warning(
                        "Server error %d on %s %s — retrying in %.1fs (attempt %d/%d)",
                        response.status_code, method, path, wait, attempt, self._max_retries,
                    )
                    await asyncio.sleep(wait)
                    last_error = httpx.HTTPStatusError(
                        f"Server error {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue

                # Client error (non-429) — fail immediately
                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException as e:
                wait = self._backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "Timeout on %s %s — retrying in %.1fs (attempt %d/%d)",
                    method, path, wait, attempt, self._max_retries,
                )
                last_error = e
                await asyncio.sleep(wait)
            except httpx.ConnectError as e:
                wait = self._backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "Connection error on %s %s — retrying in %.1fs (attempt %d/%d)",
                    method, path, wait, attempt, self._max_retries,
                )
                last_error = e
                await asyncio.sleep(wait)

        # All retries exhausted
        raise ConnectionError(
            f"Failed after {self._max_retries} attempts: {method} {path}"
        ) from last_error

    def _parse_retry_after(self, response: httpx.Response) -> float:
        """Parse Retry-After header or X-RateLimit-Reset for wait time."""
        # Standard Retry-After header (seconds)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

        # GitHub-style X-RateLimit-Reset (Unix timestamp)
        reset_ts = response.headers.get("X-RateLimit-Reset")
        if reset_ts:
            try:
                import time
                wait = float(reset_ts) - time.time()
                return max(wait, 1.0)
            except ValueError:
                pass

        # Default: 60 seconds
        return 60.0

    # ------------------------------------------------------------------
    # Pagination helpers
    # ------------------------------------------------------------------

    async def get_paginated_link(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = 100,
        max_pages: int = 200,
    ) -> list[dict[str, Any]]:
        """Paginated GET using Link header (GitHub-style).

        Follows `rel="next"` links in the response Link header.
        """
        all_items: list[dict[str, Any]] = []
        params = dict(params or {})
        params["per_page"] = page_size

        url = path
        for page_num in range(1, max_pages + 1):
            response = await self._client.request("GET", url, params=params if page_num == 1 else None)

            if response.status_code == 429:
                retry_after = self._parse_retry_after(response)
                logger.warning("Rate limited during pagination — waiting %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                continue

            response.raise_for_status()
            data = response.json()

            if isinstance(data, list):
                all_items.extend(data)
            else:
                break

            # Check Link header for next page
            next_url = self._parse_link_next(response)
            if not next_url or len(data) < page_size:
                break

            url = next_url
            params = None  # URL already contains params

        logger.info("Fetched %d items from %s (%d pages)", len(all_items), path, page_num)
        return all_items

    async def get_paginated_offset(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = 50,
        max_pages: int = 200,
        start_at_key: str = "startAt",
        max_results_key: str = "maxResults",
        values_key: str = "values",
        total_key: str = "total",
    ) -> list[dict[str, Any]]:
        """Paginated GET using offset-based pagination (Jira-style).

        Uses startAt/maxResults params and reads total from response.
        """
        all_items: list[dict[str, Any]] = []
        params = dict(params or {})
        params[max_results_key] = page_size
        offset = 0

        for page_num in range(1, max_pages + 1):
            params[start_at_key] = offset
            data = await self.get(path, params=params)

            items = data.get(values_key) or data.get("issues", [])
            all_items.extend(items)

            total = data.get(total_key, 0)
            offset += len(items)

            if offset >= total or len(items) < page_size or not items:
                break

        logger.info("Fetched %d items from %s (%d pages)", len(all_items), path, page_num)
        return all_items

    @staticmethod
    def _parse_link_next(response: httpx.Response) -> str | None:
        """Parse the 'next' URL from a Link header."""
        link_header = response.headers.get("Link", "")
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return url
        return None
