"""
The store and the balance — api/v1/billing.py

GET  /billing/items     — what you can buy and what it costs. The only public route here.
GET  /billing/me        — what this account has left.
POST /billing/checkout  — open a Razorpay order for one item.
POST /billing/webhook   — Razorpay confirms a payment; the items are granted here.

THE BALANCE ROUTE IS INFORMATIONAL, NOT A GATE. The UI reads it to render what is left and
to decide whether to show the purchase sheet before somebody starts something. It is not
what stops an exhausted user: `consume` does that inside each metered endpoint's own
transaction, and it re-reads under a row lock rather than trusting anything this route said.
A client that ignores this endpoint entirely still cannot start what it has not paid for.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.session import get_db
from app.models.billing import CreditEvent, UserPlan
from app.services.billing import captcha, offers, razorpay
from app.services.billing.credits import (
    KIND_GRANT,
    KIND_PURCHASE,
    _plan_row,
    get_balance,
    grant,
)
from app.services.billing.plans import ITEMS, get_item, trial_allowance

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing", tags=["Billing"])

_checkout_rate_limit = rate_limiter(
    limit=10,
    window_seconds=3600,
    key_builder=lambda user_id: f"rate_limit:checkout:{user_id}:hourly",
    action="starting a purchase",
)



# ─── Schemas ──────────────────────────────────────────────────────────────────


class ItemOut(BaseModel):
    id: str
    feature: str
    quantity: int
    price_rupees: int
    price_paise: int
    name: str
    tagline: str


class FeatureBalanceOut(BaseModel):
    feature: str
    label: str
    granted: int
    used: int
    remaining: int
    #: How many of `granted` came from the free trial rather than from a purchase.
    #:
    #: CARRIED SO THE CLIENT CAN TELL A FREE ATTEMPT FROM A PAID ONE. `granted` is trial plus
    #: everything bought, so on its own it cannot answer "is this one free" — and the client
    #: needs to, because the warning shown when somebody is about to abandon an interview says
    #: something materially different in each case. "Your free interview will be wasted" is
    #: true and motivating for a candidate on the trial, and simply wrong for one who bought a
    #: five-pack; guessing would mean telling paying customers they are losing something free.
    #:
    #: Derived from plans.py rather than stored, so it moves with the allowance.
    trial_allowance: int


class BalanceOut(BaseModel):
    features: list[FeatureBalanceOut]
    trial_started: bool
    #: Operator account — not metered. The UI shows "unlimited" rather than a countdown.
    unlimited: bool = False
    #: Whether this account may see the admin pages.
    #:
    #: CARRIED HERE SO THE UI DOES NOT HAVE TO PROBE FOR IT. The sidebar used to answer "am I
    #: an admin" by calling /admin/overview and watching for a 403 — which works, and costs
    #: three refused requests and three warning log lines on every page load for every
    #: ordinary user. A 403 is the correct response to that probe and a completely normal
    #: state, so logging it as a warning made a healthy system look like it was under attack.
    #:
    #: SEPARATE FROM `unlimited` even though both are currently true for the same accounts.
    #: One is about metering and one is about privilege; collapsing them would mean the first
    #: unmetered non-admin account — a beta tester, a partner — silently gains the admin
    #: navigation.
    #:
    #: It changes nothing about ACCESS. Every admin endpoint is independently gated by the
    #: `AdminUser` dependency and returns 403 regardless of what this says.
    is_admin: bool = False
    ban_reason: str | None = None


class CheckoutRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=32)
    #: A promo code, optional. The browser sends the CODE and never a price — the server
    #: resolves the offer and computes the charge.
    code: str = Field(default="", max_length=40)
    #: Cloudflare Turnstile token, required only by offers that ask for one.
    captcha_token: str = Field(default="", max_length=4096)




# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/items", response_model=list[ItemOut], summary="What you can buy")
async def list_items():
    """
    The store.

    Unauthenticated on purpose — this is the pricing page, and requiring a login to see what
    something costs is the one place where auth actively loses you the sale. It exposes only
    what is already printed on the marketing site.
    """
    return [
        ItemOut(
            id=i.id,
            feature=i.feature,
            quantity=i.quantity,
            price_rupees=i.price_rupees,
            price_paise=i.price_paise,
            name=i.name,
            tagline=i.tagline,
        )
        for i in ITEMS
    ]


@router.get("/me", response_model=BalanceOut, summary="What this account has left")
async def my_balance(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    balance = await get_balance(db, current_user.user_id)
    plan_row = await db.scalar(select(UserPlan).where(UserPlan.user_id == current_user.user_id))
    return BalanceOut(
        features=[
            FeatureBalanceOut(
                feature=f.feature,
                label=f.label,
                granted=f.granted,
                used=f.used,
                remaining=f.remaining,
                trial_allowance=trial_allowance(f.feature),
            )
            for f in balance.features
        ],
        trial_started=balance.trial_started,
        unlimited=balance.unlimited,
        is_admin=balance.unlimited,
        ban_reason=plan_row.ban_reason if plan_row else None,
    )


class QuoteRequest(BaseModel):
    #: Optional. WITHOUT it the code is validated on its own; with it, priced.
    #:
    #: The Apply box has no item yet — the candidate is still choosing — and pricing against
    #: an arbitrary one is how a code restricted to the five-interview pack got refused while
    #: the candidate was looking at the five-interview pack.
    item_id: str = Field(default="", max_length=32)
    code: str = Field(default="", max_length=40)


@router.post(
    "/quote",
    dependencies=[Depends(_checkout_rate_limit)],
    summary="What an item costs this account with a code, without committing",
)
async def quote_item(
    request: QuoteRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    Price a code before the candidate commits to paying.

    SHARES ITS VALIDATION WITH CHECKOUT rather than reimplementing it. Two functions deciding
    whether a code is valid will disagree eventually, and the one that disagrees in the
    candidate's favour is the one that gives product away. This calls `offers.quote`; so does
    checkout, and checkout calls `redeem` on top — which re-validates everything again under
    a lock, because this answer may be minutes old by the time they pay.

    RATE LIMITED WITH CHECKOUT, on the same bucket. Without that, this is an oracle for
    guessing private codes: unlimited attempts against a 40-character keyspace is slow, but
    against a code somebody chose to be memorable it is not.

    Raises the same OfferError messages, which are written to be actionable — "this offer has
    expired" rather than "invalid code".
    """
    # NO ITEM: validate the code alone. This is the Apply box, where the candidate has not
    # chosen yet — everything that is true regardless of what they buy is checked, and which
    # items it covers is decided at checkout against the item they actually pick.
    if not request.item_id:
        offer = await offers.validate_code(
            db, code=request.code, user_id=current_user.user_id
        )
        return {
            "item_id": "",
            "original_paise": 0,
            "charged_paise": 0,
            "is_free": offer.kind == offers.KIND_FREE,
            "requires_captcha": offer.requires_captcha,
            "label": offer.label,
            # So the UI can say "25% off" before an item is chosen, without pretending to
            # know the rupee figure — that depends on which item, and saying a number that
            # later changes is worse than saying none.
            "kind": offer.kind,
            "value": offer.value,
            "applies_to": list(offer.applies_to or []),
        }

    item = get_item(request.item_id)
    if item is None:
        raise NotFoundError("Item", request.item_id)

    quoted = await offers.quote(
        db, item=item, code=request.code, user_id=current_user.user_id
    )
    return {
        "item_id": item.id,
        "original_paise": quoted.original_paise,
        "charged_paise": quoted.charged_paise,
        "is_free": quoted.is_free,
        # So the page knows to render the widget BEFORE the candidate presses pay, rather
        # than bouncing them back with a challenge after they thought they were done.
        "requires_captcha": bool(quoted.offer and quoted.offer.requires_captcha),
        "label": quoted.offer.label if quoted.offer else "",
        "kind": quoted.offer.kind if quoted.offer else "",
        "value": quoted.offer.value if quoted.offer else 0,
        "applies_to": list(quoted.offer.applies_to or []) if quoted.offer else [],
    }


