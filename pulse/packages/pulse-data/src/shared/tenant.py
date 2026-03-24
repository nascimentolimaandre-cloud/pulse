"""Tenant middleware for FastAPI.

MVP: reads DEFAULT_TENANT_ID from config (no auth).
R1+: will extract tenant from JWT claims.
"""

from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.config import settings

# Request-scoped tenant storage
_TENANT_CONTEXT_KEY = "tenant_id"


class TenantMiddleware(BaseHTTPMiddleware):
    """Injects tenant_id into request.state on every request.

    MVP implementation: always uses the default tenant.
    Future: parse Authorization header, extract tenant from JWT.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # MVP: single default tenant, no auth
        tenant_id = UUID(settings.default_tenant_id)
        request.state.tenant_id = tenant_id
        response = await call_next(request)
        return response


def get_tenant_id(request: Request) -> UUID:
    """FastAPI dependency to extract tenant_id from request.state."""
    return request.state.tenant_id
