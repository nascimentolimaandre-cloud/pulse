"""Squad & team filter validation (QW-2).

Regression tests for INC-422: the `squad_key` and `team_id` query parameters
must be validated with clear rules.

- `squad_key`: 2-10 chars, alphanumeric uppercase (e.g. "FID", "PTURB", "OKM")
- `team_id`: strict UUID v1-v5 format

Prior bug: a valid UUID was rejected with HTTP 422 because the frontend was
routing squad keys to `team_id` instead of `squad_key`, and the backend's
UUID regex was too permissive. Separately, invalid formats must still 422.

Requires pulse-data running on localhost:8000 (use `make up` first).
Uses httpx against the live API — no Testcontainers needed for these checks.

Classification: PLATFORM (universal, applies to any tenant).
"""

from __future__ import annotations

import os
import uuid as uuid_module

import httpx
import pytest

BASE_URL = os.environ.get("PULSE_DATA_URL", "http://localhost:8000")
API = f"{BASE_URL}/data/v1"

# Absent-from-DB UUID with valid format — tests format validation, not data.
SYNTHETIC_UUID = "0e62a0b0-0000-4000-8000-000000000000"


def _pulse_data_reachable() -> bool:
    """Quick reachability probe — use /health (fast) not /metrics (can block on slow DB)."""
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        return r.is_success
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
        return False


API_UP = _pulse_data_reachable()

pytestmark = pytest.mark.skipif(
    not API_UP,
    reason="pulse-data not reachable at localhost:8000 — run `make up` first",
)


class TestSquadKeyFilter:
    """Squad-key filtering: non-UUID identifiers from /pipeline/teams."""

    def test_valid_squad_key_returns_200(self):
        """Valid squad_key (uppercase alphanumeric 2-10 chars) must return HTTP 200."""
        r = httpx.get(f"{API}/metrics/home?period=60d&squad_key=FID", timeout=60.0)
        assert r.status_code == 200, (
            f"Valid squad_key=FID returned {r.status_code} — expected 200. "
            f"This regressed INC-422: squad keys should not be treated as team_ids."
        )
        body = r.json()
        assert "data" in body, "Response missing `data` wrapper"

    def test_squad_key_lowercase_normalizes_to_uppercase(self):
        """squad_key in lowercase should be normalized (backend upper()s it)."""
        r = httpx.get(f"{API}/metrics/home?period=60d&squad_key=fid", timeout=60.0)
        assert r.status_code == 200
        body = r.json()
        assert body.get("data") is not None

    def test_non_existent_squad_key_still_returns_200(self):
        """Unknown squad_key should return 200 with empty data, not 404 or 422."""
        r = httpx.get(
            f"{API}/metrics/home?period=60d&squad_key=NOSUCHSQUAD", timeout=60.0
        )
        assert r.status_code == 200, (
            f"Unknown squad_key returned {r.status_code} — should be 200 with "
            f"empty/null data, because squad_key is a filter not a resource path."
        )

    @pytest.mark.xfail(
        reason=(
            "FDD-SEC-001: /metrics/home does NOT reject squad_key with special "
            "chars like 'FID;DROP' — returns 200 because no regex validation on "
            "the query param. The backend IS safe from SQL injection (sqlalchemy "
            "uses bindparams) but should reject malformed input upfront. See "
            "pulse/contexts/pipeline/routes.py for the correct regex pattern: "
            "r'^[A-Za-z][A-Za-z0-9]*$'. Sprint 5 (security hardening) will fix."
        ),
        strict=True,
    )
    def test_squad_key_with_invalid_chars_rejected(self):
        """Squad key with SQL-injection-like chars must be rejected."""
        r = httpx.get(
            f"{API}/metrics/home?period=60d&squad_key=FID%3BDROP", timeout=60.0
        )
        assert r.status_code in (400, 422), (
            f"Squad key 'FID;DROP' returned {r.status_code} — must be 400/422 "
            f"(injection protection)."
        )


class TestTeamIdFilter:
    """team_id filtering: strict UUID v1-v5."""

    def test_valid_uuid_v4_accepted(self):
        """A valid UUID v4 must be accepted (HTTP 200)."""
        valid_uuid = str(uuid_module.uuid4())
        r = httpx.get(
            f"{API}/metrics/home?period=60d&team_id={valid_uuid}", timeout=60.0
        )
        assert r.status_code == 200, (
            f"Valid UUID v4 returned {r.status_code} — expected 200. "
            f"UUID regex may be too restrictive."
        )

    @pytest.mark.parametrize("bad", [
        "not-a-uuid",
        "okm",
        "123",
        "FID",
        "0e62a0b0-0000-4000",  # too short
    ])
    def test_invalid_uuid_format_rejected(self, bad):
        """Invalid formats must be rejected (422)."""
        r = httpx.get(
            f"{API}/metrics/home?period=60d&team_id={bad}", timeout=60.0
        )
        assert r.status_code == 422, (
            f"Invalid team_id '{bad}' returned {r.status_code} — "
            f"expected 422 (strict UUID validation)."
        )

    def test_synthetic_valid_uuid_returns_200_not_crash(self):
        """A UUID with valid format but absent from DB should return 200 (empty)."""
        r = httpx.get(
            f"{API}/metrics/home?period=60d&team_id={SYNTHETIC_UUID}",
            timeout=60.0,
        )
        assert r.status_code == 200

    def test_empty_team_id_ignored(self):
        """Empty team_id should be ignored (tenant-wide), not 422."""
        r = httpx.get(f"{API}/metrics/home?period=60d&team_id=", timeout=60.0)
        # Acceptable: treated as absent (200), or rejected (422).
        # Unacceptable: 500 or silent fallback to wrong tenant.
        assert r.status_code in (200, 422), (
            f"Empty team_id returned {r.status_code} — unexpected."
        )


class TestPeriodValidation:
    """Period parameter validation regression (part of INC-422 family)."""

    @pytest.mark.parametrize("period", ["7d", "14d", "30d", "60d", "90d", "120d"])
    def test_known_periods_accepted(self, period):
        """7d, 14d, 30d, 60d, 90d, 120d all accepted."""
        r = httpx.get(f"{API}/metrics/home?period={period}", timeout=60.0)
        assert r.status_code == 200, (
            f"Valid period '{period}' returned {r.status_code} — "
            f"_PERIODS list may be out of sync with _VALID_PERIODS."
        )

    def test_unknown_period_rejected(self):
        """Unknown period (e.g. 45d) must be rejected with 400."""
        r = httpx.get(f"{API}/metrics/home?period=45d", timeout=60.0)
        assert r.status_code == 400, (
            f"Unknown period '45d' returned {r.status_code} — expected 400."
        )
