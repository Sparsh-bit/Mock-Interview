"""
Rating the interview you just finished — tests/test_interview_feedback.py

THE CONSTRAINT THAT SHAPES ALL OF THIS: the candidate is one tap away from a report they have
paid ₹49 for. The rating is required by the UI, but it must never be able to cost them that
report — so the client fires this call WITHOUT AWAITING IT, and every property below is chosen
so that a failure here is contained to the rating.

What is pinned:

  TENANCY — a rating is a write against a session, so it needs the same ownership check every
  other write to that session has. 404 rather than 403, because whether a session exists is
  itself a fact about another account.

  THE RANGE, IN THE DATABASE AND NOT ONLY IN PYDANTIC. The request model is one refactor away
  from being bypassed by a fixture, a backfill or a background job, and a zero-star row would
  skew the only aggregate anybody looks at.

  ONE PER SESSION, BY UNIQUE INDEX. A SELECT-then-INSERT has a window between the two, and two
  taps on a slow connection land in it.

  A DUPLICATE MUST NOT POISON THE TRANSACTION. This is the exact bug that silently discarded a
  whole generated report once — a duplicate rating raised, the handler rolled back, and the
  caller's write went with it. The insert runs in a SAVEPOINT for that reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.core.config import settings
from app.main import app


def _token(user_id: uuid.UUID) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": f"f-{user_id}@example.test",
            "aud": settings.SUPABASE_JWT_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


@pytest.mark.asyncio
class TestRatingAnInterview:
    @pytest.fixture
    async def world(self):
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.company import Company, InterviewTrack
        from app.models.session import InterviewSession, SessionStatus
        from app.models.user import User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        owner, stranger = uuid.uuid4(), uuid.uuid4()
        session_id = uuid.uuid4()
        async with AsyncSessionFactory() as db:
            company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(
                id=uuid.uuid4(), company_id=company.id, name="T", slug=f"t-{uuid.uuid4().hex[:8]}"
            )
            db.add_all([
                company,
                track,
                User(id=owner, supabase_uid=str(owner), email=f"o-{owner}@example.test",
                     is_active=True, is_admin=False),
                User(id=stranger, supabase_uid=str(stranger),
                     email=f"s-{stranger}@example.test", is_active=True, is_admin=False),
            ])
            await db.flush()
            db.add(
                InterviewSession(
                    id=session_id, user_id=owner, track_id=track.id,
                    status=SessionStatus.COMPLETED,
                )
            )
            await db.commit()
        return {"owner": owner, "stranger": stranger, "session_id": session_id}

    async def _rate(self, user_id: uuid.UUID, session_id: uuid.UUID, body: dict):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            return await ac.post(
                f"/api/v1/interview/{session_id}/feedback",
                headers={"Authorization": f"Bearer {_token(user_id)}"},
                json=body,
            )

    async def test_the_owner_can_rate_their_own_interview(self, world):
        r = await self._rate(world["owner"], world["session_id"], {"stars": 4})
        assert r.status_code == 204, r.text
        assert not r.content, "204 must carry no body — the client does not await this call"

    async def test_a_stranger_cannot_rate_someone_elses_interview(self, world):
        # 404, not 403: whether a session exists is a fact about another account.
        r = await self._rate(world["stranger"], world["session_id"], {"stars": 5})
        assert r.status_code == 404

    async def test_rating_requires_authentication(self, world):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            r = await ac.post(
                f"/api/v1/interview/{world['session_id']}/feedback", json={"stars": 5}
            )
        assert r.status_code == 401

    @pytest.mark.parametrize("bad", [0, 6, -1, 100, 2.5, "five", None])
    async def test_a_rating_outside_one_to_five_is_refused(self, world, bad):
        r = await self._rate(world["owner"], world["session_id"], {"stars": bad})
        assert r.status_code == 422, f"stars={bad!r} was accepted"

    async def test_an_overlong_comment_is_refused_rather_than_truncated(self, world):
        # Truncating would store something the candidate did not write and show it to an admin
        # as though they had.
        r = await self._rate(
            world["owner"], world["session_id"], {"stars": 5, "comment": "x" * 1001}
        )
        assert r.status_code == 422

    async def test_rating_twice_does_not_error_and_does_not_double_count(self, world):
        from sqlalchemy import func, select

        from app.db.session import AsyncSessionFactory
        from app.models.session import InterviewFeedback

        first = await self._rate(world["owner"], world["session_id"], {"stars": 5})
        second = await self._rate(world["owner"], world["session_id"], {"stars": 1})
        assert first.status_code == 204
        # The candidate's intent is already satisfied. A 409 on a call nobody awaits would be
        # logged as a failure by a client that is not listening.
        assert second.status_code == 204

        async with AsyncSessionFactory() as db:
            n = await db.scalar(
                select(func.count())
                .select_from(InterviewFeedback)
                .where(InterviewFeedback.session_id == world["session_id"])
            )
            stars = await db.scalar(
                select(InterviewFeedback.stars).where(
                    InterviewFeedback.session_id == world["session_id"]
                )
            )
        assert n == 1, "the unique index did not hold — one interview has two ratings"
        assert stars == 5, "the second rating overwrote the first"

    async def test_a_duplicate_does_not_poison_the_transaction(self, world):
        """
        THE BUG THIS IS REALLY GUARDING. A duplicate insert raises IntegrityError, and an
        unhandled one poisons the whole request transaction — which is how a duplicate RATING
        once silently discarded a fully generated REPORT that shared it. The insert runs in a
        SAVEPOINT so the failure costs exactly itself.
        """
        from app.db.session import AsyncSessionFactory
        from app.models.session import InterviewFeedback
        from app.models.user import Profile

        await self._rate(world["owner"], world["session_id"], {"stars": 3})

        async with AsyncSessionFactory() as db:
            # A write BEFORE the duplicate, standing in for anything else the request does.
            db.add(Profile(user_id=world["owner"], full_name="Survives", timezone="UTC"))
            await db.flush()
            from sqlalchemy.exc import IntegrityError

            # ADDED INSIDE THE SAVEPOINT, mirroring the endpoint. Outside it, the failed
            # object survives the rollback in `session.new` and the commit below flushes it
            # again — which is a 500 at the end of the request rather than a handled duplicate.
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    db.add(
                        InterviewFeedback(
                            session_id=world["session_id"], user_id=world["owner"], stars=1
                        )
                    )
                    await db.flush()
            await db.commit()

        async with AsyncSessionFactory() as db:
            from sqlalchemy import select

            survived = await db.scalar(
                select(Profile.full_name).where(Profile.user_id == world["owner"])
            )
        assert survived == "Survives", (
            "a write made before the duplicate was discarded — the savepoint is not containing "
            "the IntegrityError, which is the bug that lost a whole report once"
        )

    async def test_the_comment_is_optional(self, world):
        r = await self._rate(world["owner"], world["session_id"], {"stars": 2})
        assert r.status_code == 204

    async def test_rating_a_session_that_does_not_exist_is_a_404(self, world):
        r = await self._rate(world["owner"], uuid.uuid4(), {"stars": 5})
        assert r.status_code == 404


class TestTheStarRangeIsEnforcedByTheDatabaseToo:
    """
    Pydantic guards the HTTP path. The column constraint guards every other path — a fixture,
    a backfill, a shell. Belt and braces on the one number the whole aggregate is built from.
    """

    def test_the_column_carries_a_check_constraint(self):
        from app.models.session import InterviewFeedback

        checks = [
            str(c.sqltext)
            for c in InterviewFeedback.__table__.constraints
            if hasattr(c, "sqltext")
        ]
        assert any("stars" in c and "1" in c and "5" in c for c in checks), (
            f"no 1-5 CHECK on stars; found {checks}"
        )

    def test_one_rating_per_session_is_a_unique_column(self):
        from app.models.session import InterviewFeedback

        col = InterviewFeedback.__table__.columns["session_id"]
        assert col.unique, (
            "session_id is not unique, so the one-rating-per-interview rule is only whatever "
            "the endpoint remembers to check"
        )

    def test_it_is_not_called_a_rating(self):
        # `rating_events` is the ELO ledger of how the CANDIDATE performed. This is how the
        # PRODUCT performed. Two tables both called some form of "rating" is how a query ends
        # up joining the wrong one.
        from app.models.session import InterviewFeedback

        assert InterviewFeedback.__tablename__ == "interview_feedback"


@pytest.mark.asyncio
class TestTheHandlerLeavesTheSessionUsable:
    """
    WHY THIS CALLS THE HANDLER DIRECTLY INSTEAD OF THE ENDPOINT.

    `get_db` commits AFTER the handler returns, in dependency teardown. So a session poisoned
    by a duplicate raises there — after the 204 has already been formed — and an HTTP-level
    test sees a perfectly good 204 either way. Verified by mutation: removing the savepoint
    entirely leaves all eighteen endpoint tests green.

    That is the failure this file exists to prevent, and it is invisible from outside. So the
    property is pinned where it lives: after a duplicate, the session must still commit.

    It matters beyond this handler. Today the endpoint does nothing but the rating, so a
    poisoned transaction loses only the rating. The moment somebody adds a second write here —
    an activity row, an event — the duplicate would silently discard it, which is exactly how a
    duplicate rating once discarded a fully generated report.
    """

    async def test_a_duplicate_rating_leaves_the_session_committable(self):
        from app.api.v1.interview import FeedbackRequest, submit_feedback
        from app.core.security import AuthenticatedUser
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.company import Company, InterviewTrack
        from app.models.session import InterviewSession, SessionStatus
        from app.models.user import Profile, User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        uid, sid = uuid.uuid4(), uuid.uuid4()
        async with AsyncSessionFactory() as db:
            company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(
                id=uuid.uuid4(), company_id=company.id, name="T",
                slug=f"t-{uuid.uuid4().hex[:8]}",
            )
            db.add_all([
                company, track,
                User(id=uid, supabase_uid=str(uid), email=f"h-{uid}@example.test",
                     is_active=True, is_admin=False),
            ])
            await db.flush()
            db.add(
                InterviewSession(
                    id=sid, user_id=uid, track_id=track.id, status=SessionStatus.COMPLETED
                )
            )
            await db.commit()

        user = AuthenticatedUser(
            user_id=uid, supabase_uid=str(uid), email=f"h-{uid}@example.test"
        )

        async with AsyncSessionFactory() as db:
            await submit_feedback(sid, FeedbackRequest(stars=5), user, db)
            await db.commit()

        async with AsyncSessionFactory() as db:
            # The duplicate, then a SECOND WRITE in the same session. If the duplicate poisoned
            # the transaction, this write is discarded and the commit raises.
            await submit_feedback(sid, FeedbackRequest(stars=1), user, db)
            db.add(Profile(user_id=uid, full_name="Written after the duplicate", timezone="UTC"))
            await db.commit()

        async with AsyncSessionFactory() as db:
            from sqlalchemy import select

            survived = await db.scalar(select(Profile.full_name).where(Profile.user_id == uid))

        assert survived == "Written after the duplicate", (
            "a write made after the duplicate rating was lost. The IntegrityError poisoned the "
            "request's transaction — the savepoint around the insert is missing or the object "
            "is being added outside it."
        )
