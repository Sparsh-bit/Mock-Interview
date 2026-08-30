"""referral codes, referrals, and the three constraints that make them un-farmable

A referral gives away entitlement, so every rule about who may earn one is worth exactly as
much as the thing enforcing it. Three of them are in this file rather than in application
code, because each is the kind of check that reads fine in Python and loses to two tabs:

  1. ONE REDEMPTION PER NEW ACCOUNT — `referrals.referred_user_id` is UNIQUE. A second claim
     is a constraint violation, not a race the second request can win.

  2. NO SELF-REFERRAL — `ck_referral_not_self`. The service refuses it first with a message
     somebody can read; this is what holds on any path the service does not cover, including
     paths that do not exist yet.

  3. NO MUTUAL REFERRAL — a unique index on the UNORDERED pair,
     (LEAST(referrer, referred), GREATEST(referrer, referred)), so (A refers B) and (B refers
     A) collide. Two accounts crediting each other is the cheapest farm available, and it is
     also the shape that would let the two settlement transactions lock each other's rows.
     Ruling out the pair rules out both problems with one index.

## The fourth constraint is on an existing table, and it is the interesting one

`credit_events.payment_ref` has always been indexed and never unique. `credits.grant` says
plainly why: "a partial unique index on `payment_ref` is the other correct answer and is a
better long-term shape — but it needs a migration, and a migration that fails on pre-existing
duplicates fails the deploy... The index is worth adding later, without launch pressure, as
belt and braces."

`uq_credit_events_referral_ref` is that index, scoped with `WHERE payment_ref LIKE
'referral:%'` — the one prefix for which the objection cannot apply, because no row has ever
carried it. It is what makes double-crediting a referral impossible at the DATABASE, which
matters here more than anywhere else in the ledger: a referral's two grants are written by
two DIFFERENT transactions, locking two different users' rows, so no single lock covers both.

If this migration fails on that index, it means rows with a `referral:` payment_ref already
exist and something has already double-granted. Do not drop the WHERE clause to get past it.

## Two new tables rather than a column on `users`

The reason 021 through 024 all set out, and that models/user.py records the cost of:
migrations here are applied BY HAND against Supabase, so there is always a window where the
code is live and the schema is not. SQLAlchemy names every mapped column in its SELECT, so a
`users.referral_code` column deployed before its migration would 500 every read of the users
table — which is every authenticated request in the product. A missing TABLE breaks only the
feature that reads it.

RLS is enabled with no policies, matching every other table in this schema. The app connects
as the owner and bypasses RLS; the blanket deny is what keeps PostgREST shut, and PostgREST
matters because the anon key ships in the browser bundle. A `referral_codes` table readable
through it would hand every code in the product to anyone who opened dev tools.

Revision ID: 025
Revises: 024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

#: The tables this migration creates, named once with the `public.` prefix below.
#:
#: This exact shape is what tests/test_rls_coverage.py scans for, and that test is what stops
#: a new table reaching Supabase readable through PostgREST. 018 learned this the hard way:
#: written first as an inline tuple, its RLS was invisible to the scanner.
_TABLES: list[str] = ["referral_codes", "referrals"]

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referral_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # CASCADE, unlike every other user reference in the billing schema. A code is a live
        # credential rather than a financial record: the grants it produced are retained in
        # `credit_events`, and a code that outlived its owner would keep crediting an account
        # that no longer exists.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
    )
    op.create_index("ix_referral_codes_created_at", "referral_codes", ["created_at"])
    op.create_index("ix_referral_codes_user_id", "referral_codes", ["user_id"])
    op.create_index("ix_referral_codes_code", "referral_codes", ["code"])

    op.create_table(
        "referrals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # SET NULL on both sides: an erased account must not take with it the record of what
        # it earned or what it was given. services/legal/retention.py stamps
        # `retained_subject` on the row first, matching on EITHER side, so the surviving row
        # stays joinable to the credit_events grant it explains and to nobody.
        sa.Column(
            "referrer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "referred_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("code", sa.String(16), nullable=False),
        # NULL until the referred account consumes something it PAID for. Signup does not
        # qualify and neither does the trial — see services/billing/referrals.py.
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referred_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referrer_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retained_subject", sa.String(64), nullable=True),
        # NO SELF-REFERRAL. Written to tolerate NULLs so that erasure — which sets one or
        # both sides to NULL — cannot violate a constraint on a row that has been sitting
        # there legitimately for a year.
        sa.CheckConstraint(
            "referrer_user_id IS NULL OR referred_user_id IS NULL "
            "OR referrer_user_id <> referred_user_id",
            name="ck_referral_not_self",
        ),
    )
    op.create_index("ix_referrals_created_at", "referrals", ["created_at"])
    op.create_index("ix_referrals_referrer_user_id", "referrals", ["referrer_user_id"])
    op.create_index("ix_referrals_referred_user_id", "referrals", ["referred_user_id"])
    op.create_index("ix_referrals_code", "referrals", ["code"])
    op.create_index("ix_referrals_qualified_at", "referrals", ["qualified_at"])
    op.create_index("ix_referrals_retained_subject", "referrals", ["retained_subject"])
    # The settlement scan: "which of my referrals have qualified and not yet paid me".
    op.create_index(
        "ix_referrals_settlement", "referrals", ["referrer_user_id", "qualified_at"]
    )
    # NO MUTUAL REFERRAL. `LEAST`/`GREATEST` on two uuids is stable, so (A,B) and (B,A)
    # produce the same entry and the second INSERT fails.
    op.execute(
        "CREATE UNIQUE INDEX uq_referral_unordered_pair ON public.referrals ("
        "LEAST(referrer_user_id, referred_user_id), "
        "GREATEST(referrer_user_id, referred_user_id))"
    )

    # ── THE ONE CHANGE TO AN EXISTING TABLE ──────────────────────────────────────────────
    #
    # See the module docstring. Partial, so it cannot fail on the history that made a full
    # unique index on `payment_ref` unsafe to add.
    op.execute(
        "CREATE UNIQUE INDEX uq_credit_events_referral_ref ON public.credit_events "
        "(payment_ref) WHERE payment_ref LIKE 'referral:%'"
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_credit_events_referral_ref")
    op.drop_table("referrals")
    op.drop_table("referral_codes")
