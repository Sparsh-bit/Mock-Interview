"""
Turning a payment into granted items — services/billing/razorpay.py

WRITTEN BEFORE THE KEYS EXIST, AND THAT IS THE POINT. The parts of a payment integration that
are easy to get wrong are not the API calls — those fail loudly the first time you try them.
The dangerous parts are signature verification and idempotency, and both of those fail
SILENTLY and only under conditions you will not hit while testing with your own card.

So they are implemented now, with tests, rather than left as a TODO to be written under
deadline pressure on the day the keys arrive.

## The two things that must not be got wrong

**VERIFY THE SIGNATURE, ALWAYS.** The webhook URL is public. Anyone who finds it can POST a
"payment succeeded" body naming any user and any item, and without verification they get
five interviews for free — and so does everybody they tell. Razorpay signs every webhook with HMAC-SHA256 over
the raw request body using the webhook secret. The comparison must be constant-time
(`hmac.compare_digest`); `==` on a signature leaks its bytes through timing.

The RAW body is what is signed. Re-serialising the parsed JSON and hashing that will produce a
different string for the same payload — key order and whitespace differ — and the mismatch
looks like an attack rather than like the bug it is.

**BE IDEMPOTENT.** Razorpay retries a webhook until it gets a 2xx, so the same payment WILL be
delivered more than once — after a timeout, a deploy, or a 500. Granting the items per
delivery means a customer who paid for five interviews receives fifteen, and the only signal
is a support ticket you cannot reconcile. `payment_ref` on `credit_events` holds the payment
id, and applying one already recorded is a no-op that still returns 200 — because returning
an error to a retry is how you get retried forever.

## Why this is a seam rather than a client

`verify_signature` and `items_from_payment` are pure functions over strings and dicts. They
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
from app.services.billing.plans import ITEMS, Item, get_item

logger = structlog.get_logger(__name__)

#: Razorpay's own field names, so a typo is a constant rather than a silent None deep in a
#: handler.
_PAYMENT_ENTITY = "payment"
_NOTES_ITEM_KEY = "item_id"
_NOTES_USER_KEY = "user_id"
#: The promo code an order was opened under, carried through the gateway so the webhook can
#: re-derive what should have been paid. It names an offer; it never names a price.
_NOTES_OFFER_KEY = "offer_code"

#: Razorpay will not accept an order below one rupee. Anything discounted under this is a
#: free grant that must never reach the gateway — see offers.quote.
_MIN_ORDER_PAISE = 100


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
    """What a verified payment says should be granted."""

    payment_id: str
    order_id: str
    user_id: str
    item: Item
    amount_paise: int
    #: The promo code claimed in the order's notes, or "".
    #:
    #: Present means the amount check below was DEFERRED, because the expected price depends
    #: on an offer row this pure function cannot read. The caller is obliged to re-derive it
    #: and reject a short payment — see `amount_verified`.
    offer_code: str = ""
    #: False when an offer was claimed and the caller must still check the amount itself.
    #:
    #: A flag rather than an honour system: the webhook asserts on it before granting, so
    #: forgetting the check fails loudly in tests instead of quietly giving product away.
    amount_verified: bool = True


def items_from_payment(payload: dict) -> PaymentOutcome | None:
    """
    Read a verified webhook body into "grant this user this item", or None.

    Returns None for anything that is not a captured payment — Razorpay sends many event
    types to one URL, and an unrecognised one is routine rather than an error. The caller
    answers 200 to those, because a non-2xx makes Razorpay retry an event we will never
    want.

    THE AMOUNT IS CHECKED AGAINST THE ITEM'S REAL PRICE. Without that, `notes.item_id` is a
    client-supplied field naming what to grant — so a ₹1 payment annotated
    `item_id=interview_5` would buy five interviews. The notes say what was INTENDED; the
    amount is what was actually paid, and they have to agree. This is the check that makes
    the whole flow safe, because everything else about `notes` is attacker-influenced.
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
    item_id = str(notes.get(_NOTES_ITEM_KEY) or "").strip()
    offer_code = str(notes.get(_NOTES_OFFER_KEY) or "").strip().upper()
    payment_id = str(payment.get("id") or "").strip()
    order_id = str(payment.get("order_id") or "").strip()
    amount = int(payment.get("amount") or 0)

    if not user_id or not payment_id:
        logger.warning("razorpay_payment_missing_notes", payment_id=payment_id)
        return None

    item = get_item(item_id)
    if item is None:
        # A payment naming something not in the catalogue. Never guess — granting the
        # nearest thing would be inventing a purchase nobody made. A support ticket is the
        # right outcome.
        logger.warning("razorpay_payment_unknown_item", payment_id=payment_id, item_id=item_id)
        return None

    if not offer_code and amount < item.price_paise:
        # Underpaid. See the note above — the notes are an intention, the amount is the fact.
        logger.warning(
            "razorpay_amount_below_item_price",
            payment_id=payment_id,
            item_id=item.id,
            paid=amount,
            expected=item.price_paise,
        )
        return None

    # A DISCOUNTED PAYMENT IS LEGITIMATELY BELOW THE LIST PRICE, so the check above cannot
    # apply — but it must not simply be skipped either, or `offer_code` becomes a
    # client-supplied field that disables the one guard protecting every purchase. The
    # expected price lives in an offer row, which this function deliberately cannot read
    # (being pure is what makes the rest of it testable without a database), so the decision
    # is handed to the caller along with an explicit flag saying it is still owed.
    return PaymentOutcome(
        payment_id=payment_id,
        order_id=order_id,
        user_id=user_id,
        item=item,
        amount_paise=amount,
        offer_code=offer_code,
        amount_verified=not offer_code,
    )


