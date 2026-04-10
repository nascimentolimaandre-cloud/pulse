"""Unit tests for GitHubConnector.

Tests in this module mock ResilientHTTPClient so no real HTTP calls are made.
All assertions verify behavior at the connector boundary: method signatures,
return shapes, field mappings, incremental-sync cutoff logic, and error
handling — not HTTP transport internals.

Coverage targets (from test plan):
    1.  test_connection — healthy status with user info and rate limit
    2.  discover_repos — filters by active_months, excludes archived
    3.  discover_repos_explicit — explicit repo list used as-is (no API call)
    4.  fetch_pull_requests — iterates repos, calls enrichment per PR
    5.  fetch_pull_requests_incremental — stops at since watermark
    6.  _fetch_pr_detail — returns additions, deletions, changed_files, commits
    7.  _fetch_pr_detail_error — returns zeros on API failure
    8.  _fetch_pr_reviews — extracts first_review_at, approved_at, reviewers
    9.  _fetch_pr_reviews_empty — empty list yields empty review data
    10. _fetch_pr_reviews_error — API failure yields empty review data
    11. _map_pr — maps GitHub API response to normalizer dict
    12. _map_pr_merged — MERGED state set when merged_at present
    13. _map_pr_open — OPEN state preserved for open PRs
    14. fetch_issues — returns empty list (not_supported)
    15. fetch_deployments — returns empty list (not_supported)
    16. source_type — returns "github"
    17. close — delegates to HTTP client close
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Patch settings before the module is imported so the connector does not
# attempt to read missing env vars at module load time.
# ---------------------------------------------------------------------------

os.environ.setdefault("GITHUB_TOKEN", "test-token")
os.environ.setdefault("GITHUB_ORG", "test-org")
os.environ.setdefault("GITHUB_API_URL", "https://api.github.com")
os.environ.setdefault("JENKINS_BASE_URL", "http://jenkins.test")
os.environ.setdefault("JENKINS_API_TOKEN", "tok")

from src.connectors.github_connector import GitHubConnector  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _iso(year: int, month: int, day: int, hour: int = 0) -> str:
    return _utc(year, month, day, hour).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_github_pr(
    number: int = 1,
    state: str = "closed",
    merged_at: str | None = None,
    updated_at: str | None = None,
    title: str = "feat: sample PR",
    author: str = "dev-user",
    base_ref: str = "main",
    head_ref: str = "feature/sample",
) -> dict:
    """Build a minimal GitHub PR list-endpoint payload."""
    return {
        "number": number,
        "state": state,
        "title": title,
        "html_url": f"https://github.com/test-org/repo/pull/{number}",
        "merged_at": merged_at,
        "closed_at": merged_at,
        "created_at": _iso(2024, 1, 1),
        "updated_at": updated_at or _iso(2024, 1, 10),
        "merge_commit_sha": "abc123",
        "user": {"login": author},
        "base": {"ref": base_ref},
        "head": {"ref": head_ref},
    }


def _make_pr_detail(
    additions: int = 50,
    deletions: int = 10,
    changed_files: int = 4,
    commits: int = 3,
) -> dict:
    return {
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
        "commits": commits,
    }


def _make_review(
    login: str = "reviewer-a",
    state: str = "APPROVED",
    submitted_at: str | None = None,
) -> dict:
    return {
        "user": {"login": login},
        "state": state,
        "submitted_at": submitted_at or _iso(2024, 1, 5),
    }


def _make_repo(
    full_name: str = "test-org/repo-a",
    archived: bool = False,
    pushed_at: str | None = None,
) -> dict:
    return {
        "full_name": full_name,
        "archived": archived,
        "pushed_at": pushed_at or _iso(2024, 3, 1),
    }


def _build_connector(
    repos: list[str] | None = None,
    active_months: int = 12,
    include_archived: bool = False,
) -> tuple[GitHubConnector, MagicMock]:
    """Instantiate GitHubConnector with a mocked HTTP client.

    Returns (connector, mock_client) so tests can set up call responses.
    """
    mock_client = MagicMock()
    mock_client.get = AsyncMock()
    mock_client.get_paginated_link = AsyncMock()
    mock_client.close = AsyncMock()

    with patch("src.connectors.github_connector.ResilientHTTPClient", return_value=mock_client):
        connector = GitHubConnector(
            token="test-token",
            org="test-org",
            api_url="https://api.github.com",
            repos=repos,
            active_months=active_months,
            include_archived=include_archived,
            connection_id=1,
        )

    return connector, mock_client


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestGitHubConnector:
    # ------------------------------------------------------------------
    # 1. test_connection
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_connection_returns_healthy_status(self):
        connector, mock_client = _build_connector()
        mock_client.get.side_effect = [
            {"login": "pulse-bot", "id": 99},
            {"resources": {"core": {"remaining": 4800, "limit": 5000}}},
        ]

        result = await connector.test_connection()

        assert result["status"] == "healthy"
        assert "pulse-bot" in result["message"]
        assert result["details"]["org"] == "test-org"
        assert result["details"]["rate_limit_remaining"] == 4800
        assert result["details"]["rate_limit_total"] == 5000

    @pytest.mark.asyncio
    async def test_connection_returns_error_on_failure(self):
        connector, mock_client = _build_connector()
        mock_client.get.side_effect = ConnectionError("unreachable")

        result = await connector.test_connection()

        assert result["status"] == "error"
        assert "unreachable" in result["message"]

    # ------------------------------------------------------------------
    # 2. discover_repos — filters by active_months, excludes archived
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discover_repos_excludes_archived(self):
        connector, mock_client = _build_connector(active_months=12)
        recent_push = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        mock_client.get_paginated_link.return_value = [
            _make_repo("test-org/active", archived=False, pushed_at=recent_push),
            _make_repo("test-org/archived", archived=True, pushed_at=recent_push),
        ]

        result = await connector.discover_repos()

        assert "test-org/active" in result
        assert "test-org/archived" not in result

    @pytest.mark.asyncio
    async def test_discover_repos_excludes_stale_repos(self):
        connector, mock_client = _build_connector(active_months=6)
        old_push = (datetime.now(timezone.utc) - timedelta(days=300)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        recent_push = (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        mock_client.get_paginated_link.return_value = [
            _make_repo("test-org/fresh", archived=False, pushed_at=recent_push),
            _make_repo("test-org/stale", archived=False, pushed_at=old_push),
        ]

        result = await connector.discover_repos()

        assert "test-org/fresh" in result
        assert "test-org/stale" not in result

    @pytest.mark.asyncio
    async def test_discover_repos_includes_archived_when_configured(self):
        connector, mock_client = _build_connector(include_archived=True)
        recent_push = (datetime.now(timezone.utc) - timedelta(days=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        mock_client.get_paginated_link.return_value = [
            _make_repo("test-org/archived-repo", archived=True, pushed_at=recent_push),
        ]

        result = await connector.discover_repos()

        assert "test-org/archived-repo" in result

    # ------------------------------------------------------------------
    # 3. discover_repos_explicit — explicit repos bypass API discovery
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_repos_uses_explicit_list_without_discovery(self):
        """When repos= is supplied, no org repo API call should be made."""
        connector, mock_client = _build_connector(repos=["repo-a", "repo-b"])

        # Trigger _get_repos via fetch_pull_requests (returns empty because
        # the mock returns empty PR lists, but _get_repos must not call API)
        mock_client.get.return_value = []

        await connector.fetch_pull_requests()

        # get_paginated_link (used by discover_repos) should NOT be called
        mock_client.get_paginated_link.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_repos_qualified_with_org_prefix(self):
        """Short names (without '/') are qualified as {org}/{name}."""
        connector, mock_client = _build_connector(repos=["my-repo"])
        mock_client.get.return_value = []

        repos = await connector._get_repos()

        assert repos == ["test-org/my-repo"]

    @pytest.mark.asyncio
    async def test_explicit_repos_with_slash_kept_verbatim(self):
        """Full names (with '/') are kept as-is."""
        connector, mock_client = _build_connector(repos=["other-org/my-repo"])

        repos = await connector._get_repos()

        assert repos == ["other-org/my-repo"]

    # ------------------------------------------------------------------
    # 4. fetch_pull_requests — calls enrichment per PR across repos
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_returns_all_prs(self):
        connector, mock_client = _build_connector(repos=["test-org/repo-a"])

        pr = _make_github_pr(number=42, state="closed", merged_at=_iso(2024, 1, 10))
        detail = _make_pr_detail(additions=20, deletions=5, changed_files=2, commits=1)
        reviews: list = []

        # Three sequential get calls per PR: PR list, PR detail, PR reviews
        mock_client.get.side_effect = [
            [pr],          # /repos/.../pulls (list)
            detail,        # /repos/.../pulls/42 (detail)
            reviews,       # /repos/.../pulls/42/reviews
        ]

        result = await connector.fetch_pull_requests()

        assert len(result) == 1
        pr_out = result[0]
        assert pr_out["_pr_number"] == 42
        assert pr_out["additions"] == 20
        assert pr_out["deletions"] == 5

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_aggregates_across_repos(self):
        connector, mock_client = _build_connector(repos=["test-org/repo-a", "test-org/repo-b"])

        pr1 = _make_github_pr(number=1)
        pr2 = _make_github_pr(number=2)
        detail = _make_pr_detail()

        # repo-a: 1 PR with detail + reviews, then repo-b: 1 PR with detail + reviews
        mock_client.get.side_effect = [
            [pr1], detail, [],   # repo-a
            [pr2], detail, [],   # repo-b
        ]

        result = await connector.fetch_pull_requests()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_continues_on_repo_error(self):
        """A failure for one repo must not abort the rest."""
        connector, mock_client = _build_connector(repos=["test-org/bad-repo", "test-org/good-repo"])

        pr = _make_github_pr(number=7)
        detail = _make_pr_detail()

        # First repo raises, second repo succeeds
        mock_client.get.side_effect = [
            ConnectionError("bad-repo unavailable"),  # bad-repo list call fails
            [pr], detail, [],                          # good-repo succeeds
        ]

        result = await connector.fetch_pull_requests()

        assert len(result) == 1
        assert result[0]["_pr_number"] == 7

    # ------------------------------------------------------------------
    # 5. fetch_pull_requests_incremental — stops at since watermark
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_stops_before_watermark(self):
        """PRs updated before `since` must not be included in results."""
        connector, mock_client = _build_connector(repos=["test-org/repo"])

        since = _utc(2024, 2, 1)

        new_pr = _make_github_pr(number=10, updated_at=_iso(2024, 2, 10))
        old_pr = _make_github_pr(number=5, updated_at=_iso(2024, 1, 15))
        detail = _make_pr_detail()

        # The list endpoint returns newest first (sort=updated desc).
        # new_pr passes the watermark, old_pr does not (stop=True is set).
        mock_client.get.side_effect = [
            [new_pr, old_pr],  # list — both PRs returned by API
            detail,            # detail for new_pr
            [],                # reviews for new_pr
            # old_pr should NOT trigger detail/reviews calls
        ]

        result = await connector.fetch_pull_requests(since=since)

        assert len(result) == 1
        assert result[0]["_pr_number"] == 10

    # ------------------------------------------------------------------
    # 6. _fetch_pr_detail — returns enrichment fields
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pr_detail_returns_correct_fields(self):
        connector, mock_client = _build_connector()
        mock_client.get.return_value = {
            "additions": 120,
            "deletions": 40,
            "changed_files": 8,
            "commits": 5,
        }

        detail = await connector._fetch_pr_detail("test-org/repo", 42)

        assert detail["additions"] == 120
        assert detail["deletions"] == 40
        assert detail["changed_files"] == 8
        assert detail["commits"] == 5

    # ------------------------------------------------------------------
    # 7. _fetch_pr_detail_error — returns zeros on failure
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pr_detail_returns_zeros_on_error(self):
        connector, mock_client = _build_connector()
        mock_client.get.side_effect = ConnectionError("timeout")

        detail = await connector._fetch_pr_detail("test-org/repo", 99)

        assert detail == {"additions": 0, "deletions": 0, "changed_files": 0, "commits": 0}

    # ------------------------------------------------------------------
    # 8. _fetch_pr_reviews — extracts review timestamps and reviewers
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pr_reviews_extracts_first_review_and_approval(self):
        connector, mock_client = _build_connector()
        mock_client.get.return_value = [
            _make_review("reviewer-a", "COMMENTED", submitted_at=_iso(2024, 1, 5, 9)),
            _make_review("reviewer-b", "APPROVED",  submitted_at=_iso(2024, 1, 5, 14)),
        ]

        reviews = await connector._fetch_pr_reviews("test-org/repo", 1)

        # first_review_at is the earliest submitted_at across all reviews
        assert reviews["_first_review_at"] == _iso(2024, 1, 5, 9)
        # approved_at is set when at least one APPROVED review exists
        assert reviews["_approved_at"] == _iso(2024, 1, 5, 14)
        logins = [r["login"] for r in reviews["_reviewers"]]
        assert "reviewer-a" in logins
        assert "reviewer-b" in logins

    @pytest.mark.asyncio
    async def test_fetch_pr_reviews_no_approval_when_only_comments(self):
        connector, mock_client = _build_connector()
        mock_client.get.return_value = [
            _make_review("reviewer-a", "COMMENTED", submitted_at=_iso(2024, 1, 5, 9)),
        ]

        reviews = await connector._fetch_pr_reviews("test-org/repo", 1)

        assert reviews["_first_review_at"] == _iso(2024, 1, 5, 9)
        assert reviews["_approved_at"] is None

    @pytest.mark.asyncio
    async def test_fetch_pr_reviews_deduplicates_reviewers(self):
        """Same reviewer submitting multiple reviews must appear once."""
        connector, mock_client = _build_connector()
        mock_client.get.return_value = [
            _make_review("reviewer-a", "CHANGES_REQUESTED", submitted_at=_iso(2024, 1, 4)),
            _make_review("reviewer-a", "APPROVED",          submitted_at=_iso(2024, 1, 5)),
        ]

        reviews = await connector._fetch_pr_reviews("test-org/repo", 1)

        assert len(reviews["_reviewers"]) == 1

    # ------------------------------------------------------------------
    # 9. _fetch_pr_reviews_empty — empty list
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pr_reviews_empty_list(self):
        connector, mock_client = _build_connector()
        mock_client.get.return_value = []

        reviews = await connector._fetch_pr_reviews("test-org/repo", 1)

        assert reviews["_reviewers"] == []
        assert reviews["_first_review_at"] is None
        assert reviews["_approved_at"] is None

    # ------------------------------------------------------------------
    # 10. _fetch_pr_reviews_error — returns empty on API failure
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pr_reviews_returns_empty_on_error(self):
        connector, mock_client = _build_connector()
        mock_client.get.side_effect = ConnectionError("reviews endpoint down")

        reviews = await connector._fetch_pr_reviews("test-org/repo", 1)

        assert reviews == {"_reviewers": [], "_first_review_at": None, "_approved_at": None}

    # ------------------------------------------------------------------
    # 11. _map_pr — maps GitHub PR to normalizer format
    # ------------------------------------------------------------------

    def test_map_pr_contains_all_normalizer_fields(self):
        connector, _ = _build_connector()

        raw_pr = _make_github_pr(number=10, state="closed", merged_at=_iso(2024, 1, 10))
        detail = _make_pr_detail(additions=30, deletions=5, changed_files=3, commits=2)
        reviews = {
            "_first_review_at": _iso(2024, 1, 8),
            "_approved_at": _iso(2024, 1, 9),
            "_reviewers": [{"login": "rev-x", "state": "APPROVED"}],
        }

        mapped = connector._map_pr("test-org/repo", raw_pr, detail=detail, reviews=reviews)

        # Standard normalizer contract fields
        assert mapped["id"].startswith("github:GithubPullRequest:")
        assert mapped["base_repo_id"].startswith("github:GithubRepo:")
        assert mapped["head_repo_id"].startswith("github:GithubRepo:")
        assert mapped["title"] == "feat: sample PR"
        assert mapped["author_name"] == "dev-user"
        assert mapped["additions"] == 30
        assert mapped["deletions"] == 5
        assert mapped["base_ref"] == "main"
        assert mapped["head_ref"] == "feature/sample"

        # Enrichment fields
        assert mapped["_files_changed"] == 3
        assert mapped["_commits_count"] == 2
        assert mapped["_first_review_at"] == _iso(2024, 1, 8)
        assert mapped["_approved_at"] == _iso(2024, 1, 9)
        assert len(mapped["_reviewers"]) == 1

    def test_map_pr_without_enrichment_uses_safe_defaults(self):
        connector, _ = _build_connector()
        raw_pr = _make_github_pr(number=1, state="open")

        mapped = connector._map_pr("test-org/repo", raw_pr)

        assert mapped["additions"] == 0
        assert mapped["deletions"] == 0
        assert mapped["_files_changed"] == 0
        assert mapped["_commits_count"] == 0
        assert mapped["_reviewers"] == []
        assert mapped["_first_review_at"] is None
        assert mapped["_approved_at"] is None

    # ------------------------------------------------------------------
    # 12. _map_pr_merged — MERGED state when merged_at is set
    # ------------------------------------------------------------------

    def test_map_pr_merged_state_when_merged_at_present(self):
        connector, _ = _build_connector()
        raw_pr = _make_github_pr(number=3, state="closed", merged_at=_iso(2024, 1, 15))

        mapped = connector._map_pr("test-org/repo", raw_pr)

        assert mapped["status"] == "MERGED"
        assert mapped["merged_date"] == _iso(2024, 1, 15)

    # ------------------------------------------------------------------
    # 13. _map_pr_open — OPEN state preserved
    # ------------------------------------------------------------------

    def test_map_pr_open_state(self):
        connector, _ = _build_connector()
        raw_pr = _make_github_pr(number=4, state="open", merged_at=None)
        raw_pr["closed_at"] = None

        mapped = connector._map_pr("test-org/repo", raw_pr)

        assert mapped["status"] == "OPEN"
        assert mapped["merged_date"] is None

    def test_map_pr_closed_without_merged_at_stays_closed(self):
        """A closed (rejected) PR with no merged_at should be CLOSED, not MERGED."""
        connector, _ = _build_connector()
        raw_pr = _make_github_pr(number=5, state="closed", merged_at=None)

        mapped = connector._map_pr("test-org/repo", raw_pr)

        assert mapped["status"] == "CLOSED"

    # ------------------------------------------------------------------
    # 14. fetch_issues — returns empty (not_supported)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_issues_returns_empty_list(self):
        connector, _ = _build_connector()

        result = await connector.fetch_issues()

        assert result == []

    # ------------------------------------------------------------------
    # 15. fetch_deployments — returns empty (not_supported)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_deployments_returns_empty_list(self):
        connector, _ = _build_connector()

        result = await connector.fetch_deployments()

        assert result == []

    # ------------------------------------------------------------------
    # 16. source_type
    # ------------------------------------------------------------------

    def test_source_type_is_github(self):
        connector, _ = _build_connector()

        assert connector.source_type == "github"

    # ------------------------------------------------------------------
    # 17. close
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_close_delegates_to_http_client(self):
        connector, mock_client = _build_connector()

        await connector.close()

        mock_client.close.assert_awaited_once()

    # ------------------------------------------------------------------
    # Anti-surveillance guarantee
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_no_individual_rankings(self):
        """fetch_pull_requests must never return ranking or score fields."""
        connector, mock_client = _build_connector(repos=["test-org/repo"])

        pr = _make_github_pr(number=1, state="closed", merged_at=_iso(2024, 1, 10))
        mock_client.get.side_effect = [[pr], _make_pr_detail(), []]

        result = await connector.fetch_pull_requests()

        forbidden_keys = {"rank", "score", "leaderboard", "developer_rank", "ranking"}
        for pr_record in result:
            assert not forbidden_keys.intersection(pr_record.keys()), (
                f"PR record contains forbidden ranking key: {pr_record.keys()}"
            )

    # ------------------------------------------------------------------
    # Constructor — missing token raises early
    # ------------------------------------------------------------------

    def test_constructor_raises_without_token(self):
        with patch("src.connectors.github_connector.settings") as mock_settings:
            mock_settings.github_token = ""
            mock_settings.github_org = "test-org"
            mock_settings.github_api_url = "https://api.github.com"

            with pytest.raises(ValueError, match="GITHUB_TOKEN"):
                GitHubConnector(token=None)
