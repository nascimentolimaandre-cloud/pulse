"""Unit tests for JenkinsConnector.

Tests in this module mock ResilientHTTPClient so no real HTTP calls are made.
All assertions verify behavior at the connector boundary: method signatures,
return shapes, field mappings, watermark filtering, environment detection,
and error handling — not HTTP transport internals.

Coverage targets (from test plan):
    1.  test_connection — healthy status with Jenkins version/executor info
    2.  fetch_deployments — fetches builds from configured jobs
    3.  fetch_deployments_incremental — filters builds before since watermark
    4.  discover_jobs — returns job list from Jenkins API
    5.  _map_build — maps Jenkins build dict to normalizer deployment format
    6.  _detect_environment — heuristics and pattern-based env detection
    7.  source_type — returns "jenkins"
    8.  fetch_pull_requests — returns empty (not_supported)
    9.  fetch_issues — returns empty (not_supported)
    10. close — delegates to HTTP client close
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("GITHUB_TOKEN", "test-token")
os.environ.setdefault("JENKINS_BASE_URL", "http://jenkins.test")
os.environ.setdefault("JENKINS_API_TOKEN", "tok")

from src.connectors.jenkins_connector import JenkinsConnector  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _ts_ms(year: int, month: int, day: int, hour: int = 0) -> int:
    """Return Unix timestamp in milliseconds for a UTC datetime."""
    dt = _utc(year, month, day, hour)
    return int(dt.timestamp() * 1000)


def _make_jenkins_build(
    number: int = 42,
    result: str = "SUCCESS",
    timestamp_ms: int | None = None,
    duration_ms: int = 300_000,  # 5 minutes
    url: str = "http://jenkins.test/job/deploy-prod/42/",
) -> dict:
    """Build a minimal Jenkins build API payload."""
    return {
        "number": number,
        "result": result,
        "timestamp": timestamp_ms if timestamp_ms is not None else _ts_ms(2024, 1, 10),
        "duration": duration_ms,
        "url": url,
        "displayName": f"#{number}",
    }


def _make_jenkins_job(
    full_name: str = "deploy-prod",
    url: str = "http://jenkins.test/job/deploy-prod/",
    color: str = "blue",
) -> dict:
    return {"fullName": full_name, "url": url, "color": color, "name": full_name}


def _build_connector(
    jobs: list[dict] | None = None,
    connection_id: int = 1,
) -> tuple[JenkinsConnector, MagicMock]:
    """Instantiate JenkinsConnector with a mocked HTTP client.

    Returns (connector, mock_client).
    """
    mock_client = MagicMock()
    mock_client.get = AsyncMock()
    mock_client.close = AsyncMock()

    with patch("src.connectors.jenkins_connector.ResilientHTTPClient", return_value=mock_client):
        connector = JenkinsConnector(
            base_url="http://jenkins.test",
            username="pulse-svc",
            api_token="super-secret-token",
            jobs=jobs or [],
            connection_id=connection_id,
        )

    return connector, mock_client


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestJenkinsConnector:
    # ------------------------------------------------------------------
    # 1. test_connection
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_connection_returns_healthy_status(self):
        jobs = [{"fullName": "deploy-prod"}, {"fullName": "deploy-staging"}]
        connector, mock_client = _build_connector(jobs=jobs)
        mock_client.get.return_value = {
            "nodeDescription": "Jenkins master",
            "numExecutors": 4,
        }

        result = await connector.test_connection()

        assert result["status"] == "healthy"
        assert "Jenkins master" in result["message"]
        assert result["details"]["executors"] == 4
        assert result["details"]["configured_jobs"] == 2

    @pytest.mark.asyncio
    async def test_connection_returns_error_on_failure(self):
        connector, mock_client = _build_connector()
        mock_client.get.side_effect = ConnectionError("Jenkins unreachable")

        result = await connector.test_connection()

        assert result["status"] == "error"
        assert "Jenkins unreachable" in result["message"]

    @pytest.mark.asyncio
    async def test_connection_handles_missing_node_description(self):
        """Should not crash if Jenkins returns partial response."""
        connector, mock_client = _build_connector()
        mock_client.get.return_value = {}  # nodeDescription missing

        result = await connector.test_connection()

        assert result["status"] == "healthy"
        assert "unknown" in result["message"]

    # ------------------------------------------------------------------
    # 2. fetch_deployments — fetches builds from configured jobs
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_deployments_maps_builds_to_deployment_format(self):
        jobs = [{"fullName": "deploy-prod"}]
        connector, mock_client = _build_connector(jobs=jobs)
        build = _make_jenkins_build(number=10, result="SUCCESS")
        mock_client.get.return_value = {"builds": [build]}

        result = await connector.fetch_deployments()

        assert len(result) == 1
        dep = result[0]
        assert dep["id"].startswith("jenkins:JenkinsBuild:1:deploy-prod:10")
        assert dep["result"] == "SUCCESS"
        assert dep["status"] == "DONE"
        assert dep["environment"] == "production"  # heuristic: "prod" in name
        assert dep["started_date"] is not None
        assert dep["finished_date"] is not None

    @pytest.mark.asyncio
    async def test_fetch_deployments_skips_in_progress_builds(self):
        """Builds with no result (still running) must be excluded."""
        jobs = [{"fullName": "deploy-prod"}]
        connector, mock_client = _build_connector(jobs=jobs)

        running_build = _make_jenkins_build(number=5, result=None)  # type: ignore[arg-type]
        done_build = _make_jenkins_build(number=6, result="SUCCESS")
        mock_client.get.return_value = {"builds": [running_build, done_build]}

        result = await connector.fetch_deployments()

        assert len(result) == 1
        assert result[0]["id"].endswith(":6")

    @pytest.mark.asyncio
    async def test_fetch_deployments_returns_empty_when_no_jobs_configured(self):
        connector, mock_client = _build_connector(jobs=[])

        result = await connector.fetch_deployments()

        assert result == []
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_deployments_continues_on_job_failure(self):
        """A failure for one job must not abort the rest."""
        jobs = [
            {"fullName": "bad-job"},
            {"fullName": "good-job-prod"},
        ]
        connector, mock_client = _build_connector(jobs=jobs)

        good_build = _make_jenkins_build(number=1, result="SUCCESS")
        mock_client.get.side_effect = [
            ConnectionError("bad-job unavailable"),
            {"builds": [good_build]},
        ]

        result = await connector.fetch_deployments()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_deployments_aggregates_across_multiple_jobs(self):
        jobs = [
            {"fullName": "deploy-prod"},
            {"fullName": "deploy-staging"},
        ]
        connector, mock_client = _build_connector(jobs=jobs)

        prod_build = _make_jenkins_build(number=10, result="SUCCESS")
        stg_build = _make_jenkins_build(number=5, result="FAILURE")
        mock_client.get.side_effect = [
            {"builds": [prod_build]},
            {"builds": [stg_build]},
        ]

        result = await connector.fetch_deployments()

        assert len(result) == 2

    # ------------------------------------------------------------------
    # 3. fetch_deployments_incremental — filters by since watermark
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_deployments_filters_builds_before_watermark(self):
        jobs = [{"fullName": "deploy-prod"}]
        connector, mock_client = _build_connector(jobs=jobs)

        since = _utc(2024, 2, 1)
        new_ts = _ts_ms(2024, 2, 10)
        old_ts = _ts_ms(2024, 1, 15)

        new_build = _make_jenkins_build(number=20, result="SUCCESS", timestamp_ms=new_ts)
        old_build = _make_jenkins_build(number=15, result="SUCCESS", timestamp_ms=old_ts)
        mock_client.get.return_value = {"builds": [new_build, old_build]}

        result = await connector.fetch_deployments(since=since)

        assert len(result) == 1
        assert result[0]["id"].endswith(":20")

    @pytest.mark.asyncio
    async def test_fetch_deployments_no_watermark_returns_all(self):
        jobs = [{"fullName": "deploy-prod"}]
        connector, mock_client = _build_connector(jobs=jobs)

        builds = [
            _make_jenkins_build(number=i, result="SUCCESS") for i in range(1, 6)
        ]
        mock_client.get.return_value = {"builds": builds}

        result = await connector.fetch_deployments(since=None)

        assert len(result) == 5

    # ------------------------------------------------------------------
    # 4. discover_jobs — returns job list from root or folder
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discover_jobs_returns_job_list(self):
        connector, mock_client = _build_connector()
        mock_client.get.return_value = {
            "jobs": [
                _make_jenkins_job("deploy-prod"),
                _make_jenkins_job("deploy-staging"),
                _make_jenkins_job("build-service"),
            ]
        }

        result = await connector.discover_jobs()

        assert len(result) == 3
        full_names = [j["fullName"] for j in result]
        assert "deploy-prod" in full_names

    @pytest.mark.asyncio
    async def test_discover_jobs_with_folder_scopes_api_path(self):
        """When a folder is provided, the API path should include the folder."""
        connector, mock_client = _build_connector()
        mock_client.get.return_value = {
            "jobs": [_make_jenkins_job("my-folder/deploy-prod")]
        }

        result = await connector.discover_jobs(folder="my-folder")

        # Verify the API was called (path assertion happens implicitly via call)
        mock_client.get.assert_awaited_once()
        call_args = mock_client.get.call_args
        assert "my-folder" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_discover_jobs_returns_empty_on_no_jobs(self):
        connector, mock_client = _build_connector()
        mock_client.get.return_value = {"jobs": []}

        result = await connector.discover_jobs()

        assert result == []

    # ------------------------------------------------------------------
    # 5. _map_build — maps Jenkins build to deployment format
    # ------------------------------------------------------------------

    def test_map_build_success_fields(self):
        connector, _ = _build_connector()
        ts = _ts_ms(2024, 3, 5, 14)
        duration = 600_000  # 10 minutes
        build = _make_jenkins_build(
            number=99, result="SUCCESS", timestamp_ms=ts, duration_ms=duration
        )

        mapped = connector._map_build("deploy-prod", build)

        assert mapped["id"] == "jenkins:JenkinsBuild:1:deploy-prod:99"
        assert mapped["cicd_deployment_id"] == "jenkins:JenkinsJob:1:deploy-prod"
        assert mapped["repo_id"] is None
        assert mapped["name"] == "deploy-prod"
        assert mapped["result"] == "SUCCESS"
        assert mapped["status"] == "DONE"
        # started_date and finished_date must be ISO strings
        assert mapped["started_date"] is not None
        assert "T" in mapped["started_date"]
        assert mapped["finished_date"] is not None
        # finished must be after started
        started = datetime.fromisoformat(mapped["started_date"])
        finished = datetime.fromisoformat(mapped["finished_date"])
        assert finished > started

    def test_map_build_failure_result_preserved(self):
        connector, _ = _build_connector()
        build = _make_jenkins_build(number=10, result="FAILURE")

        mapped = connector._map_build("deploy-prod", build)

        assert mapped["result"] == "FAILURE"

    def test_map_build_zero_timestamp_produces_none_dates(self):
        """A build with timestamp=0 and duration=0 should not crash."""
        connector, _ = _build_connector()
        build = _make_jenkins_build(number=1, result="ABORTED", timestamp_ms=0, duration_ms=0)

        mapped = connector._map_build("deploy-prod", build)

        # started/finished are None when timestamp is 0 (falsy)
        assert mapped["started_date"] is None
        assert mapped["finished_date"] is None

    def test_map_build_uses_connection_id_in_id(self):
        jobs = [{"fullName": "deploy-prod"}]
        connector, _ = _build_connector(jobs=jobs, connection_id=7)
        build = _make_jenkins_build(number=3)

        mapped = connector._map_build("deploy-prod", build)

        assert "jenkins:JenkinsBuild:7:deploy-prod:3" == mapped["id"]

    # ------------------------------------------------------------------
    # 6. _detect_environment — heuristic and pattern-based
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "job_name,expected_env",
        [
            # Production keywords
            ("deploy-prod", "production"),
            ("release-prd", "production"),
            ("main-deploy", "production"),
            ("release/1.0", "production"),
            # Staging keywords
            ("deploy-staging", "staging"),
            ("deploy-stg-api", "staging"),
            ("homolog-service", "staging"),
            ("hml-deploy", "staging"),
            # Development keywords
            ("build-develop", "development"),
            ("dev-pipeline", "development"),
            ("feature-build", "development"),
            # Test/QA keywords
            ("qa-pipeline", "test"),
            ("run-quality-checks", "test"),
            ("test-suite", "test"),
            # Default: unconfigured job name defaults to production
            ("unknown-job", "production"),
        ],
    )
    def test_detect_environment_heuristics(self, job_name: str, expected_env: str):
        connector, _ = _build_connector()

        env = connector._detect_environment(job_name)

        assert env == expected_env, f"Job '{job_name}': expected '{expected_env}', got '{env}'"

    def test_detect_environment_uses_production_pattern_when_configured(self):
        """Explicit productionPattern in job config overrides heuristics."""
        jobs = [
            {
                "fullName": "ci/webmotors-api",
                "productionPattern": r"webmotors",
            }
        ]
        connector, _ = _build_connector(jobs=jobs)

        env = connector._detect_environment("ci/webmotors-api")

        assert env == "production"

    def test_detect_environment_falls_back_to_heuristics_when_pattern_misses(self):
        """Pattern that does NOT match the job name falls through to heuristics."""
        jobs = [
            {
                "fullName": "ci/qa-suite",
                "productionPattern": r"^PROD-",  # won't match "ci/qa-suite"
            }
        ]
        connector, _ = _build_connector(jobs=jobs)

        env = connector._detect_environment("ci/qa-suite")

        # heuristic: "qa" -> "test"
        assert env == "test"

    # ------------------------------------------------------------------
    # 7. source_type
    # ------------------------------------------------------------------

    def test_source_type_is_jenkins(self):
        connector, _ = _build_connector()

        assert connector.source_type == "jenkins"

    # ------------------------------------------------------------------
    # 8. fetch_pull_requests — returns empty (not_supported)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_returns_empty_list(self):
        connector, _ = _build_connector()

        result = await connector.fetch_pull_requests()

        assert result == []

    # ------------------------------------------------------------------
    # 9. fetch_issues — returns empty (not_supported)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_issues_returns_empty_list(self):
        connector, _ = _build_connector()

        result = await connector.fetch_issues()

        assert result == []

    # ------------------------------------------------------------------
    # 10. close
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_close_delegates_to_http_client(self):
        connector, mock_client = _build_connector()

        await connector.close()

        mock_client.close.assert_awaited_once()

    # ------------------------------------------------------------------
    # Constructor — missing credentials raise early
    # ------------------------------------------------------------------

    def test_constructor_raises_without_base_url(self):
        with patch("src.connectors.jenkins_connector.settings") as mock_settings:
            mock_settings.jenkins_base_url = ""
            mock_settings.jenkins_username = ""
            mock_settings.jenkins_api_token = "tok"

            with pytest.raises(ValueError, match="JENKINS_BASE_URL"):
                JenkinsConnector(base_url=None, api_token="tok")

    def test_constructor_raises_without_api_token(self):
        with patch("src.connectors.jenkins_connector.settings") as mock_settings:
            mock_settings.jenkins_base_url = "http://jenkins.test"
            mock_settings.jenkins_username = ""
            mock_settings.jenkins_api_token = ""

            with pytest.raises(ValueError, match="JENKINS_API_TOKEN"):
                JenkinsConnector(base_url="http://jenkins.test", api_token=None)

    # ------------------------------------------------------------------
    # Anti-surveillance guarantee
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_deployments_no_individual_rankings(self):
        """fetch_deployments must never contain ranking or score fields."""
        jobs = [{"fullName": "deploy-prod"}]
        connector, mock_client = _build_connector(jobs=jobs)
        build = _make_jenkins_build(number=1, result="SUCCESS")
        mock_client.get.return_value = {"builds": [build]}

        result = await connector.fetch_deployments()

        forbidden_keys = {"rank", "score", "leaderboard", "developer_rank", "ranking"}
        for dep in result:
            assert not forbidden_keys.intersection(dep.keys()), (
                f"Deployment record contains forbidden ranking key: {dep.keys()}"
            )

    # ------------------------------------------------------------------
    # Edge cases — builds list
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_deployments_empty_builds_list(self):
        jobs = [{"fullName": "deploy-prod"}]
        connector, mock_client = _build_connector(jobs=jobs)
        mock_client.get.return_value = {"builds": []}

        result = await connector.fetch_deployments()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_deployments_skips_jobs_without_fullname(self):
        """Job configs with no fullName key should be silently skipped."""
        jobs = [{"deploymentPattern": ".*"}]  # no fullName
        connector, mock_client = _build_connector(jobs=jobs)

        result = await connector.fetch_deployments()

        assert result == []
        mock_client.get.assert_not_called()
