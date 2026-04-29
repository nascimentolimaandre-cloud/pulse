"""FDD-OPS-015 — per-scope progress tracking with rate-aware ETA.

Encapsulates the lifecycle of a single ingestion scope (e.g., one Jira
project, one GitHub repo, one Jenkins job):

    1. start_scope(estimate) — record initial state, persist row
    2. tick(items_added)    — per-batch update; recompute rolling rate + ETA
    3. finish(status, error)— record completion (done / failed)

The tracker upserts into `pipeline_progress` on every tick. Operators
query that table via `GET /data/v1/pipeline/jobs` to see live progress.

Rolling rate window: last N samples (default 5) — mean of (Δitems / Δseconds).
Smoothing avoids volatile spikes when one batch is unusually large/small.

ETA = max(0, (estimate - items_done) / rate) when both available.
None = unknown (no estimate, no rate yet, or rate=0).
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.contexts.pipeline.models import PipelineProgress
from src.database import get_session

logger = logging.getLogger(__name__)


# Rolling window size for rate computation. 5 samples = rate over the last
# ~5 batches; smooths out per-batch jitter. Tuned for ~50-item batches:
# at 18 items/sec, 5 batches ≈ 14 seconds of recent history.
DEFAULT_RATE_WINDOW = 5


class ProgressTracker:
    """Per-scope ingestion progress tracker.

    Lifecycle (one tracker per scope):
        tracker = ProgressTracker(tenant_id, "issues", "jira:project:BG")
        await tracker.start_scope(estimate=12450)
        async for batch in connector.fetch_issues_batched(...):
            await tracker.tick(len(batch))
        await tracker.finish(status="done")

    On exception, call `tracker.finish(status="failed", error=str(e))`.
    """

    def __init__(
        self,
        tenant_id: UUID,
        entity_type: str,
        scope_key: str,
        rate_window: int = DEFAULT_RATE_WINDOW,
    ) -> None:
        self.tenant_id = tenant_id
        self.entity_type = entity_type
        self.scope_key = scope_key
        self.items_done: int = 0
        self.estimate: Optional[int] = None
        self.started_at = datetime.now(timezone.utc)
        # Idempotency guard — once finish() succeeds, subsequent calls
        # are no-ops (avoids 'done' tracker being flipped to 'failed' by
        # an outer except block). See worker error-handling pattern.
        self._is_finished: bool = False
        # Rolling window of (timestamp, cumulative_items_done) for rate calc.
        # We keep cumulative (not delta) so rate is always a mean over the
        # window's full elapsed time — robust to batch-size variance.
        self._samples: deque[tuple[datetime, int]] = deque(maxlen=rate_window)

    # ------------------------------------------------------------------
    # Public lifecycle methods
    # ------------------------------------------------------------------

    async def start_scope(
        self, estimate: Optional[int] = None, phase: str = "pre_flight",
    ) -> None:
        """Initialize tracker state and persist the first progress row.

        Args:
            estimate: Pre-flight count. None when count call failed/skipped.
            phase: Initial phase label. Default 'pre_flight' transitions to
                'fetching' on first tick.
        """
        self.estimate = estimate
        self._samples.clear()
        # Seed with t=0 so first tick produces a finite rate immediately.
        self._samples.append((self.started_at, 0))
        await self._upsert(
            phase=phase,
            status="running",
            items_per_second=0.0,
            eta_seconds=None,
            finished=False,
            error=None,
        )

    async def tick(self, items_added: int, phase: str = "fetching") -> None:
        """Record a batch of items processed; recompute rate + ETA.

        Args:
            items_added: Items in THIS batch (not cumulative).
            phase: Phase label for this update. Default 'fetching'.
        """
        if items_added < 0:
            logger.warning(
                "[progress] %s/%s: negative items_added=%d ignored",
                self.entity_type, self.scope_key, items_added,
            )
            return
        self.items_done += items_added
        now = datetime.now(timezone.utc)
        self._samples.append((now, self.items_done))
        rate = self._compute_rate()
        eta = self._compute_eta(rate)
        await self._upsert(
            phase=phase,
            status="running",
            items_per_second=rate,
            eta_seconds=eta,
            finished=False,
            error=None,
        )

    async def finish(
        self, status: str = "done", error: Optional[str] = None,
    ) -> None:
        """Mark the scope as completed (done or failed) and persist final row.

        Idempotent: subsequent calls after the first are no-ops. This
        protects against double-finish patterns in worker error handling
        (e.g., per-scope finish in the loop + outer except block).

        Args:
            status: 'done' | 'failed' | 'cancelled' | 'paused'.
            error: Error message when status='failed'. Truncated to 4000
                chars to avoid log bloat.
        """
        if self._is_finished:
            return
        self._is_finished = True
        # Final rate + 0 ETA (work complete).
        rate = self._compute_rate()
        eta_zero = 0 if status == "done" else None
        truncated_error = (
            error[:4000] if isinstance(error, str) and len(error) > 4000
            else error
        )
        await self._upsert(
            phase=status,  # 'done'/'failed' becomes the final phase
            status=status,
            items_per_second=rate,
            eta_seconds=eta_zero,
            finished=True,
            error=truncated_error,
        )

    # ------------------------------------------------------------------
    # Public read helpers (for tests + worker introspection)
    # ------------------------------------------------------------------

    @property
    def progress_pct(self) -> Optional[float]:
        """Completion percentage (0-100) when estimate available."""
        if self.estimate is None or self.estimate <= 0:
            return None
        return min(100.0, 100.0 * self.items_done / self.estimate)

    @property
    def current_rate(self) -> float:
        """Current rolling rate (items per second). 0 if insufficient samples."""
        return self._compute_rate()

    @property
    def current_eta(self) -> Optional[int]:
        """ETA seconds remaining, or None if unknown."""
        return self._compute_eta(self._compute_rate())

    # ------------------------------------------------------------------
    # Internal: rate + ETA math
    # ------------------------------------------------------------------

    def _compute_rate(self) -> float:
        """Rolling rate (items/sec) over the sample window.

        Uses oldest vs newest sample to compute mean rate. Returns 0.0
        when:
          - Fewer than 2 samples (insufficient data)
          - Elapsed time is 0 (samples in same instant — unusual)
          - Items haven't increased (worker stalled or back-pressured)
        """
        if len(self._samples) < 2:
            return 0.0
        oldest_ts, oldest_done = self._samples[0]
        newest_ts, newest_done = self._samples[-1]
        elapsed = (newest_ts - oldest_ts).total_seconds()
        if elapsed <= 0:
            return 0.0
        delta = newest_done - oldest_done
        if delta <= 0:
            return 0.0
        return delta / elapsed

    def _compute_eta(self, rate: float) -> Optional[int]:
        """Seconds remaining = (estimate - done) / rate.

        Returns None when:
          - No estimate (couldn't pre-flight count)
          - Rate is zero (no progress yet, or stalled)
          - Done >= estimate (worker overshot — UI shows 0)
        """
        if rate <= 0 or self.estimate is None:
            return None
        remaining = max(0, self.estimate - self.items_done)
        if remaining == 0:
            return 0
        return int(round(remaining / rate))

    # ------------------------------------------------------------------
    # Internal: persistence
    # ------------------------------------------------------------------

    async def _upsert(
        self,
        phase: str,
        status: str,
        items_per_second: float,
        eta_seconds: Optional[int],
        finished: bool,
        error: Optional[str],
    ) -> None:
        """Upsert pipeline_progress row by (tenant, entity_type, scope_key).

        Idempotent — multiple ticks per second are fine, last write wins.
        """
        now = datetime.now(timezone.utc)
        values = {
            "tenant_id": self.tenant_id,
            "scope_key": self.scope_key,
            "entity_type": self.entity_type,
            "phase": phase,
            "status": status,
            "items_done": self.items_done,
            "items_estimate": self.estimate,
            "items_per_second": items_per_second,
            "eta_seconds": eta_seconds,
            "started_at": self.started_at,
            "last_progress_at": now,
            "finished_at": now if finished else None,
            "last_error": error,
        }
        try:
            async with get_session(self.tenant_id) as session:
                stmt = (
                    pg_insert(PipelineProgress)
                    .values(**values)
                    .on_conflict_do_update(
                        constraint="uq_pipeline_progress_scope",
                        set_={
                            "phase": values["phase"],
                            "status": values["status"],
                            "items_done": values["items_done"],
                            "items_estimate": values["items_estimate"],
                            "items_per_second": values["items_per_second"],
                            "eta_seconds": values["eta_seconds"],
                            "last_progress_at": values["last_progress_at"],
                            "finished_at": values["finished_at"],
                            "last_error": values["last_error"],
                        },
                    )
                )
                await session.execute(stmt)
        except Exception:
            # Persistence failures must NOT break ingestion. Log and move on.
            logger.exception(
                "[progress] %s/%s: failed to upsert pipeline_progress row",
                self.entity_type, self.scope_key,
            )
