"""Unit tests for the snapshot schema registry (FDD-OPS-001 L3).

Validates that every registered (metric_type, metric_name) pair
resolves to a concrete dataclass and exposes a non-empty field set.
Guards against:
  - typos in the registry map
  - dataclass renames / deletions breaking the contract silently
  - accidental registration of non-dataclass types
"""
from __future__ import annotations

import dataclasses

import pytest

from src.contexts.metrics.domain.cycle_time import CycleTimeBreakdown
from src.contexts.metrics.domain.dora import DoraMetrics
from src.contexts.metrics.domain.lean import LeadTimeDistribution
from src.contexts.metrics.domain.throughput import PrAnalytics
from src.contexts.metrics.infrastructure.schema_registry import (
    expected_fields,
    registered_contracts,
)


# ---------------------------------------------------------------------------
# Individual lookups
# ---------------------------------------------------------------------------


def test_expected_fields_dora_all_nonempty() -> None:
    fields = expected_fields("dora", "all")
    assert fields is not None
    assert len(fields) > 0
    # Spot-check: presence of the headline DORA metrics.
    assert "deployment_frequency_per_day" in fields
    assert "lead_time_for_changes_hours" in fields
    assert "change_failure_rate" in fields
    assert "mean_time_to_recovery_hours" in fields


def test_expected_fields_cycle_time_breakdown_has_percentiles() -> None:
    fields = expected_fields("cycle_time", "breakdown")
    assert fields is not None
    # Each phase should have p50, p85, p95.
    for phase in ("coding", "pickup", "review", "deploy", "total"):
        for pct in ("p50", "p85", "p95"):
            assert f"{phase}_{pct}" in fields, f"missing {phase}_{pct}"


def test_expected_fields_lean_lead_time_distribution() -> None:
    fields = expected_fields("lean", "lead_time_distribution")
    assert fields is not None
    assert "buckets" in fields
    assert "p50_hours" in fields
    assert "total_issues" in fields


def test_expected_fields_throughput_pr_analytics() -> None:
    fields = expected_fields("throughput", "pr_analytics")
    assert fields is not None
    assert "total_merged" in fields
    assert "size_distribution" in fields
    assert "repos_breakdown" in fields


# ---------------------------------------------------------------------------
# Unknown types return None (do not validate)
# ---------------------------------------------------------------------------


def test_expected_fields_unknown_type_returns_none() -> None:
    assert expected_fields("unknown_type", "anything") is None


def test_expected_fields_unknown_name_returns_none() -> None:
    # Known type, unknown name.
    assert expected_fields("dora", "bogus_metric") is None


def test_wrapper_payloads_are_not_registered() -> None:
    """Wrapper payloads ({'points': [...]}) intentionally not validated."""
    assert expected_fields("cycle_time", "trend") is None
    assert expected_fields("throughput", "trend") is None
    assert expected_fields("lean", "cfd") is None
    assert expected_fields("lean", "throughput") is None
    assert expected_fields("lean", "wip") is None
    assert expected_fields("lean", "scatterplot") is None


# ---------------------------------------------------------------------------
# Registry integrity — every mapped class must be a dataclass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metric_type", "metric_name", "expected_cls"),
    [
        ("dora", "all", DoraMetrics),
        ("cycle_time", "breakdown", CycleTimeBreakdown),
        ("lean", "lead_time_distribution", LeadTimeDistribution),
        ("throughput", "pr_analytics", PrAnalytics),
    ],
)
def test_registered_class_is_dataclass(
    metric_type: str, metric_name: str, expected_cls: type
) -> None:
    assert dataclasses.is_dataclass(expected_cls)
    fields_from_cls = {f.name for f in dataclasses.fields(expected_cls)}
    fields_from_registry = expected_fields(metric_type, metric_name)
    assert fields_from_registry == fields_from_cls


def test_registered_contracts_returns_sorted_pairs() -> None:
    contracts = registered_contracts()
    assert len(contracts) >= 4
    assert contracts == sorted(contracts)
    assert ("dora", "all") in contracts
