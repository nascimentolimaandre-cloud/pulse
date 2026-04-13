"""ProjectDiscoveryService — orchestrates a full discovery run for a tenant.

Calls the Jira API to list all accessible projects, diffs against the
catalog, and updates statuses based on the tenant's discovery mode.
Robust to partial Jira failures: catches per-page errors and continues.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.contexts.integrations.jira.discovery.guardrails import Guardrails
from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository
from src.contexts.integrations.jira.discovery.smart_prioritizer import SmartPrioritizer

logger = logging.getLogger(__name__)


class ProjectDiscoveryService:
    """Runs a full Jira project discovery cycle for a tenant."""

    def __init__(
        self,
        session: AsyncSession,
        jira_client: Any = None,
    ) -> None:
        self._session = session
        self._repo = DiscoveryRepository(session)
        self._jira_client = jira_client
        self._prioritizer = SmartPrioritizer(session)
        self._guardrails = Guardrails(session)

    async def run_discovery(self, tenant_id: UUID) -> dict[str, Any]:
        """Execute a full discovery run. Returns a JiraDiscoveryResult-shaped dict."""
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        errors: list[str] = []

        result = {
            "runId": run_id,
            "startedAt": started_at.isoformat(),
            "finishedAt": None,
            "status": "success",
            "discoveredCount": 0,
            "activatedCount": 0,
            "archivedCount": 0,
            "updatedCount": 0,
            "errors": errors,
        }

        # 1. Load tenant config
        config = await self._repo.get_tenant_config(tenant_id)
        if not config or not config.get("discovery_enabled", True):
            result["finishedAt"] = datetime.now(timezone.utc).isoformat()
            logger.info("Discovery disabled or no config for tenant %s", tenant_id)
            return result

        mode = config["mode"]

        # 2. Fetch all accessible projects from Jira
        if not self._jira_client:
            errors.append("No Jira client configured")
            result["status"] = "failed"
            result["finishedAt"] = datetime.now(timezone.utc).isoformat()
            return result

        jira_projects: list[dict[str, Any]] = []
        try:
            jira_projects = await self._jira_client.fetch_all_accessible_projects()
        except Exception as exc:
            error_msg = f"Failed to fetch Jira projects: {exc}"
            errors.append(error_msg)
            logger.exception(error_msg)
            # Total failure — no projects fetched at all
            result["status"] = "failed"
            result["errors"] = errors
            result["finishedAt"] = datetime.now(timezone.utc).isoformat()
            return result

        # 3. Load existing catalog for diff
        existing_projects, _ = await self._repo.list_projects(
            tenant_id, limit=100000, offset=0,
        )
        existing_by_key: dict[str, dict] = {
            p["project_key"]: p for p in existing_projects
        }

        jira_keys_seen: set[str] = set()

        # 4. Process each discovered project
        for jp in jira_projects:
            key = jp.get("project_key", "")
            if not key:
                continue
            jira_keys_seen.add(key)

            existing = existing_by_key.get(key)

            if existing is None:
                # New project
                initial_status = "active" if mode == "auto" else "discovered"
                activation_source = "auto_mode" if mode == "auto" else None
                activated_at = datetime.now(timezone.utc) if mode == "auto" else None

                try:
                    await self._repo.upsert_project(
                        tenant_id,
                        key,
                        project_id=jp.get("project_id"),
                        name=jp.get("name"),
                        project_type=jp.get("project_type"),
                        lead_account_id=jp.get("lead_account_id"),
                        status=initial_status,
                        activation_source=activation_source,
                        activated_at=activated_at,
                    )
                    result["discoveredCount"] += 1
                    if initial_status == "active":
                        result["activatedCount"] += 1
                except Exception as exc:
                    errors.append(f"Failed to insert project {key}: {exc}")
                    logger.exception("Failed to insert project %s", key)
            else:
                # Existing project — update metadata if changed
                changed = False
                for field in ("name", "project_type", "lead_account_id"):
                    if jp.get(field) and jp.get(field) != existing.get(field):
                        changed = True
                        break

                if changed:
                    try:
                        await self._repo.upsert_project(
                            tenant_id,
                            key,
                            project_id=jp.get("project_id"),
                            name=jp.get("name"),
                            project_type=jp.get("project_type"),
                            lead_account_id=jp.get("lead_account_id"),
                        )
                        result["updatedCount"] += 1
                    except Exception as exc:
                        errors.append(f"Failed to update project {key}: {exc}")

        # 5. Archive projects no longer in Jira
        for key, existing in existing_by_key.items():
            if key not in jira_keys_seen and existing["status"] not in ("blocked", "archived"):
                try:
                    await self._repo.update_project_status(
                        tenant_id, key,
                        status="archived",
                        actor="system",
                        reason="Project no longer returned by Jira API",
                    )
                    result["archivedCount"] += 1
                except Exception as exc:
                    errors.append(f"Failed to archive project {key}: {exc}")

        # 6. If smart mode, score and auto-activate
        if mode == "smart":
            try:
                await self._prioritizer.score_projects(tenant_id)
                activated = await self._prioritizer.auto_activate(tenant_id)
                result["activatedCount"] += activated
            except Exception as exc:
                errors.append(f"Smart prioritizer error: {exc}")
                logger.exception("Smart prioritizer failed for tenant %s", tenant_id)

        # 7. Enforce project cap
        try:
            await self._guardrails.enforce_project_cap(tenant_id)
        except Exception as exc:
            errors.append(f"Guardrails cap enforcement error: {exc}")

        # 8. Update tenant config with discovery results
        finished_at = datetime.now(timezone.utc)
        discovery_status = "partial" if errors else "success"
        result["status"] = discovery_status
        result["finishedAt"] = finished_at.isoformat()

        try:
            await self._repo.upsert_tenant_config(
                tenant_id,
                last_discovery_at=finished_at,
                last_discovery_status=discovery_status,
                last_discovery_error="; ".join(errors) if errors else None,
            )
        except Exception as exc:
            logger.exception("Failed to update tenant config after discovery: %s", exc)

        # 9. Audit event
        try:
            await self._repo.append_audit(
                tenant_id,
                event_type="discovery_run",
                actor="system",
                after={
                    "run_id": run_id,
                    "discovered": result["discoveredCount"],
                    "activated": result["activatedCount"],
                    "archived": result["archivedCount"],
                    "updated": result["updatedCount"],
                    "status": discovery_status,
                },
                reason=f"Discovery run completed: {discovery_status}",
            )
        except Exception as exc:
            logger.exception("Failed to write discovery audit: %s", exc)

        logger.info(
            "Discovery run %s for tenant %s: discovered=%d activated=%d archived=%d updated=%d status=%s",
            run_id, tenant_id,
            result["discoveredCount"], result["activatedCount"],
            result["archivedCount"], result["updatedCount"],
            discovery_status,
        )

        return result
