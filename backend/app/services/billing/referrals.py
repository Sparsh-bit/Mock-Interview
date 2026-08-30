"""
Referrals — services/billing/referrals.py

THE ONLY PLACE A REFERRAL IS DECIDED, for the same reason `credits.py` is the only place
entitlement is and `offers.py` is the only place a discount is. A referral gives away
product; a second implementation of when it pays out is a second place to be wrong about
money, and this one has an attacker on the other side of it.

## What it does, in the order it happens

    GET  /referrals/me      →  `code_for` — this account's code, created on first sight
    POST /referrals/claim   →  `claim`    — a NEW account names somebody else's code
    (the new account buys something and uses it)
       inside `credits.consume`  →  `on_paid_consumption` — qualifies the referral and
                                     grants the NEW account its reward
    (the referrer next touches their own balance)
       inside `consume` / `get_balance`  →  `settle_referrer_grants` — grants the referrer

Both grants are `credits.grant(..., kind=KIND_GRANT)` — rows appended to `credit_events`.
Nothing here writes a balance, because there is no balance to write: a balance is a SUM over
that ledger and always has been.

## The usage gate, which is the whole anti-farm design

**Signup does not qualify. Neither does the trial.** A referral pays out only when the
referred account CONSUMES SOMETHING IT PAID FOR — a `credit_events` row with `kind='consume'`
and `detail->>'paid_with' = 'credit'`.

Every weaker gate is farmable and the difference is not marginal:

  * **on signup** — an email address costs nothing. A script mints accounts and credit.
  * **on first use** — `TRIAL_ALLOWANCE` includes one free communication drill, so "first
    use" costs an attacker one throwaway email and about $0.025 of our AI, and returns a
    reward on both sides. The farm is profitable on day one.
  * **on first purchase, not first use** — closer, and it still pays out for a purchase that
    can be charged back. Requiring the CONSUMPTION means the product was actually delivered
    before anything is given away.

`credits.consume` already computes `paid_with` on every consumption and stores it in the
row's `detail` — it was kept as an audit field for support questions after the report paywall
was removed. This is the second thing it is now load-bearing for, and it is why the gate
costs no extra query.

## Why the two grants are in two transactions

The referred account's reward is written inside the paying transaction, where that account's
`user_plans` row is ALREADY locked by `consume`. The referrer's is written later, the next
time the referrer touches their own balance, locking only the referrer's row.

A single transaction granting to both would routinely lock two different users' plan rows,
in an order decided by the referral graph. `Referral`'s unique index on the unordered pair
rules out the two-cycle, but a longer ring of referrals could still deadlock two `consume`
calls against each other — and `consume` sits between a candidate pressing Start and the
interview beginning, so a deadlock there is a 500 on the most important request in the
product. Splitting it means no transaction ever locks a plan row that is not its own.

The cost of the split is that a referrer's reward appears when they next load their balance
rather than at the instant it is earned. The dashboard reads the balance, so in practice that
is "the next time they look".

## Idempotency, three deep, because this is money

  1. `Referral.referred_granted_at` / `referrer_granted_at` — the cheap check, and what a
     settlement scan uses to find work.
  2. `SELECT ... FOR UPDATE` on the referral row — serialises two concurrent settlements.
  3. `credit_events.payment_ref` carries a PARTIAL UNIQUE INDEX for `referral:%` refs. Even
     a bug that gets past both of the above cannot write the second row.

Three is not paranoia here: the two grants are written by two different transactions locking
two different rows, so there is no single lock that covers both, and (3) is the only one of
the three that holds regardless of which code path arrives.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.billing import CreditEvent, Referral, ReferralCode
from app.services.billing.credits import KIND_CONSUME, KIND_GRANT, grant
from app.services.billing.plans import REFERRAL_REWARD

logger = structlog.get_logger(__name__)

#: The alphabet a code is drawn from: uppercase, digits, MINUS everything confusable.
#:
#: A referral code is read off a phone screen and typed into another one, often from a
#: screenshot in a WhatsApp group. `O`/`0`, `I`/`1`/`L` and `S`/`5` are the pairs that get
#: mistyped, and a mistyped code is indistinguishable from an invalid one — the candidate
#: concludes the feature is broken rather than that they misread a character.
#:
#: `U` is out as well, so no code can contain the vowel that turns a random string into a
#: word somebody has to read out loud in a placement cell.
_ALPHABET = "ABCDEFGHJKMNPQRTVWXYZ2346789"

#: 8 characters from a 28-symbol alphabet is ~38 bits. Not a secret — a code is meant to be
#: shared — but large enough that enumerating the space is not a way to find live accounts,
#: which matters because `POST /referrals/claim` will tell you whether a code exists.
_CODE_LENGTH = 8

#: How many times to retry on a code collision before giving up.
#:
#: At 38 bits, a collision needs the birthday bound at ~800,000 accounts to become likely at
#: all, and each retry is independent — so three is not "probably enough", it is enough by
#: several orders of magnitude. It is a bounded loop rather than a `while True` because an
#: unbounded retry against a UNIQUE index is an infinite loop the day something else is wrong
#: with the insert.
_MAX_CODE_ATTEMPTS = 3

#: The `payment_ref` prefix that the partial unique index on `credit_events` matches. Named
#: here rather than spelled inline twice: the index in models/billing.py is written against
#: this exact literal, and the two silently diverging would remove the last line of defence
#: against a double grant while every test still passed.
REF_PREFIX = "referral"


class ReferralError(AppError):
    """
    A code that cannot be claimed, with a reason the candidate can act on.

    `status_code` is set in `__init__` rather than as a class attribute, for the reason
    `offers.OfferError` records: `AppError.__init__` assigns it unconditionally, so a
    class-level value is silently overwritten and every ordinary refusal reaches the browser
    as a 500 with no message.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=400, code="REFERRAL_INVALID")


