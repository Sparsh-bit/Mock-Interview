"""how the candidate rated the interview

Adds `interview_feedback`: one star rating per interview session, plus an optional comment.

A SEPARATE TABLE RATHER THAN COLUMNS ON `interview_sessions`, for the same deployment reason
set out in 021. Migrations here are applied BY HAND against Supabase (docs/DEPLOY.md), so there
is always a window where the new code is live and the schema is not, and the only question that
matters is what breaks during it.

Columns on `interview_sessions` would put the new fields into every SELECT against the busiest
table in the product — every question served, every answer stored, every report generated — so
the interview itself would 500 until somebody remembered to run this. A new table cannot do
that: nothing existing reads it, so before the migration the feedback feature simply has
nothing to show and every other path carries on exactly as before.

NOT NAMED `ratings`, AND NOT `rating_events`. `rating_events` already exists and is the
ELO-style ledger of how well a candidate PERFORMED. This is how well the PRODUCT performed.
Two tables both called some form of "rating" is how a query ends up joining the wrong one.

ONE ROW PER SESSION, enforced by UNIQUE on `session_id` rather than by the endpoint checking
first. A read-then-write check has a window between the read and the write, and two taps on a
slow connection land in it — the same reasoning as the unique index on offer redemptions.

THE 1-5 RANGE IS A DATABASE CONSTRAINT as well as a Pydantic one. The request model is one
refactor away from being bypassed by a fixture, a backfill or a background job, and a zero-star
or 400-star row would silently skew the only aggregate anybody looks at.

CASCADE ON DELETE on both foreign keys. Feedback about a deleted interview is feedback about
nothing, and account deletion has to be able to remove it — `admin.delete_user` relies on
database cascades rather than the ORM, because an ORM delete NULLs children instead of removing
them and that is what made account deletion 500 once already.

Revision ID: 022
Revises: 021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interview_feedback",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("stars >= 1 AND stars <= 5", name="ck_interview_feedback_stars"),
    )
    op.create_index(
        "ix_interview_feedback_session_id", "interview_feedback", ["session_id"], unique=True
    )
    op.create_index("ix_interview_feedback_user_id", "interview_feedback", ["user_id"])

    # ── ROW LEVEL SECURITY, BECAUSE SUPABASE EXPOSES EVERY PUBLIC TABLE ──────────────────
    #
    # A new table in `public` is reachable through PostgREST with the anon key the moment it
    # exists. Without RLS this one would let anybody read every comment any candidate has
    # written. `test_rls_coverage.py` fails the build on a table that skips this, which is why
    # it is here rather than remembered later.
    op.execute("ALTER TABLE interview_feedback ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_interview_feedback_user_id", table_name="interview_feedback")
    op.drop_index("ix_interview_feedback_session_id", table_name="interview_feedback")
    op.drop_table("interview_feedback")
