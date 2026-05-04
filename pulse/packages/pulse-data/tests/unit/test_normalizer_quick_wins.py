"""Quick-wins data coverage — INC-024, INC-025, INC-026.

Three small enrichments to the normalizers so deep-links and the Jira
priority field reach the DB. All three signals are already returned by the
upstream connectors; they were just being dropped at the normalizer stage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from src.contexts.engineering_data.normalizer import (
    normalize_deployment,
    normalize_issue,
    normalize_pull_request,
)


_TENANT = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# INC-026 — normalize_issue.priority + url
# ---------------------------------------------------------------------------

class TestIssuePriorityAndUrl:
    def _base_issue(self, **overrides):
        base = {
            "id": "jira:JiraIssue:1:OKM-1234",
            "issue_key": "OKM-1234",
            "url": "https://webmotors.atlassian.net/browse/OKM-1234",
            "title": "Implementar X",
            "status": "Done",
            "original_status": "Done",
            "priority": "High",
            "type": "Task",
            "created_date": "2026-04-01T10:00:00Z",
            "updated_date": "2026-04-15T10:00:00Z",
            "resolution_date": "2026-04-15T10:00:00Z",
        }
        base.update(overrides)
        return base

    def test_priority_propagates_when_set(self):
        result = normalize_issue(self._base_issue(priority="Highest"), _TENANT)
        assert result["priority"] == "Highest"

    def test_priority_preserves_pt_br_values(self):
        """Webmotors uses pt-BR priorities (`Bloqueador`, `Crítica`)."""
        result = normalize_issue(self._base_issue(priority="Bloqueador"), _TENANT)
        assert result["priority"] == "Bloqueador"

    def test_priority_empty_string_normalizes_to_none(self):
        """Connector returns '' when Jira leaves priority unset → None for clean filtering."""
        result = normalize_issue(self._base_issue(priority=""), _TENANT)
        assert result["priority"] is None

    def test_priority_whitespace_only_normalizes_to_none(self):
        result = normalize_issue(self._base_issue(priority="   "), _TENANT)
        assert result["priority"] is None

    def test_priority_missing_key_normalizes_to_none(self):
        issue = self._base_issue()
        issue.pop("priority")
        result = normalize_issue(issue, _TENANT)
        assert result["priority"] is None

    def test_url_propagates(self):
        result = normalize_issue(self._base_issue(), _TENANT)
        assert result["url"] == "https://webmotors.atlassian.net/browse/OKM-1234"

    def test_url_missing_normalizes_to_none(self):
        issue = self._base_issue()
        issue.pop("url")
        result = normalize_issue(issue, _TENANT)
        assert result["url"] is None


# ---------------------------------------------------------------------------
# INC-025 — normalize_pull_request.url + closed_at
# ---------------------------------------------------------------------------

class TestPullRequestUrlAndClosedAt:
    def _base_pr(self, **overrides):
        base = {
            "id": "github:GithubPullRequest:1:5678",
            "title": "Fix bug",
            "url": "https://github.com/webmotors/repo/pull/5678",
            "status": "MERGED",
            "author_name": "alice",
            "created_date": "2026-04-01T10:00:00Z",
            "merged_date": "2026-04-02T15:00:00Z",
            "closed_date": "2026-04-02T15:00:00Z",
            "additions": 100,
            "deletions": 50,
            "base_repo_id": "github:GithubRepo:1:webmotors/repo",
        }
        base.update(overrides)
        return base

    def test_url_propagates(self):
        result = normalize_pull_request(self._base_pr(), _TENANT)
        assert result["url"] == "https://github.com/webmotors/repo/pull/5678"

    def test_url_missing_normalizes_to_none(self):
        pr = self._base_pr()
        pr["url"] = ""
        result = normalize_pull_request(pr, _TENANT)
        assert result["url"] is None

    def test_closed_at_populated_for_merged_pr(self):
        result = normalize_pull_request(self._base_pr(), _TENANT)
        assert result["closed_at"] == datetime(2026, 4, 2, 15, 0, tzinfo=timezone.utc)
        # closed_at and merged_at coincide for clean merges
        assert result["merged_at"] == result["closed_at"]

    def test_closed_at_populated_for_rejected_pr(self):
        """PR closed without merging — merged_at=None but closed_at populated.

        This is the exact case the new field unblocks: rejected PR aging
        analysis previously had no usable timestamp.
        """
        result = normalize_pull_request(self._base_pr(
            status="CLOSED",
            merged_date=None,
            closed_date="2026-04-03T09:00:00Z",
        ), _TENANT)
        assert result["merged_at"] is None
        assert result["closed_at"] == datetime(2026, 4, 3, 9, 0, tzinfo=timezone.utc)

    def test_closed_at_none_for_open_pr(self):
        result = normalize_pull_request(self._base_pr(
            status="OPEN", merged_date=None, closed_date=None,
        ), _TENANT)
        assert result["closed_at"] is None
        assert result["merged_at"] is None


# ---------------------------------------------------------------------------
# INC-024 — normalize_deployment.url
# ---------------------------------------------------------------------------

class TestDeploymentUrl:
    def _base_deploy(self, **overrides):
        base = {
            "id": "jenkins:JenkinsBuild:1:repo/main:42",
            "name": "repo/main",
            "result": "SUCCESS",
            "environment": "production",
            "url": "https://jenkins.webmotors.com.br/job/repo/main/42/",
            "started_date": "2026-04-15T10:00:00Z",
            "finished_date": "2026-04-15T10:05:00Z",
        }
        base.update(overrides)
        return base

    def test_url_propagates_from_jenkins(self):
        result = normalize_deployment(self._base_deploy(), _TENANT)
        assert result["url"] == "https://jenkins.webmotors.com.br/job/repo/main/42/"

    def test_url_missing_normalizes_to_none(self):
        deploy = self._base_deploy()
        deploy.pop("url")
        result = normalize_deployment(deploy, _TENANT)
        assert result["url"] is None

    def test_url_empty_string_normalizes_to_none(self):
        result = normalize_deployment(self._base_deploy(url=""), _TENANT)
        assert result["url"] is None

    def test_url_whitespace_only_normalizes_to_none(self):
        result = normalize_deployment(self._base_deploy(url="   "), _TENANT)
        assert result["url"] is None
