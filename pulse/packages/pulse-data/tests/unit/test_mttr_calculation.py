"""FDD-DSH-050 — unit tests for `calculate_mttr` MTTR computation logic.

Pure tests over `calculate_mttr` and `calculate_dora_metrics` — covers:
  - Median computation (DORA canonical)
  - 5-minute flaky-test filter (_MTTR_MIN_RECOVERY_HOURS)
  - 5-incident minimum sample size (_MTTR_MIN_SAMPLE) → returns None
  - Open incident counting (no recovery_time_hours)
  - Resolved incident counting (passes flaky filter)
  - Anti-surveillance: no author/assignee fields touched

Edge cases NOT in this test file (live DB needed):
  - SQL pairing logic (failure→success on (repo, env)) — see test_mttr_pairing_service.py (integration)
  - Back-to-back failure grouping ('superseded' status) — same
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.contexts.metrics.domain.dora import (
    _MTTR_MIN_RECOVERY_HOURS,
    _MTTR_MIN_SAMPLE,
    DeploymentData,
    calculate_mttr,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _failed(recovery_hours: float | None) -> DeploymentData:
    """Build a failed-deploy fixture with given recovery time."""
    return DeploymentData(
        deployed_at=datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc),
        is_failure=True,
        recovery_time_hours=recovery_hours,
    )


def _success() -> DeploymentData:
    """Build a successful deploy fixture (not used by MTTR)."""
    return DeploymentData(
        deployed_at=datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc),
        is_failure=False,
        recovery_time_hours=None,
    )


# ---------------------------------------------------------------------------
# Median computation — DORA canonical
# ---------------------------------------------------------------------------

class TestMedianComputation:
    def test_median_of_resolved_failures(self):
        """5 incidents with recovery times → median computed correctly."""
        deploys = [_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0)]
        # median of [1, 2, 3, 4, 5] = 3
        assert calculate_mttr(deploys) == 3.0

    def test_median_handles_even_count(self):
        """Even count: median is mean of the two middle values."""
        deploys = [_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)]
        # median of [1, 2, 3, 4, 5, 6] = (3+4)/2 = 3.5
        assert calculate_mttr(deploys) == 3.5

    def test_median_robust_to_outlier(self):
        """One huge outlier doesn't drag the median (DORA chose median for this reason)."""
        deploys = [_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 999.0)]
        # median = 3, mean would have been 201.8
        assert calculate_mttr(deploys) == 3.0


# ---------------------------------------------------------------------------
# Sample size guard
# ---------------------------------------------------------------------------

class TestSampleSizeGuard:
    def test_returns_none_below_minimum_sample(self):
        """Below _MTTR_MIN_SAMPLE resolved incidents, return None."""
        # 4 resolved is one below the threshold (5)
        deploys = [_failed(h) for h in (1.0, 2.0, 3.0, 4.0)]
        assert len(deploys) == _MTTR_MIN_SAMPLE - 1
        assert calculate_mttr(deploys) is None

    def test_returns_none_with_zero_resolved(self):
        """Empty / no failed deploys → None."""
        assert calculate_mttr([]) is None

    def test_returns_value_at_minimum_sample(self):
        """Exactly _MTTR_MIN_SAMPLE resolved incidents → median computed."""
        deploys = [_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0)]
        assert len(deploys) == _MTTR_MIN_SAMPLE
        assert calculate_mttr(deploys) is not None


# ---------------------------------------------------------------------------
# Flaky-test filter (5 minute minimum)
# ---------------------------------------------------------------------------

class TestFlakyTestFilter:
    def test_discards_recoveries_below_5_minutes(self):
        """recovery_time_hours < 5/60h is treated as flaky test re-trigger."""
        # 5 valid + 3 flaky → only 5 contribute
        deploys = [
            *[_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0)],
            *[_failed(h) for h in (0.01, 0.02, 0.05)],  # all < 5 min
        ]
        # median should be over [1,2,3,4,5] only = 3.0
        assert calculate_mttr(deploys) == 3.0

    def test_keeps_recovery_at_exact_threshold(self):
        """Recovery exactly at 5 minutes is kept (>=, not >)."""
        five_min = _MTTR_MIN_RECOVERY_HOURS  # 5/60 = 0.0833...
        deploys = [_failed(h) for h in (five_min, 1.0, 2.0, 3.0, 4.0)]
        # All 5 contribute → median of [0.083, 1, 2, 3, 4] = 2.0
        assert calculate_mttr(deploys) == 2.0

    def test_all_flaky_returns_none(self):
        """If every recovery is below threshold, no real incidents → None."""
        deploys = [_failed(0.01) for _ in range(10)]  # all 36s recoveries
        assert calculate_mttr(deploys) is None

    def test_min_recovery_threshold_is_five_minutes(self):
        """Constant value sanity check (DORA-aligned, 5 min = 1/12 hour)."""
        assert _MTTR_MIN_RECOVERY_HOURS == pytest.approx(5.0 / 60.0)


