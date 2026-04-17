"""Unit tests for the DevLake data normalizer.

Tests pure normalization functions in:
    src/contexts/engineering_data/normalizer.py

Coverage targets:
- normalize_status: default mapping, custom mapping, unknown status fallback
- normalize_pull_request: state mapping, source detection, repo extraction
- normalize_issue: status normalization, type detection, project key extraction
- normalize_deployment: result-to-failure mapping, environment normalization
- normalize_sprint: with and without sprint_issues, carryover calculation
- link_issues_to_prs: branch name patterns, title matching, no match
- _detect_source: github, gitlab, jira, azure_devops, unknown
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.contexts.engineering_data.normalizer import (
    apply_pr_issue_links,
    build_issue_key_map,
    link_issues_to_prs,
    normalize_deployment,
    normalize_issue,
    normalize_pull_request,
    normalize_sprint,
    normalize_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------


class TestNormalizeStatus:
    def test_todo_maps_to_todo(self) -> None:
        assert normalize_status("To Do") == "todo"
        assert normalize_status("todo") == "todo"
        assert normalize_status("backlog") == "todo"

    def test_in_progress_variants_map_correctly(self) -> None:
        assert normalize_status("In Progress") == "in_progress"
        assert normalize_status("in development") == "in_progress"
        assert normalize_status("Code Review") == "in_progress"
        assert normalize_status("QA") == "in_progress"

    def test_done_variants_map_correctly(self) -> None:
        assert normalize_status("Done") == "done"
        assert normalize_status("closed") == "done"
        assert normalize_status("resolved") == "done"
        assert normalize_status("Released") == "done"

    def test_cancelled_maps_to_done(self) -> None:
        assert normalize_status("Cancelled") == "done"
        assert normalize_status("canceled") == "done"
        assert normalize_status("Won't Do") == "done"

    def test_unknown_status_defaults_to_todo(self) -> None:
        assert normalize_status("Weird Custom Status") == "todo"

    def test_custom_mapping_overrides_default(self) -> None:
        custom = {"my status": "in_progress"}
        assert normalize_status("My Status", status_mapping=custom) == "in_progress"

    def test_custom_mapping_case_insensitive(self) -> None:
        custom = {"DEPLOYED TO PROD": "done"}
        assert normalize_status("deployed to prod", status_mapping=custom) == "done"

    def test_whitespace_trimmed_before_lookup(self) -> None:
        assert normalize_status("  done  ") == "done"


# ---------------------------------------------------------------------------
# normalize_pull_request
# ---------------------------------------------------------------------------


class TestNormalizePullRequest:
    def test_merged_status_maps_to_merged_state(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert result["state"] == "merged"

    def test_closed_status_maps_to_closed_state(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:10", "status": "CLOSED", "title": "fix bug"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["state"] == "closed"

    def test_open_status_maps_to_open_state(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:11", "status": "OPEN", "title": "WIP: feature"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["state"] == "open"

    def test_github_source_detected_from_id(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert result["source"] == "github"

    def test_gitlab_source_detected_from_id(self) -> None:
        pr = {"id": "gitlab:GitlabMergeRequest:1:42", "status": "MERGED", "title": "feat"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["source"] == "gitlab"

    def test_repo_extracted_from_github_url(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert result["repo"] == "org/backend"

    def test_tenant_id_stored_in_result(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert result["tenant_id"] == TENANT_ID

    def test_external_id_is_string_of_devlake_id(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert result["external_id"] == sample_devlake_pr["id"]

    def test_additions_and_deletions_preserved(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert result["additions"] == 150
        assert result["deletions"] == 30

    def test_missing_additions_defaults_to_zero(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:99", "status": "MERGED", "title": "fix"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["additions"] == 0
        assert result["deletions"] == 0

    def test_created_date_parsed_as_datetime(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert isinstance(result["first_commit_at"], datetime)

    def test_merged_date_parsed_as_datetime(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        assert isinstance(result["merged_at"], datetime)

    def test_result_has_expected_keys(self, sample_devlake_pr: dict) -> None:
        result = normalize_pull_request(sample_devlake_pr, TENANT_ID)
        required_keys = {
            "external_id", "tenant_id", "source", "repo", "title",
            "state", "first_commit_at", "merged_at", "additions", "deletions",
        }
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# normalize_issue
# ---------------------------------------------------------------------------


class TestNormalizeIssue:
    def test_done_status_maps_to_done(self, sample_devlake_issue: dict) -> None:
        result = normalize_issue(sample_devlake_issue, TENANT_ID)
        assert result["normalized_status"] == "done"

    def test_completed_at_set_when_done(self, sample_devlake_issue: dict) -> None:
        result = normalize_issue(sample_devlake_issue, TENANT_ID)
        assert result["completed_at"] is not None
        assert isinstance(result["completed_at"], datetime)

    def test_completed_at_none_when_not_done(self) -> None:
        issue = {
            "id": "BACK-789",
            "issue_key": "BACK-789",
            "status": "In Progress",
            "original_status": "In Progress",
            "created_date": "2024-01-08T10:00:00Z",
        }
        result = normalize_issue(issue, TENANT_ID)
        assert result["normalized_status"] == "in_progress"
        assert result["completed_at"] is None

    def test_story_type_detected(self, sample_devlake_issue: dict) -> None:
        result = normalize_issue(sample_devlake_issue, TENANT_ID)
        assert result["type"] == "story"

    def test_bug_type_detected(self) -> None:
        issue = {
            "id": "BUG-1",
            "issue_key": "BUG-1",
            "type": "Bug",
            "status": "Done",
            "created_date": "2024-01-08T10:00:00Z",
        }
        result = normalize_issue(issue, TENANT_ID)
        assert result["type"] == "bug"

    def test_epic_type_detected(self) -> None:
        issue = {
            "id": "EPIC-1",
            "issue_key": "EPIC-1",
            "type": "Epic",
            "status": "In Progress",
            "created_date": "2024-01-08T10:00:00Z",
        }
        result = normalize_issue(issue, TENANT_ID)
        assert result["type"] == "epic"

    def test_project_key_extracted_from_issue_key(self, sample_devlake_issue: dict) -> None:
        result = normalize_issue(sample_devlake_issue, TENANT_ID)
        assert result["project_key"] == "BACK"

    def test_jira_source_detected_from_url(self, sample_devlake_issue: dict) -> None:
        result = normalize_issue(sample_devlake_issue, TENANT_ID)
        assert result["source"] == "jira"

    def test_custom_status_mapping_applied(self) -> None:
        issue = {
            "id": "PROJ-1",
            "issue_key": "PROJ-1",
            "status": "UAT",
            "original_status": "UAT",
            "created_date": "2024-01-08T10:00:00Z",
        }
        custom = {"uat": "in_progress"}
        result = normalize_issue(issue, TENANT_ID, status_mapping=custom)
        assert result["normalized_status"] == "in_progress"

    def test_tenant_id_stored_in_result(self, sample_devlake_issue: dict) -> None:
        result = normalize_issue(sample_devlake_issue, TENANT_ID)
        assert result["tenant_id"] == TENANT_ID

    def test_original_status_preserved_in_status_field(self) -> None:
        issue = {
            "id": "PROJ-5",
            "issue_key": "PROJ-5",
            "status": "Done",
            "original_status": "Released",
            "created_date": "2024-01-10T09:00:00Z",
        }
        result = normalize_issue(issue, TENANT_ID)
        assert result["status"] == "Released"


# ---------------------------------------------------------------------------
# normalize_deployment
# ---------------------------------------------------------------------------


class TestNormalizeDeployment:
    def test_success_result_is_not_failure(self, sample_devlake_deployment: dict) -> None:
        result = normalize_deployment(sample_devlake_deployment, TENANT_ID)
        assert result["is_failure"] is False

    def test_failure_result_is_failure(self) -> None:
        deploy = {
            "id": "github:GithubRun:1:999",
            "result": "FAILURE",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["is_failure"] is True

    def test_failed_result_is_failure(self) -> None:
        deploy = {
            "id": "github:GithubRun:1:1000",
            "result": "FAILED",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["is_failure"] is True

    def test_error_result_is_failure(self) -> None:
        deploy = {
            "id": "github:GithubRun:1:1001",
            "result": "ERROR",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["is_failure"] is True

    def test_finished_date_used_as_deployed_at(self, sample_devlake_deployment: dict) -> None:
        result = normalize_deployment(sample_devlake_deployment, TENANT_ID)
        assert isinstance(result["deployed_at"], datetime)

    def test_started_date_used_as_fallback_when_no_finished_date(self) -> None:
        deploy = {
            "id": "github:GithubRun:1:55",
            "result": "SUCCESS",
            "environment": "production",
            "finished_date": None,
            "started_date": "2024-01-11T14:00:00Z",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert isinstance(result["deployed_at"], datetime)

    def test_invalid_environment_defaults_to_production(self) -> None:
        deploy = {
            "id": "github:GithubRun:1:56",
            "result": "SUCCESS",
            "environment": "CUSTOM_ENV",
            "finished_date": "2024-01-15T12:00:00Z",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["environment"] == "production"

    def test_valid_environments_preserved(self) -> None:
        for env in ("production", "staging", "dev", "test"):
            deploy = {
                "id": f"github:GithubRun:1:{env}",
                "result": "SUCCESS",
                "environment": env,
                "finished_date": "2024-01-15T12:00:00Z",
            }
            result = normalize_deployment(deploy, TENANT_ID)
            assert result["environment"] == env

    def test_recovery_time_hours_is_none_by_default(self, sample_devlake_deployment: dict) -> None:
        """Recovery time is calculated by the metrics worker, not the normalizer."""
        result = normalize_deployment(sample_devlake_deployment, TENANT_ID)
        assert result["recovery_time_hours"] is None

    def test_github_source_detected(self, sample_devlake_deployment: dict) -> None:
        result = normalize_deployment(sample_devlake_deployment, TENANT_ID)
        assert result["source"] == "github"


# ---------------------------------------------------------------------------
# normalize_sprint
# ---------------------------------------------------------------------------


class TestNormalizeSprint:
    def test_basic_sprint_normalization(self, sample_devlake_sprint: dict) -> None:
        result = normalize_sprint(sample_devlake_sprint, TENANT_ID)
        assert result["external_id"] == sample_devlake_sprint["id"]
        assert result["name"] == "Sprint 5"
        assert result["tenant_id"] == TENANT_ID

    def test_no_issues_gives_zero_counts(self, sample_devlake_sprint: dict) -> None:
        result = normalize_sprint(sample_devlake_sprint, TENANT_ID, sprint_issues=None)
        assert result["committed_items"] == 0
        assert result["completed_items"] == 0
        assert result["committed_points"] == 0.0

    def test_sprint_issues_calculate_committed_and_completed(self, sample_devlake_sprint: dict) -> None:
        sprint_issues = [
            {"id": "BACK-1", "story_point": 3, "status": "done", "resolution_date": "2024-01-20T10:00:00Z"},
            {"id": "BACK-2", "story_point": 5, "status": "In Progress", "resolution_date": None},
            {"id": "BACK-3", "story_point": 2, "status": "closed", "resolution_date": "2024-01-21T12:00:00Z"},
        ]
        result = normalize_sprint(sample_devlake_sprint, TENANT_ID, sprint_issues=sprint_issues)
        assert result["committed_items"] == 3
        assert result["committed_points"] == 10.0  # 3+5+2
        assert result["completed_items"] == 2  # done + closed
        assert result["completed_points"] == 5.0  # 3+2 points

    def test_started_and_ended_dates_parsed(self, sample_devlake_sprint: dict) -> None:
        result = normalize_sprint(sample_devlake_sprint, TENANT_ID)
        assert isinstance(result["started_at"], datetime)
        assert isinstance(result["completed_at"], datetime)

    def test_jira_source_detected_from_sprint_id(self, sample_devlake_sprint: dict) -> None:
        result = normalize_sprint(sample_devlake_sprint, TENANT_ID)
        assert result["source"] == "jira"

    def test_added_and_removed_items_default_to_zero(self, sample_devlake_sprint: dict) -> None:
        """Sprint scope change tracking requires history — defaults to 0 from DevLake."""
        result = normalize_sprint(sample_devlake_sprint, TENANT_ID)
        assert result["added_items"] == 0
        assert result["removed_items"] == 0


# ---------------------------------------------------------------------------
# link_issues_to_prs
# ---------------------------------------------------------------------------


class TestLinkIssuesToPrs:
    def test_no_issues_prs_unchanged(self) -> None:
        prs = [{"id": "PR-1", "title": "BACK-123: add feature", "linked_issue_ids": []}]
        result = link_issues_to_prs(prs, [])
        assert result[0]["linked_issue_ids"] == []

    def test_no_prs_returns_empty(self) -> None:
        issues = [{"external_id": "BACK-123", "project_key": "BACK"}]
        result = link_issues_to_prs([], issues)
        assert result == []

    def test_issue_key_in_pr_title_linked(self) -> None:
        prs = [{"title": "BACK-123: implement auth", "_head_ref": "", "linked_issue_ids": []}]
        issues = [{"external_id": "BACK-123", "project_key": "BACK"}]
        result = link_issues_to_prs(prs, issues)
        assert "BACK-123" in result[0]["linked_issue_ids"]

    def test_issue_key_in_branch_name_linked(self) -> None:
        prs = [{"title": "add feature", "_head_ref": "feature/PROJ-456-auth", "linked_issue_ids": []}]
        issues = [{"external_id": "PROJ-456", "project_key": "PROJ"}]
        result = link_issues_to_prs(prs, issues)
        assert "PROJ-456" in result[0]["linked_issue_ids"]

    def test_no_matching_key_leaves_linked_ids_empty(self) -> None:
        prs = [{"title": "fix typo", "_head_ref": "bugfix/typo", "linked_issue_ids": []}]
        issues = [{"external_id": "BACK-999", "project_key": "BACK"}]
        result = link_issues_to_prs(prs, issues)
        assert result[0]["linked_issue_ids"] == []

    def test_multiple_issue_keys_in_pr_title_all_linked(self) -> None:
        prs = [{"title": "BACK-100 and BACK-200: merge two features", "_head_ref": "", "linked_issue_ids": []}]
        issues = [
            {"external_id": "BACK-100", "project_key": "BACK"},
            {"external_id": "BACK-200", "project_key": "BACK"},
        ]
        result = link_issues_to_prs(prs, issues)
        assert "BACK-100" in result[0]["linked_issue_ids"]
        assert "BACK-200" in result[0]["linked_issue_ids"]

    def test_issue_key_not_duplicated_in_linked_ids(self) -> None:
        """Same issue key appearing multiple times should link only once."""
        prs = [{"title": "BACK-123: fix BACK-123", "_head_ref": "feature/BACK-123", "linked_issue_ids": []}]
        issues = [{"external_id": "BACK-123", "project_key": "BACK"}]
        result = link_issues_to_prs(prs, issues)
        assert result[0]["linked_issue_ids"].count("BACK-123") == 1

    def test_case_insensitive_matching(self) -> None:
        """Branch name with lowercase issue key should still match."""
        prs = [{"title": "add feature", "_head_ref": "feature/back-777-auth", "linked_issue_ids": []}]
        issues = [{"external_id": "BACK-777", "project_key": "BACK"}]
        result = link_issues_to_prs(prs, issues)
        assert "BACK-777" in result[0]["linked_issue_ids"]


# ---------------------------------------------------------------------------
# Source detection
# ---------------------------------------------------------------------------


class TestDetectSource:
    """Tests for _detect_source via normalize functions (indirect)."""

    def test_github_url_detected(self) -> None:
        pr = {
            "id": "pr-1",
            "url": "https://github.com/org/repo/pull/1",
            "status": "MERGED",
            "title": "test",
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["source"] == "github"

    def test_gitlab_url_detected(self) -> None:
        pr = {
            "id": "pr-1",
            "url": "https://gitlab.com/org/repo/merge_requests/1",
            "status": "MERGED",
            "title": "test",
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["source"] == "gitlab"

    def test_jira_url_detected(self) -> None:
        issue = {
            "id": "ISSUE-1",
            "issue_key": "ISSUE-1",
            "url": "https://myorg.atlassian.net/browse/ISSUE-1",
            "status": "Done",
            "created_date": "2024-01-08T10:00:00Z",
        }
        result = normalize_issue(issue, TENANT_ID)
        assert result["source"] == "jira"

    def test_azure_devops_id_detected(self) -> None:
        pr = {
            "id": "azure:AzurePullRequest:1:42",
            "status": "MERGED",
            "title": "feat",
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["source"] == "azure"

    def test_jenkins_id_detected(self) -> None:
        deploy = {
            "id": "jenkins:JenkinsJob:1:42",
            "result": "SUCCESS",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["source"] == "jenkins"

    def test_jenkins_url_detected(self) -> None:
        deploy = {
            "id": "deploy-999",
            "url": "https://jenkins.webmotors.com.br/job/deploy/42",
            "result": "SUCCESS",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["source"] == "jenkins"

    def test_unknown_source_returns_unknown(self) -> None:
        pr = {
            "id": "custom:Thing:1",
            "status": "MERGED",
            "title": "feat",
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["source"] == "unknown"


# ---------------------------------------------------------------------------
# Jenkins-specific deployment normalization
# ---------------------------------------------------------------------------


class TestJenkinsDeploymentNormalization:
    """Tests for Jenkins-specific behavior in normalize_deployment."""

    def test_jenkins_success_is_not_failure(self) -> None:
        deploy = {
            "id": "jenkins:JenkinsJob:1:100",
            "result": "SUCCESS",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["is_failure"] is False
        assert result["source"] == "jenkins"

    def test_jenkins_failure_is_failure(self) -> None:
        deploy = {
            "id": "jenkins:JenkinsJob:1:101",
            "result": "FAILURE",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["is_failure"] is True

    def test_jenkins_unstable_is_failure(self) -> None:
        """Jenkins UNSTABLE means tests failed — should count as failure for DORA CFR."""
        deploy = {
            "id": "jenkins:JenkinsJob:1:102",
            "result": "UNSTABLE",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["is_failure"] is True

    def test_jenkins_aborted_is_not_failure(self) -> None:
        """Jenkins ABORTED means manually cancelled — not a failure for DORA."""
        deploy = {
            "id": "jenkins:JenkinsJob:1:103",
            "result": "ABORTED",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["is_failure"] is False

    def test_jenkins_job_name_used_as_repo(self) -> None:
        """For Jenkins, the job name serves as repo identifier."""
        deploy = {
            "id": "jenkins:JenkinsJob:1:200",
            "result": "SUCCESS",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["repo"] == "webmotors-next-ui/deploy"

    def test_jenkins_empty_name_falls_back_to_repo_id(self) -> None:
        deploy = {
            "id": "jenkins:JenkinsJob:1:201",
            "result": "SUCCESS",
            "environment": "staging",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "",
            "repo_id": "jenkins:JenkinsJob:1",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["repo"] == "jenkins:JenkinsJob:1"

    def test_jenkins_production_environment_preserved(self) -> None:
        deploy = {
            "id": "jenkins:JenkinsJob:1:300",
            "result": "SUCCESS",
            "environment": "production",
            "finished_date": "2024-01-15T12:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["environment"] == "production"

    def test_jenkins_staging_environment_preserved(self) -> None:
        deploy = {
            "id": "jenkins:JenkinsJob:1:301",
            "result": "SUCCESS",
            "environment": "staging",
            "finished_date": "2024-01-16T10:00:00Z",
            "name": "webmotors-next-ui/deploy",
        }
        result = normalize_deployment(deploy, TENANT_ID)
        assert result["environment"] == "staging"


# ---------------------------------------------------------------------------
# Enrichment-field tests — connector-format fixtures (post-ADR-005 migration)
# ---------------------------------------------------------------------------


class TestNormalizePrEnrichmentFields:
    """Verify normalizer maps underscore-prefixed enrichment fields correctly."""

    def test_first_review_at_parsed_as_datetime(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert isinstance(result["first_review_at"], datetime)
        assert result["first_review_at"].tzinfo is not None

    def test_approved_at_parsed_as_datetime(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert isinstance(result["approved_at"], datetime)
        assert result["approved_at"].tzinfo is not None

    def test_files_changed_mapped_as_integer(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["files_changed"] == 12
        assert isinstance(result["files_changed"], int)

    def test_commits_count_mapped_as_integer(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["commits_count"] == 7
        assert isinstance(result["commits_count"], int)

    def test_reviewers_is_list_of_dicts(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert isinstance(result["reviewers"], list)
        assert len(result["reviewers"]) == 2
        assert result["reviewers"][0]["login"] == "dave"
        assert result["reviewers"][1]["login"] == "eve"

    def test_is_merged_true_when_merged_date_present(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["is_merged"] is True

    def test_enrichment_values_match_fixture(self, sample_github_pr_raw: dict) -> None:
        """Spot-check that parsed datetime values match the raw ISO strings."""
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        expected_first_review = datetime(2024, 3, 1, 16, 45, 0, tzinfo=timezone.utc)
        expected_approved = datetime(2024, 3, 2, 9, 10, 0, tzinfo=timezone.utc)
        assert result["first_review_at"] == expected_first_review
        assert result["approved_at"] == expected_approved


class TestFirstCommitEnrichment:
    """INC-003 — normalizer must prefer real `_first_commit_at` over created_date."""

    def test_uses_enrichment_first_commit_when_present(self) -> None:
        pr = {
            "id": "github:GithubPullRequest:1:400",
            "status": "MERGED",
            "title": "feat",
            "created_date": "2026-04-10T15:00:00Z",
            "merged_date": "2026-04-10T15:05:00Z",
            "_first_commit_at": "2026-04-01T09:00:00Z",  # 9 days earlier
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["first_commit_at"] == datetime(
            2026, 4, 1, 9, 0, 0, tzinfo=timezone.utc,
        )

    def test_falls_back_to_created_date_when_enrichment_missing(self) -> None:
        pr = {
            "id": "github:GithubPullRequest:1:401",
            "status": "MERGED",
            "title": "feat",
            "created_date": "2026-04-10T15:00:00Z",
            "merged_date": "2026-04-10T15:05:00Z",
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["first_commit_at"] == datetime(
            2026, 4, 10, 15, 0, 0, tzinfo=timezone.utc,
        )

    def test_falls_back_when_enrichment_is_none(self) -> None:
        pr = {
            "id": "github:GithubPullRequest:1:402",
            "status": "MERGED",
            "title": "feat",
            "created_date": "2026-04-10T15:00:00Z",
            "merged_date": "2026-04-10T15:05:00Z",
            "_first_commit_at": None,
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["first_commit_at"] == datetime(
            2026, 4, 10, 15, 0, 0, tzinfo=timezone.utc,
        )


class TestNormalizePrEnrichmentNulls:
    """Verify enrichment fields default to safe zero-values when absent."""

    def test_first_review_at_none_when_not_provided(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:200", "status": "MERGED", "title": "fix typo"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["first_review_at"] is None

    def test_approved_at_none_when_not_provided(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:201", "status": "MERGED", "title": "fix typo"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["approved_at"] is None

    def test_files_changed_zero_when_not_provided(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:202", "status": "MERGED", "title": "fix typo"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["files_changed"] == 0

    def test_commits_count_zero_when_not_provided(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:203", "status": "MERGED", "title": "fix typo"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["commits_count"] == 0

    def test_reviewers_empty_list_when_not_provided(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:204", "status": "MERGED", "title": "fix typo"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["reviewers"] == []

    def test_explicit_none_enrichment_fields_safe(self) -> None:
        """Explicit None values should not raise and should return safe defaults."""
        pr = {
            "id": "github:GithubPullRequest:1:205",
            "status": "OPEN",
            "title": "WIP: new feature",
            "_first_review_at": None,
            "_approved_at": None,
            "_files_changed": None,
            "_commits_count": None,
            "_reviewers": None,
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["first_review_at"] is None
        assert result["approved_at"] is None
        assert result["files_changed"] == 0
        assert result["commits_count"] == 0
        assert result["reviewers"] == []


class TestNormalizePrIsMergedFalse:
    """Verify is_merged is False when merged_date is absent or None."""

    def test_is_merged_false_when_no_merged_date(self) -> None:
        pr = {"id": "github:GithubPullRequest:1:300", "status": "OPEN", "title": "WIP"}
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["is_merged"] is False

    def test_is_merged_false_when_merged_date_is_none(self) -> None:
        pr = {
            "id": "github:GithubPullRequest:1:301",
            "status": "CLOSED",
            "title": "closed without merge",
            "merged_date": None,
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["is_merged"] is False

    def test_is_merged_true_when_merged_date_is_string(self) -> None:
        pr = {
            "id": "github:GithubPullRequest:1:302",
            "status": "MERGED",
            "title": "merged pr",
            "merged_date": "2024-04-01T12:00:00Z",
        }
        result = normalize_pull_request(pr, TENANT_ID)
        assert result["is_merged"] is True


class TestNormalizePrFromGithubConnector:
    """End-to-end normalization using the connector-format fixture."""

    def test_source_is_github(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["source"] == "github"

    def test_repo_extracted_correctly(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["repo"] == "org/backend"

    def test_state_is_merged(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["state"] == "merged"

    def test_tenant_id_stored(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["tenant_id"] == TENANT_ID

    def test_additions_and_deletions(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["additions"] == 210
        assert result["deletions"] == 55

    def test_all_enrichment_fields_present(self, sample_github_pr_raw: dict) -> None:
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        enrichment_keys = {"first_review_at", "approved_at", "files_changed", "commits_count", "reviewers"}
        assert enrichment_keys.issubset(result.keys())

    def test_linked_issue_ids_starts_empty(self, sample_github_pr_raw: dict) -> None:
        """linked_issue_ids is populated by link_issues_to_prs(), not by the normalizer."""
        result = normalize_pull_request(sample_github_pr_raw, TENANT_ID)
        assert result["linked_issue_ids"] == []


class TestNormalizeIssueFromJiraConnector:
    """Normalization of JiraConnector._map_issue() output."""

    def test_source_is_jira(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["source"] == "jira"

    def test_project_key_extracted(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["project_key"] == "DESC"

    def test_normalized_status_is_done(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["normalized_status"] == "done"

    def test_completed_at_is_datetime(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert isinstance(result["completed_at"], datetime)

    def test_issue_type_is_story(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["issue_type"] == "story"

    def test_story_points_preserved(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["story_points"] == 8

    def test_sprint_id_preserved(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["sprint_id"] == "jira:JiraSprint:1:55"

    def test_external_id_matches_connector_id(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["external_id"] == "jira:JiraIssue:1:98765"

    def test_tenant_id_stored(self, sample_jira_issue_raw: dict) -> None:
        result = normalize_issue(sample_jira_issue_raw, TENANT_ID)
        assert result["tenant_id"] == TENANT_ID


class TestNormalizeSprintFromJiraConnector:
    """Normalization of JiraConnector._map_sprint() output."""

    def test_source_is_jira(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID)
        assert result["source"] == "jira"

    def test_external_id_matches_connector_id(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID)
        assert result["external_id"] == "jira:JiraSprint:1:55"

    def test_name_preserved(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID)
        assert result["name"] == "DESC Sprint 7"

    def test_board_id_mapped_from_original_board_id(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID)
        assert result["board_id"] == "10"

    def test_started_at_is_datetime(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID)
        assert isinstance(result["started_at"], datetime)

    def test_completed_at_is_datetime(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID)
        assert isinstance(result["completed_at"], datetime)

    def test_tenant_id_stored(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID)
        assert result["tenant_id"] == TENANT_ID

    def test_zero_counts_without_issues(self, sample_jira_sprint_raw: dict) -> None:
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID, sprint_issues=None)
        assert result["committed_items"] == 0
        assert result["completed_items"] == 0
        assert result["committed_points"] == 0.0

    def test_counts_calculated_from_sprint_issues(self, sample_jira_sprint_raw: dict) -> None:
        sprint_issues = [
            {"id": "DESC-10", "story_point": 5, "status": "done", "resolution_date": "2024-02-18T10:00:00Z"},
            {"id": "DESC-11", "story_point": 3, "status": "in progress", "resolution_date": None},
            {"id": "DESC-12", "story_point": 8, "status": "closed", "resolution_date": "2024-02-19T12:00:00Z"},
        ]
        result = normalize_sprint(sample_jira_sprint_raw, TENANT_ID, sprint_issues=sprint_issues)
        assert result["committed_items"] == 3
        assert result["committed_points"] == 16.0  # 5 + 3 + 8
        assert result["completed_items"] == 2       # done + closed
        assert result["completed_points"] == 13.0  # 5 + 8


class TestNormalizeDeploymentFromJenkins:
    """End-to-end normalization using the Jenkins connector-format fixture."""

    def test_source_is_jenkins(self, sample_jenkins_deployment_raw: dict) -> None:
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        assert result["source"] == "jenkins"

    def test_is_not_failure_for_success(self, sample_jenkins_deployment_raw: dict) -> None:
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        assert result["is_failure"] is False

    def test_deployed_at_uses_finished_date(self, sample_jenkins_deployment_raw: dict) -> None:
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        expected = datetime(2024, 3, 5, 22, 8, 45, tzinfo=timezone.utc)
        assert result["deployed_at"] == expected

    def test_environment_is_production(self, sample_jenkins_deployment_raw: dict) -> None:
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        assert result["environment"] == "production"

    def test_repo_uses_job_name(self, sample_jenkins_deployment_raw: dict) -> None:
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        assert result["repo"] == "webmotors-next-ui/deploy-prod"

    def test_external_id_matches_connector_id(self, sample_jenkins_deployment_raw: dict) -> None:
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        assert result["external_id"] == "jenkins:JenkinsBuild:1:webmotors-next-ui/deploy-prod:312"

    def test_tenant_id_stored(self, sample_jenkins_deployment_raw: dict) -> None:
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        assert result["tenant_id"] == TENANT_ID

    def test_recovery_time_hours_is_none(self, sample_jenkins_deployment_raw: dict) -> None:
        """Recovery time is computed by the metrics worker, not the normalizer."""
        result = normalize_deployment(sample_jenkins_deployment_raw, TENANT_ID)
        assert result["recovery_time_hours"] is None

    def test_failure_build_is_failure(self, sample_jenkins_deployment_raw: dict) -> None:
        failed = {**sample_jenkins_deployment_raw, "result": "FAILURE"}
        result = normalize_deployment(failed, TENANT_ID)
        assert result["is_failure"] is True

    def test_unstable_build_is_failure(self, sample_jenkins_deployment_raw: dict) -> None:
        unstable = {**sample_jenkins_deployment_raw, "result": "UNSTABLE"}
        result = normalize_deployment(unstable, TENANT_ID)
        assert result["is_failure"] is True

    def test_aborted_build_is_not_failure(self, sample_jenkins_deployment_raw: dict) -> None:
        aborted = {**sample_jenkins_deployment_raw, "result": "ABORTED"}
        result = normalize_deployment(aborted, TENANT_ID)
        assert result["is_failure"] is False


# ---------------------------------------------------------------------------
# PR-to-issue linking helpers
# ---------------------------------------------------------------------------


class TestBuildIssueKeyMap:
    def test_uses_explicit_issue_key_column(self) -> None:
        """When issue_key is provided, it's used directly (no regex needed)."""
        result = build_issue_key_map([
            ("ANCR-1234", "jira:JiraIssue:1:792543"),
            ("DESC-42", "jira:JiraIssue:1:792544"),
        ])
        assert result["ANCR-1234"] == "jira:JiraIssue:1:792543"
        assert result["DESC-42"] == "jira:JiraIssue:1:792544"

    def test_keys_are_uppercased(self) -> None:
        result = build_issue_key_map([("ancr-7", "jira:JiraIssue:1:100")])
        assert "ANCR-7" in result
        assert result["ANCR-7"] == "jira:JiraIssue:1:100"

    def test_falls_back_to_external_id_regex_when_key_missing(self) -> None:
        """Legacy rows pre-migration 005 have issue_key=NULL; extract from id."""
        result = build_issue_key_map([(None, "github:Issue:FOO-99")])
        assert result == {"FOO-99": "github:Issue:FOO-99"}

    def test_skips_rows_with_neither_key_nor_extractable_id(self) -> None:
        result = build_issue_key_map([(None, "jira:JiraIssue:1:792543")])
        assert result == {}

    def test_ignores_empty_external_id(self) -> None:
        result = build_issue_key_map([("ANCR-1", "")])
        assert result == {}

    def test_handles_empty_input(self) -> None:
        assert build_issue_key_map([]) == {}


