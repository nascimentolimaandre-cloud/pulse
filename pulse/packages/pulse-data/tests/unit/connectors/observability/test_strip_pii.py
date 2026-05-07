"""FDD-OBS-001 PR 1 — ADR-025 Layer 1 anti-surveillance.

Validates that `strip_pii` removes the forbidden keys from every
position in a vendor JSON record, recursively, without mutating the
input.
"""

from __future__ import annotations

import pytest

from src.connectors.observability._anti_surveillance import (
    FORBIDDEN_FIELD_NAMES,
    strip_pii,
)


class TestForbiddenFieldsList:
    def test_canonical_pii_keys_present(self):
        """The set is the contract — must include the headline cases."""
        assert "user.email" in FORBIDDEN_FIELD_NAMES
        assert "deployment.author" in FORBIDDEN_FIELD_NAMES
        assert "alert.assignee" in FORBIDDEN_FIELD_NAMES
        assert "incident.assignee" in FORBIDDEN_FIELD_NAMES
        assert "trace.user_id" in FORBIDDEN_FIELD_NAMES
        assert "rum.user_id" in FORBIDDEN_FIELD_NAMES


class TestTopLevelStrip:
    def test_strips_user_email(self):
        result = strip_pii({"name": "checkout", "user.email": "alice@webmotors.com"})
        assert "user.email" not in result
        assert result["name"] == "checkout"

    def test_strips_deployment_author(self):
        result = strip_pii({"version": "1.0", "deployment.author": "marina"})
        assert "deployment.author" not in result

    def test_does_not_strip_safe_keys(self):
        result = strip_pii({"service": "checkout", "version": "1.0"})
        assert result == {"service": "checkout", "version": "1.0"}

    def test_case_insensitive(self):
        """`User.Email` (mixed case) is also blocked."""
        result = strip_pii({"User.Email": "alice@x.com"})
        assert "User.Email" not in result


class TestNestedStrip:
    def test_strips_inside_nested_dict(self):
        record = {"event": {"actor": {"user.email": "alice@x.com"}, "type": "deploy"}}
        result = strip_pii(record)
        assert result["event"]["type"] == "deploy"
        assert "user.email" not in result["event"]["actor"]

    def test_strips_inside_list(self):
        record = {"alerts": [{"id": 1, "alert.assignee": "bob"}, {"id": 2}]}
        result = strip_pii(record)
        assert "alert.assignee" not in result["alerts"][0]
        assert result["alerts"][0]["id"] == 1
        assert result["alerts"][1]["id"] == 2

    def test_strips_in_tuple(self):
        record = {"data": ({"user.id": "u1"}, {"version": "1"})}
        result = strip_pii(record)
        assert "user.id" not in result["data"][0]
        assert result["data"][1]["version"] == "1"


class TestNonMutating:
    def test_input_not_mutated(self):
        original = {"name": "x", "user.email": "alice@x.com"}
        original_copy = dict(original)
        strip_pii(original)
        assert original == original_copy, "strip_pii mutated the input"

    def test_nested_input_not_mutated(self):
        original = {"deep": {"user.email": "alice@x.com", "ok": 1}}
        strip_pii(original)
        assert "user.email" in original["deep"], "strip_pii mutated nested dict"


class TestEdgeCases:
    def test_empty_dict_returns_empty(self):
        assert strip_pii({}) == {}

    def test_non_dict_passthrough(self):
        assert strip_pii("hello") == "hello"
        assert strip_pii(42) == 42
        assert strip_pii(None) is None

    def test_non_string_keys_preserved(self):
        """Defensive — int keys can't match any forbidden name and pass through."""
        result = strip_pii({1: "a", 2: {"user.email": "x"}})
        assert result[1] == "a"
        assert "user.email" not in result[2]


class TestAllForbiddenStripped:
    @pytest.mark.parametrize("forbidden_key", sorted(FORBIDDEN_FIELD_NAMES))
    def test_each_forbidden_key_is_stripped(self, forbidden_key):
        """Every entry in FORBIDDEN_FIELD_NAMES must actually be stripped."""
        result = strip_pii({forbidden_key: "any-value", "safe": "kept"})
        assert forbidden_key not in result
        assert result["safe"] == "kept"


class TestNestedParentChildStrip:
    """CISO M-001 fix — nested PII like {"usr": {"email": ...}} that
    bypasses the flat key check must be caught by the parent/child rule."""

    def test_usr_email_subtree_dropped(self):
        """Datadog APM common pattern — usr nested with email."""
        record = {
            "service": "checkout",
            "usr": {"email": "alice@webmotors.com", "id": "u-1"},
        }
        result = strip_pii(record)
        assert "usr" not in result, "usr subtree should be dropped"
        assert result["service"] == "checkout"

    def test_usr_id_subtree_dropped(self):
        record = {"trace_id": "abc", "usr": {"id": "u-42"}}
        result = strip_pii(record)
        assert "usr" not in result
        assert result["trace_id"] == "abc"

    def test_user_email_nested_dropped(self):
        """`{"user": {"email": ...}}` — `user` IS in FORBIDDEN_FIELD_NAMES
        so it's dropped by the flat check; this test confirms the result
        regardless of which path drops it."""
        result = strip_pii({"user": {"email": "x@y.com"}})
        assert "user" not in result

    def test_trace_user_id_nested_dropped(self):
        """{"trace": {"user_id": ...}} — pair (trace, user_id) is forbidden."""
        record = {"span_id": "s1", "trace": {"user_id": "u-7"}}
        result = strip_pii(record)
        assert "trace" not in result
        assert result["span_id"] == "s1"

    def test_unrelated_nested_dict_preserved(self):
        """Don't over-strip: {"usr": {"role": "admin"}} has no forbidden child."""
        record = {"usr": {"role": "admin"}}
        result = strip_pii(record)
        # "role" is not in any forbidden pair with "usr", so subtree stays.
        # However "usr" by itself isn't in FORBIDDEN_FIELD_NAMES, so it's kept.
        assert "usr" in result
        assert result["usr"]["role"] == "admin"

    def test_deeply_nested_pii_caught_recursively(self):
        """{"event": {"actor": {"usr": {"email": ...}}}} — recursive descent
        eventually evaluates the parent/child rule at the right level."""
        record = {
            "event": {
                "actor": {
                    "usr": {"email": "alice@webmotors.com"},
                    "role": "admin",
                },
                "type": "deploy",
            }
        }
        result = strip_pii(record)
        assert "usr" not in result["event"]["actor"]
        assert result["event"]["actor"]["role"] == "admin"
        assert result["event"]["type"] == "deploy"

    def test_case_insensitive_parent_child_match(self):
        """{"USR": {"Email": ...}} — pairs match case-insensitively."""
        record = {"USR": {"Email": "alice@x.com"}}
        result = strip_pii(record)
        assert "USR" not in result and "usr" not in result
