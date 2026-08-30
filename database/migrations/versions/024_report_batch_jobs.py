"""report_jobs — remembering work that outlives the request that started it

A report generated through Anthropic's Message Batches API is answered on the provider's
schedule, not inside the HTTP call. That is worth about half the price of the most expensive
thing this product does (docs/AI-COST-MODEL.md), and it means the work survives the request —
so something has to hold the batch id and what each part of it was for until somebody comes
back to collect.

WHY THE UNIQUE INDEX ON session_id IS THE POINT OF THIS MIGRATION. It is not tidiness. It is
what makes "one batch attempt per session, ever" a property of the database rather than of a
code path somebody can later add a branch to. Two rows for one session would mean two batches
billed for one report, racing each other to write it — and, worse, a session that could keep
resubmitting, which is the failure the whole design exists to rule out: a report that is
never stuck is one where every route out of the cheap path ends somewhere a report gets
written.

A FAILED JOB'S ROW IS KEPT, DELIBERATELY. The terminal row is exactly what routes the session
to the synchronous path for good. Deleting it on failure would make the session look untried.

A NEW TABLE RATHER THAN COLUMNS ON `reports`, for the deployment reason 021, 022 and 023 all
set out: migrations here are applied by hand against Supabase, so there is always a window
where the code is live and the schema is not. During that window a missing COLUMN breaks
every SELECT against the table; a missing TABLE breaks only the feature that reads it, and
the batch path is written to fall back to synchronous generation when anything about it
fails. So the pre-migration window costs full-price reports rather than no reports.

Revision ID: 024
Revises: 023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="processing"
        ),
        # custom_id -> what that part was asked to do. The Batches API returns results in
        # COMPLETION order, so this mapping is the only link between a response and the
        # questions it was supposed to grade.
        sa.Column(
            "parts", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("lookup_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("strategy", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ONE JOB PER SESSION. See the module docstring — this constraint is the safety
    # property, not an index for speed.
    op.create_index(
        "ix_report_jobs_session_id", "report_jobs", ["session_id"], unique=True
    )
    op.create_index("ix_report_jobs_user_id", "report_jobs", ["user_id"])
    # Polling and collection both start from the provider's batch id.
    op.create_index("ix_report_jobs_batch_id", "report_jobs", ["batch_id"])
    # Finding jobs still in flight, for an operator asking "is anything stuck?". Partial,
    # because the answer is only ever about the processing ones and they are the minority.
    op.create_index(
        "ix_report_jobs_processing",
        "report_jobs",
        ["created_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )

    # ROW LEVEL SECURITY, BECAUSE SUPABASE EXPOSES EVERY PUBLIC TABLE. A new table in
    # `public` is reachable through PostgREST with the anon key the moment it exists, and
    # the anon key ships in the browser bundle. This one carries session and user ids.
    # test_rls_coverage.py fails the build on a table that skips this.
    op.execute("ALTER TABLE report_jobs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """
    Fully reversible, and losing nothing that cannot be regenerated.

    Dropping this table forgets any batch still in flight. That is not data loss in the way
    dropping a report would be: the affected sessions simply generate their reports
    synchronously at full price the next time anyone opens them, which is the same fallback
    every other failure in this path takes. Money, not information.
    """
    op.drop_index("ix_report_jobs_processing", table_name="report_jobs")
    op.drop_index("ix_report_jobs_batch_id", table_name="report_jobs")
    op.drop_index("ix_report_jobs_user_id", table_name="report_jobs")
    op.drop_index("ix_report_jobs_session_id", table_name="report_jobs")
    op.drop_table("report_jobs")
