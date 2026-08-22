"""
The paywall over real HTTP — tests/test_report_paywall_http.py

WHY THIS FILE EXISTS SEPARATELY FROM test_report_access.py. That file tests the DECISION —
`evaluate` returning locked or not for a given ledger state — and it is thorough about the
fail-open cases. What it cannot see is the SERIALISATION: whether the thing that actually
leaves the server over the wire has the sold content stripped out of it, and whether the
unlock really is nothing more than a refetch. Two source-inspection tests stood in for that,
and source inspection cannot catch a field that leaks because Pydantic serialised a default.

So these go through the ASGI app, with a real JWT, against a real report row, and read the
JSON body. There are exactly two claims, and they are the two the product makes to a
candidate:

  1. A FREE interview's report comes back as a teaser. The score is there, the count is there,
     and nothing that is being sold is — no summary, no dimension scores, no per-question
     analysis, no roadmap, no pdf. Asserted by walking the response, not by naming three
     fields, so a NEW field added to ReportResponse cannot quietly ship through the paywall.

  2. UNLOCKING IS A REFETCH. The same GET, by the same user, on the same report, after the
     unlock lands in the ledger, returns the whole thing. Nothing is regenerated — which is
     the entire reason the gate is on delivery rather than on generation, and it is worth
     having a test that would fail if somebody "optimised" that into a regeneration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.core.config import settings
from app.main import app
from app.services.billing.plans import (
    REPORT_UNLOCK_FEATURE,
    REPORT_UNLOCK_ITEM,
    REPORT_UNLOCK_PRICE_PAISE,
    trial_allowance,
)

pytestmark = pytest.mark.asyncio

#: Everything the unlock is selling. A locked response must carry none of it.
#:
#: Kept as data rather than as a list of assertions so that the "nothing new leaks" test can
#: check the COMPLEMENT — every field on the model that is not the teaser and not metadata —
#: and fail when ReportResponse grows a field nobody classified.
SOLD = (
    "executive_summary",
    "readiness_level",
    "readiness_reasoning",
    "strengths",
    "weaknesses",
    "topic_scores",
    "dimension_scores",
    "performance_percentile",
    "question_analysis",
    "improvement_roadmap",
    "pdf_url",
    "delivery",
    "previous",
)

#: Free to see: identity, the teaser, and the lock itself. A candidate is entitled to know
#: which session this is, roughly how they did, how much is behind the wall and what it costs.
NOT_SOLD = (
    "id",
    "session_id",
    "overall_score",
    "overall_score_label",
    "is_shared",
    "created_at",
    "unscored_reason",
    "locked",
    "lock_price_paise",
    "lock_item_id",
    "lock_question_count",
)


@pytest.fixture
async def env():
    """A user with a completed FREE interview and a full report stored against it."""
    from app.db.session import AsyncSessionFactory, engine
    from app.models.base import Base
    from app.models.company import Company, InterviewTrack
    from app.models.report import Report
    from app.models.session import InterviewSession, SessionStatus
    from app.models.user import User

    # test_integration.py drops the schema, so a fixture that assumes one silently SKIPS — and
    # a skipped test has already been mistaken for a passing one twice in this project.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uid = uuid.uuid4()
    sid = uuid.uuid4()
    async with AsyncSessionFactory() as db:
        company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
        track = InterviewTrack(
            id=uuid.uuid4(), company_id=company.id, name="T", slug=f"t-{uuid.uuid4().hex[:8]}"
        )
        db.add_all([
            User(id=uid, supabase_uid=str(uid), email=f"pw-{uid}@example.test",
                 is_active=True, is_admin=False),
            company,
            track,
        ])
        await db.flush()
        db.add(InterviewSession(id=sid, user_id=uid, track_id=track.id,
                                status=SessionStatus.COMPLETED))
        await db.flush()
        db.add(Report(
            id=uuid.uuid4(),
            session_id=sid,
            user_id=uid,
            overall_score=68.0,
            overall_score_label="Solid",
            executive_summary="A real summary that must not leak.",
            readiness_level="close_to_ready",
            strengths=["Collections"],
            weaknesses=["Concurrency"],
            topic_scores={"java": 70.0},
            improvement_roadmap=[{"topic": "Concurrency", "why": "weakest", "resources": []}],
            raw_report={
                "readiness_reasoning": "Nearly there.",
                "dimension_scores": {"technical": 70.0},
                "performance_percentile": 61,
                "question_analysis": [
                    {
                        "question": "HashMap vs Hashtable?",
                        "ideal_answer_summary": "The answer being sold.",
                    }
                ],
            },
        ))
        await db.commit()

    token = jwt.encode(
        {
            "sub": str(uid),
            "email": f"pw-{uid}@example.test",
            "aud": "authenticated",
            "exp": datetime.now(UTC) + timedelta(days=1),
            "iat": datetime.now(UTC),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {
        "user_id": uid,
        "session_id": sid,
        "headers": {"Authorization": f"Bearer {token}"},
    }


async def _burn_the_free_interview(user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """Spend the trial on this session, which is what makes its report payable."""
    from app.db.session import AsyncSessionFactory
    from app.services.billing.credits import consume

    async with AsyncSessionFactory() as db:
        await consume(db, user_id, "interview", session_id=session_id)
        await db.commit()


async def _get_report(env) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/reports/{env['session_id']}", headers=env["headers"])
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_a_free_interviews_report_arrives_as_a_teaser(env):
    await _burn_the_free_interview(env["user_id"], env["session_id"])
    body = await _get_report(env)

    # The lock, priced and named by the server. The browser never invents either.
    assert body["locked"] is True
    assert body["lock_price_paise"] == REPORT_UNLOCK_PRICE_PAISE == 4_900
    assert body["lock_item_id"] == REPORT_UNLOCK_ITEM.id == "report_unlock_1"

    # The teaser: the score they already want, and how much is waiting.
    assert body["overall_score"] == 68.0
    assert body["lock_question_count"] == 1

    # NOTHING BEING SOLD IS IN THE BODY — checked as a string search over the serialised
    # response, not field by field, because a leak through a nested structure would satisfy
    # a per-field check while still putting the answer on the wire.
    import json

    raw = json.dumps(body)
    assert "must not leak" not in raw
    assert "The answer being sold." not in raw
    assert "Nearly there." not in raw
    for field in SOLD:
        assert not body[field], f"{field} survived the paywall: {body[field]!r}"


async def test_no_unclassified_field_can_ship_through_the_paywall(env):
    """
    A GUARD ON THE FUTURE, not on today's behaviour.

    `_deliver` clears a fixed list of fields. The next person to add a field to
    ReportResponse gets it delivered through the paywall for free unless they think about it,
    and the failure is silent — a paid-for insight appearing on a locked screen, noticed by
    nobody. So this asserts that every field on the model is either something we sell (and is
    therefore cleared) or something deliberately given away, with no third category.
    """
    from app.api.v1.reports import ReportResponse

    classified = set(SOLD) | set(NOT_SOLD)
    actual = set(ReportResponse.model_fields)
    assert actual == classified, (
        "ReportResponse has changed. Add each new field to SOLD (and clear it in `_deliver`) "
        f"or to NOT_SOLD, deliberately.\n  unclassified: {sorted(actual - classified)}\n"
        f"  gone: {sorted(classified - actual)}"
    )


async def test_unlocking_is_a_refetch_and_nothing_is_regenerated(env):
    await _burn_the_free_interview(env["user_id"], env["session_id"])
    assert (await _get_report(env))["locked"] is True

    from app.db.session import AsyncSessionFactory
    from app.services.billing.credits import grant

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

    body = await _get_report(env)
    assert body["locked"] is False
    # The SAME report row, not a new one — the gate was never on generation.
    assert body["session_id"] == str(env["session_id"])
    assert body["executive_summary"] == "A real summary that must not leak."
    assert body["readiness_level"] == "close_to_ready"
    assert body["question_analysis"][0]["ideal_answer_summary"] == "The answer being sold."
    assert body["improvement_roadmap"]
    assert body["dimension_scores"]


async def test_a_purchased_interviews_report_was_never_locked(env):
    """The other half of the rule, over HTTP: paying for the interview includes the report."""
    from app.db.session import AsyncSessionFactory
    from app.services.billing.credits import consume, grant

    async with AsyncSessionFactory() as db:
        # Used the free one on some earlier session, then bought.
        for _ in range(trial_allowance("interview")):
            await consume(db, env["user_id"], "interview")
        await grant(db, env["user_id"], "interview", 1,
                    payment_ref=f"pay_{uuid.uuid4().hex[:12]}")
        # THIS session is the bought one.
        await consume(db, env["user_id"], "interview", session_id=env["session_id"])
        await db.commit()

    body = await _get_report(env)
    assert body["locked"] is False
    assert body["lock_price_paise"] is None
    assert body["executive_summary"] == "A real summary that must not leak."
