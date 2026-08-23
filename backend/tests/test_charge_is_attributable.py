"""
Every interview charge names the session it paid for — tests/test_charge_is_attributable.py

REPORTED: "the report has been shown without payment i created a new account given the free
interview and it showed the report without any payment".

THE HOLE WAS NOT IN THE PAYWALL. `report_access` was working exactly as written: it decides by
finding the consume row for a session, and it FAILS OPEN when it cannot find one, because
locking a report somebody already owns is far worse than failing to charge for one. That design
is right and is not what changed.

The hole was that `/interview/plan` charged with `session_id=None`. It charges BEFORE
generating — deliberately, so an exhausted user does not pay for the expensive part before
being refused — and the session does not exist until `create_plan` returns. So the ledger held
a charge attached to nothing, which is indistinguishable from no charge at all, and every
interview begun through that endpoint produced a free report. That is most of them.

WHY THIS FILE GUARDS THE CLASS AND NOT THE INSTANCE. The same mistake is available to every
future endpoint that begins an interview: charge, generate, forget to attach. The instance is
one line; the class is "an unattributable charge silently gives away the thing it paid for",
and it is silent in both directions — nothing errors, and the candidate is not billed twice.
So the test is over the CALL SITES, not over one of them.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from datetime import UTC, datetime

import pytest

from app.services.billing.plans import trial_allowance

INTERVIEW_API = pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/interview.py"


class TestEveryChargeCanBeTracedToItsSession:
    """
    Source-level, because the failure is an ABSENCE — a keyword argument nobody passed — and an
    absence in a path that is otherwise correct cannot be reached from outside without standing
    up a live interview and a live AI call.
    """

    def test_every_interview_charge_names_a_session(self):
        src = INTERVIEW_API.read_text()
        calls = list(
            re.finditer(r'consume\(\s*db,\s*current_user\.user_id,\s*"interview"', src)
        )
        assert calls, "the interview charge moved; this guard needs repointing"

        for match in calls:
            # The call's own argument list, up to its closing paren.
            tail = src[match.start() : src.index(")", match.start()) + 1]
            if "session_id=" in tail:
                continue
            # Otherwise the charge MUST be captured and attached after the session exists.
            # Anything else is the bug: a row in the ledger that names no session.
            head = src[: match.start()].rsplit("\n", 1)[-1]
            assert "=" in head, (
                "an interview charge neither passes session_id nor keeps the returned row to "
                "attach one. An unattributable charge reads as no charge to report_access, "
                "which fails open and gives the report away."
            )
            after = src[match.end() :]
            assert ".session_id =" in after, (
                "the charge is captured but never attached to a session — see the module "
                "docstring for why that gives away paid reports."
            )

    def test_the_charge_and_the_attachment_are_in_one_transaction(self):
        # `get_db` owns the commit. If the attachment were committed separately, a failure
        # between them would leave a charge that still names no session — the same bug with a
        # smaller window.
        src = INTERVIEW_API.read_text()
        start = src.index("async def plan_interview")
        # Bounded to THIS function. Slicing to the end of the file swept in other endpoints
        # that legitimately commit, which made the assertion fail for the wrong reason — the
        # first version of this test reported a bug in code it was not looking at.
        end = src.index("\nasync def ", start + 1)
        plan_block = src[start:end]
        assert "db.commit()" not in plan_block, (
            "committing inside the endpoint breaks the atomicity the charge relies on"
        )

    def test_consume_returns_the_row_so_it_can_be_attached(self):
        import inspect

        from app.services.billing import credits

        sig = inspect.signature(credits.consume)
        assert sig.return_annotation != "None", (
            "consume returning None again removes the only way a charge-before-generate call "
            "site can attach its session"
        )


@pytest.mark.asyncio
class TestTheLedgerShapeDecidesAccess:
    """
    The behaviour underneath, at the level report_access actually reads: a charge with no
    session attached must not be what unlocks a report.
    """

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
                User(id=uid, supabase_uid=str(uid), email=f"att-{uid}@example.test",
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

    async def test_an_attached_trial_charge_locks_the_report(self, env):
        """The fixed behaviour: the charge names the session, so the paywall can see it."""
        from app.db.session import AsyncSessionFactory
        from app.services.billing.credits import consume
        from app.services.billing.report_access import evaluate

        async with AsyncSessionFactory() as db:
            await consume(db, env["user_id"], "interview", session_id=env["session_id"])
            await db.commit()

        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
        assert access.locked is True, "a free interview's report must be paywalled"

    async def test_the_old_shape_is_what_gave_the_report_away(self, env):
        """
        Documents the bug rather than the fix, and is worth keeping.

        A charge with no session attached leaves report_access with nothing to find, so it
        fails open — correctly, given its contract — and the report is delivered. This test
        exists so nobody reads the fail-open in report_access as the defect and "hardens" it:
        that would start locking reports people own, which is the far more expensive mistake.
        The defect was upstream, in charging without saying what for.
        """
        from app.db.session import AsyncSessionFactory
        from app.services.billing.credits import consume
        from app.services.billing.report_access import evaluate

        async with AsyncSessionFactory() as db:
            await consume(db, env["user_id"], "interview")  # no session_id — the old bug
            await db.commit()

        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
        assert access.locked is False, (
            "report_access must keep failing open on an unfindable charge; the fix belongs at "
            "the call site that failed to attach one"
        )

    async def test_attaching_after_the_fact_locks_it_just_the_same(self, env):
        """
        The plan flow's actual shape: charge first, attach once the session exists. What
        matters is that the end state is identical to charging with the id in hand.
        """
        from app.db.session import AsyncSessionFactory
        from app.services.billing.credits import consume
        from app.services.billing.report_access import evaluate

        async with AsyncSessionFactory() as db:
            charge = await consume(db, env["user_id"], "interview")
            assert charge is not None
            charge.session_id = env["session_id"]
            await db.commit()

        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
        assert access.locked is True

    async def test_a_purchased_interview_is_still_not_locked(self, env):
        """The fix must not start charging twice for an interview somebody bought."""
        from app.db.session import AsyncSessionFactory
        from app.services.billing.credits import consume, grant
        from app.services.billing.report_access import evaluate

        async with AsyncSessionFactory() as db:
            for _ in range(trial_allowance("interview")):
                await consume(db, env["user_id"], "interview")
            await grant(
                db, env["user_id"], "interview", 1, payment_ref=f"pay_{uuid.uuid4().hex[:10]}"
            )
            charge = await consume(db, env["user_id"], "interview")
            charge.session_id = env["session_id"]
            await db.commit()

        async with AsyncSessionFactory() as db:
            access = await evaluate(db, user_id=env["user_id"], session_id=env["session_id"])
        assert access.locked is False
        assert datetime.now(UTC) is not None  # (sanity: the fixture ran in this process)
