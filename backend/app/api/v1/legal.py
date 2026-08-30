"""
Notice, consent and the grievance contact — api/v1/legal.py

The mechanism behind DPDP §5 (notice), §6 (consent and withdrawal), §8(9)–(10)
(a named contact and a grievance route) and §16 (cross-border disclosure).

`GET /legal/disclosure` IS DELIBERATELY PUBLIC, and it is the only route here that
is. §5 requires the notice to be available *before* processing begins, which means
before there is an account to authenticate — a notice you have to sign up to read is
not notice. It contains no user data: the processor list is derived from this
deployment's own configuration, and the contact is a published one.

Everything else requires a token, because it is about one person's answers.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.session import get_db
from app.models.consent import (
    CONSENT_PURPOSES,
    PURPOSE_AGE_18_PLUS,
    PURPOSE_ANALYTICS,
    PURPOSE_PRIVACY_NOTICE,
    PURPOSE_TERMS,
    SOURCE_SETTINGS,
    SOURCE_SIGNUP,
)
from app.services.legal import consent as consent_service
from app.services.legal.disclosure import NOTICE_VERSION, disclosure

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/legal", tags=["Legal"])


@router.get("/disclosure", summary="Who processes your data, where, and who to complain to")
async def get_disclosure() -> dict:
    """
    The §5 notice content and the §16 transfer disclosure.

    PUBLIC ON PURPOSE — see the module docstring. Returns `draft: true`, which the UI
    is required to surface: this text states verifiable facts about the system, and
    it is not a lawyer-reviewed privacy policy. See docs/COMPLIANCE.md for the list
    of what still needs sign-off.
    """
    return disclosure()


class SignupConsentRequest(BaseModel):
    """
    The three answers taken at signup.

    ALL THREE ARE REQUIRED AND NONE DEFAULTS TO TRUE. §6 wants consent by clear
    affirmative action, and a field that defaults to True is a pre-ticked box in
    a different costume — the one thing §6 names explicitly as not consent.
    """

    #: "I have read the privacy notice." Distinct from agreeing to the terms:
    #: §5 notice and §6 consent are separate obligations and bundling them makes it
    #: impossible to show which one a person actually answered.
    privacy_notice: bool
    terms: bool
    #: "I am 18 or older." §9 prohibits behavioural monitoring of children outright,
    #: and this product measures speech pace, fillers, pauses and presence. The
    #: product cannot ask the question later — by then it has already monitored them.
    age_18_plus: bool
    #: "You may measure how I use the product." THE ONLY OPTIONAL ONE, and the only one
    #: with a default — `False`, which is the safe direction and is not a pre-ticked box:
    #: a client that omits the field records a REFUSAL, not a grant.
    #:
    #: It defaults rather than being required so that this endpoint stays backward
    #: compatible with a browser running the previous bundle. The frontend and backend
    #: deploy separately, and an older client that does not send the field must record
    #: "not agreed" rather than 422 the whole consent call — a signup that ends with no
    #: consent row at all is the exact state DPDP §6 is about.
    analytics: bool = False
    #: Which version of the notice was on screen. Sent by the client rather than
    #: assumed server-side, so a stale tab records what it actually showed.
    notice_version: str = Field(default=NOTICE_VERSION, max_length=32)


@router.post("/consent/signup", status_code=status.HTTP_201_CREATED)
async def record_signup_consent(
    request: SignupConsentRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Record the answers given on the signup screen.

    CALLED AFTER THE SUPABASE ACCOUNT EXISTS, not before, because a consent row needs
    a user to belong to. That ordering leaves a real window — an account created and
    then abandoned before this call — which is why `age_18_plus` is ALSO enforced as
    a gate on the paths that do behavioural monitoring, rather than only here.

    REFUSES rather than recording a `false` for age. The other two are recorded
    whatever the answer, because "they declined the terms" is a fact worth having;
    an under-18 declaration is not a state this product may operate in at all.
    """
    if not request.age_18_plus:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This service is for candidates aged 18 and over. It measures how you "
                "speak and how you present, which the law does not permit us to do for "
                "under-18s."
            ),
        )

    for purpose, granted in (
        (PURPOSE_PRIVACY_NOTICE, request.privacy_notice),
        (PURPOSE_TERMS, request.terms),
        (PURPOSE_AGE_18_PLUS, request.age_18_plus),
        # Recorded whatever the answer, and a `False` here is as much a record as a
        # `True`: "they were asked and said no" is the fact that stops the question
        # being asked again, and it is the evidence that nothing was tracked.
        (PURPOSE_ANALYTICS, request.analytics),
    ):
        await consent_service.record(
            db,
            current_user.user_id,
            purpose=purpose,
            granted=granted,
            source=SOURCE_SIGNUP,
            notice_version=request.notice_version,
        )

    return {"recorded": True, "notice_version": request.notice_version}


class ConsentChangeRequest(BaseModel):
    purpose: str = Field(max_length=64)
    granted: bool
    notice_version: str = Field(default=NOTICE_VERSION, max_length=32)


@router.post("/consent", status_code=status.HTTP_201_CREATED)
async def change_consent(
    request: ConsentChangeRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Give or withdraw one consent. §6(4)–(6): withdrawal must be as easy as giving,
    which is why it is this same endpoint with `granted: false` rather than a
    different flow behind a support ticket.

    Age is not changeable here. Somebody who declared 18+ at signup and now wishes to
    say otherwise is asking for the account to be removed, and the honest route for
    that is deletion — flipping a flag would leave every measurement already taken.
    """
    if request.purpose not in CONSENT_PURPOSES:
        raise HTTPException(status_code=422, detail=f"Unknown purpose: {request.purpose}")
    if request.purpose == PURPOSE_AGE_18_PLUS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Age confirmation cannot be changed here. If you are under 18, delete "
                "your account in Settings and everything held about you goes with it."
            ),
        )

    await consent_service.record(
        db,
        current_user.user_id,
        purpose=request.purpose,
        granted=request.granted,
        source=SOURCE_SETTINGS,
        notice_version=request.notice_version,
    )
    return {"purpose": request.purpose, "granted": request.granted}


@router.get("/consent", summary="What you have and have not agreed to")
async def my_consent(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Every purpose and where it stands, including the ones never asked.

    SCOPED BY THE TOKEN, with no `user_id` parameter — the same rule as the export,
    for the same reason.
    """
    return {
        "notice_version": NOTICE_VERSION,
        "consents": await consent_service.summary(db, current_user.user_id),
    }


async def require_consent(
    db: AsyncSession, user_id: uuid.UUID, purpose: str, *, what: str
) -> None:
    """
    Raise 428 unless this person's newest answer for `purpose` is a grant.

    428 PRECONDITION REQUIRED, not 403. The difference is actionable: 403 says "you
    may not", 428 says "there is something you have to do first", and the client can
    tell them apart without string-matching a message. The body names the purpose so
    the UI knows which prompt to open.

    Deliberately NOT a FastAPI dependency. Consent gating is per-purpose and
    per-endpoint, and a dependency would have to be parameterised into a factory that
    reads no better than one explicit call at the top of the handler that needs it.
    """
    if await consent_service.has_granted(db, user_id, purpose):
        return

    logger.info("consent_required", purpose=purpose)
    raise HTTPException(
        status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        detail={
            "error": "consent_required",
            "purpose": purpose,
            "message": what,
        },
    )
