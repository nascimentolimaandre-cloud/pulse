"""Async CRUD repository for Jira dynamic discovery tables.

Tables: tenant_jira_config, jira_project_catalog, jira_discovery_audit.
All queries filter by tenant_id explicitly (RLS belt-and-suspenders).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    func,
    or_,
    select,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reflected table definitions (match migration 006 exactly)
# ---------------------------------------------------------------------------
metadata = MetaData()

tenant_jira_config = Table(
    "tenant_jira_config",
    metadata,
    Column("tenant_id", PG_UUID(as_uuid=True), primary_key=True),
    Column("mode", String(16), nullable=False),
    Column("discovery_enabled", Boolean, nullable=False),
    Column("discovery_schedule_cron", String(64), nullable=False),
    Column("max_active_projects", Integer, nullable=False),
    Column("max_issues_per_hour", Integer, nullable=False),
    Column("smart_pr_scan_days", Integer, nullable=False),
    Column("smart_min_pr_references", Integer, nullable=False),
    Column("last_discovery_at", DateTime(timezone=True)),
    Column("last_discovery_status", String(16)),
    Column("last_discovery_error", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

jira_project_catalog = Table(
    "jira_project_catalog",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("project_key", String(64), nullable=False),
    Column("project_id", String(64)),
    Column("name", String(255)),
    Column("project_type", String(32)),
    Column("lead_account_id", String(128)),
    Column("status", String(16), nullable=False),
    Column("activation_source", String(32)),
    Column("issue_count", Integer),
    Column("pr_reference_count", Integer),
    Column("first_seen_at", DateTime(timezone=True), server_default=func.now()),
    Column("activated_at", DateTime(timezone=True)),
    Column("last_sync_at", DateTime(timezone=True)),
    Column("last_sync_status", String(16)),
    Column("consecutive_failures", Integer, nullable=False),
    Column("last_error", Text),
    Column("metadata", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

jira_discovery_audit = Table(
    "jira_discovery_audit",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("project_key", String(64)),
    Column("actor", String(128)),
    Column("before_value", JSONB),
    Column("after_value", JSONB),
    Column("reason", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


# ---------------------------------------------------------------------------
# Sort column mapping
# ---------------------------------------------------------------------------
_SORT_COLUMNS = {
    "project_key": jira_project_catalog.c.project_key,
    "pr_reference_count": jira_project_catalog.c.pr_reference_count,
    "issue_count": jira_project_catalog.c.issue_count,
    "last_sync_at": jira_project_catalog.c.last_sync_at,
}


class DiscoveryRepository:
    """Async CRUD for Jira discovery tables. Requires a caller-provided session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # tenant_jira_config
    # ------------------------------------------------------------------

    async def get_tenant_config(self, tenant_id: UUID) -> dict[str, Any] | None:
        """Return tenant config row as dict, or None if not found."""
        result = await self._session.execute(
            select(tenant_jira_config).where(
                tenant_jira_config.c.tenant_id == tenant_id
            )
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def upsert_tenant_config(self, tenant_id: UUID, **fields: Any) -> dict[str, Any]:
        """Insert or update tenant config. Returns the upserted row."""
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {"tenant_id": tenant_id, **fields, "updated_at": now}

        update_set = {k: v for k, v in values.items() if k != "tenant_id"}

        stmt = (
            pg_insert(tenant_jira_config)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["tenant_id"],
                set_=update_set,
            )
            .returning(*tenant_jira_config.c)
        )
        result = await self._session.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else values

    # ------------------------------------------------------------------
    # jira_project_catalog
    # ------------------------------------------------------------------

    async def list_projects(
        self,
        tenant_id: UUID,
        status: str | list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "project_key",
        sort_dir: Literal["asc", "desc"] = "asc",
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List catalog projects with filtering, sorting, pagination.

        Returns (items, total_count).
        """
        base = select(jira_project_catalog).where(
            jira_project_catalog.c.tenant_id == tenant_id
        )
        count_q = select(func.count()).select_from(jira_project_catalog).where(
            jira_project_catalog.c.tenant_id == tenant_id
        )

        if status is not None:
            statuses = [status] if isinstance(status, str) else status
            base = base.where(jira_project_catalog.c.status.in_(statuses))
            count_q = count_q.where(jira_project_catalog.c.status.in_(statuses))

        if search:
            like = f"%{search}%"
            search_filter = or_(
                jira_project_catalog.c.project_key.ilike(like),
                jira_project_catalog.c.name.ilike(like),
            )
            base = base.where(search_filter)
            count_q = count_q.where(search_filter)

        col = _SORT_COLUMNS.get(sort_by, jira_project_catalog.c.project_key)
        order = col.desc() if sort_dir == "desc" else col.asc()
        base = base.order_by(order).limit(limit).offset(offset)

        total_result = await self._session.execute(count_q)
        total = total_result.scalar() or 0

        result = await self._session.execute(base)
        items = [dict(row) for row in result.mappings().all()]
        return items, total

    async def get_project(self, tenant_id: UUID, project_key: str) -> dict[str, Any] | None:
        """Get a single catalog project by key."""
        result = await self._session.execute(
            select(jira_project_catalog).where(
                and_(
                    jira_project_catalog.c.tenant_id == tenant_id,
                    jira_project_catalog.c.project_key == project_key,
                )
            )
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def upsert_project(self, tenant_id: UUID, project_key: str, **fields: Any) -> dict[str, Any]:
        """Insert or update a catalog project using ON CONFLICT ON CONSTRAINT."""
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "project_key": project_key,
            "consecutive_failures": 0,
            "metadata": {},
            "updated_at": now,
            **fields,
        }

        # Build update set: everything except PK fields
        update_set = {
            k: v for k, v in values.items()
            if k not in ("id", "tenant_id", "project_key", "first_seen_at", "created_at")
        }

        stmt = (
            pg_insert(jira_project_catalog)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_jira_catalog_tenant_key",
                set_=update_set,
            )
            .returning(*jira_project_catalog.c)
        )
        result = await self._session.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else values

    async def update_project_status(
        self,
        tenant_id: UUID,
        project_key: str,
        status: str,
        source: str | None = None,
        actor: str = "system",
        reason: str | None = None,
    ) -> None:
        """Update project status and write audit row atomically."""
        # Fetch current state for audit before_value
        current = await self.get_project(tenant_id, project_key)
        old_status = current["status"] if current else None

        now = datetime.now(timezone.utc)
        update_values: dict[str, Any] = {
            "status": status,
            "updated_at": now,
        }
        if source:
            update_values["activation_source"] = source
        if status == "active":
            update_values["activated_at"] = now

        await self._session.execute(
            jira_project_catalog.update()
            .where(
                and_(
                    jira_project_catalog.c.tenant_id == tenant_id,
                    jira_project_catalog.c.project_key == project_key,
                )
            )
            .values(**update_values)
        )

        # Determine event type from status
        event_map = {
            "active": "project_activated",
            "paused": "project_paused",
            "blocked": "project_blocked",
            "archived": "project_archived",
        }
        event_type = event_map.get(status, f"status_changed_to_{status}")

        await self.append_audit(
            tenant_id,
            event_type=event_type,
            project_key=project_key,
            actor=actor,
            before={"status": old_status} if old_status else None,
            after={"status": status},
            reason=reason,
        )

    async def bulk_set_sync_result(
        self,
        tenant_id: UUID,
        results: list[tuple[str, str, str | None]],
    ) -> None:
        """Bulk update sync status for multiple projects.

        Each tuple: (project_key, status, error_or_none).
        """
        now = datetime.now(timezone.utc)
        for project_key, status, error in results:
            await self._session.execute(
                jira_project_catalog.update()
                .where(
                    and_(
                        jira_project_catalog.c.tenant_id == tenant_id,
                        jira_project_catalog.c.project_key == project_key,
                    )
                )
                .values(
                    last_sync_at=now,
                    last_sync_status=status,
                    last_error=error,
                    updated_at=now,
                )
            )

    # ------------------------------------------------------------------
    # jira_discovery_audit (append-only)
    # ------------------------------------------------------------------

    async def append_audit(
        self,
        tenant_id: UUID,
        event_type: str,
        project_key: str | None = None,
        actor: str = "system",
        before: Any = None,
        after: Any = None,
        reason: str | None = None,
    ) -> UUID:
        """Insert an audit row. Returns the new row's ID."""
        row_id = uuid.uuid4()
        await self._session.execute(
            jira_discovery_audit.insert().values(
                id=row_id,
                tenant_id=tenant_id,
                event_type=event_type,
                project_key=project_key,
                actor=actor,
                before_value=before,
                after_value=after,
                reason=reason,
            )
        )
        return row_id

    async def list_audit(
        self,
        tenant_id: UUID,
        event_type: str | None = None,
        project_key: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List audit entries with optional filters. Returns (items, total)."""
        base = select(jira_discovery_audit).where(
            jira_discovery_audit.c.tenant_id == tenant_id
        )
        count_q = select(func.count()).select_from(jira_discovery_audit).where(
            jira_discovery_audit.c.tenant_id == tenant_id
        )

        if event_type:
            base = base.where(jira_discovery_audit.c.event_type == event_type)
            count_q = count_q.where(jira_discovery_audit.c.event_type == event_type)
        if project_key:
            base = base.where(jira_discovery_audit.c.project_key == project_key)
            count_q = count_q.where(jira_discovery_audit.c.project_key == project_key)
        if since:
            base = base.where(jira_discovery_audit.c.created_at >= since)
            count_q = count_q.where(jira_discovery_audit.c.created_at >= since)

        base = base.order_by(jira_discovery_audit.c.created_at.desc()).limit(limit).offset(offset)

        total_result = await self._session.execute(count_q)
        total = total_result.scalar() or 0

        result = await self._session.execute(base)
        items = [dict(row) for row in result.mappings().all()]
        return items, total
