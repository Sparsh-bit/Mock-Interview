"""report_disputes — a route of appeal against a machine-written assessment

WHY THIS TABLE EXISTS. A report states whether somebody is ready for a job interview, as a
score and a readiness level, and a language model wrote it with no human reading it first.
The candidate acts on that. The model can be wrong. Without this there is an automated
judgement about a person with no way to contest it, and the absence is worth fixing on its
own terms rather than because a particular regulation demands this exact shape.

A NEW TABLE RATHER THAN COLUMNS ON `reports`, for the deployment reason 021 and 022 both set
out at length: migrations here are applied BY HAND against Supabase, so there is always a
window where the new code is live and the schema is not. Columns on `reports` would enter
every SELECT the report page makes and 500 it for the length of that window. A new table
cannot — nothing existing reads it, so before the migration the feature simply has nothing to
show and every other path is untouched.

THE UNIQUE INDEX IS PARTIAL, and that is the whole design of it. One OPEN dispute per report
stops two taps on a slow connection becoming two rows for a human to reconcile — the same
reasoning `interview_feedback` records for its own constraint, and a unique index rather than
a read-then-write check because that check has a window in it. Partial on `status = 'open'`
so a RESOLVED dispute does not block a later one: somebody whose next report has the same
problem should not be told they already complained.

Revision ID: 028
Revises: 027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_disputes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE", name="fk_report_disputes_report"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_report_disputes_user"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("resolution", sa.String(2000), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # SET NULL, not CASCADE: an admin account being removed must not erase the fact that
        # somebody's dispute was answered.
        sa.Column(
            "resolved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_report_disputes_resolver"),
            nullable=True,
        ),
    )
    op.create_index("ix_report_disputes_report_id", "report_disputes", ["report_id"])
    op.create_index("ix_report_disputes_user_id", "report_disputes", ["user_id"])
    op.create_index("ix_report_disputes_status", "report_disputes", ["status"])
    # See the header. Partial, so a resolved dispute does not block a later one.
    op.create_index(
        "uq_report_disputes_one_open",
        "report_disputes",
        ["report_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )

    # RLS, matching every other public table. test_rls_coverage.py fails without it.
    op.execute("ALTER TABLE public.report_disputes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.report_disputes FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("report_disputes")
