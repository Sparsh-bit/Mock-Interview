"""
The referral page and the claim — api/v1/referrals.py

GET  /referrals/me     — this account's code, and how it is doing.
POST /referrals/claim  — a new account applies somebody else's code.

NEITHER ROUTE GRANTS ANYTHING. Claiming records an intention; the credit is written later,
by `credits.consume`, once the referred account has paid for and used something. That
separation is the whole anti-farm design and it is described in
`services/billing/referrals.py` — the endpoints here are deliberately thin so there is no
second place where a referral could be decided.

THE ACCOUNT IS THE TOKEN, NEVER THE BODY. `ClaimRequest` carries a code and nothing else: no
user id, no referrer id, no reward, no quantity. That absence is the security control, in the
same way `CheckoutRequest` carrying no `amount` is — a field that does not exist cannot be
tampered with, and `tests/test_pentest_referrals.py` asserts the absence so that adding one
"for convenience" has to be a decision somebody makes on purpose.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.session import get_db
from app.services.billing import referrals

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/referrals", tags=["Referrals"])

#: A claim can be attempted a handful of times an hour, per account.
#:
#: NOT ABOUT LOAD. `POST /referrals/claim` answers "does this code exist" differently from
#: "this code cannot be used here", which makes it an oracle for enumerating live accounts.
#: Eight bits short of forty is a large space, but an unlimited endpoint is still the wrong
#: shape to leave open, and a real candidate types their friend's code once and gets it right
#: or nearly right.
_claim_rate_limit = rate_limiter(
    limit=10,
    window_seconds=3600,
    key_builder=lambda user_id: f"rate_limit:referral_claim:{user_id}:hourly",
    action="applying a referral code",
)


class ReferralOut(BaseModel):
    """This account's referral state. Counts only — never who."""

    code: str
    claimed: int
    qualified: int
    rewarded: int
    reward_feature: str
    reward_quantity: int
    referred_by_code: str | None
    referred_reward_granted: bool


class ClaimRequest(BaseModel):
    #: The ONLY field. See the module docstring.
    code: str = Field(min_length=1, max_length=32)


@router.get("/me", response_model=ReferralOut, summary="This account's referral code")
async def my_referrals(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ReferralOut:
    """
    The code, created on first sight, plus what it has earned.

    A GET that can write — it allocates the code if this account has never had one. Same
    lazy-creation pattern, and the same justification, as `credits._plan_row`: signup is not
    the only way an account comes into existence here, and an account that can never refer
    anybody because a hook did not fire is a worse failure than a write on a read.
    """
    status = await referrals.status_for(db, current_user.user_id)
    return ReferralOut(**vars(status))


@router.post(
    "/claim",
    response_model=ReferralOut,
    dependencies=[Depends(_claim_rate_limit)],
    summary="Apply somebody else's referral code to this new account",
)
async def claim_referral(
    request: ClaimRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ReferralOut:
    """
    Record that this account was referred. Grants nothing.

    Every refusal — your own code, a code you have already used, an account that is not new,
    a mutual pair — comes back as a 400 with a message the candidate can act on. See
    `referrals.claim` for what each one closes.
    """
    await referrals.claim(db, user_id=current_user.user_id, code=request.code)
    status = await referrals.status_for(db, current_user.user_id)
    return ReferralOut(**vars(status))