@router.post(
    "/checkout",
    dependencies=[Depends(_checkout_rate_limit)],
    summary="Open a Razorpay order for one item",
)
async def checkout(
    request: CheckoutRequest,
    http_request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    Start a purchase. Returns what the browser checkout widget needs.

    THE ITEM IS RESOLVED SERVER-SIDE FROM ITS ID, and the amount comes from the resolved
    item — never from the request. A client-supplied price is the oldest bug in online
    payments, and Razorpay would happily accept ₹1 for five interviews if we let the browser
    name the figure.
    """
    item = get_item(request.item_id)
    if item is None:
        raise NotFoundError("Item", request.item_id)

    quoted = await offers.quote(
        db, item=item, code=request.code, user_id=current_user.user_id
    )

    # The captcha gate, if this offer asks for one. Before anything is granted or ordered,
    # because its whole purpose is to cost a script something up front.
    if quoted.offer is not None and quoted.offer.requires_captcha:
        await captcha.verify(
            request.captcha_token,
            remote_ip=http_request.client.host if http_request.client else None,
        )

    if quoted.is_free:
            # A 100%-OFF CODE NEVER TOUCHES THE PAYMENT GATEWAY.
        #
        # Razorpay has a one-rupee minimum, so a free item cannot be expressed as an order
        # at all. The redemption and the grant go in one transaction — `get_db` commits on
        # success and rolls back on any error — so the code cannot be burned without the
        # item arriving, and the item cannot arrive without the code being burned.
        #
        # `redeem` runs FIRST. If it raises (already used, switched off, expired, fully
        # claimed) nothing is granted, which is the direction this has to fail in.
        await offers.redeem(
            db, quoted=quoted, user_id=current_user.user_id, payment_ref=None
        )
        await grant(
            db,
            current_user.user_id,
            item.feature,
            item.quantity,
            kind=KIND_GRANT,
            detail={
                "item_id": item.id,
                "offer": quoted.offer.code if quoted.offer else "",
                "original_paise": quoted.original_paise,
                "charged_paise": 0,
            },
        )
        logger.info(
            "offer_free_grant",
            user_id=str(current_user.user_id),
            item=item.id,
            offer=quoted.offer.code if quoted.offer else "",
        )
        return {
            "order_id": None,
            "amount_paise": 0,
            "currency": "INR",
            "item_id": item.id,
            "key_id": None,
            "granted": True,
            "code": quoted.offer.code if quoted.offer else "",
        }

    order = await razorpay.create_order(
        item,
        str(current_user.user_id),
        charged_paise=quoted.charged_paise,
        offer_code=quoted.offer.code if quoted.offer else "",
    )
    order["granted"] = False
    order["original_paise"] = quoted.original_paise
    order["code"] = quoted.offer.code if quoted.offer else ""
    return order


class VerifyRequest(BaseModel):
    """What Razorpay's checkout sheet hands the browser when a payment succeeds."""

    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=256)


