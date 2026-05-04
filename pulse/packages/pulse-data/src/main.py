"""FastAPI application entry point for pulse-data.

Run locally: uvicorn src.main:app --reload --port 8000
Deploy to Lambda: see src/lambda_handler.py
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.contexts.engineering_data.routes import admin_router as engineering_data_admin_router
from src.contexts.engineering_data.routes import deployments_admin_router as engineering_data_deployments_admin_router
from src.contexts.engineering_data.routes import issues_admin_router as engineering_data_issues_admin_router
from src.contexts.engineering_data.routes import router as engineering_data_router
from src.contexts.metrics.routes import admin_router as metrics_admin_router
from src.contexts.metrics.routes import router as metrics_router
from src.contexts.pipeline.routes import router as pipeline_router
from src.contexts.pipeline.routes import squad_admin_router as pipeline_squad_admin_router
from src.contexts.tenant.routes import router as tenant_router
from src.shared.tenant import TenantMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    # Startup — future: warm up DB pool, Kafka producer, etc.
    yield
    # Shutdown — future: close connections gracefully
    from src.database import engine

    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/data/v1/docs",
    openapi_url="/data/v1/openapi.json",
    lifespan=lifespan,
)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TenantMiddleware)

# --- Routers ---
app.include_router(engineering_data_router)
app.include_router(engineering_data_admin_router)
app.include_router(engineering_data_issues_admin_router)
app.include_router(engineering_data_deployments_admin_router)
app.include_router(metrics_router)
app.include_router(metrics_admin_router)
app.include_router(pipeline_router)
app.include_router(pipeline_squad_admin_router)
app.include_router(tenant_router)


# --- Health ---
@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.app_version,
    }
