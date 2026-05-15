"""FDD-OBS-001 PR 4a — Observability Rollup Worker.

Calls `rollup_service.run_cycle()` every 15 minutes. Each cycle iterates
every tenant with a configured DD credential, queries the 6 PulseMetrics
for every service in their ownership map, and writes hourly buckets to
`obs_metric_snapshots`.

Operational properties:
  - APScheduler `IntervalTrigger(minutes=15)` with `coalesce=True` and
    `max_instances=1` — overlapping ticks (when a cycle takes > 15 min)
    are squashed, never running two in parallel.
  - Soft per-cycle deadline of 12 minutes (built into `run_cycle`); on
    overrun, the cycle returns clean and the next tick takes over.
  - Provider instances are NOT cached across cycles — keeps master-key
    memory residence ≤ one cycle (ADR-028).
  - SIGTERM / SIGINT trigger graceful scheduler shutdown.

Run:
  python -m src.workers.obs_rollup_worker          # default 15-min loop
  python -m src.workers.obs_rollup_worker --once   # single cycle, exit

Operational kill switch:
  Set `OBS_ROLLUP_ENABLED=false` in the worker container's env to make
  the worker exit cleanly on startup. Use this if a runaway DD spend or
  rate-limit bug is suspected — restart with the env restored once
  the issue is fixed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

from src.config import settings
from src.contexts.observability.services import rollup_service
from src.contexts.observability.services.token_bucket import TokenBucket

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

logger = logging.getLogger(__name__)


# Tunables. ENABLED env gives ops a one-flag kill switch to disable
# the worker without redeploying — useful if rate-limit calibration
# misfires or DD goes into outage.
_ENV_ENABLED = "OBS_ROLLUP_ENABLED"
_DEFAULT_INTERVAL_MINUTES = 15


def _is_enabled() -> bool:
    """`OBS_ROLLUP_ENABLED=false` exits the worker on startup; absent
    or any other value defaults to enabled."""
    val = (os.environ.get(_ENV_ENABLED) or "true").strip().lower()
    return val not in ("false", "0", "no", "off")


async def _run_one_cycle() -> None:
    """Wrapper that swallows exceptions out of `run_cycle`. The
    orchestrator already returns clean for the per-tenant errors, but
    this is the last line of defense so APScheduler's job tracking
    doesn't go red on a transient blip."""
    bucket = TokenBucket()  # fresh per cycle — Redis is the shared state
    try:
        await rollup_service.run_cycle(provider_id="datadog", bucket=bucket)
    except Exception as exc:
        # CISO FIND-001: avoid logger.exception (exc_info=True attaches full
        # traceback w/ local var bindings; driver excs may carry bound params).
        logger.error(
            "[obs-rollup] cycle raised — continuing scheduler err_class=%s",
            type(exc).__name__,
        )


async def run_worker(interval_minutes: int = _DEFAULT_INTERVAL_MINUTES) -> None:
    """Main scheduler loop. Blocks until SIGTERM / SIGINT."""
    if not HAS_APSCHEDULER:
        logger.error(
            "apscheduler not installed. pip install apscheduler>=3.10",
        )
        sys.exit(1)

    if not _is_enabled():
        logger.warning(
            "[obs-rollup] %s=false — worker exiting (kill switch).",
            _ENV_ENABLED,
        )
        return

    if not settings.pulse_obs_master_key:
        logger.warning(
            "[obs-rollup] PULSE_OBS_MASTER_KEY not configured — worker exits. "
            "Configure the master key in the container env before starting.",
        )
        return

    scheduler = AsyncIOScheduler()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("[obs-rollup] Received shutdown signal — stopping scheduler.")
        scheduler.shutdown(wait=False)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, ValueError):
            # Windows / non-main thread — fall back, scheduler still works
            # but signals won't be handled gracefully.
            pass

    # CISO PR 4a INFO-2: register the immediate-first-tick via APScheduler
    # itself (with `next_run_time=now`) instead of `asyncio.create_task` —
    # this way `max_instances=1` covers the bootstrap call too, ruling
    # out a race where startup + first interval tick run concurrently.
    scheduler.add_job(
        _run_one_cycle,
        IntervalTrigger(minutes=interval_minutes),
        id="obs-rollup-cycle",
        coalesce=True,                              # squash overlapping ticks
        max_instances=1,                            # never two cycles concurrently
        next_run_time=datetime.now(timezone.utc),  # fire ASAP, then every N min
    )

    scheduler.start()
    logger.info(
        "[obs-rollup] worker started — interval=%d min", interval_minutes,
    )

    await stop_event.wait()
    logger.info("[obs-rollup] worker stopped.")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="obs_rollup_worker")
    p.add_argument(
        "--once", action="store_true",
        help="Run one cycle and exit (useful for manual ops triggers).",
    )
    p.add_argument(
        "--interval-minutes", type=int, default=_DEFAULT_INTERVAL_MINUTES,
        help=f"Cycle interval (default {_DEFAULT_INTERVAL_MINUTES} min).",
    )
    return p.parse_args()


def _configure_logging() -> None:
    """Initialize root logging + suppress noisy / leaky third-party loggers.

    CISO PR 4a follow-up (live smoke 2026-05-08): httpx logs every HTTP
    request at INFO level with the FULL URL — including DD query
    parameters that contain plaintext service names like
    `service:agendafacil-barramento-api-get-agendamento`. ADR-028's
    service-name hashing only redacts OUR logs; without raising
    httpx to WARNING, the URL leak negates that guarantee. Pin
    httpx + apscheduler to WARNING so only retry / failure events
    surface in the worker logs.
    """
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # Anti-surveillance — httpx URL leak (see docstring above).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # APScheduler internal chatter — INFO level emits "added job", "next
    # run scheduled at", etc. Useful for one-shot --once debug runs but
    # noisy in production cycles.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def _main() -> None:
    args = _parse_args()
    _configure_logging()
    if args.once:
        if not _is_enabled():
            logger.warning("[obs-rollup] %s=false — --once aborted.", _ENV_ENABLED)
            return
        if not settings.pulse_obs_master_key:
            logger.warning("[obs-rollup] no master key — --once aborted.")
            return
        await _run_one_cycle()
    else:
        await run_worker(interval_minutes=args.interval_minutes)


if __name__ == "__main__":
    asyncio.run(_main())
