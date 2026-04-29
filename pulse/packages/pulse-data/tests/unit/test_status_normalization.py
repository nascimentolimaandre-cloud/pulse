"""Regression tests for FDD-OPS-017 — status normalization with statusCategory
fallback.

THE BUG (2026-04-28 audit): 311k issues showed normalized_status distribution
of 96.5% done, 0.2% in_progress, 3.3% todo. Investigation revealed:

  - Webmotors Jira has 104 distinct status names across workflows
  - DEFAULT_STATUS_MAPPING covered ~50 → 50+ statuses fell to default 'todo'
  - 2,881 issues with status='FECHADO EM PROD' landed in 'todo' (should be 'done')
  - Various active work states ('Em Progresso', 'Em desenv') were classified
    as 'todo'
  - Result: every flow metric (Cycle Time, Throughput, WIP, CFD, Flow
    Efficiency) was systematically corrupted across the whole tenant

THE FIX: hybrid normalization

  1. Textual DEFAULT_STATUS_MAPPING — preserves the in_progress vs in_review
     distinction we curated for Cycle Time breakdown
  2. Jira's statusCategory.key fallback — authoritative for done/non-done,
     covers the long tail of tenant-custom workflows automatically
  3. Final default 'todo' with WARN log

If a future refactor reverts to the textual-only path, these tests fail
loudly with messages naming the broken classification.
"""

from __future__ import annotations

import pytest

from src.contexts.engineering_data.normalizer import (
    DEFAULT_STATUS_MAPPING,
    build_status_transitions,
    normalize_status,
)


# ---------------------------------------------------------------------------
# 1. Textual mapping wins (preserves curated granularity)
# ---------------------------------------------------------------------------

class TestTextualMappingTakesPriority:
    def test_known_status_uses_textual_even_when_category_disagrees(self):
        """Even if Jira's category says 'indeterminate', our explicit mapping
        of 'em code review' → 'in_review' must win. The category-only fallback
        loses the in_progress/in_review granularity that Cycle Time needs."""
        result = normalize_status(
            "Em Code Review",
            status_category="indeterminate",
        )
        assert result == "in_review"

    def test_pt_br_done_status_classified_correctly(self):
        """'Concluído' must always be done, regardless of category."""
        assert normalize_status("Concluído") == "done"
        # Even if hypothetically the category was wrong:
        assert normalize_status("Concluído", status_category="new") == "done"

    def test_custom_mapping_overrides_default(self):
        custom = {"weird-state": "in_progress"}
        assert normalize_status("weird-state", status_mapping=custom) == "in_progress"


# ---------------------------------------------------------------------------
# 2. statusCategory fallback — the actual fix
# ---------------------------------------------------------------------------

class TestStatusCategoryFallback:
    def test_unknown_status_with_done_category_returns_done(self):
        """REGRESSION: pre-fix, this returned 'todo' and corrupted Throughput
        + Cycle Time + Lead Time for every issue with a custom 'done' status."""
        result = normalize_status(
            "FECHADO EM PROD UNKNOWN VARIANT",
            status_category="done",
        )
        assert result == "done"

    def test_unknown_status_with_indeterminate_returns_in_progress(self):
        """Active work that isn't in our textual mapping defaults to
        in_progress (not in_review) — operators must add explicit mapping
        if the in_review distinction matters."""
        result = normalize_status(
            "Some New Custom State",
            status_category="indeterminate",
        )
        assert result == "in_progress"

    def test_unknown_status_with_new_category_returns_todo(self):
        result = normalize_status(
            "Aguardando Terceiro Custom",
            status_category="new",
        )
        assert result == "todo"

    def test_unknown_status_without_category_defaults_to_todo(self):
        """Legacy fallback when neither textual nor category matches."""
        result = normalize_status("Totally Unknown")
        assert result == "todo"

    def test_invalid_category_falls_through_to_default(self):
        """Defensive: garbage in `status_category` doesn't crash the pipeline."""
        result = normalize_status("Whatever", status_category="garbage")
        assert result == "todo"

    def test_category_is_case_insensitive(self):
        assert normalize_status("X", status_category="DONE") == "done"
        assert normalize_status("X", status_category="Indeterminate") == "in_progress"


