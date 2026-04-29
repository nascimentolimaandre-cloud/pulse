"""Regression tests for FDD-OPS-018 — sprint status normalization.

THE BUG: `normalize_sprint` returned a dict that did NOT include the
`status` field, so all 216 Webmotors sprints landed with status=''
in `eng_sprints`. The connector mapped state correctly (ACTIVE/CLOSED/
FUTURE), but the normalizer dropped it.

Compounding bug: `_upsert_sprints` ON CONFLICT did not update `status`
or `goal` in `set_={...}`, so even fixing the normalizer wouldn't
correct existing rows on re-sync — only newly-created sprints would
land correctly. Active→Closed transitions were silently invisible.

THIS TEST FILE locks in the contract:
  1. The normalizer always emits `status` (lowercase: active/closed/future)
  2. Unknown raw values become None (not silently bucketed)
  3. The normalizer always emits `goal` (string or None)

If a future refactor drops `status` from the return dict again, every
test in the StatusFieldPresent class fails with a precise error pointing
to the contract breach.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.contexts.engineering_data.normalizer import (
    _normalize_sprint_status,
    normalize_sprint,
)


# ---------------------------------------------------------------------------
# Helper — minimal sprint payload as the connector emits
# ---------------------------------------------------------------------------

def _connector_sprint(
    sprint_id: str = "1234",
    status: str | None = "ACTIVE",
    goal: str | None = "Ship the thing",
) -> dict:
    """Mirror what `JiraConnector._map_sprint` returns (ACTIVE/CLOSED/FUTURE)."""
    return {
        "id": f"jira:JiraSprint:1:{sprint_id}",
        "original_board_id": "42",
        "name": "Sprint 99",
        "url": "https://example.atlassian.net",
        "status": status,
        "goal": goal,
        "started_date": "2026-04-01T00:00:00.000Z",
        "ended_date": "2026-04-15T00:00:00.000Z",
        "completed_date": None,
        "total_issues": 0,
    }


# ---------------------------------------------------------------------------
# 1. Normalize sprint emits the status field
# ---------------------------------------------------------------------------

class TestStatusFieldPresent:
    """REGRESSION GUARD: pre-fix, `normalize_sprint` returned a dict without
    a `status` key at all, so every sprint landed with NULL/empty status."""

    def test_active_normalizes_to_lowercase(self):
        result = normalize_sprint(_connector_sprint(status="ACTIVE"), uuid4())
        assert "status" in result, (
            "normalize_sprint dropped the `status` field — eng_sprints.status "
            "would land empty for every sprint. This is the 2026-04-29 bug."
        )
        assert result["status"] == "active"

    def test_closed_normalizes_to_lowercase(self):
        result = normalize_sprint(_connector_sprint(status="CLOSED"), uuid4())
        assert result["status"] == "closed"

    def test_future_normalizes_to_lowercase(self):
        result = normalize_sprint(_connector_sprint(status="FUTURE"), uuid4())
        assert result["status"] == "future"

    def test_already_lowercase_passthrough(self):
        result = normalize_sprint(_connector_sprint(status="active"), uuid4())
        assert result["status"] == "active"

    def test_whitespace_is_stripped(self):
        result = normalize_sprint(_connector_sprint(status="  CLOSED  "), uuid4())
        assert result["status"] == "closed"


# ---------------------------------------------------------------------------
# 2. Unknown / missing values
# ---------------------------------------------------------------------------

class TestUnknownStatusReturnsNone:
    """We deliberately don't bucket unknown values — operators must see
    NULLs in eng_sprints.status and investigate (e.g., new Jira state).
    Silently mapping to one of the known states would corrupt Velocity /
    Carryover logic that relies on knowing which sprints are ACTUALLY
    closed."""

    def test_empty_string_is_none(self):
        result = normalize_sprint(_connector_sprint(status=""), uuid4())
        assert result["status"] is None

    def test_none_is_none(self):
        result = normalize_sprint(_connector_sprint(status=None), uuid4())
        assert result["status"] is None

    def test_unknown_value_is_none(self):
        result = normalize_sprint(_connector_sprint(status="some_new_state"), uuid4())
        assert result["status"] is None

    def test_non_string_is_none(self):
        result = normalize_sprint(_connector_sprint(status=42), uuid4())  # type: ignore[arg-type]
        assert result["status"] is None


# ---------------------------------------------------------------------------
# 3. Aliases — common Jira variants that should map cleanly
# ---------------------------------------------------------------------------

class TestStatusAliases:
    @pytest.mark.parametrize("raw,expected", [
        ("active", "active"),
        ("ACTIVE", "active"),
        ("open", "active"),         # alias
        ("in_progress", "active"),  # alias
        ("closed", "closed"),
        ("CLOSED", "closed"),
        ("completed", "closed"),    # alias
        ("complete", "closed"),     # alias
        ("ended", "closed"),        # alias
        ("future", "future"),
        ("FUTURE", "future"),
        ("planned", "future"),      # alias
        ("upcoming", "future"),     # alias
    ])
    def test_alias_maps_correctly(self, raw, expected):
        assert _normalize_sprint_status(raw) == expected


# ---------------------------------------------------------------------------
# 4. Goal field passthrough (also was previously hardcoded to None)
# ---------------------------------------------------------------------------

class TestGoalFieldPassthrough:
    def test_goal_string_is_preserved(self):
        result = normalize_sprint(
            _connector_sprint(goal="Ship the auth flow this sprint"), uuid4(),
        )
        assert result["goal"] == "Ship the auth flow this sprint"

    def test_none_goal_stays_none(self):
        result = normalize_sprint(_connector_sprint(goal=None), uuid4())
        assert result["goal"] is None

    def test_null_byte_in_goal_is_stripped(self):
        """Postgres `text` rejects 0x00. Same defensive strip we apply to
        title/description/assignee on issues."""
        result = normalize_sprint(
            _connector_sprint(goal="Goal with\x00null byte"), uuid4(),
        )
        assert result["goal"] is not None
        assert "\x00" not in result["goal"]


# ---------------------------------------------------------------------------
# 5. Anti-regression on _upsert_sprints — structural source check
# ---------------------------------------------------------------------------

class TestUpsertSprintsIncludesStatus:
    """REGRESSION GUARD: pre-fix, `_upsert_sprints.on_conflict_do_update.set_`
    omitted `status` and `goal` — so existing sprints kept their stale empty
    status forever even after the normalizer was fixed.

    If a future refactor removes them from the set_ block again, this test
    fails. The check is structural (greps the source) so it doesn't depend
    on a real DB or Jira client.
    """

    def test_upsert_sprints_set_includes_status_and_goal(self):
        from pathlib import Path

        sync_file = (
            Path(__file__).resolve().parents[2] / "src" / "workers" / "devlake_sync.py"
        )
        source = sync_file.read_text()

        start = source.find("async def _upsert_sprints(")
        assert start != -1, "Could not find _upsert_sprints definition"

        # Find next method or top-level def
        end = source.find("\n    async def ", start + 1)
        if end == -1:
            end = source.find("\n    def ", start + 1)
        if end == -1:
            end = len(source)

        body = source[start:end]

        for field in ("status", "goal"):
            assert f'"{field}": sprint_data' in body or f'"{field}":sprint_data' in body, (
                f"_upsert_sprints set_ block must update {field!r} on conflict. "
                "Without it, existing sprints never receive the corrected "
                "value when the connector or normalizer changes."
            )