@dataclass(frozen=True)
class ReferralStatus:
    """What this account's referral page shows."""

    code: str
    #: Referrals claimed against this account's code, whatever their state.
    claimed: int
    #: Of those, how many have qualified — the referred account paid for and used something.
    qualified: int
    #: Of those, how many have actually paid this account out.
    rewarded: int
    reward_feature: str
    reward_quantity: int
    #: Who referred THIS account, if anybody, and whether it has paid out yet.
    referred_by_code: str | None = None
    referred_reward_granted: bool = False


def _new_code() -> str:
    """A fresh code. `secrets`, not `random` — this is an identifier tied to entitlement."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def normalise(code: str | None) -> str:
    """
    A typed code, in the form the unique index stores.

    Uppercased and stripped of ALL internal whitespace, not just the ends. The failure this
    prevents is real and was found in this repo's TTS voice map: a value pasted from a
    screenshot or a wrapped message can carry a space or a newline INSIDE it, which survives
    `.strip()` and produces a lookup miss that looks exactly like a wrong code.
    """
    return "".join((code or "").split()).upper()


async def code_for(db: AsyncSession, user_id: uuid.UUID) -> ReferralCode:
    """
    This account's code, created on first sight.

    LAZY CREATION RATHER THAN A SIGNUP HOOK, for the reason `credits._plan_row` gives: signup
    is not the only way a user appears here. The Supabase sync in `POST /auth/profile`
    creates them, admin tooling creates them, a restored backup has them already. A row
    created on first read cannot be missed by any of those; a hook that did not fire months
    ago leaves an account that can never refer anybody.

    Does NOT commit — the caller owns the transaction, as everywhere else in this package.
    """
    existing = await db.scalar(select(ReferralCode).where(ReferralCode.user_id == user_id))
    if existing is not None:
        return existing

    for attempt in range(_MAX_CODE_ATTEMPTS):
        row = ReferralCode(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            user_id=user_id,
            code=_new_code(),
        )
        db.add(row)
        try:
            # A SAVEPOINT, so a collision does not poison the caller's transaction. Without
            # it the failed INSERT aborts the whole transaction in Postgres and the retry
            # cannot run — and on the `consume` path that transaction is somebody's interview.
            async with db.begin_nested():
                await db.flush()
            return row
        except IntegrityError:
            # Either the code collided (astronomically unlikely at 38 bits) or another
            # request created this user's row first (a double-clicked page load, which is
            # ordinary). Re-read before retrying: if it is the second case there is now a row
            # to return and generating another code would be wrong.
            existing = await db.scalar(
                select(ReferralCode).where(ReferralCode.user_id == user_id)
            )
            if existing is not None:
                return existing
            logger.warning("referral_code_collision", attempt=attempt + 1)

    raise ReferralError("Could not allocate a referral code. Please try again.")


async def _has_ledger_history(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Has this account ever bought, been granted, or spent anything?"""
    return bool(
        await db.scalar(
            select(func.count())
            .select_from(CreditEvent)
            .where(CreditEvent.user_id == user_id)
            .limit(1)
        )
    )


