"""FDD-OBS-001 PR 3 — ownership_inference unit tests.

Validates:
  - Tier-1 sync upserts inferred fields, never touches override_squad_key.
  - Idempotency: WHERE clause skips no-op updates.
  - PII allowlist on metadata JSONB (M-001-style defense-in-depth).
  - set_override calls SquadDirectory.assert_valid_squad before persisting.
  - clear_override / set_override raise LookupError on unknown service.
  - list_for_tenant computes effective_squad_key + is_qualified_squad.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.connectors.observability.base import ObservabilityProvider, ServiceEntity
from src.contexts.observability.services import ownership_inference
from src.contexts.observability.services.ownership_inference import (
    InferenceResult,
    sync_tier1_inference,
    set_override,
    clear_override,
    list_for_tenant,
    _build_metadata,
)
from src.contexts.observability.services.squad_directory import (
    InvalidSquadKeyError,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session_cm(execute_mock: AsyncMock) -> MagicMock:
    session = AsyncMock()
    session.execute = execute_mock
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _service(
    name: str,
    *,
    external_id: str | None = None,
    owner_squad: str | None = None,
    tier: str | None = None,
    runtime: str | None = None,
    repo_url: str | None = None,
) -> ServiceEntity:
    return ServiceEntity(
        service_name=name,
        external_id=external_id or f"id-{name}",
        owner_squad=owner_squad,
        repo_url=repo_url,
        runtime=runtime,
        tier=tier,
    )


def _row(**kwargs) -> MagicMock:
    r = MagicMock()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


# ---------------------------------------------------------------------------
# Tier 1 sync
# ---------------------------------------------------------------------------


class TestTier1Sync:
    @pytest.mark.asyncio
    async def test_empty_catalog_returns_zero_result_no_db_writes(self):
        provider = MagicMock(spec=ObservabilityProvider)
        provider.list_services = AsyncMock(return_value=[])

        with patch.object(ownership_inference, "get_session") as session_mock:
            result = await sync_tier1_inference(_TENANT, "datadog", provider)
            session_mock.assert_not_called()

        assert result.services_seen == 0
        assert result.inferred_with_tag == 0
        assert result.inferred_none == 0

    @pytest.mark.asyncio
    async def test_services_with_tags_get_confidence_tag(self):
        services = [
            _service("checkout", owner_squad="FID", tier="tier-1"),
            _service("billing", owner_squad="OKM"),
        ]
        provider = MagicMock(spec=ObservabilityProvider)
        provider.list_services = AsyncMock(return_value=services)

        execute = AsyncMock()
        # Each upsert returns a row -> "changed"
        execute.return_value = MagicMock()
        execute.return_value.first = MagicMock(return_value=_row(inserted=True))

        with patch.object(
            ownership_inference, "get_session", return_value=_mock_session_cm(execute),
        ):
            result = await sync_tier1_inference(_TENANT, "datadog", provider)

        assert result.services_seen == 2
        assert result.inferred_with_tag == 2
        assert result.inferred_none == 0

        # Verify the SQL upsert was called twice with the right squad
        assert execute.await_count == 2
        first_call_params = execute.await_args_list[0].args[1]
        assert first_call_params["inferred_squad_key"] == "FID"
        assert first_call_params["inferred_confidence"] == "tag"

    @pytest.mark.asyncio
    async def test_services_without_tags_get_confidence_none(self):
        provider = MagicMock(spec=ObservabilityProvider)
        provider.list_services = AsyncMock(return_value=[
            _service("orphan-svc", owner_squad=None),
        ])
        execute = AsyncMock()
        execute.return_value = MagicMock()
        execute.return_value.first = MagicMock(return_value=_row(inserted=True))

        with patch.object(
            ownership_inference, "get_session", return_value=_mock_session_cm(execute),
        ):
            result = await sync_tier1_inference(_TENANT, "datadog", provider)

        assert result.inferred_none == 1
        params = execute.await_args.args[1]
        assert params["inferred_squad_key"] is None
        assert params["inferred_confidence"] == "none"

    @pytest.mark.asyncio
    async def test_upsert_does_not_touch_override_squad_key(self):
        """The DO UPDATE SET clause must omit override_squad_key —
        admin-set overrides survive re-inference."""
        provider = MagicMock(spec=ObservabilityProvider)
        provider.list_services = AsyncMock(return_value=[_service("x", owner_squad="FID")])
        execute = AsyncMock()
        execute.return_value = MagicMock()
        execute.return_value.first = MagicMock(return_value=_row(inserted=True))

        with patch.object(
            ownership_inference, "get_session", return_value=_mock_session_cm(execute),
        ):
            await sync_tier1_inference(_TENANT, "datadog", provider)

        sql = str(execute.await_args.args[0])
        assert "DO UPDATE SET" in sql
        # The DO UPDATE clause must NOT contain override_squad_key.
        update_section = sql.split("DO UPDATE SET")[1]
        assert "override_squad_key" not in update_section, (
            "Tier-1 sync MUST NOT overwrite admin-set overrides"
        )

    @pytest.mark.asyncio
    async def test_idempotency_unchanged_count(self):
        """When RETURNING is empty (WHERE clause filtered out the
        update), the row is counted as unchanged."""
        provider = MagicMock(spec=ObservabilityProvider)
        provider.list_services = AsyncMock(return_value=[
            _service("a"), _service("b"), _service("c"),
        ])

        # 1st call returns row (changed), 2nd returns None (unchanged), 3rd returns None
        results = []
        for inserted in (True, False, False):
            r = MagicMock()
            r.first = MagicMock(return_value=_row(inserted=inserted) if inserted else None)
            results.append(r)
        execute = AsyncMock(side_effect=results)

        with patch.object(
            ownership_inference, "get_session", return_value=_mock_session_cm(execute),
        ):
            result = await sync_tier1_inference(_TENANT, "datadog", provider)

        assert result.services_seen == 3
        assert result.unchanged == 2
        assert result.total_changed == 1


# ---------------------------------------------------------------------------
# _build_metadata — Layer 1 explicit allowlist
# ---------------------------------------------------------------------------


class TestBuildMetadata:
    def test_keeps_allowlisted_fields(self):
        svc = _service("x", owner_squad="FID", tier="tier-1", runtime="python")
        meta = _build_metadata(svc)
        assert meta["team_tag_raw"] == "FID"
        assert meta["tier"] == "tier-1"
        assert meta["runtime"] == "python"

    def test_drops_unknown_fields(self):
        """Even if ServiceEntity gained new fields, _build_metadata
        only persists allowlisted ones (defense in depth)."""
        svc = _service("x", owner_squad="FID")
        meta = _build_metadata(svc)
        # Only allowlisted keys appear
        for key in meta.keys():
            assert key in {"team_tag_raw", "owner_tag_raw", "dd_service_type", "tier", "runtime"}


# ---------------------------------------------------------------------------
# Override (Tier 3) — squad-key validation + persistence
# ---------------------------------------------------------------------------


class TestSetOverride:
    @pytest.mark.asyncio
    async def test_invalid_squad_raises_before_db_write(self):
        with patch(
            "src.contexts.observability.services.ownership_inference."
            "SquadDirectory.assert_valid_squad",
            new=AsyncMock(side_effect=InvalidSquadKeyError("GHOST")),
        ), patch.object(
            ownership_inference, "get_session",
        ) as session_mock:
            with pytest.raises(InvalidSquadKeyError):
                await set_override(_TENANT, "datadog", "svc-1", "GHOST")
            session_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_service_raises_lookup(self):
        update_result = MagicMock()
        update_result.first.return_value = None  # no row updated
        execute = AsyncMock(return_value=update_result)

        with patch(
            "src.contexts.observability.services.ownership_inference."
            "SquadDirectory.assert_valid_squad",
            new=AsyncMock(return_value=None),
        ), patch.object(
            ownership_inference, "get_session", return_value=_mock_session_cm(execute),
        ):
            with pytest.raises(LookupError):
                await set_override(_TENANT, "datadog", "missing", "FID")


class TestClearOverride:
    @pytest.mark.asyncio
    async def test_unknown_service_raises_lookup(self):
        update_result = MagicMock()
        update_result.first.return_value = None
        execute = AsyncMock(return_value=update_result)

        with patch.object(
            ownership_inference, "get_session", return_value=_mock_session_cm(execute),
        ):
            with pytest.raises(LookupError):
                await clear_override(_TENANT, "datadog", "missing")


# ---------------------------------------------------------------------------
# list_for_tenant — read model
# ---------------------------------------------------------------------------


class TestListForTenant:
    @pytest.mark.asyncio
    async def test_computes_effective_squad_and_qualified_flag(self):
        rows = [
            _row(
                service_external_id="svc-1",
                service_name="checkout",
                repo_url=None,
                inferred_squad_key="FID",
                inferred_confidence="tag",
                override_squad_key=None,
                effective_squad_key="FID",
                last_inference_at=datetime.now(timezone.utc),
            ),
            _row(
                service_external_id="svc-2",
                service_name="billing",
                repo_url=None,
                inferred_squad_key="GHOST",
                inferred_confidence="tag",
                override_squad_key=None,
                effective_squad_key="GHOST",
                last_inference_at=datetime.now(timezone.utc),
            ),
        ]
        result = MagicMock()
        result.all.return_value = rows
        execute = AsyncMock(return_value=result)

        with patch.object(
            ownership_inference, "get_session", return_value=_mock_session_cm(execute),
        ), patch(
            "src.contexts.observability.services.ownership_inference."
            "SquadDirectory.list_qualified_squads",
            new=AsyncMock(return_value=frozenset({"FID"})),
        ):
            out = await list_for_tenant(_TENANT, "datadog")

        assert len(out) == 2
        assert out[0].is_qualified_squad is True   # FID ∈ qualified
        assert out[1].is_qualified_squad is False  # GHOST ∉ qualified
