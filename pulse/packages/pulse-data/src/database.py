"""SQLAlchemy 2.0 async engine, session factory, and RLS middleware.

Every session executes SET app.current_tenant before any query,
ensuring PostgreSQL Row-Level Security policies filter by tenant.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from src.config import settings

engine = create_async_engine(
    settings.async_database_url,
    echo=settings.debug,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def _set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Set the current tenant on the PostgreSQL session for RLS."""
    await session.execute(text(f"SET app.current_tenant = '{tenant_id}'"))


@asynccontextmanager
async def get_session(tenant_id: UUID | None = None) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session with RLS tenant set.

    Args:
        tenant_id: The tenant UUID. Falls back to DEFAULT_TENANT_ID from config.
    """
    resolved_tenant = tenant_id or UUID(settings.default_tenant_id)
    async with async_session_factory() as session:
        await _set_tenant(session, resolved_tenant)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a tenant-scoped DB session."""
    async with get_session() as session:
        yield session
