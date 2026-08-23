"""
Paying for a report unlock actually unlocks it — test_paid_unlock_actually_unlocks.py

THE WORST BUG SHAPE THIS PRODUCT CAN HAVE: money taken, nothing delivered, permanently, and
nothing anywhere that looks like a failure.

`report_access.evaluate` decides a report is unlocked by finding a credit event whose
`session_id` matches the report being opened. Every grant path — the browser calling /verify,
Razorpay calling the webhook, and a 100%-off code granting directly — called `grant()` with no
`session_id` at all. So the sequence was:

  1. The candidate pays ₹49.
  2. The grant is written, correctly, against their account.
  3. report_access looks for an unlock FOR THAT SESSION, finds none.
  4. The report stays locked. Forever.

Nothing retried, because nothing had failed: the payment succeeded and the grant was written.
The two simply could not be connected, and the only fix was an admin inserting a row by hand.

WHY IT IS TESTED AT THE LEDGER RATHER THAN THROUGH RAZORPAY. The bug is a missing argument, and
what makes it invisible is that every individual piece works. So these tests assert the SHAPE
the ledger ends up in — because that shape is the entire contract between paying and reading —
plus source assertions that every path which can grant an unlock passes the session through.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest

from app.services.billing.plans import REPORT_UNLOCK_FEATURE

BILLING = pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/billing.py"
RAZORPAY = pathlib.Path(__file__).resolve().parents[1] / "app/services/billing/razorpay.py"


class TestEveryGrantPathCarriesTheSession:
    """
    Three ways an unlock can be granted, and all three had the same hole. A future fourth is
    the risk this guards.
    """

    def test_every_grant_call_passes_a_session(self):
        """
        CHECKED PER CALL SITE, not by counting.

        The first version of this asserted `src.count("session_id=") >= 3`, which passed even
        with one of the three grants stripped — the other occurrences (create_order, the
        remaining grants) kept the total above the threshold. Mutation-testing caught it: a
        count is a proxy for the property, and this one had enough slack to hide exactly the
        regression it was written for.
        """
        src = BILLING.read_text()
        sites = []
        at = 0
        while (at := src.find("await grant(", at)) != -1:
            # The call's own argument list, to its closing paren at the same indent.
            end = src.index("\n    )", at)
            sites.append((at, src[at:end]))
            at = end
        assert len(sites) >= 3, f"expected three grant paths, found {len(sites)}"
        for offset, block in sites:
            line = src[:offset].count("\n") + 1
            assert "session_id=" in block, (
                f"the grant at billing.py:{line} does not pass session_id — an unlock granted "
                "without it cannot be found by report_access, so the report stays locked after "
                "the payment succeeds"
            )

    def test_the_session_rides_through_the_gateway(self):
        # `notes` is the only channel that survives BOTH completion paths. Anything held in our
        # own request state is missing from the webhook, which is the path that runs when the
        # candidate closes the tab after paying — exactly when nobody is around to retry.
        rz = RAZORPAY.read_text()
        assert "_NOTES_SESSION_KEY" in rz
        assert 'session_id: str = ""' in rz, "PaymentOutcome must carry it back"
        at = rz.index("def create_order")
        assert "session_id" in rz[at : at + 1200], "create_order cannot forward it"

    def test_checkout_verifies_the_session_belongs_to_the_buyer(self):
        # The id comes from the browser. Naming somebody else's session could never unlock
        # their report — the grant is written for the authenticated buyer and report_access
        # matches on user_id too — but it would sell an unlock that does nothing.
        src = BILLING.read_text()
        at = src.index("async def checkout(")
        block = src[at : src.index("async def ", at + 10)]
        assert "InterviewSession.user_id == current_user.user_id" in block
        assert "Interview session" in block, "an unowned session must be refused by name"

    def test_a_gateway_supplied_session_id_is_never_trusted_as_a_uuid(self):
        # notes is attacker-influenced. A ValueError here would 500 the verify endpoint, which
        # runs immediately after a successful payment.
        from app.api.v1.billing import _session_uuid

        assert _session_uuid("") is None
        assert _session_uuid("   ") is None
        assert _session_uuid("not-a-uuid") is None
        assert _session_uuid("../../etc/passwd") is None
        real = uuid.uuid4()
        assert _session_uuid(str(real)) == real


@pytest.mark.asyncio
class TestTheLedgerShapeThatDecidesAccess:
    @pytest.fixture
    async def env(self):
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.company import Company, InterviewTrack
        from app.models.session import InterviewSession, SessionStatus
        from app.models.user import User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        uid, sid = uuid.uuid4(), uuid.uuid4()
        async with AsyncSessionFactory() as db:
            company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(
                id=uuid.uuid4(), company_id=company.id, name="T", slug=f"t-{uuid.uuid4().hex[:8]}"
            )
            db.add_all([
                User(id=uid, supabase_uid=str(uid), email=f"pu-{uid}@example.test",
                     is_active=True, is_admin=False),
                company,
                track,
            ])
            await db.flush()
            db.add(
                InterviewSession(
                    id=sid, user_id=uid, track_id=track.id, status=SessionStatus.COMPLETED
                )
            )
            await db.commit()
        return {"user_id": uid, "session_id": sid}

    async def _spend_the_free_interview(self, env):
        from app.db.session import AsyncSessionFactory
        from app.services.billing.credits import consume

        async with AsyncSessionFactory() as db:
            await consume(db, env["user_id"], "interview", session_id=env["session_id"])
            await db.commit()

    async def test_an_unlock_granted_with_the_session_unlocks_the_report(self, env):
        from app.db.session import AsyncSessionFactory
        from app.services.billing.credits import grant
        from app.services.billing.report_access import evaluate

        await self._spend_the_free_interview(env)
        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
            assert access.locked is True, "a free interview's report should start locked"

        async with AsyncSessionFactory() as db:
            await grant(
                db,
                env["user_id"],
                REPORT_UNLOCK_FEATURE,
                1,
                payment_ref=f"pay_{uuid.uuid4().hex[:12]}",
                session_id=env["session_id"],
            )
            await db.commit()

        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
        assert access.locked is False, "a paid unlock did not unlock the report"

    async def test_an_unlock_granted_without_a_session_leaves_it_locked(self, env):
        """
        THE BUG, PINNED AS A FACT RATHER THAN AS A WISH.

        This is what every payment used to produce, and the assertion documents why the fix had
        to be at the grant site: report_access is behaving correctly here, and "fixing" it to
        accept a session-less unlock would let one payment unlock every report the account
        ever generates.
        """
        from app.db.session import AsyncSessionFactory
        from app.services.billing.credits import grant
        from app.services.billing.report_access import evaluate

        await self._spend_the_free_interview(env)
        async with AsyncSessionFactory() as db:
            await grant(
                db,
                env["user_id"],
                REPORT_UNLOCK_FEATURE,
                1,
                payment_ref=f"pay_{uuid.uuid4().hex[:12]}",
            )
            await db.commit()

        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
        assert access.locked is True, (
            "a session-less unlock must NOT unlock a report — otherwise one ₹49 payment "
            "unlocks every report this account ever generates"
        )

    async def test_an_unlock_bought_for_another_session_does_not_apply(self, env):
        """
        One purchase, one report — the other direction of the same rule.

        Written against a DIFFERENT session id rather than a second free interview, because the
        trial allowance is one: a candidate can only ever have one free interview, so "two
        lockable reports" is not a reachable state. What is reachable, and what this asserts, is
        an unlock whose session does not match the report being opened — which is exactly the
        shape a session-less or mis-attributed grant produces.
        """
        from sqlalchemy import select

        from app.db.session import AsyncSessionFactory
        from app.models.session import InterviewSession, SessionStatus
        from app.services.billing.credits import grant
        from app.services.billing.report_access import evaluate

        await self._spend_the_free_interview(env)

        # A REAL second session row. `credit_events.session_id` is a foreign key, so the ledger
        # cannot even reference a session that does not exist — a guarantee worth noting, and
        # the reason this test cannot just invent a UUID.
        other = uuid.uuid4()
        async with AsyncSessionFactory() as db:
            first = await db.scalar(
                select(InterviewSession).where(InterviewSession.id == env["session_id"])
            )
            db.add(
                InterviewSession(
                    id=other,
                    user_id=env["user_id"],
                    track_id=first.track_id,
                    status=SessionStatus.COMPLETED,
                )
            )
            await db.flush()
            await grant(
                db,
                env["user_id"],
                REPORT_UNLOCK_FEATURE,
                1,
                payment_ref=f"pay_{uuid.uuid4().hex[:12]}",
                # A real unlock, correctly attached — to the other session.
                session_id=other,
            )
            await db.commit()

        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
        assert access.locked is True, (
            "an unlock bought for a different session unlocked this report — one ₹49 payment "
            "must not unlock everything the account generates"
        )
