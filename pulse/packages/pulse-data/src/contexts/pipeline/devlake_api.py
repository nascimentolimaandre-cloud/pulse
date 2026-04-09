"""Client for DevLake REST API — pipeline status queries.

Read-only client that queries DevLake's REST API for pipeline run
information. Used by the Pipeline Monitor to display sync status
and health indicators.

All calls are wrapped in try/except since DevLake may be unavailable.
"""

from __future__ import annotations

import logging

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

DEVLAKE_API_URL = getattr(settings, "devlake_api_url", "http://localhost:4000")


class DevLakeAPIClient:
    """Read-only client for DevLake REST API."""

    def __init__(self, base_url: str = DEVLAKE_API_URL) -> None:
        self._base_url = base_url.rstrip("/")

    async def get_latest_pipeline(self) -> dict | None:
        """Get the most recent DevLake pipeline run."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self._base_url}/api/pipelines",
                params={"pageSize": 1, "page": 1},
            )
            if resp.status_code != 200:
                logger.warning(
                    "DevLake API returned %d for latest pipeline", resp.status_code,
                )
                return None
            data = resp.json()
            pipelines = data.get("pipelines", [])
            return pipelines[0] if pipelines else None

    async def get_running_pipeline(self) -> dict | None:
        """Get currently running pipeline, if any."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self._base_url}/api/pipelines",
                params={"pageSize": 1, "page": 1, "status": "TASK_RUNNING"},
            )
            if resp.status_code != 200:
                logger.warning(
                    "DevLake API returned %d for running pipeline", resp.status_code,
                )
                return None
            data = resp.json()
            pipelines = data.get("pipelines", [])
            return pipelines[0] if pipelines else None

    async def get_pipeline_health(self) -> dict:
        """Get overall DevLake pipeline health summary.

        Returns a dict with keys: latest_pipeline, running_pipeline,
        is_running, last_status, last_finished_at.
        """
        latest = await self.get_latest_pipeline()
        running = await self.get_running_pipeline()
        return {
            "latest_pipeline": latest,
            "running_pipeline": running,
            "is_running": running is not None,
            "last_status": latest.get("status") if latest else None,
            "last_finished_at": latest.get("finishedAt") if latest else None,
        }
