"""Webmotors-specific throughput ground-truth values (QW-1 customer part).

These tests validate that the Webmotors tenant produces **specific** throughput
values that match what we've observed in production-like data. They protect
against regressions AND against data ingestion problems (e.g. sync worker
broken, backfill not completed).

Tolerance: ±10% to accommodate data drift during active ingestion, backfill
progress, and normal daily variation. If a test fails outside this tolerance,
something has genuinely broken.

Observed baselines (2026-04-18):
- 60d: ~5044 merged PRs
- 90d: ~7341 merged PRs
- 120d: ~9007 merged PRs

Baselines should be updated whenever Webmotors onboards new repos or
decommissions large ones. Record the date + rationale in this file's header.

Classification: CUSTOMER (Webmotors-specific values).
"""

from __future__ import annotations

import pytest

# Baselines + tolerance (inclusive range)
BASELINES = {
    60: {"expected": 5044, "tolerance_pct": 10.0},
    90: {"expected": 7341, "tolerance_pct": 10.0},
    120: {"expected": 9007, "tolerance_pct": 10.0},
}


@pytest.mark.parametrize("period_days", [60, 90, 120])
def test_webmotors_throughput_matches_baseline(psql, period_days):
    """Webmotors merged PR count for a given period is within ±10% of baseline."""
    baseline = BASELINES[period_days]
    expected = baseline["expected"]
    tol = baseline["tolerance_pct"] / 100.0

    result = psql(
        f"SELECT COUNT(*) FROM eng_pull_requests "
        f"WHERE merged_at >= NOW() - INTERVAL '{period_days} days' "
        f"AND is_merged = true;"
    )
    assert result is not None, f"Could not fetch throughput for {period_days}d"
    actual = int(result)

    lower = int(expected * (1 - tol))
    upper = int(expected * (1 + tol))
    assert lower <= actual <= upper, (
        f"Webmotors {period_days}d throughput = {actual}, expected in "
        f"[{lower}, {upper}] (baseline {expected} ±{tol*100:.0f}%). "
        f"If this is an intentional change, update BASELINES in this file "
        f"with rationale and date."
    )


def test_webmotors_throughput_monotonic_with_production_values(psql):
    """Webmotors throughput must grow with period. This is the customer
    version of the platform monotonicity test — with REAL expected magnitudes."""
    t60 = int(psql(
        "SELECT COUNT(*) FROM eng_pull_requests "
        "WHERE merged_at >= NOW() - INTERVAL '60 days' AND is_merged = true;"
    ) or 0)
    t120 = int(psql(
        "SELECT COUNT(*) FROM eng_pull_requests "
        "WHERE merged_at >= NOW() - INTERVAL '120 days' AND is_merged = true;"
    ) or 0)

    assert t120 >= t60 * 1.3, (
        f"Webmotors 120d ({t120}) should be at least 30% more than 60d ({t60}). "
        f"If they are equal, sync worker is broken."
    )
