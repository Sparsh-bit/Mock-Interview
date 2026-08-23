"""
Deleting an account is permanent, confirmed, and cannot strand one — test_admin_delete_user.py

Asked for as "give the feature in the users section in admin to delete any account
permanently".

WHAT "PERMANENTLY" HAD TO MEAN, and why the obvious implementation is not it. Our `users` row
is not the account: the credentials live in Supabase's auth schema, and `get_current_user`
creates a local row on first sight of a valid token — deliberately, so nobody is ever locked
out by a signup hook that failed months ago. So deleting only our row means the person signs
in again, gets a fresh row, and is back: their data gone, their access intact. That is the
worst available outcome and it presents as the delete button not working.

THE ORDER OF OPERATIONS IS THE DESIGN, and these tests are mostly about it: files, then the
login, then our rows. A failure at the login must ABORT before any data is touched, because
the alternative leaves a working login attached to nothing.

The refusals are tested as hard as the deletion, because the mistake this feature makes
available is mundane, one click away, and irreversible: the wrong row in a list where every
row looks the same.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.main import app

ADMIN_API = pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/admin.py"
SRC = ADMIN_API.read_text()
BLOCK = SRC[SRC.index("async def delete_user(") : SRC.index('@router.get("/audit"')]


class TestItActuallyRemovesTheAccount:
    def test_it_deletes_the_supabase_login_not_just_our_row(self):
        """
        THE DIFFERENCE BETWEEN A DELETION AND A DATA WIPE. Without this the person signs back
        in and `get_current_user` recreates them.
        """
        assert "_delete_supabase_user" in BLOCK
        assert "async def _delete_supabase_user" in SRC

    def test_the_supabase_call_is_a_delete_against_the_admin_api(self):
        helper = SRC[SRC.index("async def _delete_supabase_user") : SRC.index("async def _delete_stored_files")]
        assert "/auth/v1/admin/users/" in helper
        assert "client.delete(" in helper
        # 404 must count as success, or a retry of a half-finished deletion can never complete.
        assert "404" in helper

    def test_it_removes_the_stored_files(self):
        """
        The cascade does not reach storage. `resume_files` rows go with the user and the objects
        they point at would stay in the bucket forever — a candidate's CV, still stored,
        referenced by nothing that would ever reveal it exists.
        """
        assert "_delete_stored_files" in BLOCK
        assert "SUPABASE_STORAGE_BUCKET_RESUMES" in SRC

    def test_it_deletes_with_a_core_statement_so_the_database_cascade_runs(self):
        """
        NOT `db.delete(user)`. The ORM does not defer to ON DELETE rules unless every
        relationship declares `passive_deletes=True`; it loads the children and NULLS their
        foreign keys, which on a NOT NULL column is an instant IntegrityError:

            UPDATE resume_files SET user_id=NULL ...
            null value in column "user_id" violates not-null constraint

        That 500'd the endpoint and deleted nobody — accounts stayed listed after being
        "deleted". The FK rules were right all along; the ORM never let them run.
        """
        assert "sa_delete(User)" in BLOCK
        assert "await db.delete(user)" not in BLOCK, (
            "the ORM delete nullifies NOT NULL child columns instead of cascading"
        )


class TestTheOrderOfOperations:
    """
    Ordering is what a failure halfway through leaves behind, and it is the whole design.
    """

    def test_the_login_is_deleted_before_our_rows(self):
        # Reversed, a failure at the login step leaves our data gone and the login working —
        # the person signs in and is silently recreated.
        assert BLOCK.index("_delete_supabase_user") < BLOCK.index("sa_delete(User)")

    def test_a_failed_login_deletion_aborts_before_touching_data(self):
        at = BLOCK.index("_delete_supabase_user")
        after = BLOCK[at : at + 700]
        assert "raise HTTPException" in after, (
            "a failed auth deletion must refuse, not continue — continuing leaves a working "
            "login attached to no data"
        )
        assert "nothing was" in after.lower() or "nothing" in after.lower()

    def test_files_are_removed_before_the_rows_that_name_them(self):
        # After the rows are gone there is nothing left that knows the storage paths.
        assert BLOCK.index("_delete_stored_files") < BLOCK.index("sa_delete(User)")

    def test_a_file_failure_does_not_abort_the_deletion(self):
        helper = SRC[SRC.index("async def _delete_stored_files") : SRC.index("class DeleteUserRequest")]
        # Files are unreachable either way once the rows are gone, so refusing to proceed over
        # one would strand the account instead of deleting it.
        assert "contextlib.suppress" in helper
        assert "raise" not in helper


class TestItRefusesTheMistakesThatCannotBeUndone:
    def test_the_email_must_match_and_the_server_checks_it(self):
        """
        A confirmation the client alone enforces is not a confirmation: the endpoint is
        reachable with a user id and nothing else.
        """
        assert "confirm_email" in BLOCK
        assert "does not match" in BLOCK
        # Case-insensitive and trimmed, or a correct address rejected over a capital letter
        # teaches the admin that the confirmation is noise.
        assert ".strip().lower()" in BLOCK

    def test_an_admin_cannot_delete_their_own_account(self):
        assert "user.id == current_user.user_id" in BLOCK
        assert "cannot delete your own account" in BLOCK

    def test_the_last_admin_cannot_be_deleted(self):
        # Counted rather than inferred from this row: the dangerous case is deleting the OTHER
        # admin while assuming you are not the last one.
        assert "last admin account" in BLOCK
        assert "User.is_admin.is_(True), User.id != user.id" in BLOCK

    def test_a_missing_user_is_a_404_not_a_silent_success(self):
        assert "User not found" in BLOCK


class TestItLeavesAnAudit:
    def test_the_deletion_is_recorded_before_it_happens(self):
        # Captured before, because afterwards there is nothing left to describe.
        assert BLOCK.index("AuditLog(") < BLOCK.index("sa_delete(User)")
        assert 'action="admin.user_deleted"' in BLOCK

    def test_the_audit_row_survives_the_deletion(self):
        """
        `entity_id` is a plain UUID column rather than a foreign key, which is exactly what
        stops the record of the deletion being deleted by it. Asserted on the MODEL, because
        that is where the property lives.
        """
        model = (
            pathlib.Path(__file__).resolve().parents[1] / "app/models/system.py"
        ).read_text()
        at = model.index("entity_id")
        assert "ForeignKey" not in model[at : at + 200]
        # And the actor is SET NULL, so the row outlives the admin too.
        assert 'ForeignKey("users.id", ondelete="SET NULL")' in model

    def test_the_email_is_captured_before_the_row_goes(self):
        assert BLOCK.index("target_email = user.email") < BLOCK.index("sa_delete(User)")
        assert '"target_email": target_email' in BLOCK

    def test_the_reason_is_recorded(self):
        assert '"reason"' in BLOCK


class TestItIsAdminOnlyAndRateLimited:
    def test_it_is_a_post_because_it_carries_a_confirmation(self):
        """
        A body on a DELETE is permitted to be dropped by intermediaries, and this app is served
        through Cloudflare. A confirmation that can vanish in transit is worse than none: the
        endpoint would refuse every legitimate deletion, or with a laxer check accept one that
        was never confirmed.
        """
        at = SRC.index("async def delete_user(")
        decorator = SRC[SRC.rindex("@router.", 0, at) : at]
        assert "@router.post(" in decorator
        assert "/delete" in decorator

    def test_it_is_behind_admin_auth(self):
        at = SRC.index("async def delete_user(")
        assert "current_user: AdminUser" in SRC[at : at + 500]

    def test_it_shares_the_admin_write_rate_limit(self):
        at = SRC.rindex("@router.post(", 0, SRC.index("async def delete_user("))
        assert "_admin_write_rate_limit" in SRC[at : SRC.index("async def delete_user(")]


# ─── The behavioural test, and why the ones above were not enough ──────────────────────────
#
# EVERY SOURCE ASSERTION IN THIS FILE PASSED WHILE THE ENDPOINT WAS COMPLETELY BROKEN.
#
# The first implementation used `await db.delete(user)`. That goes through the ORM, and the ORM
# does not defer to the database's ON DELETE rules unless every relationship is declared
# `passive_deletes=True` — instead it loads the children and NULLS their foreign keys:
#
#     UPDATE resume_files SET user_id=NULL WHERE resume_files.id = ...
#     null value in column "user_id" of relation "resume_files" violates not-null constraint
#
# So the endpoint 500'd and nothing was deleted, which is exactly what was reported: accounts
# still listed after being deleted. The FK rules were correct all along; the ORM never let them
# run. Every check above — the ordering, the confirmation, the audit, the refusals — was true of
# code that could not delete anybody.
#
# THE DETAIL THAT MADE IT INVISIBLE: a user with no resume, no session and no ledger rows has no
# children to nullify, so the ORM path succeeds. A first attempt at this test used exactly such
# a user and passed. Any REAL account has all three, which is why it failed for every real one.
#
# So this test builds the FULL graph — session, per-session question, answer, score, report,
# resume, plan, ledger row — and asserts the rows are gone afterwards. A thin fixture here is
# not a weaker test, it is a test of a different code path.


@pytest.mark.asyncio
class TestItDeletesARealAccountWithHistory:
    @pytest.fixture
    async def env(self):
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.billing import CreditEvent, UserPlan
        from app.models.company import Company, InterviewTrack, QuestionCategory
        from app.models.question import Question, Topic
        from app.models.report import Report, ResumeFile
        from app.models.session import Answer, InterviewSession, Score, SessionStatus
        from app.models.user import Profile, User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        admin_id, victim_id = uuid.uuid4(), uuid.uuid4()
        sid, qid, aid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        email = f"vic-{victim_id}@example.test"

        async with AsyncSessionFactory() as db:
            company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(
                id=uuid.uuid4(), company_id=company.id, name="T", slug=f"t-{uuid.uuid4().hex[:8]}"
            )
            db.add_all([
                company,
                track,
                User(id=admin_id, supabase_uid=str(admin_id), email=f"adm-{admin_id}@example.test",
                     is_active=True, is_admin=True),
                User(id=victim_id, supabase_uid=str(victim_id), email=email,
                     is_active=True, is_admin=False),
            ])
            await db.flush()
            cat = QuestionCategory(
                id=uuid.uuid4(), track_id=track.id, name="Cat", slug=f"cat-{uuid.uuid4().hex[:6]}"
            )
            db.add(cat)
            await db.flush()
            topic = Topic(
                id=uuid.uuid4(), category_id=cat.id, name="T", slug=f"tp-{uuid.uuid4().hex[:6]}"
            )
            db.add(topic)
            await db.flush()
            db.add_all([
                Profile(user_id=victim_id, full_name="Victim", timezone="UTC"),
                InterviewSession(
                    id=sid, user_id=victim_id, track_id=track.id, status=SessionStatus.COMPLETED
                ),
            ])
            await db.flush()
            # A per-session question, which is what makes `answers -> questions` (NO ACTION)
            # part of the graph rather than a detail nobody exercises.
            db.add(
                Question(id=qid, topic_id=topic.id, session_id=sid, content="Q?",
                         difficulty="medium", question_type="conceptual")
            )
            await db.flush()
            db.add(Answer(id=aid, session_id=sid, question_id=qid, content="A."))
            await db.flush()
            db.add_all([
                Score(session_id=sid, answer_id=aid, technical_score=7.0, communication_score=7.0,
                      completeness_score=7.0, confidence_score=7.0, overall_score=7.0,
                      strengths=[], weaknesses=[], feedback="ok"),
                Report(session_id=sid, user_id=victim_id, overall_score=70.0,
                       overall_score_label="ok", executive_summary="s",
                       readiness_level="close_to_ready", strengths=[], weaknesses=[],
                       topic_scores={}, improvement_roadmap=[], raw_report={}),
                # THE ROW THAT BROKE IT: user_id is NOT NULL, so the ORM's nullify attempt is
                # an immediate IntegrityError.
                ResumeFile(user_id=victim_id, filename="cv.pdf",
                           storage_path=f"resumes/{victim_id}/x/cv.pdf",
                           file_size_bytes=100, mime_type="application/pdf", is_primary=True),
                UserPlan(user_id=victim_id, source="signup"),
                CreditEvent(created_at=datetime.now(UTC), user_id=victim_id, feature="interview",
                            kind="consume", delta=-1, session_id=sid,
                            detail={"paid_with": "trial"}),
            ])
            await db.commit()

        token = jwt.encode(
            {
                "sub": str(admin_id),
                "email": f"adm-{admin_id}@example.test",
                "aud": "authenticated",
                "exp": datetime.now(UTC) + timedelta(days=1),
                "iat": datetime.now(UTC),
            },
            settings.SUPABASE_JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        return {
            "victim_id": victim_id,
            "email": email,
            "session_id": sid,
            "question_id": qid,
            "answer_id": aid,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    async def _delete(self, env, *, confirm: str | None = None):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.post(
                f"/api/v1/admin/users/{env['victim_id']}/delete",
                json={"confirm_email": confirm if confirm is not None else env["email"],
                      "reason": "test"},
                headers=env["headers"],
            )

    async def test_an_account_with_a_full_history_is_actually_deleted(self, env):
        """
        THE TEST THAT CATCHES THE ORM-NULLIFY BUG. A 500 here, or a surviving user row, is the
        reported failure.
        """
        resp = await self._delete(env)
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] is True

        from sqlalchemy import func as sql_func

        from app.db.session import AsyncSessionFactory
        from app.models.user import User

        async with AsyncSessionFactory() as db:
            assert await db.scalar(
                select(sql_func.count()).select_from(User).where(User.id == env["victim_id"])
            ) == 0, "the user row survived a successful-looking deletion"

    async def test_the_whole_graph_goes_with_it(self, env):
        """
        "Permanently" means the interview history too. Checked per table rather than by trusting
        the declared cascades, because the ORM bug above proved that correct FK rules can be
        bypassed entirely by the layer above them.
        """
        assert (await self._delete(env)).status_code == 200

        from sqlalchemy import func as sql_func

        from app.db.session import AsyncSessionFactory
        from app.models.billing import CreditEvent, UserPlan
        from app.models.question import Question
        from app.models.report import Report, ResumeFile
        from app.models.session import Answer, InterviewSession

        async with AsyncSessionFactory() as db:
            checks = {
                "interview_sessions": select(sql_func.count())
                .select_from(InterviewSession)
                .where(InterviewSession.id == env["session_id"]),
                "questions": select(sql_func.count())
                .select_from(Question)
                .where(Question.id == env["question_id"]),
                "answers": select(sql_func.count())
                .select_from(Answer)
                .where(Answer.id == env["answer_id"]),
                "reports": select(sql_func.count())
                .select_from(Report)
                .where(Report.session_id == env["session_id"]),
                "resume_files": select(sql_func.count())
                .select_from(ResumeFile)
                .where(ResumeFile.user_id == env["victim_id"]),
                "credit_events": select(sql_func.count())
                .select_from(CreditEvent)
                .where(CreditEvent.user_id == env["victim_id"]),
                "user_plans": select(sql_func.count())
                .select_from(UserPlan)
                .where(UserPlan.user_id == env["victim_id"]),
            }
            leftovers = {name: await db.scalar(stmt) for name, stmt in checks.items()}
        assert leftovers == dict.fromkeys(checks, 0), f"orphaned rows survived: {leftovers}"

    async def test_the_audit_entry_outlives_the_account(self, env):
        assert (await self._delete(env)).status_code == 200

        from sqlalchemy import func as sql_func

        from app.db.session import AsyncSessionFactory
        from app.models.system import AuditLog

        async with AsyncSessionFactory() as db:
            surviving = await db.scalar(
                select(sql_func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == env["victim_id"],
                       AuditLog.action == "admin.user_deleted")
            )
        assert surviving >= 1, "the only remaining record of the account was deleted with it"

    async def test_a_wrong_confirmation_deletes_nothing(self, env):
        resp = await self._delete(env, confirm="someone.else@example.test")
        assert resp.status_code == 400

        from sqlalchemy import func as sql_func

        from app.db.session import AsyncSessionFactory
        from app.models.user import User

        async with AsyncSessionFactory() as db:
            assert await db.scalar(
                select(sql_func.count()).select_from(User).where(User.id == env["victim_id"])
            ) == 1, "a refused deletion still removed the account"
