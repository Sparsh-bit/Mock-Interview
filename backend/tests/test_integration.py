"""
Integration tests for InterviewOS backend.
Run with: pytest tests/test_integration.py -v --tb=short
"""
import os
import sys
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.core.config import settings
from app.db.session import engine, AsyncSessionFactory
from app.models.base import Base
from app.models.user import User, Profile
from app.models.company import Company, InterviewTrack, QuestionCategory
from app.models.question import Topic, Question, QuestionDifficulty, QuestionType
from app.models.session import InterviewSession, SessionStatus, Answer, Score
from app.models.report import Report, ResumeFile


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture(scope="session", autouse=True)
async def _setup_schema():
    """Create all tables once for the entire test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Clean up by dropping all tables after all tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "iat": datetime.now(timezone.utc),
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

    async def test_get_next_question_no_session(self, async_client: AsyncClient, auth_headers: dict):
        """A nonexistent (or not-owned) session must 404, not silently return an empty question."""
        fake_id = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/interview/{fake_id}/next",
            headers=auth_headers,
        )
        assert response.status_code == 404


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
