"""
Offers and promo codes, from the admin side — api/v1/admin_offers.py

GET    /admin/offers          — every code, with how many times each has been used
POST   /admin/offers          — create one
PATCH  /admin/offers/{id}     — edit it, including the on/off switch
DELETE /admin/offers/{id}     — remove one that has never been used

ADMIN ONLY, VIA THE EXISTING DEPENDENCY. `AdminUser` is checked against users.is_admin and
returns 403, the same as every other admin route. These endpoints can give the product away
for free, so they are the single most sensitive surface in the app after the payment webhook.

THE ON/OFF SWITCH IS A COLUMN, NOT A DELETION, and that is the point of it. A private code
given to friends needs to be turnable off and back on without losing who has already used it
— deleting and recreating would reset the single-use record and let everybody claim again.
`PATCH {"enabled": false}` stops it working for everybody on the next request.

DELETION IS REFUSED ONCE A CODE HAS BEEN USED. The redemptions are the audit trail for
revenue that was given away, and `ON DELETE CASCADE` on the foreign key means dropping the
offer would take them with it. An unused code can go; a used one is switched off instead.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.security import AdminUser
from app.db.session import get_db
from app.models.billing import Offer, OfferRedemption
from app.services.billing.offers import KINDS
from app.services.billing.plans import ITEMS

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/offers", tags=["Admin — Offers"])

_ITEM_IDS = {i.id for i in ITEMS}


class OfferIn(BaseModel):
    """A new offer, or a set of edits to one."""

    code: str = Field(min_length=3, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    kind: str
    value: int = Field(default=0, ge=0)
    applies_to: list[str] = Field(default_factory=list, max_length=32)
    enabled: bool = True
    is_public: bool = False
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_redemptions: int | None = Field(default=None, ge=1)
    requires_captcha: bool = False

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        # Stored and compared uppercase, so "diwali25" and "DIWALI25" cannot become two
        # offers — one of which would then have its own separate single-use record.
        return v.strip().upper()

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        return v

    @field_validator("applies_to")
    @classmethod
    def _real_items(cls, v: list[str]) -> list[str]:
        # A typo here silently makes the code apply to nothing, which presents to the
        # candidate as "that code does not apply to this item" on every item they try.
        unknown = [i for i in v if i not in _ITEM_IDS]
        if unknown:
            raise ValueError(f"unknown item ids: {', '.join(unknown)}")
        return v

    @field_validator("value")
    @classmethod
    def _sane_value(cls, v: int, info) -> int:
        kind = (info.data or {}).get("kind")
        if kind == "percent" and not (1 <= v <= 100):
            raise ValueError("a percent offer needs a value between 1 and 100")
        return v

    def check_window(self) -> None:
        """An offer that ends before it starts can never be used by anybody."""
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise AppError(
                message="The offer ends before it starts.",
                status_code=400,
                code="OFFER_WINDOW_INVALID",
            )


class OfferOut(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    kind: str
    value: int
    applies_to: list[str]
    enabled: bool
    is_public: bool
    starts_at: datetime | None
    ends_at: datetime | None
    max_redemptions: int | None
    requires_captcha: bool
    #: How many accounts have used it. The number that decides whether it can be deleted.
    redemptions: int
    #: Rupees given away, so an offer's cost is visible next to the offer itself rather than
    #: needing a separate report to notice a code that has quietly cost thousands.
    discount_given_rupees: int
    #: Why this offer cannot be bought right now, or "" when nothing is wrong.
    #:
    #: THIS EXISTS BECAUSE THE ONE FAILURE IT REPORTS WAS INVISIBLE FROM EVERY ADMIN SCREEN.
    #: An offer with `requires_captcha` on a deployment where TURNSTILE_SECRET_KEY is unset
    #: refuses every single purchase — correctly, because captcha.py fails closed rather than
    #: waiving a check the offer was priced on — but the only place that state surfaced was a
    #: toast in front of a candidate who could do nothing about it, reading "please try again
    #: later" for something that will never resolve on its own.
    #:
    #: `enabled` says the offer is switched on. It can be true while this is non-empty, and
    #: that combination is exactly the trap: the row looks healthy in the table and cannot be
    #: redeemed. Nothing here changes what is enforced — this reports the state, it does not
    #: relax it.
    blocked_reason: str = ""


@router.get("", response_model=list[OfferOut], summary="Every offer, with usage")
async def list_offers(
    current_user: AdminUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[OfferOut]:
    rows = (await db.execute(select(Offer).order_by(Offer.created_at.desc()))).scalars().all()

    # One grouped query rather than one per offer. The list is small today, and a per-row
    # query in an admin list is how a page that was fine at ten rows times out at two hundred.
    usage = {
        r[0]: (r[1], r[2])
        for r in (
            await db.execute(
                select(
                    OfferRedemption.offer_id,
                    func.count(),
                    func.coalesce(
                        func.sum(
                            OfferRedemption.original_paise - OfferRedemption.charged_paise
                        ),
                        0,
                    ),
                ).group_by(OfferRedemption.offer_id)
            )
        ).all()
    }

    # Read once for the whole list rather than per row: it is one process-wide setting, and
    # asking per offer would imply it could differ between them.
    captcha_ready = bool(settings.TURNSTILE_SECRET_KEY)

    return [
        OfferOut(
            id=o.id,
            code=o.code,
            label=o.label,
            kind=o.kind,
            value=o.value,
            applies_to=list(o.applies_to or []),
            enabled=o.enabled,
            is_public=o.is_public,
            starts_at=o.starts_at,
            ends_at=o.ends_at,
            max_redemptions=o.max_redemptions,
            requires_captcha=o.requires_captcha,
            redemptions=usage.get(o.id, (0, 0))[0],
            discount_given_rupees=usage.get(o.id, (0, 0))[1] // 100,
            blocked_reason=_blocked_reason(o, captcha_ready=captcha_ready),
        )
        for o in rows
    ]


def _blocked_reason(offer: Offer, *, captcha_ready: bool) -> str:
    """
    Why this offer refuses every purchase, in words an admin can act on.

    Deliberately NOT a boolean. "Blocked: yes" sends somebody to read the source; the
    sentence names both fixes, and which one is right is a product decision — a public
    launch code wants the captcha and therefore the key, a code shared with four friends
    wants neither.

    Only reports states that are certain and permanent. An expired window or an exhausted
    `max_redemptions` is already visible in its own column and is the offer working as
    configured, not a misconfiguration.
    """
    if offer.requires_captcha and not captcha_ready:
        return (
            "Requires human verification, but TURNSTILE_SECRET_KEY is not set on this "
            "deployment — every purchase using this code is refused. Either set that key "
            "(plus NEXT_PUBLIC_TURNSTILE_SITE_KEY on the frontend), or turn off "
            "\"requires captcha\" here."
        )
    return ""


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an offer")
async def create_offer(
    request: OfferIn,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    request.check_window()
    offer = Offer(
        id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        code=request.code,
        label=request.label,
        kind=request.kind,
        value=request.value,
        applies_to=request.applies_to,
        enabled=request.enabled,
        is_public=request.is_public,
        starts_at=request.starts_at,
        ends_at=request.ends_at,
        max_redemptions=request.max_redemptions,
        requires_captcha=request.requires_captcha,
        created_by=current_user.user_id,
    )
    db.add(offer)
    try:
        await db.flush()
    except IntegrityError as exc:
        # The unique index on `code`. Reported as a conflict rather than a 500, because
        # reusing a code by accident is a normal thing for an admin to do.
        raise AppError(
            message=f"The code {request.code} already exists.",
            status_code=409,
            code="OFFER_CODE_TAKEN",
        ) from exc

    logger.info(
        "offer_created",
        code=offer.code,
        kind=offer.kind,
        value=offer.value,
        public=offer.is_public,
        by=str(current_user.user_id),
    )
    return {"id": str(offer.id), "code": offer.code}


class OfferPatch(BaseModel):
    """
    Partial edits. Every field optional; only what is sent changes.

    `enabled` on its own is the kill switch, and it is the field this endpoint exists for:
    `PATCH {"enabled": false}` stops a code working for everybody on the next request, and
    `true` brings it back with its redemption history intact.
    """

    label: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    is_public: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_redemptions: int | None = Field(default=None, ge=1)
    requires_captcha: bool | None = None

    #: Deliberately absent: `code`, `kind` and `value`.
    #:
    #: Editing what a code MEANS after people have used it makes the redemption record a lie
    #: — the rows say what was charged under the old terms, and the offer would claim
    #: different ones. Switch it off and make a new code instead.


@router.patch("/{offer_id}", summary="Edit an offer, including turning it on or off")
async def update_offer(
    offer_id: uuid.UUID,
    request: OfferPatch,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    offer = await db.get(Offer, offer_id)
    if offer is None:
        raise NotFoundError("Offer", str(offer_id))

    changes = request.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(offer, field, value)
    offer.updated_at = datetime.now(UTC)

    if offer.starts_at and offer.ends_at and offer.ends_at <= offer.starts_at:
        raise AppError(
            message="The offer ends before it starts.",
            status_code=400,
            code="OFFER_WINDOW_INVALID",
        )

    logger.info(
        "offer_updated",
        code=offer.code,
        changed=sorted(changes),
        enabled=offer.enabled,
        by=str(current_user.user_id),
    )
    return {"id": str(offer.id), "code": offer.code, "enabled": offer.enabled}


@router.delete("/{offer_id}", summary="Delete an offer that has never been used")
async def delete_offer(
    offer_id: uuid.UUID,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    offer = await db.get(Offer, offer_id)
    if offer is None:
        raise NotFoundError("Offer", str(offer_id))

    used = await db.scalar(
        select(func.count())
        .select_from(OfferRedemption)
        .where(OfferRedemption.offer_id == offer_id)
    )
    if used:
        # The foreign key cascades, so deleting would take the redemption records with it —
        # and those are the audit trail for revenue that was given away. Switching off
        # achieves everything deletion would, without destroying evidence.
        raise AppError(
            message=(
                f"{offer.code} has been used {used} time(s). Turn it off instead — deleting "
                "it would remove the record of who claimed it."
            ),
            status_code=409,
            code="OFFER_IN_USE",
        )

    await db.delete(offer)
    logger.info("offer_deleted", code=offer.code, by=str(current_user.user_id))
    return {"status": "deleted"}


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

reconcile_router = APIRouter(prefix="/admin/payments", tags=["Admin — Payments"])


@reconcile_router.get("/unapplied", summary="Captured payments that were never credited")
async def list_unapplied(
    current_user: AdminUser,  # noqa: ARG001
    days: int = 30,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Money that arrived and product that never did.

    WHY THIS CAN HAPPEN AT ALL. The webhook is the primary granting path and a webhook is not
    a guarantee — pointed at the wrong URL, signed with the wrong secret, blocked, or dropped,
    it simply never arrives. Verify-on-return covers payments made from a browser that stays
    open, and covers nothing that was paid before it existed. Neither helps a payment that
    already happened, and "we fixed the webhook" does not go back and grant it.

    READ-ONLY. It says what is missing; `POST /apply` is what acts. Being able to look without
    acting matters here, because the thing being looked at is other people's money.
    """
    from app.models.billing import CreditEvent  # noqa: PLC0415
    from app.services.billing import razorpay  # noqa: PLC0415
    from app.services.billing.plans import get_item  # noqa: PLC0415

    payments = await razorpay.list_recent_payments(since_days=days)
    captured = [p for p in payments if p.get("status") == "captured"]
    if not captured:
        return {"unapplied": [], "checked": len(payments)}

    ids = [str(p.get("id")) for p in captured if p.get("id")]
    applied = set(
        (
            await db.execute(
                select(CreditEvent.payment_ref).where(CreditEvent.payment_ref.in_(ids))
            )
        ).scalars()
    )

    out = []
    for p in captured:
        pid = str(p.get("id") or "")
        if not pid or pid in applied:
            continue
        notes = p.get("notes") or {}
        item = get_item(str(notes.get("item_id") or ""))
        out.append(
            {
                "payment_id": pid,
                "amount_paise": int(p.get("amount") or 0),
                "amount_rupees": int(p.get("amount") or 0) / 100,
                "email": p.get("email") or "",
                "created_at": p.get("created_at"),
                "user_id": str(notes.get("user_id") or ""),
                "item_id": str(notes.get("item_id") or ""),
                "item_name": item.name if item else "(unknown item)",
                # A payment whose notes name no known user or item cannot be applied
                # automatically — granting a guess would be inventing a purchase.
                "applicable": bool(item and notes.get("user_id")),
            }
        )
    return {"unapplied": out, "checked": len(payments)}


