"""Partial + GIN indexes for Kanban Flow Health endpoint.

Supports FDD-KB-003 (Aging WIP) and FDD-KB-004 (Flow Efficiency).
Target: p95 < 800ms per SLA section 13 of
`pulse/docs/metrics/kanban-formulas-v1.md`.

Three indexes:

1. `idx_eng_issues_flow_active` — partial index on
   (tenant_id, project_key, normalized_status) WHERE normalized_status
   IN ('in_progress', 'in_review'). Accelerates Aging WIP (active set
   is a tiny fraction of eng_issues at ~0.5-5% of the table).

2. `idx_eng_issues_flow_completed` — partial index on
   (tenant_id, project_key, completed_at DESC) WHERE
   normalized_status = 'done' AND completed_at IS NOT NULL AND
   started_at IS NOT NULL. Accelerates baseline P85 cycle time
   (Query 2 + Query 4) and Flow Efficiency window scan (Query 3).

3. `idx_eng_issues_status_transitions_gin` — GIN on status_transitions.
   Makes jsonb_array_elements() lookups fast when parsing transition
   history for the Aging WIP age derivation and FE touch-time sum.

All created IF NOT EXISTS so the migration is idempotent, and CONCURRENTLY
is NOT used (Alembic transactional DDL friendlier, and the tenant in
scope currently has no read traffic during deploy).

Revision ID: 007_kanban_flow_health_indexes
Revises: 006_jira_discovery
Create Date: 2026-04-17
"""

from typing import Sequence, Union

from alembic import op


revision: str = "007_kanban_flow_health_indexes"
down_revision: Union[str, None] = "006_jira_discovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (1) Active WIP — partial, tiny selective slice of the table.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_eng_issues_flow_active
            ON eng_issues (tenant_id, project_key, normalized_status)
            WHERE normalized_status IN ('in_progress', 'in_review')
        """
    )

    # (2) Completed — partial, supports baseline P85 + FE window scan.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_eng_issues_flow_completed
            ON eng_issues (tenant_id, project_key, completed_at DESC)
            WHERE normalized_status = 'done'
              AND completed_at IS NOT NULL
              AND started_at IS NOT NULL
        """
    )

    # (3) GIN on JSONB — accelerates jsonb_array_elements() unnesting.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_eng_issues_status_transitions_gin
            ON eng_issues USING GIN (status_transitions)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_eng_issues_status_transitions_gin")
    op.execute("DROP INDEX IF EXISTS idx_eng_issues_flow_completed")
    op.execute("DROP INDEX IF EXISTS idx_eng_issues_flow_active")
