"""
Activity Log — 003_activity_logs.py
Revision: 003

Adds the activity_logs table: a unified feed of every completed activity a
candidate does (interview, group discussion, communication round, quiz) so the
reports/history surface can show all of them in one place.

RLS is enabled with no permissive policies, matching migration 002 — the
backend connects directly via asyncpg and never relies on Supabase PostgREST,
so this fully denies anon/authenticated API access while leaving the backend
unaffected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "activity_logs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("details", JSONB(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_activity_logs_user_id", "activity_logs", ["user_id"])
    op.create_index(
        "ix_activity_logs_user_created", "activity_logs", ["user_id", "created_at"]
    )
    op.execute("ALTER TABLE public.activity_logs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE public.activity_logs DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_activity_logs_user_created", table_name="activity_logs")
    op.drop_index("ix_activity_logs_user_id", table_name="activity_logs")
    op.drop_table("activity_logs")
