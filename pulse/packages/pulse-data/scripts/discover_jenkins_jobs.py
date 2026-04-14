#!/usr/bin/env python3
"""Jenkins Job Discovery & Auto-Mapping Script (READ-ONLY).

Fetches ALL Jenkins jobs, classifies them by environment, and attempts
to match each job to a GitHub repo using multiple heuristic strategies.

Output: A confidence-scored report for human review. Nothing is changed.

Usage (from pulse/ root):
    docker compose exec sync-worker python -m src.scripts.discover_jenkins_jobs

Or locally:
    cd packages/pulse-data && python scripts/discover_jenkins_jobs.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Setup: ensure we can import from src/
# ---------------------------------------------------------------------------
_script_dir = Path(__file__).resolve().parent
_pkg_root = _script_dir.parent  # packages/pulse-data/
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from src.config import settings
from src.shared.http_client import ResilientHTTPClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("jenkins-discovery")


# ---------------------------------------------------------------------------
# Constants: Environment classification patterns
# ---------------------------------------------------------------------------

# Patterns that indicate environment — ORDER MATTERS (first match wins)
ENV_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("production", re.compile(r"(?i)(?:^|[-_./])(?:prd|prod|production)(?:[-_./]|$)")),
    ("staging",    re.compile(r"(?i)(?:^|[-_./])(?:stg|staging|azl|azul|blue)(?:[-_./]|$)")),
    ("homolog",    re.compile(r"(?i)(?:^|[-_./])(?:hml|homolog|homologacao|uat)(?:[-_./]|$)")),
    ("dev",        re.compile(r"(?i)(?:^|[-_./])(?:dev|develop|development|sandbox)(?:[-_./]|$)")),
    ("test",       re.compile(r"(?i)(?:^|[-_./])(?:test|qa|quality)(?:[-_./]|$)")),
]

# Suffixes/prefixes to strip when extracting the "core" job name
ENV_STRIP_PATTERNS = re.compile(
    r"(?i)"
    r"(?:^(?:prd|prod|hml|azl|stg|dev|test|qa)-)|"   # prefix: prd-xxx
    r"(?:-(?:prd|prod|hml|azl|stg|dev|test|qa)$)|"    # suffix: xxx-prd
    r"(?:-rollback$)|"                                  # rollback variants
    r"(?:-nodejs\d+$)|"                                 # runtime variants
    r"(?:-firebase$|-playstore$|-testflight$)"          # distribution channel
)

# Additional noise to strip from job names for matching
NOISE_STRIP = re.compile(
    r"(?i)"
    r"(?:^wm-|^webmotors-)|"     # org prefix
    r"(?:-ui$|-api$|-bff$|-web$|-lambda$)|"  # type suffix (keep for matching)
    r"(?:^build-)|"               # build prefix
    r"(?:-all-platforms$)"        # multi-platform suffix
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class JenkinsJob:
    """A discovered Jenkins job with classification metadata."""
    full_name: str
    url: str
    color: str  # Jenkins color = last build status
    environment: str = "unknown"
    core_name: str = ""  # Normalized name for matching
    matched_repo: str | None = None
    match_confidence: float = 0.0
    match_strategy: str = ""
    is_disabled: bool = False

    def __post_init__(self):
        self.is_disabled = self.color in ("disabled", "disabled_anime")
        self.environment = self._classify_environment()
        self.core_name = self._extract_core_name()

    def _classify_environment(self) -> str:
        for env_name, pattern in ENV_PATTERNS:
            if pattern.search(self.full_name):
                return env_name
        return "unknown"

    def _extract_core_name(self) -> str:
        """Strip environment prefixes/suffixes to get the 'core' job identity."""
        name = self.full_name
        # Iterative stripping (some jobs have multiple patterns)
        for _ in range(3):
            stripped = ENV_STRIP_PATTERNS.sub("", name)
            if stripped == name:
                break
            name = stripped.strip("-_")
        return name.lower()


@dataclass
class MatchResult:
    """A potential job→repo match with confidence scoring."""
    job_name: str
    repo_name: str
    confidence: float  # 0.0 - 1.0
    strategy: str      # Which matching strategy found this
    details: str = ""  # Human-readable explanation


# ---------------------------------------------------------------------------
# Matching strategies (ordered by confidence)
# ---------------------------------------------------------------------------

def strategy_exact_name(core_name: str, repos: dict[str, str]) -> MatchResult | None:
    """Strategy 1: Exact match of core name to repo name."""
    # Try direct match
    for repo_short, repo_full in repos.items():
        repo_lower = repo_short.lower()
        if core_name == repo_lower:
            return MatchResult(
                job_name=core_name, repo_name=repo_full,
                confidence=0.95, strategy="exact_name",
                details=f"Core name '{core_name}' == repo '{repo_short}'"
            )
    return None


def strategy_contains_repo(core_name: str, repos: dict[str, str]) -> MatchResult | None:
    """Strategy 2: Core name contains the full repo name (or vice versa)."""
    # Normalize: replace dots and hyphens for comparison
    cn_normalized = core_name.replace(".", "-").replace("_", "-")

    best: MatchResult | None = None
    for repo_short, repo_full in repos.items():
        rn_normalized = repo_short.lower().replace(".", "-").replace("_", "-")

        if cn_normalized == rn_normalized:
            return MatchResult(
                job_name=core_name, repo_name=repo_full,
                confidence=0.93, strategy="normalized_exact",
                details=f"Normalized '{cn_normalized}' == '{rn_normalized}'"
            )

        # Core contains repo or repo contains core
        if len(rn_normalized) >= 5 and rn_normalized in cn_normalized:
            score = len(rn_normalized) / len(cn_normalized)
            if not best or score > best.confidence:
                best = MatchResult(
                    job_name=core_name, repo_name=repo_full,
                    confidence=min(0.85, 0.5 + score * 0.4), strategy="contains",
                    details=f"Repo '{rn_normalized}' found in job '{cn_normalized}' (coverage={score:.0%})"
                )

        if len(cn_normalized) >= 5 and cn_normalized in rn_normalized:
            score = len(cn_normalized) / len(rn_normalized)
            if not best or score > best.confidence:
                best = MatchResult(
                    job_name=core_name, repo_name=repo_full,
                    confidence=min(0.80, 0.5 + score * 0.3), strategy="contained_in",
                    details=f"Job '{cn_normalized}' found in repo '{rn_normalized}' (coverage={score:.0%})"
                )

    return best


def strategy_token_overlap(core_name: str, repos: dict[str, str]) -> MatchResult | None:
    """Strategy 3: Token-based overlap (split by -, ., _ and compare)."""
    job_tokens = set(re.split(r"[-._]", core_name.lower()))
    job_tokens -= {"wm", "webmotors", "lambda", "frontend", "backend", "ui", "api",
                    "web", "app", "prd", "hml", "azl", "dev", "test", "check", "sonar",
                    "coverage", "build", "rollback", "private"}

    if len(job_tokens) < 2:
        return None

    best: MatchResult | None = None
    for repo_short, repo_full in repos.items():
        repo_tokens = set(re.split(r"[-._]", repo_short.lower()))
        repo_tokens -= {"webmotors", "private", "ui", "api"}

        if not repo_tokens:
            continue

        overlap = job_tokens & repo_tokens
        if len(overlap) >= 2:
            # Jaccard similarity
            jaccard = len(overlap) / len(job_tokens | repo_tokens)
            confidence = min(0.75, 0.3 + jaccard * 0.5)
            if not best or confidence > best.confidence:
                best = MatchResult(
                    job_name=core_name, repo_name=repo_full,
                    confidence=confidence, strategy="token_overlap",
                    details=f"Shared tokens: {overlap} (jaccard={jaccard:.2f})"
                )

    return best


def strategy_sequence_match(core_name: str, repos: dict[str, str]) -> MatchResult | None:
    """Strategy 4: SequenceMatcher ratio (fuzzy string similarity)."""
    cn_clean = core_name.replace("-", "").replace("_", "").replace(".", "")

    best: MatchResult | None = None
    for repo_short, repo_full in repos.items():
        rn_clean = repo_short.lower().replace("-", "").replace("_", "").replace(".", "")
        ratio = SequenceMatcher(None, cn_clean, rn_clean).ratio()

        if ratio >= 0.65:
            confidence = min(0.70, ratio * 0.8)
            if not best or confidence > best.confidence:
                best = MatchResult(
                    job_name=core_name, repo_name=repo_full,
                    confidence=confidence, strategy="sequence_match",
                    details=f"SequenceMatcher ratio={ratio:.2f} between '{cn_clean}' and '{rn_clean}'"
                )

    return best


STRATEGIES = [
    strategy_exact_name,
    strategy_contains_repo,
    strategy_token_overlap,
    strategy_sequence_match,
]


# ---------------------------------------------------------------------------
# Main discovery logic
# ---------------------------------------------------------------------------

async def fetch_all_jenkins_jobs() -> list[dict[str, str]]:
    """Fetch ALL jobs from Jenkins API (READ-ONLY)."""
    client = ResilientHTTPClient(
        base_url=settings.jenkins_base_url.rstrip("/"),
        auth={"basic": (settings.jenkins_username, settings.jenkins_api_token)},
        timeout=60.0,
        max_retries=3,
    )

    try:
        # Fetch with recursive depth to get jobs inside folders
        # tree=jobs[name,url,fullName,color,jobs[name,url,fullName,color,...]] (3 levels deep)
        tree = (
            "jobs[name,url,fullName,color,"
            "jobs[name,url,fullName,color,"
            "jobs[name,url,fullName,color]]]"
        )
        data = await client.get("/api/json", params={"tree": tree})

        def _flatten_jobs(jobs_list: list[dict], results: list[dict]):
            for job in jobs_list:
                if "fullName" in job or "name" in job:
                    # Only add leaf nodes (jobs without sub-jobs or with sub-jobs + own builds)
                    sub_jobs = job.get("jobs", [])
                    if not sub_jobs:
                        results.append({
                            "fullName": job.get("fullName", job.get("name", "")),
                            "url": job.get("url", ""),
                            "color": job.get("color", ""),
                        })
                    else:
                        # This is a folder — recurse
                        _flatten_jobs(sub_jobs, results)

        all_jobs: list[dict[str, str]] = []
        _flatten_jobs(data.get("jobs", []), all_jobs)

        logger.info("Fetched %d Jenkins jobs (READ-ONLY)", len(all_jobs))
        return all_jobs

    finally:
        await client.close()


async def fetch_github_repos_from_db() -> dict[str, str]:
    """Get all unique repo names from our PR database.

    Returns dict: {repo_short_name: repo_full_name}
    """
    # We'll use psql via subprocess since we don't have async DB here
    import subprocess
    result = subprocess.run(
        [
            "psql", "-h", "postgres", "-U", "pulse", "-d", "pulse",
            "-tA", "-c",
            "SET app.current_tenant='00000000-0000-0000-0000-000000000001'; "
            "SELECT DISTINCT repo FROM eng_pull_requests WHERE repo IS NOT NULL;",
        ],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PGPASSWORD": "pulse_dev"},
    )

    repos: dict[str, str] = {}
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # repo_full = "webmotors-private/webmotors.next.ui"
        # repo_short = "webmotors.next.ui"
        short = line.split("/", 1)[-1] if "/" in line else line
        repos[short] = line

    logger.info("Found %d GitHub repos in PR database", len(repos))
    return repos


def match_jobs_to_repos(
    jobs: list[JenkinsJob],
    repos: dict[str, str],
) -> list[JenkinsJob]:
    """Apply all matching strategies to each job."""
    for job in jobs:
        if job.is_disabled:
            continue

        # Try each strategy in order (highest confidence first)
        for strategy_fn in STRATEGIES:
            result = strategy_fn(job.core_name, repos)
            if result and result.confidence > job.match_confidence:
                job.matched_repo = result.repo_name
                job.match_confidence = result.confidence
                job.match_strategy = f"{result.strategy}: {result.details}"

    return jobs


def generate_report(jobs: list[JenkinsJob], repos: dict[str, str]) -> str:
    """Generate human-readable report of discovery results."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("JENKINS JOB DISCOVERY REPORT (READ-ONLY)")
    lines.append("=" * 80)
    lines.append("")

    # --- Summary ---
    total = len(jobs)
    by_env = defaultdict(int)
    by_env_matched = defaultdict(int)
    disabled = sum(1 for j in jobs if j.is_disabled)
    matched = sum(1 for j in jobs if j.matched_repo and not j.is_disabled)
    unmatched = total - matched - disabled

    for j in jobs:
        if not j.is_disabled:
            by_env[j.environment] += 1
            if j.matched_repo:
                by_env_matched[j.environment] += 1

    lines.append(f"Total Jenkins jobs:  {total}")
    lines.append(f"  Disabled:          {disabled}")
    lines.append(f"  Active:            {total - disabled}")
    lines.append(f"  Matched to repo:   {matched} ({matched/(total-disabled)*100:.1f}%)" if total > disabled else "")
    lines.append(f"  Unmatched:         {unmatched}")
    lines.append(f"  GitHub repos (DB): {len(repos)}")
    lines.append("")

    lines.append("--- By Environment ---")
    for env in ["production", "staging", "homolog", "dev", "test", "unknown"]:
        c = by_env.get(env, 0)
        m = by_env_matched.get(env, 0)
        if c > 0:
            lines.append(f"  {env:12s}: {c:4d} jobs, {m:4d} matched ({m/c*100:.0f}%)")
    lines.append("")

    # --- Production jobs (what matters for DORA) ---
    prd_jobs = [j for j in jobs if j.environment == "production" and not j.is_disabled]
    prd_matched = [j for j in prd_jobs if j.matched_repo]
    prd_unmatched = [j for j in prd_jobs if not j.matched_repo]

    lines.append("=" * 80)
    lines.append(f"PRODUCTION JOBS — MATCHED ({len(prd_matched)})")
    lines.append("=" * 80)
    lines.append("")

    # Group by repo
    by_repo: dict[str, list[JenkinsJob]] = defaultdict(list)
    for j in prd_matched:
        by_repo[j.matched_repo or ""].append(j)

    for repo in sorted(by_repo.keys()):
        repo_jobs = by_repo[repo]
        lines.append(f"  {repo}")
        for j in sorted(repo_jobs, key=lambda x: -x.match_confidence):
            conf_bar = "█" * int(j.match_confidence * 10) + "░" * (10 - int(j.match_confidence * 10))
            lines.append(f"    [{conf_bar}] {j.match_confidence:.0%}  {j.full_name}")
            lines.append(f"              └─ {j.match_strategy}")
        lines.append("")

    if prd_unmatched:
        lines.append("=" * 80)
        lines.append(f"PRODUCTION JOBS — UNMATCHED ({len(prd_unmatched)})")
        lines.append("=" * 80)
        lines.append("")
        for j in sorted(prd_unmatched, key=lambda x: x.full_name):
            lines.append(f"    {j.full_name}  (core: {j.core_name})")
        lines.append("")

    # --- Confidence distribution ---
    lines.append("=" * 80)
    lines.append("CONFIDENCE DISTRIBUTION (all matched, active jobs)")
    lines.append("=" * 80)
    lines.append("")
    conf_buckets = defaultdict(int)
    for j in jobs:
        if j.matched_repo and not j.is_disabled:
            bucket = int(j.match_confidence * 10) * 10
            conf_buckets[bucket] += 1

    for bucket in sorted(conf_buckets.keys(), reverse=True):
        count = conf_buckets[bucket]
        bar = "█" * (count // 2)
        lines.append(f"  {bucket:3d}-{bucket+9}%: {count:4d} {bar}")
    lines.append("")

    # --- Proposed new connections.yaml entries (PRD only, confidence >= 0.80) ---
    high_conf_prd = [
        j for j in prd_matched
        if j.match_confidence >= 0.80
        and j.full_name not in _current_configured_jobs()
    ]

    lines.append("=" * 80)
    lines.append(f"PROPOSED NEW PRD JOBS (confidence ≥ 80%, not already configured): {len(high_conf_prd)}")
    lines.append("=" * 80)
    lines.append("")

    new_by_repo: dict[str, list[JenkinsJob]] = defaultdict(list)
    for j in high_conf_prd:
        new_by_repo[j.matched_repo or ""].append(j)

    for repo in sorted(new_by_repo.keys()):
        repo_short = repo.split("/", 1)[-1] if "/" in repo else repo
        lines.append(f"  # ── {repo_short} ──")
        for j in sorted(new_by_repo[repo], key=lambda x: x.full_name):
            lines.append(f'  - fullName: "{j.full_name}"')
            lines.append(f'    # confidence: {j.match_confidence:.0%} | {j.match_strategy}')
        lines.append("")

    # --- Low confidence matches that need human review ---
    low_conf = [
        j for j in jobs
        if j.matched_repo and not j.is_disabled
        and j.environment == "production"
        and 0.50 <= j.match_confidence < 0.80
    ]

    if low_conf:
        lines.append("=" * 80)
        lines.append(f"⚠️  LOW CONFIDENCE PRD MATCHES (50-79%) — NEEDS HUMAN REVIEW: {len(low_conf)}")
        lines.append("=" * 80)
        lines.append("")
        for j in sorted(low_conf, key=lambda x: -x.match_confidence):
            lines.append(f"  {j.full_name}")
            lines.append(f"    → {j.matched_repo} ({j.match_confidence:.0%})")
            lines.append(f"      {j.match_strategy}")
            lines.append("")

    # --- JSON output for programmatic use ---
    json_output = {
        "summary": {
            "total_jobs": total,
            "disabled": disabled,
            "active": total - disabled,
            "matched": matched,
            "unmatched": unmatched,
            "by_environment": dict(by_env),
        },
        "proposed_new_prd_jobs": [
            {
                "fullName": j.full_name,
                "repo": j.matched_repo,
                "confidence": j.match_confidence,
                "strategy": j.match_strategy,
            }
            for j in high_conf_prd
        ],
        "low_confidence_review": [
            {
                "fullName": j.full_name,
                "repo": j.matched_repo,
                "confidence": j.match_confidence,
                "strategy": j.match_strategy,
            }
            for j in low_conf
        ],
        "all_prd_unmatched": [j.full_name for j in prd_unmatched],
    }

    # Save JSON alongside report
    json_path = _script_dir / "jenkins-discovery-result.json"
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
    lines.append(f"\n📄 JSON output saved to: {json_path}")

    return "\n".join(lines)


def _current_configured_jobs() -> set[str]:
    """Get set of currently configured job fullNames from connections.yaml."""
    from src.config import _load_connections_yaml, _extract_jenkins_jobs
    conns = _load_connections_yaml()
    jobs = _extract_jenkins_jobs(conns)
    return {j.get("fullName", "") for j in jobs}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    logger.info("Starting Jenkins job discovery (READ-ONLY)...")
    logger.info("Jenkins URL: %s", settings.jenkins_base_url)

    # 1. Fetch all Jenkins jobs
    raw_jobs = await fetch_all_jenkins_jobs()

    # 2. Classify jobs
    jobs = [
        JenkinsJob(
            full_name=j["fullName"],
            url=j["url"],
            color=j["color"],
        )
        for j in raw_jobs
        if j.get("fullName")  # Skip empty names
    ]

    logger.info(
        "Classified %d jobs: %d production, %d staging, %d homolog, %d dev, %d test, %d unknown",
        len(jobs),
        sum(1 for j in jobs if j.environment == "production"),
        sum(1 for j in jobs if j.environment == "staging"),
        sum(1 for j in jobs if j.environment == "homolog"),
        sum(1 for j in jobs if j.environment == "dev"),
        sum(1 for j in jobs if j.environment == "test"),
        sum(1 for j in jobs if j.environment == "unknown"),
    )

    # 3. Fetch GitHub repos from DB
    repos = await fetch_github_repos_from_db()

    # 4. Match jobs to repos
    jobs = match_jobs_to_repos(jobs, repos)

    # 5. Generate report
    report = generate_report(jobs, repos)
    print(report)

    # 6. Also save full report to file
    report_path = _script_dir / "jenkins-discovery-report.txt"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info("Full report saved to: %s", report_path)


if __name__ == "__main__":
    asyncio.run(main())
