"""
Promo codes and offers — services/billing/offers.py

THE ONLY PLACE A DISCOUNT IS DECIDED, for the same reason `credits.py` is the only place
entitlement is. Two things compute a price and they will disagree, and when they disagree
about money one of them is giving away product.

WHAT MAKES THIS SAFE, in the order the failures actually happen:

1. THE PRICE IS NEVER SENT BY THE CLIENT. The browser sends an item id and a code; the
   server resolves both and computes the charge. This is the oldest bug in online payments
   and Razorpay would happily accept ₹1 for five interviews if we let the page name the
   figure.

2. ONE REDEMPTION PER ACCOUNT, ENFORCED BY A UNIQUE INDEX rather than by a check. A
   read-then-write check has a window between the read and the write; two tabs and a
   double-click find it. The INSERT is the check.

3. THE REDEMPTION AND THE GRANT SHARE A TRANSACTION. A code is never burned for something
   the candidate did not receive, and an item is never granted without the code being burned.
   Neither half can survive the other failing.

4. THE KILL SWITCH IS CHECKED AT REDEMPTION, not at quote time. Switching a code off stops
   it working immediately, including for somebody who was quoted a discount thirty seconds
   ago. A code that keeps working after it is switched off cannot be given to friends.

5. A FREE CODE NEVER TOUCHES RAZORPAY. Razorpay has a ₹1 minimum, so a 100% discount cannot
   be expressed as an order at all — it is a direct grant, and it is a separate `kind` rather
   than percent=100 so that path is chosen deliberately instead of arrived at by arithmetic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.billing import Offer, OfferRedemption
from app.services.billing.plans import Item

logger = structlog.get_logger(__name__)

#: Razorpay will not take an order below one rupee. A discount that lands under this is
#: not a cheap order, it is an impossible one — see `quote`, which promotes it to a free
#: grant rather than creating an order that would be rejected at the gateway.
MIN_CHARGEABLE_PAISE = 100

KIND_PERCENT = "percent"
KIND_FIXED = "fixed"
KIND_FREE = "free"
KINDS = (KIND_PERCENT, KIND_FIXED, KIND_FREE)


class OfferError(AppError):
    """
    A code that cannot be used, with a reason the candidate can act on.

    THE STATUS IS SET IN `__init__`, NOT AS A CLASS ATTRIBUTE, and that distinction was a
    live 500 on every checkout with a code applied.

    `AppError.__init__` defaults `status_code` to 500 and assigns it unconditionally, so a
    class-level `status_code = 400` is silently overwritten the moment the exception is
    constructed. "You have already used this code" — an ordinary, expected outcome — reached
    the browser as an Internal Server Error with no message, which is how a working guard
    looks identical to a crash.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=400,
            code="OFFER_INVALID",
        )


@dataclass(frozen=True)
class Quote:
    """What an item costs this account, with this code."""

    item: Item
    offer: Offer | None
    original_paise: int
    charged_paise: int

    @property
    def is_free(self) -> bool:
        """No payment at all. Grant directly; never create an order."""
        return self.charged_paise == 0

    @property
    def discount_paise(self) -> int:
        return self.original_paise - self.charged_paise


def _window_message(offer: Offer, now: datetime) -> str | None:
    """Why this code is not live, or None if it is."""
    if offer.starts_at and now < offer.starts_at:
        return "This code is not active yet."
    if offer.ends_at and now > offer.ends_at:
        return "This offer has expired."
    return None


async def find_code(db: AsyncSession, code: str) -> Offer | None:
    """
    Look a code up, case-insensitively.

    Stored uppercase and compared uppercase, so "diwali25" and "Diwali25" are the same code
    rather than one working and the other reading as a typo to the candidate.
    """
    cleaned = (code or "").strip().upper()
    if not cleaned:
        return None
    return await db.scalar(select(Offer).where(Offer.code == cleaned))


