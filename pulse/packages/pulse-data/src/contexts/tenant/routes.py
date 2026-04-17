"""Tenant capability endpoint.

Internal, read-only. No auth header required in MVP — the tenant middleware
injects the default tenant. Response is cached (Redis, 5min TTL) inside the
service layer to avoid hitting the DB on every page load.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from src.config import settings
from src.contexts.tenant.schemas import TenantCapabilities
from src.contexts.tenant.service import get_capabilities

router = APIRouter(prefix="/data/v1/tenant", tags=["Tenant"])


@router.get("/capabilities", response_model=TenantCapabilities)
async def get_tenant_capabilities(
    refresh: bool = Query(default=False, description="Bypass cache and recompute."),
    squad_key: str | None = Query(
        default=None,
        description=(
            "Optional Jira project key (e.g. 'FID', 'PTURB'). When supplied, "
            "returns squad-scoped capabilities instead of tenant-wide."
        ),
    ),
) -> TenantCapabilities:
    """Return capability flags for the current tenant (or a single squad).

    Used by the frontend to conditionally render sprint-specific and
    kanban-specific UI. Tenants working with continuous flow will see
    has_sprints=false; tenants with no active flow will see has_kanban=false.

    When `squad_key` is provided, `has_sprints` is evaluated against the
    sprints linked to that squad's issues only — so a tenant with sprints on
    some squads still hides sprint UI on squads that run pure kanban.
    """
    tenant_id = uuid.UUID(settings.default_tenant_id)
    return await get_capabilities(
        tenant_id, squad_key=squad_key, use_cache=not refresh
    )
