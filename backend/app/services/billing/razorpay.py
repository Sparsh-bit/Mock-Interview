"""
Turning a payment into a plan change — services/billing/razorpay.py

WRITTEN BEFORE THE KEYS EXIST, AND THAT IS THE POINT. The parts of a payment integration that
are easy to get wrong are not the API calls — those fail loudly the first time you try them.
The dangerous parts are signature verification and idempotency, and both of those fail
SILENTLY and only under conditions you will not hit while testing with your own card.

So they are implemented now, with tests, rather than left as a TODO to be written under
deadline pressure on the day the keys arrive.

## The two things that must not be got wrong

**VERIFY THE SIGNATURE, ALWAYS.** The webhook URL is public. Anyone who finds it can POST a
"payment succeeded" body naming any user and any plan, and without verification they get Pro
for free — and so does everybody they tell. Razorpay signs every webhook with HMAC-SHA256 over
the raw request body using the webhook secret. The comparison must be constant-time
(`hmac.compare_digest`); `==` on a signature leaks its bytes through timing.

The RAW body is what is signed. Re-serialising the parsed JSON and hashing that will produce a
different string for the same payload — key order and whitespace differ — and the mismatch
looks like an attack rather than like the bug it is.

**BE IDEMPOTENT.** Razorpay retries a webhook until it gets a 2xx, so the same payment WILL be
delivered more than once — after a timeout, a deploy, or a 500. Granting a month of Pro per
delivery means a customer who paid once gets three months, and the only signal is a support
ticket you cannot reconcile. `provider_ref` on `user_plans` holds the payment id, and applying
a payment whose id is already recorded is a no-op that still returns 200 — because returning
an error to a retry is how you get retried forever.

## Why this is a seam rather than a client

`verify_signature` and `plan_from_payment` are pure functions over strings and dicts. They
need no key, no network and no account, so they are fully testable today. The only piece that
genuinely requires credentials is creating the order, and that is one function at the bottom
which raises a clear configuration error until `RAZORPAY_KEY_ID` is set.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

import structlog

from app.core.exceptions import AppError
from app.services.billing.plans import PLANS, Plan, get_plan

logger = structlog.get_logger(__name__)

#: Razorpay's own field names, so a typo is a constant rather than a silent None deep in a
#: handler.
_PAYMENT_ENTITY = "payment"
_NOTES_PLAN_KEY = "plan_id"
_NOTES_USER_KEY = "user_id"


class PaymentNotConfiguredError(AppError):
    """
    Somebody tried to buy something before the keys were set.

    503, not 500: nothing is broken, the feature is simply not switched on yet, and the
    distinction is what stops this paging somebody at 3am during the period before launch.
    """

    def __init__(self) -> None:
        super().__init__(
            message="Payments are not configured on this deployment yet.",
            status_code=503,
            code="PAYMENTS_NOT_CONFIGURED",
        )


class PaymentVerificationError(AppError):
    """
    A webhook or callback did not verify.

    400 rather than 401. This is not a caller who needs to authenticate — it is a body that
    does not match its signature, which means either a forgery or a misconfigured secret, and
    both are the request's problem rather than the sender's identity.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(
            message="Payment could not be verified.",
            status_code=400,
            code="PAYMENT_VERIFICATION_FAILED",
            details={"reason": reason},
        )


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """
    Is this webhook genuinely from Razorpay?

    HMAC-SHA256 over the RAW body — see the note at the top about why re-serialised JSON does
    not work. Compared with `hmac.compare_digest` rather than `==`, because a byte-by-byte
    comparison that short-circuits on the first difference leaks the correct prefix through
    response timing, and a signature can be recovered one byte at a time from that.

    Returns False rather than raising on missing input. A blank signature and a wrong one are
    the same event to a caller, and the branch that treats "no signature supplied" as anything
    other than a failure is the branch an attacker aims for.
    """
    if not raw_body or not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


@dataclass(frozen=True)
class PaymentOutcome:
    """What a verified payment says should happen."""

    payment_id: str
    user_id: str
    plan: Plan
    amount_paise: int


