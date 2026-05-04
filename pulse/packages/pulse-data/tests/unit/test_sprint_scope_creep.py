"""INC-006 — unit tests for sprint scope creep calculation.

Tests the pure-Python `calculate_sprint_scope` and the
`extract_sprint_transitions_inline` helper. Covers:
  - Boundary cases at the planning grace window (1d default)
  - Re-entry handling (last entry wins)
  - Removed during sprint vs after sprint end
  - Multi-sprint changelog diffs (issue moved between sprints)
  - Defensive parsing (None / whitespace / no-changelog)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.contexts.engineering_data.services.calculate_sprint_scope import (
    DEFAULT_PLANNING_GRACE_DAYS,
    calculate_sprint_scope,
)
from src.workers.devlake_sync import (
    _normalize_sprint_id,
    extract_sprint_transitions_inline,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SPRINT_ID = "jira:JiraSprint:1:42"
SPRINT_STARTED = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
SPRINT_ENDED = datetime(2026, 4, 14, 18, 0, tzinfo=timezone.utc)


def _issue(transitions):
    """Build an issue dict with the given list of transitions."""
    return {"sprint_transitions": transitions}


def _entered(at: datetime, sprint_id: str = SPRINT_ID) -> dict:
    return {"sprint_id": sprint_id, "action": "entered", "at": at.isoformat()}


def _exited(at: datetime, sprint_id: str = SPRINT_ID) -> dict:
    return {"sprint_id": sprint_id, "action": "exited", "at": at.isoformat()}


# ---------------------------------------------------------------------------
# COMMITTED — issue joined within the planning grace window
# ---------------------------------------------------------------------------

class TestCommittedClassification:
    def test_join_at_sprint_start_is_committed(self):
        """Issue entered AT sprint start → committed."""
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([_entered(SPRINT_STARTED)])],
        )
        assert result.committed_items == 1
        assert result.added_items == 0

    def test_join_before_sprint_start_is_committed(self):
        """Issue entered BEFORE sprint start (pre-planning) → committed."""
        before = SPRINT_STARTED - timedelta(hours=2)
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([_entered(before)])],
        )
        assert result.committed_items == 1

    def test_join_within_grace_window_is_committed(self):
        """Issue entered 23h after start (within 1d grace) → committed."""
        within = SPRINT_STARTED + timedelta(hours=23)
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([_entered(within)])],
        )
        assert result.committed_items == 1
        assert result.added_items == 0

    def test_join_at_exact_grace_boundary_is_committed(self):
        """Boundary: entered exactly 1d after start → still committed."""
        boundary = SPRINT_STARTED + timedelta(days=1)
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([_entered(boundary)])],
        )
        assert result.committed_items == 1
        assert result.added_items == 0


# ---------------------------------------------------------------------------
# ADDED — scope creep
# ---------------------------------------------------------------------------

class TestAddedClassification:
    def test_join_just_after_grace_is_added(self):
        """Entered 1d + 1h after start → scope creep."""
        after = SPRINT_STARTED + timedelta(days=1, hours=1)
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([_entered(after)])],
        )
        assert result.added_items == 1
        assert result.committed_items == 0
        assert result.scope_creep_pct is None  # no committed items denominator

    def test_join_mid_sprint_is_added(self):
        """Entered halfway through sprint → scope creep."""
        mid = SPRINT_STARTED + timedelta(days=7)
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([_entered(mid)])],
        )
        assert result.added_items == 1

    def test_scope_creep_pct_with_mixed_committed_and_added(self):
        committed_at = SPRINT_STARTED - timedelta(hours=1)
        added_at = SPRINT_STARTED + timedelta(days=3)
        issues = [
            _issue([_entered(committed_at)]),       # committed
            _issue([_entered(committed_at)]),       # committed
            _issue([_entered(added_at)]),           # added
        ]
        result = calculate_sprint_scope(SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED, issues)
        assert result.committed_items == 2
        assert result.added_items == 1
        assert result.scope_creep_pct == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# REMOVED — exited during sprint
# ---------------------------------------------------------------------------

class TestRemovedClassification:
    def test_exit_during_sprint_is_removed(self):
        """Entered before, exited mid-sprint → removed."""
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([
                _entered(SPRINT_STARTED - timedelta(hours=1)),
                _exited(SPRINT_STARTED + timedelta(days=5)),
            ])],
        )
        assert result.committed_items == 1
        assert result.removed_items == 1

    def test_exit_after_sprint_end_is_not_removed(self):
        """Exit AFTER sprint completion → normal closure, not removed."""
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([
                _entered(SPRINT_STARTED - timedelta(hours=1)),
                _exited(SPRINT_ENDED + timedelta(days=2)),
            ])],
        )
        assert result.committed_items == 1
        assert result.removed_items == 0

    def test_exit_during_planning_grace_is_not_removed(self):
        """Joined and left within planning window → planning churn, not removal."""
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([
                _entered(SPRINT_STARTED + timedelta(hours=1)),
                _exited(SPRINT_STARTED + timedelta(hours=12)),
            ])],
        )
        assert result.removed_items == 0


# ---------------------------------------------------------------------------
# RE-ENTRY — last entry/exit wins
# ---------------------------------------------------------------------------

class TestReEntryHandling:
    def test_re_entry_uses_last_entry(self):
        """Out → In within sprint counts only the LAST entry. Per the
        decision: 'movi pro próximo sprint, voltei atrás' is one net change."""
        early_exit = SPRINT_STARTED - timedelta(days=2)
        late_entry = SPRINT_STARTED + timedelta(days=3)
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([
                _entered(SPRINT_STARTED - timedelta(days=5)),  # original
                _exited(early_exit),
                _entered(late_entry),
            ])],
        )
        # Last entry = late_entry (after grace) → added
        # No exit AFTER late_entry → not removed
        assert result.added_items == 1
        assert result.removed_items == 0


# ---------------------------------------------------------------------------
# MULTI-SPRINT — changelog diffs that mention multiple sprints
# ---------------------------------------------------------------------------

class TestMultiSprint:
    def test_other_sprint_transitions_ignored(self):
        """Transitions for a different sprint don't affect this sprint's count."""
        other_sprint = "jira:JiraSprint:1:99"
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([
                _entered(SPRINT_STARTED, sprint_id=other_sprint),
                _exited(SPRINT_STARTED + timedelta(days=2), sprint_id=other_sprint),
            ])],
        )
        assert result.committed_items == 0
        assert result.added_items == 0
        assert result.issues_considered == 0


# ---------------------------------------------------------------------------
# EDGE CASES
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_started_at_returns_zeros(self):
        """Sprint without a started_at can't classify — returns zeros."""
        result = calculate_sprint_scope(SPRINT_ID, None, None, [])
        assert result.committed_items == 0
        assert result.added_items == 0
        assert result.scope_creep_pct is None

    def test_active_sprint_no_ended_at_no_removed(self):
        """Active sprint (ended_at=None) — exits are still classified BUT
        only as 'removed' if also after grace; here no end means we treat
        the exit as 'during sprint'."""
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, None,
            [_issue([
                _entered(SPRINT_STARTED - timedelta(hours=1)),
                _exited(SPRINT_STARTED + timedelta(days=3)),
            ])],
        )
        assert result.removed_items == 1  # active sprint counts mid-flight removals

    def test_empty_issues_returns_zeros(self):
        result = calculate_sprint_scope(SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED, [])
        assert result.committed_items == 0
        assert result.scope_creep_pct is None

    def test_planning_grace_zero_strict(self):
        """With grace=0, even +1ms after start is added."""
        result = calculate_sprint_scope(
            SPRINT_ID, SPRINT_STARTED, SPRINT_ENDED,
            [_issue([_entered(SPRINT_STARTED + timedelta(milliseconds=1))])],
            planning_grace_days=0,
        )
        assert result.added_items == 1
        assert result.committed_items == 0

    def test_default_grace_constant(self):
        assert DEFAULT_PLANNING_GRACE_DAYS == 1


