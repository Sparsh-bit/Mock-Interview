"""
A duplicate rating must not discard the caller's work — tests/test_rating_savepoint.py

THE BUG THIS PINS WAS SILENT DATA LOSS, and it took direct instrumentation to find, which is
exactly why it needs a test rather than a comment.

`record_round` writes a RatingEvent with a UNIQUE constraint on session_id, so that a
regenerated report cannot bank the same rating gain twice. That duplicate is EXPECTED — the
docstring says so. It was handled with `await db.rollback()`.

But reports are generated inside ONE transaction with the rating, deliberately, so that a
candidate can never see a report with no rating attached. So the rollback threw away the
caller's report write along with the rating. On a second generation for the same session the
endpoint returned 200, logged the new score, and the database still held the old row —
measured: the UPDATE wrote thirteen analyses with rowcount 1, and the row afterwards had six.
Every retry redid the same work and persisted none of it.

The insert now runs inside a SAVEPOINT, so a duplicate costs exactly the rating.

WHAT EACH TEST IS FOR:

  the first call still rates the round        — the savepoint must not break the normal path
  a duplicate returns None                    — the caller's contract is unchanged
  A WRITE MADE BEFORE THE DUPLICATE SURVIVES  — the actual bug
  the session is still usable afterwards      — a poisoned transaction would fail at commit
                                                instead, which is the same loss one step later
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.services.progress.rating import Tier
from app.services.progress.recorder import record_round


@pytest.mark.asyncio
class TestADuplicateRatingCostsOnlyTheRating:
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
                company,
                track,
                User(
                    id=uid,
                    supabase_uid=str(uid),
                    email=f"sp-{uid}@example.test",
                    is_active=True,
                    is_admin=False,
                ),
            ])
            await db.flush()
            db.add(
                InterviewSession(
                    id=sid, user_id=uid, track_id=track.id, status=SessionStatus.COMPLETED
                )
            )
            await db.commit()
        return uid, sid

    async def test_the_first_call_rates_the_round(self, env):
        from app.db.session import AsyncSessionFactory

        uid, sid = env
        async with AsyncSessionFactory() as db:
            event = await record_round(
                db, user_id=uid, session_id=sid, kind="interview", tier=Tier.CORE,
                score_out_of_100=70.0, topics=["Java"],
            )
            assert event is not None, "the savepoint must not break the normal path"
            await db.commit()

    async def test_a_duplicate_returns_none_rather_than_raising(self, env):
        from app.db.session import AsyncSessionFactory

        uid, sid = env
        async with AsyncSessionFactory() as db:
            assert await record_round(
                db, user_id=uid, session_id=sid, kind="interview", tier=Tier.CORE,
                score_out_of_100=70.0, topics=["Java"],
            ) is not None
            await db.commit()

        async with AsyncSessionFactory() as db:
            again = await record_round(
                db, user_id=uid, session_id=sid, kind="interview", tier=Tier.CORE,
                score_out_of_100=70.0, topics=["Java"],
            )
            assert again is None, "a session already rated is not an error"
            await db.commit()

    async def test_a_write_made_before_the_duplicate_survives(self, env):
        """
        THE BUG. A report write shares this transaction, and it must still be there.
        """
        from app.db.session import AsyncSessionFactory
        from app.models.report import Report

        uid, sid = env
        async with AsyncSessionFactory() as db:
            assert await record_round(
                db, user_id=uid, session_id=sid, kind="interview", tier=Tier.CORE,
                score_out_of_100=70.0, topics=["Java"],
            ) is not None
            await db.commit()

        async with AsyncSessionFactory() as db:
            # Stands in for the report the endpoint writes just before rating the round.
            db.add(
                Report(
                    session_id=sid,
                    user_id=uid,
                    overall_score=88.0,
                    overall_score_label="Excellent",
                    executive_summary="written before the rating was attempted",
                    readiness_level="interview_ready",
                    strengths=[],
                    weaknesses=[],
                    topic_scores={},
                    improvement_roadmap=[],
                    raw_report={"generated_by": "ai"},
                )
            )
            await db.flush()

            # The duplicate. Before the savepoint this rolled the transaction back and the
            # report above ceased to exist, with no error anywhere.
            assert await record_round(
                db, user_id=uid, session_id=sid, kind="interview", tier=Tier.CORE,
                score_out_of_100=70.0, topics=["Java"],
            ) is None
            await db.commit()

        async with AsyncSessionFactory() as db:
            stored = await db.scalar(select(Report).where(Report.session_id == sid))
            assert stored is not None, (
                "the report written before the duplicate rating was DISCARDED — this is the "
                "silent data loss that made a partial report impossible to complete: every "
                "retry regenerated it and none of them persisted."
            )
            assert stored.overall_score == 88.0

    async def test_the_session_still_works_after_a_duplicate(self, env):
        """
        A savepoint that is not released leaves the transaction poisoned, and the loss simply
        moves to the commit — where it is even harder to attribute.
        """
        from app.db.session import AsyncSessionFactory
        from app.models.report import Report

        uid, sid = env
        async with AsyncSessionFactory() as db:
            assert await record_round(
                db, user_id=uid, session_id=sid, kind="interview", tier=Tier.CORE,
                score_out_of_100=70.0, topics=["Java"],
            ) is not None
            await db.commit()

        async with AsyncSessionFactory() as db:
            assert await record_round(
                db, user_id=uid, session_id=sid, kind="interview", tier=Tier.CORE,
                score_out_of_100=70.0, topics=["Java"],
            ) is None
            # Writing AFTER the duplicate must work too — the endpoint's activity-feed row and
            # its final commit both happen after `record_round` returns.
            db.add(
                Report(
                    session_id=sid,
                    user_id=uid,
                    overall_score=91.0,
                    overall_score_label="Excellent",
                    executive_summary="written after the duplicate",
                    readiness_level="interview_ready",
                    strengths=[],
                    weaknesses=[],
                    topic_scores={},
                    improvement_roadmap=[],
                    raw_report={"generated_by": "ai"},
                )
            )
            await db.commit()

        async with AsyncSessionFactory() as db:
            stored = await db.scalar(select(Report).where(Report.session_id == sid))
            assert stored is not None and stored.overall_score == 91.0
