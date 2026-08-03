"""TEMPORARY: per-feature AI token and cost ledger

WHY THIS EXISTS, AND WHY IT IS MARKED TEMPORARY.

Before pricing a credit system you have to know what a user actually costs, and
that is not a number anyone can guess: the twelve AI-backed features differ by
more than an order of magnitude per call. The interview planner buys 2500 output
tokens with reasoning enabled; answer scoring buys a few hundred against an
explicit rubric. Cache reads bill at 0.1x and cache writes at 1.25x, so the same
prompt costs different amounts depending on what ran before it.

This table records one row per billed provider call so those questions can be
answered with arithmetic instead of estimates.

IT IS SCHEDULED FOR DELETION. Once credits and subscriptions land, per-call
accounting belongs to the billing system, which will need its own schema with
guarantees this table deliberately does not have — idempotency keys, immutability,
a reconciliation trail. Keeping this one alive alongside it would mean two
disagreeing sources of truth for money. `TEMPORARY-token-counter.md` at the repo
root lists every file to remove; this migration's downgrade drops the table
cleanly and is tested.

DESIGN NOTES THAT MATTER IF YOU TOUCH THIS:

  * cost_usd is NUMERIC(12, 6), not double precision — for exactness and
    determinism, not because floats "lose money". At this scale the float error
    is around 1e-15 and invisible. What NUMERIC buys is that a SUM is exactly the
    sum of the stored rows, so a total can never disagree with the rows it was
    built from, and that the answer does not change between runs: Postgres may
    compute a double-precision aggregate in a different order under a parallel
    plan. Six decimal places holds a tenth of a millidollar, finer than any
    provider prices.

  * outcome distinguishes 'ok' from 'discarded'. A provider call that returned
    malformed JSON, or whose result failed the call site's is_valid predicate,
    was still billed in full. Those calls are invisible in a naive success-only
    ledger and they are exactly the waste worth finding — a feature whose
    discarded spend is 30% of its total has a prompt problem, not a volume
    problem.

  * user_id is ON DELETE SET NULL, not CASCADE. Deleting an account must not
    erase the record that money was spent; the cost happened whether or not the
    user still exists.

  * No foreign key on `feature`. It is the `context` string already passed at
    every generate_structured call site — the labels live in code, and a lookup
    table would mean a migration every time a feature is added.

Revision ID: 011
Revises: 010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # The `context=` label from the generate_structured call site.
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("cost_tier", sa.String(16), nullable=False),
        # 'ok' — the result was used. 'discarded' — billed and thrown away.
        sa.Column("outcome", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_usage_user_id"),
            nullable=True,
        ),
    )

    # Every query is "the last N days, grouped by something". A composite index
    # leading on created_at serves the window scan, and the trailing column lets
    # the per-feature rollup — the main view — be answered from the index.
    op.create_index("ix_ai_usage_created_at", "ai_usage", ["created_at"])
    op.create_index("ix_ai_usage_feature_created", "ai_usage", ["feature", "created_at"])
    op.create_index("ix_ai_usage_user_created", "ai_usage", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_user_created", table_name="ai_usage")
    op.drop_index("ix_ai_usage_feature_created", table_name="ai_usage")
    op.drop_index("ix_ai_usage_created_at", table_name="ai_usage")
    op.drop_table("ai_usage")
