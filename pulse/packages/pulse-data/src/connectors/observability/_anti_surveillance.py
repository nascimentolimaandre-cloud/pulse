"""FDD-OBS-001 PR 1 — ADR-025 Layer 1 anti-surveillance.

Strips known-PII keys from vendor JSON BEFORE returning to PULSE
business code. Defense-in-depth: even if an adapter forgets to call
`strip_pii`, Layer 2 (DB CHECK trigger) catches it before storage.

Forbidden field set is duplicated in migration 018's
`obs_no_pii_in_metadata()` PL/pgSQL function — keep both in sync.

Adapters MUST call `strip_pii()` on every dict returned by HTTP
queries before mapping to `DeployMarker` / `MetricSeries` /
`ServiceEntity`. Recommended pattern:

    raw = await self._http.get(url)
    clean = strip_pii(raw)            # ← Layer 1
    return self._to_deploy_marker(clean)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Forbidden keys — case-insensitive match. Mirrors the SQL list in
# migration 018. When adding to either, update both.
FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset({
    "user", "user_id", "user.id", "user.email",
    "deployment.author", "alert.assignee", "incident.assignee",
    "owner.email", "ack_by", "resolved_by", "creator",
    "modified_by", "trace.user_id", "rum.user_id", "usr.email",
})


def _is_forbidden(key: str) -> bool:
    """Case-insensitive match against `FORBIDDEN_FIELD_NAMES`."""
    return key.lower() in FORBIDDEN_FIELD_NAMES


def strip_pii(record: Any) -> Any:
    """Recursively remove forbidden keys from a vendor JSON record.

    Returns a new structure (does not mutate). Logs a counter increment
    per stripped field so we can track which providers / tenants
    surface PII most often.

    Behaviour:
      - dict: copy, drop forbidden keys, recurse into values.
      - list / tuple: recurse into each element.
      - other: return as-is.
    """
    if isinstance(record, dict):
        cleaned: dict[str, Any] = {}
        for k, v in record.items():
            if not isinstance(k, str):
                # Defensive — non-string keys can't match any forbidden name.
                cleaned[k] = strip_pii(v)
                continue
            if _is_forbidden(k):
                logger.debug(
                    "anti-surveillance: stripped forbidden key %r at ingestion", k,
                )
                continue
            cleaned[k] = strip_pii(v)
        return cleaned
    if isinstance(record, list):
        return [strip_pii(item) for item in record]
    if isinstance(record, tuple):
        return tuple(strip_pii(item) for item in record)
    return record
