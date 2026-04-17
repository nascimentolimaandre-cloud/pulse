"""GitHub connector — fetches PRs via GraphQL (primary) and REST (fallback).

GraphQL path: single query returns PR + reviews + commits + file stats per page
of 50 PRs. Uses the separate GraphQL rate limit quota (5,000 pts/h), independent
from REST (also 5,000/h). Cuts API calls by ~5x vs REST+enrichment.

REST path (fallback): GET /repos/{owner}/{repo}/pulls plus 2 enrichment calls
per PR (detail + reviews). Kept for resilience when GraphQL fails.

Authentication: Personal Access Token (PAT) or GitHub App token.
Parallelism: fetch_pull_requests_batched processes multiple repos concurrently
with an asyncio.Semaphore to respect rate limits.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import settings
from src.connectors.base import BaseConnector
from src.shared.http_client import ResilientHTTPClient

logger = logging.getLogger(__name__)

# GitHub REST API constants
PER_PAGE = 100  # Max items per page
MAX_PAGES = 200  # Safety limit for pagination

# GraphQL constants
GRAPHQL_PAGE_SIZE = 50  # PRs per page (GitHub max 100, 50 keeps complexity low)
GRAPHQL_MAX_PAGES = 200  # Safety limit
GRAPHQL_REVIEWS_PER_PR = 50  # Reviews fetched per PR in the same query

# Parallelism
REPO_CONCURRENCY = 5  # Number of repos to process in parallel

# GraphQL query — fetches PRs with reviews, commits, and file stats in ONE call
PR_GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $cursor: String, $pageSize: Int!, $reviewsPerPR: Int!) {
  rateLimit { remaining, resetAt, cost }
  repository(owner: $owner, name: $name) {
    pullRequests(
      first: $pageSize,
      after: $cursor,
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage, endCursor }
      nodes {
        number
        title
        url
        state
        createdAt
        updatedAt
        closedAt
        mergedAt
        additions
        deletions
        changedFiles
        baseRefName
        headRefName
        author { login }
        mergeCommit { oid }
        commits(first: 1) {
          totalCount
          nodes {
            commit {
              authoredDate
              oid
            }
          }
        }
        reviews(first: $reviewsPerPR) {
          nodes {
            state
            submittedAt
            author { login }
          }
        }
      }
    }
  }
}
"""