def plan_from_payment(payload: dict) -> PaymentOutcome | None:
    """
    Read a verified webhook body into "give this user this plan", or None.

    Returns None for anything that is not a captured payment — Razorpay sends many event
    types to one URL, and an unrecognised one is routine rather than an error. The caller
    answers 200 to those, because a non-2xx makes Razorpay retry an event we will never
    want.

    THE AMOUNT IS CHECKED AGAINST THE PLAN'S PRICE. Without that, `notes.plan_id` is a
    client-supplied field that says which plan to grant — so a ₹1 payment annotated
    `plan_id=pro` would buy Pro. The notes say what was INTENDED; the amount is what was
    actually paid, and they have to agree.
    """
    entity = (payload.get("payload") or {}).get(_PAYMENT_ENTITY) or {}
    payment = entity.get("entity") or {}
    if not payment:
        return None
    if payment.get("status") != "captured":
        # Authorised-but-not-captured is not money yet, and failed is not money at all.
        return None

    notes = payment.get("notes") or {}
    user_id = str(notes.get(_NOTES_USER_KEY) or "").strip()
    plan_id = str(notes.get(_NOTES_PLAN_KEY) or "").strip()
    payment_id = str(payment.get("id") or "").strip()
    amount = int(payment.get("amount") or 0)

    if not user_id or not payment_id:
        logger.warning("razorpay_payment_missing_notes", payment_id=payment_id)
        return None

    plan = get_plan(plan_id)
    if plan.is_free:
        # Somebody paid real money against the free plan id. Never grant on this — it means
        # the notes were wrong or tampered with, and the safe outcome is a support ticket
        # rather than an unpaid upgrade.
        logger.warning("razorpay_payment_for_free_plan", payment_id=payment_id, plan_id=plan_id)
        return None

    if amount < plan.price_paise:
        # Underpaid. See the note above — the notes are an intention, the amount is the fact.
        logger.warning(
            "razorpay_amount_below_plan_price",
            payment_id=payment_id,
            plan_id=plan.id,
            paid=amount,
            expected=plan.price_paise,
        )
        return None

    return PaymentOutcome(
        payment_id=payment_id,
        user_id=user_id,
        plan=plan,
        amount_paise=amount,
    )


def purchasable_plans() -> tuple[Plan, ...]:
    """The plans somebody can actually pay for — everything except Free."""
    return tuple(p for p in PLANS if not p.is_free)


async def create_order(plan: Plan, user_id: str) -> dict:
    """
    Open an order at Razorpay for `plan`, returning what the browser checkout needs.

    THE ONLY FUNCTION HERE THAT NEEDS CREDENTIALS, which is why everything above it is
    testable today. Raises PaymentNotConfiguredError until the keys are set, rather than
    returning a fake order — a stub that looks like it worked is how an unpayable checkout
    reaches production.

    `notes` carries the user and plan back to us through the webhook. It is not trusted on the
    way back: `plan_from_payment` re-checks the amount against the plan's real price.
    """
    from app.core.config import settings  # noqa: PLC0415

    key_id = getattr(settings, "RAZORPAY_KEY_ID", "") or ""
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "") or ""
    if not key_id or not key_secret:
        raise PaymentNotConfiguredError

    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.razorpay.com/v1/orders",
            auth=(key_id, key_secret),
            json={
                "amount": plan.price_paise,
                "currency": "INR",
                "notes": {_NOTES_PLAN_KEY: plan.id, _NOTES_USER_KEY: user_id},
            },
        )
    if resp.status_code >= 400:
        logger.error("razorpay_order_failed", status=resp.status_code, body=resp.text[:300])
        raise AppError(
            message="Could not start the payment. Please try again.",
            status_code=502,
            code="PAYMENT_ORDER_FAILED",
        )

    order = resp.json()
    return {
        "order_id": order.get("id"),
        "amount_paise": plan.price_paise,
        "currency": "INR",
        "plan_id": plan.id,
        # The PUBLIC key id — this is meant to reach the browser. The secret never does.
        "key_id": key_id,
    }
