"""FDD-OPS-001 Linha 5 — schema drift guard between ORM and DB.

Catches the class of bug found in INC-023 #4 (sprint 4-layer cheese):
the DB had `eng_sprints.status` column but the SQLAlchemy `EngSprint`
model didn't declare a corresponding `Mapped` column. Paths that
omitted `status` worked silently empty; paths that included it crashed
with `Unconsumed column names: status`. The bug went undetected for
months because no test compared the two sources of truth.

This test runs Alembic's autogenerate diff: given the ORM `Base.metadata`
and a live DB (with all migrations applied), it asks "what schema
operations would be needed to reach the ORM state?" If anything → drift.
Empty diff → ORM and migrations agree.

Catches:
    - column in DB but not in ORM (the INC-023 #4 case — most insidious)
    - column in ORM but not in DB (drift inverso)
    - type mismatch (e.g., String(50) in ORM vs String(100) in DB)
    - extra/missing tables on either side

Won't catch (false negatives):
    - Computed columns added via `column_property` (these aren't in
      Alembic's diff — they're SELECT expressions, not real columns).
      EngPullRequest.lead_time_hours / cycle_time_hours fall here.
    - Server-default value differences (PG normalization edge cases —
      we disable compare_server_default by default).

Connection strategy:
    - Reads `PULSE_DRIFT_TEST_DATABASE_URL` env var (sync DSN, e.g.,
      `postgresql://user:pass@host/db`). CI sets this to its postgres.
    - Falls back to `settings.database_url` (converted from async to sync)
      so dev workflow runs against the running local postgres.
    - Skips with clear message when neither is available.

The test is READ-ONLY (only inspects schema), so it can safely run
against any DB without contaminating it.
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# Fixture: sync DSN for connecting to a migrated DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sync_db_url() -> str:
    """Return a sync (psycopg2) DSN for inspecting the schema."""
    # CI / explicit override
    explicit = os.environ.get("PULSE_DRIFT_TEST_DATABASE_URL")
    if explicit:
        return explicit

    # Fall back to the application's own DB URL (async asyncpg → sync psycopg2)
    try:
        from src.config import settings
    except ImportError:
        pytest.skip(
            "Cannot import src.config.settings — set "
            "PULSE_DRIFT_TEST_DATABASE_URL env var to run this test"
        )

    db_url = getattr(settings, "database_url", None)
    if not db_url:
        pytest.skip(
            "settings.database_url not set; provide "
            "PULSE_DRIFT_TEST_DATABASE_URL env var"
        )

    # Strip async driver — Alembic + Inspector use sync (psycopg2)
    return (
        db_url
        .replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("+asyncpg", "", 1)
    )


# ---------------------------------------------------------------------------
# THE GUARD TEST
# ---------------------------------------------------------------------------

class TestORMvsDBSchemaParity:
    """REGRESSION GUARD for INC-023 #4 / FDD-OPS-001 Linha 5.

    Compares ORM `Base.metadata` vs DB schema. Any discrepancy fails
    with a precise diff message naming the field and the action needed.
    """

    def test_no_drift_between_orm_and_migrations(self, sync_db_url):
        """Alembic autogenerate finds zero changes when ORM matches DB.

        How it works:
            1. Connect to a migrated DB (live or test fixture)
            2. Use alembic.autogenerate.compare_metadata() — same engine
               that powers `alembic revision --autogenerate`
            3. Filter known false positives
            4. Assert the remaining diff is empty
        """
        try:
            from sqlalchemy import create_engine
            from alembic.migration import MigrationContext
            from alembic.autogenerate import compare_metadata
        except ImportError as exc:
            pytest.skip(f"Required deps missing: {exc}")

        # Import all models so Base.metadata is fully populated.
        # Importing one models module doesn't auto-discover others —
        # SQLAlchemy's registry only knows what's been imported.
        from src.shared.models import Base
        from src.contexts.engineering_data import models as _eng  # noqa: F401
        from src.contexts.pipeline import models as _pipe  # noqa: F401
        # metrics models live one level deeper: contexts/metrics/infrastructure/models.py
        try:
            from src.contexts.metrics.infrastructure import models as _metrics  # noqa: F401
        except ImportError:
            pass
        try:
            from src.contexts.integrations.jira.discovery import models as _jira  # noqa: F401
        except ImportError:
            pass

        engine = create_engine(sync_db_url, pool_pre_ping=True)

        try:
            with engine.connect() as conn:
                mc = MigrationContext.configure(
                    connection=conn,
                    opts={
                        "compare_type": True,
                        "compare_server_default": False,
                        "include_schemas": False,
                        # Important: exclude tenant-domain tables that aren't
                        # declared in our ORM (none today, but kept for safety).
                        "include_object": _include_object,
                    },
                )
                diffs = compare_metadata(mc, Base.metadata)
        finally:
            engine.dispose()

        filtered = self._filter_false_positives(diffs)

        if filtered:
            self._fail_with_friendly_message(filtered)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_false_positives(diffs: list) -> list:
        """Drop drift entries that are noise vs real bugs.

        We KEEP only the drifts that cause the INC-023#4-class of silent
        bug — column presence on either side, or type mismatch:
            ✅ add_column / remove_column  (the swiss-cheese case)
            ✅ add_table   / remove_table  (orphan tables)
            ✅ modify_type                  (VARCHAR(50) vs VARCHAR(100))

        We DROP cosmetic drift that doesn't affect runtime behavior:
            ❌ add_index / remove_index    (ORM rarely names indices the
               same as migrations; runtime queries don't care about
               index existence vs migration mismatch — Postgres uses
               whatever exists)
            ❌ modify_comment              (column COMMENT in DB; ORM
               doesn't carry these by default)
            ❌ modify_nullable             (migration vs ORM nullability
               can drift cosmetically — e.g., TenantModel.created_at
               server_default vs migration's nullable=True. Real bugs
               here are caught at INSERT time anyway.)
            ❌ modify_default              (compare_server_default=False
               in MigrationContext, but Alembic still emits these
               sometimes — drop for consistency)
        """
        IGNORED_TABLES = {
            "alembic_version",
            "migrations",
            # Tables managed by other layers (TypeORM in pulse-api or raw SQL),
            # not by SQLAlchemy ORM in pulse-data. The pulse-data drift guard
            # only checks tables that pulse-data is authoritative for.
            #
            # IAM (pulse-api TypeORM):
            "users",
            "memberships",
            "tenants",
            "iam_organizations",
            "iam_teams",
            "teams",
            "organizations",
            # Integration / connection management (pulse-api TypeORM):
            "connections",
            "integration_connections",
            # Jira discovery (raw SQL via pulse-data discovery service,
            # not via SQLAlchemy ORM):
            "tenant_jira_config",
            "jira_project_catalog",
            "jira_discovery_audit",
        }
        # Postgres GENERATED-AS-STORED columns. These are physical columns
        # in the DB but the ORM models them as `column_property` (computed
        # at SELECT time via the same formula). Two equivalent paths;
        # filter out so the guard doesn't false-positive on this pattern.
        # If a future column drift is masked by this allowlist, the column
        # name should be added here with a clear comment.
        IGNORED_COMPUTED_COLUMNS = {
            ("eng_pull_requests", "lead_time_hours"),
            ("eng_pull_requests", "cycle_time_hours"),
            ("eng_issues", "lead_time_hours"),
            ("eng_issues", "cycle_time_hours"),
        }
        # Operations that cause real silent bugs (the INC-023#4 class).
        # Anything else is cosmetic noise that we filter out.
        REAL_BUG_OPS = {
            "add_column",
            "remove_column",
            "add_table",
            "remove_table",
            "modify_type",
        }
        filtered = []
        for entry in diffs:
            # Some operations come back as a list of tuples (modify_* groups).
            # Recurse one level into them.
            if isinstance(entry, list):
                inner_filtered = [
                    e for e in entry
                    if isinstance(e, tuple)
                    and e and e[0] in REAL_BUG_OPS
                    and (len(e) < 3 or e[2] not in IGNORED_TABLES)
                ]
                if inner_filtered:
                    filtered.append(inner_filtered)
                continue

            if not isinstance(entry, tuple) or not entry:
                continue
            op = entry[0]
            if op not in REAL_BUG_OPS:
                continue

            # Skip ignored tables (alembic_version is auto-managed)
            if op in ("add_table", "remove_table"):
                table_name = getattr(entry[1], "name", None)
                if table_name in IGNORED_TABLES:
                    continue
            elif op in ("add_column", "remove_column", "modify_type"):
                table_name = entry[2] if len(entry) >= 3 else None
                if table_name in IGNORED_TABLES:
                    continue
                # Skip Postgres GENERATED columns mapped via column_property
                col_name = None
                if op in ("add_column", "remove_column"):
                    col_obj = entry[3] if len(entry) >= 4 else None
                    col_name = getattr(col_obj, "name", None)
                elif op == "modify_type":
                    # tuple shape: (op, schema, table, column_name, ...)
                    col_name = entry[3] if len(entry) >= 4 else None
                if (table_name, col_name) in IGNORED_COMPUTED_COLUMNS:
                    continue

            filtered.append(entry)
        return filtered

    @staticmethod
    def _fail_with_friendly_message(diffs: list) -> None:
        """Format the diff into an actionable error message."""
        lines = [
            "",
            "═" * 78,
            "FDD-OPS-001 Linha 5 — SCHEMA DRIFT DETECTED between ORM and DB",
            "═" * 78,
            "",
            f"{len(diffs)} discrepancy(ies) found:",
            "",
        ]
        for entry in diffs:
            if isinstance(entry, list):
                # nested modify_* group
                for sub in entry:
                    lines.append(f"  ❌ {sub}")
                continue
            op = entry[0] if isinstance(entry, tuple) else "?"
            if op == "add_column":
                # Column in ORM but not in DB → migration is missing
                _, schema, table, col = entry
                lines.append(
                    f"  ❌ ORM declares but DB lacks: {table}.{col.name} "
                    f"({col.type}). MISSING MIGRATION — run "
                    f"`alembic revision --autogenerate` to create one."
                )
            elif op == "remove_column":
                # Column in DB but not in ORM → INC-023 #4 scenario!
                _, schema, table, col = entry
                lines.append(
                    f"  ❌ DB has but ORM lacks: {table}.{col.name} "
                    f"({col.type}). SCHEMA DRIFT — add `Mapped[...] = "
                    f"mapped_column(...)` to the model. "
                    f"This is the INC-023 #4 swiss-cheese scenario."
                )
            elif op == "add_table":
                lines.append(
                    f"  ❌ ORM declares table not in DB: "
                    f"{entry[1].name}. Missing migration."
                )
            elif op == "remove_table":
                lines.append(
                    f"  ❌ DB has table not in ORM: {entry[1].name}. "
                    f"Either model is missing or migration created an "
                    f"orphan."
                )
            elif op in ("modify_type", "modify_nullable"):
                lines.append(f"  ❌ {op}: {entry}")
            else:
                lines.append(f"  ❌ {op}: {entry}")

        lines += [
            "",
            "Why this matters: silent ORM↔DB drift caused INC-023 (sprint",
            "status field empty in 100% of 216 sprints across the entire",
            "Webmotors tenant). Paths that omit drifted columns work; paths",
            "that include them crash. Bug stayed hidden for months.",
            "",
            "How to fix:",
            "  - Column in DB, not ORM: add `Mapped[...]` to the model class",
            "  - Column in ORM, not DB: create migration via",
            "    `alembic revision --autogenerate -m 'description'`",
            "  - Type mismatch: align both — change ORM OR migration to match",
            "═" * 78,
        ]
        pytest.fail("\n".join(lines), pytrace=False)


# ---------------------------------------------------------------------------
# Helper: Alembic include_object filter
# ---------------------------------------------------------------------------

def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Filter at the inspection level — exclude objects we don't want compared.

    Args (per Alembic API):
        obj: SQLAlchemy schema object (Table, Column, Index, …)
        name: object name
        type_: 'table' | 'column' | 'index' | 'unique_constraint' …
        reflected: True if from DB, False if from ORM
        compare_to: the object being compared against (or None)

    Currently a no-op (returns True for everything). Reserved for cases
    where we deliberately don't manage a table/column via the ORM.
    """
    return True
