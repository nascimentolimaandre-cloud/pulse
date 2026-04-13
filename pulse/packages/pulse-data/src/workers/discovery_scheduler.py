"""Discovery Scheduler Worker — runs ProjectDiscoveryService per tenant on cron.

Uses APScheduler to schedule discovery runs per tenant according to their
``discovery_schedule_cron`` setting. Also exposes an HTTP endpoint for
manual triggering via FastAPI.

Run: python -m src.workers.discovery_scheduler
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from src.config import settings
from src.contexts.integrations.jira.discovery.project_discovery_service import (
    ProjectDiscoveryService,
)
from src.contexts.integrations.jira.discovery.repository import (
    DiscoveryRepository,
    tenant_jira_config,
)
from src.database import get_session

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal API for manual trigger
# ---------------------------------------------------------------------------

trigger_app = FastAPI(title="discovery-scheduler-internal", docs_url=None)


class TriggerRequest(BaseModel):
    tenant_id: str


class TriggerResponse(BaseModel):
    run_id: str
    status: str


def _check_internal_token(x_internal_token: str | None) -> None:
    """Validate the internal API token using constant-time comparison.

    Uses hmac.compare_digest to prevent timing-oracle attacks that could
    allow an attacker to reconstruct the token byte-by-byte.
    """
    import hmac

    expected = getattr(settings, "internal_api_token", "")
    if not expected:
        # No token configured = allow (dev mode)
        return
    if x_internal_token is None or not hmac.compare_digest(
        x_internal_token.encode(), expected.encode()
    ):
        raise HTTPException(status_code=403, detail="Invalid internal token")


@trigger_app.post("/internal/discovery/trigger", response_model=TriggerResponse)
async def trigger_discovery(
    body: TriggerRequest,
    x_internal_token: str | None = Header(default=None),
) -> TriggerResponse:
    """Manually trigger a discovery run for a tenant."""
    _check_internal_token(x_internal_token)

    tenant_id = uuid.UUID(body.tenant_id)

    async with get_session(tenant_id) as session:
        from src.connectors.jira_connector import JiraConnector

        try:
            jira_client = JiraConnector()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initialize Jira client: {exc}",
            )

        service = ProjectDiscoveryService(session, jira_client=jira_client)
        result = await service.run_discovery(tenant_id)

    return TriggerResponse(
        run_id=result["runId"],
        status=result["status"],
    )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

async def _run_discovery_for_tenant(tenant_id_str: str) -> None:
    """Execute a discovery run for one tenant."""
    tenant_id = uuid.UUID(tenant_id_str)
    logger.info("Running scheduled discovery for tenant %s", tenant_id)

    try:
        async with get_session(tenant_id) as session:
            from src.connectors.jira_connector import JiraConnector

            try:
                jira_client = JiraConnector()
            except Exception:
                logger.exception("Failed to init Jira client for tenant %s", tenant_id)
                return

            service = ProjectDiscoveryService(session, jira_client=jira_client)
            result = await service.run_discovery(tenant_id)
            logger.info(
                "Discovery run %s for tenant %s completed: %s",
                result["runId"], tenant_id, result["status"],
            )
    except Exception:
        logger.exception("Discovery run failed for tenant %s", tenant_id)


async def _load_tenant_schedules() -> list[dict[str, Any]]:
    """Load all tenant configs that have discovery enabled."""
    from sqlalchemy import select as sa_select

    async with get_session() as session:
        result = await session.execute(
            sa_select(
                tenant_jira_config.c.tenant_id,
                tenant_jira_config.c.discovery_schedule_cron,
                tenant_jira_config.c.discovery_enabled,
            )
        )
        return [dict(row) for row in result.mappings().all()]


def _parse_cron(cron_expr: str) -> dict[str, str]:
    """Parse '0 3 * * *' into APScheduler CronTrigger kwargs."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return {"hour": "3", "minute": "0"}
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


async def run_scheduler() -> None:
    """Main entry point: start APScheduler + HTTP server."""
    if not HAS_APSCHEDULER:
        logger.error(
            "apscheduler not installed. Install with: pip install apscheduler"
        )
        return

    scheduler = AsyncIOScheduler()
    running = True

    def _handle_signal() -> None:
        nonlocal running
        running = False
        scheduler.shutdown(wait=False)
        logger.info("Received shutdown signal")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # Load tenant schedules and register jobs
    try:
        tenants = await _load_tenant_schedules()
    except Exception:
        logger.exception("Failed to load tenant schedules, using empty list")
        tenants = []

    for tenant in tenants:
        if not tenant.get("discovery_enabled", True):
            continue
        cron_expr = tenant.get("discovery_schedule_cron", "0 3 * * *")
        cron_kwargs = _parse_cron(cron_expr)
        tenant_id_str = str(tenant["tenant_id"])
        scheduler.add_job(
            _run_discovery_for_tenant,
            CronTrigger(**cron_kwargs),
            args=[tenant_id_str],
            id=f"discovery-{tenant_id_str}",
            replace_existing=True,
        )
        logger.info("Scheduled discovery for tenant %s: %s", tenant_id_str, cron_expr)

    scheduler.start()
    logger.info("Discovery scheduler started with %d tenant jobs", len(tenants))

    # Start HTTP server for manual trigger
    import uvicorn

    config = uvicorn.Config(
        trigger_app, host="0.0.0.0", port=8001, log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run_scheduler())
