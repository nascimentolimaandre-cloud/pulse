"""Pydantic v2 schemas for Tenant Capabilities endpoint."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class CapabilitySources(_CamelModel):
    """Connection state of each source system (connector-level, not data-level)."""

    jira_connected: bool
    github_connected: bool
    jenkins_connected: bool


class TenantCapabilities(_CamelModel):
    """Capability flags that condition UI rendering for a tenant or squad.

    Heuristics (see service.compute_capabilities for exact queries):
      - has_sprints: tenant/squad has >= 3 sprints ingested in the last 180 days.
      - has_kanban : tenant has >= 10 issues currently in progress (active flow).

    Squad-level response (when squad_key is supplied):
      - squad_key is echoed back
      - boards lists the Jira board_ids resolved for the squad (0..N)
      - sample_sprints surfaces up to 3 recent sprint names (debug/observability)
      - has_kanban is always inherited from the tenant-wide flag (squads without
        sprints are assumed kanban for routing purposes)

    Values are cached in Redis for 5 minutes to avoid hitting the DB on every
    page load. Cache is automatically refreshed after TTL.
    """

    tenant_id: UUID
    squad_key: str | None = None
    has_sprints: bool
    has_kanban: bool
    sprint_count: int
    issue_count_30d: int
    boards: list[str] = []
    sample_sprints: list[str] = []
    last_evaluated_at: datetime
    sources: CapabilitySources