# ---------------------------------------------------------------------------
# Open-incident handling (recovery_time_hours is None)
# ---------------------------------------------------------------------------

class TestOpenIncidents:
    def test_open_incidents_excluded_from_median(self):
        """Failures with recovery_time_hours=None (open or superseded)
        do NOT contribute to the MTTR median."""
        # 5 resolved + 3 open. Open should be ignored entirely.
        deploys = [
            *[_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0)],
            *[_failed(None) for _ in range(3)],
        ]
        # median over [1,2,3,4,5] = 3.0
        assert calculate_mttr(deploys) == 3.0

    def test_only_open_incidents_returns_none(self):
        """All failures unresolved → no median to compute."""
        deploys = [_failed(None) for _ in range(10)]
        assert calculate_mttr(deploys) is None


# ---------------------------------------------------------------------------
# calculate_dora_metrics integration — counts populated correctly
# ---------------------------------------------------------------------------

class TestBuildDoraMetricsCounts:
    @staticmethod
    def _build_args(failed_deploys: list[DeploymentData]):
        """Minimal kwargs for calculate_dora_metrics."""
        from src.contexts.metrics.domain.dora import calculate_dora_metrics

        # We don't care about DF/LT/CFR here — pass empty lists where allowed
        return calculate_dora_metrics(
            deployments=failed_deploys,
            pull_requests=[],
            start_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )

    def test_counts_resolved_incidents(self):
        """`mttr_incident_count` reflects resolved (passes flaky filter) failures."""
        deploys = [_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)]
        m = self._build_args(deploys)
        assert m.mttr_incident_count == 6
        assert m.mttr_open_incident_count == 0

    def test_counts_open_incidents(self):
        """`mttr_open_incident_count` reflects None-recovery_time failures."""
        deploys = [
            *[_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0)],
            *[_failed(None) for _ in range(3)],
        ]
        m = self._build_args(deploys)
        assert m.mttr_incident_count == 5
        assert m.mttr_open_incident_count == 3

    def test_flaky_failures_not_counted_as_resolved(self):
        """Failures with recovery < 5 min don't increment mttr_incident_count."""
        deploys = [
            *[_failed(h) for h in (1.0, 2.0, 3.0, 4.0, 5.0)],
            *[_failed(0.01) for _ in range(3)],  # flaky
        ]
        m = self._build_args(deploys)
        # 5 real + 0 flaky counted (filtered) = 5
        assert m.mttr_incident_count == 5
        # And flaky aren't open either (they have recovery_time_hours, just below threshold)
        assert m.mttr_open_incident_count == 0


# ---------------------------------------------------------------------------
# Anti-surveillance — DeploymentData has no person fields the calc reads
# ---------------------------------------------------------------------------

class TestAntiSurveillance:
    def test_calculate_mttr_only_reads_aggregable_fields(self):
        """Sanity check: the function only references fields safe to aggregate.

        Reading source ensures `calculate_mttr` doesn't sneak in a per-author
        path. If a future refactor adds author logic, this test fails.
        """
        from pathlib import Path
        import re

        src_path = (
            Path(__file__).resolve().parents[2]
            / "src" / "contexts" / "metrics" / "domain" / "dora.py"
        )
        source = src_path.read_text()

        # Find calculate_mttr body
        start = source.find("def calculate_mttr(")
        assert start != -1
        end = source.find("\ndef ", start + 1)
        body = source[start:end] if end != -1 else source[start:]

        # Strip docstring + comments to inspect only code references
        body_no_strings = re.sub(r'"""[\s\S]*?"""', "", body)
        body_no_comments = re.sub(r"#[^\n]*", "", body_no_strings)

        # Must NEVER reference these forbidden fields
        forbidden = ["author", "assignee", "reporter", "user", "committer"]
        for word in forbidden:
            assert word not in body_no_comments, (
                f"Anti-surveillance regression: calculate_mttr references "
                f"{word!r}. MTTR must operate only on (repo, environment, "
                f"timestamps, is_failure) tuples."
            )
