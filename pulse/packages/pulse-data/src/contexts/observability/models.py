"""FDD-OBS-001 PR 1 — Observability ORM models.

Three aggregate roots:
  - `TenantObservabilityCredentials` — DD/NR/Grafana per-tenant keys
  - `ServiceSquadOwnership` — service ↔ squad mapping (3-tier inference)
  - `ObsMetricSnapshot` — hourly rollups (ADR-024 cache layer 1)

## Why these inherit from `Base` directly (not `TenantModel`)

PULSE convention is: every table has an `id UUID PK` column (provided
by `TenantModel`) plus the natural keys as a `UNIQUE` constraint. This
is fine when natural keys are 2-3 columns and the synthetic id is
useful for FK relationships.

These three tables have **composite primary keys** with 2-5 columns
that are semantically correct — adding a synthetic UUID id would be
pure noise (no FKs reference them; all reads go through composite-key
upserts).

Alternative considered: keep `id UUID PK` + `UNIQUE(natural keys)`
matching `PipelineWatermark`. Rejected because:
  - The synthetic id would never be used by any code path.
  - Extra index storage for no benefit.
  - PRIMARY KEY enforces tenant_id NOT NULL anyway (RLS still works).

Documented here so future reviewers don't think this is sloppy.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Double,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import Base


class TenantObservabilityCredentials(Base):
    """Per-tenant API keys for observability providers (ADR-021).

    `api_key_encrypted` / `app_key_encrypted` are stored via
    `pgp_sym_encrypt(plain, PULSE_OBS_MASTER_KEY)` — never plain text
    and never logged. The ORM exposes the bytea columns; the
    `CredentialService` (PR 2) handles encryption/decryption inside
    the application layer.
    """

    __tablename__ = "tenant_observability_credentials"

    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    app_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    site: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="datadoghq.com",
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    key_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ServiceSquadOwnership(Base):
    """Service → squad mapping (ADR-022 — 3-tier inference).

    Effective squad: `COALESCE(override_squad_key, inferred_squad_key)`.

    `metadata` JSONB has a DB trigger blocking known-PII keys
    (ADR-025 Layer 2) — `obs_no_pii_in_metadata()` raises if anyone
    tries to store `user.email`, `deployment.author`, etc.
    """

    __tablename__ = "service_squad_ownership"

    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    service_external_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    service_name: Mapped[str] = mapped_column(String(256), nullable=False)
    repo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    inferred_squad_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inferred_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    override_squad_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_inference_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class TenantTeamAlias(Base):
    """FDD-OBS-001 PR 3.5 — vendor_team → PULSE squad mapping per tenant.

    Bridges the gap between vendor team taxonomies (DD: `agenda-facil`,
    `iazi`, ...) and PULSE squad keys (Jira project keys: `FID`, `OKM`,
    ...). Live test against Webmotors DD found 99.8% DD-tag coverage
    but 0% qualified-squad mapping without this translation table.

    Read pattern: `ownership_inference` loads the full alias map for
    (tenant, provider) once per sync run, resolves each `team:` tag
    in-memory, and only persists the resolved squad_key when found.

    `vendor_team_value` is normalized lowercase by the service layer
    before insert (DD tag values are case-insensitive in practice).
    """

    __tablename__ = "tenant_team_alias"

    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    vendor_team_value: Mapped[str] = mapped_column(String(128), primary_key=True)
    squad_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ObsMetricSnapshot(Base):
    """Hourly rollup of observability metrics (ADR-024 — cache layer 1).

    The Carlos's Deploy Health Timeline (PR 4) reads exclusively from
    this table — zero live API calls per page load. The rollup worker
    (PR 4) writes one row per (provider, service, metric, hour_bucket)
    by batched provider queries every 15 minutes.
    """

    __tablename__ = "obs_metric_snapshots"

    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    service: Mapped[str] = mapped_column(String(256), primary_key=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    hour_bucket: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True,
    )
    value: Mapped[float | None] = mapped_column(Double, nullable=True)
    samples_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}",
    )
