"""Add `description` column to eng_issues for Flow Health drawer.

FDD-KB-013 — Expose the Jira issue description (plain text) in the
Flow Health drawer so users can triage aging items without leaving the
dashboard. The API returns a 300-char truncated version; storage caps
at 4000 chars (see connector/normalizer + backfill service).

Design:
- `description` is nullable (legacy issues + Jira issues with empty
  description are the common case).
- Partial index on `(tenant_id)` WHERE description IS NOT NULL — lets
  the backfill admin endpoint cheaply count/scan unpopulated rows per
  tenant without an enum-wide index.

Anti-surveillance: description is issue-level (no assignee/reporter).
It CAN contain PII typed by humans in the ticket body — downstream
consumers (Flow Health endpoint) truncate and never log full text.

Revision ID: 008_eng_issues_description
Revises: 007_kanban_flow_health_indexes
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "008_eng_issues_description"
down_revision: Union[str, None] = "007_kanban_flow_health_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable — legacy rows stay NULL until the admin backfill runs.
    op.add_column(
        "eng_issues",
        sa.Column("description", sa.Text(), nullable=True),
    )

    # Partial index: tenant scan of populated descriptions. Supports admin
    # coverage queries ("X/Y issues have description") without bloating
    # the index with millions of NULL rows.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_eng_issues_description_populated
            ON eng_issues (tenant_id)
            WHERE description IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_eng_issues_description_populated")
    op.drop_column("eng_issues", "description")
