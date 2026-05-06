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
