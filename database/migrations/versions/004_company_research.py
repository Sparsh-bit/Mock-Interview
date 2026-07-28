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
    # Idempotent by design. A deploy that created the table but then failed on
    # the policy below leaves the schema present WITHOUT alembic having stamped
    # this revision, so the next boot re-runs it and dies on "already exists" —
    # an unrecoverable loop, because the boot chain is `alembic && uvicorn` and a
    # migration failure means no API at all.
    bind = op.get_bind()
    already = bind.exec_driver_sql(
        "SELECT to_regclass('public.company_research') IS NOT NULL"
    ).scalar()
    if already:
        _ensure_rls()
        return

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

    _ensure_rls()


def _ensure_rls() -> None:
    """
    Enable RLS and (re)create the read policy.

    Research is public reference data, not user data: readable by any signed-in
    user, writable only by the service role (the seeder). RLS is enabled to match
    every other table in this schema rather than leaving one exception.

    Wrapped so it cannot break the deploy. `TO authenticated` depends on a role
    Supabase provides but a plain Postgres (local dev, CI) does not, and RLS on a
    reference table is a hardening measure — not worth trading the entire API's
    availability for, given the boot chain is `alembic && uvicorn`.
    """
    op.execute("ALTER TABLE company_research ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
            DROP POLICY IF EXISTS company_research_read ON company_research;
            CREATE POLICY company_research_read ON company_research
                FOR SELECT TO authenticated USING (true);
        EXCEPTION WHEN undefined_object THEN
            -- No `authenticated` role (non-Supabase Postgres). RLS stays on with
            -- no read policy, which the service-role seeder bypasses anyway.
            RAISE NOTICE 'skipped company_research_read: no authenticated role';
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS company_research_read ON company_research")
    op.drop_index("ix_company_research_lookup", table_name="company_research")
    op.drop_table("company_research")
