#!/usr/bin/env python3
"""PULSE Full Ingestion Script.

Orchestrates a complete data ingestion from all configured sources
(GitHub, Jira, Jenkins) through DevLake into the PULSE database.

Key features:
- Resumable: DevLake pipelines checkpoint internally; PULSE watermarks
  are stored in PostgreSQL. Safe to stop and restart.
- Idempotent: ON CONFLICT upserts guarantee no duplicates.
- Observable: Logs progress, record counts, and errors in real time.

Usage:
    # From pulse/ directory:
    python scripts/full_ingestion.py

    # Or with options:
    python scripts/full_ingestion.py --skip-devlake    # Only sync PULSE (DevLake already has data)
    python scripts/full_ingestion.py --reset-watermarks # Force full re-sync from DevLake to PULSE
    python scripts/full_ingestion.py --blueprint-id 1   # Trigger specific blueprint only
    python scripts/full_ingestion.py --dry-run           # Show what would happen
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import asyncpg

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("full_ingestion")

# ── Configuration ────────────────────────────────────────────────────────────

# DevLake API — the Gin server runs on 8080 inside the container,
# mapped to 8080 externally. The basePath is "/" (not "/api/").
DEVLAKE_API = os.environ.get("DEVLAKE_API_URL", "http://localhost:8080")

# DevLake PostgreSQL (read-only)
DEVLAKE_DB = os.environ.get(
    "DEVLAKE_DB_URL",
    "postgresql://devlake:devlake_dev@localhost:5433/lake",
)

# PULSE PostgreSQL
PULSE_DB = os.environ.get(
    "DATABASE_URL",
    "postgresql://pulse:pulse_dev@localhost:5432/pulse",
)

TENANT_ID = os.environ.get(
    "DEFAULT_TENANT_ID",
    "00000000-0000-0000-0000-000000000001",
)

# Poll interval for DevLake pipeline status (seconds)
POLL_INTERVAL = 30

# Maximum retries for a failed DevLake pipeline
MAX_RETRIES = 3

# ── ANSI Colors ──────────────────────────────────────────────────────────────

class C:
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def banner(msg: str) -> None:
    log.info(f"{C.BOLD}{C.CYAN}{'─' * 60}{C.RESET}")
    log.info(f"{C.BOLD}{C.CYAN}  {msg}{C.RESET}")
    log.info(f"{C.BOLD}{C.CYAN}{'─' * 60}{C.RESET}")


def ok(msg: str) -> None:
    log.info(f"{C.GREEN}  ✓ {msg}{C.RESET}")


def warn(msg: str) -> None:
    log.warning(f"{C.YELLOW}  ⚠ {msg}{C.RESET}")


def fail(msg: str) -> None:
    log.error(f"{C.RED}  ✗ {msg}{C.RESET}")


def info(msg: str) -> None:
    log.info(f"  {msg}")


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — Health checks
# ═══════════════════════════════════════════════════════════════════════════


async def check_devlake_health(client: httpx.AsyncClient) -> bool:
    """Verify DevLake API is reachable and responding."""
    try:
        r = await client.get(f"{DEVLAKE_API}/ping", timeout=10)
        if r.status_code == 200:
            ok("DevLake API is healthy")
            return True
        # Try alternate path
        r = await client.get(f"{DEVLAKE_API}/health", timeout=10)
        if r.status_code == 200:
            ok("DevLake API is healthy")
            return True
    except Exception as e:
        fail(f"DevLake API unreachable: {e}")
    return False


async def check_devlake_db() -> bool:
    """Verify DevLake PostgreSQL is reachable."""
    try:
        conn = await asyncpg.connect(DEVLAKE_DB)
        result = await conn.fetchval("SELECT COUNT(*) FROM pull_requests")
        await conn.close()
        ok(f"DevLake DB is healthy — {result:,} pull_requests")
        return True
    except Exception as e:
        fail(f"DevLake DB unreachable: {e}")
        return False


async def check_pulse_db() -> bool:
    """Verify PULSE PostgreSQL is reachable."""
    try:
        conn = await asyncpg.connect(PULSE_DB)
        # Test with RLS context
        await conn.execute(f"SET app.current_tenant = '{TENANT_ID}'")
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM eng_pull_requests WHERE tenant_id = $1::uuid",
            TENANT_ID,
        )
        await conn.close()
        ok(f"PULSE DB is healthy — {result:,} eng_pull_requests")
        return True
    except Exception as e:
        fail(f"PULSE DB unreachable: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — Inventory: list what DevLake has configured
# ═══════════════════════════════════════════════════════════════════════════


async def get_inventory(client: httpx.AsyncClient) -> dict[str, Any]:
    """Fetch all connections, scopes, and blueprints from DevLake."""
    inventory: dict[str, Any] = {"connections": {}, "blueprints": []}

    for plugin, conn_id in [("github", 1), ("jira", 2), ("jenkins", 1)]:
        try:
            r = await client.get(f"{DEVLAKE_API}/plugins/{plugin}/connections/{conn_id}/scopes")
            if r.status_code == 200:
                data = r.json()
                scopes = data.get("scopes", data) if isinstance(data, dict) else data
                inventory["connections"][plugin] = {
                    "connectionId": conn_id,
                    "scopeCount": len(scopes) if isinstance(scopes, list) else data.get("count", 0),
                    "scopes": scopes if isinstance(scopes, list) else [],
                }
                ok(f"{plugin}: {inventory['connections'][plugin]['scopeCount']} scopes configured")
            else:
                warn(f"{plugin}: connection {conn_id} returned HTTP {r.status_code}")
        except Exception as e:
            warn(f"{plugin}: could not fetch scopes — {e}")

    try:
        r = await client.get(f"{DEVLAKE_API}/blueprints")
        if r.status_code == 200:
            data = r.json()
            bps = data.get("blueprints", data) if isinstance(data, dict) else data
            inventory["blueprints"] = bps if isinstance(bps, list) else []
            for bp in inventory["blueprints"]:
                status = "enabled" if bp.get("enable") else "disabled"
                ok(f"Blueprint #{bp['id']}: {bp['name']} ({status}, cron: {bp.get('cronConfig', 'manual')})")
    except Exception as e:
        warn(f"Could not fetch blueprints: {e}")

    return inventory


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — Trigger DevLake pipelines and monitor progress
# ═══════════════════════════════════════════════════════════════════════════


async def check_running_pipelines(client: httpx.AsyncClient) -> list[dict]:
    """Check if there are any currently running DevLake pipelines."""
    try:
        r = await client.get(f"{DEVLAKE_API}/pipelines", params={"pageSize": 5, "page": 1})
        if r.status_code == 200:
            data = r.json()
            pipelines = data.get("pipelines", [])
            running = [p for p in pipelines if p.get("status") == "TASK_RUNNING"]
            return running
    except Exception:
        pass
    return []


async def trigger_blueprint(
    client: httpx.AsyncClient,
    blueprint_id: int,
    blueprint_name: str,
) -> int | None:
    """Trigger a DevLake blueprint and return the pipeline ID."""
    try:
        r = await client.post(
            f"{DEVLAKE_API}/blueprints/{blueprint_id}/trigger",
            timeout=30,
        )
        if r.status_code in (200, 201):
            data = r.json()
            pipeline_id = data.get("id")
            ok(f"Triggered blueprint '{blueprint_name}' → pipeline #{pipeline_id}")
            return pipeline_id
        else:
            fail(f"Failed to trigger blueprint #{blueprint_id}: HTTP {r.status_code} — {r.text[:200]}")
    except Exception as e:
        fail(f"Error triggering blueprint #{blueprint_id}: {e}")
    return None


async def wait_for_pipeline(
    client: httpx.AsyncClient,
    pipeline_id: int,
    blueprint_name: str,
) -> str:
    """Poll DevLake pipeline status until it completes or fails.

    Returns the final status: TASK_COMPLETED, TASK_PARTIAL, TASK_FAILED, TASK_CANCELLED.
    """
    start_time = time.monotonic()
    last_log_time = 0.0
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spin_idx = 0

    while True:
        try:
            r = await client.get(f"{DEVLAKE_API}/pipelines/{pipeline_id}")
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "UNKNOWN")
                elapsed = time.monotonic() - start_time
                elapsed_str = _format_duration(elapsed)

                if status in ("TASK_COMPLETED", "TASK_PARTIAL", "TASK_FAILED", "TASK_CANCELLED"):
                    icon = "✓" if status == "TASK_COMPLETED" else "⚠" if status == "TASK_PARTIAL" else "✗"
                    color = C.GREEN if status == "TASK_COMPLETED" else C.YELLOW if status == "TASK_PARTIAL" else C.RED
                    log.info(f"{color}  {icon} Pipeline #{pipeline_id} ({blueprint_name}): {status} in {elapsed_str}{C.RESET}")
                    return status

                # Log progress every 60s
                if elapsed - last_log_time >= 60:
                    # Try to get task details
                    tasks_info = ""
                    try:
                        tr = await client.get(f"{DEVLAKE_API}/pipelines/{pipeline_id}/tasks")
                        if tr.status_code == 200:
                            tasks = tr.json()
                            if isinstance(tasks, list):
                                active = [t for t in tasks if t.get("status") == "TASK_RUNNING"]
                                if active:
                                    subtask = active[0].get("subtaskName", "")
                                    plugin = active[0].get("plugin", "")
                                    tasks_info = f" [{plugin}: {subtask}]"
                    except Exception:
                        pass

                    s = spinner[spin_idx % len(spinner)]
                    spin_idx += 1
                    info(f"{s} Pipeline #{pipeline_id}: {status} — {elapsed_str} elapsed{tasks_info}")
                    last_log_time = elapsed

        except Exception as e:
            warn(f"Error polling pipeline #{pipeline_id}: {e}")

        await asyncio.sleep(POLL_INTERVAL)


async def run_devlake_ingestion(
    client: httpx.AsyncClient,
    blueprints: list[dict],
    specific_blueprint_id: int | None = None,
) -> dict[int, str]:
    """Run DevLake blueprints and wait for completion.

    Returns a dict of {blueprint_id: final_status}.
    """
    results: dict[int, str] = {}

    # Check for already running pipelines
    running = await check_running_pipelines(client)
    if running:
        warn(f"{len(running)} pipeline(s) already running — waiting for completion first")
        for p in running:
            status = await wait_for_pipeline(client, p["id"], f"existing-#{p['id']}")
            info(f"Existing pipeline #{p['id']} finished: {status}")

    # Filter blueprints
    targets = blueprints
    if specific_blueprint_id:
        targets = [bp for bp in blueprints if bp["id"] == specific_blueprint_id]
        if not targets:
            fail(f"Blueprint #{specific_blueprint_id} not found")
            return results

    # Trigger each blueprint sequentially (DevLake processes one at a time)
    for bp in targets:
        bp_id = bp["id"]
        bp_name = bp["name"]
        banner(f"DevLake: Triggering '{bp_name}' (#{bp_id})")

        retries = 0
        while retries < MAX_RETRIES:
            pipeline_id = await trigger_blueprint(client, bp_id, bp_name)
            if not pipeline_id:
                fail(f"Could not trigger blueprint '{bp_name}' — skipping")
                results[bp_id] = "TRIGGER_FAILED"
                break

            status = await wait_for_pipeline(client, pipeline_id, bp_name)
            results[bp_id] = status

            if status in ("TASK_COMPLETED", "TASK_PARTIAL"):
                break
            elif status == "TASK_FAILED" and retries < MAX_RETRIES - 1:
                retries += 1
                warn(f"Pipeline failed — retrying ({retries}/{MAX_RETRIES})...")
                await asyncio.sleep(10)
            else:
                break

    return results


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — Record counts in DevLake DB
# ═══════════════════════════════════════════════════════════════════════════


async def get_devlake_counts() -> dict[str, int]:
    """Get record counts from DevLake domain tables."""
    counts: dict[str, int] = {}
    tables = {
        "pull_requests": "pull_requests",
        "issues": "issues",
        "deployments": "cicd_deployment_commits",
        "sprints": "sprints",
        "issue_changelogs": "issue_changelogs",
    }
    try:
        conn = await asyncpg.connect(DEVLAKE_DB)
        for name, table in tables.items():
            try:
                result = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                counts[name] = result or 0
            except Exception:
                counts[name] = 0
        await conn.close()
    except Exception as e:
        warn(f"Could not query DevLake DB: {e}")
    return counts


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5 — Reset PULSE watermarks (optional)
# ═══════════════════════════════════════════════════════════════════════════


async def reset_pulse_watermarks() -> None:
    """Delete all watermarks to force a full re-sync from DevLake to PULSE."""
    try:
        conn = await asyncpg.connect(PULSE_DB)
        deleted = await conn.execute(
            "DELETE FROM pipeline_watermarks WHERE tenant_id = $1::uuid",
            TENANT_ID,
        )
        await conn.close()
        ok(f"Watermarks reset: {deleted}")
    except Exception as e:
        warn(f"Could not reset watermarks: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6 — Trigger sync worker (DevLake → PULSE DB → Kafka)
# ═══════════════════════════════════════════════════════════════════════════


async def trigger_sync_worker() -> bool:
    """Trigger the PULSE sync worker via direct import.

    The sync worker reads from DevLake DB, normalizes, upserts to PULSE DB,
    and publishes to Kafka topics.
    """
    info("Starting PULSE sync worker cycle...")

    try:
        # Add project root to path
        project_root = Path(__file__).resolve().parent.parent / "packages" / "pulse-data"
        sys.path.insert(0, str(project_root))

        # Set env vars for the worker
        os.environ.setdefault("DATABASE_URL", PULSE_DB.replace("postgresql://", "postgresql+asyncpg://"))
        os.environ.setdefault("DEVLAKE_DB_URL", DEVLAKE_DB)
        os.environ.setdefault("KAFKA_BROKERS", os.environ.get("KAFKA_BROKERS", "localhost:9092"))
        os.environ.setdefault("DEFAULT_TENANT_ID", TENANT_ID)

        from src.workers.devlake_sync import DevLakeSyncWorker

        worker = DevLakeSyncWorker()
        try:
            results = await worker.sync()
            ok(f"Sync worker cycle completed: {results}")
        finally:
            await worker.close()
        return True
    except ImportError:
        warn("Could not import sync worker — running via Docker instead")
        return await trigger_sync_worker_docker()
    except Exception as e:
        fail(f"Sync worker error: {e}")
        return False


async def trigger_sync_worker_docker() -> bool:
    """Trigger sync worker via docker compose exec."""
    import subprocess

    compose_file = Path(__file__).resolve().parent.parent / "docker-compose.yml"
    cmd = [
        "docker", "compose", "-f", str(compose_file),
        "exec", "-T", "sync-worker",
        "python", "-c",
        "import asyncio\nasync def _run():\n    from src.workers.devlake_sync import DevLakeSyncWorker\n    w = DevLakeSyncWorker()\n    try:\n        r = await w.sync()\n        print(f'Sync results: {r}')\n    finally:\n        await w.close()\nasyncio.run(_run())",
    ]

    info("Triggering sync via Docker container...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )
        if result.returncode == 0:
            ok("Docker sync worker cycle completed")
            return True
        else:
            fail(f"Docker sync failed: {result.stderr[:300]}")
            return False
    except subprocess.TimeoutExpired:
        warn("Sync worker timed out (10 min) — will continue on next cycle")
        return False
    except Exception as e:
        fail(f"Docker exec error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 7 — Final counts and validation
# ═══════════════════════════════════════════════════════════════════════════


async def get_pulse_counts() -> dict[str, int]:
    """Get record counts from PULSE domain tables."""
    counts: dict[str, int] = {}
    tables = {
        "pull_requests": "eng_pull_requests",
        "issues": "eng_issues",
        "deployments": "eng_deployments",
        "sprints": "eng_sprints",
    }
    try:
        conn = await asyncpg.connect(PULSE_DB)
        for name, table in tables.items():
            try:
                result = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {table} WHERE tenant_id = $1::uuid",
                    TENANT_ID,
                )
                counts[name] = result or 0
            except Exception:
                counts[name] = 0
        await conn.close()
    except Exception as e:
        warn(f"Could not query PULSE DB: {e}")
    return counts


def print_comparison(devlake: dict[str, int], pulse: dict[str, int]) -> None:
    """Print a comparison table of DevLake vs PULSE record counts."""
    banner("Final Record Count Comparison")
    header = f"  {'Entity':<20} {'DevLake':>10} {'PULSE':>10} {'Delta':>10} {'Status':>10}"
    info(header)
    info("  " + "─" * 62)

    total_dl = 0
    total_pl = 0
    all_synced = True

    for entity in ["pull_requests", "issues", "deployments", "sprints"]:
        dl = devlake.get(entity, 0)
        pl = pulse.get(entity, 0)
        delta = dl - pl
        total_dl += dl
        total_pl += pl

        if abs(delta) <= 5:
            status = f"{C.GREEN}✓ synced{C.RESET}"
        elif delta > 0:
            status = f"{C.YELLOW}⚠ behind{C.RESET}"
            all_synced = False
        else:
            status = f"{C.CYAN}↑ ahead{C.RESET}"

        info(f"  {entity:<20} {dl:>10,} {pl:>10,} {delta:>+10,} {status}")

    info("  " + "─" * 62)
    info(f"  {'TOTAL':<20} {total_dl:>10,} {total_pl:>10,} {total_dl - total_pl:>+10,}")

    if all_synced:
        ok("All entities are in sync!")
    else:
        warn("Some entities have pending records — the sync worker will catch up on next cycle (15 min)")


# ═══════════════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════════════


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════


async def main(args: argparse.Namespace) -> None:
    started_at = time.monotonic()

    banner("PULSE Full Ingestion — Starting")
    info(f"DevLake API:  {DEVLAKE_API}")
    info(f"DevLake DB:   {DEVLAKE_DB.split('@')[1] if '@' in DEVLAKE_DB else DEVLAKE_DB}")
    info(f"PULSE DB:     {PULSE_DB.split('@')[1] if '@' in PULSE_DB else PULSE_DB}")
    info(f"Tenant:       {TENANT_ID}")
    info(f"Dry run:      {args.dry_run}")
    info("")

    # ── Step 1: Health checks ──
    banner("Step 1/7 — Health Checks")

    async with httpx.AsyncClient(timeout=30) as client:
        devlake_ok = await check_devlake_health(client)
        if not devlake_ok:
            # Try with /health or just assume it's OK if we can reach blueprints
            try:
                r = await client.get(f"{DEVLAKE_API}/blueprints")
                devlake_ok = r.status_code == 200
                if devlake_ok:
                    ok("DevLake API responded on /blueprints")
            except Exception:
                pass

    devlake_db_ok = await check_devlake_db()
    pulse_db_ok = await check_pulse_db()

    if not devlake_db_ok or not pulse_db_ok:
        fail("Required databases are not reachable. Aborting.")
        sys.exit(1)

    # ── Step 2: Inventory ──
    banner("Step 2/7 — DevLake Inventory")

    async with httpx.AsyncClient(timeout=30) as client:
        inventory = await get_inventory(client)

    if not inventory["blueprints"]:
        fail("No blueprints found in DevLake. Configure blueprints first.")
        sys.exit(1)

    # ── Step 3: DevLake ingestion (API → DevLake DB) ──
    if not args.skip_devlake:
        banner("Step 3/7 — DevLake Data Collection (API → DevLake DB)")
        info("This step pulls data from GitHub/Jira/Jenkins APIs into DevLake.")
        info("It may take 2-8 hours depending on data volume.")
        info("Safe to interrupt — DevLake checkpoints internally.")
        info("")

        if args.dry_run:
            warn("DRY RUN — skipping DevLake trigger")
        else:
            async with httpx.AsyncClient(timeout=60) as client:
                results = await run_devlake_ingestion(
                    client,
                    inventory["blueprints"],
                    specific_blueprint_id=args.blueprint_id,
                )
                for bp_id, status in results.items():
                    if status in ("TASK_COMPLETED", "TASK_PARTIAL"):
                        ok(f"Blueprint #{bp_id}: {status}")
                    else:
                        fail(f"Blueprint #{bp_id}: {status}")
    else:
        info("Skipping DevLake collection (--skip-devlake)")

    # ── Step 4: DevLake record counts ──
    banner("Step 4/7 — DevLake Record Counts")
    devlake_counts = await get_devlake_counts()
    for entity, count in sorted(devlake_counts.items()):
        info(f"  {entity:<25} {count:>10,}")

    # ── Step 5: Reset watermarks (optional) ──
    if args.reset_watermarks:
        banner("Step 5/7 — Reset PULSE Watermarks")
        if args.dry_run:
            warn("DRY RUN — would reset watermarks")
        else:
            await reset_pulse_watermarks()
    else:
        info("Step 5/7 — Keeping existing watermarks (incremental sync)")

    # ── Step 6: Sync worker (DevLake DB → PULSE DB → Kafka) ──
    banner("Step 6/7 — PULSE Sync (DevLake → PULSE DB → Kafka)")
    info("Syncing records from DevLake DB into PULSE with normalization...")

    if args.dry_run:
        warn("DRY RUN — skipping sync worker")
    else:
        success = await trigger_sync_worker()
        if not success:
            warn("Sync worker had issues — records may catch up in next scheduled cycle (15 min)")

    # ── Step 7: Final validation ──
    banner("Step 7/7 — Validation")
    devlake_final = await get_devlake_counts()
    pulse_final = await get_pulse_counts()
    print_comparison(devlake_final, pulse_final)

    # ── Summary ──
    elapsed = time.monotonic() - started_at
    banner(f"PULSE Full Ingestion — Complete ({_format_duration(elapsed)})")
    info(f"DevLake records: {sum(devlake_final.get(e, 0) for e in ['pull_requests', 'issues', 'deployments', 'sprints']):,}")
    info(f"PULSE records:   {sum(pulse_final.values()):,}")
    info("")
    info("Next steps:")
    info("  • The sync worker runs every 15 min and will catch any remaining delta")
    info("  • The metrics worker consumes Kafka events and recalculates DORA/Lean/Sprint metrics")
    info("  • Check Pipeline Monitor at http://localhost:5173/pipeline-monitor")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PULSE Full Ingestion — Orchestrate complete data collection",
    )
    parser.add_argument(
        "--skip-devlake",
        action="store_true",
        help="Skip DevLake collection phase (only sync DevLake → PULSE)",
    )
    parser.add_argument(
        "--reset-watermarks",
        action="store_true",
        help="Reset PULSE watermarks to force full re-sync from DevLake",
    )
    parser.add_argument(
        "--blueprint-id",
        type=int,
        default=None,
        help="Trigger only a specific blueprint ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        log.info(f"\n{C.YELLOW}Interrupted by user. Safe to re-run — all progress is checkpointed.{C.RESET}")
        sys.exit(130)
