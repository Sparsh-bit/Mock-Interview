"""
Integration tests for InterviewOS backend.
Run with: pytest tests/test_integration.py -v --tb=short
"""
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models as _register_models  # noqa: E402, F401 -- see note below
from app.core.config import settings  # noqa: E402
from app.db.session import AsyncSessionFactory, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.company import Company, InterviewTrack  # noqa: E402
from app.models.user import Profile, User  # noqa: E402

# `_register_models` above is deliberate and must not be pruned as unused: it
# registers every mapper on Base.metadata, which _setup_schema's create_all needs
# in order to create the full schema. Importing app.main happens to pull them in
# transitively today, but the routers import models lazily inside handlers, so
# relying on that chain would make table creation depend on an import order
# nothing states. Naming the dependency here keeps it true if that changes.


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture(scope="session", autouse=True)
async def _app_lifespan():
    """
    Run the app's real startup/shutdown hooks for the test session (EventBus,
    AI provider singleton, prompt cache warm-up). ASGITransport does not run
    lifespan on its own, so without this, anything relying on
    initialize_event_bus()/initialize_ai_provider() having run would only be
    caught in production, not in tests.
    """
    async with app.router.lifespan_context(app):
        yield


@pytest.fixture(scope="session", autouse=True)
async def _setup_schema():
    """Create all tables once for the entire test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Drop the whole schema rather than Base.metadata.drop_all: if the DB was
    # migrated via Alembic (explicitly-named FK constraints), metadata.drop_all
    # fails trying to drop constraints it doesn't know the names of. A schema
    # drop is agnostic to how the tables were created.
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
async def db_session():
    """Provide a clean database session for each test."""
    # Truncate all tables before each test for isolation
    async with engine.begin() as conn:
        # Truncate in reverse dependency order
        await conn.execute(text("TRUNCATE TABLE system_prompts, audit_logs, reports, scores, answers, voice_transcripts, interview_sessions, resume_files, follow_up_questions, questions, subtopics, topics, question_categories, interview_tracks, companies, profiles, users RESTART IDENTITY CASCADE"))

    async with AsyncSessionFactory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def client():
    """Synchronous test client."""
    return TestClient(app)


@pytest.fixture
async def async_client():
    """Async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(db_session):
    """Create a test user and return auth headers."""
    from jose import jwt

    test_user_id = uuid.uuid4()
    test_email = _unique_email()

    user = User(
        id=test_user_id,
        supabase_uid=str(test_user_id),
        email=test_email,
        is_active=True,
        is_admin=False,
    )
    profile = Profile(
        user_id=test_user_id,
        full_name="Test User",
        timezone="UTC",
    )
    db_session.add(user)
    db_session.add(profile)
    await db_session.commit()

    payload = {
        "sub": str(test_user_id),
        "email": test_email,
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(days=7),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(
        payload,
        settings.SUPABASE_JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


# ─── Health Check Tests ────────────────────────────────────────────────────────

class TestHealthCheck:
    async def test_health_endpoint(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data


# ─── Auth Endpoint Tests ───────────────────────────────────────────────────────

class TestAuthEndpoints:
    async def test_sync_profile(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/v1/auth/profile",
            json={"full_name": "Updated Name"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "profile" in data

    async def test_get_me(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.get(
            "/api/v1/auth/me",
            headers=auth_headers,
        )
        assert response.status_code == 200


# ─── Interview Endpoint Tests ──────────────────────────────────────────────────

class TestInterviewEndpoints:
    async def test_start_session(self, async_client: AsyncClient, auth_headers: dict, db_session):
        company = Company(name="TestCo", slug=f"testco-{uuid.uuid4().hex[:6]}", description="Test")
        db_session.add(company)
        await db_session.flush()

        track = InterviewTrack(
            company_id=company.id,
            name="Test Track",
            slug=f"test-track-{uuid.uuid4().hex[:6]}",
            description="Test track",
        )
        db_session.add(track)
        await db_session.commit()

        response = await async_client.post(
            "/api/v1/interview/start",
            json={"track_id": str(track.id)},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert data["status"] == "active"

    async def test_submit_answer_records_without_scoring(
        self, async_client: AsyncClient, auth_headers: dict, db_session
    ):
        """
        End-to-end: start a session, fetch a question, submit an answer, and
        confirm the answer is simply RECORDED. Scoring is deferred to the final
        report (so the interview stays fluent and no score is shown per
        question) -- the submit response must NOT contain per-answer scores.
        """
        company = Company(name="TestCo", slug=f"testco-{uuid.uuid4().hex[:6]}", description="Test")
        db_session.add(company)
        await db_session.flush()

        track = InterviewTrack(
            company_id=company.id,
            name="Test Track",
            slug=f"test-track-{uuid.uuid4().hex[:6]}",
            description="Test track",
        )
        db_session.add(track)
        await db_session.commit()

        start_resp = await async_client.post(
            "/api/v1/interview/start",
            json={"track_id": str(track.id)},
            headers=auth_headers,
        )
        assert start_resp.status_code == 201
        session_id = start_resp.json()["session_id"]

        next_resp = await async_client.get(
            f"/api/v1/interview/{session_id}/next", headers=auth_headers
        )
        assert next_resp.status_code == 200
        question = next_resp.json()["question"]
        assert question is not None

        answer_resp = await async_client.post(
            f"/api/v1/interview/{session_id}/answer",
            json={
                "question_id": question["id"],
                "content": (
                    "HashMap is not synchronized and allows one null key and multiple "
                    "null values, making it faster than Hashtable which is synchronized "
                    "and does not allow nulls. ConcurrentHashMap offers thread safety "
                    "via bucket-level locking instead of locking the whole map."
                ),
            },
            headers=auth_headers,
        )
        assert answer_resp.status_code == 200, answer_resp.text
        data = answer_resp.json()

        # New store-only contract: the answer is recorded, no scoring here.
        assert data["status"] == "recorded"
        assert data["questions_answered"] >= 1

        # Per-answer scores must NOT leak into the submit response anymore --
        # they belong to the end-of-interview report.
        for key in ("technical_score", "overall_score", "feedback"):
            assert key not in data, f"'{key}' should not be in the submit response"

    async def test_get_next_question_no_session(self, async_client: AsyncClient, auth_headers: dict):
        """A nonexistent (or not-owned) session must 404, not silently return an empty question."""
        fake_id = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/interview/{fake_id}/next",
            headers=auth_headers,
        )
        assert response.status_code == 404


# ─── Report Endpoint Tests ──────────────────────────────────────────────────────

class TestReportEndpoints:
    async def test_generate_report_real_ai(
        self, async_client: AsyncClient, auth_headers: dict, db_session
    ):
        """
        End-to-end: run a full session (start -> answer x2 -> complete), then
        generate a report and confirm it's a REAL AI-generated report (not the
        old heuristic-only placeholder) -- exercises PromptBuilder ->
        report_generator.md -> GLMProvider -> ResponseParser -> Pydantic.
        """
        company = Company(name="TestCo", slug=f"testco-{uuid.uuid4().hex[:6]}", description="Test")
        db_session.add(company)
        await db_session.flush()

        track = InterviewTrack(
            company_id=company.id,
            name="Test Track",
            slug=f"test-track-{uuid.uuid4().hex[:6]}",
            description="Test track",
        )
        db_session.add(track)
        await db_session.commit()

        start_resp = await async_client.post(
            "/api/v1/interview/start",
            json={"track_id": str(track.id)},
            headers=auth_headers,
        )
        assert start_resp.status_code == 201
        session_id = start_resp.json()["session_id"]

        answers = [
            "HashMap is not synchronized and allows one null key and multiple null "
            "values, unlike Hashtable which is synchronized and disallows nulls.",
            "final marks a variable/method/class as non-modifiable, finally is a "
            "block that always runs after try/catch, and finalize() was a "
            "deprecated garbage-collection hook.",
        ]
        for answer_content in answers:
            next_resp = await async_client.get(
                f"/api/v1/interview/{session_id}/next", headers=auth_headers
            )
            question = next_resp.json()["question"]
            if question is None:
                break
            answer_resp = await async_client.post(
                f"/api/v1/interview/{session_id}/answer",
                json={"question_id": question["id"], "content": answer_content},
                headers=auth_headers,
            )
            assert answer_resp.status_code == 200, answer_resp.text

        complete_resp = await async_client.post(
            f"/api/v1/interview/{session_id}/complete", headers=auth_headers
        )
        assert complete_resp.status_code == 200

        report_resp = await async_client.post(
            f"/api/v1/reports/{session_id}/generate", headers=auth_headers
        )
        assert report_resp.status_code == 201, report_resp.text
        data = report_resp.json()

        for key in (
            "overall_score", "overall_score_label", "executive_summary",
            "readiness_level", "readiness_reasoning", "strengths", "weaknesses",
            "topic_scores", "dimension_scores", "performance_percentile",
            "question_analysis",
        ):
            assert key in data, f"missing '{key}' in report response"

        assert data["readiness_level"] in (
            "interview_ready", "close_to_ready", "needs_more_practice", "significant_gaps"
        )
        assert 0.0 <= data["overall_score"] <= 100.0
        assert len(data["executive_summary"]) > 0
        assert len(data["question_analysis"]) >= 1


# ─── Questions Endpoint Tests ──────────────────────────────────────────────────

class TestQuestionsEndpoints:
    async def test_list_tracks(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.get(
            "/api/v1/questions/tracks",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)


# ─── Database Connectivity Test ────────────────────────────────────────────────

class TestDatabaseConnectivity:
    async def test_db_connection(self, db_session):
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1

    async def test_user_creation(self, db_session):
        test_email = _unique_email()
        user = User(
            supabase_uid=str(uuid.uuid4()),
            email=test_email,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        from sqlalchemy import select as sa_select
        result = await db_session.execute(
            sa_select(User).where(User.email == test_email)
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.email == test_email


# ─── Supabase Integration Test ─────────────────────────────────────────────────

class TestSupabaseIntegration:
    @pytest.mark.skipif(
        settings.SUPABASE_URL == "https://your-project.supabase.co",
        reason="Supabase project not configured in .env"
    )
    async def test_supabase_health(self):
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.SUPABASE_URL}/health",
                headers={"apikey": settings.SUPABASE_ANON_KEY},
            )
            assert response.status_code == 200

    @pytest.mark.skipif(
        settings.SUPABASE_SERVICE_KEY == "your-service-role-key",
        reason="Service role key not configured in .env"
    )
    async def test_supabase_storage_bucket_exists(self):
        from supabase import create_client
        supabase = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY,
        )
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        assert "resumes" in bucket_names, f"Resume bucket not found. Found: {bucket_names}"


# ─── Question-pool tenancy ────────────────────────────────────────────────────


class TestQuestionPoolIsolation:
    """
    One candidate's generated questions must never reach another's interview.

    This is the behavioural half of tests/test_question_tenancy.py, which checks
    the source for a missing filter. Both are needed: the structural test catches
    a query written without the filter, this one catches a filter that is present
    but wrong.

    The bug these exist for: a live cross-question quoting one candidate's
    speech-to-text — "You mentioned 'annual function' in your answer" — was
    written into the shared questions table under the track's topic, and the next
    candidate's plan picked it out of the pool as an ordinary question.
    """

    async def _track_with_topic(self, db_session):
        """A company → track → category → topic chain to hang questions off."""
        from app.models.company import Company, InterviewTrack, QuestionCategory
        from app.models.question import Topic

        company = Company(id=uuid.uuid4(), name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}", is_active=True)
        db_session.add(company)
        await db_session.flush()
        track = InterviewTrack(
            id=uuid.uuid4(), company_id=company.id, name="FSE",
            slug=f"fse-{uuid.uuid4().hex[:6]}", is_active=True,
        )
        db_session.add(track)
        await db_session.flush()
        cat = QuestionCategory(
            id=uuid.uuid4(), track_id=track.id, name="Core",
            slug=f"core-{uuid.uuid4().hex[:6]}", order_index=0, is_active=True,
        )
        db_session.add(cat)
        await db_session.flush()
        topic = Topic(
            id=uuid.uuid4(), category_id=cat.id, name="Java",
            slug=f"java-{uuid.uuid4().hex[:6]}", order_index=0,
        )
        db_session.add(topic)
        await db_session.flush()
        return track, topic

    async def _session_for(self, db_session, track, email_suffix: str):
        from app.models.session import InterviewSession, SessionStatus
        from app.models.user import User

        uid = uuid.uuid4()
        db_session.add(User(id=uid, supabase_uid=str(uid), email=f"{email_suffix}@example.com"))
        await db_session.flush()
        sess = InterviewSession(
            id=uuid.uuid4(), user_id=uid, track_id=track.id,
            status=SessionStatus.ACTIVE, mode="text",
        )
        db_session.add(sess)
        await db_session.flush()
        return sess

    async def test_another_sessions_cross_question_is_not_in_the_plan_pool(self, db_session):
        """
        Candidate B's fallback plan must be built only from bank questions, never
        from the cross-question generated inside candidate A's interview.
        """
        from sqlalchemy import select

        from app.models.question import Question
        from app.services.interview.orchestrator import InterviewOrchestrator

        track, topic = await self._track_with_topic(db_session)
        session_a = await self._session_for(db_session, track, "candidate-a")
        session_b = await self._session_for(db_session, track, "candidate-b")

        # A bank question anyone may be asked.
        db_session.add(Question(
            id=uuid.uuid4(), topic_id=topic.id, session_id=None,
            content="What is the difference between an interface and an abstract class?",
            difficulty="easy", question_type="conceptual",
        ))
        # The leak: a cross-question quoting candidate A, owned by A's session.
        leaked = Question(
            id=uuid.uuid4(), topic_id=topic.id, session_id=session_a.id,
            content="You mentioned 'annual function' in your answer instead of method overriding — what do those mean?",
            difficulty="easy", question_type="conceptual",
        )
        db_session.add(leaked)
        await db_session.commit()

        orch = InterviewOrchestrator(db_session)
        planned_ids, _ = await orch._fallback_plan(track.id, session_b.id)
        await db_session.commit()

        assert str(leaked.id) not in planned_ids, (
            "candidate A's cross-question was selected into candidate B's plan"
        )

        contents = list(await db_session.scalars(
            select(Question.content).where(Question.id.in_([uuid.UUID(i) for i in planned_ids]))
        ))
        assert not any("annual function" in c for c in contents), (
            "candidate A's spoken words reached candidate B's interview"
        )

    async def test_plan_questions_are_owned_by_their_session(self, db_session):
        """
        A planned question can be resume-tailored, so it must be stamped with the
        session that generated it and never left in the shared bank.
        """
        from app.models.question import Question
        from app.services.interview.orchestrator import InterviewOrchestrator

        track, _ = await self._track_with_topic(db_session)
        sess = await self._session_for(db_session, track, "candidate-c")
        await db_session.commit()

        orch = InterviewOrchestrator(db_session)
        planned_ids, _ = await orch._fallback_plan(track.id, sess.id)
        await db_session.commit()

        assert planned_ids, "fallback plan produced no questions"
        intro = await db_session.get(Question, uuid.UUID(planned_ids[0]))
        assert intro is not None
        assert intro.session_id == sess.id, (
            "the intro question was left in the shared bank, so every future "
            "fallback plan would accumulate another copy of it"
        )

    async def test_answer_cannot_be_filed_against_another_sessions_question(self, db_session):
        """
        The endpoint checks the SESSION belongs to the caller but used to accept
        any question_id. A mismatched (question, answer) pair is fed straight to
        the cross-question prompt, which then asks about a topic the candidate
        never discussed — the same symptom, reached a different way.
        """
        from app.models.question import Question
        from app.services.interview.orchestrator import InterviewOrchestrator

        track, topic = await self._track_with_topic(db_session)
        session_a = await self._session_for(db_session, track, "candidate-d")
        session_b = await self._session_for(db_session, track, "candidate-e")

        foreign = Question(
            id=uuid.uuid4(), topic_id=topic.id, session_id=session_a.id,
            content="A question generated inside candidate A's interview.",
            difficulty="easy", question_type="conceptual",
        )
        db_session.add(foreign)
        await db_session.commit()

        orch = InterviewOrchestrator(db_session)
        with pytest.raises(ValueError, match="different interview session"):
            await orch.submit_answer(session_b.id, foreign.id, "some answer text")

    async def test_bank_questions_remain_answerable_by_anyone(self, db_session):
        """
        The guard above must not lock candidates out of the shared bank, which is
        where most questions legitimately come from.
        """
        from app.models.question import Question
        from app.services.interview.orchestrator import InterviewOrchestrator

        track, topic = await self._track_with_topic(db_session)
        sess = await self._session_for(db_session, track, "candidate-f")
        bank = Question(
            id=uuid.uuid4(), topic_id=topic.id, session_id=None,
            content="What is a HashMap?", difficulty="easy", question_type="conceptual",
        )
        db_session.add(bank)
        await db_session.commit()

        orch = InterviewOrchestrator(db_session)
        result = await orch.submit_answer(sess.id, bank.id, "It stores key value pairs in buckets.")
        assert result["questions_answered"] == 1
