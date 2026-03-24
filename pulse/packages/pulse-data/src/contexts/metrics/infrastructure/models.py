"""SQLAlchemy model for the metrics_snapshots table.

Stores pre-calculated metric values per team, metric type, and time period.
This is the single source of truth for dashboard data — API reads from here,
never calculates on the fly.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Uuid, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import Base


class MetricsSnapshot(Base):
    """Pre-calculated metrics snapshot.

    Each row represents one metric calculation for a specific team and period.
    The value column is JSONB to accommodate different metric shapes (DORA, Lean, etc.).

    Upsert key: (tenant_id, team_id, metric_type, metric_name, period_start, period_end)
    """

    __tablename__ = "metrics_snapshots"

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
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )
    metric_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )  # dora | lean | cycle_time | throughput | sprint
    metric_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )  # deployment_frequency | lead_time | cfd | wip | etc.
    value: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
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

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "team_id",
            "metric_type",
            "metric_name",
            "period_start",
            "period_end",
            name="uq_metrics_snapshot_key",
        ),
    )
