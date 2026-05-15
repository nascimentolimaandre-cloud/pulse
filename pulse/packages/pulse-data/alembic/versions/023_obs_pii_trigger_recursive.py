"""FDD-OBS-001 Phase 1 T1.5 — recursive PII trigger on service_squad_ownership.

Migration 018 installed `obs_no_pii_in_metadata()`, a PL/pgSQL trigger
that blocks INSERTs/UPDATEs to `service_squad_ownership` where the
`metadata` JSONB column contains a known-PII key. RISK-7 in the
backlog flagged a real gap: the original implementation uses
`NEW.metadata ? k`, which only checks for TOP-LEVEL key existence.

So a payload like:

    {"deep": {"user.email": "alice@webmotors.com"}}

silently passes the trigger because neither `deep` nor `user.email`
appears at the top level. This is precisely the failure mode that
Layer 2 was supposed to be the safety net for — if Layer 1 (adapter
`strip_pii`) ever misses a nested case, the DB trigger should catch it
before it lands on disk. Current trigger doesn't.

This migration:
  1. Drops + recreates `obs_no_pii_in_metadata()` as a RECURSIVE
     function that walks the JSONB tree depth-first and raises
     `check_violation` on any forbidden key at any depth.
  2. Keeps the trigger binding on `service_squad_ownership` (same
     row-level guard, just stronger backend).
  3. Uses `jsonb_each` to iterate object fields and `jsonb_array_elements`
     to descend into arrays — handles both shapes.

Forbidden key list mirrors the Python `FORBIDDEN_FIELD_NAMES` from
`src/connectors/observability/_anti_surveillance.py` (kept in lockstep
by a test in `test_obs_anti_surveillance.py`).

Revision ID: 023_obs_pii_trigger_recursive
Revises: 022_obs_metric_monitor_health
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op


revision: str = "023_obs_pii_trigger_recursive"
down_revision: Union[str, None] = "022_obs_metric_monitor_health"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors `_anti_surveillance.FORBIDDEN_FIELD_NAMES` (Python). Changing
# one MUST change the other; a test in `test_obs_anti_surveillance.py`
# enforces that drift.
_FORBIDDEN_KEYS = (
    "user", "user_id", "user.id", "user.email",
    "deployment.author", "alert.assignee", "incident.assignee",
    "owner.email", "ack_by", "resolved_by", "creator",
    "modified_by", "trace.user_id", "rum.user_id", "usr.email",
)


def _sql_array_of_keys() -> str:
    """Build the PL/pgSQL ARRAY[...] literal of forbidden keys."""
    return "ARRAY[" + ", ".join(f"'{k}'" for k in _FORBIDDEN_KEYS) + "]"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION obs_no_pii_in_metadata()
        RETURNS trigger AS $$
        DECLARE
            forbidden_keys TEXT[] := {_sql_array_of_keys()};
            offending_key  TEXT;
        BEGIN
            IF NEW.metadata IS NULL THEN
                RETURN NEW;
            END IF;

            -- Recursive walk: descend into every JSONB object/array and
            -- collect each KEY at any depth. The CTE returns one row per
            -- distinct key seen. If any matches the forbidden set we
            -- raise check_violation.
            WITH RECURSIVE walk(node) AS (
                SELECT NEW.metadata AS node
                UNION ALL
                SELECT child_value
                FROM walk,
                     LATERAL (
                         -- Object: recurse on every value
                         SELECT value AS child_value
                         FROM jsonb_each(walk.node)
                         WHERE jsonb_typeof(walk.node) = 'object'
                         UNION ALL
                         -- Array: recurse on every element
                         SELECT element AS child_value
                         FROM jsonb_array_elements(walk.node) AS element
                         WHERE jsonb_typeof(walk.node) = 'array'
                     ) AS children
            )
            SELECT k INTO offending_key
            FROM walk,
                 LATERAL (
                     SELECT key AS k
                     FROM jsonb_each(walk.node)
                     WHERE jsonb_typeof(walk.node) = 'object'
                 ) AS keys
            WHERE keys.k = ANY (forbidden_keys)
            LIMIT 1;

            IF offending_key IS NOT NULL THEN
                RAISE EXCEPTION
                    'PII key % blocked in obs metadata at any depth (ADR-025 Layer 2)',
                    offending_key
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    # Revert to migration 018's top-level-only check.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION obs_no_pii_in_metadata()
        RETURNS trigger AS $$
        DECLARE
            forbidden_keys TEXT[] := ARRAY[
                'user', 'user_id', 'user.id', 'user.email',
                'deployment.author', 'alert.assignee', 'incident.assignee',
                'owner.email', 'ack_by', 'resolved_by', 'creator',
                'modified_by', 'trace.user_id', 'rum.user_id', 'usr.email'
            ];
            k TEXT;
        BEGIN
            IF NEW.metadata IS NULL THEN
                RETURN NEW;
            END IF;
            FOREACH k IN ARRAY forbidden_keys LOOP
                IF NEW.metadata ? k THEN
                    RAISE EXCEPTION 'PII key % blocked in obs metadata (ADR-025 Layer 2)', k
                        USING ERRCODE = 'check_violation';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
