"""FDD-DSH-050 — MTTR incident pairing columns on eng_deployments (INC-005 fix).

Adds the 3 columns needed to compute Mean Time to Recovery from existing
Jenkins deploy data, plus the index that supports the per-(repo,environment)
pairing query.

Schema additions on eng_deployments:
  - recovered_by_deploy_id  UUID NULL  → FK to eng_deployments.id (success that resolved)
  - superseded_by_deploy_id UUID NULL  → groups back-to-back failures into ONE incident
  - incident_status         VARCHAR(16) NULL  → 'open' | 'resolved' | 'superseded'
                                                 (NULL when is_failure=false and not a success-target)

Index strategy:
  - Partial index on (tenant_id, repo, environment, deployed_at) WHERE
    environment IN ('production','prod'). Supports the LATERAL/window-function
    pairing query without bloating with non-prod rows.

Decision rationale (see docs/fdd/FDD-DSH-050-mttr-design.md):
  - Self-referential columns on `eng_deployments` instead of a separate
    `eng_incidents` table — single SELECT for MTTR aggregation, RLS preserved.
  - String + CHECK constraint instead of Postgres ENUM type — flexible
    ALTER, matches `normalized_status` precedent.
  - All 3 columns nullable — backwards-compatible, zero data migration risk.
  - FDD-OPS-001 L5 schema-drift guard auto-validates on next worker startup.

Revision ID: 013_mttr_incident_pairing
Revises: 012_pipeline_progress
Create Date: 2026-04-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "013_mttr_incident_pairing"
down_revision: Union[str, None] = "012_pipeline_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add MTTR pairing columns + index."""
    op.add_column(
        "eng_deployments",
        sa.Column(
            "recovered_by_deploy_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="FK to the eng_deployments row that resolved this failure",
        ),
    )
    op.add_column(
        "eng_deployments",
        sa.Column(
            "superseded_by_deploy_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment=(
                "When set, this row is a back-to-back failure absorbed into "
                "an earlier incident anchored at superseded_by_deploy_id."
            ),
        ),
    )
    op.add_column(
        "eng_deployments",
        sa.Column(
            "incident_status",
            sa.String(16),
            nullable=True,
            comment=(
                "open | resolved | superseded. NULL when row isn't a "
                "failure-anchor (i.e., is_failure=false or never paired)."
            ),
        ),
    )

    # CHECK constraint enforces the enum without using Postgres ENUM type
    # (per design decision C — easier to ALTER if values change).
    op.create_check_constraint(
        "ck_eng_deploy_incident_status",
        "eng_deployments",
        "incident_status IS NULL OR incident_status IN ('open','resolved','superseded')",
    )

    # Self-referential FKs — ON DELETE SET NULL so we never lose the
    # failure row if its successor is purged for retention.
    op.create_foreign_key(
        "fk_eng_deploy_recovered_by",
        "eng_deployments",
        "eng_deployments",
        ["recovered_by_deploy_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_eng_deploy_superseded_by",
        "eng_deployments",
        "eng_deployments",
        ["superseded_by_deploy_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Partial index for the pairing query. PRODUCTION-ONLY mirror of the
    # INC-008 filter (CFR + DF only count prod). Smaller index = faster
    # window-function scan during backfill and forward-link.
    op.execute(
        "CREATE INDEX ix_eng_deploy_mttr_pairing "
        "ON eng_deployments (tenant_id, repo, environment, deployed_at) "
        "WHERE environment IN ('production','prod')"
    )

    # Helper index for the "find still-open incidents" query (operator UI
    # + repair cron). Tiny (only failure-anchors with status='open').
    op.execute(
        "CREATE INDEX ix_eng_deploy_open_incidents "
        "ON eng_deployments (tenant_id, repo, deployed_at) "
        "WHERE incident_status = 'open'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_eng_deploy_open_incidents")
    op.execute("DROP INDEX IF EXISTS ix_eng_deploy_mttr_pairing")
    op.drop_constraint(
        "fk_eng_deploy_superseded_by", "eng_deployments", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_eng_deploy_recovered_by", "eng_deployments", type_="foreignkey",
    )
    op.drop_constraint(
        "ck_eng_deploy_incident_status", "eng_deployments", type_="check",
    )
    op.drop_column("eng_deployments", "incident_status")
    op.drop_column("eng_deployments", "superseded_by_deploy_id")
    op.drop_column("eng_deployments", "recovered_by_deploy_id")