# ---------------------------------------------------------------------------
# extract_sprint_transitions_inline — Jira changelog parsing
# ---------------------------------------------------------------------------

class TestExtractSprintTransitionsInline:
    def test_extracts_entered_and_exited_from_diff(self):
        """Issue moved from sprint 1 to sprint 2 → exit 1, enter 2."""
        raw = {
            "id": "10001",
            "changelog": {
                "histories": [{
                    "created": "2026-04-05T10:00:00.000+0000",
                    "items": [{
                        "field": "Sprint",
                        "from": "1",
                        "to": "2",
                    }],
                }],
            },
        }
        transitions = extract_sprint_transitions_inline(raw, connection_id="1")
        assert len(transitions) == 2
        actions = sorted((t["action"], t["sprint_id"]) for t in transitions)
        assert actions == [
            ("entered", "jira:JiraSprint:1:2"),
            ("exited", "jira:JiraSprint:1:1"),
        ]

    def test_handles_multi_sprint_to(self):
        """Issue added to a 2nd sprint while keeping the 1st: from='1' to='1, 2'."""
        raw = {
            "id": "10001",
            "changelog": {
                "histories": [{
                    "created": "2026-04-05T10:00:00.000+0000",
                    "items": [{
                        "field": "Sprint",
                        "from": "1",
                        "to": "1, 2",
                    }],
                }],
            },
        }
        transitions = extract_sprint_transitions_inline(raw, connection_id="1")
        # Only sprint 2 is new — sprint 1 stayed
        assert len(transitions) == 1
        assert transitions[0]["sprint_id"] == "jira:JiraSprint:1:2"
        assert transitions[0]["action"] == "entered"

    def test_handles_empty_from(self):
        """Issue first added to a sprint: from='' to='1'."""
        raw = {
            "id": "10001",
            "changelog": {
                "histories": [{
                    "created": "2026-04-05T10:00:00.000+0000",
                    "items": [{"field": "Sprint", "from": "", "to": "1"}],
                }],
            },
        }
        transitions = extract_sprint_transitions_inline(raw, connection_id="1")
        assert len(transitions) == 1
        assert transitions[0]["action"] == "entered"

    def test_handles_empty_to(self):
        """Issue removed from all sprints: from='1' to=''."""
        raw = {
            "id": "10001",
            "changelog": {
                "histories": [{
                    "created": "2026-04-05T10:00:00.000+0000",
                    "items": [{"field": "Sprint", "from": "1", "to": ""}],
                }],
            },
        }
        transitions = extract_sprint_transitions_inline(raw, connection_id="1")
        assert len(transitions) == 1
        assert transitions[0]["action"] == "exited"

    def test_ignores_non_sprint_field_changes(self):
        """Status / Assignee / etc. changes don't show up here."""
        raw = {
            "id": "10001",
            "changelog": {
                "histories": [{
                    "created": "2026-04-05T10:00:00.000+0000",
                    "items": [
                        {"field": "status", "from": "Open", "to": "Done"},
                        {"field": "assignee", "from": "alice", "to": "bob"},
                    ],
                }],
            },
        }
        transitions = extract_sprint_transitions_inline(raw, connection_id="1")
        assert transitions == []

    def test_no_changelog_returns_empty(self):
        transitions = extract_sprint_transitions_inline({"id": "1"}, connection_id="1")
        assert transitions == []

    def test_transitions_sorted_by_at(self):
        """Multiple history items → output is chronologically sorted."""
        raw = {
            "id": "10001",
            "changelog": {
                "histories": [
                    {
                        "created": "2026-04-10T10:00:00.000+0000",
                        "items": [{"field": "Sprint", "from": "1", "to": "2"}],
                    },
                    {
                        "created": "2026-04-05T10:00:00.000+0000",
                        "items": [{"field": "Sprint", "from": "", "to": "1"}],
                    },
                ],
            },
        }
        transitions = extract_sprint_transitions_inline(raw, connection_id="1")
        # All three events sorted ASC: enter 1 (5th), exit 1 + enter 2 (10th)
        assert transitions[0]["at"].startswith("2026-04-05")


# ---------------------------------------------------------------------------
# _normalize_sprint_id helper
# ---------------------------------------------------------------------------

class TestNormalizeSprintId:
    def test_raw_id_gets_prefixed(self):
        assert _normalize_sprint_id("42", "1") == "jira:JiraSprint:1:42"

    def test_already_normalized_passes_through(self):
        full = "jira:JiraSprint:7:99"
        assert _normalize_sprint_id(full, "1") == full

    def test_strips_whitespace(self):
        assert _normalize_sprint_id("  42  ", "1") == "jira:JiraSprint:1:42"

    def test_empty_returns_empty(self):
        assert _normalize_sprint_id("", "1") == ""
