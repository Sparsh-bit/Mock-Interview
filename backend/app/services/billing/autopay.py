"""
Auto top-up — services/billing/autopay.py

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT. It is not a subscription. This product removed
subscriptions on purpose: asking a student to bet ₹299 on using the app enough to justify it
is the reason most of them never start, and `plans.py` opens by saying so. Auto top-up keeps
"you buy what you use" and removes only the interruption — running out at eleven at night
before a drive buys the next pack instead of putting a paywall in the way.

THE RULES, in the order they protect somebody's money:

1. OFF UNLESS EXPLICITLY TURNED ON. Money leaving an account without its owner pressing
   anything is the fastest way to lose their trust. It names the exact item and price when
   they enable it, and it is revocable from the same screen.

2. ONE ATTEMPT PER WINDOW. A declined card retried on every request is a card the bank
   blocks, and a wall of decline SMS from their bank rather than one message from us.

3. IT SWITCHES ITSELF OFF AFTER REPEATED FAILURES. A card that has declined three times will
   decline again. Continuing to try is not persistence, it is noise on somebody's statement.

4. IT NEVER BLOCKS THE THING THEY WERE DOING. A charge is attempted alongside the paywall,
   never in front of it: if the top-up succeeds they carry on, and if it fails they see the
   ordinary purchase screen. An interview must never wait on a payment gateway.

5. ENTITLEMENT STILL COMES FROM THE WEBHOOK. This asks Razorpay to charge a saved token; the
   items are granted when the payment webhook confirms capture, through exactly the same path
   a manual purchase takes. There is no second granting path to keep correct.

WHAT NEEDS LIVE KEYS. `charge_saved_token` is the one function here that talks to Razorpay,
and like `create_order` it raises PaymentNotConfiguredError until the keys are set rather than
pretending. Everything else — eligibility, the throttle, the failure counter, the disable
rule — is pure and tested.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UserPlan
from app.services.billing.plans import Item, get_item

logger = structlog.get_logger(__name__)

#: How long after an attempt before another may be made.
#:
#: Six hours, not minutes. The failure mode being prevented is a declined card retried on
#: every request — a bank blocks that, and the user gets a wall of decline messages. Six
#: hours is long enough to be obviously deliberate and short enough that somebody who fixes
#: their card in the morning is topped up by the afternoon.
RETRY_WINDOW = timedelta(hours=6)

#: Consecutive failures before auto top-up switches itself off.
#:
#: Three. A card that has declined three times will decline a fourth, and the honest response
#: is to stop and say so rather than keep quietly failing against somebody's statement.
MAX_FAILURES = 3


def is_eligible(plan: UserPlan, *, now: datetime | None = None) -> tuple[bool, str]:
    """
    May we attempt an automatic charge for this account right now?

    Returns (allowed, reason). The reason is for logs, not for the candidate — a user who
    has not enabled this should never see a message about it.
    """
    now = now or datetime.now(UTC)

    if not plan.autopay_enabled:
        return False, "not enabled"
    if plan.is_banned:
        # A suspended account must not be charged. Taking money from somebody who cannot use
        # the product is the worst possible combination.
        return False, "account suspended"
    if not plan.autopay_item_id or not plan.autopay_token:
        # Enabled but never completed. Treated as off rather than as an error: the mandate
        # setup can be abandoned halfway, and that must not become a charge.
        return False, "no saved mandate"
    if plan.autopay_failures >= MAX_FAILURES:
        return False, "disabled after repeated failures"
    if plan.autopay_last_attempt_at is not None:
        last = plan.autopay_last_attempt_at
        if last.tzinfo is None:
            # Postgres returns tz-aware, but a naive value from a fixture or an older row
            # would otherwise raise on comparison and take an interview down with it.
            last = last.replace(tzinfo=UTC)
        if now - last < RETRY_WINDOW:
            return False, "attempted too recently"

    if get_item(plan.autopay_item_id) is None:
        # The saved item no longer exists in the catalogue — a price change or a removed
        # bundle. Charging the nearest thing would be inventing a purchase.
        return False, "saved item is no longer sold"

    return True, "ok"


def item_for(plan: UserPlan) -> Item | None:
    """The item this account tops up with, resolved from the catalogue."""
    return get_item(plan.autopay_item_id) if plan.autopay_item_id else None


async def record_attempt(db: AsyncSession, plan: UserPlan, *, succeeded: bool) -> None:
    """
    Note that a charge was tried.

    The timestamp moves on EVERY attempt, success or failure — it is the throttle, and a
    successful charge that did not move it would allow an immediate second one.

    The failure counter resets on success, because three failures spread over three months
    with successes between them is a card that mostly works, not a card that is dead.
    """
    plan.autopay_last_attempt_at = datetime.now(UTC)
    if succeeded:
        plan.autopay_failures = 0
    else:
        plan.autopay_failures += 1
        if plan.autopay_failures >= MAX_FAILURES:
            # Switched off rather than left to keep failing. The user is told on their next
            # visit; continuing to try is noise on their statement and ours.
            plan.autopay_enabled = False
            logger.warning(
                "autopay_disabled_after_failures",
                user_id=str(plan.user_id),
                failures=plan.autopay_failures,
            )
    await db.flush()


async def get_plan(db: AsyncSession, user_id: uuid.UUID) -> UserPlan | None:
    return await db.scalar(select(UserPlan).where(UserPlan.user_id == user_id))


async def charge_saved_token(plan: UserPlan, item: Item) -> str:
    """
    Ask Razorpay to charge the saved instrument. Returns the payment id.

    THE ONLY FUNCTION HERE THAT NEEDS CREDENTIALS, deliberately, so everything above it is
    testable today. Raises PaymentNotConfiguredError until the keys are set rather than
    returning a fake id — a stub that looks like it worked is how a charge that never
    happened grants somebody five interviews.

    THE AMOUNT COMES FROM THE RESOLVED ITEM, exactly as it does for a manual purchase. The
    saved item id is on the plan row; its price is looked up here.

    ENTITLEMENT IS NOT GRANTED HERE. This creates a payment; the webhook grants the items
    when Razorpay confirms capture, through the same path a manual purchase takes. One
    granting path is the only way to keep the idempotency and the amount checks true.
    """
    from app.core.config import settings  # noqa: PLC0415
    from app.services.billing.razorpay import (  # noqa: PLC0415
        _NOTES_ITEM_KEY,
        _NOTES_USER_KEY,
        PaymentNotConfiguredError,
    )

    key_id = getattr(settings, "RAZORPAY_KEY_ID", "") or ""
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "") or ""
    if not key_id or not key_secret:
        raise PaymentNotConfiguredError

    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.razorpay.com/v1/payments/create/recurring",
            auth=(key_id, key_secret),
            json={
                "amount": item.price_paise,
                "currency": "INR",
                "customer_id": plan.autopay_customer_id,
                "token": plan.autopay_token,
                "recurring": "1",
                "description": item.name,
                # The same notes a manual order carries, so the webhook reads a recurring
                # payment through exactly the code path it reads every other payment with.
                "notes": {
                    _NOTES_ITEM_KEY: item.id,
                    _NOTES_USER_KEY: str(plan.user_id),
                },
            },
        )

    if resp.status_code >= 400:
        logger.warning(
            "autopay_charge_failed",
            user_id=str(plan.user_id),
            status=resp.status_code,
            body=resp.text[:300],
        )
        raise RuntimeError(f"razorpay recurring charge failed: {resp.status_code}")

    payment_id = str((resp.json() or {}).get("id") or "")
    logger.info(
        "autopay_charged",
        user_id=str(plan.user_id),
        item=item.id,
        amount_paise=item.price_paise,
        payment_id=payment_id,
    )
    return payment_id


async def try_top_up(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """
    Attempt an automatic top-up. Returns True only if a charge was actually created.

    NEVER RAISES, and that is the contract that lets it be called from the paywall path. A
    payment gateway being slow or down must not turn "you are out of interviews" into an
    error page — the candidate sees the ordinary purchase screen and can pay by hand.

    Returns False for every ineligible case too, which the caller treats identically: show
    the paywall.
    """
    plan = await get_plan(db, user_id)
    if plan is None:
        return False

    allowed, reason = is_eligible(plan)
    if not allowed:
        logger.debug("autopay_skipped", user_id=str(user_id), reason=reason)
        return False

    item = item_for(plan)
    if item is None:
        return False

    try:
        await charge_saved_token(plan, item)
    except Exception as exc:  # noqa: BLE001 — see the contract above
        logger.info("autopay_attempt_failed", user_id=str(user_id), error=str(exc)[:200])
        await record_attempt(db, plan, succeeded=False)
        return False

    await record_attempt(db, plan, succeeded=True)
    return True