async def quote(
    db: AsyncSession,
    *,
    item: Item,
    code: str,
    user_id: uuid.UUID,
) -> Quote:
    """
    What this account would pay for this item with this code. Does NOT redeem anything.

    Raises OfferError with a message the candidate can act on — "this offer has expired" is
    useful, "invalid code" for an expired one sends them to look for a typo that is not there.

    Every check here runs again inside `redeem`, under a lock. This one exists to tell the
    candidate the price before they commit; it is not the thing that makes the rules true.
    """
    if not code:
        return Quote(item=item, offer=None, original_paise=item.price_paise,
                     charged_paise=item.price_paise)

    offer = await find_code(db, code)
    if offer is None:
        raise OfferError("That code was not recognised.")

    # Off means off, and it means it here rather than at redemption alone — quoting a
    # discount that will be refused at the till is worse than refusing it now.
    if not offer.enabled:
        raise OfferError("That code is no longer active.")

    now = datetime.now(UTC)
    if (why := _window_message(offer, now)) is not None:
        raise OfferError(why)

    if offer.applies_to and item.id not in offer.applies_to:
        raise OfferError("That code does not apply to this item.")

    # Already used by this account. Checked here for the message; the unique index in
    # `redeem` is what actually enforces it.
    used = await db.scalar(
        select(func.count())
        .select_from(OfferRedemption)
        .where(OfferRedemption.offer_id == offer.id, OfferRedemption.user_id == user_id)
    )
    if used:
        raise OfferError("You have already used this code.")

    if offer.max_redemptions is not None:
        total = await db.scalar(
            select(func.count())
            .select_from(OfferRedemption)
            .where(OfferRedemption.offer_id == offer.id)
        )
        if (total or 0) >= offer.max_redemptions:
            raise OfferError("This offer has been fully claimed.")

    charged = _apply(offer, item.price_paise)
    return Quote(
        item=item, offer=offer, original_paise=item.price_paise, charged_paise=charged
    )


def _apply(offer: Offer, price_paise: int) -> int:
    """
    The discount arithmetic. Integer paise throughout.

    Anything landing under Razorpay's one-rupee floor becomes free rather than becoming an
    order the gateway will reject — a 95%-off code on a ₹19 drill is ₹0.95, and the candidate
    should get the drill, not an error from a payment provider they never chose to involve.
    """
    if offer.kind == KIND_FREE:
        return 0
    if offer.kind == KIND_FIXED:
        charged = max(0, int(offer.value))
    elif offer.kind == KIND_PERCENT:
        pct = min(100, max(0, int(offer.value)))
        # Rounded DOWN, so rounding always favours the candidate. A discount that rounds
        # against the person using it is the kind of thing that ends up on Twitter.
        charged = price_paise - (price_paise * pct) // 100
    else:
        # An unknown kind must not silently mean "no discount" — that would charge full
        # price against a code the candidate was told would work.
        raise OfferError("That code is misconfigured. Please contact support.")

    if charged < MIN_CHARGEABLE_PAISE:
        return 0
    return min(charged, price_paise)


def charge_for(offer: Offer, item: Item) -> int:
    """
    What this item costs under this offer, recomputed from the offer row.

    Used by the WEBHOOK to check what was actually paid. It deliberately re-derives rather
    than trusting anything that travelled through the payment gateway: the order notes name
    which offer was claimed, and this decides what that offer means. Same arithmetic the
    quote used, so a legitimate payment matches exactly.
    """
    return _apply(offer, item.price_paise)