async def claim(db: AsyncSession, *, user_id: uuid.UUID, code: str) -> Referral:
    """
    A new account claims somebody else's code.

    Raises `ReferralError` with a message the candidate can act on. Does not commit.

    FOUR REFUSALS, and each one closes a specific way of minting credit:

      1. THE CODE IS YOUR OWN. Self-referral, the first thing anybody tries. Refused here
         with a readable message, and refused again by `ck_referral_not_self` in the database
         — because a check in application code is only as good as the number of paths that
         reach it, and a CHECK constraint has no paths.

      2. YOU HAVE ALREADY CLAIMED ONE. Enforced by the UNIQUE index on `referred_user_id`,
         not by the count below. The count produces the message; the index produces the
         guarantee. Two tabs, a double-clicked button or a retry storm cannot all win,
         because the second INSERT fails however they interleave.

      3. THE OTHER ACCOUNT ALREADY CLAIMED YOURS. Two accounts pointing at each other is the
         cheapest possible farm, and it is also the shape that would let the two settlement
         paths lock each other's rows. Enforced by the unique index on the UNORDERED pair.

      4. YOUR ACCOUNT IS NOT NEW. This is the one that is easy to miss and expensive to get
         wrong. Without it, an established account with credits already bought could claim a
         code today and qualify on its very next consumption — a referral that referred
         nobody, paying out on usage that was going to happen anyway. "New" is defined as
         "has no `credit_events` rows at all": never bought, never spent, never been granted
         anything. That is checkable, exact, and cannot be un-done by waiting.
    """
    cleaned = normalise(code)
    if not cleaned:
        raise ReferralError("Enter a referral code.")

    owner = await db.scalar(select(ReferralCode).where(ReferralCode.code == cleaned))
    if owner is None:
        raise ReferralError("That referral code was not recognised.")

    if owner.user_id == user_id:
        raise ReferralError("You cannot use your own referral code.")

    if await _has_ledger_history(db, user_id):
        raise ReferralError(
            "Referral codes can only be applied to a new account, before your first "
            "purchase."
        )

    already = await db.scalar(
        select(Referral.id).where(Referral.referred_user_id == user_id)
    )
    if already is not None:
        raise ReferralError("You have already used a referral code.")

    mutual = await db.scalar(
        select(Referral.id).where(
            Referral.referrer_user_id == user_id,
            Referral.referred_user_id == owner.user_id,
        )
    )
    if mutual is not None:
        raise ReferralError("That account was referred by you, so you cannot use its code.")

    row = Referral(
        id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        referrer_user_id=owner.user_id,
        referred_user_id=user_id,
        code=cleaned,
    )
    db.add(row)
    try:
        # Forces every constraint above to speak NOW, inside this call, where the violation
        # can be turned into a message — rather than at commit, where it surfaces as an
        # opaque 500 after the caller has already told the candidate it worked.
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        logger.info(
            "referral_claim_rejected_by_constraint",
            user_id=str(user_id),
            referrer_id=str(owner.user_id),
            reason="a unique index or check constraint refused the pair",
        )
        raise ReferralError("That referral code cannot be used on this account.") from exc

    logger.info(
        "referral_claimed",
        code=cleaned,
        referrer_id=str(owner.user_id),
        referred_id=str(user_id),
    )
    return row


async def on_paid_consumption(db: AsyncSession, user_id: uuid.UUID) -> Referral | None:
    """
    The referred account just consumed something it PAID FOR. Qualify, and pay its side.

    Called from `credits.consume`, in that function's transaction, and ONLY when the
    consumption drew on purchased credit rather than on the trial. Returns the referral it
    qualified, or None — which is what almost every call returns, because almost every user
    was never referred.

    THE COST ON THE HOT PATH IS ONE INDEX PROBE. `referred_user_id` is UNIQUE, and the
    predicate `qualified_at IS NULL` is checked on the single row it can return. For a user
    who was never referred that is a miss on a unique index; for one who was, it fires once
    in the lifetime of the account and never again.

    Grants only the REFERRED side. The referrer is paid by `settle_referrer_grants`, in the
    referrer's own transaction — see the module docstring for why that split is not an
    optimisation.
    """
    referral = await db.scalar(
        select(Referral)
        .where(Referral.referred_user_id == user_id, Referral.qualified_at.is_(None))
        # Serialises two concurrent qualifications of the same referral. `consume` already
        # holds this user's plan row, and this row belongs to this user alone, so no other
        # transaction can be holding it and waiting on anything we hold.
        .with_for_update()
    )
    if referral is None:
        return None

    referral.qualified_at = datetime.now(UTC)

    if referral.referred_granted_at is None:
        granted = await grant(
            db,
            # `user_id`, not `referral.referred_user_id`, and they are the same value by the
            # WHERE clause above. The column is nullable — it is SET NULL on erasure — so
            # reading it back here would be a `UUID | None` that has to be narrowed for no
            # reason, when the non-null one is already in hand.
            user_id,
            REFERRAL_REWARD.feature,
            REFERRAL_REWARD.quantity,
            kind=KIND_GRANT,
            payment_ref=f"{REF_PREFIX}:{referral.id}:referred",
            detail={"reason": "referral_referred", "code": referral.code},
        )
        # `grant` returns False when this payment_ref was already applied. Stamping anyway is
        # correct and is the point of the stamp: it records that this side is settled, which
        # is exactly what "already applied" means.
        referral.referred_granted_at = datetime.now(UTC)
        if not granted:
            logger.warning(
                "referral_referred_grant_already_applied", referral_id=str(referral.id)
            )

    await db.flush()
    logger.info(
        "referral_qualified",
        referral_id=str(referral.id),
        referrer_id=str(referral.referrer_user_id),
        referred_id=str(user_id),
    )
    return referral


