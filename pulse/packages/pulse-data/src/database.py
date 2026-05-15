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

# CISO FDD-OBS-001 PR2 H-001 — `echo` is wired to a DEDICATED
# `sqlalchemy_echo` setting, NOT to `debug`. SQL `echo=True` logs all
# bound parameters, which includes the pgcrypto master key and plaintext
# API keys flowing through `credential_service.upsert_credential`.
# Flipping app `debug` to True must never silently enable SQL logging.
#
# CISO FDD-OBS-001 PR2 H-002 — `hide_parameters=True` strips bound
# parameter values from EXCEPTION messages and tracebacks. Without this,
# any DB error that travels up through SQLAlchemy includes the full
# `[parameters: (...)]` block in the message — which for credential_service
# would emit the master key and plaintext API key into application logs
# (caught in the wild during PR 2 live test on 2026-05-06: an
# AmbiguousParameterError leaked `pgp_sym_encrypt` plaintexts to docker
# logs). `hide_parameters` is INDEPENDENT of `echo` — exception logging
# is on a different code path inside SQLAlchemy.
engine = create_async_engine(
    settings.async_database_url,
    echo=settings.sqlalchemy_echo,
    hide_parameters=True,
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
    """Set the current tenant on the PostgreSQL session for RLS.

    FDD-OBS-001 Phase 1 T1.3 — uses `set_config(name, value, is_local)`
    with a bound parameter instead of f-string interpolation. The old
    pattern was safe in practice because Pydantic validates the UUID
    upstream, but a single misuse anywhere on the call chain (string
    parameter accidentally typed `UUID | str`) would expose H-severity
    SQL injection at the RLS layer. `set_config` is the canonical
    PostgreSQL helper for this exact pattern — `SET ... = '...'` is
    statement-level and rejects bound parameters in its operand
    position, whereas `set_config(:t, :v, true)` accepts them.

    `is_local=true` keeps the setting scoped to the current
    transaction — same semantics as `SET LOCAL`, identical to what
    the previous `SET app.current_tenant = '...'` provided since RLS
    policies read it via `current_setting('app.current_tenant')`.
    """
    await session.execute(
        text("SELECT set_config('app.current_tenant', :t, true)"),
        {"t": str(tenant_id)},
    )


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
