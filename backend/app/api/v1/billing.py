"""
Plans, balance and checkout — api/v1/billing.py

GET  /billing/plans     — the catalogue. The only public route here.
GET  /billing/me        — what this user is on and what they have left.
POST /billing/checkout  — open a Razorpay order for a plan.
POST /billing/webhook   — Razorpay tells us a payment was captured.

THE BALANCE ROUTE IS INFORMATIONAL, NOT A GATE. The UI reads it to render remaining counts and
to decide whether to show the upgrade sheet before somebody starts something. It is not what
stops an exhausted user: `consume` does that inside each metered endpoint's own transaction,
and it re-reads under a lock rather than trusting anything this route said. A client that
ignores this endpoint entirely still cannot exceed its allowance.
"""

from __future__ import annotations

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
from app.models.billing import UserPlan
from app.services.billing import razorpay
from app.services.billing.credits import _PERIOD, get_balance
from app.services.billing.plans import PLANS, get_plan

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing", tags=["Billing"])

_checkout_rate_limit = rate_limiter(
    limit=10,
    window_seconds=3600,
    key_builder=lambda user_id: f"rate_limit:checkout:{user_id}:hourly",
    action="starting a purchase",
)


# ─── Schemas ──────────────────────────────────────────────────────────────────


class PlanOut(BaseModel):
    id: str
    name: str
    price_rupees: int
    price_paise: int
    tagline: str
    allowances: dict[str, int]
    highlights: list[str]
    is_free: bool


class FeatureBalanceOut(BaseModel):
    feature: str
    label: str
    used: int
    allowance: int
    remaining: int
    unlimited: bool


class BalanceOut(BaseModel):
    plan_id: str
    plan_name: str
    period_start: str
    period_end: str
    features: list[FeatureBalanceOut]


class CheckoutRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=32)


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/plans", response_model=list[PlanOut], summary="The plan catalogue")
async def list_plans():
    """
    Every plan, including Free.

    Unauthenticated on purpose — this is the pricing page, and requiring a login to see what
    something costs is the one place where auth actively loses you the sale. It exposes only
    what is already printed on the marketing site.
    """
    return [
        PlanOut(
            id=p.id,
            name=p.name,
            price_rupees=p.price_rupees,
            price_paise=p.price_paise,
            tagline=p.tagline,
            allowances=p.allowances,
            highlights=list(p.highlights),
            is_free=p.is_free,
        )
        for p in PLANS
    ]


@router.get("/me", response_model=BalanceOut, summary="This user's plan and remaining usage")
async def my_balance(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    # get_balance creates the plan row on first sight, so this GET can write. That is fine
    # and intentional — see the lazy-creation note in credits.py — and `get_db` commits it on
    # success like any other request.
    balance = await get_balance(db, current_user.user_id)
    return BalanceOut(
        plan_id=balance.plan_id,
        plan_name=balance.plan_name,
        period_start=balance.period_start.isoformat(),
        period_end=balance.period_end.isoformat(),
        features=[
            FeatureBalanceOut(
                feature=f.feature,
                label=f.label,
                used=f.used,
                allowance=f.allowance,
                remaining=f.remaining,
                unlimited=f.unlimited,
            )
            for f in balance.features
        ],
    )


@router.post(
    "/checkout",
    dependencies=[Depends(_checkout_rate_limit)],
    summary="Open a Razorpay order for a plan",
)
async def checkout(
    request: CheckoutRequest,
    current_user: CurrentUser,
):
    """
    Start a purchase. Returns what the browser checkout widget needs.

    THE PLAN IS RESOLVED SERVER-SIDE FROM ITS ID, and the amount comes from the resolved
    plan — never from the request. A client-supplied price is the oldest bug in online
    payments, and the fact that Razorpay would happily accept ₹1 for Pro is exactly why the
    amount is not something a caller gets to say.
    """
    plan = get_plan(request.plan_id)
    if plan.is_free:
        # Nothing to buy. A 404 rather than a 400 because from the client's point of view
        # there is no such purchasable plan.
        raise NotFoundError("Purchasable plan", request.plan_id)

    return await razorpay.create_order(plan, str(current_user.user_id))


@router.post("/webhook", status_code=status.HTTP_200_OK, summary="Razorpay payment callback")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    Apply a captured payment.

    UNAUTHENTICATED BY NECESSITY AND VERIFIED BY SIGNATURE. Razorpay has no user token to
    present, so the HMAC over the raw body is the *entire* authentication — see
    services/billing/razorpay.py for why the comparison is constant-time and why the raw
    bytes, not the re-serialised JSON, are what get hashed.

    ALWAYS 200 ON ANYTHING WE CHOSE NOT TO ACT ON. Razorpay retries until it gets a 2xx, so
    returning an error for an event type we ignore means being retried forever for something
    we will never want. A verification FAILURE is the exception: that returns 400, because it
    is either a forgery or a misconfigured secret, and both need to be visible rather than
    absorbed.
    """
    raw = await request.body()

    if not razorpay.verify_signature(raw, x_razorpay_signature, settings.RAZORPAY_WEBHOOK_SECRET):
        logger.warning("razorpay_webhook_bad_signature", body_bytes=len(raw))
        raise razorpay.PaymentVerificationError("signature mismatch")

    import json  # noqa: PLC0415

    try:
        payload = json.loads(raw)
    except ValueError:
        # Signed but unparseable should not happen, and if it does it is not something a
        # retry fixes.
        raise razorpay.PaymentVerificationError("body is not JSON") from None

    outcome = razorpay.plan_from_payment(payload)
    if outcome is None:
        # Not a captured payment, or one we deliberately refuse to act on (free plan named,
        # amount below the plan price). Acknowledged so it is not retried.
        return {"status": "ignored"}

    # IDEMPOTENCY. Razorpay redelivers after any timeout, deploy or 500, so the same payment
    # will arrive more than once. Without this check each delivery grants another period and
    # a customer who paid once silently gets three months.
    already = await db.scalar(
        select(UserPlan.id).where(UserPlan.provider_ref == outcome.payment_id)
    )
    if already:
        logger.info("razorpay_webhook_replay_ignored", payment_id=outcome.payment_id)
        return {"status": "already_applied"}

    import uuid as _uuid  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    try:
        user_uuid = _uuid.UUID(outcome.user_id)
    except ValueError:
        logger.warning("razorpay_webhook_bad_user_id", payment_id=outcome.payment_id)
        return {"status": "ignored"}

    now = datetime.now(UTC)
    plan_row = await db.scalar(
        select(UserPlan).where(UserPlan.user_id == user_uuid).with_for_update()
    )
    if plan_row is None:
        plan_row = UserPlan(user_id=user_uuid)
        db.add(plan_row)

    plan_row.plan_id = outcome.plan.id
    # THE PERIOD RESTARTS NOW rather than continuing the free one. Somebody who upgrades on
    # day 29 expects their allowance immediately, not tomorrow — and since usage is counted
    # as "events since period_start", moving the start forward is also what stops their free
    # usage being charged against the plan they just bought.
    plan_row.period_start = now
    plan_row.period_end = now + _PERIOD
    plan_row.source = "razorpay"
    plan_row.provider_ref = outcome.payment_id
    await db.commit()

    logger.info(
        "razorpay_plan_applied",
        user_id=outcome.user_id,
        plan_id=outcome.plan.id,
        payment_id=outcome.payment_id,
        amount_paise=outcome.amount_paise,
    )
    return {"status": "applied", "plan_id": outcome.plan.id}