class GitHubConnector(BaseConnector):
    """Fetches pull requests and repository data from GitHub REST API.

    Configuration (from settings):
        - github_token: Personal Access Token or GitHub App token
        - github_org: Organization name (e.g., "webmotors-private")
        - github_api_url: API base URL (default: https://api.github.com)

    Repo filtering:
        - repos: Explicit list of repo names to fetch (if empty, discovers all)
        - active_months: Only include repos with activity in last N months (default: 12)
        - include_archived: Whether to include archived repos (default: False)
    """

    def __init__(
        self,
        token: str | None = None,
        org: str | None = None,
        api_url: str | None = None,
        repos: list[str] | None = None,
        active_months: int = 12,
        include_archived: bool = False,
        connection_id: int = 1,
    ) -> None:
        self._token = token or settings.github_token
        self._org = org or settings.github_org
        self._api_url = (api_url or settings.github_api_url).rstrip("/")
        self._explicit_repos = repos
        self._active_months = active_months
        self._include_archived = include_archived
        self._connection_id = connection_id

        if not self._token:
            raise ValueError(
                "GitHub connector requires GITHUB_TOKEN. "
                "Set it in environment variables or .env file."
            )

        self._client = ResilientHTTPClient(
            base_url=self._api_url,
            auth={"token": self._token},
            timeout=30.0,
            max_retries=3,
            extra_headers={"X-GitHub-Api-Version": "2022-11-28"},
        )

        # Cache: discovered repos
        self._repos: list[str] | None = None

    @property
    def source_type(self) -> str:
        return "github"

    async def test_connection(self) -> dict[str, Any]:
        """Test GitHub connectivity and check rate limit."""
        try:
            user = await self._client.get("/user")
            rate = await self._client.get("/rate_limit")
            core = rate.get("resources", {}).get("core", {})
            return {
                "status": "healthy",
                "message": f"Connected as {user.get('login', 'unknown')}",
                "details": {
                    "org": self._org,
                    "rate_limit_remaining": core.get("remaining", 0),
                    "rate_limit_total": core.get("limit", 0),
                },
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    async def fetch_pull_requests(
        self, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch pull requests from all repos in the organization.

        Uses GET /repos/{owner}/{repo}/pulls with state=all for each repo.
        Supports incremental sync via `since` parameter (filters by updated_at).

        Each PR is enriched with:
        - Detail call: additions, deletions, changed_files (not in list endpoint)
        - Reviews call: first_review_at, approved_at, reviewers
        """
        repos = await self._get_repos()
        all_prs: list[dict[str, Any]] = []

        for repo_full_name in repos:
            try:
                prs = await self._fetch_repo_prs(repo_full_name, since)
                all_prs.extend(prs)
            except Exception:
                logger.exception("Failed to fetch PRs for %s", repo_full_name)

        logger.info(
            "Fetched %d PRs from %d repos (org: %s)",
            len(all_prs), len(repos), self._org,
        )
        return all_prs

    async def get_source_count(self) -> int:
        """Return the number of repos that will be scanned for PRs."""
        repos = await self._get_repos()
        return len(repos)

    async def fetch_pull_requests_batched(
        self, since: datetime | None = None,
    ) -> AsyncIterator[tuple[str, list[dict[str, Any]] | None]]:
        """Yield PRs in batches, one batch per repo — parallelized via GraphQL.

        Processes REPO_CONCURRENCY repos at a time. Each repo uses a single
        GraphQL query per page (50 PRs) instead of 1+2N REST calls.

        For each repo, emits:
          1. (repo_full_name, None) — "starting" signal for UI progress
          2. (repo_full_name, list_of_prs) — completed batch (only if non-empty)
        """
        repos = await self._get_repos()
        total_repos = len(repos)
        logger.info(
            "Starting parallel PR fetch: %d repos, concurrency=%d, page_size=%d",
            total_repos, REPO_CONCURRENCY, GRAPHQL_PAGE_SIZE,
        )

        semaphore = asyncio.Semaphore(REPO_CONCURRENCY)
        # Queue holds outputs from worker coroutines so we can yield them
        # from the outer async generator. Workers push (kind, repo, prs).
        queue: asyncio.Queue[tuple[str, str, list[dict[str, Any]] | None]] = asyncio.Queue()

        async def worker(repo_full_name: str) -> None:
            async with semaphore:
                # Emit "starting" as soon as we acquire the slot
                await queue.put(("start", repo_full_name, None))
                try:
                    prs = await self._fetch_repo_prs_graphql(repo_full_name, since)
                    if prs:
                        logger.info(
                            "Batch: %d PRs from %s (GraphQL)",
                            len(prs), repo_full_name,
                        )
                        await queue.put(("batch", repo_full_name, prs))
                    else:
                        await queue.put(("batch", repo_full_name, []))
                except Exception:
                    logger.exception(
                        "GraphQL failed for %s — retrying with REST",
                        repo_full_name,
                    )
                    try:
                        prs = await self._fetch_repo_prs(repo_full_name, since)
                        await queue.put(("batch", repo_full_name, prs or []))
                    except Exception:
                        logger.exception("REST fallback also failed for %s", repo_full_name)
                        await queue.put(("batch", repo_full_name, []))

        # Schedule all repo workers — semaphore bounds concurrency
        tasks = [asyncio.create_task(worker(r)) for r in repos]

        # Track when all workers are done
        async def wait_all() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)
            await queue.put(("done", "", None))

        waiter = asyncio.create_task(wait_all())

        while True:
            kind, repo_full_name, payload = await queue.get()
            if kind == "done":
                break
            if kind == "start":
                yield repo_full_name, None
            elif kind == "batch":
                # Always yield — empty list signals "repo done, no PRs" so the
                # caller can increment its counter and continue.
                yield repo_full_name, payload or []

        await waiter  # propagate any uncaught error

    async def _fetch_repo_prs(
        self, repo_full_name: str, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all PRs for a specific repo, with enrichment."""
        params: dict[str, Any] = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": PER_PAGE,
        }

        all_prs: list[dict[str, Any]] = []
        page = 1
        stop = False

        while page <= MAX_PAGES and not stop:
            params["page"] = page
            prs = await self._client.get(f"/repos/{repo_full_name}/pulls", params=params)

            if not prs:
                break

            for pr in prs:
                updated_at = pr.get("updated_at")
                if since and updated_at:
                    try:
                        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        if dt < since:
                            stop = True
                            break
                    except ValueError:
                        pass

                pr_number = pr.get("number", 0)

                # Enrich: fetch PR detail (additions, deletions, changed_files)
                detail = await self._fetch_pr_detail(repo_full_name, pr_number)

                # Enrich: fetch reviews (first_review_at, approved_at, reviewers)
                reviews = await self._fetch_pr_reviews(repo_full_name, pr_number)

                # Enrich: fetch first commit authored_date (INC-003)
                first_commit_at = await self._fetch_first_commit_date(
                    repo_full_name, pr_number,
                )

                mapped = self._map_pr(
                    repo_full_name, pr,
                    detail=detail, reviews=reviews,
                    first_commit_at=first_commit_at,
                )
                all_prs.append(mapped)

            if len(prs) < PER_PAGE:
                break
            page += 1

        return all_prs

    # ------------------------------------------------------------------
    # GraphQL: fetch PRs with reviews and commits in a single query
    # ------------------------------------------------------------------

    async def _fetch_repo_prs_graphql(
        self, repo_full_name: str, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all PRs for a repo via GraphQL.

        One query per page (50 PRs) returns PR + reviews + commits + file stats.
        ~5-10x fewer calls than REST for repos with many PRs.

        Stops paginating when it finds PRs older than `since` (incremental sync).
        """
        owner, name = repo_full_name.split("/", 1)
        all_prs: list[dict[str, Any]] = []
        cursor: str | None = None
        page = 0
        stop = False

        while page < GRAPHQL_MAX_PAGES and not stop:
            page += 1
            variables = {
                "owner": owner,
                "name": name,
                "cursor": cursor,
                "pageSize": GRAPHQL_PAGE_SIZE,
                "reviewsPerPR": GRAPHQL_REVIEWS_PER_PR,
            }

            response = await self._client.post(
                "/graphql",
                json_body={"query": PR_GRAPHQL_QUERY, "variables": variables},
            )

            if "errors" in response:
                errors = response.get("errors", [])
                # Non-fatal errors (e.g., partial data); log and try to continue
                first_msg = errors[0].get("message", "") if errors else ""
                if "NOT_FOUND" in str(errors).upper() or "not found" in first_msg.lower():
                    logger.warning("Repo %s not accessible via GraphQL: %s", repo_full_name, first_msg)
                    return []
                if response.get("data") is None:
                    logger.warning("GraphQL errors for %s: %s", repo_full_name, errors)
                    raise RuntimeError(f"GraphQL error for {repo_full_name}: {first_msg}")

            data = (response.get("data") or {}).get("repository")
            if not data:
                return all_prs

            prs_block = data.get("pullRequests") or {}
            nodes = prs_block.get("nodes") or []

            for pr_node in nodes:
                updated_at = pr_node.get("updatedAt")
                if since and updated_at:
                    try:
                        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        if dt < since:
                            stop = True
                            break
                    except ValueError:
                        pass

                mapped = self._map_pr_graphql(repo_full_name, pr_node)
                all_prs.append(mapped)

            page_info = prs_block.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break

        return all_prs

    def _map_pr_graphql(
        self, repo_full_name: str, node: dict[str, Any],
    ) -> dict[str, Any]:
        """Map a GraphQL PR node to the normalizer-expected dict format."""
        pr_number = node.get("number", 0)
        # GraphQL state: OPEN | CLOSED | MERGED (no inference needed)
        state = str(node.get("state", "OPEN")).upper()

        author = (node.get("author") or {}).get("login") or "unknown"
        merge_commit = (node.get("mergeCommit") or {}).get("oid")
        commits_block = node.get("commits") or {}
        commits_count = commits_block.get("totalCount", 0)

        # INC-003 fix: extract authoredDate of the first commit on the PR.
        # Use `author.date` (immutable) not `committer.date` (mutable on rebase).
        # In GraphQL PullRequestCommitConnection, nodes are ordered by position
        # in the PR, so nodes[0] is the oldest commit.
        first_commit_at: str | None = None
        commit_nodes = commits_block.get("nodes") or []
        if commit_nodes:
            first_commit_obj = (commit_nodes[0] or {}).get("commit") or {}
            first_commit_at = first_commit_obj.get("authoredDate")

        # Reviews — compute first_review_at and approved_at
        review_nodes = ((node.get("reviews") or {}).get("nodes")) or []
        reviewers: list[dict[str, str]] = []
        first_review_at: str | None = None
        approved_at: str | None = None
        for review in review_nodes:
            submitted_at = review.get("submittedAt")
            review_state = review.get("state", "")
            reviewer_login = ((review.get("author") or {}).get("login")) or "unknown"

            if reviewer_login not in [r.get("login") for r in reviewers]:
                reviewers.append({"login": reviewer_login, "state": review_state})

            if submitted_at:
                if first_review_at is None or submitted_at < first_review_at:
                    first_review_at = submitted_at
                if review_state == "APPROVED" and (
                    approved_at is None or submitted_at < approved_at
                ):
                    approved_at = submitted_at

        return {
            # Standard fields (normalizer contract)
            # IMPORTANT: include repo in ID to avoid cross-repo PR number collisions
            "id": f"github:GithubPullRequest:{self._connection_id}:{repo_full_name}:{pr_number}",
            "base_repo_id": f"github:GithubRepo:{self._connection_id}:{repo_full_name}",
            "head_repo_id": f"github:GithubRepo:{self._connection_id}:{repo_full_name}",
            "status": state,
            "title": node.get("title", ""),
            "url": node.get("url", ""),
            "author_name": author,
            "created_date": node.get("createdAt"),
            "merged_date": node.get("mergedAt"),
            "closed_date": node.get("closedAt"),
            "merge_commit_sha": merge_commit,
            "base_ref": node.get("baseRefName", ""),
            "head_ref": node.get("headRefName", ""),
            "additions": node.get("additions", 0),
            "deletions": node.get("deletions", 0),
            # Enrichment fields (consumed by normalizer)
            "_files_changed": node.get("changedFiles", 0),
            "_commits_count": commits_count,
            "_first_commit_at": first_commit_at,  # INC-003
            "_first_review_at": first_review_at,
            "_approved_at": approved_at,
            "_reviewers": reviewers,
            "_pr_number": pr_number,
            "_repo_full_name": repo_full_name,
        }

    # ------------------------------------------------------------------
    # PR Enrichment — detail + reviews (2 API calls per PR)
    # ------------------------------------------------------------------

    async def _fetch_pr_detail(
        self, repo_full_name: str, pr_number: int,
    ) -> dict[str, Any]:
        """Fetch PR detail for fields not available in the list endpoint.

        The list endpoint (GET /repos/{owner}/{repo}/pulls) returns 0 for
        additions/deletions/changed_files. The detail endpoint returns real values.
        """
        try:
            data = await self._client.get(
                f"/repos/{repo_full_name}/pulls/{pr_number}",
            )
            return {
                "additions": data.get("additions", 0),
                "deletions": data.get("deletions", 0),
                "changed_files": data.get("changed_files", 0),
                "commits": data.get("commits", 0),
            }
        except Exception:
            logger.debug("Failed to fetch detail for %s#%d", repo_full_name, pr_number)
            return {"additions": 0, "deletions": 0, "changed_files": 0, "commits": 0}

    async def _fetch_first_commit_date(
        self, repo_full_name: str, pr_number: int,
    ) -> str | None:
        """Fetch the authored_date of the first commit on a PR (INC-003).

        Uses GET /repos/{owner}/{repo}/pulls/{n}/commits with per_page=1.
        Commits are returned in chronological order (oldest first), so
        the first element is the first commit on the branch.

        Returns `commit.author.date` (ISO8601 string) or None if unavailable.
        We deliberately use `author.date` (immutable) rather than
        `committer.date`, which can be rewritten by a rebase.
        """
        try:
            commits = await self._client.get(
                f"/repos/{repo_full_name}/pulls/{pr_number}/commits",
                params={"per_page": 1, "page": 1},
            )
        except Exception:
            logger.debug("Failed to fetch first commit for %s#%d", repo_full_name, pr_number)
            return None

        if not commits:
            return None
        first = commits[0] or {}
        commit_obj = first.get("commit") or {}
        author_obj = commit_obj.get("author") or {}
        return author_obj.get("date")

    async def _fetch_pr_reviews(
        self, repo_full_name: str, pr_number: int,
    ) -> dict[str, Any]:
        """Fetch review data for a specific PR.

        Returns dict with _first_review_at, _approved_at, _reviewers.
        """
        try:
            reviews = await self._client.get(
                f"/repos/{repo_full_name}/pulls/{pr_number}/reviews",
            )
        except Exception:
            return {"_reviewers": [], "_first_review_at": None, "_approved_at": None}

        reviewers: list[dict[str, str]] = []
        first_review_at: str | None = None
        approved_at: str | None = None

        for review in reviews:
            user = review.get("user") or {}
            reviewer = user.get("login", "unknown")
            state = review.get("state", "")
            submitted_at = review.get("submitted_at")

            if reviewer not in [r.get("login") for r in reviewers]:
                reviewers.append({"login": reviewer, "state": state})

            if submitted_at:
                if first_review_at is None or submitted_at < first_review_at:
                    first_review_at = submitted_at
                if state == "APPROVED" and (approved_at is None or submitted_at < approved_at):
                    approved_at = submitted_at

        return {
            "_reviewers": reviewers,
            "_first_review_at": first_review_at,
            "_approved_at": approved_at,
        }

    # ------------------------------------------------------------------
    # Issues — GitHub Issues (not primary, Jira handles this)
    # ------------------------------------------------------------------

    async def fetch_issues(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """GitHub Issues are not our primary issue tracker (Jira is).
        Return empty for now. Can be enabled if needed.
        """
        return await self._not_supported("issues")

    async def fetch_issue_changelogs(self, issue_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return {}

    # ------------------------------------------------------------------
    # Deployments — GitHub Actions (future, currently Jenkins handles this)
    # ------------------------------------------------------------------

    async def fetch_deployments(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """GitHub deployments via Deployments API or Actions.
        Currently not used (Jenkins handles CI/CD for Webmotors).
        Can be enabled for orgs using GitHub Actions for deployments.
        """
        return await self._not_supported("deployments")

    # ------------------------------------------------------------------
    # Sprints — not applicable for GitHub
    # ------------------------------------------------------------------

    async def fetch_sprints(self, since: datetime | None = None) -> list[dict[str, Any]]:
        return await self._not_supported("sprints")

    async def fetch_sprint_issues(self, sprint_id: str) -> list[dict[str, Any]]:
        return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.close()
        logger.info("GitHub connector closed")

    # ------------------------------------------------------------------
    # Internal: Repo discovery
    # ------------------------------------------------------------------

    async def _get_repos(self) -> list[str]:
        """Get the list of repos to fetch PRs from.

        Uses explicit list if provided, otherwise discovers all org repos.
        """
        if self._repos is not None:
            return self._repos

        if self._explicit_repos:
            self._repos = [
                r if "/" in r else f"{self._org}/{r}"
                for r in self._explicit_repos
            ]
            return self._repos

        # Discover all repos in the org
        self._repos = await self.discover_repos()
        return self._repos

    async def discover_repos(
        self,
        org: str | None = None,
        active_months: int | None = None,
    ) -> list[str]:
        """Discover all repos in an organization, filtered by activity.

        Args:
            org: Organization name (default: settings.github_org)
            active_months: Only include repos active in last N months

        Returns:
            List of full repo names (e.g., ["webmotors-private/api-service"])
        """
        target_org = org or self._org
        months = active_months if active_months is not None else self._active_months
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

        all_repos = await self._client.get_paginated_link(
            f"/orgs/{target_org}/repos",
            params={"type": "all", "sort": "pushed", "direction": "desc"},
            page_size=PER_PAGE,
        )

        filtered: list[str] = []
        for repo in all_repos:
            # Skip archived repos unless configured otherwise
            if repo.get("archived") and not self._include_archived:
                continue

            # Filter by activity
            pushed_at = repo.get("pushed_at")
            if pushed_at and months > 0:
                try:
                    dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass

            filtered.append(repo.get("full_name", ""))

        logger.info(
            "Discovered %d active repos out of %d total in org %s (cutoff: %d months)",
            len(filtered), len(all_repos), target_org, months,
        )
        self._repos = filtered
        return filtered

    # ------------------------------------------------------------------
    # Internal: Mapping GitHub API → Normalizer format
    # ------------------------------------------------------------------

    def _map_pr(
        self,
        repo_full_name: str,
        pr: dict[str, Any],
        detail: dict[str, Any] | None = None,
        reviews: dict[str, Any] | None = None,
        first_commit_at: str | None = None,
    ) -> dict[str, Any]:
        """Map a GitHub PR API response to the normalizer-expected format.

        Preserves the same dict keys that DevLake's pull_requests domain table
        had, so the normalizer works unchanged. Also adds enrichment fields
        prefixed with underscore.

        Args:
            pr: Raw PR from the list endpoint
            detail: Enrichment from GET /pulls/{number} (additions, deletions, etc.)
            reviews: Enrichment from GET /pulls/{number}/reviews
        """
        pr_number = pr.get("number", 0)
        state = str(pr.get("state", "open")).upper()
        detail = detail or {}
        reviews = reviews or {}

        # GitHub merged_at is only set when PR is merged
        merged_at = pr.get("merged_at")
        if merged_at and state == "CLOSED":
            state = "MERGED"

        return {
            # Standard fields (normalizer contract — same as DevLake)
            # IMPORTANT: include repo in ID to avoid cross-repo PR number collisions
            "id": f"github:GithubPullRequest:{self._connection_id}:{repo_full_name}:{pr_number}",
            "base_repo_id": f"github:GithubRepo:{self._connection_id}:{repo_full_name}",
            "head_repo_id": f"github:GithubRepo:{self._connection_id}:{repo_full_name}",
            "status": state,
            "title": pr.get("title", ""),
            "url": pr.get("html_url", ""),
            "author_name": (pr.get("user") or {}).get("login", "unknown"),
            "created_date": pr.get("created_at"),
            "merged_date": merged_at,
            "closed_date": pr.get("closed_at"),
            "merge_commit_sha": pr.get("merge_commit_sha"),
            "base_ref": (pr.get("base") or {}).get("ref", ""),
            "head_ref": (pr.get("head") or {}).get("ref", ""),
            # From detail enrichment (list endpoint returns 0 for these)
            "additions": detail.get("additions", 0),
            "deletions": detail.get("deletions", 0),
            # Enrichment fields (consumed by normalizer)
            "_files_changed": detail.get("changed_files", 0),
            "_commits_count": detail.get("commits", 0),
            "_first_commit_at": first_commit_at,  # INC-003
            "_first_review_at": reviews.get("_first_review_at"),
            "_approved_at": reviews.get("_approved_at"),
            "_reviewers": reviews.get("_reviewers", []),
            "_pr_number": pr_number,
            "_repo_full_name": repo_full_name,
        }
