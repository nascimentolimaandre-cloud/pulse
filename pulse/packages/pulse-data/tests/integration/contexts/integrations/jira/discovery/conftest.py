"""Shared fixtures for Jira discovery integration tests.

Uses testcontainers-python to spin up a real PostgreSQL instance.
Applies Alembic migrations through 006_jira_discovery.
Provides an async SQLAlchemy session scoped to each test function.

Requirements:
    pip install testcontainers[postgres] pytest-asyncio asyncpg sqlalchemy[asyncio] alembic

Each test gets a clean, isolated state via transaction rollback.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# testcontainers is an optional test dependency — import lazily so the
# module can be parsed without it for static analysis.
try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "testcontainers[postgres] is required for integration tests. "
        "Install with: pip install 'testcontainers[postgres]'"
    ) from exc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")

# Locate the alembic directory relative to this file.
_PACKAGE_ROOT = Path(__file__).parents[6]  # pulse/packages/pulse-data/
_ALEMBIC_CFG = _PACKAGE_ROOT / "alembic" / "alembic.ini"


# ---------------------------------------------------------------------------
# Session-scoped: one PostgreSQL container for the entire test session.
# This avoids the expensive container startup per test.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for the test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def sync_db_url(postgres_container) -> str:
    """Return the sync (psycopg2) DSN for Alembic migrations."""
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session")
def async_db_url(postgres_container) -> str:
    """Return the async (asyncpg) DSN for SQLAlchemy sessions."""
    url = postgres_container.get_connection_url()
    # testcontainers returns postgresql+psycopg2://..., swap driver
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(sync_db_url: str):
    """Run Alembic upgrade head once for the session.

    Sets JIRA_PROJECTS env var to empty so migration 006 does not try to
    bootstrap catalog rows from a real env var.
    """
    from alembic.config import Config
    from alembic import command

    # Prevent migration 006 bootstrap from seeding catalog rows
    os.environ.setdefault("JIRA_PROJECTS", "")

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", str(_PACKAGE_ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", sync_db_url)

    command.upgrade(alembic_cfg, "head")


# ---------------------------------------------------------------------------
# Function-scoped: async engine + session with savepoint rollback isolation.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine(async_db_url: str):
    """Async engine bound to the test container."""
    engine = create_async_engine(async_db_url, echo=False, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an AsyncSession with per-test rollback isolation.

    Each test runs inside a SAVEPOINT. On teardown the savepoint is rolled
    back, leaving the database pristine for the next test.

    RLS is bypassed for integration tests by setting the session-level GUC
    app.current_tenant to the test tenant UUID. Tests that need a different
    tenant can execute SET LOCAL themselves.
    """
    async with engine.connect() as conn:
        # Open outer transaction — never committed
        trans = await conn.begin()

        # Bypass RLS for the test session
        await conn.execute(
            text(f"SET LOCAL app.current_tenant = '{TENANT_ID}'")
        )

        session_factory = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with session_factory() as sess:
            yield sess

        # Roll back everything written during the test
        await trans.rollback()


# ---------------------------------------------------------------------------
# Helpers used across integration test modules
# ---------------------------------------------------------------------------

async def insert_tenant_config(
    session: AsyncSession,
    tenant_id: uuid.UUID = TENANT_ID,
    mode: str = "allowlist",
    max_active_projects: int = 100,
    max_issues_per_hour: int = 20000,
    smart_min_pr_references: int = 3,
    smart_pr_scan_days: int = 90,
    discovery_enabled: bool = True,
) -> dict[str, Any]:
    """Insert a tenant_jira_config row directly via SQL."""
    from src.contexts.integrations.jira.discovery.repository import (
        DiscoveryRepository,
    )
    repo = DiscoveryRepository(session)
    return await repo.upsert_tenant_config(
        tenant_id,
        mode=mode,
        discovery_enabled=discovery_enabled,
        discovery_schedule_cron="0 3 * * *",
        max_active_projects=max_active_projects,
        max_issues_per_hour=max_issues_per_hour,
        smart_pr_scan_days=smart_pr_scan_days,
        smart_min_pr_references=smart_min_pr_references,
    )


async def insert_catalog_project(
    session: AsyncSession,
    project_key: str,
    tenant_id: uuid.UUID = TENANT_ID,
    status: str = "discovered",
    pr_reference_count: int = 0,
    consecutive_failures: int = 0,
    activation_source: str | None = None,
) -> dict[str, Any]:
    """Insert a jira_project_catalog row."""
    from src.contexts.integrations.jira.discovery.repository import (
        DiscoveryRepository,
    )
    repo = DiscoveryRepository(session)
    return await repo.upsert_project(
        tenant_id,
        project_key,
        project_id=f"ID-{project_key}",
        name=f"Project {project_key}",
        project_type="software",
        status=status,
        pr_reference_count=pr_reference_count,
        consecutive_failures=consecutive_failures,
        activation_source=activation_source,
    )


def make_jira_project_payload(project_key: str) -> dict[str, Any]:
    """Build a mock Jira API project dict (as returned by fetch_all_accessible_projects)."""
    return {
        "project_key": project_key,
        "project_id": f"ID-{project_key}",
        "name": f"Project {project_key}",
        "project_type": "software",
        "lead_account_id": None,
    }
