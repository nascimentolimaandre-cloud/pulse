"""Unit tests for FDD-OPS-014 step 2.2 — per-scope watermark API.

Validates that:
1. `make_scope_key()` produces canonical strings
2. Default scope_key='*' preserves legacy callers (backwards-compat)
3. New explicit scope_keys are independent rows
4. `_list_watermarks_by_scope` returns None for missing scopes (full backfill)

Tests use a Postgres test container fixture (existing in conftest); the
DB-touching tests live under tests/integration/ — this file covers the
pure helpers that don't need DB.
"""

from __future__ import annotations

import pytest

from src.workers.devlake_sync import GLOBAL_SCOPE, make_scope_key


class TestMakeScopeKey:
    def test_jira_project_format(self):
        assert make_scope_key("jira", "project", "BG") == "jira:project:BG"

    def test_github_repo_format(self):
        assert make_scope_key("github", "repo", "foo/bar") == "github:repo:foo/bar"

    def test_jenkins_job_with_folders(self):
        # Jenkins jobs can have folder/sub/job notation
        assert (
            make_scope_key("jenkins", "job", "PI-Money/money-prd")
            == "jenkins:job:PI-Money/money-prd"
        )

    def test_global_scope_constant(self):
        # Sanity: the default value used everywhere matches what migration 010
        # set as DEFAULT in DDL. If this changes, the migration default and
        # legacy reads break.
        assert GLOBAL_SCOPE == "*"

    def test_separator_is_colon(self):
        # Scope keys are routed by source prefix; helpers and consumers all
        # split on ':'. Don't change the separator without a migration.
        result = make_scope_key("source", "dim", "value")
        assert result.count(":") == 2
        assert result.split(":") == ["source", "dim", "value"]

    @pytest.mark.parametrize(
        "source,dim,value",
        [
            ("jira", "project", "X"),
            ("github", "repo", "a/b/c"),     # repos can have slashes
            ("jenkins", "job", "x.y.z"),     # job names can have dots
            ("future", "tenant", "id-with-dashes"),
        ],
    )
    def test_value_pass_through(self, source, dim, value):
        # Helper does NOT escape or sanitize — values pass through. Callers
        # are expected to use scope_key as opaque identifier; equality
        # comparison is what matters.
        result = make_scope_key(source, dim, value)
        assert result == f"{source}:{dim}:{value}"
