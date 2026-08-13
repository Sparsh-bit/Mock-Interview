"""
The store, the balance and the appeal — api/v1/billing.py

GET  /billing/items     — what you can buy and what it costs. The only public route here.
GET  /billing/me        — what this account has left.
POST /billing/checkout  — open a Razorpay order for one item.
POST /billing/webhook   — Razorpay confirms a payment; the items are granted here.
POST /billing/appeal    — a banned user asks for a review.

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.session import get_db
from app.models.billing import CreditEvent, UserPlan
from app.services.billing import razorpay
from app.services.billing.credits import KIND_PURCHASE, get_balance, grant
from app.services.billing.plans import ITEMS, get_item

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing", tags=["Billing"])

_checkout_rate_limit = rate_limiter(
    limit=10,
    window_seconds=3600,
    key_builder=lambda user_id: f"rate_limit:checkout:{user_id}:hourly",
    action="starting a purchase",
)

_appeal_rate_limit = rate_limiter(
    limit=3,
    window_seconds=24 * 3600,
    key_builder=lambda user_id: f"rate_limit:appeal:{user_id}:daily",
    action="requesting a review",
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


class BalanceOut(BaseModel):
    features: list[FeatureBalanceOut]
    trial_started: bool
    is_banned: bool
    ban_reason: str | None = None
    appeal_submitted: bool = False


class CheckoutRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=32)


class AppealRequest(BaseModel):
    message: str = Field(min_length=10, max_length=1000)


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
            )
            for f in balance.features
        ],
        trial_started=balance.trial_started,
        is_banned=bool(plan_row and plan_row.is_banned),
        ban_reason=plan_row.ban_reason if plan_row else None,
        appeal_submitted=bool(plan_row and plan_row.appeal_at),
    )


@router.post(
    "/checkout",
    dependencies=[Depends(_checkout_rate_limit)],
    summary="Open a Razorpay order for one item",
)
async def checkout(request: CheckoutRequest, current_user: CurrentUser):
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
    return await razorpay.create_order(item, str(current_user.user_id))


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


@router.post(
    "/appeal",
    dependencies=[Depends(_appeal_rate_limit)],
    summary="Ask for a suspended account to be reviewed",
)
async def appeal(
    request: AppealRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    A banned user's one route back.

    AN AUTOMATIC BAN NEEDS A HUMAN ROUTE OUT, and this is not a courtesy. The detector keys
    on two IPs at once, which is a genuine sharing signal and also what a phone handing off
    from mobile data to campus wi-fi looks like. Some proportion of bans will be wrong, they
    will land on people who have paid, and without an appeal the only recourse is a support
    email nobody reads.

    Rate limited to three a day. Not to be obstructive — one honest appeal is enough — but
    because the endpoint is reachable by exactly the population with a reason to spam it.

    Deliberately does NOT unban. Only an admin can (see api/v1/admin.py); an appeal that
    lifted its own ban would make the ban decorative.
    """
    plan_row = await db.scalar(
        select(UserPlan).where(UserPlan.user_id == current_user.user_id).with_for_update()
    )
    if plan_row is None or not plan_row.is_banned:
        # Nothing to appeal. Not an error — a user who was unbanned while writing their
        # appeal should be told the good news, not shown a failure.
        return {"status": "not_banned"}

    plan_row.appeal_text = request.message.strip()[:1000]
    plan_row.appeal_at = datetime.now(UTC)
    await db.commit()

    logger.info("ban_appeal_submitted", user_id=str(current_user.user_id))
    return {"status": "submitted"}