@reconcile_router.post("/apply", summary="Credit every captured payment that was never applied")
async def apply_unapplied(
    current_user: AdminUser,
    days: int = 30,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Grant what was paid for. Idempotent, and safe to run repeatedly.

    EVERY CHECK THE OTHER TWO PATHS MAKE, MADE AGAIN HERE:

      * only `captured` payments — authorised is not money
      * the amount against the item's real price, recomputed from the offer row when one was
        used, so a discounted payment is accepted for what it should have cost and no more
      * the ledger for idempotency, so a payment the webhook has since delivered is skipped
        rather than granted twice

    WHAT IT WILL NOT DO. A payment whose notes name no user, or an item that is not in the
    catalogue, is REPORTED and not applied. Granting the nearest thing would be inventing a
    purchase nobody made, and an admin reading a list of three anomalies is a better outcome
    than a silent guess.
    """
    from app.models.billing import CreditEvent  # noqa: PLC0415
    from app.services.billing import offers, razorpay  # noqa: PLC0415
    from app.services.billing.credits import KIND_PURCHASE, grant  # noqa: PLC0415
    from app.services.billing.plans import get_item  # noqa: PLC0415

    payments = await razorpay.list_recent_payments(since_days=days)
    granted: list[dict] = []
    skipped: list[dict] = []

    for p in payments:
        pid = str(p.get("id") or "")
        if not pid or p.get("status") != "captured":
            continue

        already = await db.scalar(
            select(CreditEvent.id).where(CreditEvent.payment_ref == pid)
        )
        if already:
            continue

        notes = p.get("notes") or {}
        item = get_item(str(notes.get("item_id") or ""))
        raw_user = str(notes.get("user_id") or "")
        if item is None or not raw_user:
            skipped.append({"payment_id": pid, "reason": "notes name no known user or item"})
            continue
        try:
            user_uuid = uuid.UUID(raw_user)
        except ValueError:
            skipped.append({"payment_id": pid, "reason": "user id in notes is not a uuid"})
            continue

        amount = int(p.get("amount") or 0)
        offer_code = str(notes.get("offer_code") or "").strip().upper()
        if offer_code:
            offer = await offers.find_code(db, offer_code)
            expected = offers.charge_for(offer, item) if offer else item.price_paise
        else:
            offer = None
            expected = item.price_paise

        if amount < expected:
            skipped.append(
                {"payment_id": pid, "reason": f"paid {amount} against an expected {expected}"}
            )
            continue

        if offer is not None:
            # Already redeemed by this account is not a reason to withhold the grant: the
            # code has been counted, and the money was still taken.
            with contextlib.suppress(offers.OfferError):
                await offers.redeem_verified(
                    db,
                    offer=offer,
                    item=item,
                    user_id=user_uuid,
                    charged_paise=amount,
                    payment_ref=pid,
                )

        await grant(
            db,
            user_uuid,
            item.feature,
            item.quantity,
            kind=KIND_PURCHASE,
            payment_ref=pid,
            detail={
                "item_id": item.id,
                "amount_paise": amount,
                "offer": offer_code,
                # So a support question can tell how this arrived. A ledger full of
                # "reconcile" entries is a webhook that has never worked.
                "granted_via": "reconcile",
            },
        )
        granted.append(
            {
                "payment_id": pid,
                "user_id": raw_user,
                "item_id": item.id,
                "quantity": item.quantity,
            }
        )
        logger.info(
            "payment_reconciled",
            payment_id=pid,
            user_id=raw_user,
            item=item.id,
            by=str(current_user.user_id),
        )

    return {"granted": granted, "skipped": skipped}
