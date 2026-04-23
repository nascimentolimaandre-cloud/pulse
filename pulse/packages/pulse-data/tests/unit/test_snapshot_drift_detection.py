"""Unit tests for snapshot schema drift detection (FDD-OPS-001 L3).

Exercises `_detect_schema_drift` directly — no DB, no Kafka, no
workers. Asserts that:

  - complete payloads don't trip the drift signal
  - missing fields are surfaced via logs AND mutate the payload with
    the `_schema_drift` annotation
  - unknown (metric_type, metric_name) pairs short-circuit without
    touching the payload
  - non-dict payloads are ignored safely
  - the function never raises (drift detection is advisory, not a hard
    error path)
"""
from __future__ import annotations

import logging

import pytest

from src.contexts.metrics.infrastructure.snapshot_writer import _detect_schema_drift


# ---------------------------------------------------------------------------
# Positive case: complete payloads pass without annotation
# ---------------------------------------------------------------------------


def _complete_dora_payload() -> dict:
    """A DoraMetrics `asdict(...)` snapshot with every current field.

    Built dynamically from the dataclass so adding a new field on the
    domain side doesn't silently skew these tests. If this breaks you
    likely need to update _detect_schema_drift-aware callsites too.
    """
    import dataclasses

    from src.contexts.metrics.domain.dora import DoraMetrics

    return {f.name: None for f in dataclasses.fields(DoraMetrics)}


def test_complete_dora_payload_no_drift(caplog: pytest.LogCaptureFixture) -> None:
    payload = _complete_dora_payload()
    with caplog.at_level(logging.WARNING):
        missing = _detect_schema_drift("dora", "all", payload)
    assert missing == []
    assert "_schema_drift" not in payload
    # No warning should have been emitted.
    drift_records = [r for r in caplog.records if r.message == "snapshot_schema_drift"]
    assert drift_records == []


# ---------------------------------------------------------------------------
# Negative case: drift detected
# ---------------------------------------------------------------------------


def test_missing_field_triggers_annotation(caplog: pytest.LogCaptureFixture) -> None:
    # Drop two fields that are present on the current DoraMetrics
    # dataclass — simulates a worker running older bytecode that
    # doesn't know about `overall_level` or `mttr_level` yet.
    payload = _complete_dora_payload()
    del payload["overall_level"]
    del payload["mttr_level"]

    with caplog.at_level(logging.WARNING):
        missing = _detect_schema_drift("dora", "all", payload)

    assert set(missing) == {"overall_level", "mttr_level"}
    assert "_schema_drift" in payload
    assert set(payload["_schema_drift"]["missing_fields"]) == {
        "overall_level",
        "mttr_level",
    }
    assert "detected_at" in payload["_schema_drift"]
    # Structured warning was emitted with the right tag.
    drift_records = [r for r in caplog.records if r.message == "snapshot_schema_drift"]
    assert len(drift_records) == 1
    rec = drift_records[0]
    assert getattr(rec, "tag", None) == "FDD-OPS-001/L3"
    assert getattr(rec, "metric_type", None) == "dora"


def test_missing_field_returns_sorted_list() -> None:
    payload = _complete_dora_payload()
    del payload["deployment_frequency_per_day"]
    del payload["change_failure_rate"]
    missing = _detect_schema_drift("dora", "all", payload)
    assert missing == sorted(missing)


# ---------------------------------------------------------------------------
# Unknown metric types / non-dict payloads pass through untouched
# ---------------------------------------------------------------------------


def test_unknown_metric_is_not_validated() -> None:
    payload = {"anything": 1}
    missing = _detect_schema_drift("ghost", "metric", payload)
    assert missing == []
    assert "_schema_drift" not in payload


def test_wrapper_payload_not_validated() -> None:
    # ("cycle_time", "trend") writes {"points": [...]} — intentionally
    # not registered. Should not trip drift even though "points" is all
    # it has.
    payload = {"points": []}
    missing = _detect_schema_drift("cycle_time", "trend", payload)
    assert missing == []
    assert "_schema_drift" not in payload


def test_non_dict_payload_is_ignored() -> None:
    # Defensive: if someone calls write_snapshot with a list (shouldn't
    # happen but Pydantic v2 lax mode could let it through), we don't
    # crash.
    missing = _detect_schema_drift("dora", "all", [1, 2, 3])  # type: ignore[arg-type]
    assert missing == []


def test_existing_drift_annotation_is_ignored_when_rechecking() -> None:
    # If for whatever reason the payload ALREADY carries a
    # `_schema_drift` key (e.g. a retry/requeue path re-wrote a
    # previously-annotated dict), we should not count that annotation
    # itself against the schema.
    payload = _complete_dora_payload()
    payload["_schema_drift"] = {"missing_fields": [], "detected_at": "2026-04-23T00:00:00Z"}
    missing = _detect_schema_drift("dora", "all", payload)
    assert missing == []


# ---------------------------------------------------------------------------
# Cross-schema smoke tests
# ---------------------------------------------------------------------------


def test_cycle_time_breakdown_missing_phase() -> None:
    # Older code that didn't have the "deploy_*" phase yet.
    payload = {
        "coding_p50": 1.0, "coding_p85": 2.0, "coding_p95": 3.0,
        "pickup_p50": 1.0, "pickup_p85": 2.0, "pickup_p95": 3.0,
        "review_p50": 1.0, "review_p85": 2.0, "review_p95": 3.0,
        # deploy_* intentionally missing
        "total_p50": 1.0, "total_p85": 2.0, "total_p95": 3.0,
        "bottleneck_phase": "coding",
        "pr_count": 10,
    }
    missing = _detect_schema_drift("cycle_time", "breakdown", payload)
    assert set(missing) >= {"deploy_p50", "deploy_p85", "deploy_p95"}
    assert "_schema_drift" in payload
