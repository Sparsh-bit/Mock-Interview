"""
The answer key is not handed to the candidate being asked — tests/test_question_access.py

FOUND BY A PRE-LAUNCH SECURITY AUDIT AND REPRODUCED LIVE. `GET /api/v1/questions/{id}` returned
`expected_keywords` and `ideal_answer` for any question, to any signed-in user, with
`current_user` explicitly marked "identity unused".

THE PRACTICAL EXPLOIT IS CHEATING, WHICH IS WORSE HERE THAN A LEAK. A candidate mid-interview
reads the question id out of the JSON already sitting in their browser — `GET
/interview/{id}/next` returns it — calls this endpoint, and is handed the model answer to the
question on their screen. `/next` deliberately withholds those two fields; this endpoint gave
them away. Nobody else's data is exposed, and every score the product produces becomes
meaningless. An assessment tool that can be queried for its own answer key is not an assessment
tool.

The audit also demonstrated the second half with a real id: `questions.session_id` is documented
as a tenancy boundary because cross-questions quote the candidate's own words and planned
questions name their resume projects, and this endpoint filtered on nothing but the id.

WHAT IS DELIBERATELY STILL ALLOWED. Bank questions (session_id IS NULL) remain readable by
anyone signed in — that is what the standalone practice screen is for, and the old docstring's
premise, "retrying a coding question must not require an interview session", is still honoured.
What changed is that it is checked rather than assumed.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def two_candidates():
    """Two users, a bank question, and one session-scoped question owned by the first."""
    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import AsyncSessionFactory
    from app.models.company import Company, InterviewTrack, QuestionCategory
    from app.models.question import Question, Topic
    from app.models.session import InterviewSession, SessionStatus
    from app.models.user import User

    a, b = uuid.uuid4(), uuid.uuid4()
    ids: dict[str, uuid.UUID] = {}
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
                            email=f"acc-{uid}@example.test", is_active=True, is_admin=False))
            company = Company(id=uuid.uuid4(), name="T Co", slug=f"tco-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(id=uuid.uuid4(), company_id=company.id, name="T",
                                  slug=f"t-{uuid.uuid4().hex[:8]}")
            # topics.category_id is NOT NULL, so the category has to exist first. Building the
            # real chain rather than nulling the column: a fixture that diverges from the
            # schema tests something the app cannot produce.
            category = QuestionCategory(
                id=uuid.uuid4(), track_id=track.id, name="Core",
                slug=f"core-{uuid.uuid4().hex[:8]}",
            )
            topic = Topic(
                id=uuid.uuid4(), category_id=category.id, name="OOP",
                slug=f"oop-{uuid.uuid4().hex[:8]}",
            )
            session = InterviewSession(id=uuid.uuid4(), user_id=a, track_id=track.id,
                                       status=SessionStatus.ACTIVE, mode="text")
            bank = Question(id=uuid.uuid4(), topic_id=topic.id, session_id=None,
                            content="What is a HashMap?", difficulty="easy",
                            question_type="conceptual",
                            expected_keywords=["bucket", "hash"],
                            ideal_answer="A map backed by buckets.")
            owned = Question(id=uuid.uuid4(), topic_id=topic.id, session_id=session.id,
                             content="You said buckets — what happens on a collision?",
                             difficulty="medium", question_type="conceptual",
                             expected_keywords=["chaining"],
                             ideal_answer="Entries chain in the bucket.")
            db.add_all([company, track, category, topic, session, bank, owned])
            await db.commit()
            ids = {"bank": bank.id, "owned": owned.id, "session": session.id,
                   "topic": topic.id, "track": track.id, "company": company.id,
                   "category": category.id}
            yield db, a, b, ids

            from app.models.session import Answer

            await db.execute(delete(Answer).where(Answer.session_id == ids["session"]))
            await db.execute(delete(Question).where(Question.id.in_([ids["bank"], ids["owned"]])))
            await db.execute(delete(InterviewSession).where(InterviewSession.id == ids["session"]))
            await db.execute(delete(Topic).where(Topic.id == ids["topic"]))
            await db.execute(delete(QuestionCategory).where(QuestionCategory.id == ids["category"]))
            await db.execute(delete(InterviewTrack).where(InterviewTrack.id == ids["track"]))
            await db.execute(delete(Company).where(Company.id == ids["company"]))
            await db.execute(delete(User).where(User.id.in_([a, b])))
            await db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - environment
        pytest.skip(f"needs the dev Postgres: {exc}")


class _User:
    def __init__(self, uid: uuid.UUID) -> None:
        self.user_id = uid
        self.supabase_uid = str(uid)
        self.email = f"{uid}@example.test"


async def _get(db, uid, question_id):
    from app.api.v1.questions import get_question

    return await get_question(question_id, _User(uid), db)  # type: ignore[arg-type]


class TestTheAnswerKey:
    async def test_is_withheld_before_the_candidate_answers(self, two_candidates):
        """THE ONE THAT WOULD HAVE CAUGHT IT."""
        db, a, _b, ids = two_candidates
        out = await _get(db, a, ids["bank"])
        assert out.content  # the question itself is still served
        assert out.expected_keywords == []
        assert out.ideal_answer is None

    async def test_is_released_once_they_have_answered_it(self, two_candidates):
        """
        The practice screen is reached from a finished report, so it must keep working. Gating
        on "has this user answered it" is what lets coaching survive without letting somebody
        read ahead.
        """
        db, a, _b, ids = two_candidates
        from app.models.session import Answer

        db.add(Answer(id=uuid.uuid4(), session_id=ids["session"],
                      question_id=ids["bank"], content="buckets and hashing"))
        await db.commit()

        out = await _get(db, a, ids["bank"])
        assert out.expected_keywords == ["bucket", "hash"]
        assert out.ideal_answer == "A map backed by buckets."

    async def test_another_users_answer_does_not_unlock_it(self, two_candidates):
        # The gate is per USER, not per question. Otherwise the first candidate to answer a
        # bank question would unlock its answer key for everybody still being asked it.
        db, a, b, ids = two_candidates
        from app.models.session import Answer

        db.add(Answer(id=uuid.uuid4(), session_id=ids["session"],
                      question_id=ids["bank"], content="answered by A"))
        await db.commit()

        out = await _get(db, b, ids["bank"])
        assert out.ideal_answer is None


class TestSessionScopedQuestions:
    async def test_the_owner_can_read_their_own(self, two_candidates):
        db, a, _b, ids = two_candidates
        out = await _get(db, a, ids["owned"])
        assert "collision" in out.content

    async def test_another_candidate_gets_a_404_not_a_403(self, two_candidates):
        """
        Indistinguishable from "does not exist", or the response becomes an oracle for which
        ids are real. These quote the candidate's own words — the audit read one that said
        "time complexity of login" out of somebody else's session.
        """
        from fastapi import HTTPException

        db, _a, b, ids = two_candidates
        with pytest.raises(HTTPException) as excinfo:
            await _get(db, b, ids["owned"])
        assert excinfo.value.status_code == 404

    async def test_a_bank_question_is_still_readable_by_anyone(self, two_candidates):
        # The practice screen depends on this. The fix must not close the door it was built for.
        db, _a, b, ids = two_candidates
        out = await _get(db, b, ids["bank"])
        assert out.content == "What is a HashMap?"

    async def test_a_missing_id_is_404(self, two_candidates):
        from fastapi import HTTPException

        db, a, _b, _ids = two_candidates
        with pytest.raises(HTTPException) as excinfo:
            await _get(db, a, uuid.uuid4())
        assert excinfo.value.status_code == 404
