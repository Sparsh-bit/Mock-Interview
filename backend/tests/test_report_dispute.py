"""
Disputing a machine-written assessment — tests/test_report_dispute.py

WHY THIS EXISTS. A report here says whether somebody is ready for a job interview, in the
shape of a score and a readiness level, and a model wrote it without a human reading it
first. A candidate can reasonably act on that — practise differently, apply or not apply,
believe something about themselves — and the model can be wrong. It can mark a correct answer
down, miss what somebody actually said, or produce feedback that does not fit the session at
all.

So there has to be a way to say "this is wrong" and reach a person. Not because the law here
demands one in exactly this shape, but because the alternative is an automated judgement about
a person with no route of appeal, and that is the thing worth avoiding on its own terms.

WHAT THIS PINS.

  A dispute is OWNED. Only the person the report is about can raise one, and nobody can
  raise one against somebody else's report — the same IDOR question `test_pentest_idor.py`
  asks of every other object, asked again of a new one rather than assumed.

  ONE OPEN DISPUTE PER REPORT, enforced by a unique index rather than by the endpoint
  reading first. A read-then-write check has a window between the read and the write, and
  two taps on a slow connection land in it — the same reasoning `interview_feedback` records
  for its own constraint.

  IT IS NEVER SILENTLY CLOSED. A dispute has a status and a resolution, so "we looked and
  the score stands" is a thing that can be said, rather than the row simply disappearing.

  THE TEXT IS UNTRUSTED. A dispute reason is free text a candidate types, and it ends up in
  front of an admin. It is bounded, and it must never be handed to a model as instructions —
  the trust boundary from services/ai/untrusted.py applies to it as much as to an answer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio


def _token(user_id: uuid.UUID) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": f"d-{user_id}@example.test",
            "aud": settings.SUPABASE_JWT_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


async def _seed_report(owner: uuid.UUID) -> uuid.UUID:
    """A user, a completed session and a report belonging to them."""
    from app.db.session import AsyncSessionFactory, engine
    from app.models.base import Base
    from app.models.company import Company, InterviewTrack
    from app.models.report import Report
    from app.models.session import InterviewSession
    from app.models.user import User

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_id = uuid.uuid4()
    report_id = uuid.uuid4()
    async with AsyncSessionFactory() as db:
        # A session needs a track and a track needs a company — `track_id` is NOT NULL, and
        # a fixture that skips them fails on the insert rather than on the thing under test.
        company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
        track = InterviewTrack(
            id=uuid.uuid4(), company_id=company.id, name="T", slug=f"t-{uuid.uuid4().hex[:8]}"
        )
        db.add_all([
            company,
            track,
            User(
                id=owner,
                supabase_uid=str(owner),
                email=f"d-{owner}@example.test",
                is_active=True,
                is_admin=False,
            ),
        ])
        await db.flush()
        db.add(
            InterviewSession(
                id=session_id, user_id=owner, track_id=track.id, status="completed"
            )
        )
        await db.flush()
        db.add(
            Report(
                id=report_id,
                session_id=session_id,
                user_id=owner,
                overall_score=41.0,
                overall_score_label="Needs work",
                readiness_level="needs_work",
                executive_summary="A short summary.",
            )
        )
        await db.commit()
    return report_id


async def _post(user_id: uuid.UUID, report_id: uuid.UUID, reason: str):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
    ):
        return await ac.post(
            f"/api/v1/reports/{report_id}/dispute",
            headers={"Authorization": f"Bearer {_token(user_id)}"},
            json={"reason": reason},
        )


class TestACandidateCanDisputeTheirOwnReport:
    async def test_a_dispute_is_accepted_and_recorded(self):
        owner = uuid.uuid4()
        report_id = await _seed_report(owner)

        response = await _post(owner, report_id, "It marked my HashMap answer wrong. It was right.")

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "open"
        assert body["report_id"] == str(report_id)

    async def test_the_dispute_is_readable_back(self):
        owner = uuid.uuid4()
        report_id = await _seed_report(owner)
        await _post(owner, report_id, "The transcript is not what I said.")

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            response = await ac.get(
                f"/api/v1/reports/{report_id}/dispute",
                headers={"Authorization": f"Bearer {_token(owner)}"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "open"

    async def test_a_second_dispute_does_not_create_a_duplicate(self):
        """
        ONE OPEN DISPUTE PER REPORT. Two taps on a slow connection must not become two rows
        for a human to reconcile, and the guarantee is a unique index rather than a
        read-then-write check with a window in it.
        """
        owner = uuid.uuid4()
        report_id = await _seed_report(owner)

        first = await _post(owner, report_id, "First reason.")
        second = await _post(owner, report_id, "Second reason.")

        assert first.status_code == 201
        assert second.status_code in (200, 409), second.text
        # Either answer is fine as long as it is not a second open dispute.
        assert second.json().get("id") == first.json().get("id") or second.status_code == 409


class TestNobodyCanDisputeSomebodyElsesReport:
    async def test_a_stranger_gets_a_404_rather_than_a_403(self):
        """
        404, NOT 403 — the same rule the public-report route follows. A 403 confirms the
        report exists, which is a disclosure in itself.
        """
        owner = uuid.uuid4()
        stranger = uuid.uuid4()
        report_id = await _seed_report(owner)
        await _seed_report(stranger)

        response = await _post(stranger, report_id, "Not mine, but I would like it changed.")

        assert response.status_code == 404, response.text

    async def test_an_unauthenticated_caller_is_refused(self):
        owner = uuid.uuid4()
        report_id = await _seed_report(owner)

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac,
        ):
            response = await ac.post(
                f"/api/v1/reports/{report_id}/dispute", json={"reason": "hello"}
            )
        assert response.status_code == 401


class TestTheReasonIsTreatedAsUntrustedText:
    async def test_an_empty_reason_is_refused(self):
        owner = uuid.uuid4()
        report_id = await _seed_report(owner)

        assert (await _post(owner, report_id, "")).status_code == 422
        assert (await _post(owner, report_id, "   ")).status_code == 422

    async def test_an_enormous_reason_is_refused_rather_than_stored(self):
        owner = uuid.uuid4()
        report_id = await _seed_report(owner)

        response = await _post(owner, report_id, "x" * 20_000)

        assert response.status_code == 422

    async def test_the_reason_is_never_fed_to_a_model(self):
        """
        A dispute reason is free text written by somebody arguing about their score — which
        makes it the single most motivated piece of injection bait in the product. Nothing
        may pass it to an AI call; if that ever changes it has to go through
        `services/ai/untrusted.fence` like every other candidate string.
        """
        import ast
        import pathlib

        api = pathlib.Path(__file__).resolve().parents[1] / "app"
        offenders: list[str] = []
        for path in api.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "dispute" not in text.lower():
                continue
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name not in ("chat", "chat_static", "generate_structured", "generate"):
                    continue
                snippet = ast.dump(node)
                if "reason" in snippet and "dispute" in text.lower():
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, f"a dispute reason may be reaching a model: {offenders}"


class TestTheDisputeIsVisibleToSomebodyWhoCanAct:
    def test_an_admin_route_exists_and_is_swept_for_authorisation(self):
        from app.main import app as live
        from tests.test_pentest_authz import _ADMIN_PREFIXES, _walk

        paths = [p for _m, p in _walk(live.routes)]
        assert "/api/v1/admin/disputes" in paths, (
            "a dispute nobody can see is a dispute nobody will answer"
        )
        assert "/api/v1/admin/disputes".startswith(_ADMIN_PREFIXES)

    def test_a_dispute_carries_a_resolution_field_so_it_is_never_closed_silently(self):
        from app.models.report import ReportDispute

        for column in ("status", "resolution", "resolved_at"):
            assert hasattr(ReportDispute, column), f"ReportDispute has no {column}"

    def test_a_migration_creates_the_table(self):
        import pathlib

        versions = (
            pathlib.Path(__file__).resolve().parents[2] / "database" / "migrations" / "versions"
        )
        sources = "\n".join(p.read_text(encoding="utf-8") for p in versions.glob("*.py"))
        assert "report_disputes" in sources
