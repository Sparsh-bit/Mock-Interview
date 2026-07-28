"""reconcile the reports table with the Report model (schema drift repair)

Production was raising on every read of `reports`:

    UndefinedColumnError: column reports.readiness_level does not exist

The column IS declared in 001_initial_schema and IS on the model, so this is not
a missing migration — it is drift. The Supabase database was created from an
earlier schema and Alembic was stamped at a later revision, so 001 never actually
ran against it. Any column added by 001 that the hand-made table lacked has been
missing ever since, and because every SELECT on the ORM model lists all columns,
*every* read of `reports` failed — which is why an interview report could never
be generated or fetched.

Repairing rather than recreating: the table holds real rows, and this uses
ADD COLUMN IF NOT EXISTS for each column the model expects. That makes it safe on
a correct database (no-ops), sufficient on a drifted one (adds only what's
missing), and re-runnable. Every added column carries a server_default so it can
be NOT NULL without failing on existing rows.

Revision ID: 005
Revises: 004
"""

from __future__ import annotations

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels = None
depends_on = None

#: Every column 001 defines for `reports`, as (name, type, extra DDL).
#: NOT NULL columns need a default so adding them to a populated table succeeds.
_COLUMNS: list[tuple[str, str]] = [
    ("user_id", "UUID"),
    ("overall_score", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("overall_score_label", "VARCHAR(50) NOT NULL DEFAULT 'Pending'"),
    ("executive_summary", "TEXT NOT NULL DEFAULT ''"),
    ("readiness_level", "VARCHAR(30) NOT NULL DEFAULT 'needs_more_practice'"),
    ("strengths", "VARCHAR[] NOT NULL DEFAULT '{}'"),
    ("weaknesses", "VARCHAR[] NOT NULL DEFAULT '{}'"),
    ("topic_scores", "JSONB NOT NULL DEFAULT '{}'"),
    ("improvement_roadmap", "JSONB NOT NULL DEFAULT '[]'"),
    ("pdf_url", "TEXT"),
    ("is_shared", "BOOLEAN NOT NULL DEFAULT false"),
    ("raw_report", "JSONB NOT NULL DEFAULT '{}'"),
    ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("updated_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
]


def upgrade() -> None:
    bind = op.get_bind()

    # If the table itself is absent, 001 genuinely did not run and recreating it
    # here would duplicate that migration. Leave it to be resolved deliberately
    # rather than guess at the full original definition.
    exists = bind.exec_driver_sql(
        "SELECT to_regclass('public.reports') IS NOT NULL"
    ).scalar()
    if not exists:
        return

    for name, ddl in _COLUMNS:
        op.execute(f"ALTER TABLE reports ADD COLUMN IF NOT EXISTS {name} {ddl}")


def downgrade() -> None:
    # Deliberately not reversible. These columns are part of the intended schema
    # (001 declares them); dropping them would reintroduce the drift and destroy
    # report data. Nothing to undo.
    pass
