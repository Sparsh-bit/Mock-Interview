"""
A suspended account gets back in on its own — tests/test_suspension_expiry.py

REPORTED: "once the id gets suspended then it is not opening even if we log out from
everywhere make sure that you fix that thing".

The report was accurate and logout was not the culprit. `UserPlan.is_banned` is a persisted
column; signing out has never touched it and should not. Nothing else lifted it either, so a
detector whose own module header calls itself fallible — and names the honest population it
will hit hardest, campus students on phones behind two layers of NAT — produced an
IRREVERSIBLE penalty. The evidence expired after a week; the punishment did not.

These tests are behavioural rather than source pins, because the thing that has to be true is
"the next request works", and every part of that is easy to get individually right and still
leave the user locked out: the flag cleared but the strike counter left behind, the window
computed from the wrong column, or the lift rolled back with the request that triggered it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.core.security import _is_banned

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def banned_user():
    """A user whose plan row is suspended, with the ban's age under the caller's control."""
    from app.db.session import AsyncSessionFactory, engine
    from app.models.base import Base
    from app.models.billing import UserPlan
    from app.models.user import User

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uid = uuid.uuid4()
    async with AsyncSessionFactory() as db:
        db.add(
            User(id=uid, supabase_uid=str(uid), email=f"ban-{uid}@example.test",
                 is_active=True, is_admin=False)
        )
        await db.flush()
        db.add(UserPlan(user_id=uid, is_banned=False))
        await db.commit()

    async def suspend(*, hours_ago: float, unbanned_count: int = 0) -> None:
        from sqlalchemy import select

        async with AsyncSessionFactory() as db:
            plan = await db.scalar(select(UserPlan).where(UserPlan.user_id == uid))
            plan.is_banned = True
            plan.ban_reason = "shared_account"
            plan.banned_at = datetime.now(UTC) - timedelta(hours=hours_ago)
            plan.unbanned_count = unbanned_count
            await db.commit()

    async def state() -> dict:
        from sqlalchemy import select

        async with AsyncSessionFactory() as db:
            plan = await db.scalar(select(UserPlan).where(UserPlan.user_id == uid))
            return {
                "is_banned": plan.is_banned,
                "banned_at": plan.banned_at,
                "ban_reason": plan.ban_reason,
                "unbanned_count": plan.unbanned_count,
            }

    return {"user_id": uid, "suspend": suspend, "state": state}


async def _check(user_id: uuid.UUID) -> bool:
    """Ask the real gate, through a real session, the way an authenticated request does."""
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        return await _is_banned(db, user_id)


async def test_a_fresh_suspension_still_blocks(banned_user):
    """The fix must not make the suspension decorative. Inside the window it holds."""
    await banned_user["suspend"](hours_ago=0)
    assert await _check(banned_user["user_id"]) is True
    assert (await banned_user["state"]())["is_banned"] is True


async def test_a_suspension_past_its_window_lets_the_user_back_in(banned_user):
    """THE REPORTED BUG. Past the cooling-off window the next request simply works."""
    await banned_user["suspend"](hours_ago=settings.ACCOUNT_SUSPENSION_HOURS + 1)

    assert await _check(banned_user["user_id"]) is False, "still locked out after the window"

    # And it is genuinely cleared in the database, not merely waved through on the read —
    # otherwise every other place that reads `is_banned` (autopay, the credit ledger, the
    # admin ban list) would still treat the account as suspended.
    after = await banned_user["state"]()
    assert after["is_banned"] is False
    assert after["banned_at"] is None
    assert after["ban_reason"] is None


async def test_the_lift_is_recorded_so_a_repeat_is_visible(banned_user):
    """
    `unbanned_count` is the only trace that this account has been here before, and it is what
    makes the next suspension longer. A lift that forgot to increment it would hand a sharer
    the minimum window forever.
    """
    await banned_user["suspend"](hours_ago=settings.ACCOUNT_SUSPENSION_HOURS + 1)
    await _check(banned_user["user_id"])
    assert (await banned_user["state"]())["unbanned_count"] == 1


async def test_a_repeat_offender_serves_longer_before_being_let_back_in(banned_user):
    """
    The escalation has to actually gate the request, not just compute a bigger number. A
    second suspension of the same age as a first must still be in force.
    """
    aged = settings.ACCOUNT_SUSPENSION_HOURS + 1
    await banned_user["suspend"](hours_ago=aged, unbanned_count=1)
    assert await _check(banned_user["user_id"]) is True, (
        "a repeat suspension expired on the first-offence schedule"
    )

    # ...and it does end eventually. Nothing is permanent.
    await banned_user["suspend"](hours_ago=aged * 4, unbanned_count=1)
    assert await _check(banned_user["user_id"]) is False


async def test_a_suspension_with_no_timestamp_is_not_treated_as_expired(banned_user):
    """
    Absence of evidence is not evidence of age. A row with `is_banned` set and `banned_at`
    NULL cannot be aged, and clearing it would lift a suspension on the strength of missing
    data — the one direction where guessing costs the product rather than the user.
    """
    from sqlalchemy import select

    from app.db.session import AsyncSessionFactory
    from app.models.billing import UserPlan

    await banned_user["suspend"](hours_ago=999)
    async with AsyncSessionFactory() as db:
        plan = await db.scalar(
            select(UserPlan).where(UserPlan.user_id == banned_user["user_id"])
        )
        plan.banned_at = None
        await db.commit()

    assert await _check(banned_user["user_id"]) is True


async def test_the_expiry_can_be_disabled(banned_user, monkeypatch):
    """An operator who wants the original admin-only behaviour sets the window to zero."""
    monkeypatch.setattr(settings, "ACCOUNT_SUSPENSION_HOURS", 0)
    await banned_user["suspend"](hours_ago=10_000)
    assert await _check(banned_user["user_id"]) is True
    assert (await banned_user["state"]())["is_banned"] is True


async def test_an_unsuspended_account_is_never_touched(banned_user):
    """The fast path: not banned, no writes, no counter movement."""
    before = await banned_user["state"]()
    assert before["is_banned"] is False
    assert await _check(banned_user["user_id"]) is False
    after = await banned_user["state"]()
    assert after["unbanned_count"] == before["unbanned_count"], (
        "the fast path incremented the repeat counter — every clean request would inflate it"
    )
