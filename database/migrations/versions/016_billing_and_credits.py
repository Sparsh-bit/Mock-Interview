"""Plans and the metered-usage ledger

WHY TWO TABLES RATHER THAN A `credits_remaining` COLUMN ON `users`.

`user_plans` is mutable state — which tier, and the period the allowance is measured over.
`credit_events` is an append-only ledger of consumption. Usage is a COUNT over the ledger
within the current period, never a stored counter.

A counter and the events that produced it are two stores of one fact and they drift. The
drift is silent, permanent, and attached to money: a decrement that runs twice on a client
retry charges somebody for an interview they did not get, and nothing in the system can later
prove it happened. A ledger answers "you said I had eight and I have done five" directly.

It also makes the monthly reset free. Against a counter, a reset is a scheduled job, and that
job failing is an outage that either locks every user out or gives every user unlimited use.
Against a ledger it is `WHERE created_at >= period_start` — a predicate on the read, which
cannot fail to run. `user_plans.period_start` rolls forward lazily when the row is read.

CONSTRAINTS THAT ARE LOAD-BEARING, NOT HYGIENE.

  * UNIQUE (user_id) on user_plans. The consume path takes `SELECT ... FOR UPDATE` on this
    row to serialise concurrent starts — the fix for a double-clicked Start button spending
    two of somebody's last one interview. A lock is only mutual exclusion if there is provably
    one row to take it on; two rows and the guarantee silently evaporates.

  * credit_events.session_id is ON DELETE SET NULL, not CASCADE. Deleting a session must not
    delete the record that it was paid for, or a candidate could refund themselves an
    allowance by deleting their sessions.

  * The composite index (user_id, feature, created_at) is the only read that happens inside a
    request, and it happens between the candidate pressing Start and anything appearing. In
    that column order it is an index-only range scan rather than a walk of every event the
    user has ever produced.

RLS is enabled with no policy, matching migrations 012 and 013. The app connects as the table
owner and bypasses RLS; this closes the tables to the public anon key, which reaches Postgres
through PostgREST where RLS is NOT bypassed. Getting this wrong on THESE tables is worse than
on the others: world-writable `credit_events` is not a data leak, it is unlimited free use,
and world-writable `user_plans` is a free upgrade to Pro for anyone who reads the JS bundle.

Revision ID: 016
Revises: 015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
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
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(32), nullable=False, server_default=sa.text("'free'")),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'signup'")),
        sa.Column("provider_ref", sa.String(128), nullable=True),
        # See the note above — this is the mutual-exclusion guarantee, not a tidy-up.
        sa.UniqueConstraint("user_id", name="uq_user_plans_user"),
    )
    op.create_index("ix_user_plans_user_id", "user_plans", ["user_id"])
    op.create_index("ix_user_plans_provider_ref", "user_plans", ["provider_ref"])

    op.create_table(
        "credit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature", sa.String(32), nullable=False),
        # SET NULL, not CASCADE. See the note above.
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Denormalised at write time: "what was this user entitled to AT THE TIME" is the
        # question a billing dispute asks, and reading it from the current plan row gives the
        # wrong answer the moment they upgrade.
        sa.Column("plan_id", sa.String(32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_credit_events_created_at", "credit_events", ["created_at"])
    op.create_index("ix_credit_events_user_id", "credit_events", ["user_id"])
    op.create_index("ix_credit_events_feature", "credit_events", ["feature"])
    # The hot read, inside the request path. Column order is the point.
    op.create_index(
        "ix_credit_events_user_feature_created",
        "credit_events",
        ["user_id", "feature", "created_at"],
    )

    op.execute("ALTER TABLE public.user_plans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.credit_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_credit_events_user_feature_created", table_name="credit_events")
    op.drop_index("ix_credit_events_feature", table_name="credit_events")
    op.drop_index("ix_credit_events_user_id", table_name="credit_events")
    op.drop_index("ix_credit_events_created_at", table_name="credit_events")
    op.drop_table("credit_events")
    op.drop_index("ix_user_plans_provider_ref", table_name="user_plans")
    op.drop_index("ix_user_plans_user_id", table_name="user_plans")
    op.drop_table("user_plans")
