"""Pay-per-item entitlement, and credential-sharing detection

TWO CHANGES THAT ARRIVE TOGETHER because both reshape `user_plans`.

## 1. Subscriptions become a trial plus purchases

Migration 016 modelled a monthly subscription: a plan id and a rolling 30-day window on
`user_plans`, with usage counted inside that window. That is the wrong shape for campus
students, who want three interviews the week before a drive and nothing for two months —
they overpay in quiet months and feel metered in busy ones.

The replacement is one free trial of each feature, then a fixed price per item with no
expiry. Concretely:

  * `user_plans` loses `plan_id`, `period_start`, `period_end` and `provider_ref`. It keeps
    only its identity as the per-user row, because `consume` takes `SELECT ... FOR UPDATE`
    on it to serialise concurrent starts.
  * `credit_events` gains `kind` and a SIGNED `delta`, and loses `plan_id`/`period_start`.
    A balance is now one `SUM(delta)` plus the trial constant, rather than a COUNT inside a
    window. One sum cannot disagree with itself; two counts subtracted from each other are
    two places to filter wrongly and get a plausible wrong number.
  * `payment_ref` moves onto `credit_events`, where the idempotency check belongs now that a
    payment grants items rather than changing a plan.

THE PERIOD COLUMNS ARE DROPPED RATHER THAN LEFT NULLABLE. Purchased items do not expire, so
they can never be correct again, and a nullable date column that used to mean something is
the kind of thing a future reader writes a WHERE clause against.

Existing rows are migrated rather than discarded: any consumption recorded under 016 becomes
a `kind='consume', delta=-1` row, so nobody's history is rewritten in their favour or
against them.

## 2. Credential-sharing detection

`user_sessions` records where an account is being used from. The detector compares the
active IPs for one account and bans on a genuine overlap.

WHY A TABLE RATHER THAN REDIS. A ban is a moderation decision with an appeal attached, and
the evidence for it has to survive a cache eviction and a restart — "we banned you, and we
no longer have the record of why" is not a position to defend to somebody who has paid.
Redis still fronts the hot path; this is the durable record.

The ban flags live on `user_plans` rather than on `users` because `consume` already locks
that row, so the ban is read under the same lock that decides whether to spend an interview
— no second query, and no window between the two checks.

RLS is enabled with no policy, matching 012, 013 and 016. The app connects as the table
owner and bypasses RLS; this closes the tables to the public anon key, which reaches
Postgres through PostgREST where RLS is NOT bypassed. On these tables that matters
especially: world-writable `credit_events` is unlimited free use, and world-writable
`user_plans` would let anyone clear their own ban.

Revision ID: 017
Revises: 016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── credit_events: signed ledger ──────────────────────────────────────
    op.add_column("credit_events", sa.Column("kind", sa.String(16), nullable=True))
    op.add_column("credit_events", sa.Column("delta", sa.Integer(), nullable=True))
    op.add_column("credit_events", sa.Column("payment_ref", sa.String(128), nullable=True))

    # Backfill before the NOT NULLs go on. Every row written under 016 was a consumption —
    # that schema had no other kind of entry — so they become -1 consumes and existing
    # balances are preserved exactly.
    op.execute("UPDATE credit_events SET kind = 'consume', delta = -1 WHERE kind IS NULL")

    op.alter_column("credit_events", "kind", nullable=False)
    op.alter_column("credit_events", "delta", nullable=False)
    op.create_index("ix_credit_events_kind", "credit_events", ["kind"])
    op.create_index("ix_credit_events_payment_ref", "credit_events", ["payment_ref"])

    op.drop_index("ix_credit_events_user_feature_created", table_name="credit_events")
    op.create_index("ix_credit_events_user_feature", "credit_events", ["user_id", "feature"])
    op.drop_column("credit_events", "plan_id")
    op.drop_column("credit_events", "period_start")

    # ── user_plans: no plan, no period, but a ban ─────────────────────────
    op.add_column(
        "user_plans",
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("user_plans", sa.Column("ban_reason", sa.String(200), nullable=True))
    op.add_column("user_plans", sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_plans", sa.Column("appeal_text", sa.Text(), nullable=True))
    op.add_column("user_plans", sa.Column("appeal_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "user_plans",
        sa.Column("unbanned_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_user_plans_is_banned", "user_plans", ["is_banned"])

    op.drop_index("ix_user_plans_provider_ref", table_name="user_plans")
    op.drop_column("user_plans", "provider_ref")
    op.drop_column("user_plans", "plan_id")
    op.drop_column("user_plans", "period_start")
    op.drop_column("user_plans", "period_end")

    # ── user_sessions: where an account is being used from ────────────────
    op.create_table(
        "user_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Truncated /24 for IPv4 and /48 for IPv6 rather than the exact address — see
        # services/security/sharing.py. A phone that changes IP inside its carrier's range
        # is the single largest source of false positives, and the whole prefix belongs to
        # one network, so comparing prefixes rather than addresses removes that class of
        # wrong ban without weakening the real signal.
        sa.Column("ip_prefix", sa.String(64), nullable=False),
        # Hashed, never raw. It is a fingerprint of the browser, it identifies a person, and
        # storing it in the clear buys nothing the hash does not.
        sa.Column("agent_hash", sa.String(64), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # One row per (user, prefix, agent). Upserted on every authenticated request, so
        # without this the table would grow by a row per request.
        sa.UniqueConstraint(
            "user_id", "ip_prefix", "agent_hash", name="uq_user_sessions_identity"
        ),
    )
    # The detector's only read: this user's rows seen recently.
    op.create_index(
        "ix_user_sessions_user_last_seen",
        "user_sessions",
        ["user_id", sa.text("last_seen_at DESC")],
    )

    op.execute("ALTER TABLE public.user_sessions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_last_seen", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.add_column("user_plans", sa.Column("period_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "user_plans", sa.Column("period_start", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "user_plans",
        sa.Column("plan_id", sa.String(32), nullable=False, server_default=sa.text("'free'")),
    )
    op.add_column("user_plans", sa.Column("provider_ref", sa.String(128), nullable=True))
    op.create_index("ix_user_plans_provider_ref", "user_plans", ["provider_ref"])
    op.drop_index("ix_user_plans_is_banned", table_name="user_plans")
    for col in ("unbanned_count", "appeal_at", "appeal_text", "banned_at", "ban_reason", "is_banned"):
        op.drop_column("user_plans", col)

    op.add_column(
        "credit_events", sa.Column("period_start", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("credit_events", sa.Column("plan_id", sa.String(32), nullable=True))
    op.drop_index("ix_credit_events_user_feature", table_name="credit_events")
    op.create_index(
        "ix_credit_events_user_feature_created",
        "credit_events",
        ["user_id", "feature", "created_at"],
    )
    op.drop_index("ix_credit_events_payment_ref", table_name="credit_events")
    op.drop_index("ix_credit_events_kind", table_name="credit_events")
    op.drop_column("credit_events", "payment_ref")
    op.drop_column("credit_events", "delta")
    op.drop_column("credit_events", "kind")