class TestApplyPrIssueLinks:
    def test_links_from_title(self) -> None:
        prs = [{"title": "ANCR-1234 fix login bug"}]
        key_map = {"ANCR-1234": "jira:JiraIssue:1:ANCR-1234"}
        count = apply_pr_issue_links(prs, key_map)
        assert count == 1
        assert prs[0]["linked_issue_ids"] == ["jira:JiraIssue:1:ANCR-1234"]

    def test_links_from_head_ref(self) -> None:
        prs = [{"title": "fix bug", "_head_ref": "feature/DESC-42-login"}]
        key_map = {"DESC-42": "jira:JiraIssue:1:DESC-42"}
        apply_pr_issue_links(prs, key_map)
        assert prs[0]["linked_issue_ids"] == ["jira:JiraIssue:1:DESC-42"]

    def test_multiple_keys_in_same_pr(self) -> None:
        prs = [{"title": "ANCR-1 and ANCR-2 together"}]
        key_map = {
            "ANCR-1": "jira:JiraIssue:1:ANCR-1",
            "ANCR-2": "jira:JiraIssue:1:ANCR-2",
        }
        apply_pr_issue_links(prs, key_map)
        assert set(prs[0]["linked_issue_ids"]) == {
            "jira:JiraIssue:1:ANCR-1",
            "jira:JiraIssue:1:ANCR-2",
        }

    def test_deduplicates_repeated_key(self) -> None:
        prs = [{"title": "ANCR-1 ANCR-1 again", "_head_ref": "ancr-1-branch"}]
        key_map = {"ANCR-1": "jira:JiraIssue:1:ANCR-1"}
        apply_pr_issue_links(prs, key_map)
        assert prs[0]["linked_issue_ids"] == ["jira:JiraIssue:1:ANCR-1"]

    def test_unknown_key_not_linked(self) -> None:
        prs = [{"title": "NOPE-999 fix"}]
        key_map = {"ANCR-1": "jira:JiraIssue:1:ANCR-1"}
        apply_pr_issue_links(prs, key_map)
        # No linked ids set (or empty) — either is acceptable, but not a wrong link
        assert prs[0].get("linked_issue_ids", []) == []

    def test_empty_key_map_is_noop(self) -> None:
        prs = [{"title": "ANCR-1 x"}]
        count = apply_pr_issue_links(prs, {})
        assert count == 0

    def test_returns_linked_pr_count(self) -> None:
        prs = [
            {"title": "ANCR-1 fix"},
            {"title": "no key here"},
            {"title": "ANCR-2 feat"},
        ]
        key_map = {
            "ANCR-1": "jira:JiraIssue:1:ANCR-1",
            "ANCR-2": "jira:JiraIssue:1:ANCR-2",
        }
        count = apply_pr_issue_links(prs, key_map)
        assert count == 2
