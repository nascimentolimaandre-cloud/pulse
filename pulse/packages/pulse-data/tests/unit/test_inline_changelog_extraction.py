"""Regression tests for FDD-OPS-013 — inline changelog extraction.

Locks in the contract that `_sync_issues` extracts status transitions from
the JQL response payload (`raw_issue["changelog"]["histories"]`) WITHOUT
making additional HTTP round-trips per issue.

Why this matters: the previous implementation called
`self._reader.fetch_issue_changelogs(issue_ids)` after `fetch_issues`,
which performed one `GET /issue/{id}?expand=changelog` per issue. For
Webmotors-scale tenants (~376k issues), this took 24+ hours of pure
HTTP latency. After this fix, the same data is extracted from the
already-loaded JQL response in a few milliseconds.

If a future refactor reintroduces the round-trip pattern, these tests
should fail and force the author to confront the cost.
"""

from __future__ import annotations

import pytest

from src.workers.devlake_sync import extract_status_transitions_inline


# ---------------------------------------------------------------------------
# Fixtures — shape mirrors real Jira JQL `expand=changelog` response
# ---------------------------------------------------------------------------

def _jira_issue_with_changelog(issue_id: str, histories: list[dict]) -> dict:
    """Build a fake Jira JQL response item with inline changelog."""
    return {
        "id": issue_id,
        "key": f"TEST-{issue_id}",
        "fields": {"status": {"name": "In Progress"}},
        "changelog": {"histories": histories},
    }


@pytest.fixture
def issue_with_two_status_transitions() -> dict:
    """Realistic case: a typical issue moves through To Do → In Progress → Done."""
    return _jira_issue_with_changelog(
        issue_id="100200",
        histories=[
            {
                "created": "2026-01-15T10:00:00.000+0000",
                "items": [
                    {
                        "field": "Status",
                        "fromString": "To Do",
                        "toString": "In Progress",
                    },
                ],
            },
            {
                "created": "2026-01-20T16:30:00.000+0000",
                "items": [
                    {
                        "field": "Status",
                        "fromString": "In Progress",
                        "toString": "Done",
                    },
                ],
            },
        ],
    )


@pytest.fixture
def issue_with_no_changelog() -> dict:
    """Edge case: brand-new issue, never moved status. Pre-fix this caused
    the cache miss → downstream HTTP call. Now must return [] safely."""
    return _jira_issue_with_changelog(issue_id="100300", histories=[])


@pytest.fixture
def issue_with_mixed_history() -> dict:
    """Realistic: changelog has Status changes mixed with non-Status events
    (assignee, priority, summary). Only Status events become transitions."""
    return _jira_issue_with_changelog(
        issue_id="100400",
        histories=[
            {
                "created": "2026-02-01T09:00:00.000+0000",
                "items": [
                    {"field": "Assignee", "fromString": "Alice", "toString": "Bob"},
                ],
            },
            {
                "created": "2026-02-02T11:00:00.000+0000",
                "items": [
                    {"field": "Status", "fromString": "To Do", "toString": "In Progress"},
                    {"field": "Priority", "fromString": "Medium", "toString": "High"},
                ],
            },
            {
                "created": "2026-02-03T14:00:00.000+0000",
                "items": [
                    {"field": "Summary", "fromString": "Foo", "toString": "Foo bar"},
                ],
            },
        ],
    )


@pytest.fixture
def issue_with_unsorted_history() -> dict:
    """Defensive: Jira occasionally returns histories out of chronological
    order. The extracted transitions must be sorted by created_date so
    `build_status_transitions` (downstream) computes correct durations."""
    return _jira_issue_with_changelog(
        issue_id="100500",
        histories=[
            {
                "created": "2026-03-15T12:00:00.000+0000",  # later
                "items": [
                    {"field": "Status", "fromString": "B", "toString": "C"},
                ],
            },
            {
                "created": "2026-03-10T09:00:00.000+0000",  # earlier
                "items": [
                    {"field": "Status", "fromString": "A", "toString": "B"},
                ],
            },
        ],
    )


# ---------------------------------------------------------------------------
# Behavioral tests
# ---------------------------------------------------------------------------

