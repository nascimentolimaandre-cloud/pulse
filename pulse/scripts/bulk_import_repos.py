#!/usr/bin/env python3
"""PULSE — Bulk Import GitHub Repos into DevLake.

Discovers all repositories from the GitHub org via DevLake's remote-scopes API,
filters out archived/inactive repos, and registers them as scopes in DevLake.

This does NOT trigger data collection — it only registers repos so that
the next Blueprint run (or manual trigger) will collect their data.

Usage:
    # Dry run — see what would be imported
    python scripts/bulk_import_repos.py --dry-run

    # Import all active repos
    python scripts/bulk_import_repos.py

    # Import only repos with activity in the last 12 months
    python scripts/bulk_import_repos.py --active-months 12

    # Import only repos matching a pattern
    python scripts/bulk_import_repos.py --filter "webmotors.*.ui"

    # After import, trigger ingestion
    python scripts/full_ingestion.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

DEVLAKE_API = "http://localhost:8080"
CONNECTION_ID = 1
SCOPE_CONFIG_ID = 1  # "Webmotors Default"
ORG = "webmotors-private"
BATCH_SIZE = 50  # DevLake recommends batches of ~50 scopes per PUT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bulk-import")


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def ok(msg: str) -> None:
    log.info(f"\033[92m  ✓ {msg}\033[0m")

def warn(msg: str) -> None:
    log.warning(f"\033[93m  ⚠ {msg}\033[0m")

def fail(msg: str) -> None:
    log.error(f"\033[91m  ✗ {msg}\033[0m")

def header(msg: str) -> None:
    log.info(f"\033[1m\033[96m{'─' * 60}\033[0m")
    log.info(f"\033[1m\033[96m  {msg}\033[0m")
    log.info(f"\033[1m\033[96m{'─' * 60}\033[0m")


# ──────────────────────────────────────────────────────────────
# Step 1: Discover all repos from GitHub org via DevLake API
# ──────────────────────────────────────────────────────────────

def discover_all_repos(client: httpx.Client) -> list[dict]:
    """Paginate through all repos in the org via DevLake remote-scopes."""
    all_repos = []
    page_token = ""
    page = 0

    while True:
        page += 1
        params: dict = {"groupId": ORG}
        if page_token:
            params["pageToken"] = page_token

        resp = client.get(
            f"{DEVLAKE_API}/plugins/github/connections/{CONNECTION_ID}/remote-scopes",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        children = data.get("children", [])
        all_repos.extend(children)

        log.info(f"  Page {page}: {len(children)} repos (total: {len(all_repos)})")

        next_token = data.get("nextPageToken", "")
        if not next_token or not children:
            break
        page_token = next_token

    return all_repos


# ──────────────────────────────────────────────────────────────
# Step 2: Get already-imported scopes
# ──────────────────────────────────────────────────────────────

def get_existing_scopes(client: httpx.Client) -> set[str]:
    """Return set of fullName for repos already imported."""
    resp = client.get(
        f"{DEVLAKE_API}/plugins/github/connections/{CONNECTION_ID}/scopes",
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    scopes = data.get("scopes", [])
    return {s["scope"]["fullName"] for s in scopes if "scope" in s}


# ──────────────────────────────────────────────────────────────
# Step 3: Filter repos
# ──────────────────────────────────────────────────────────────

def filter_repos(
    repos: list[dict],
    existing: set[str],
    *,
    pattern: str | None = None,
    active_months: int | None = None,
    include_archived: bool = False,
) -> tuple[list[dict], dict[str, int]]:
    """Filter repos and return (filtered_list, stats)."""
    stats = {
        "total_discovered": len(repos),
        "already_imported": 0,
        "archived": 0,
        "pattern_excluded": 0,
        "inactive": 0,
        "selected": 0,
    }

    filtered = []
    cutoff = None
    if active_months:
        cutoff = datetime.now(timezone.utc) - timedelta(days=active_months * 30)

    pattern_re = re.compile(pattern, re.IGNORECASE) if pattern else None

    for repo in repos:
        full_name = repo.get("fullName", "")
        name = repo.get("name", "")
        repo_data = repo.get("data", {}) or {}

        # Skip already imported
        if full_name in existing:
            stats["already_imported"] += 1
            continue

        # Skip archived repos (check data.archived if available)
        if not include_archived and repo_data.get("archived", False):
            stats["archived"] += 1
            continue

        # Pattern filter
        if pattern_re and not pattern_re.search(name) and not pattern_re.search(full_name):
            stats["pattern_excluded"] += 1
            continue

        # Activity filter — check updatedDate from data
        if cutoff:
            updated = repo_data.get("updatedDate") or repo_data.get("updated_at")
            if updated and updated != "0001-01-01T00:00:00Z":
                try:
                    updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    if updated_dt < cutoff:
                        stats["inactive"] += 1
                        continue
                except (ValueError, TypeError):
                    pass  # Can't parse, include it

        filtered.append(repo)
        stats["selected"] += 1

    return filtered, stats


# ──────────────────────────────────────────────────────────────
# Step 4: Register repos as scopes in DevLake (batch PUT)
# ──────────────────────────────────────────────────────────────

def register_scopes(
    client: httpx.Client,
    repos: list[dict],
    dry_run: bool = False,
) -> int:
    """Register repos as scopes in DevLake via PUT.

    DevLake's PUT /plugins/github/connections/:id/scopes
    accepts a list of scope objects. We send in batches.
    """
    total_registered = 0

    for batch_start in range(0, len(repos), BATCH_SIZE):
        batch = repos[batch_start : batch_start + BATCH_SIZE]
        batch_num = (batch_start // BATCH_SIZE) + 1
        total_batches = (len(repos) + BATCH_SIZE - 1) // BATCH_SIZE

        # Build scope objects for DevLake
        scope_objects = []
        for repo in batch:
            scope_obj = {
                "connectionId": CONNECTION_ID,
                "githubId": int(repo["id"]),
                "name": repo["name"],
                "fullName": repo["fullName"],
                "scopeConfigId": SCOPE_CONFIG_ID,
            }
            scope_objects.append(scope_obj)

        if dry_run:
            log.info(
                f"  [DRY RUN] Batch {batch_num}/{total_batches}: "
                f"would register {len(scope_objects)} repos"
            )
            for s in scope_objects[:3]:
                log.info(f"    → {s['fullName']}")
            if len(scope_objects) > 3:
                log.info(f"    ... and {len(scope_objects) - 3} more")
            total_registered += len(scope_objects)
            continue

        log.info(
            f"  Batch {batch_num}/{total_batches}: "
            f"registering {len(scope_objects)} repos..."
        )

        try:
            resp = client.put(
                f"{DEVLAKE_API}/plugins/github/connections/{CONNECTION_ID}/scopes",
                json={"data": scope_objects},
                timeout=60,
            )
            if resp.status_code in (200, 201):
                total_registered += len(scope_objects)
                ok(f"Batch {batch_num} registered ({total_registered} total)")
            else:
                fail(
                    f"Batch {batch_num} failed: HTTP {resp.status_code} — "
                    f"{resp.text[:200]}"
                )
                # Continue with next batch instead of failing completely
        except httpx.HTTPError as e:
            fail(f"Batch {batch_num} HTTP error: {e}")

        # Small delay between batches to be gentle on DevLake
        if batch_start + BATCH_SIZE < len(repos):
            time.sleep(1)

    return total_registered


# ──────────────────────────────────────────────────────────────
# Step 5: Update Blueprint to include all scopes
# ──────────────────────────────────────────────────────────────

def update_blueprint_connections(client: httpx.Client, blueprint_id: int, dry_run: bool = False) -> bool:
    """Ensure the blueprint's GitHub connection includes all registered scopes.

    DevLake blueprints reference scopes by their scope IDs. We need to
    update the blueprint to include all the new scopes we just registered.
    """
    # Get current blueprint
    resp = client.get(f"{DEVLAKE_API}/blueprints/{blueprint_id}", timeout=30)
    if resp.status_code != 200:
        fail(f"Could not fetch blueprint {blueprint_id}: {resp.status_code}")
        return False

    blueprint = resp.json()
    log.info(f"  Blueprint #{blueprint_id}: {blueprint.get('name', '?')}")

    # Get all currently registered scopes (paginate if needed)
    all_scopes = []
    page = 1
    while True:
        scopes_resp = client.get(
            f"{DEVLAKE_API}/plugins/github/connections/{CONNECTION_ID}/scopes",
            params={"page": page, "pageSize": 100},
            timeout=30,
        )
        if scopes_resp.status_code != 200:
            # Fallback: try without pagination params
            scopes_resp = client.get(
                f"{DEVLAKE_API}/plugins/github/connections/{CONNECTION_ID}/scopes",
                timeout=30,
            )
            scopes_resp.raise_for_status()
            all_scopes = scopes_resp.json().get("scopes", [])
            break
        batch = scopes_resp.json().get("scopes", [])
        if not batch:
            break
        all_scopes.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    all_scope_ids = [str(s["scope"]["githubId"]) for s in all_scopes]

    log.info(f"  Total registered scopes: {len(all_scope_ids)}")

    # Build updated connections config
    # Blueprint settings format depends on DevLake version
    settings = blueprint.get("settings", {})
    connections = settings.get("connections", [])

    github_conn = None
    for conn in connections:
        if conn.get("pluginName") == "github" and conn.get("connectionId") == CONNECTION_ID:
            github_conn = conn
            break

    if not github_conn:
        warn(f"No GitHub connection found in blueprint {blueprint_id} — skipping")
        return False

    current_scopes = github_conn.get("scopes", [])
    current_scope_ids = {s.get("scopeId") for s in current_scopes}

    log.info(f"  Current blueprint scopes: {len(current_scope_ids)}")

    # Build new scopes list — keep existing + add new
    new_scope_entries = list(current_scopes)  # Keep existing
    added = 0
    for scope_id in all_scope_ids:
        if scope_id not in current_scope_ids:
            new_scope_entries.append({
                "scopeId": scope_id,
                "entities": ["CODE", "CODE_REVIEW", "CROSS"],
            })
            added += 1

    if added == 0:
        ok("Blueprint already has all scopes — no update needed")
        return True

    log.info(f"  Adding {added} new scopes to blueprint")

    if dry_run:
        warn(f"DRY RUN — would update blueprint {blueprint_id} with {len(new_scope_entries)} total scopes")
        return True

    # Update the blueprint
    github_conn["scopes"] = new_scope_entries

    patch_resp = client.patch(
        f"{DEVLAKE_API}/blueprints/{blueprint_id}",
        json={
            "settings": settings,
        },
        timeout=60,
    )

    if patch_resp.status_code == 200:
        ok(f"Blueprint {blueprint_id} updated with {len(new_scope_entries)} scopes")
        return True
    else:
        fail(f"Blueprint update failed: {patch_resp.status_code} — {patch_resp.text[:200]}")
        return False


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bulk import GitHub repos into DevLake",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without making changes",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Regex pattern to filter repos by name (e.g. 'webmotors\\..*\\.ui')",
    )
    parser.add_argument(
        "--active-months",
        type=int,
        default=None,
        help="Only import repos with activity in the last N months",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived repositories",
    )
    parser.add_argument(
        "--blueprint-id",
        type=int,
        default=1,
        help="Blueprint ID to update with new scopes (default: 1)",
    )
    parser.add_argument(
        "--skip-blueprint",
        action="store_true",
        help="Don't update the blueprint after importing scopes",
    )
    args = parser.parse_args()

    start = time.time()

    header("PULSE — Bulk GitHub Repo Import")
    log.info(f"  DevLake API:     {DEVLAKE_API}")
    log.info(f"  Connection:      #{CONNECTION_ID} (GitHub)")
    log.info(f"  Org:             {ORG}")
    log.info(f"  Scope Config:    #{SCOPE_CONFIG_ID} (Webmotors Default)")
    log.info(f"  Dry run:         {args.dry_run}")
    if args.filter:
        log.info(f"  Filter pattern:  {args.filter}")
    if args.active_months:
        log.info(f"  Active months:   {args.active_months}")
    log.info("")

    client = httpx.Client(timeout=30)

    # ── Step 1: Health check ──
    header("Step 1/5 — Health Check")
    try:
        resp = client.get(f"{DEVLAKE_API}/ping", timeout=10)
        resp.raise_for_status()
        ok("DevLake API is healthy")
    except Exception as e:
        fail(f"DevLake API unreachable: {e}")
        sys.exit(1)

    # ── Step 2: Discover all repos ──
    header("Step 2/5 — Discover Repos from GitHub Org")
    all_repos = discover_all_repos(client)
    ok(f"Discovered {len(all_repos)} repos in {ORG}")

    # ── Step 3: Get existing + filter ──
    header("Step 3/5 — Filter Repos")
    existing = get_existing_scopes(client)
    log.info(f"  Already imported: {len(existing)} repos")

    filtered, stats = filter_repos(
        all_repos,
        existing,
        pattern=args.filter,
        active_months=args.active_months,
        include_archived=args.include_archived,
    )

    log.info("")
    log.info("  Filter Results:")
    log.info(f"    Total discovered:   {stats['total_discovered']:>6}")
    log.info(f"    Already imported:   {stats['already_imported']:>6}")
    log.info(f"    Archived (skip):    {stats['archived']:>6}")
    if args.filter:
        log.info(f"    Pattern excluded:   {stats['pattern_excluded']:>6}")
    if args.active_months:
        log.info(f"    Inactive (skip):    {stats['inactive']:>6}")
    log.info(f"    ─────────────────────────")
    log.info(f"    To import:          {stats['selected']:>6}")

    if not filtered:
        ok("No new repos to import — all repos already registered")
        return

    # Show sample of repos to import
    log.info("")
    log.info("  Sample repos to import:")
    for repo in filtered[:10]:
        log.info(f"    → {repo['fullName']}")
    if len(filtered) > 10:
        log.info(f"    ... and {len(filtered) - 10} more")

    # ── Step 4: Register scopes ──
    header("Step 4/5 — Register Scopes in DevLake")
    registered = register_scopes(client, filtered, dry_run=args.dry_run)

    if registered > 0:
        ok(f"Registered {registered} new repos as DevLake scopes")
    else:
        warn("No repos were registered")

    # ── Step 5: Update Blueprint ──
    if not args.skip_blueprint:
        header("Step 5/5 — Update Blueprint")
        update_blueprint_connections(client, args.blueprint_id, dry_run=args.dry_run)
    else:
        log.info("  Skipping blueprint update (--skip-blueprint)")

    # ── Summary ──
    elapsed = int(time.time() - start)
    header(f"Import Complete ({elapsed}s)")
    log.info(f"  Repos discovered:   {len(all_repos)}")
    log.info(f"  Previously imported: {len(existing)}")
    log.info(f"  Newly registered:    {registered}")
    log.info(f"  Total scopes:        {len(existing) + registered}")
    log.info("")
    if not args.dry_run:
        log.info("  Next steps:")
        log.info("    1. Trigger DevLake collection:")
        log.info(f"       python scripts/full_ingestion.py")
        log.info("    2. Or wait for the next scheduled Blueprint run")
        log.info(f"       Blueprint #{args.blueprint_id} runs every 15 min")
    else:
        log.info("  This was a DRY RUN — no changes were made.")
        log.info("  Remove --dry-run to actually import.")

    client.close()


if __name__ == "__main__":
    main()
