"""Jenkins connector — fetches build/deployment data from Jenkins REST API.

Replaces DevLake's Jenkins plugin with direct API access.
Jenkins builds are mapped to DORA deployment metrics:
- Deployment Frequency = count of production builds per period
- Change Failure Rate = failed builds / total builds
- MTTR = time between failure and next success

Authentication: Basic auth (username + API token).

Job filtering: Uses config/connections.yaml to determine which jobs are
production deployments vs CI builds. Each job can specify:
- deploymentPattern: regex to match deployment jobs
- productionPattern: regex to match production environment
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from src.config import settings
from src.connectors.base import BaseConnector
from src.shared.http_client import ResilientHTTPClient

logger = logging.getLogger(__name__)

# Jenkins API tree parameter to minimize response size
JOB_TREE = "jobs[name,url,fullName,color]"
BUILD_TREE = "builds[number,result,timestamp,duration,url,displayName]{0,100}"


class JenkinsConnector(BaseConnector):
    """Fetches build data from Jenkins REST API.

    Configuration (from settings):
        - jenkins_base_url: Jenkins instance URL
        - jenkins_username: Service account username
        - jenkins_api_token: Jenkins API token

    Job configuration is loaded from connections.yaml via the `jobs` parameter.
    Each job dict should have:
        - fullName: Jenkins job path (e.g., "folder/job-name")
        - deploymentPattern: regex for matching deployment builds (optional)
        - productionPattern: regex for production environment (optional)
    """

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        api_token: str | None = None,
        jobs: list[dict[str, str]] | None = None,
        job_to_repo: dict[str, str] | None = None,
        connection_id: int = 1,
    ) -> None:
        self._base_url = (base_url or settings.jenkins_base_url).rstrip("/")
        self._username = username or settings.jenkins_username
        self._api_token = api_token or settings.jenkins_api_token
        self._connection_id = connection_id

        # Job configs from connections.yaml
        self._jobs = jobs or []

        # Reverse map: Jenkins job fullName → GitHub repo short name
        # Used to populate eng_deployments.repo with the actual repo name
        self._job_to_repo = job_to_repo or {}

        if not self._base_url or not self._api_token:
            raise ValueError(
                "Jenkins connector requires JENKINS_BASE_URL and JENKINS_API_TOKEN. "
                "Set them in environment variables or .env file."
            )

        self._client = ResilientHTTPClient(
            base_url=self._base_url,
            auth={"basic": (self._username, self._api_token)},
            timeout=30.0,
            max_retries=3,
        )

        # Pre-compile deployment/production patterns
        self._job_patterns: dict[str, dict[str, re.Pattern | None]] = {}
        for job in self._jobs:
            name = job.get("fullName", "")
            deploy_pat = job.get("deploymentPattern")
            prod_pat = job.get("productionPattern")
            self._job_patterns[name] = {
                "deployment": re.compile(deploy_pat) if deploy_pat else None,
                "production": re.compile(prod_pat) if prod_pat else None,
            }

    @property
    def source_type(self) -> str:
        return "jenkins"

    async def test_connection(self) -> dict[str, Any]:
        """Test Jenkins connectivity."""
        try:
            data = await self._client.get("/api/json", params={"tree": "nodeDescription,numExecutors"})
            return {
                "status": "healthy",
                "message": f"Connected to Jenkins ({data.get('nodeDescription', 'unknown')})",
                "details": {
                    "executors": data.get("numExecutors", 0),
                    "configured_jobs": len(self._jobs),
                },
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # Deployments (Jenkins builds → DORA deployment metrics)
    # ------------------------------------------------------------------

    async def fetch_deployments(
        self,
        since: datetime | None = None,
        since_by_repo: dict[str, datetime | None] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch builds from configured Jenkins jobs.

        Each build is mapped to a deployment record. Only jobs configured
        in connections.yaml are fetched (not all Jenkins jobs).

        FDD-OPS-014 step 2.5-B: per-repo `since` resolution. Jenkins has
        no native "repo" concept — we use the job→repo mapping (built
        from SCM scan, see `discover_jenkins_jobs.py`) to map each job
        to its source repo and look up the repo's watermark.

        Resolution order per job:
          1. since_by_repo[mapped_repo] (if mapped_repo in dict)
          2. fall back to bulk `since` (single-watermark behavior)

        Backwards compat: if since_by_repo is None, all jobs use
        single `since` (legacy bulk behavior preserved).
        """
        if not self._jobs:
            logger.warning("No Jenkins jobs configured — skipping deployment fetch")
            return []

        # Pre-flight: log per-repo plan when since_by_repo is provided.
        if since_by_repo is not None:
            jobs_with_scope = sum(
                1 for j in self._jobs
                if self._job_to_repo.get(j.get("fullName", ""), "") in since_by_repo
            )
            logger.info(
                "Jenkins fetch: %d jobs total, %d jobs with per-repo watermark, "
                "rest use bulk since=%s",
                len(self._jobs), jobs_with_scope, since,
            )

        all_builds: list[dict[str, Any]] = []

        for job_config in self._jobs:
            job_name = job_config.get("fullName", "")
            if not job_name:
                continue

            # Resolve per-repo since via job→repo mapping.
            repo = self._job_to_repo.get(job_name, job_name)
            if since_by_repo is not None and repo in since_by_repo:
                job_since = since_by_repo[repo]
            else:
                job_since = since

            try:
                builds = await self._fetch_job_builds(job_name, job_since)
                all_builds.extend(builds)
            except Exception:
                logger.exception("Failed to fetch builds for job: %s", job_name)

        logger.info(
            "Fetched %d builds from %d Jenkins jobs",
            len(all_builds), len(self._jobs),
        )
        return all_builds

    # ------------------------------------------------------------------
    # Not applicable for Jenkins
    # ------------------------------------------------------------------

    async def fetch_pull_requests(self, since: datetime | None = None) -> list[dict[str, Any]]:
        return await self._not_supported("pull_requests")

    async def fetch_issues(self, since: datetime | None = None) -> list[dict[str, Any]]:
        return await self._not_supported("issues")

    async def fetch_issue_changelogs(self, issue_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return {}

    async def fetch_sprints(self, since: datetime | None = None) -> list[dict[str, Any]]:
        return await self._not_supported("sprints")

    async def fetch_sprint_issues(self, sprint_id: str) -> list[dict[str, Any]]:
        return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.close()
        logger.info("Jenkins connector closed")

    # ------------------------------------------------------------------
    # Internal: Fetch and map builds
    # ------------------------------------------------------------------

    async def count_builds_for_job(
        self,
        job_name: str,
        since: datetime | None = None,
        timeout_seconds: float = 10.0,
    ) -> int | None:
        """FDD-OPS-015 — pre-flight estimate of builds in a Jenkins job.

        Uses the same `BUILD_TREE` query but extracts only the count. The
        Jenkins tree spec `builds[number,timestamp]{0,100}` returns at most
        100 most recent builds — for jobs that build infrequently this
        captures everything; for high-frequency jobs we return 100 as
        floor (worker treats this as a lower-bound estimate).

        When `since` is provided, filters builds whose timestamp >= since.
        Cheaper than fetching full build details (no result/duration).

        Returns:
            Build count (possibly capped at 100), or None on failure/timeout.
        """
        api_path = f"/job/{job_name.replace('/', '/job/')}/api/json"
        # Lighter tree than BUILD_TREE — only number + timestamp for filtering.
        params = {"tree": "builds[number,timestamp]{0,100}"}

        try:
            import asyncio
            data = await asyncio.wait_for(
                self._client.get(api_path, params=params),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[count] %s: Jenkins builds list exceeded %.1fs — None",
                job_name, timeout_seconds,
            )
            return None
        except Exception:
            logger.exception(
                "[count] %s: Jenkins builds list failed — None", job_name,
            )
            return None

        builds = data.get("builds") or []
        if not since:
            logger.info(
                "[count] %s: %d builds (capped at 100 most recent)",
                job_name, len(builds),
            )
            return len(builds)

        # Filter by timestamp client-side (Jenkins doesn't filter natively).
        since_ms = int(since.timestamp() * 1000)
        filtered = [b for b in builds if (b.get("timestamp") or 0) >= since_ms]
        logger.info(
            "[count] %s: %d builds since %s (of %d returned)",
            job_name, len(filtered), since.isoformat(), len(builds),
        )
        return len(filtered)

    async def _fetch_job_builds(
        self, job_name: str, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch builds for a specific Jenkins job."""
        # Jenkins API path: encode slashes in folder names
        api_path = f"/job/{job_name.replace('/', '/job/')}/api/json"
        params = {"tree": BUILD_TREE}

        data = await self._client.get(api_path, params=params)
        builds = data.get("builds", [])

        mapped_builds: list[dict[str, Any]] = []
        for build in builds:
            # Skip builds without a result (still running)
            if not build.get("result"):
                continue

            mapped = self._map_build(job_name, build)

            # Apply watermark filter
            if since and mapped.get("finished_date"):
                finished = mapped["finished_date"]
                if isinstance(finished, str):
                    try:
                        dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                        if dt < since:
                            continue
                    except ValueError:
                        pass

            mapped_builds.append(mapped)

        logger.debug("Fetched %d builds for job %s", len(mapped_builds), job_name)
        return mapped_builds

    def _map_build(self, job_name: str, build: dict[str, Any]) -> dict[str, Any]:
        """Map a Jenkins build to the normalizer-expected deployment format.

        Preserves the same dict keys that DevLake's cicd_deployment_commits
        domain table had, so the normalizer works unchanged.
        """
        result = str(build.get("result", "UNKNOWN")).upper()
        timestamp_ms = build.get("timestamp", 0)
        duration_ms = build.get("duration", 0)
        build_number = build.get("number", 0)

        started = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc) if timestamp_ms else None
        finished = (
            datetime.fromtimestamp((timestamp_ms + duration_ms) / 1000, tz=timezone.utc)
            if timestamp_ms and duration_ms
            else started
        )

        environment = self._detect_environment(job_name, build)

        # Resolve GitHub repo name from job→repo mapping
        repo_name = self._job_to_repo.get(job_name, job_name)

        # INC-024 — surface the Jenkins build URL so the UI can deep-link from
        # deploy rows / Pipeline Monitor cells back to the source build page.
        # Jenkins exposes `url` per build (we already fetch it via BUILD_TREE).
        build_url = build.get("url") if isinstance(build, dict) else None

        return {
            "id": f"jenkins:JenkinsBuild:{self._connection_id}:{job_name}:{build_number}",
            "cicd_deployment_id": f"jenkins:JenkinsJob:{self._connection_id}:{job_name}",
            "repo_id": None,
            "name": job_name,
            "repo_name": repo_name,  # GitHub repo name (resolved from mapping)
            "result": result,  # SUCCESS, FAILURE, UNSTABLE, ABORTED, NOT_BUILT
            "status": "DONE",
            "environment": environment,
            "url": build_url,  # INC-024 — Jenkins build deep-link
            "created_date": started.isoformat() if started else None,
            "started_date": started.isoformat() if started else None,
            "finished_date": finished.isoformat() if finished else None,
        }

    def _detect_environment(
        self, job_name: str, build: dict[str, Any] | None = None,
    ) -> str:
        """Detect the deployment environment for a Jenkins job.

        Uses patterns from connections.yaml if available.
        Falls back to heuristic name matching.
        """
        patterns = self._job_patterns.get(job_name, {})

        # Check production pattern first
        prod_pattern = patterns.get("production")
        if prod_pattern:
            if prod_pattern.search(job_name):
                return "production"

        # Heuristic: job name contains environment indicators
        name_lower = job_name.lower()
        if any(kw in name_lower for kw in ("prod", "prd", "release", "deploy-prod", "main-deploy")):
            return "production"
        if any(kw in name_lower for kw in ("staging", "stg", "homolog", "hml")):
            return "staging"
        if any(kw in name_lower for kw in ("dev", "develop", "feature")):
            return "development"
        if any(kw in name_lower for kw in ("test", "qa", "quality")):
            return "test"

        # Default: if it's in our configured jobs list, treat as production
        # (connections.yaml should only contain production-relevant jobs)
        return "production"

    # ------------------------------------------------------------------
    # Job discovery (for initial setup / configuration)
    # ------------------------------------------------------------------

    async def discover_jobs(self, folder: str | None = None) -> list[dict[str, str]]:
        """Discover all Jenkins jobs. Useful for initial configuration.

        Args:
            folder: Optional folder path to scope discovery.

        Returns:
            List of dicts with job info (fullName, url, color).
        """
        path = "/api/json"
        if folder:
            path = f"/job/{folder.replace('/', '/job/')}/api/json"

        data = await self._client.get(path, params={"tree": JOB_TREE})
        jobs = data.get("jobs", [])

        discovered: list[dict[str, str]] = []
        for job in jobs:
            discovered.append({
                "fullName": job.get("fullName", job.get("name", "")),
                "url": job.get("url", ""),
                "color": job.get("color", ""),
            })

        logger.info("Discovered %d Jenkins jobs", len(discovered))
        return discovered
