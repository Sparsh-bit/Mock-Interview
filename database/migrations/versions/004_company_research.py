"""company_research: cached interview intelligence per company/program

Stores the rounds, previously-asked questions and focus topics for a company's
interview process, so the interviewer can be grounded in what that company
actually asks without paying for a live web search on every session.

Revision ID: 004
Revises: 003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: str | None = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_research",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_slug", sa.String(length=64), nullable=False),
        # "" means the row applies to every program for this company, so a
        # lookup for an unknown program can still fall back to something.
        sa.Column("program_slug", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("company_name", sa.String(length=128), nullable=False),
        sa.Column("program_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("rounds", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("previous_questions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("focus_topics", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tips", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_slug", "program_slug", name="uq_company_research_company_program"
        ),
    )
    op.create_index(
        "ix_company_research_lookup",
        "company_research",
        ["company_slug", "program_slug"],
    )

    # Research is public reference data, not user data: readable by any signed-in
    # user, writable only by the service role (the seeder). RLS is enabled to
    # match every other table in this schema rather than leaving one exception.
    op.execute("ALTER TABLE company_research ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY company_research_read ON company_research
        FOR SELECT TO authenticated USING (true)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS company_research_read ON company_research")
    op.drop_index("ix_company_research_lookup", table_name="company_research")
    op.drop_table("company_research")
