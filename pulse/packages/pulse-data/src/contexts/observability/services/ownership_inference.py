"""FDD-OBS-001 PR 3 — Tier 1 + Tier 3 ownership inference.

ADR-022 specifies a 3-tier inference for service-to-squad mapping:

  Tier 1 (this PR, sync) — vendor tag (DD `team:` / NR `team`):
      `DatadogProvider.list_services()` already extracts `owner_squad`
      from `dd-service.team`. We just persist it with
      `inferred_confidence='tag'`.

  Tier 2 (PR 4) — repo-intersection heuristic over rollup data.

  Tier 3 (this PR) — admin override (`override_squad_key`).
      Always wins; effective squad = `COALESCE(override, inferred)`.

The service does NOT validate Tier 1 squad keys against the qualified
set — surfacing "tag points to non-tenant squad" as a yellow badge
in the UI is a feature, not a bug. Validation happens **only** when
an admin sets an override (the `set_override` path).

Idempotency: a re-run with no DD-side changes results in zero row
updates. This matters for PR 4 to detect "stale tag inference" via
`last_inference_at` deltas. The upsert uses
`IS DISTINCT FROM` to skip touching `updated_at` when nothing
actually changed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.connectors.observability.base import ObservabilityProvider
from src.contexts.observability.services.squad_directory import (
    SquadDirectory,
)
from src.database import get_session

logger = logging.getLogger(__name__)


# Allowlist of vendor-supplied keys we're willing to persist in the
# JSONB `metadata` column (ADR-025 Layer 1 belt + Layer 2 trigger
# suspenders). Anything outside this list is dropped before INSERT.
# Values come from `DatadogProvider.list_services()` already-stripped
# `vendor_raw` plus a couple of fields we explicitly extract.
_METADATA_ALLOWED_KEYS: frozenset[str] = frozenset({
    "team_tag_raw",       # the DD team tag value before normalization
    "owner_tag_raw",      # the DD owner tag value (alternative to team)
    "dd_service_type",    # web / db / cache (no PII)
    "tier",               # tier-0 / tier-1 / tier-2 (no PII)
    "runtime",            # python / java / node (no PII)
})


@dataclass(frozen=True)
class InferenceResult:
    """Outcome of one Tier-1 inference run (returned to the admin endpoint).

    `unchanged` + `inferred_*` + `inferred_none` should sum to
    `services_seen`; the assertion would fail loud if it ever drifts."""

    services_seen: int
    inferred_with_tag: int
    inferred_none: int
    unchanged: int
    duration_ms: int

    @property
    def total_changed(self) -> int:
        return self.services_seen - self.unchanged


@dataclass(frozen=True)
class OwnershipRow:
    """Read-model row exposed by `list_for_tenant`. The frontend consumes
    `effective_squad_key` directly — no client-side COALESCE."""

    service_external_id: str
    service_name: str
    repo_url: str | None
    inferred_squad_key: str | None
    inferred_confidence: str | None
    override_squad_key: str | None
    effective_squad_key: str | None
    last_inference_at: datetime
    is_qualified_squad: bool


# ---------------------------------------------------------------------------
# Tier 1 sync — provider catalog → ownership table
# ---------------------------------------------------------------------------


async def sync_tier1_inference(
    tenant_id: UUID,
    provider_id: str,
    provider: ObservabilityProvider,
) -> InferenceResult:
    """Fetch the provider's service catalog and upsert Tier-1 ownership
    rows. Idempotent — rows whose `inferred_*` values match are not
    bumped.

    Only writes `inferred_*` columns. NEVER touches `override_squad_key`
    (Tier 3 admin data) — the `DO UPDATE SET` clause omits it.

    `provider` is injected (constructed by `provider_factory`); this
    function doesn't manage its lifetime.
    """
    started_at = datetime.now(timezone.utc)
    services = await provider.list_services()
    services_seen = len(services)

    if services_seen == 0:
        logger.warning(
            "[obs-inference] empty service catalog tenant=%s provider=%s — skip",
            tenant_id, provider_id,
        )
        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        return InferenceResult(
            services_seen=0,
            inferred_with_tag=0,
            inferred_none=0,
            unchanged=0,
            duration_ms=duration_ms,
        )

    inferred_with_tag = 0
    inferred_none = 0
    changed_rows = 0

    async with get_session(tenant_id) as session:
        for svc in services:
            squad = svc.owner_squad
            confidence = "tag" if squad else "none"
            if squad:
                inferred_with_tag += 1
            else:
                inferred_none += 1

            metadata = _build_metadata(svc)

            result = await session.execute(
                text(
                    """
                    INSERT INTO service_squad_ownership (
                        tenant_id, provider, service_external_id,
                        service_name, repo_url,
                        inferred_squad_key, inferred_confidence,
                        last_inference_at, metadata
                    )
                    VALUES (
                        :tenant_id, :provider, :external_id,
                        :service_name, :repo_url,
                        :inferred_squad_key, :inferred_confidence,
                        :now, CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (tenant_id, provider, service_external_id)
                    DO UPDATE SET
                        service_name        = EXCLUDED.service_name,
                        repo_url            = EXCLUDED.repo_url,
                        inferred_squad_key  = EXCLUDED.inferred_squad_key,
                        inferred_confidence = EXCLUDED.inferred_confidence,
                        last_inference_at   = EXCLUDED.last_inference_at,
                        metadata            = EXCLUDED.metadata,
                        updated_at          = NOW()
                    WHERE
                        service_squad_ownership.inferred_squad_key
                            IS DISTINCT FROM EXCLUDED.inferred_squad_key
                        OR service_squad_ownership.inferred_confidence
                            IS DISTINCT FROM EXCLUDED.inferred_confidence
                        OR service_squad_ownership.service_name
                            IS DISTINCT FROM EXCLUDED.service_name
                        OR service_squad_ownership.repo_url
                            IS DISTINCT FROM EXCLUDED.repo_url
                    RETURNING xmax = 0 AS inserted
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "provider": provider_id,
                    "external_id": svc.external_id,
                    "service_name": svc.service_name,
                    "repo_url": svc.repo_url,
                    "inferred_squad_key": squad,
                    "inferred_confidence": confidence,
                    "now": started_at,
                    "metadata": _json_dumps(metadata),
                },
            )
            # When the WHERE clause filters out the UPDATE, RETURNING is
            # empty — that's our "unchanged" signal.
            if result.first() is not None:
                changed_rows += 1

        await session.commit()

    duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    unchanged = services_seen - changed_rows

    logger.info(
        "[obs-inference] tier1 tenant=%s provider=%s seen=%d tag=%d none=%d unchanged=%d ms=%d",
        tenant_id, provider_id,
        services_seen, inferred_with_tag, inferred_none, unchanged, duration_ms,
    )
    return InferenceResult(
        services_seen=services_seen,
        inferred_with_tag=inferred_with_tag,
        inferred_none=inferred_none,
        unchanged=unchanged,
        duration_ms=duration_ms,
    )


