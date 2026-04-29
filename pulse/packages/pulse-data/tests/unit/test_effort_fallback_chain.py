"""Regression tests for FDD-OPS-016 — effort estimation fallback chain.

Webmotors and many enterprise tenants don't use Story Points. Different
squads use T-shirt sizes (P/M/G…), original estimate hours, or simply
don't estimate. The connector's `_extract_story_points` walks a priority
chain so downstream metrics get a usable number when one exists, and
None when the issue is genuinely unestimated.

These tests exercise the chain end-to-end against Jira-shaped payloads.
If a future refactor reorders the chain or drops a fallback, multiple
tests fail with messages naming the broken hop.
"""

from __future__ import annotations

import pytest

from src.connectors.jira_connector import (
    TSHIRT_TO_POINTS,
    JiraConnector,
    _hours_to_points,
)


@pytest.fixture
def connector() -> JiraConnector:
    """A connector instance with effort discovery already populated.

    We bypass __init__ so tests don't hit env vars / the network.
    """
    c = JiraConnector.__new__(JiraConnector)
    c._connection_id = 1
    c._base_url = "https://example.atlassian.net"
    c._sprint_field_id = None
    c._story_points_field_id = "customfield_10004"
    c._tshirt_field_ids = ["customfield_18762", "customfield_15100"]
    c._custom_fields_discovered = True
    c._effort_source_counts = {}
    return c


# ---------------------------------------------------------------------------
# 1. Native Story Points — highest priority
# ---------------------------------------------------------------------------

class TestStoryPointsTakesPriority:
    def test_uses_discovered_story_points_field_when_set(self, connector):
        result = connector._extract_story_points({"customfield_10004": 5})
        assert result == 5.0
        assert connector._effort_source_counts == {"story_points": 1}

    def test_skips_zero_story_points_and_falls_through(self, connector):
        """0 SP is a common sentinel for "not yet estimated" — skip it."""
        result = connector._extract_story_points({
            "customfield_10004": 0,
            "customfield_18762": {"value": "P"},
        })
        assert result == TSHIRT_TO_POINTS["P"]
        assert connector._effort_source_counts == {"tshirt_to_sp": 1}

    def test_native_sp_wins_over_tshirt(self, connector):
        result = connector._extract_story_points({
            "customfield_10004": 8,
            "customfield_18762": {"value": "P"},  # would map to 2
            "timeoriginalestimate": 14400,        # would map via hours
        })
        assert result == 8.0


# ---------------------------------------------------------------------------
# 2. T-shirt sizing — second priority
# ---------------------------------------------------------------------------

class TestTshirtSizing:
    @pytest.mark.parametrize(
        "size,expected",
        [("PP", 1.0), ("P", 2.0), ("M", 3.0), ("G", 5.0), ("GG", 8.0), ("GGG", 13.0)],
    )
    def test_portuguese_sizes_map_correctly(self, connector, size, expected):
        result = connector._extract_story_points({
            "customfield_18762": {"value": size},
        })
        assert result == expected

    @pytest.mark.parametrize(
        "size,expected",
        [("XS", 1.0), ("S", 2.0), ("M", 3.0), ("L", 5.0), ("XL", 8.0), ("XXL", 13.0)],
    )
    def test_english_sizes_map_correctly(self, connector, size, expected):
        result = connector._extract_story_points({
            "customfield_18762": {"value": size},
        })
        assert result == expected

    def test_lowercase_size_is_normalized(self, connector):
        """Be lenient: Jira sometimes returns 'p' instead of 'P'."""
        result = connector._extract_story_points({
            "customfield_18762": {"value": "p"},
        })
        assert result == TSHIRT_TO_POINTS["P"]

    def test_unknown_size_falls_through_to_hours(self, connector):
        result = connector._extract_story_points({
            "customfield_18762": {"value": "JUMBO"},
            "timeoriginalestimate": 28800,  # 8h → 2 SP
        })
        assert result == 2.0
        assert connector._effort_source_counts == {"hours_to_sp": 1}

    def test_secondary_tshirt_field_used_when_first_empty(self, connector):
        """Tamanho/Impacto picks up where T-Shirt Size is empty."""
        result = connector._extract_story_points({
            "customfield_18762": None,
            "customfield_15100": {"value": "G"},
        })
        assert result == TSHIRT_TO_POINTS["G"]

    def test_bare_string_option_value(self, connector):
        """Some legacy responses give a string directly, not a dict."""
        result = connector._extract_story_points({
            "customfield_18762": "M",
        })
        assert result == TSHIRT_TO_POINTS["M"]


