"""Add issue_key column to eng_issues for PR linking.

Revision ID: 005
Revises: 004
Create Date: 2026-04-13

The external_id for Jira issues is the internal numeric ID (e.g. "792543"),
not the human-readable key (e.g. "SECOM-1441"). PR titles/branches reference
the key, so linking PRs to issues requires storing the key explicitly.
"""

from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eng_issues",
        sa.Column("issue_key", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_eng_issues_issue_key",
        "eng_issues",
        ["tenant_id", "issue_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_eng_issues_issue_key", table_name="eng_issues")
    op.drop_column("eng_issues", "issue_key")