def _build_metadata(svc) -> dict:
    """Project a `ServiceEntity` onto the JSONB metadata allowlist.

    Layer 1 (`strip_pii`) already ran in the adapter; this allowlist is
    a second-line guard preventing accidental persistence of any
    not-yet-classified vendor field. Anything outside
    `_METADATA_ALLOWED_KEYS` is silently dropped.
    """
    candidate: dict = {}
    if svc.tier:
        candidate["tier"] = svc.tier
    if svc.runtime:
        candidate["runtime"] = svc.runtime
    if svc.owner_squad:
        candidate["team_tag_raw"] = svc.owner_squad
    return {k: v for k, v in candidate.items() if k in _METADATA_ALLOWED_KEYS}


def _json_dumps(value: dict) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Tier 3 — admin override (sync, no provider call)
# ---------------------------------------------------------------------------


async def set_override(
    tenant_id: UUID,
    provider_id: str,
    service_external_id: str,
    squad_key: str,
) -> OwnershipRow:
    """Set `override_squad_key` on an existing ownership row.

    Validates:
      - The service row exists (404 from caller if not).
      - `squad_key` is in the tenant's qualified set
        (raises `InvalidSquadKeyError` → 422 from caller).
    """
    await SquadDirectory.assert_valid_squad(tenant_id, squad_key)

    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                UPDATE service_squad_ownership
                SET override_squad_key = :squad_key, updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND service_external_id = :external_id
                RETURNING service_external_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "external_id": service_external_id,
                "squad_key": squad_key,
            },
        )
        if result.first() is None:
            raise LookupError(
                f"No ownership row for service_external_id={service_external_id!r}"
            )
        await session.commit()

    row = await _get_row(tenant_id, provider_id, service_external_id)
    assert row is not None  # we just updated it
    return row