class TestExtractStatusTransitionsInline:
    def test_extracts_two_status_transitions(self, issue_with_two_status_transitions):
        result = extract_status_transitions_inline(issue_with_two_status_transitions)
        assert len(result) == 2
        assert result[0]["from_status"] == "To Do"
        assert result[0]["to_status"] == "In Progress"
        assert result[1]["from_status"] == "In Progress"
        assert result[1]["to_status"] == "Done"

    def test_each_transition_carries_issue_id(self, issue_with_two_status_transitions):
        result = extract_status_transitions_inline(issue_with_two_status_transitions)
        assert all(t["issue_id"] == "100200" for t in result)

    def test_each_transition_carries_created_date(self, issue_with_two_status_transitions):
        result = extract_status_transitions_inline(issue_with_two_status_transitions)
        assert result[0]["created_date"] == "2026-01-15T10:00:00.000+0000"
        assert result[1]["created_date"] == "2026-01-20T16:30:00.000+0000"

    def test_empty_changelog_returns_empty_list(self, issue_with_no_changelog):
        """REGRESSION GUARD: pre-fix, this case caused cache-miss + HTTP fallback.
        Must always return a list, even if empty. Never None, never raise."""
        result = extract_status_transitions_inline(issue_with_no_changelog)
        assert result == []
        assert isinstance(result, list)

    def test_only_status_field_events_are_extracted(self, issue_with_mixed_history):
        """Assignee, Priority, Summary changes don't become transitions."""
        result = extract_status_transitions_inline(issue_with_mixed_history)
        assert len(result) == 1
        assert result[0]["from_status"] == "To Do"
        assert result[0]["to_status"] == "In Progress"

    def test_status_field_match_is_case_insensitive(self):
        """Defensive: Jira sometimes returns 'status', sometimes 'Status'."""
        for field_name in ("Status", "status", "STATUS"):
            issue = _jira_issue_with_changelog(
                issue_id="999",
                histories=[
                    {
                        "created": "2026-01-01T00:00:00.000+0000",
                        "items": [
                            {"field": field_name, "fromString": "X", "toString": "Y"},
                        ],
                    },
                ],
            )
            result = extract_status_transitions_inline(issue)
            assert len(result) == 1, f"failed for field name {field_name!r}"

    def test_transitions_are_chronologically_sorted(self, issue_with_unsorted_history):
        """Downstream metric calculations depend on ordered transitions."""
        result = extract_status_transitions_inline(issue_with_unsorted_history)
        assert len(result) == 2
        assert result[0]["created_date"] == "2026-03-10T09:00:00.000+0000"
        assert result[1]["created_date"] == "2026-03-15T12:00:00.000+0000"

    def test_returns_empty_for_issue_without_changelog_key(self):
        """Defensive: issue from Jira API may lack `changelog` key entirely."""
        result = extract_status_transitions_inline(
            {"id": "555", "key": "X-1", "fields": {}}
        )
        assert result == []

    def test_returns_empty_for_changelog_without_histories(self):
        """Defensive: `changelog: {}` without `histories` key."""
        result = extract_status_transitions_inline(
            {"id": "555", "key": "X-1", "changelog": {}}
        )
        assert result == []


# ---------------------------------------------------------------------------
# Anti-regression: the redundant HTTP call must NEVER come back
# ---------------------------------------------------------------------------

class TestSyncIssuesDoesNotCallFetchIssueChangelogs:
    """If a future refactor reintroduces the per-issue HTTP fallback in
    `_sync_issues`, this test fails. The check is structural — it greps
    the source — to keep the test independent of any DB or network setup.

    Note: `fetch_issue_changelogs` may STILL be called from sprint sync
    (where issues come without `expand=changelog`). This test scopes its
    assertion to `_sync_issues` only.
    """

    def test_sync_issues_does_not_call_fetch_issue_changelogs(self):
        """Source-grep: `_sync_issues` body must not reference `fetch_issue_changelogs`.

        If you really need it back, remove this test AND amend FDD-OPS-013
        in ops-backlog.md AND benchmark the new approach against
        Webmotors-scale dataset (376k issues).
        """
        from pathlib import Path

        sync_file = Path(__file__).resolve().parents[2] / "src" / "workers" / "devlake_sync.py"
        source = sync_file.read_text()

        # Find the _sync_issues body — from "async def _sync_issues" until
        # the next "async def" or "def " at the same indentation.
        start = source.find("async def _sync_issues(")
        assert start != -1, "Could not find _sync_issues definition"

        # Find next method def at same indent (4 spaces, prefixed with newline).
        end = source.find("\n    async def ", start + 1)
        if end == -1:
            end = source.find("\n    def ", start + 1)
        assert end != -1, "Could not find end of _sync_issues body"

        sync_issues_body = source[start:end]

        # Only flag actual function CALLS (`.fetch_issue_changelogs(` or
        # `await fetch_issue_changelogs(`), not comments or docstrings that
        # reference the name historically. The pattern matches a call
        # expression, not free text.
        import re
        call_pattern = re.compile(r"(?<![A-Za-z_])fetch_issue_changelogs\s*\(")
        # But we still allow the function name to appear in comments/strings.
        # Strip Python comments before matching to avoid false positives.
        body_no_comments = re.sub(r"#[^\n]*", "", sync_issues_body)
        # Strip triple-quoted strings (docstrings)
        body_no_comments = re.sub(
            r'"""[\s\S]*?"""', "", body_no_comments,
        )

        match = call_pattern.search(body_no_comments)
        assert match is None, (
            "FDD-OPS-013 regression: _sync_issues is calling "
            "fetch_issue_changelogs() again at offset "
            f"{match.start() if match else '?'}. This makes one HTTP "
            "round-trip per issue and was the cause of the 2026-04-28 "
            "24h-stuck incident. Use extract_status_transitions_inline(raw) "
            "instead — changelogs are already inline in the JQL response "
            "(expand=changelog)."
        )


