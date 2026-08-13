"""
Plans and metered usage — models/billing.py

Tables: user_plans, credit_events

TWO TABLES, AND THE SPLIT IS THE DESIGN.

`user_plans` is mutable state: which tier somebody is on and when their current period ends.
There is exactly one row per user and it is overwritten on upgrade, downgrade and renewal.

`credit_events` is an append-only ledger of consumption. It is never updated and never
deleted. "How many interviews has this user used this period" is a COUNT over it, not a
counter column.

WHY A LEDGER RATHER THAN A `used_interviews` INTEGER. The same reasoning as the rating ledger
in models/progress.py, and it matters more here because this one is attached to money:

  * A counter and the events that produced it are two stores of one fact, and they drift. A
    decrement that runs twice on a retry, or not at all on a rollback, is silently wrong and
    stays wrong forever — and the direction it fails in is "customer was charged for
    something they did not get".
  * "You said I had eight interviews and I have only done five" is unanswerable against a
    counter and trivially answerable against a ledger. Billing disputes need an audit trail,
    not a number.
  * The period reset becomes free. A monthly allowance against a counter needs a scheduled
    job to zero it, and that job failing is an outage that hands everybody unlimited use or
    nobody any. Against a ledger the reset is `WHERE created_at >= period_start` — a query
    predicate, which cannot fail to run.

WHY session_id IS NULLABLE AND `SET NULL`. Same reason as the rating ledger: deleting a
session must not delete the fact that it was paid for. Cascading would let a candidate delete
their sessions to refund themselves the allowance.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Which tier a user is on, and the period their allowance is measured against.

    One row per user, enforced by a unique constraint rather than by convention — the
    consume path locks this row to serialise concurrent starts, and that lock is only a
    mutual exclusion if there is provably one row to take it on.
    """

    __tablename__ = "user_plans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    #: A plan id from services/billing/plans.py. A plain string, not an enum, because plans
    #: are product decisions that change more often than schemas should — and `get_plan`
    #: already degrades an unrecognised id to Free, so a withdrawn tier cannot lock anybody
    #: out or, worse, keep serving a plan that no longer exists.
    plan_id: Mapped[str] = mapped_column(String(32), nullable=False, default="free")

    #: The window the allowance is counted over. Stored rather than derived from created_at
    #: so an upgrade can restart the period immediately — somebody who pays on day 29 of a
    #: free month expects their eight interviews now, not tomorrow.
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: How this plan was granted: "signup", "razorpay", "admin". Kept because a free upgrade
    #: handed out by support and one that was actually paid for look identical afterwards,
    #: and only one of them should appear in revenue.
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="signup")

    #: The payment provider's own id for the subscription or order, when there is one.
    #: Nullable — the free tier has no counterpart at the provider.
    provider_ref: Mapped[str | None] = mapped_column(String(128), index=True)


class CreditEvent(Base, UUIDPrimaryKeyMixin):
    """
    One consumption of one metered feature. Append-only.

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

    #: What was started. SET NULL, not CASCADE — see the note at the top of this file.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: The plan and period this was charged against, copied at write time.
    #:
    #: Denormalised on purpose. Reading the allowance from the user's CURRENT plan row when
    #: investigating a past charge gives the wrong answer the moment they upgrade, and "what
    #: was this user entitled to at the time" is exactly the question a billing dispute asks.
    plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Room for anything the dispute needs later without a migration.
    detail: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        # THE HOT READ, and the only one that runs inside a request: "how many of this
        # feature has this user consumed since their period started". Composite and in this
        # column order so it is an index-only range scan rather than a walk of every event
        # the user has ever produced — this query sits between a candidate pressing Start
        # and the interview beginning.
        Index("ix_credit_events_user_feature_created", "user_id", "feature", "created_at"),
    )
