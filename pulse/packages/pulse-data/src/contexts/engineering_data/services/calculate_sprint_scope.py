"""INC-006 — Sprint scope creep / removal derivation.

Pure-Python reference implementation. The service that calls it (admin
endpoint + forward-hook) handles I/O and persistence; this module is the
canonical specification of the rule and is the unit-test target.

Inputs:
  - One sprint (started_at, ended_at, external_id)
  - The set of issues that ever touched the sprint, each with its
    `sprint_transitions` list (from `eng_issues.sprint_transitions`).
  - Tunables: planning-day grace window (default 1 day).

Outputs:
  committed_items   = #issues that were members of the sprint AT
                      sprint start (within the grace window).
  added_items       = #issues that joined the sprint AFTER start
                      (and stayed in or left during the sprint).
  removed_items     = #issues that left the sprint AFTER start AND
                      DURING the sprint (left after end → counted as
                      normal closure, not removal).

Re-entry handling (per FDD-PIPE-001-style decision):
  Each (issue, sprint) is reduced to its LAST entry / LAST exit. A
  "removed and re-added" cycle within a sprint is treated as a single
  net membership decision rather than a 2× scope-creep event. Same
  philosophy as MTTR's chain-anchor: avoid double-counting churn.

Scope creep %:
  scope_creep_pct = added_items / committed_items   if committed_items > 0
                  = None                            otherwise

This file is the SSOT — the SQL backfill uses Python iteration over
results, so there's no separate SQL CTE to keep aligned.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Tunables (defaults — can be overridden by callers)
# ---------------------------------------------------------------------------

DEFAULT_PLANNING_GRACE_DAYS = 1


@dataclass(frozen=True)
class SprintScope:
    """Output of `calculate_sprint_scope`."""

    committed_items: int
    added_items: int
    removed_items: int
    scope_creep_pct: float | None
    # Diagnostic — # of issues we considered (touched the sprint at any time)
    issues_considered: int


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """Coerce naive timestamps to UTC. Same fix as INC-014 / lean.py."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_at(at_value: Any) -> datetime | None:
    """Parse the `at` field of a transition entry. Tolerant of:
       - str ISO
       - datetime instance
       - None
    """
    if at_value is None:
        return None
    if isinstance(at_value, datetime):
        return _ensure_aware(at_value)
    if isinstance(at_value, str):
        # Jira changelog timestamps end with `+0000` (no colon) — fromisoformat
        # in Python 3.11+ handles this, but be defensive for older Pythons.
        try:
            return _ensure_aware(datetime.fromisoformat(at_value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _last_entry_exit_for_sprint(
    transitions: list[dict[str, Any]],
    sprint_id: str,
) -> tuple[datetime | None, datetime | None]:
    """For a single issue, return (last_entered_at, last_exited_at) for the
    given sprint. Either may be None when the issue never entered (impossible
    if we filtered correctly upstream) or never exited (still in the sprint).
    """
    last_entered: datetime | None = None
    last_exited: datetime | None = None
    for t in transitions:
        if t.get("sprint_id") != sprint_id:
            continue
        at = _parse_at(t.get("at"))
        if at is None:
            continue
        action = t.get("action")
        if action == "entered":
            if last_entered is None or at > last_entered:
                last_entered = at
        elif action == "exited":
            if last_exited is None or at > last_exited:
                last_exited = at
    return last_entered, last_exited


def calculate_sprint_scope(
    sprint_id: str,
    sprint_started_at: datetime | None,
    sprint_ended_at: datetime | None,
    issues: Iterable[dict[str, Any]],
    *,
    planning_grace_days: int = DEFAULT_PLANNING_GRACE_DAYS,
) -> SprintScope:
    """Derive committed / added / removed counts for a single sprint.

    Args:
        sprint_id: PULSE external_id of the sprint
            (e.g. "jira:JiraSprint:1:42").
        sprint_started_at: Sprint planning / activation timestamp.
            REQUIRED — if None, all counts are 0 (we can't decide
            "before vs after start" without a reference point).
        sprint_ended_at: Sprint close timestamp. REQUIRED for `removed`
            (without an end, every exit looks "during sprint"). When
            None, removed_items=0.
        issues: Iterable of dicts with at least a `sprint_transitions`
            key (list of transition entries). Caller should pre-filter
            to issues whose `sprint_transitions` reference this sprint
            for performance, but the function tolerates extras.
        planning_grace_days: Tolerance window after `sprint_started_at`
            during which a NEW entry is still considered "committed",
            not "added". Default 1 day — sprints are rarely planned at
            the exact minute of `started_at`. Set to 0 for strict.

    Returns:
        SprintScope with the four counts + diagnostic.
    """
    sprint_started_at = _ensure_aware(sprint_started_at)
    sprint_ended_at = _ensure_aware(sprint_ended_at)

    if sprint_started_at is None:
        return SprintScope(
            committed_items=0,
            added_items=0,
            removed_items=0,
            scope_creep_pct=None,
            issues_considered=0,
        )

    grace_until = sprint_started_at + timedelta(days=planning_grace_days)

    committed = 0
    added = 0
    removed = 0
    issues_considered = 0

    for issue in issues:
        transitions = issue.get("sprint_transitions") or []
        last_entered, last_exited = _last_entry_exit_for_sprint(transitions, sprint_id)

        if last_entered is None:
            # No entry record for this sprint — issue never joined per
            # changelog. Skip (caller may still pass it if it appears in
            # current `sprint_id` field but that'd be a data anomaly).
            continue

        issues_considered += 1

        if last_entered <= grace_until:
            # Joined within planning grace window → committed
            committed += 1
        else:
            # Joined AFTER planning grace → scope creep
            added += 1

        # Removal: exited DURING the sprint (after start, before end).
        # Exit AFTER end is normal closure (ended_at can be None for
        # active sprints; in that case skip the removal check).
        if last_exited is None:
            continue
        if last_exited <= grace_until:
            # Removed during planning — equivalent to never committed.
            # Don't double-count: this issue won't appear in committed
            # because last_entered is its FINAL entry which is also
            # before grace_until → it's "committed" but also "removed",
            # which makes no sense. The cleanest interpretation is to
            # not count it as removed (planning churn, not scope change).
            continue
        if sprint_ended_at is None or last_exited <= sprint_ended_at:
            removed += 1
        # else: exited after sprint end → normal closure, ignore.

    scope_creep_pct = (added / committed) if committed > 0 else None

    return SprintScope(
        committed_items=committed,
        added_items=added,
        removed_items=removed,
        scope_creep_pct=scope_creep_pct,
        issues_considered=issues_considered,
    )