def purchasable_items() -> tuple[Item, ...]:
    """Everything in the catalogue. All of it is purchasable — there is no free tier item."""
    return ITEMS


async def create_order(
    item: Item,
    user_id: str,
    *,
    charged_paise: int | None = None,
    offer_code: str = "",
) -> dict:
    """
    Open an order at Razorpay for `item`, returning what the browser checkout needs.

    THE ONLY FUNCTION HERE THAT NEEDS CREDENTIALS, which is why everything above it is
    testable today. Raises PaymentNotConfiguredError until the keys are set, rather than
    returning a fake order — a stub that looks like it worked is how an unpayable checkout
    reaches production.

    `notes` carries the user and item back to us through the webhook. It is not trusted on
    the way back: `items_from_payment` re-checks the amount against the item's real price.
    """
    # THE AMOUNT IS CHECKED BEFORE THE CREDENTIALS, deliberately.
    #
    # A zero-rupee order is a programming error — the free path in checkout should have
    # granted it directly and never come here — and it is an error whether or not payments
    # are configured. Checking credentials first would hide it behind "payments are not
    # configured" on every development machine, which is precisely where you want to find it.
    amount_paise = item.price_paise if charged_paise is None else int(charged_paise)
    if amount_paise < _MIN_ORDER_PAISE:
        raise ValueError(
            f"order amount {amount_paise} is below Razorpay's minimum; "
            "a fully-discounted item must be granted directly, not ordered"
        )

    from app.core.config import settings  # noqa: PLC0415

    key_id = getattr(settings, "RAZORPAY_KEY_ID", "") or ""
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "") or ""
    if not key_id or not key_secret:
        raise PaymentNotConfiguredError

    notes: dict[str, str] = {_NOTES_ITEM_KEY: item.id, _NOTES_USER_KEY: user_id}
    if offer_code:
        # Carried so the webhook can re-derive what SHOULD have been paid. Not trusted on
        # the way back — it names which offer to look up, and the offer decides the price.
        notes[_NOTES_OFFER_KEY] = offer_code.upper()

    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.razorpay.com/v1/orders",
            auth=(key_id, key_secret),
            json={
                # THE AMOUNT COMES FROM THE RESOLVED ITEM, never from the request. The
                # caller looked the item up by id; the browser never names a price.
                # THE AMOUNT STILL COMES FROM THE SERVER. `charged_paise` is computed by
                # services/billing/offers.quote from the item and the offer row — the browser
                # sends a code, never a figure, so this is no more client-controlled than the
                # list price was.
                "amount": amount_paise,
                "currency": "INR",
                "notes": notes,
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
        "amount_paise": amount_paise,
        "currency": "INR",
        "item_id": item.id,
        # The PUBLIC key id — this is meant to reach the browser. The secret never does.
        "key_id": key_id,
    }
