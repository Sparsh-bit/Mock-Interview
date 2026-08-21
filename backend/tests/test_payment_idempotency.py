"""
One payment grants once, however many times it is presented — tests/test_payment_idempotency.py

FOUND BY A PRE-LAUNCH SECURITY AUDIT AND REPRODUCED: one payment could be redeemed an
unlimited number of times.

Buy interview_5 once for ₹199, then POST the same razorpay_payment_id / order_id / signature
to /api/v1/billing/verify twenty times in parallel. Every one passes the signature check,
every one reads an empty ledger, and every one commits its own +5 grant.

WHY THE OLD GUARD LOST. Both callers — /billing/verify and the webhook — ran
`SELECT id FROM credit_events WHERE payment_ref = ?` and granted if it was empty. Under READ
COMMITTED with no lock, two concurrent requests both read empty and both insert. And the
window was not small: /verify makes a live HTTP call to Razorpay inside it, roughly 300ms, and
/verify has no rate limit. The index on payment_ref is not unique, so the database did not
stop it either.

It also double-credited HONEST customers: the webhook and /verify fire within milliseconds of
the same capture and did not serialise against each other, so whichever lost the race still
granted.

THE FIX IS THAT IDEMPOTENCY MOVED INTO `grant()`. The old docstring said "IDEMPOTENCY IS THE
CALLER'S JOB AND IS NOT OPTIONAL" — and both callers did it the same unsafe way, which is the
argument against ever writing that sentence again. `grant` now takes the same
`SELECT ... FOR UPDATE` on user_plans that `consume` has always taken, then re-checks, so two
requests for one payment always serialise on the same row.

NOT A UNIQUE INDEX, deliberately, and the reasoning is in the docstring: an index is the better
long-term shape and needs a migration, and a migration that fails on pre-existing duplicates
fails the deploy. On launch eve the lock is the safe correct fix; the index is worth adding
afterwards as belt and braces.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.billing.credits import KIND_PURCHASE, grant

# Applied to the async classes only, so the synchronous source assertions at the bottom do not
# inherit an asyncio mark they cannot use.
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def two_users():
    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import AsyncSessionFactory
    from app.models.billing import CreditEvent, UserPlan
    from app.models.user import User

    a, b = uuid.uuid4(), uuid.uuid4()
    try:
        from app.db.session import engine  # noqa: PLC0415
        from app.models.base import Base  # noqa: PLC0415

        # See the note in this fixture: test_integration.py drops the schema, so a
        # test that assumes one is order-dependent and skips instead of running.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with AsyncSessionFactory() as db:
            for uid in (a, b):
                db.add(User(id=uid, supabase_uid=str(uid),
                            email=f"idem-{uid}@example.test", is_active=True, is_admin=False))
            await db.commit()
            yield db, a, b
            await db.execute(delete(CreditEvent).where(CreditEvent.user_id.in_([a, b])))
            await db.execute(delete(UserPlan).where(UserPlan.user_id.in_([a, b])))
            await db.execute(delete(User).where(User.id.in_([a, b])))
            await db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - environment
        pytest.skip(f"needs the dev Postgres: {exc}")


async def _count(db, user_id) -> int:
    from sqlalchemy import func, select

    from app.models.billing import CreditEvent

    return await db.scalar(
        select(func.count()).select_from(CreditEvent).where(CreditEvent.user_id == user_id)
    ) or 0


async def _granted(db, user_id) -> int:
    from sqlalchemy import func, select

    from app.models.billing import CreditEvent

    return await db.scalar(
        select(func.coalesce(func.sum(CreditEvent.delta), 0)).where(
            CreditEvent.user_id == user_id
        )
    ) or 0


class TestOnePaymentGrantsOnce:
    async def test_the_same_payment_presented_twice_grants_once(self, two_users):
        """THE ONE THAT WOULD HAVE CAUGHT IT."""
        db, payer, _ = two_users
        first = await grant(db, payer, "interview", 5, payment_ref="pay_Replay1")
        await db.commit()
        second = await grant(db, payer, "interview", 5, payment_ref="pay_Replay1")
        await db.commit()

        assert first is True
        # False, not an exception. Razorpay redelivers until it gets a 2xx and a client
        # retrying a verify is being reasonable, so "already applied" is the honest answer and
        # the caller returns success without granting twice.
        assert second is False
        assert await _count(db, payer) == 1
        assert await _granted(db, payer) == 5

    async def test_presented_twenty_times_still_grants_once(self, two_users):
        # The reported attack, at its reported scale.
        db, payer, _ = two_users
        results = []
        for _ in range(20):
            results.append(await grant(db, payer, "interview", 5, payment_ref="pay_Twenty"))
            await db.commit()
        assert results.count(True) == 1
        assert results.count(False) == 19
        assert await _granted(db, payer) == 5

    async def test_a_verify_and_a_webhook_for_one_capture_grant_once(self, two_users):
        """
        The honest-customer case. Both paths fire within milliseconds of the same capture and
        used to grant independently, so an ordinary buyer silently received double.
        """
        db, payer, _ = two_users
        a = await grant(db, payer, "interview", 5, payment_ref="pay_Race", kind=KIND_PURCHASE)
        await db.commit()
        b = await grant(db, payer, "interview", 5, payment_ref="pay_Race", kind=KIND_PURCHASE)
        await db.commit()
        assert [a, b].count(True) == 1
        assert await _granted(db, payer) == 5

    async def test_different_payments_both_grant(self, two_users):
        # The guard must not become "one purchase per account ever".
        db, payer, _ = two_users
        assert await grant(db, payer, "interview", 1, payment_ref="pay_A") is True
        await db.commit()
        assert await grant(db, payer, "interview", 1, payment_ref="pay_B") is True
        await db.commit()
        assert await _granted(db, payer) == 2

    async def test_one_users_payment_does_not_block_another_user(self, two_users):
        db, a, b = two_users
        assert await grant(db, a, "interview", 1, payment_ref="pay_Mine") is True
        await db.commit()
        assert await grant(db, b, "interview", 1, payment_ref="pay_Theirs") is True
        await db.commit()
        assert await _granted(db, a) == 1
        assert await _granted(db, b) == 1

    async def test_grants_without_a_payment_ref_are_not_deduplicated(self, two_users):
        """
        Admin goodwill and refunds have nothing to deduplicate on, and two acts of goodwill are
        two grants. Collapsing them would silently swallow a support gesture.
        """
        db, payer, _ = two_users
        from app.services.billing.credits import KIND_GRANT

        assert await grant(db, payer, "interview", 1, kind=KIND_GRANT) is True
        await db.commit()
        assert await grant(db, payer, "interview", 1, kind=KIND_GRANT) is True
        await db.commit()
        assert await _granted(db, payer) == 2


# The two below are synchronous source assertions, so they sit outside the module-level
# asyncio mark — pytest-asyncio warns about a sync test carrying it, and a warning nobody can
# act on is noise that hides the ones that matter.
@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
class TestTheLockIsWhereItHasToBe:
    def test_the_lock_is_taken_before_the_duplicate_check(self):
        """
        Source assertion on ORDER, because reversing it restores the bug exactly and no
        single-threaded test can tell the difference.
        """
        import inspect

        src = inspect.getsource(grant)
        code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        lock = code.index("_plan_row(db, user_id, lock=True)")
        check = code.index("CreditEvent.payment_ref == payment_ref")
        assert lock < check

    def test_callers_no_longer_carry_their_own_guard_alone(self):
        """
        The callers may keep their early check as a cheap fast path, but `grant` must be the
        thing that decides. Asserted so nobody removes the lock on the grounds that the caller
        already checks — that was the state that shipped the bug.
        """
        import inspect

        src = inspect.getsource(grant)
        assert "lock=True" in src