async def clear_override(
    tenant_id: UUID,
    provider_id: str,
    service_external_id: str,
) -> OwnershipRow:
    """Clear `override_squad_key`. Effective squad falls back to inferred."""
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                UPDATE service_squad_ownership
                SET override_squad_key = NULL, updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND service_external_id = :external_id
                RETURNING service_external_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "external_id": service_external_id,
            },
        )
        if result.first() is None:
            raise LookupError(
                f"No ownership row for service_external_id={service_external_id!r}"
            )
        await session.commit()

    row = await _get_row(tenant_id, provider_id, service_external_id)
    assert row is not None
    return row


# ---------------------------------------------------------------------------
# Read model — list_for_tenant + single-row
# ---------------------------------------------------------------------------


async def list_for_tenant(
    tenant_id: UUID,
    provider_id: str,
) -> list[OwnershipRow]:
    """Return the ownership map for one tenant + provider.

    Adds the derived `effective_squad_key` (`COALESCE(override, inferred)`)
    and `is_qualified_squad` (boolean — true iff effective_squad maps to
    a qualified squad in this tenant). Both computed in SQL — frontend
    just reads.
    """
    qualified = await SquadDirectory.list_qualified_squads(tenant_id)

    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT
                    service_external_id, service_name, repo_url,
                    inferred_squad_key, inferred_confidence,
                    override_squad_key,
                    COALESCE(override_squad_key, inferred_squad_key)
                        AS effective_squad_key,
                    last_inference_at
                FROM service_squad_ownership
                WHERE tenant_id = :tenant_id AND provider = :provider
                ORDER BY service_name ASC
                """
            ),
            {"tenant_id": str(tenant_id), "provider": provider_id},
        )
        rows = result.all()

    return [
        OwnershipRow(
            service_external_id=r.service_external_id,
            service_name=r.service_name,
            repo_url=r.repo_url,
            inferred_squad_key=r.inferred_squad_key,
            inferred_confidence=r.inferred_confidence,
            override_squad_key=r.override_squad_key,
            effective_squad_key=r.effective_squad_key,
            last_inference_at=r.last_inference_at,
            is_qualified_squad=(
                r.effective_squad_key is not None
                and r.effective_squad_key in qualified
            ),
        )
        for r in rows
    ]


async def _get_row(
    tenant_id: UUID,
    provider_id: str,
    service_external_id: str,
) -> OwnershipRow | None:
    """Single-row read used after override mutations."""
    async with get_session(tenant_id) as session:
        result = await session.execute(
            text(
                """
                SELECT
                    service_external_id, service_name, repo_url,
                    inferred_squad_key, inferred_confidence,
                    override_squad_key,
                    COALESCE(override_squad_key, inferred_squad_key)
                        AS effective_squad_key,
                    last_inference_at
                FROM service_squad_ownership
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND service_external_id = :external_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "provider": provider_id,
                "external_id": service_external_id,
            },
        )
        r = result.first()
        if r is None:
            return None

    qualified = await SquadDirectory.list_qualified_squads(tenant_id)
    return OwnershipRow(
        service_external_id=r.service_external_id,
        service_name=r.service_name,
        repo_url=r.repo_url,
        inferred_squad_key=r.inferred_squad_key,
        inferred_confidence=r.inferred_confidence,
        override_squad_key=r.override_squad_key,
        effective_squad_key=r.effective_squad_key,
        last_inference_at=r.last_inference_at,
        is_qualified_squad=(
            r.effective_squad_key is not None
            and r.effective_squad_key in qualified
        ),
    )
