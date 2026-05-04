"""On-demand metric computation services (INC-015, FDD-DSH-060).

Each module here exposes a single `compute_*_on_demand` coroutine that
the `routes.py` deep-dive endpoints call when `squad_key` is set or
`period == 'custom'` — i.e. when the snapshot fast-path can't serve the
request because pre-computed data doesn't exist for that scope.

Design (architect-validated, INC-015):
  - Services depend on `MetricsRepository` (extended with squad-aware
    fetchers) — never open their own DB sessions.
  - Each service maps repo output → domain dataclass → pure-Python
    calculator → asdict() → response-shape dict that mirrors the
    snapshot value JSONB.
  - Services are unit-tested with a mocked repository (no DB).
"""

from .home import compute_home_metrics_on_demand, compute_previous_period
from .dora import compute_dora_on_demand
from .lean import compute_lean_on_demand
from .cycle_time import compute_cycle_time_on_demand
from .throughput import compute_throughput_on_demand

__all__ = [
    "compute_home_metrics_on_demand",
    "compute_previous_period",
    "compute_dora_on_demand",
    "compute_lean_on_demand",
    "compute_cycle_time_on_demand",
    "compute_throughput_on_demand",
]
