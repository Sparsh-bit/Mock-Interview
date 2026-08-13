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

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
        )
        for o in rows
    ]


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
