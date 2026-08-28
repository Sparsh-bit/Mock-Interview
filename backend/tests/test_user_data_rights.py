"""
What a person can do with their own data — tests/test_user_data_rights.py

Both of these existed only as admin actions, so the honest answer to "can I leave?" and "what
do you hold on me?" was "email somebody and hope". DPDP §11 and §12 make them rights; they are
also the plainest kind of user experience, because an account nobody can leave is one they were
never fully in control of.

THE EXPORT IS THE MOST VALUABLE IDOR TARGET IN THE PRODUCT. One request returns a resume, a
transcript and an assessment. There is deliberately no `user_id` parameter anywhere in it — the
account is the one the token names — and that absence is asserted rather than assumed, because
adding one "for admin convenience" is the single change that would turn this endpoint into a
data breach.

DELETION IS IRREVERSIBLE AND REMOVES THINGS THE PERSON PAID FOR, so the tests care as much
about it refusing as about it working.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.core.config import settings
from app.main import app


def _token(user_id: uuid.UUID, email: str) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "aud": settings.SUPABASE_JWT_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


@pytest.mark.asyncio
class TestExportingYourOwnData:
    @pytest.fixture
    async def world(self):
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.company import Company, InterviewTrack, QuestionCategory
        from app.models.question import Question, Topic
        from app.models.report import Report
        from app.models.session import Answer, InterviewSession, SessionStatus
        from app.models.user import Profile, User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        owner, stranger = uuid.uuid4(), uuid.uuid4()
        session_id, question_id = uuid.uuid4(), uuid.uuid4()

        async with AsyncSessionFactory() as db:
            company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(
                id=uuid.uuid4(), company_id=company.id, name="T", slug=f"t-{uuid.uuid4().hex[:8]}"
            )
            db.add_all([
                company, track,
                User(id=owner, supabase_uid=str(owner), email=f"own-{owner}@example.test",
                     is_active=True, is_admin=False),
                User(id=stranger, supabase_uid=str(stranger),
                     email=f"str-{stranger}@example.test", is_active=True, is_admin=False),
            ])
            await db.flush()
            cat = QuestionCategory(id=uuid.uuid4(), track_id=track.id, name="Core",
                                   slug=f"cat-{uuid.uuid4().hex[:6]}")
            db.add(cat)
            await db.flush()
            topic = Topic(id=uuid.uuid4(), category_id=cat.id, name="Java",
                          slug=f"tp-{uuid.uuid4().hex[:6]}")
            db.add(topic)
            await db.flush()
            db.add_all([
                Profile(user_id=owner, full_name="Owner O", timezone="UTC"),
                InterviewSession(id=session_id, user_id=owner, track_id=track.id,
                                 status=SessionStatus.COMPLETED),
            ])
            await db.flush()
            db.add(
                Question(
                    id=question_id, topic_id=topic.id, session_id=session_id,
                    content="What is a HashMap?", difficulty="medium",
                    question_type="conceptual",
                    ideal_answer="THE ANSWER KEY — belongs to the bank, not the candidate.",
                )
            )
            await db.flush()
            db.add(
                Answer(session_id=session_id, question_id=question_id,
                       content="MY OWN WORDS about hashing.")
            )
            db.add(
                Report(
                    session_id=session_id, user_id=owner, overall_score=77.0,
                    overall_score_label="Good", executive_summary="MY ASSESSMENT.",
                    readiness_level="close_to_ready", strengths=["a"], weaknesses=["b"],
                    topic_scores={}, improvement_roadmap=[], raw_report={"generated_by": "ai"},
                )
            )
            await db.commit()
        return {"owner": owner, "stranger": stranger, "session_id": session_id}

    async def _export(self, user_id: uuid.UUID, email: str, query: str = ""):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            return await ac.get(
                f"/api/v1/users/me/export{query}",
                headers={"Authorization": f"Bearer {_token(user_id, email)}"},
            )

    async def test_it_returns_your_own_data(self, world):
        r = await self._export(world["owner"], "own@example.test")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["profile"]["full_name"] == "Owner O"
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["your_answers"][0]["answer"] == "MY OWN WORDS about hashing."
        assert body["reports"][0]["summary"] == "MY ASSESSMENT."

    async def test_it_returns_nothing_belonging_to_anybody_else(self, world):
        # The stranger has an account and no data. Their export must be empty rather than
        # everybody's.
        r = await self._export(world["stranger"], "str@example.test")
        assert r.status_code == 200
        body = r.json()
        assert body["sessions"] == []
        assert body["reports"] == []
        assert "MY OWN WORDS" not in r.text
        assert "MY ASSESSMENT" not in r.text

    async def test_a_user_id_parameter_is_ignored_rather_than_honoured(self, world):
        """
        THE ONE THAT MATTERS MOST. If this endpoint ever grew a `user_id` argument it would be
        the highest-value IDOR in the product — one request for somebody else's resume,
        transcript and assessment. Passing one today must change nothing.
        """
        r = await self._export(
            world["stranger"], "str@example.test", f"?user_id={world['owner']}"
        )
        assert r.status_code == 200
        assert r.json()["sessions"] == [], "a user_id query parameter was honoured"
        assert "MY OWN WORDS" not in r.text


    async def test_the_answer_key_is_not_included(self, world):
        # `ideal_answer` belongs to the question bank, not to the candidate. An export that
        # carried it would be a supported way to read every answer in the product.
        r = await self._export(world["owner"], "own@example.test")
        assert "belongs to the bank" not in r.text

    async def test_it_names_who_the_data_is_shared_with(self, world):
        # DPDP §5 requires telling people who their data goes to. A list they have to infer is
        # not a disclosure.
        r = await self._export(world["owner"], "own@example.test")
        shared = " ".join(r.json()["shared_with"]).lower()
        for processor in ("razorpay", "anthropic", "supabase"):
            assert processor in shared, f"{processor} is not disclosed in the export"

    async def test_export_requires_authentication(self):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            r = await ac.get("/api/v1/users/me/export")
        assert r.status_code == 401


@pytest.mark.asyncio
class TestDeletingYourOwnAccount:
    @pytest.fixture
    async def user(self):
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.user import User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        uid = uuid.uuid4()
        email = f"del-{uid}@example.test"
        async with AsyncSessionFactory() as db:
            db.add(
                User(id=uid, supabase_uid=str(uid), email=email, is_active=True, is_admin=False)
            )
            await db.commit()
        return uid, email

    async def _delete(self, user_id: uuid.UUID, email: str, confirm: str):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            return await ac.post(
                "/api/v1/users/me/delete",
                headers={"Authorization": f"Bearer {_token(user_id, email)}"},
                json={"confirm_email": confirm},
            )

    async def test_a_wrong_confirmation_deletes_nothing(self, user):
        from sqlalchemy import select

        from app.db.session import AsyncSessionFactory
        from app.models.user import User

        uid, email = user
        r = await self._delete(uid, email, "not-my-email@example.test")
        assert r.status_code == 400

        async with AsyncSessionFactory() as db:
            assert await db.scalar(select(User.id).where(User.id == uid)) is not None, (
                "the account was deleted despite a failed confirmation"
            )

    async def test_an_empty_confirmation_deletes_nothing(self, user):
        uid, email = user
        assert (await self._delete(uid, email, "")).status_code == 400
        assert (await self._delete(uid, email, "   ")).status_code == 400

    async def test_deletion_requires_authentication(self, user):
        _, email = user
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            r = await ac.post("/api/v1/users/me/delete", json={"confirm_email": email})
        assert r.status_code == 401


class TestTheShapeOfTheseEndpoints:
    """
    Signature-level guards, in a plain class.

    THEY WERE UNDER `@pytest.mark.asyncio` AND WARNED ON EVERY RUN — a sync test under an
    asyncio mark emits a PytestWarning, and four of them made the suite's warning count jump
    from six to ten. Warnings that are normal are warnings nobody reads, which is how a real
    one goes unnoticed.
    """

    def test_the_endpoint_takes_no_user_id_at_all(self):
        # Asserted on the signature, not just the behaviour: the absence IS the control, and
        # an absence has to be pinned deliberately or it erodes.
        import inspect

        from app.api.v1.users import export_my_data

        params = set(inspect.signature(export_my_data).parameters)
        for forbidden in ("user_id", "account_id", "email", "supabase_uid"):
            assert forbidden not in params, (
                f"the export accepts {forbidden!r}. This endpoint returns a resume, a "
                "transcript and an assessment — any parameter naming an account is a breach."
            )

    def test_the_endpoint_deletes_the_caller_and_nobody_else(self):
        # No id parameter, so there is no account to name but your own.
        import inspect

        from app.api.v1.users import delete_my_account

        params = set(inspect.signature(delete_my_account).parameters)
        assert "user_id" not in params and "email" not in params

    def test_it_reuses_the_tested_admin_deletion_helpers(self):
        # A second implementation would not carry the two details that took an incident each:
        # a Core DELETE so the database cascade runs, and Supabase auth removed BEFORE our
        # rows so a working login is never left attached to nothing.
        import inspect

        from app.api.v1.users import delete_my_account

        src = inspect.getsource(delete_my_account)
        assert "_delete_stored_files" in src
        assert "_delete_supabase_user" in src
        assert "sa_delete(User)" in src, "not a Core delete — the ORM path NULLs children"

    def test_the_login_is_removed_before_our_rows(self):
        # Order is the whole correctness of this: rows first would leave a working login with
        # no data, and the next sign-in silently recreates the account.
        import inspect

        from app.api.v1.users import delete_my_account

        src = inspect.getsource(delete_my_account)
        assert src.index("_delete_supabase_user") < src.index("sa_delete(User)")