async def redeem_verified(
    db: AsyncSession,
    *,
    offer: Offer,
    item: Item,
    user_id: uuid.UUID,
    charged_paise: int,
    payment_ref: str | None,
) -> None:
    """
    Burn a code for a payment that has already arrived and been checked.

    SEPARATE FROM `redeem` BECAUSE THE MONEY IS ALREADY TAKEN. `redeem` re-validates the
    window and the kill switch, which is right before a purchase — refusing costs the
    candidate nothing but a message. Here the candidate has paid, and refusing because the
    offer expired in the ninety seconds they spent in the Razorpay widget would take their
    money and give them nothing.

    So this checks only what must still hold: that this account has not already used the
    code. That one is enforced by the unique index rather than by a check, and a violation
    means a genuine double-redemption, which the caller turns into a rejected delivery.
    """
    await _insert_redemption(
        db,
        offer=offer,
        user_id=user_id,
        item_id=item.id,
        original_paise=item.price_paise,
        charged_paise=charged_paise,
        payment_ref=payment_ref,
    )


async def _insert_redemption(
    db: AsyncSession,
    *,
    offer: Offer,
    user_id: uuid.UUID,
    item_id: str,
    original_paise: int,
    charged_paise: int,
    payment_ref: str | None,
) -> None:
    """The INSERT, and the unique index doing the enforcing. Shared by both redeem paths."""
    db.add(
        OfferRedemption(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            offer_id=offer.id,
            user_id=user_id,
            item_id=item_id,
            original_paise=original_paise,
            charged_paise=charged_paise,
            payment_ref=payment_ref,
        )
    )
    try:
        # Forces the unique index to speak now rather than at commit, so a second use is
        # refused here — where it can be turned into a clear message — instead of surfacing
        # as an opaque failure after the item has apparently been granted.
        await db.flush()
    except IntegrityError as exc:
        logger.info(
            "offer_redemption_rejected_duplicate",
            offer=offer.code,
            user_id=str(user_id),
            reason="the unique index refused a second use for this account",
        )
        raise OfferError("You have already used this code.") from exc

    logger.info(
        "offer_redeemed",
        offer=offer.code,
        kind=offer.kind,
        user_id=str(user_id),
        item=item_id,
        original_paise=original_paise,
        charged_paise=charged_paise,
        free_grant=charged_paise == 0,
    )


async def redeem(
    db: AsyncSession,
    *,
    quoted: Quote,
    user_id: uuid.UUID,
    payment_ref: str | None,
) -> None:
    """
    Burn one use of the code for this account.

    DOES NOT COMMIT, and that is the whole design. The caller grants the item in the same
    transaction, so the redemption and the grant live or die together: a code is never spent
    on something the candidate did not receive, and an item is never given away without the
    code being spent. Same rule as `credits.consume`, for the same reason.

    Re-validates everything `quote` checked. The quote may be seconds or minutes old — a code
    can be switched off, expire, or be claimed to its limit in between, and the kill switch is
    worth nothing if the only check ran before the candidate went to pay.

    Raises OfferError if the code is no longer usable. Callers must let that propagate rather
    than swallowing it and granting anyway.
    """
    offer = quoted.offer
    if offer is None:
        return

    # Re-read under a row lock. This serialises concurrent redemptions of the SAME code, which
    # is what makes max_redemptions exact rather than approximately right under load — the
    # same FOR UPDATE pattern the credit ledger uses on the plan row.
    locked = await db.scalar(select(Offer).where(Offer.id == offer.id).with_for_update())
    if locked is None:
        raise OfferError("That code was not recognised.")
    if not locked.enabled:
        raise OfferError("That code is no longer active.")

    now = datetime.now(UTC)
    if (why := _window_message(locked, now)) is not None:
        raise OfferError(why)

    if locked.max_redemptions is not None:
        total = await db.scalar(
            select(func.count())
            .select_from(OfferRedemption)
            .where(OfferRedemption.offer_id == locked.id)
        )
        if (total or 0) >= locked.max_redemptions:
            raise OfferError("This offer has been fully claimed.")

    await _insert_redemption(
        db,
        offer=locked,
        user_id=user_id,
        item_id=quoted.item.id,
        original_paise=quoted.original_paise,
        charged_paise=quoted.charged_paise,
        payment_ref=payment_ref,
    )
