"""INC-006 — Sprint transitions JSONB on eng_issues.

Adds `eng_issues.sprint_transitions` to capture each issue's history of
sprint membership changes (entered/exited a sprint, with timestamp).
Mirrors the storage shape of `status_transitions` so the same
write-on-upsert pattern applies.

Why a column on `eng_issues` (not a separate table):
  - 1:N where N is small (most issues touch 0-3 sprints)
  - Always read with the issue (sprint scope service queries
    eng_issues filtered by `sprint_transitions @> [{...}]`)
  - Avoids a join + an index on sprint_id for the common case
  - Matches the precedent set by `status_transitions` (INC-020)

Why JSONB (not normalized rows):
  - Same reasoning as status_transitions — sequence is naturally a list
  - Postgres JSONB indexes via GIN make the lookup queries fast
  - No additional foreign keys to maintain

Schema of each transition entry:
    {
      "sprint_id": "jira:JiraSprint:1:42",
      "action":    "entered" | "exited",
      "at":        "2026-04-15T14:30:00+00:00"
    }

Order: entries appended chronologically (sorted by `at` ASC).

Revision ID: 015_sprint_transitions
Revises: 014_squad_qualification
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op


# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision: str = "015_sprint_transitions"
down_revision: Union[str, None] = "014_squad_qualification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE eng_issues
            ADD COLUMN sprint_transitions JSONB DEFAULT '[]'::jsonb
        """
    )

    # GIN index for "find issues that ever touched sprint X" — used by the
    # sprint scope service to avoid a sequential scan on the larger tenants.
    # Keyed on the JSONB column directly; the service queries
    # `sprint_transitions @> '[{"sprint_id":"..."}]'::jsonb`.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eng_issues_sprint_transitions
            ON eng_issues
            USING GIN (sprint_transitions jsonb_path_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_eng_issues_sprint_transitions")
    op.execute("ALTER TABLE eng_issues DROP COLUMN IF EXISTS sprint_transitions")
