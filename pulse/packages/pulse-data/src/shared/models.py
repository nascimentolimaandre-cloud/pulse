"""Base SQLAlchemy model with common columns for all PULSE tables.

Every table has:
- id: UUID primary key (server-side default)
- tenant_id: UUID NOT NULL (for RLS)
- created_at / updated_at: timestamps with timezone
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Abstract declarative base for all PULSE models."""

    pass


class TenantModel(Base):
    """Abstract base with id, tenant_id, created_at, updated_at.

    All concrete models inherit from this to guarantee
    RLS-compatible tenant_id is always present.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )
