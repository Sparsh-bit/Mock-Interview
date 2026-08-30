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

    # ── Auto top-up ───────────────────────────────────────────────────────
    #
    # AUTO TOP-UP, NOT A SUBSCRIPTION, and the difference is the product decision this app
    # already made. A subscription asks a student to bet ₹299 on using the product enough to
    # justify it; the store exists because that bet is the reason most of them never start.
    # This keeps "you buy what you use" and removes only the interruption: when you run out
    # mid-preparation, the next pack is bought for you instead of a paywall appearing the
    # evening before a drive.
    #
    # OFF BY DEFAULT AND OPTED INTO EXPLICITLY. Money leaving somebody's account without them
    # pressing anything is the single easiest way to lose their trust, so it is never the
    # default, it names the exact item and price, and it is revocable from the same screen.
    autopay_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    #: Which item is bought when the balance runs out. An item id from plans.ITEMS, resolved
    #: server-side to its price — the browser never names what gets charged.
    autopay_item_id: Mapped[str | None] = mapped_column(String(64))

    #: Razorpay's token for the saved payment instrument, from a mandate the user authorised.
    #:
    #: A TOKEN, NOT A CARD. Razorpay holds the instrument; this is an opaque reference that
    #: is useless anywhere else, so a database leak does not become a card leak. Nothing in
    #: this app ever sees a card number.
    autopay_token: Mapped[str | None] = mapped_column(String(128))

    #: Razorpay's id for the customer the token belongs to. Required alongside the token to
    #: charge it, and stored separately because one customer can have several instruments.
    autopay_customer_id: Mapped[str | None] = mapped_column(String(128))

    #: The last charge attempt, successful or not.
    #:
    #: THE THROTTLE. A failed card that is retried on every request is a card the bank blocks
    #: and a user who gets a wall of declines from their bank rather than from us. One
    #: attempt per window, decided against this timestamp.
    autopay_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Consecutive failures. Auto top-up switches ITSELF off after a few, because a card that
    #: has declined three times is a card that will decline again, and the honest response is
    #: to stop trying and tell the user rather than to keep quietly failing.
    autopay_failures: Mapped[int] = mapped_column(
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

    #: NULLABLE, AND SET NULL RATHER THAN CASCADE, since migration 023. This is a
    #: financial record: the Companies Act §128(5) requires eight financial years of
    #: books, and DPDP §8(7) makes erasure yield to a retention obligation under
    #: another law. Cascading it away on account deletion destroyed records the
    #: business is required to hold. It is NULL for exactly one reason — the account
    #: was erased — and `retained_subject` is then what identifies the row's cohort.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: Set only when the owning account is erased: a salted one-way digest of the user
    #: id, written by services/legal/retention.py in the same transaction as the
    #: delete. Keeps the surviving financial rows joinable to each other — which is
    #: what makes a later refund dispute reconcilable — and to nobody.
    #:
    #: `deferred=True` IS LOAD-BEARING, NOT A PERFORMANCE TWEAK. models/user.py
    #: records what happens when a mapped column ships before its migration: SQLAlchemy
    #: names every mapped column in its SELECT, so the reads against this table would
    #: 500 in the window between deploying the code and running 023 by hand against
    #: Supabase — and the read on this table sits between a candidate pressing Start
    #: and the interview beginning. Deferred columns are left out of the default
    #: SELECT, so only the erasure path touches this one, and only that path can fail.
    retained_subject: Mapped[str | None] = mapped_column(
        String(64), index=True, deferred=True
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


class Offer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A promo code, a festival offer, or a private 100%-off code for friends.

    ONE TABLE FOR ALL THREE, because they differ only in their fields. A Diwali offer is a
    public code with an end date; a friends code is a private one with `enabled` flipped by
    hand; a ₹1 launch offer is a fixed-price code. Modelling them separately would mean three
    redemption paths and three places for the single-use rule to be wrong.

    ONE REDEMPTION PER ACCOUNT, ALWAYS, AND THE DATABASE ENFORCES IT. `offer_redemptions`
    carries a unique constraint on (offer_id, user_id), so two requests racing to redeem the
    same code for the same account cannot both succeed however they interleave — the second
    INSERT fails. A read-then-write check in application code has a window between the read
    and the write, and on something attached to money that window WILL be found.

    There is deliberately no `per_user_limit` column. It was drafted and removed: a value
    above 1 would contradict the unique constraint that makes the rule true, so the field
    would have been a setting that either did nothing or corrupted the guarantee depending on
    which code path read it. A code that can be used twice is a different feature and would
    need a different key; until it is asked for, once per account is the whole rule and there
    is exactly one thing enforcing it.

    `enabled` is the kill switch and it is checked at redemption time, so turning a code off
    stops it working for everybody immediately — including anybody mid-checkout who has
    already been quoted a discounted price. That is deliberate: a code that keeps working
    after it is switched off is not a code that can be given to friends.
    """

    __tablename__ = "offers"

    #: Typed by a human, matched case-insensitively. Stored uppercase so the index is exact
    #: and "diwali25", "Diwali25" and "DIWALI25" cannot become three different offers.
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)

    #: What the candidate sees. Public offers render this on the store; private ones never
    #: appear anywhere, so it is only for the admin list.
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    #: "percent" | "fixed" | "free".
    #:
    #: `free` is not `percent` with value 100. A 100% discount produces a zero-rupee order,
    #: and Razorpay has a ₹1 minimum — so `free` skips the payment gateway entirely and
    #: grants the item directly, which is a materially different code path that must be
    #: chosen explicitly rather than fallen into by arithmetic.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Percent (1-100) for "percent"; the final price in PAISE for "fixed"; ignored for
    #: "free". Paise for the same reason prices are: a rupee figure as a float is a rounding
    #: bug waiting for the first ₹49.50.
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Item ids this applies to. Empty list means every item.
    applies_to: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    #: THE KILL SWITCH. Checked on every redemption, so switching it off is immediate.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    #: Whether the store lists it. False keeps a code entirely out of every public response —
    #: the friends code must not be discoverable by reading the offers endpoint.
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: The window. Both nullable: an offer with no start is live now, one with no end runs
    #: until it is switched off.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Total redemptions allowed across all users. NULL is unlimited.
    max_redemptions: Mapped[int | None] = mapped_column(Integer)

    #: Whether redeeming this code requires passing a captcha.
    #:
    #: Per-offer rather than global: a ₹1 public launch offer is worth farming with scripts
    #: and needs one, while a private code shared with four friends does not — and a captcha
    #: on everything trains people to click through it.
    requires_captcha: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Who created it, for the audit trail. SET NULL so removing an admin does not delete
    #: the record of an offer they made.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # The store lists public, enabled offers and orders them by window. One index rather
        # than a scan on a table that is read on every visit to the pricing page.
        Index("ix_offers_public_enabled", "is_public", "enabled", "ends_at"),
    )


class OfferBanner(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    The promo image for one offer: shown on the dashboard, links to the apply-a-code box.

    A SEPARATE TABLE RATHER THAN COLUMNS ON `Offer`, and the reason is this project's
    deployment shape rather than modelling taste. Migrations are run BY HAND against Supabase,
    so there is always a window where new code is live and the schema is not. Columns on
    `offers` would put `SELECT offers.banner_url ...` on every read of that table — the pricing
    page, the quote, checkout, redemption — and 500 the entire paid path until somebody
    remembered to migrate. Nothing existing reads this table, so before the migration the
    feature simply has nothing to show and every money path is untouched.

    ONE PER OFFER, by a unique constraint rather than by the endpoint checking first: two
    admins uploading at once cannot leave two rows where the reader expects one.

    THE DIMENSIONS ARE COLUMNS, not just the URL, so the admin list can say whether an image
    matches the required ratio without re-downloading it to find out.
    """

    __tablename__ = "offer_banners"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    #: Where the file sits in the bucket. Kept because deleting or replacing a banner has to
    #: delete the FILE too, and a public URL cannot be turned back into a storage path
    #: reliably once the bucket's URL format changes.
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)

    #: NOT NULL, because a banner is a LINK. Without an accessible name a screen reader
    #: announces an unlabelled link to the pricing page, which is the same defect as an
    #: icon-only button with no aria-label.
    alt_text: Mapped[str] = mapped_column(String(160), nullable=False)

    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class OfferRedemption(Base, UUIDPrimaryKeyMixin):
    """
    One account, one use of one code. Append-only.

    THE UNIQUE CONSTRAINT IS THE FEATURE. `per_user_limit` is almost always 1, and this is
    what makes that true under concurrency: two tabs, a double-click, or a retry storm cannot
    all redeem the same code for the same account, because the second INSERT violates the
    constraint and the transaction rolls back.

    Written in the SAME transaction as the grant it pays for. If the grant fails the
    redemption unwinds with it, so a code is never burned for something the candidate did not
    receive — the same rule `credits.consume` follows for the same reason.

    Not TimestampMixin: `updated_at` on an append-only row can only ever lie.
    """

    __tablename__ = "offer_redemptions"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: NULLABLE and SET NULL since 023, for the reason on CreditEvent.user_id, plus one
    #: that is not about law at all: the unique constraint below is what stops a
    #: single-use code being redeemed twice, so cascading the row away made
    #: delete-and-re-register a way to reuse any code.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    #: Set only when the owning account is erased: a salted one-way digest of the user
    #: id, written by services/legal/retention.py in the same transaction as the
    #: delete. Keeps the surviving financial rows joinable to each other — which is
    #: what makes a later refund dispute reconcilable — and to nobody.
    #:
    #: `deferred=True` IS LOAD-BEARING, NOT A PERFORMANCE TWEAK. models/user.py
    #: records what happens when a mapped column ships before its migration: SQLAlchemy
    #: names every mapped column in its SELECT, so the reads against this table would
    #: 500 in the window between deploying the code and running 023 by hand against
    #: Supabase — and the read on this table sits between a candidate pressing Start
    #: and the interview beginning. Deferred columns are left out of the default
    #: SELECT, so only the erasure path touches this one, and only that path can fail.
    retained_subject: Mapped[str | None] = mapped_column(
        String(64), index=True, deferred=True
    )

    #: What they bought with it, and what it saved them. Kept for the audit trail: "why is
    #: this account's revenue lower than its usage" has to be answerable.
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    original_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    charged_paise: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The Razorpay payment this rode on, or NULL for a free grant that never touched the
    #: gateway. Nullable precisely because `free` codes skip payment entirely.
    payment_ref: Mapped[str | None] = mapped_column(String(128), index=True)

    __table_args__ = (
        # THE RULE, in the only place that can actually hold it. One row per (offer, user),
        # so a double-clicked Apply, two tabs, or a retry storm cannot redeem the same code
        # twice for one account — the second INSERT simply fails.
        Index("uq_offer_redemption_user", "offer_id", "user_id", unique=True),
    )