async def settle_referrer_grants(db: AsyncSession, user_id: uuid.UUID) -> int:
    """
    Pay this account for every referral of theirs that has qualified. Returns how many.

    Called on the paths where this user is already the subject of the transaction —
    `credits.consume` and `credits.get_balance` — so it locks nothing but rows belonging to
    this user. That is the property the whole two-transaction split exists to preserve.

    A WRITE ON WHAT LOOKS LIKE A READ PATH, DELIBERATELY, and with precedent in this package:
    `credits._plan_row` creates the user's plan row on an unlocked read for the same reason.
    The alternative is a scheduled job, and a scheduled job that does not run is entitlement
    somebody earned and never receives, with nothing in the product that would show it.

    Does not commit. On the `get_balance` path `get_db` commits at the end of the request; on
    the `consume` path the caller's transaction covers it, so a failed interview also unwinds
    the settlement — correct, because the settlement is then simply retried on the next call.
    """
    pending = (
        await db.execute(
            select(Referral)
            .where(
                Referral.referrer_user_id == user_id,
                Referral.qualified_at.isnot(None),
                Referral.referrer_granted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalars().all()

    settled = 0
    for referral in pending:
        granted = await grant(
            db,
            user_id,
            REFERRAL_REWARD.feature,
            REFERRAL_REWARD.quantity,
            kind=KIND_GRANT,
            payment_ref=f"{REF_PREFIX}:{referral.id}:referrer",
            detail={"reason": "referral_referrer", "code": referral.code},
        )
        referral.referrer_granted_at = datetime.now(UTC)
        settled += 1
        if not granted:
            logger.warning(
                "referral_referrer_grant_already_applied", referral_id=str(referral.id)
            )

    if settled:
        await db.flush()
        logger.info("referral_referrer_settled", user_id=str(user_id), count=settled)
    return settled


async def status_for(db: AsyncSession, user_id: uuid.UUID) -> ReferralStatus:
    """
    Everything the referral page renders, in one place.

    Counts rather than a list of who: the referrer has no business knowing which email
    addresses signed up under their code, and a page that names them turns a growth feature
    into a disclosure. "Three people, two of them qualified" is all the information the
    incentive needs.
    """
    row = await code_for(db, user_id)

    claimed, qualified, rewarded = (
        await db.execute(
            select(
                func.count(),
                func.count(Referral.qualified_at),
                func.count(Referral.referrer_granted_at),
            ).where(Referral.referrer_user_id == user_id)
        )
    ).one()

    mine = await db.scalar(select(Referral).where(Referral.referred_user_id == user_id))

    return ReferralStatus(
        code=row.code,
        claimed=int(claimed or 0),
        qualified=int(qualified or 0),
        rewarded=int(rewarded or 0),
        reward_feature=REFERRAL_REWARD.feature,
        reward_quantity=REFERRAL_REWARD.quantity,
        referred_by_code=mine.code if mine else None,
        referred_reward_granted=bool(mine and mine.referred_granted_at),
    )


async def qualifies_now(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """
    Has this account ever consumed something it PAID for?

    Not used by the hot path — `consume` knows the answer for the row it is about to write
    without asking. This exists for the admin view and for tests, so "why has this referral
    not paid out" has an answer that does not require reading the ledger by hand.
    """
    return bool(
        await db.scalar(
            select(func.count())
            .select_from(CreditEvent)
            .where(
                CreditEvent.user_id == user_id,
                CreditEvent.kind == KIND_CONSUME,
                CreditEvent.detail["paid_with"].astext == "credit",
            )
            .limit(1)
        )
    )
