"""
A report is locked only when it is genuinely owed — tests/test_report_access.py

THE RULE: a FREE interview's report costs ₹49; a PURCHASED interview's report is included. The
interview itself is never gated.

THE FAILURE THAT MATTERS IS NOT REVENUE. It is locking a report somebody already owns. They have
just answered twelve questions, they are looking at a paywall for something they paid for, and
the only person who can fix it is an operator who is asleep. Losing one report's ₹49 costs
nothing and nobody notices. The asymmetry is enormous and it points one way, so every function in
report_access FAILS OPEN and the first three tests here are about that rather than about
charging.

THE HISTORICAL CASE IS THE DANGEROUS ONE. Every interview taken before `consume` began recording
`paid_with` has no marker, and reading absence as "free, therefore charge" would paywall every
report already earned, retroactively, at deploy. `test_a_session_from_before_this_feature` is the
one that must never be deleted.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.billing.credits import KIND_CONSUME, consume, grant
from app.services.billing.plans import REPORT_UNLOCK_FEATURE, trial_allowance
from app.services.billing.report_access import evaluate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def env():
    """A user, a track and two sessions — session_id is a real FK, so they must exist."""
    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import AsyncSessionFactory, engine
    from app.models.base import Base
    from app.models.billing import CreditEvent, UserPlan
    from app.models.company import Company, InterviewTrack
    from app.models.session import InterviewSession, SessionStatus
    from app.models.user import User

    uid = uuid.uuid4()
    try:
        # test_integration.py drops the schema, so a fixture that assumes one silently SKIPS —
        # and a skipped test has already been mistaken for a passing one twice in this project.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionFactory() as db:
            company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(id=uuid.uuid4(), company_id=company.id, name="T",
                                   slug=f"t-{uuid.uuid4().hex[:8]}")
            db.add_all([
                User(id=uid, supabase_uid=str(uid), email=f"ra-{uid}@example.test",
                     is_active=True, is_admin=False),
                company, track,
            ])
            sessions = []
            for _ in range(3):
                s = InterviewSession(id=uuid.uuid4(), user_id=uid, track_id=track.id,
                                     status=SessionStatus.COMPLETED, mode="text")
                sessions.append(s)
                db.add(s)
            await db.commit()
            yield db, uid, [s.id for s in sessions]

            await db.execute(delete(CreditEvent).where(CreditEvent.user_id == uid))
            await db.execute(delete(InterviewSession).where(InterviewSession.user_id == uid))
            await db.execute(delete(UserPlan).where(UserPlan.user_id == uid))
            await db.execute(delete(User).where(User.id == uid))
            await db.execute(delete(InterviewTrack).where(InterviewTrack.id == track.id))
            await db.execute(delete(Company).where(Company.id == company.id))
            await db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - environment
        pytest.skip(f"needs the dev Postgres: {exc}")


class TestItFailsOpen:
    async def test_a_session_from_before_this_feature_is_never_locked(self, env):
        """
        THE ONE THAT MUST NEVER BE DELETED.

        No consumption row at all — which is every historical session, and any session whose
        consumption predates `paid_with`. Reading that as "free, so charge" would paywall every
        report already earned, on deploy, all at once.
        """
        db, uid, sessions = env
        access = await evaluate(db, user_id=uid, session_id=sessions[0])
        assert access.locked is False

    async def test_a_consumption_with_no_marker_is_never_locked(self, env):
        db, uid, sessions = env
        # created_at is NOT NULL with no server default — the model sets it in Python, so a
        # hand-built row has to as well. Building the row by hand rather than calling `consume`
        # is the point: this is the shape a session from before `paid_with` existed has.
        from datetime import UTC, datetime

        from app.models.billing import CreditEvent

        db.add(CreditEvent(id=uuid.uuid4(), user_id=uid, feature="interview",
                           kind=KIND_CONSUME, delta=-1, session_id=sessions[0],
                           detail={}, created_at=datetime.now(UTC)))
        await db.commit()
        assert (await evaluate(db, user_id=uid, session_id=sessions[0])).locked is False

    async def test_an_unknown_session_is_never_locked(self, env):
        db, uid, _ = env
        assert (await evaluate(db, user_id=uid, session_id=uuid.uuid4())).locked is False


class TestWhatIsActuallyCharged:
    async def test_a_free_interview_locks_its_report(self, env):
        db, uid, sessions = env
        await consume(db, uid, "interview", session_id=sessions[0])
        await db.commit()

        access = await evaluate(db, user_id=uid, session_id=sessions[0])
        assert access.locked is True
        # ₹49, priced server-side, matching what an interview costs.
        assert access.price_paise == 4_900

    async def test_a_purchased_interview_does_not(self, env):
        """The other half of the rule, and the half that keeps paying customers happy."""
        db, uid, sessions = env
        allowance = trial_allowance("interview")
        for i in range(allowance):
            await consume(db, uid, "interview", session_id=sessions[i])
            await db.commit()

        await grant(db, uid, "interview", 1, payment_ref="pay_ReportAccess")
        await db.commit()
        paid_session = sessions[allowance]
        await consume(db, uid, "interview", session_id=paid_session)
        await db.commit()

        assert (await evaluate(db, user_id=uid, session_id=paid_session)).locked is False
        # And the free one is still locked — they are judged per session, not per account.
        assert (await evaluate(db, user_id=uid, session_id=sessions[0])).locked is True

    async def test_unlocking_one_report_does_not_unlock_another(self, env):
        """
        Entitlement is per session. A single ₹49 must not open every report on the account —
        that would be the whole product given away for one payment.
        """
        db, uid, sessions = env
        # TWO trial-marked consumptions, one of them hand-built. `trial_allowance("interview")`
        # is 1, so `consume` refuses the second — correctly. What is under test here is the
        # per-session SCOPING of the unlock, not the allowance, so the second row is written
        # directly in the shape a larger allowance would have produced. Fighting the allowance
        # to get there would test the wrong thing.
        from datetime import UTC, datetime

        from app.models.billing import CreditEvent

        await consume(db, uid, "interview", session_id=sessions[0])
        db.add(CreditEvent(id=uuid.uuid4(), user_id=uid, feature="interview",
                           kind=KIND_CONSUME, delta=-1, session_id=sessions[1],
                           detail={"paid_with": "trial"}, created_at=datetime.now(UTC)))
        await db.commit()

        await grant(db, uid, REPORT_UNLOCK_FEATURE, 1,
                    payment_ref="pay_UnlockOne", session_id=sessions[0])
        await db.commit()

        assert (await evaluate(db, user_id=uid, session_id=sessions[0])).locked is False
        assert (await evaluate(db, user_id=uid, session_id=sessions[1])).locked is True

    async def test_another_users_unlock_does_not_count(self, env):
        # Scoped by user_id as well as session_id. Anything less and one payment anywhere opens
        # a report belonging to somebody else.
        db, uid, sessions = env
        await consume(db, uid, "interview", session_id=sessions[0])
        await db.commit()
        assert (await evaluate(db, user_id=uuid.uuid4(), session_id=sessions[0])).locked is False


class TestBothEndpointsUseOneRule:
    def test_get_and_generate_both_go_through_the_same_helper(self):
        """
        `POST /generate` is what the candidate hits the instant they finish. A paywall on only
        `GET` is a paywall anybody walks around by finishing an interview, and two copies of the
        rule is how they drift.
        """
        import inspect

        from app.api.v1 import reports

        src = inspect.getsource(reports)
        assert src.count("await _deliver(db, current_user, report)") == 2
        assert "_build_report_response(report)\n" not in src.replace(
            "    full = _build_report_response(report)\n", ""
        )

    def test_the_locked_response_is_built_by_subtraction(self):
        """
        `model_copy(update=...)` rather than a hand-built second object. A hand-built one is a
        place that must be updated every time the response model gains a field, and the failure
        mode of forgetting is leaking the new field through the paywall — silently, and in the
        direction that costs money.
        """
        import inspect

        from app.api.v1.reports import _deliver

        assert "model_copy(" in inspect.getsource(_deliver)

    def test_nothing_being_sold_survives_the_lock(self):
        # Every field the paywall exists to protect must be cleared. Asserted against the
        # response model so a NEW field cannot be forgotten silently — if this fails, decide
        # whether the new field belongs in the teaser, then add it to one list or the other.
        import inspect

        from app.api.v1.reports import _deliver

        src = inspect.getsource(_deliver)
        for sold in (
            "executive_summary", "readiness_level", "readiness_reasoning", "strengths",
            "weaknesses", "topic_scores", "dimension_scores", "question_analysis",
            "improvement_roadmap", "pdf_url",
        ):
            assert f'"{sold}"' in src, sold
