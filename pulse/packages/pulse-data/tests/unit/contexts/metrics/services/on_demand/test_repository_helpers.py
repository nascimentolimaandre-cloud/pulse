"""INC-015 — pure-Python helpers + repository statics.

These are the cheap unit tests:
- `MetricsRepository.extract_project_key` (static, pure regex) covered here.
- The async fetcher methods that hit the DB are exercised by the integration
  tests in `tests/integration/contexts/metrics/test_routes_squad_filter.py`
  (live Postgres) — mocking ORM queries one statement at a time would
  duplicate SQLAlchemy's own test surface for no real coverage gain.
- Service composition (compute_dora_on_demand etc.) is tested with a
  mocked repository in adjacent files — see `test_dora_on_demand.py`.
"""

from __future__ import annotations

from src.contexts.metrics.repositories import MetricsRepository


class TestExtractProjectKey:
    def test_uppercase_match(self) -> None:
        assert MetricsRepository.extract_project_key("OKM-1234: fix login") == "OKM"

    def test_lowercase_normalized(self) -> None:
        assert MetricsRepository.extract_project_key("okm-99 hot patch") == "OKM"

    def test_alphanumeric_key(self) -> None:
        # Keys can have digits after the first letter (e.g. "B2B-123")
        assert MetricsRepository.extract_project_key("B2B-7 quick win") == "B2B"

    def test_no_digit_means_no_match(self) -> None:
        # The squad key MUST be followed by a hyphen + digits — bare prefix
        # like "RELEASE: 2025.04" doesn't match.
        assert MetricsRepository.extract_project_key("RELEASE: 2025.04") is None

    def test_empty_or_none_returns_none(self) -> None:
        assert MetricsRepository.extract_project_key(None) is None
        assert MetricsRepository.extract_project_key("") is None
        assert MetricsRepository.extract_project_key("   ") is None

    def test_first_match_wins(self) -> None:
        # Multiple project refs in title — first wins.
        assert MetricsRepository.extract_project_key("OKM-12 also touches PUSO-5") == "OKM"

    def test_match_inside_sentence(self) -> None:
        # Word boundary anchors — must follow a non-word char.
        assert MetricsRepository.extract_project_key("Fix bug for OKM-1234 today") == "OKM"

    def test_glued_text_known_limitation(self) -> None:
        # Documented limitation: `\b` matches case transitions, so `doOKM-12`
        # extracts "DOOKM" rather than "OKM". This mirrors the regex used by
        # /pipeline/teams (intentional consistency); titles in practice always
        # start the squad key at a word boundary so this corner case is
        # rare and harmless.
        assert MetricsRepository.extract_project_key("doOKM-12") == "DOOKM"