# ---------------------------------------------------------------------------
# 3. Original Estimate (hours) — third priority
# ---------------------------------------------------------------------------

class TestOriginalEstimateHours:
    @pytest.mark.parametrize(
        "seconds,expected_hours,expected_sp",
        [
            (3600,    1.0,  1.0),   # ≤4h
            (14400,   4.0,  1.0),   # exactly 4h
            (28800,   8.0,  2.0),   # ≤8h (1 day)
            (57600,  16.0,  3.0),   # ≤16h (2 days)
            (86400,  24.0,  5.0),   # ≤24h
            (115200, 32.0,  8.0),   # ≤40h
            (288000, 80.0, 13.0),   # ≤80h (2 weeks)
            (446400, 124.0, 21.0),  # >80h — observed Webmotors max
        ],
    )
    def test_seconds_to_sp_buckets(
        self, connector, seconds, expected_hours, expected_sp,
    ):
        # Direct check of the helper for clarity
        assert _hours_to_points(expected_hours) == expected_sp
        # End-to-end: connector picks up timeoriginalestimate
        result = connector._extract_story_points({
            "timeoriginalestimate": seconds,
        })
        assert result == expected_sp
        assert connector._effort_source_counts == {"hours_to_sp": 1}

    def test_zero_seconds_falls_through_to_unestimated(self, connector):
        result = connector._extract_story_points({"timeoriginalestimate": 0})
        assert result is None
        assert connector._effort_source_counts == {"unestimated": 1}


# ---------------------------------------------------------------------------
# 4. Unestimated — final fallback
# ---------------------------------------------------------------------------

class TestUnestimatedReturnsNone:
    def test_no_fields_returns_none(self, connector):
        """Kanban-pure mode: metric layer must count items, not sum SP."""
        result = connector._extract_story_points({})
        assert result is None
        assert connector._effort_source_counts == {"unestimated": 1}

    def test_empty_strings_treated_as_missing(self, connector):
        result = connector._extract_story_points({
            "customfield_10004": "",
            "customfield_18762": {"value": ""},
            "customfield_15100": None,
        })
        assert result is None

    def test_telemetry_aggregates_across_calls(self, connector):
        """Operators rely on the breakdown log to spot estimation shifts."""
        connector._extract_story_points({"customfield_10004": 5})
        connector._extract_story_points({"customfield_18762": {"value": "M"}})
        connector._extract_story_points({"timeoriginalestimate": 14400})
        connector._extract_story_points({})
        connector._extract_story_points({})
        assert connector._effort_source_counts == {
            "story_points": 1,
            "tshirt_to_sp": 1,
            "hours_to_sp": 1,
            "unestimated": 2,
        }


# ---------------------------------------------------------------------------
# 5. Webmotors-shaped real-world cases
# ---------------------------------------------------------------------------

class TestWebmotorsShapeIntegration:
    """Sanity check against the field combos actually observed in production."""

    def test_eno_typical_issue(self, connector):
        """ENO sample: T-shirt 'P' + 8h original estimate. T-shirt wins."""
        result = connector._extract_story_points({
            "customfield_18762": {"value": "P"},
            "timeoriginalestimate": 28800,
        })
        assert result == 2.0  # P → 2

    def test_desc_typical_issue(self, connector):
        """DESC sample: T-shirt 'G' only."""
        result = connector._extract_story_points({
            "customfield_18762": {"value": "G"},
        })
        assert result == 5.0

    def test_bg_typical_issue(self, connector):
        """BG (Kanban-pure): nothing populated — None forces item count."""
        result = connector._extract_story_points({
            "summary": "do the thing",
            "status": {"name": "Done"},
        })
        assert result is None