# ---------------------------------------------------------------------------
# 3. Real-world Webmotors statuses that broke the original normalizer
# ---------------------------------------------------------------------------

class TestWebmotorsStatusRegression:
    """Each parametrized case is a status string that, pre-fix, caused
    visible metric corruption. They must classify correctly NOW.
    """

    @pytest.mark.parametrize("raw,expected", [
        ("FECHADO EM PROD", "done"),       # 2,881 issues affected
        ("FECHADO EM HML", "done"),        # Jira's own category is "done"
        ("Concluído", "done"),
        ("Cancelado", "done"),
        ("FECHADO", "done"),
        ("Em Desenvolvimento", "in_progress"),
        ("Em imersão", "in_progress"),
        ("Em andamento", "in_progress"),
        ("Em Progresso", "in_progress"),   # was 'todo' pre-fix
        ("Em Code Review", "in_review"),
        ("Em Teste HML", "in_review"),
        ("Homologação", "in_review"),      # was 'todo' pre-fix
        ("Em Verificação", "in_review"),   # was 'todo' pre-fix
        ("BACKLOG", "todo"),
        ("A Fazer", "todo"),
        ("Refinado", "todo"),
        ("PAUSADO", "todo"),
    ])
    def test_observed_status_classifies_correctly(self, raw, expected):
        assert normalize_status(raw) == expected, (
            f"{raw!r} should be {expected!r}, but got {normalize_status(raw)!r}"
        )


# ---------------------------------------------------------------------------
# 4. build_status_transitions integrates the category map
# ---------------------------------------------------------------------------

class TestBuildStatusTransitionsWithCategories:
    def test_unknown_to_status_uses_categories_map(self):
        """REGRESSION: a transition into a custom 'done'-category status
        must be classified as done in the resulting transitions array,
        not 'todo'. Cycle Time breakdown reads transitions to determine
        time spent in each phase."""
        changelogs = [
            {
                "from_status": "Em Desenvolvimento",
                "to_status": "Some Custom Done State",
                "created_date": "2026-04-01T10:00:00.000+0000",
            },
        ]
        cats_map = {"some custom done state": "done"}
        result = build_status_transitions(
            changelogs, status_categories_map=cats_map,
        )
        assert len(result) == 1
        assert result[0]["status"] == "done"

    def test_textual_mapping_still_wins_in_transitions(self):
        changelogs = [
            {
                "from_status": "A",
                "to_status": "Em Code Review",
                "created_date": "2026-04-01T10:00:00.000+0000",
            },
        ]
        # Even with a misleading category in the map:
        cats_map = {"em code review": "indeterminate"}
        result = build_status_transitions(
            changelogs, status_categories_map=cats_map,
        )
        assert result[0]["status"] == "in_review"

    def test_transitions_without_categories_map_still_works(self):
        """Backward compat: legacy callers don't pass status_categories_map."""
        changelogs = [
            {
                "from_status": "A",
                "to_status": "Done",
                "created_date": "2026-04-01T10:00:00.000+0000",
            },
        ]
        result = build_status_transitions(changelogs)
        assert result[0]["status"] == "done"


# ---------------------------------------------------------------------------
# 5. Anti-regression: textual mapping coverage
# ---------------------------------------------------------------------------

class TestTextualMappingCompleteness:
    """The DEFAULT_STATUS_MAPPING grew significantly during FDD-OPS-017 to
    cover Webmotors PT-BR workflows. These tests guard against accidental
    deletion.
    """

    @pytest.mark.parametrize("status", [
        "fechado em prod", "concluído", "cancelado", "fechado",
        "em desenvolvimento", "em andamento", "em progresso",
        "em code review", "em teste hml", "em verificação", "homologação",
        "backlog", "a fazer", "refinado",
    ])
    def test_critical_pt_br_status_is_mapped(self, status):
        assert status in DEFAULT_STATUS_MAPPING, (
            f"{status!r} must remain in DEFAULT_STATUS_MAPPING — "
            "removing it reverts FDD-OPS-017 and re-corrupts metrics."
        )
