"""
Offers and promo codes, from the admin side — api/v1/admin_offers.py

GET    /admin/offers          — every code, with how many times each has been used
POST   /admin/offers          — create one
POST   /admin/offers/preview  — what each item would cost under terms not yet created
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

import asyncio
import contextlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.security import AdminUser
from app.db.session import get_db
from app.models.billing import Offer, OfferRedemption
from app.services.billing.banners import (
    BannerRejected,
    banner_spec,
    validate_banner,
)
from app.services.billing.offers import KINDS
from app.services.billing.plans import FEATURES, ITEMS, items_for

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/offers", tags=["Admin — Offers"])

_ITEM_IDS = {i.id for i in ITEMS}


def _expand_features(features: Sequence[str]) -> list[str]:
    """
    The item ids a set of chosen features covers, as of right now.

    A SCOPE IS CHOSEN PER FEATURE AND STORED PER ITEM, in the `applies_to` column that has
    always been there. An admin thinks "this code is for drills"; the column has only ever
    meant "these item ids", so the feature is expanded at creation time into
    ["communication_1", "communication_10"] and that list is what gets written.

    WHY NOT A COLUMN OF ITS OWN. Migrations here are applied BY HAND against Supabase
    (docs/DEPLOY.md), so a new column is a window in which every money path selects a column
    the database does not have yet. `applies_to` exists, is JSONB, is already read by the one
    place a scope is enforced, and already means exactly this.

    THE EXPANSION IS A SNAPSHOT, NOT A RULE, and this is the accepted cost of that choice.
    Choosing "interviews" today records the interview items that exist TODAY. Add a third
    interview bundle to plans.ITEMS tomorrow and every coupon created before it falls outside
    it — the new id is simply not in the list, so the code is refused on that bundle and the
    candidate pays full price rather than being handed a discount nobody priced. The failure
    lands on the safe side, but a feature-scoped code is genuinely not a standing rule about a
    feature: it is a frozen list of ids. A code that must cover everything forever is the one
    with an EMPTY scope, and the empty case is the only one immune to this.

    An empty `features` therefore expands to nothing, which leaves `applies_to` empty — and an
    empty `applies_to` has always meant "every item". So "no feature chosen" keeps meaning
    "applies to everything", exactly as every offer created before this field behaves.
    """
    return [item.id for f in features for item in items_for(f)]


def _features_covered(applies_to: Sequence[str]) -> list[str]:
    """
    Which features a stored id list represents — the inverse of `_expand_features`.

    DERIVED ON READ RATHER THAN STORED ALONGSIDE. Writing the chosen features down next to the
    expanded ids would be two records of one decision, and the two can drift: the ids are what
    a discount is actually computed against, so a features column that disagreed with them
    would be describing a coupon nobody has. This reads the ids and says what they add up to.

    IT ONLY CLAIMS A FEATURE WHEN THE ROUND TRIP IS EXACT — every item of that feature is
    present, AND the features together re-expand to precisely what is stored. Otherwise it
    returns nothing and `applies_to` is the only honest answer. Two real cases land there: a
    hand-picked list from before this field existed ("interview_1" alone is NOT "applies to
    interviews", and saying so would promise a discount on the five-pack that does not exist),
    and a feature-scoped code that a newly-added item has left behind — see the snapshot note
    above, where the code quietly stops covering the whole feature and the admin screen should
    stop saying that it does.
    """
    if not applies_to:
        # Unrestricted. Empty means the same thing on the way out as on the way in: every
        # feature, which is what every offer that predates this field is.
        return []
    stored = set(applies_to)
    covered: list[str] = [f for f in FEATURES if {i.id for i in items_for(f)} <= stored]
    if set(_expand_features(covered)) != stored:
        return []
    return covered


class OfferTerms(BaseModel):
    """
    The fields that decide money: what the discount is, and what it applies to.

    SHARED BY CREATION AND BY THE PRICE PREVIEW, as one definition, so the preview cannot
    price something other than what creation would make. The preview exists to tell an admin
    what a code will do before it is live; a preview that validated or normalised its inputs
    differently from `POST ""` would be a preview of a different offer, which is worse than no
    preview at all because it would be believed.
    """

    kind: str
    value: int = Field(default=0, ge=0)
    #: Which features the code covers. EMPTY MEANS EVERY FEATURE — see `_expand_features`,
    #: and note that the empty case is also the only scope that survives a new item being
    #: added to the catalogue.
    applies_to_features: list[str] = Field(default_factory=list, max_length=len(FEATURES))
    #: Item ids named outright. Predates `applies_to_features` and is kept because it can say
    #: things a feature cannot — "the five-pack only" — and because requests already send it.
    #:
    #: ON `OfferTerms` RATHER THAN ON `OfferIn`, because it decides money, which is what this
    #: model is defined to hold. It also has to be here for the price preview to be honest: a
    #: preview that ignored an item allowlist would quote a discount on items the created code
    #: would refuse.
    applies_to: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        return v

    @field_validator("applies_to_features")
    @classmethod
    def _real_features(cls, v: list[str]) -> list[str]:
        # REJECTED, NEVER IGNORED, and the direction of the failure is the reason. A misspelt
        # feature expands to no items, an empty `applies_to` means "every item", so silently
        # dropping "comunication" would not produce a narrow code — it would produce an
        # unrestricted one. The admin would have discounted the entire catalogue while
        # believing they had limited the code to drills.
        unknown = [f for f in v if f not in FEATURES]
        if unknown:
            raise ValueError(
                f"unknown features: {', '.join(unknown)} — expected {', '.join(FEATURES)}"
            )
        # Normalised to catalogue order and de-duplicated, so ["gd", "gd"] and ["gd"] store a
        # byte-identical scope and `_features_covered` reads either back the same way.
        chosen = set(v)
        return [f for f in FEATURES if f in chosen]

    @field_validator("value")
    @classmethod
    def _sane_value(cls, v: int, info) -> int:
        kind = (info.data or {}).get("kind")
        if kind == "percent" and not (1 <= v <= 100):
            raise ValueError("a percent offer needs a value between 1 and 100")
        return v


    @field_validator("applies_to")
    @classmethod
    def _real_items(cls, v: list[str]) -> list[str]:
        # A typo here silently makes the code apply to nothing, which presents to the
        # candidate as the code being refused on every single item they try.
        unknown = [i for i in v if i not in _ITEM_IDS]
        if unknown:
            raise ValueError(f"unknown item ids: {', '.join(unknown)}")
        return v

    @property
    def scope(self) -> list[str]:
        """
        The item ids to store: the chosen features expanded, plus any ids named outright.

        A UNION, because the two fields say the same kind of thing — `applies_to` IS an item
        allowlist and a feature is shorthand for a slice of one, so a request naming both wants
        both. Sorted rather than left in the order the fields happened to mention them, so two
        equivalent requests store an identical list and `_features_covered` reads them back
        identically.

        Both empty stays empty, which is the pre-existing "applies to every item".

        THE PREVIEW READS THIS SAME PROPERTY. That is what makes "what the admin was shown"
        and "what was written to the column" the same computation rather than two that agree
        today.
        """
        wanted = set(self.applies_to) | set(_expand_features(self.applies_to_features))
        return sorted(wanted)


class OfferIn(OfferTerms):
    """A new offer."""

    code: str = Field(min_length=3, max_length=40)
    label: str = Field(min_length=1, max_length=120)
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

    def check_window(self) -> None:
        """An offer that ends before it starts can never be used by anybody."""
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise AppError(
                message="The offer ends before it starts.",
                status_code=400,
                code="OFFER_WINDOW_INVALID",
            )


class BannerOut(BaseModel):
    """A stored banner, as the admin list shows it."""

    image_url: str
    alt_text: str
    width: int
    height: int
    bytes: int
    content_type: str
    #: Whether the stored image matches the CURRENT contract.
    #:
    #: Recomputed on read rather than stored, because the contract can change — raising the
    #: minimum width would leave previously-valid banners on file, and an admin needs to see
    #: which ones now need re-exporting without having to compare numbers by eye.
    matches_spec: bool


class OfferOut(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    kind: str
    value: int
    applies_to: list[str]
    #: The features this code covers, DERIVED from `applies_to` rather than stored — see
    #: `_features_covered`. Empty here means one of two things and the pair has to be read
    #: together: with an empty `applies_to` it is "every feature", and with a non-empty one it
    #: is a scope no set of whole features describes, where the item list is the truth.
    applies_to_features: list[str]
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
    #: The promo image, or None. See BannerOut.
    banner: BannerOut | None = None
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

    # ONE QUERY FOR EVERY BANNER, not one per offer. The list is short, but an N+1 here would
    # be a query per row on the page an admin refreshes while iterating on an image.
    banners = await _banners_by_offer(db)

    return [
        OfferOut(
            id=o.id,
            code=o.code,
            label=o.label,
            kind=o.kind,
            value=o.value,
            applies_to=list(o.applies_to or []),
            applies_to_features=_features_covered(list(o.applies_to or [])),
            enabled=o.enabled,
            is_public=o.is_public,
            starts_at=o.starts_at,
            ends_at=o.ends_at,
            max_redemptions=o.max_redemptions,
            requires_captcha=o.requires_captcha,
            redemptions=usage.get(o.id, (0, 0))[0],
            discount_given_rupees=usage.get(o.id, (0, 0))[1] // 100,
            blocked_reason=_blocked_reason(o, captcha_ready=captcha_ready),
            banner=banners.get(o.id),
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
        # The chosen features, expanded into the concrete ids that exist at this moment. See
        # `_expand_features` for why this is a snapshot and what that costs.
        applies_to=request.scope,
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
        # Both halves, because the stored ids are the snapshot and the features are what the
        # admin believed they were choosing. When a scope later looks wrong, the question is
        # which of the two moved.
        features=request.applies_to_features,
        scope=offer.applies_to,
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


class PreviewRow(BaseModel):
    """What one catalogue item would cost under terms that do not exist yet."""

    item_id: str
    feature: str
    name: str
    quantity: int
    price_paise: int
    charged_paise: int
    #: False when the code's scope does not reach this item. `charged_paise` is then simply the
    #: full price — the row is present so the admin sees what is NOT discounted, which is the
    #: half of the answer a list of covered items cannot give.
    covered: bool


@router.post("/preview", summary="What each item would cost under terms not yet created")
async def preview_offer(
    request: OfferTerms,
    current_user: AdminUser,
) -> list[PreviewRow]:
    """
    Price the whole catalogue under terms an admin is still typing.

    WHY IT EXISTS. "40% off, drills only" is a sentence; ₹19 becoming ₹11 is a decision. An
    admin creating a code is choosing a number they cannot see, and the two mistakes this
    prevents are both expensive and both silent: a percentage that rounds to a price nobody
    intended, and a scope that covers more than it reads like it does — an empty feature list
    means EVERY feature, so "I did not tick anything" and "I discounted the entire catalogue"
    are the same request.

    IT TAKES `OfferTerms`, THE SAME MODEL CREATION TAKES, and that is the whole point. A
    preview with its own parsing or its own validation would be a preview of a different
    offer, which is worse than no preview because it would be believed. The scope shown here
    is `request.scope` — byte-identical to what `POST ""` would write into `applies_to`.

    IT TOUCHES NO DATABASE. There is deliberately no `db` dependency: nothing is looked up and
    nothing could be written even by accident. The `Offer` it builds is never added to a
    session; it exists only to be handed to the same two functions the real quote path uses.
    """
    from app.services.billing import offers  # noqa: PLC0415

    # Unpersisted, and constructed with exactly the three fields that decide money, so the
    # figures below come from the same arithmetic a live code would get. Building a
    # lookalike object with its own fields would be a second definition of an offer.
    draft = Offer(
        code="PREVIEW",
        label="preview",
        kind=request.kind,
        value=request.value,
        applies_to=request.scope,
    )

    rows: list[PreviewRow] = []
    for item in ITEMS:
        # TWO SEPARATE QUESTIONS, ASKED SEPARATELY. `charge_for` answers "how much under these
        # terms" and deliberately does not consider scope; `covers` answers "does this code
        # reach this item at all". Collapsing them would price an out-of-scope item at the
        # discount and show the admin a saving the till would refuse.
        covered = offers.covers(draft, item)
        rows.append(
            PreviewRow(
                item_id=item.id,
                feature=item.feature,
                name=item.name,
                quantity=item.quantity,
                price_paise=item.price_paise,
                charged_paise=offers.charge_for(draft, item) if covered else item.price_paise,
                covered=covered,
            )
        )
    return rows


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


# ─── The promo banner ─────────────────────────────────────────────────────────────────────
#
# An optional image per offer, rendered as a strip on every candidate's dashboard and linking
# to the pricing page's apply-a-code box. The offer is the thing being advertised, so the
# banner hangs off the offer rather than being a standalone piece of content: switching the
# code off takes its advertisement down with it, which is the behaviour anybody would expect
# and the one they would otherwise have to remember to do by hand.


@lru_cache(maxsize=1)
def _banner_storage() -> Any:
    """
    The process-wide Supabase client, built once.

    Same reasoning as resume.py's: `create_client` builds a fresh set of HTTP clients every
    call, so calling it per request pays a new TLS handshake to Supabase before sending a
    byte. The underlying client is httpx-based and thread-safe, which matters because the
    calls here run in a worker thread.
    """
    from supabase import create_client  # noqa: PLC0415

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def _to_banner_out(row) -> BannerOut:  # noqa: ANN001 - OfferBanner, imported lazily
    """
    A stored row as the admin sees it, including whether it still meets the contract.

    `matches_spec` is recomputed here rather than stored, because the contract can change:
    raising the minimum width would leave previously-valid banners on file, and an admin needs
    to see which ones now need re-exporting rather than comparing numbers by eye.
    """
    spec = banner_spec()
    tolerance = spec.aspect_ratio * settings.BANNER_ASPECT_TOLERANCE
    return BannerOut(
        image_url=row.image_url,
        alt_text=row.alt_text,
        width=row.width,
        height=row.height,
        bytes=row.bytes,
        content_type=row.content_type,
        matches_spec=(
            row.width >= spec.min_width
            and abs(row.width / row.height - spec.aspect_ratio) <= tolerance
        ),
    )


async def _banners_by_offer(db: AsyncSession) -> dict[uuid.UUID, BannerOut]:
    """
    Every banner, keyed by offer — or nothing at all if the table does not exist yet.

    THE MISSING-TABLE CASE IS REAL. Migrations here are applied by hand (docs/DEPLOY.md), so
    between deploying this code and running migration 021 the table is absent. Without the
    guard the offers list — the page an admin would be looking at — would 500. Degrading to
    "no banners" instead means the rest of the page works and the feature appears once they
    migrate.

    A SAVEPOINT, because catching the Python exception is not sufficient: an UndefinedTable
    aborts the surrounding Postgres transaction, and every later query in this request would
    then fail with "current transaction is aborted" rather than returning data.
    """
    from sqlalchemy.exc import ProgrammingError

    from app.models.billing import OfferBanner

    try:
        async with db.begin_nested():
            rows = (await db.scalars(select(OfferBanner))).all()
    except ProgrammingError:
        logger.warning("offer_banners_table_missing", detail="run migration 021")
        return {}
    return {row.offer_id: _to_banner_out(row) for row in rows}


async def _banner_for(db: AsyncSession, offer_id: uuid.UUID) -> BannerOut | None:
    """
    The banner for one offer, or None — including when the table does not exist yet.

    THE MISSING-TABLE CASE IS REAL AND HAS TO BE SURVIVED. Migrations here are applied by hand
    (docs/DEPLOY.md), so between deploying this code and running migration 021 the table is
    absent. Without this guard the offers list — the page an admin would be on — would 500,
    which is a worse outcome than the banner column simply being empty until they migrate.
    """
    from sqlalchemy.exc import ProgrammingError

    from app.models.billing import OfferBanner

    # A SAVEPOINT, because catching the Python exception is not enough: an UndefinedTable
    # aborts the surrounding Postgres transaction, and every later query in this request
    # would then fail with "current transaction is aborted" instead of returning data.
    try:
        async with db.begin_nested():
            row = await db.scalar(
                select(OfferBanner).where(OfferBanner.offer_id == offer_id)
            )
    except ProgrammingError:
        logger.warning("offer_banners_table_missing", detail="run migration 021")
        return None
    if row is None:
        return None
    return _to_banner_out(row)


@router.get("/banner-spec", summary="What a banner image has to be")
async def get_banner_spec(current_user: AdminUser) -> dict:
    """
    The image contract, served rather than hardcoded in the form.

    The validator and the form must not be able to disagree — an admin told "2400x800" by a
    form while the server accepts something else is a bug that presents as the upload
    mysteriously failing. One source, read by both.
    """
    return banner_spec().as_dict()


@router.post("/{offer_id}/banner", summary="Upload or replace an offer's banner image")
async def upload_offer_banner(
    offer_id: uuid.UUID,
    current_user: AdminUser,
    file: UploadFile = File(...),  # noqa: B008
    alt_text: str = Form(""),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Validate the image, store it, and point the offer at it.

    VALIDATED BEFORE IT IS STORED, so a refused upload leaves nothing behind. The order is
    deliberate — uploading first and checking after means a rejected image still occupies the
    bucket, and nothing ever cleans those up.

    REPLACING DELETES THE OLD FILE. Without that, every re-upload during a design iteration
    leaves an orphan in a public bucket: still served, still linkable, and no longer
    referenced by anything that would tell you it exists.
    """
    from app.models.billing import Offer, OfferBanner

    offer = await db.scalar(select(Offer).where(Offer.id == offer_id))
    if offer is None:
        raise NotFoundError("Offer not found")

    data = await file.read()
    verdict = validate_banner(data)
    if isinstance(verdict, BannerRejected):
        # 422 rather than 400: the request was well-formed, the CONTENT is what is
        # unacceptable, and the message is written for the person reading it.
        raise AppError(
            message=verdict.reason,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="BANNER_REJECTED",
        )

    # Falls back to the offer's own label, because alt text is not optional for a link and an
    # empty string would leave a screen reader announcing an unlabelled link to the pricing
    # page. The label is what the offer is called, which is the right thing to say.
    alt = (alt_text or "").strip()[:160] or f"{offer.label} — offer"

    existing = None
    with contextlib.suppress(Exception):
        async with db.begin_nested():
            existing = await db.scalar(
                select(OfferBanner).where(OfferBanner.offer_id == offer_id)
            )

    storage_path = f"banners/{offer_id}/{uuid.uuid4()}.{verdict.fmt}"
    content_type = f"image/{verdict.fmt}"

    def _store() -> None:
        # supabase-py is SYNCHRONOUS. Called inline it blocks the event loop for the whole
        # upload — not just this request, every request this worker has in flight. Same
        # reasoning as the resume upload.
        client = _banner_storage()

        # ── THE BUCKET IS CREATED IF IT IS NOT THERE, AND THAT REMOVES A SETUP STEP ───────
        #
        # This feature otherwise needed two manual actions before it could work at all: run
        # the migration, and go into Supabase to make a public bucket. A feature that silently
        # does nothing until somebody remembers an undocumented second step is a feature that
        # gets reported as broken — which is exactly what happened.
        #
        # PUBLIC, deliberately and unlike `resumes`. The banner is rendered by an <img> on
        # every signed-in candidate's dashboard, so a private bucket would mean minting a
        # signed URL per view: an extra round trip on a page load and a link that expires
        # while the page is open. The content is a marketing image we are choosing to show
        # everybody, so a public URL leaks nothing.
        #
        # Suppressed rather than checked-then-created: "already exists" is the overwhelmingly
        # common outcome and it is not an error, and a check-then-create has a race between
        # two admins uploading at once. If creation genuinely fails the upload below fails too,
        # with the real reason, so nothing is hidden by this.
        with contextlib.suppress(Exception):
            client.storage.create_bucket(
                settings.SUPABASE_STORAGE_BUCKET_BANNERS,
                options={"public": True},
            )

        client.storage.from_(settings.SUPABASE_STORAGE_BUCKET_BANNERS).upload(
            storage_path, data, {"content-type": content_type}
        )

    await asyncio.to_thread(_store)

    public_url = (
        _banner_storage()
        .storage.from_(settings.SUPABASE_STORAGE_BUCKET_BANNERS)
        .get_public_url(storage_path)
    )

    old_path = existing.storage_path if existing else None
    if existing is not None:
        existing.storage_path = storage_path
        existing.image_url = public_url
        existing.alt_text = alt
        existing.width = verdict.width
        existing.height = verdict.height
        existing.bytes = len(data)
        existing.content_type = content_type
        existing.uploaded_by = current_user.user_id
    else:
        db.add(
            OfferBanner(
                offer_id=offer_id,
                storage_path=storage_path,
                image_url=public_url,
                alt_text=alt,
                width=verdict.width,
                height=verdict.height,
                bytes=len(data),
                content_type=content_type,
                uploaded_by=current_user.user_id,
            )
        )

    # AFTER the row is written, and failure here is swallowed: an orphaned old file is
    # untidy, while failing the request would leave the admin thinking the upload did not
    # work when the new banner is already live.
    if old_path:
        def _remove_old() -> None:
            _banner_storage().storage.from_(
                settings.SUPABASE_STORAGE_BUCKET_BANNERS
            ).remove([old_path])

        with contextlib.suppress(Exception):
            await asyncio.to_thread(_remove_old)

    logger.info(
        "offer_banner_uploaded",
        offer_id=str(offer_id),
        actor=current_user.email,
        width=verdict.width,
        height=verdict.height,
        bytes=len(data),
        replaced=bool(old_path),
    )
    return {
        "image_url": public_url,
        "alt_text": alt,
        "width": verdict.width,
        "height": verdict.height,
        "bytes": len(data),
        "content_type": content_type,
        "matches_spec": True,
    }


@router.delete("/{offer_id}/banner", summary="Remove an offer's banner image")
async def delete_offer_banner(
    offer_id: uuid.UUID,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """Take the banner down and delete the file behind it."""
    from app.models.billing import OfferBanner

    row = await db.scalar(select(OfferBanner).where(OfferBanner.offer_id == offer_id))
    if row is None:
        raise NotFoundError("This offer has no banner")

    path = row.storage_path
    await db.delete(row)

    def _remove() -> None:
        _banner_storage().storage.from_(
            settings.SUPABASE_STORAGE_BUCKET_BANNERS
        ).remove([path])

    # Swallowed for the same reason as above: the row is gone, so the banner is down, and
    # failing the request over a leftover file would tell the admin the removal did not work.
    with contextlib.suppress(Exception):
        await asyncio.to_thread(_remove)

    logger.info("offer_banner_deleted", offer_id=str(offer_id), actor=current_user.email)
    return {"status": "deleted"}