# ---------------------------------------------------------------------------
# End-to-end: connector mapping → inline extraction
# ---------------------------------------------------------------------------

class TestMapIssuePreservesChangelogForInlineExtraction:
    """REGRESSION GUARD (2026-04-27 incident).

    `JiraConnector._map_issue` originally extracted the changelog into a
    side-cache (`self._last_changelogs`) but did NOT include it in the
    returned mapped dict. The new `_sync_issues` flow reads
    `raw["changelog"]["histories"]` from the mapped dict via
    `extract_status_transitions_inline()` — so 311k issues landed in
    `eng_issues` with `status_transitions=[]`, breaking every Lean and
    Cycle Time metric downstream.

    This test wires the connector mapping to the inline extractor end-to-end
    and asserts that real Jira API shape produces non-empty transitions.
    """

    def test_map_issue_output_yields_status_transitions_when_changelog_present(self):
        from src.connectors.jira_connector import JiraConnector

        # Build a Jira API issue payload mirroring what `expand=changelog` returns.
        jira_api_response = {
            "id": "100200",
            "key": "TEST-1",
            "fields": {
                "summary": "do the thing",
                "status": {"name": "Done"},
                "priority": {"name": "Medium"},
                "issuetype": {"name": "Task"},
                "assignee": {"displayName": "Alice"},
                "created": "2026-01-15T10:00:00.000+0000",
                "updated": "2026-01-20T16:30:00.000+0000",
                "resolutiondate": "2026-01-20T16:30:00.000+0000",
                "description": None,
            },
            "changelog": {
                "histories": [
                    {
                        "created": "2026-01-15T10:00:00.000+0000",
                        "items": [
                            {"field": "Status", "fromString": "To Do",
                             "toString": "In Progress"},
                        ],
                    },
                    {
                        "created": "2026-01-20T16:30:00.000+0000",
                        "items": [
                            {"field": "Status", "fromString": "In Progress",
                             "toString": "Done"},
                        ],
                    },
                ],
            },
        }

        # Instantiate without hitting the network — supply minimal config.
        connector = JiraConnector.__new__(JiraConnector)
        connector._connection_id = 1
        connector._base_url = "https://example.atlassian.net"
        connector._sprint_field_id = None
        connector._story_points_field_id = None
        # FDD-OPS-016 — effort fallback discovery state
        connector._tshirt_field_ids = []
        connector._effort_source_counts = {}
        connector._last_changelogs = {}

        mapped = connector._map_issue(jira_api_response)

        # The mapped dict MUST carry the changelog so the inline extractor
        # downstream can find it. Removing this key (or renaming it without
        # updating extract_status_transitions_inline) silently breaks
        # every status-transition metric.
        assert "changelog" in mapped, (
            "_map_issue dropped the `changelog` key — extract_status_"
            "transitions_inline() in the sync worker will return [] for "
            "every issue. This is the 2026-04-27 production bug."
        )

        transitions = extract_status_transitions_inline(mapped)
        assert len(transitions) == 2
        assert transitions[0]["to_status"] == "In Progress"
        assert transitions[1]["to_status"] == "Done"
