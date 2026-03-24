"""API routes for BC3 — Engineering Data.

Stub routes for pull requests and issues.
Full implementation in Phase 2.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.shared.tenant import get_tenant_id

router = APIRouter(prefix="/data/v1", tags=["engineering-data"])


@router.get("/pull-requests")
async def list_pull_requests(
    tenant_id: UUID = Depends(get_tenant_id),
    repo: str | None = Query(None, description="Filter by repository"),
    state: str | None = Query(None, description="Filter by state (open|merged|closed)"),
    author: str | None = Query(None, description="Filter by author"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List normalized pull requests for the current tenant."""
    # Stub — real implementation reads from eng_pull_requests via repository
    return {
        "data": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/issues")
async def list_issues(
    tenant_id: UUID = Depends(get_tenant_id),
    project_key: str | None = Query(None, description="Filter by project key"),
    normalized_status: str | None = Query(None, description="Filter by status (todo|in_progress|done)"),
    sprint_id: UUID | None = Query(None, description="Filter by sprint"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List normalized issues for the current tenant."""
    # Stub — real implementation reads from eng_issues via repository
    return {
        "data": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }
