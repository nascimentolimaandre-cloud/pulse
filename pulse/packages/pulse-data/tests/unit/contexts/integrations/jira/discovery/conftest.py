"""Shared fixtures for Jira discovery tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_config(
    mode: str = "allowlist",
    discovery_enabled: bool = True,
    max_active_projects: int = 100,
    max_issues_per_hour: int = 20000,
    smart_pr_scan_days: int = 90,
    smart_min_pr_references: int = 3,
    discovery_schedule_cron: str = "0 3 * * *",
) -> dict[str, Any]:
    """Build a tenant_jira_config dict for tests."""
    return {
        "tenant_id": TENANT_ID,
        "mode": mode,
        "discovery_enabled": discovery_enabled,
        "discovery_schedule_cron": discovery_schedule_cron,
        "max_active_projects": max_active_projects,
        "max_issues_per_hour": max_issues_per_hour,
        "smart_pr_scan_days": smart_pr_scan_days,
        "smart_min_pr_references": smart_min_pr_references,
        "last_discovery_at": None,
        "last_discovery_status": None,
        "last_discovery_error": None,
    }


def make_project(
    project_key: str,
    status: str = "discovered",
    pr_reference_count: int = 0,
    consecutive_failures: int = 0,
    activation_source: str | None = None,
) -> dict[str, Any]:
    """Build a jira_project_catalog dict for tests."""
    return {
        "id": uuid.uuid4(),
        "tenant_id": TENANT_ID,
        "project_key": project_key,
        "project_id": f"100{ord(project_key[0])}",
        "name": f"Project {project_key}",
        "project_type": "software",
        "lead_account_id": None,
        "status": status,
        "activation_source": activation_source,
        "issue_count": 0,
        "pr_reference_count": pr_reference_count,
        "first_seen_at": _dt(2026, 1, 1),
        "activated_at": _dt(2026, 1, 1) if status == "active" else None,
        "last_sync_at": None,
        "last_sync_status": None,
        "consecutive_failures": consecutive_failures,
        "last_error": None,
        "metadata": {},
        "created_at": _dt(2026, 1, 1),
        "updated_at": _dt(2026, 1, 1),
    }


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return TENANT_ID
