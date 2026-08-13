"""
Entitlement and the ban flag — models/billing.py

Tables: user_plans, credit_events

`credit_events` is an append-only, SIGNED ledger. A purchase is +n, a consumption is -1, and
a user's balance for a feature is one `SUM(delta)` plus the one-time trial constant. There
is no stored balance anywhere.

`user_plans` holds no balance either. It exists for two things: to be the single per-user
row that `consume` takes a `SELECT ... FOR UPDATE` on — which is what stops a double-clicked
Start button spending the same interview twice — and to carry the credential-sharing ban,
so the ban can be read under that same lock rather than in a second query with a window
between them.

WHY A SIGNED LEDGER RATHER THAN A `credits_remaining` INTEGER. It is attached to money:

  * A counter and the events that produced it are two stores of one fact, and they drift.
    A decrement that runs twice on a retry, or not at all on a rollback, is silently wrong
    and stays wrong forever — and it fails in the direction of "charged for something they
    did not get".
  * "You said I had five interviews and I have only done three" is unanswerable against a
    counter and trivial against a ledger. Billing disputes need an audit trail, not a number.
  * One SUM cannot disagree with itself, where two counts subtracted from each other are two
    places to filter wrongly and get a number that is plausible and wrong.

THERE IS NO PERIOD, AND ITS ABSENCE IS THE SIMPLIFICATION. This replaced a monthly
subscription whose allowance was measured in a rolling 30-day window, which needed
period_start/period_end on every row, lazy roll-forward on read, and a catch-up loop for
dormant users — each of them a place to be wrong about somebody's money. Purchased items do
not expire, so all of that is gone and a user who buys in March and spends in September
simply gets what they paid for.

THE TRIAL IS A CONSTANT, NOT ROWS. It is added to the sum at read time rather than granted
at signup, so changing it changes what every existing account has left — the right behaviour
for a promotional allowance, and impossible once it has been written as rows.

WHY session_id IS NULLABLE AND `SET NULL`. Deleting a session must not delete the record
that it was paid for; cascading would let somebody refund themselves by deleting sessions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One row per user: the consume lock, and the ban.

    The unique constraint on user_id is load-bearing rather than hygiene. `consume` takes
    `SELECT ... FOR UPDATE` on this row to serialise concurrent starts, and a lock is only
    mutual exclusion if there is provably one row to take it on.
    """

    __tablename__ = "user_plans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    #: How the account was created: "signup", "admin".
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="signup")

    # ── Credential-sharing ban ────────────────────────────────────────────
    #
    # Lives here rather than on `users` because this row is already the per-user lock
    # target that `consume` takes, so the ban can be read under the same lock that decides
    # whether to spend an interview — no second query, and no window between the two.
    is_banned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    ban_reason: Mapped[str | None] = mapped_column(String(200))
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: What the user said when appealing. Nullable, and separate from `ban_reason` so an
    #: admin reading a queue can see our reason and their explanation side by side.
    appeal_text: Mapped[str | None] = mapped_column(Text)
    appeal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Set when an admin lifts a ban, so a repeat offender is visible as one.
    unbanned_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class CreditEvent(Base, UUIDPrimaryKeyMixin):
    """
    One movement of entitlement — bought, granted or spent. Append-only.

    Deliberately NOT TimestampMixin: `updated_at` on an append-only row is a column that can
    only ever lie, and its presence invites somebody to write an UPDATE against a table whose
    entire correctness rests on never being updated.
    """

    __tablename__ = "credit_events"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: "interview" | "gd" | "communication" — see plans.Feature.
    feature: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    #: "purchase" | "consume" | "grant". See the KIND_* constants in credits.py.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    #: SIGNED. +n for a purchase or grant, -1 for a consumption, so a balance is one
    #: SUM(delta) rather than two counts subtracted from each other. Two counts is two
    #: places to filter wrongly and get a number that is plausible and wrong; one sum
    #: cannot disagree with itself.
    delta: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The payment id this entry came from, for purchases. Indexed because the webhook
    #: checks it on every delivery to stay idempotent — Razorpay redelivers until it gets a
    #: 2xx, and without this check one payment grants its items several times.
    payment_ref: Mapped[str | None] = mapped_column(String(128), index=True)

    #: What was started. SET NULL, not CASCADE — see the note at the top of this file.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Room for anything the dispute needs later without a migration.
    detail: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        # THE HOT READ, and the only one that runs inside a request: this user's net
        # balance for one feature. Composite and in this column order so the SUM is an
        # index-only scan of just their rows rather than a walk of the whole table — it
        # sits between a candidate pressing Start and the interview beginning.
        Index("ix_credit_events_user_feature", "user_id", "feature"),
    )
