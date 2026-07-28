"""relax NOT NULL on reports columns the application does not manage

Production was failing every INSERT into `reports`:

    NotNullViolationError: null value in column "hire_recommendation"
    of relation "reports" violates not-null constraint

`hire_recommendation` appears nowhere in this codebase — not in any migration, not
on the Report model. It is a leftover from the hand-made schema the Supabase
database was originally created with (the same origin as the drift 005 repaired).

Because no code knows the column exists, nothing can ever populate it. A NOT NULL
constraint on a column the application cannot write is not a data-integrity
guarantee — it is a permanent, unfixable write block: every report INSERT fails,
forever, no matter what the application does. Relaxing it is therefore the correct
resolution rather than a workaround.

Dropping the constraint, not the column: the column may hold data from whatever
created it, and destroying columns this codebase never defined is not this
migration's business. Existing values are preserved; new rows simply leave it NULL.

Deliberately driven by information_schema against an explicit snapshot of the
columns the application manages, rather than by importing the live models. A
migration must describe a fixed point in history — importing models would make
this file's behaviour change silently as the models evolve.

Revision ID: 006
Revises: 005
"""

from __future__ import annotations

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels = None
depends_on = None

#: Columns the Report model owns, as of this revision. Anything else on the table
#: is unmanaged: the application never writes it, so it must not be able to block
#: the application's writes.
_MANAGED_COLUMNS = frozenset(
    {
        "id",
        "session_id",
        "user_id",
        "overall_score",
        "overall_score_label",
        "executive_summary",
        "readiness_level",
        "strengths",
        "weaknesses",
        "topic_scores",
        "improvement_roadmap",
        "pdf_url",
        "is_shared",
        "raw_report",
        "created_at",
        "updated_at",
    }
)


def upgrade() -> None:
    bind = op.get_bind()

    if not bind.exec_driver_sql(
        "SELECT to_regclass('public.reports') IS NOT NULL"
    ).scalar():
        return

    # Unmanaged, NOT NULL, and no default => guaranteed insert failure.
    # A column with a default can populate itself, so it is left alone.
    rows = bind.exec_driver_sql(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'reports'
          AND is_nullable = 'NO'
          AND column_default IS NULL
        """
    ).fetchall()

    for (column,) in rows:
        if column in _MANAGED_COLUMNS:
            continue
        # Quoted to survive any identifier the original schema used.
        op.execute(f'ALTER TABLE reports ALTER COLUMN "{column}" DROP NOT NULL')


def downgrade() -> None:
    # Not reversible, and must not be. Restoring NOT NULL would recreate a
    # constraint the application cannot satisfy, breaking report generation again.
    pass