@router.post("/verify", summary="Confirm a payment from the browser and grant it")
async def verify_payment(
    request: VerifyRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    Grant a purchase the moment the payment sheet closes, without waiting for the webhook.

    WHY THIS EXISTS. The webhook was the ONLY granting path, and a candidate reported paying
    and receiving nothing. A webhook is not a guarantee: it can be pointed at the wrong URL,
    signed with the wrong secret, blocked, or simply late — and every one of those presents
    identically to the person who has just been charged. "Your money left and nothing
    arrived" is the one failure a payment flow may not have.

    So there are two independent routes to the same grant, and neither is trusted on its own:

      * the SIGNATURE proves the order and payment ids were issued by us and belong together,
        which is what makes a client-supplied payment id safe to look at
      * the FETCH proves the money actually moved. A signature is not proof of payment — a
        card can authorise and then fail to capture, and granting on "authorised" would give
        away product nobody paid for
      * the AMOUNT is checked against the resolved item, exactly as the webhook does it, so a
        ₹1 payment cannot claim a ₹199 bundle
      * the LEDGER makes it idempotent. Whichever of this and the webhook arrives second finds
        the payment_ref already recorded and does nothing, so a purchase cannot be granted
        twice.

    Returns `{"status": "already_applied"}` when the webhook beat us to it, which is the
    common case in a healthy deployment and is not an error.
    """
    if not settings.RAZORPAY_KEY_SECRET:
        raise AppError(
            message="Payments are not configured on this deployment.",
            status_code=503,
            code="PAYMENTS_NOT_CONFIGURED",
        )

    if not razorpay.verify_checkout_signature(
        request.razorpay_order_id,
        request.razorpay_payment_id,
        request.razorpay_signature,
        settings.RAZORPAY_KEY_SECRET,
    ):
        logger.warning(
            "payment_verify_bad_signature",
            user_id=str(current_user.user_id),
            payment_id=request.razorpay_payment_id,
        )
        raise razorpay.PaymentVerificationError("signature mismatch")

    # Already granted, by the webhook or by an earlier call to this. Checked BEFORE the
    # network round trip: the healthy path is that the webhook won, and there is no reason to
    # ask Razorpay about a payment we have already applied.
    existing = await db.scalar(
        select(CreditEvent.id).where(CreditEvent.payment_ref == request.razorpay_payment_id)
    )
    if existing:
        return {"status": "already_applied"}

    payment = await razorpay.fetch_payment(request.razorpay_payment_id)

    if payment.get("status") != "captured":
        # Authorised is not money. It is a real state a card sits in before failing.
        logger.info(
            "payment_verify_not_captured",
            payment_id=request.razorpay_payment_id,
            status=payment.get("status"),
        )
        return {"status": "pending", "detail": "Payment is not confirmed yet."}

    notes = payment.get("notes") or {}
    item = get_item(str(notes.get("item_id") or ""))
    if item is None:
        logger.warning("payment_verify_unknown_item", payment_id=request.razorpay_payment_id)
        raise NotFoundError("Item", str(notes.get("item_id") or ""))

    # THE PAYMENT MUST BELONG TO THE CALLER. Without this, anybody holding a valid
    # (order, payment, signature) triple — their own from a previous purchase, or a friend's —
    # could grant themselves items against somebody else's payment.
    if str(notes.get("user_id") or "") != str(current_user.user_id):
        logger.warning(
            "payment_verify_user_mismatch",
            payment_id=request.razorpay_payment_id,
            caller=str(current_user.user_id),
        )
        raise razorpay.PaymentVerificationError("this payment belongs to another account")

    amount = int(payment.get("amount") or 0)
    offer_code = str(notes.get("offer_code") or "").strip().upper()

    # The same amount rule the webhook applies, and for the same reason: `notes` travelled
    # through the gateway and back, so it says what was INTENDED while the amount says what
    # was paid. A discounted payment is legitimately below list, so the expected figure is
    # recomputed from the offer row rather than taken on trust.
    if offer_code:
        offer = await offers.find_code(db, offer_code)
        if offer is None:
            raise razorpay.PaymentVerificationError("unknown offer on this payment")
        expected = offers.charge_for(offer, item)
    else:
        offer = None
        expected = item.price_paise

    if amount < expected:
        logger.error(
            "payment_verify_underpaid",
            payment_id=request.razorpay_payment_id,
            paid=amount,
            expected=expected,
        )
        raise razorpay.PaymentVerificationError("amount does not match the item")

    if offer is not None:
        await offers.redeem_verified(
            db,
            offer=offer,
            item=item,
            user_id=current_user.user_id,
            charged_paise=amount,
            payment_ref=request.razorpay_payment_id,
        )

    await grant(
        db,
        current_user.user_id,
        item.feature,
        item.quantity,
        kind=KIND_PURCHASE,
        payment_ref=request.razorpay_payment_id,
        detail={
            "item_id": item.id,
            "amount_paise": amount,
            "order_id": request.razorpay_order_id,
            "offer": offer_code,
            # Recorded so a support question can tell a browser-verified grant from a
            # webhook one — they are the same grant, but knowing which arrived first is the
            # difference between "the webhook is fine" and "the webhook has never worked".
            "granted_via": "verify",
        },
    )
    logger.info(
        "payment_verified_and_granted",
        user_id=str(current_user.user_id),
        payment_id=request.razorpay_payment_id,
        item=item.id,
        amount_paise=amount,
    )
    return {"status": "granted", "item_id": item.id, "quantity": item.quantity}


@router.post("/webhook", status_code=status.HTTP_200_OK, summary="Razorpay payment callback")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    Grant the items a captured payment paid for.

    UNAUTHENTICATED BY NECESSITY AND VERIFIED BY SIGNATURE. Razorpay has no user token to
    present, so the HMAC over the raw body is the *entire* authentication — see
    services/billing/razorpay.py for why the comparison is constant-time and why the raw
    bytes, not the re-serialised JSON, are what get hashed.

    ALWAYS 200 ON ANYTHING WE CHOSE NOT TO ACT ON. Razorpay retries until it gets a 2xx, so
    returning an error for an event type we ignore means being retried forever for something
    we will never want. A verification FAILURE is the exception: that returns 400, because it
    is either a forgery or a misconfigured secret, and both need to be visible.
    """
    raw = await request.body()

    if not razorpay.verify_signature(raw, x_razorpay_signature, settings.RAZORPAY_WEBHOOK_SECRET):
        logger.warning("razorpay_webhook_bad_signature", body_bytes=len(raw))
        raise razorpay.PaymentVerificationError("signature mismatch")

    try:
        payload = json.loads(raw)
    except ValueError:
        raise razorpay.PaymentVerificationError("body is not JSON") from None

    outcome = razorpay.items_from_payment(payload)
    if outcome is None:
        # Not a captured payment, or one we deliberately refuse to act on (unknown item,
        # amount below the item's price). Acknowledged so it is not retried forever.
        return {"status": "ignored"}

    # IDEMPOTENCY. Razorpay redelivers after any timeout, deploy or 500, so the same payment
    # WILL arrive more than once. Without this check each delivery grants the items again and
    # a customer who paid once silently receives three times what they bought.
    already = await db.scalar(
        select(CreditEvent.id).where(CreditEvent.payment_ref == outcome.payment_id)
    )
    if already:
        logger.info("razorpay_webhook_replay_ignored", payment_id=outcome.payment_id)
        return {"status": "already_applied"}

    try:
        user_uuid = uuid.UUID(outcome.user_id)
    except ValueError:
        logger.warning("razorpay_webhook_bad_user_id", payment_id=outcome.payment_id)
        return {"status": "ignored"}

    # ── THE DEFERRED AMOUNT CHECK ────────────────────────────────────────────────────────
    #
    # `items_from_payment` cannot check a discounted amount, because the expected price lives
    # in an offer row and that function is deliberately pure. It hands the decision here with
    # `amount_verified=False`, and this is the only place that can honour it.
    #
    # THIS IS LOAD-BEARING. Without it, `offer_code` is a client-influenced note that
    # switches off the one guard protecting every purchase — put any string in it and a ₹1
    # payment buys five interviews. So the offer is re-read from the database, the discount
    # is recomputed from scratch, and a payment short of that is refused.
    #
    # Refused with a 200, not an error: the money is Razorpay's to refund and retrying the
    # webhook forever will not change the amount. It is logged at error level because a
    # payment arriving under its own offer's price means either a bug or somebody probing.
    if not outcome.amount_verified:
        offer = await offers.find_code(db, outcome.offer_code)
        if offer is None:
            logger.error(
                "razorpay_payment_unknown_offer",
                payment_id=outcome.payment_id,
                offer_code=outcome.offer_code,
            )
            return {"status": "rejected"}
        expected = offers.charge_for(offer, outcome.item)
        if outcome.amount_paise < expected:
            logger.error(
                "razorpay_amount_below_discounted_price",
                payment_id=outcome.payment_id,
                item_id=outcome.item.id,
                offer_code=outcome.offer_code,
                paid=outcome.amount_paise,
                expected=expected,
            )
            return {"status": "rejected"}

        # Burned in the same transaction as the grant below, so a code cannot be spent on an
        # item that fails to arrive. A code already used by this account raises here and the
        # whole delivery unwinds — Razorpay retries, hits the replay guard above, and stops.
        try:
            await offers.redeem_verified(
                db,
                offer=offer,
                item=outcome.item,
                user_id=user_uuid,
                charged_paise=outcome.amount_paise,
                payment_ref=outcome.payment_id,
            )
        except offers.OfferError as exc:
            logger.error(
                "razorpay_offer_redeem_failed",
                payment_id=outcome.payment_id,
                offer_code=outcome.offer_code,
                reason=str(exc),
            )
            return {"status": "rejected"}

    await grant(
        db,
        user_uuid,
        outcome.item.feature,
        outcome.item.quantity,
        kind=KIND_PURCHASE,
        payment_ref=outcome.payment_id,
        detail={
            "item_id": outcome.item.id,
            "amount_paise": outcome.amount_paise,
            "order_id": outcome.order_id,
        },
    )
    await db.commit()

    logger.info(
        "razorpay_items_granted",
        user_id=outcome.user_id,
        item_id=outcome.item.id,
        quantity=outcome.item.quantity,
        payment_id=outcome.payment_id,
        amount_paise=outcome.amount_paise,
    )
    return {"status": "granted", "item_id": outcome.item.id}


class AutopayRequest(BaseModel):
    """Turn auto top-up on or off, and choose what it buys."""

    enabled: bool
    #: Which item to buy when the balance runs out. Required when enabling; the price is
    #: resolved server-side from the catalogue, never sent by the browser.
    item_id: str = Field(default="", max_length=64)


@router.post("/autopay", summary="Turn auto top-up on or off")
async def set_autopay(
    request: AutopayRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    Auto top-up: buy the next pack automatically when the balance runs out.

    NOT A SUBSCRIPTION, and the distinction is the product decision this app already made.
    A subscription asks a student to bet ₹299 on using the product enough to justify it,
    which is why the store replaced it. This keeps "you buy what you use" and removes only
    the interruption — running out at eleven at night before a drive buys the next pack
    instead of putting a paywall in the way.

    ENABLING HERE DOES NOT AUTHORISE A CHARGE. It records the intent and the chosen item;
    the mandate itself is authorised by the user inside Razorpay's own sheet, and until that
    token exists `is_eligible` refuses every attempt. So a half-finished setup is inert
    rather than dangerous.

    TURNING IT OFF IS IMMEDIATE AND ALSO CLEARS THE FAILURE COUNTER, so somebody who fixes
    their card and switches it back on is not still carrying three old declines toward the
    automatic disable.
    """
    # Get-or-create, reusing credits' own helper rather than a second one — two functions
    # that create the per-user lock row would race each other into a duplicate, and the
    # uniqueness of that row is what makes `consume` a real lock.
    plan = await _plan_row(db, current_user.user_id, lock=True)

    if request.enabled:
        item = get_item(request.item_id)
        if item is None:
            raise NotFoundError("Item", request.item_id)
        plan.autopay_enabled = True
        plan.autopay_item_id = item.id
        # A fresh start. Someone re-enabling after fixing their card must not inherit the
        # declines that switched it off.
        plan.autopay_failures = 0
        plan.autopay_last_attempt_at = None
    else:
        plan.autopay_enabled = False
        plan.autopay_failures = 0

    logger.info(
        "autopay_setting_changed",
        user_id=str(current_user.user_id),
        enabled=plan.autopay_enabled,
        item=plan.autopay_item_id,
    )
    return {
        "enabled": plan.autopay_enabled,
        "item_id": plan.autopay_item_id,
        # False until the user authorises a mandate in Razorpay's sheet. The UI uses this to
        # say "finish setup" rather than claiming auto top-up is live when it cannot charge.
        "mandate_ready": bool(plan.autopay_token),
    }


@router.get("/payments", summary="Every payment on this account, newest first")
async def my_payments(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    The candidate's own receipts.

    READ STRAIGHT OFF THE LEDGER, not from a separate receipts table. `credit_events` already
    records every grant with its payment reference, what it bought and how many — it is the
    thing entitlement is computed from, so a receipt derived from it cannot disagree with what
    the account actually received. A second store would be a second version of the truth about
    somebody's money, which is the class of bug this whole ledger exists to avoid.

    SCOPED TO THE CALLER BY user_id, not by anything the request supplies. A receipts endpoint
    that takes an id is a receipts endpoint that reads other people's payments.

    Purchases and grants both appear, distinguished by `kind`: a candidate who redeemed a
    100%-off code should see it on their history as something they received, not as a gap.
    Consumptions are excluded — this is what you paid, not what you spent.

    `payer` is returned ALONGSIDE the rows rather than repeated on each of them. A receipt has
    to name who it was issued to or it is not a receipt, and it is the same person for every
    row by construction — the query is scoped to `current_user`. Repeating an identity that
    cannot vary would invite a caller to read it per row and trust it, which is the shape of
    the bug the scoping above exists to prevent.

    ── WHY A FAILED PAYMENT IS NOT ON THIS LIST ────────────────────────────────────────────

    Asked for directly: "the payment failed must also show in the payment history section."
    It cannot yet, and the reason is not this endpoint. NOTHING ANYWHERE RECORDS A FAILED OR
    ABANDONED PAYMENT ATTEMPT. This was established by reading every place one could be:

      * `POST /billing/checkout` opens the Razorpay order and returns it to the browser. It
        persists nothing at all — there is no orders table, so an attempt that never completes
        leaves no trace that it was ever started.
      * `POST /billing/verify` answers `{"status": "pending"}` for an authorised-but-uncaptured
        payment and raises for a bad signature. It writes in neither case; the only row it ever
        creates is the grant for a payment that DID capture.
      * `POST /billing/webhook` drops everything that is not a capture. `items_from_payment`
        returns None for any other status — "failed is not money at all" — and the endpoint
        answers 200 so Razorpay stops retrying. A `payment.failed` delivery is acknowledged
        and forgotten.
      * The browser is the only party that learns a payment failed, through
        `rzp.on('payment.failed')` in lib/billing/razorpay-checkout.ts, and it tells the
        candidate rather than the server.
      * `autopay.record_attempt` keeps `autopay_failures` and `autopay_last_attempt_at` on
        `user_plans`. That is a THROTTLE COUNTER, not history: no amount, no item, no row per
        attempt, and nothing to show. It is also always zero in production today, because
        `try_top_up` has no caller yet.
      * No model and none of the twenty migrations define a payment-attempt or order table.

    SO THERE IS NOTHING HONEST TO RENDER, and this endpoint will not invent it. A fabricated
    row on a page about somebody's money is worse than the gap it fills: a candidate who was
    never charged reading "payment failed — ₹249" has been told something false about their
    bank account, and support has no record to check it against.

    WHAT IT WOULD TAKE, so the next person does not have to re-derive it. One append-only
    attempt record, written from the two places that already know — the `pending` and
    signature-failure branches of `/billing/verify`, plus the webhook's non-capture branch —
    and read here as a second source unioned into the list below.

    NOT AS ZERO-DELTA ROWS ON `credit_events`. That is the tempting shortcut because it needs
    no migration, and it is wrong twice: the table is defined as movements of entitlement, so a
    non-movement is a lie about what the row means; and every `SUM(delta)` and every count over
    that table would silently start including attempts that bought nothing. `audit_logs` is the
    existing append-only event log with a `user_id` and a JSONB payload, and it is the right
    home for "this was attempted and did not complete".
    """
    rows = (
        await db.execute(
            select(CreditEvent)
            .where(
                CreditEvent.user_id == current_user.user_id,
                CreditEvent.kind.in_([KIND_PURCHASE, KIND_GRANT]),
            )
            .order_by(CreditEvent.created_at.desc())
            .limit(200)
        )
    ).scalars().all()

    out = []
    for r in rows:
        detail = r.detail or {}
        item = get_item(str(detail.get("item_id") or ""))
        paise = int(detail.get("amount_paise") or 0)
        out.append(
            {
                "id": str(r.id),
                "at": r.created_at.isoformat(),
                # The payment id IS the receipt number. It is what Razorpay's dashboard,
                # their support and ours all index by, so inventing a prettier one would mean
                # a candidate quoting a number nobody can look up.
                "receipt": r.payment_ref or f"free-{str(r.id)[:8]}",
                # THE ORDER THE PAYMENT SETTLED AGAINST, surfaced because it was already
                # being stored and thrown away. It is the second identifier Razorpay's
                # dashboard indexes by, and the one that still resolves when a candidate has
                # a bank statement showing a debit and no payment id to quote — which is
                # exactly the conversation a receipt exists to shorten. Empty for a free
                # grant, which never had an order because Razorpay cannot open one below ₹1.
                "order_id": str(detail.get("order_id") or ""),
                "item_id": detail.get("item_id") or "",
                "item_name": item.name if item else (detail.get("item_id") or "Credit"),
                "feature": r.feature,
                "quantity": r.delta,
                "amount_paise": paise,
                "amount_rupees": paise / 100 if paise else 0,
                "offer": detail.get("offer") or "",
                # "purchase" or "grant" — a free code or admin goodwill is not a payment and
                # must not be shown as one.
                "kind": r.kind,
                "paid": bool(r.payment_ref),
            }
        )
    return {
        "payments": out,
        # Who the receipts belong to. Taken from the verified token, never from the request,
        # for the same reason the query is: the one thing a receipt must not do is name
        # somebody other than the person the payment came from.
        "payer": {"email": current_user.email},
    }


class PromoBannerOut(BaseModel):
    """The promo banner a candidate sees, and what clicking it should carry across."""

    image_url: str
    alt_text: str
    #: The offer's code, so the pricing page can prefill the box it scrolls to.
    code: str
    #: The ratio the image was validated against. The client renders its container at this
    #: ratio, which is what makes an image that met the contract land pixel-exact and one that
    #: somehow did not merely centre-crop instead of distorting the page.
    aspect_ratio: float


@router.get(
    "/promo-banner",
    response_model=PromoBannerOut | None,
    summary="The promo banner to show on the dashboard, if any",
)
async def promo_banner(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PromoBannerOut | None:
    """
    The one banner worth showing right now, or null.

    THE OFFER DECIDES, NOT THE IMAGE. A banner is returned only while its offer is enabled,
    public, and inside its window — the same conditions that decide whether the code can
    actually be redeemed. That is the whole reason a banner hangs off an offer rather than
    standing alone: switching a code off takes its advertisement down in the same action, so
    there is no route to a dashboard promoting a code that refuses everybody who types it.

    `is_public` is checked as well as `enabled`, because a private code shared with four
    friends must not end up posted on every candidate's dashboard.

    NEWEST WINS when more than one qualifies. Predictable and controlled by the admin —
    re-uploading is how you change what is shown — and it needs no ordering column that
    somebody would have to maintain.

    NULL IS THE ORDINARY CASE, not an error: most of the time there is no live public offer
    with an image, and the client renders nothing.
    """
    from sqlalchemy.exc import ProgrammingError

    from app.models.billing import Offer, OfferBanner

    now = datetime.now(UTC)

    # A SAVEPOINT around the read, because migrations here are applied BY HAND
    # (docs/DEPLOY.md): between deploying this code and running migration 021 the table does
    # not exist, and an UndefinedTable aborts the entire transaction rather than just failing
    # this one query. Every candidate's dashboard calls this, so an unguarded read would take
    # every dashboard down until somebody remembered to migrate — which is precisely the
    # failure this feature was designed to be incapable of.
    try:
        async with db.begin_nested():
            row = (
                await db.execute(
                    select(OfferBanner, Offer.code)
                    .join(Offer, Offer.id == OfferBanner.offer_id)
                    .where(
                        Offer.enabled.is_(True),
                        Offer.is_public.is_(True),
                        or_(Offer.starts_at.is_(None), Offer.starts_at <= now),
                        or_(Offer.ends_at.is_(None), Offer.ends_at >= now),
                    )
                    .order_by(OfferBanner.created_at.desc())
                    .limit(1)
                )
            ).first()
    except ProgrammingError:
        logger.warning("offer_banners_table_missing", detail="run migration 021")
        return None

    if row is None:
        return None
    banner, code = row
    return PromoBannerOut(
        image_url=banner.image_url,
        alt_text=banner.alt_text,
        code=code,
        aspect_ratio=settings.BANNER_ASPECT_RATIO,
    )
