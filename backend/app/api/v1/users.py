"""
User Endpoints — api/v1/users.py

GET    /api/v1/users/me/profile          — Get current user's extended profile
PATCH  /api/v1/users/me/profile          — Update profile
GET    /api/v1/users/me/stats            — Get interview statistics
GET    /api/v1/users/me/sessions         — Get session history (paginated)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import AsyncSession, get_db
from app.models.session import InterviewSession
from app.models.user import Profile
from app.services.interview.orchestrator import MAX_SESSION_SECONDS

logger = structlog.get_logger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    bio: str | None = None
    target_company: str | None = None
    experience_years: int | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    #: Profile picture. Editable so the field the profile page shows actually
    #: persists; it was previously read-only, so any value the UI sent was
    #: silently dropped.
    avatar_url: str | None = None
    timezone: str | None = None


class ProfileResponse(BaseModel):
    user_id: uuid.UUID
    full_name: str | None
    avatar_url: str | None
    bio: str | None
    target_company: str | None
    experience_years: int | None
    linkedin_url: str | None
    github_url: str | None
    timezone: str
    updated_at: datetime


class UserStatsResponse(BaseModel):
    total_sessions: int
    completed_sessions: int
    average_score: float | None
    total_questions_answered: int
    hours_practiced: float
    best_score: float | None
    streak_days: int


class SessionSummaryResponse(BaseModel):
    id: uuid.UUID
    track_name: str
    company_name: str
    program: str | None = None
    topics: list[str] = []
    status: str
    mode: str
    questions_asked: int
    overall_score: float | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: int | None


# ─── Endpoints ────────────────────────────────────────────────────────────────


#: Authenticated reads. Shared namespace with /progress, because a client hammering the
#: dashboard hits several of these together and they should draw on one budget rather than
#: each getting its own.
_read_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_READ_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_read(user_id),
    action="loading your account",
)


@router.get(
    "/me/profile", response_model=ProfileResponse,
    dependencies=[Depends(_read_rate_limit)],
)
async def get_profile(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.user_id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        from fastapi import HTTPException  # noqa
        raise HTTPException(status_code=404, detail="Profile not found")

    return ProfileResponse(
        user_id=profile.user_id,
        full_name=profile.full_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        target_company=profile.target_company,
        experience_years=profile.experience_years,
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        timezone=profile.timezone,
        updated_at=profile.updated_at,
    )


@router.patch(
    "/me/profile",
    response_model=ProfileResponse,
    dependencies=[Depends(_read_rate_limit)],
)
async def update_profile(
    body: UpdateProfileRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.user_id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        from fastapi import HTTPException  # noqa
        raise HTTPException(status_code=404, detail="Profile not found")

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)

    logger.info("profile_updated", user_id=str(current_user.user_id))

    return ProfileResponse(
        user_id=profile.user_id,
        full_name=profile.full_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        target_company=profile.target_company,
        experience_years=profile.experience_years,
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        timezone=profile.timezone,
        updated_at=profile.updated_at,
    )


async def _streak_days(db: AsyncSession, user_id: uuid.UUID) -> int:
    """
    Consecutive days, ending today or yesterday, with at least one completed
    session.

    This was `streak_days=0,  # Phase 9: implement streak calculation` — a
    hardcoded zero dressed up as a metric. A streak that never moves is worse
    than no streak at all: it is the one number on the dashboard whose entire
    purpose is to say "you are building a habit", and it said "you are not"
    to everybody, permanently.

    Counting from today OR yesterday is deliberate. Anchoring only on today would
    reset everyone's streak at midnight, before they have had any chance to
    practise — so somebody with a fourteen-day run would open the app in the
    morning and be told zero.

    Days are UTC. That is wrong by up to a few hours for a candidate in IST, and
    it is the right trade for now: the alternative needs the user's timezone
    threaded into this query, and a streak that is occasionally a day generous is
    better than one that is occasionally a day punitive.
    """
    rows = await db.scalars(
        select(func.date(InterviewSession.completed_at))
        .where(
            InterviewSession.user_id == user_id,
            InterviewSession.status == "completed",
            InterviewSession.completed_at.isnot(None),
        )
        .distinct()
    )
    days = sorted({d for d in rows if d is not None}, reverse=True)
    if not days:
        return 0

    today = datetime.now(UTC).date()
    if (today - days[0]).days > 1:
        return 0

    streak = 1
    for newer, older in zip(days, days[1:], strict=False):
        if (newer - older).days != 1:
            break
        streak += 1
    return streak


#: What counts as an interview the candidate actually SAT.
#:
#: ONE DEFINITION, USED BY EVERY READ ON THE DASHBOARD. There used to be two, and the
#: dashboard showed both at once: the stat cards counted every InterviewSession row while
#: the history list below them hid the ones that were never answered. Since `create_plan`
#: creates a session on every setup attempt, a candidate who opened the setup form twenty
#: times and finished nothing saw "23 sessions, 15.8 hours practised" directly above "No
#: sessions yet".
#:
#: Numbers that contradict the list beside them do not read as a counting bug. They read as
#: somebody else's data, which is exactly how it was reported.
#:
#: An abandoned plan is not practice: nothing was asked, nothing was answered, and the
#: elapsed wall-clock time is the candidate walking away from a form.
def _real_session() -> ColumnElement[bool]:
    from app.models.session import InterviewSession  # noqa: PLC0415

    return or_(
        InterviewSession.questions_asked > 0,
        InterviewSession.status == "completed",
    )


@router.get(
    "/me/stats", response_model=UserStatsResponse,
    dependencies=[Depends(_read_rate_limit)],
)
async def get_stats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Aggregate interview performance statistics for the current user."""
    from sqlalchemy import case  # noqa: PLC0415

    from app.models.report import Report  # noqa: PLC0415
    from app.models.session import Answer  # noqa: PLC0415

    # Session counts
    sessions_result = await db.execute(
        select(
            func.count(InterviewSession.id).label("total"),
            func.count(
                case((InterviewSession.status == "completed", InterviewSession.id))
            ).label("completed"),
            # Prefer the stored duration, and fall back to the timestamps for
            # sessions completed before it was being written — which is every
            # session that existed when this was fixed. Without the fallback the
            # dashboard would keep reporting 0 hours until a user completed a
            # brand-new interview, and the history they already have would never
            # be counted at all.
            func.sum(
                func.coalesce(
                    InterviewSession.duration_seconds,
                    func.least(
                        func.extract(
                            "epoch",
                            InterviewSession.completed_at - InterviewSession.started_at,
                        ),
                        MAX_SESSION_SECONDS,
                    ),
                    0,
                )
            ).label("total_seconds"),
        ).where(InterviewSession.user_id == current_user.user_id, _real_session())
    )
    session_row = sessions_result.one()

    # Questions answered comes from Answer rows, NOT Score rows. Per-answer
    # scoring was moved to report generation, so no Score row is ever written
    # any more — counting them made analytics permanently report zero.
    answers_result = await db.execute(
        select(func.count(Answer.id))
        .join(InterviewSession, Answer.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == current_user.user_id, _real_session())
    )
    total_answers = answers_result.scalar() or 0

    # Scores now live on the generated Report (0-100), which the UI shows on a
    # 0-100 scale, so no rescaling here.
    reports_result = await db.execute(
        select(
            func.avg(Report.overall_score).label("avg_score"),
            func.max(Report.overall_score).label("best_score"),
        )
        .join(InterviewSession, Report.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == current_user.user_id, _real_session())
    )
    score_row = reports_result.one()

    total_seconds = session_row.total_seconds or 0
    hours = round(total_seconds / 3600, 1)

    return UserStatsResponse(
        total_sessions=session_row.total or 0,
        completed_sessions=session_row.completed or 0,
        # `is not None`, not truthiness: a genuine average of 0.0 is a real
        # score — the lowest one — and rendering it as "—" tells a candidate who
        # scored zero that they have not been scored yet.
        average_score=round(score_row.avg_score, 2) if score_row.avg_score is not None else None,
        total_questions_answered=total_answers,
        hours_practiced=hours,
        best_score=round(score_row.best_score, 2) if score_row.best_score is not None else None,
        streak_days=await _streak_days(db, current_user.user_id),
    )


@router.get(
    "/me/sessions", response_model=list[SessionSummaryResponse],
    dependencies=[Depends(_read_rate_limit)],
)
async def get_session_history(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=10, le=50),
    offset: int = Query(default=0, ge=0),
):
    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.report import Report  # noqa: PLC0415

    result = await db.execute(
        select(
            InterviewSession,
            InterviewTrack.name.label("track_name"),
            Company.name.label("company_name"),
            Report.overall_score.label("overall_score"),
        )
        .join(InterviewTrack, InterviewSession.track_id == InterviewTrack.id)
        .join(Company, InterviewTrack.company_id == Company.id)
        .outerjoin(Report, Report.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == current_user.user_id)
        # The same definition the stat cards use — see _real_session. Two copies of this
        # predicate is how the cards and this list came to disagree.
        .where(_real_session())
        .order_by(InterviewSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = result.all()

    summaries: list[SessionSummaryResponse] = []
    for row in rows:
        # Prefer the company/program the candidate actually chose in setup
        # (stored on the session) over the generic track name, so each interview
        # is named for what it really was.
        meta = row.InterviewSession.session_metadata or {}
        meta_company = (meta.get("company") or "").strip()
        meta_program = (meta.get("program") or "").strip()
        topics = meta.get("topics") or []
        summaries.append(
            SessionSummaryResponse(
                id=row.InterviewSession.id,
                track_name=meta_program or row.track_name,
                company_name=meta_company or row.company_name,
                program=meta_program or None,
                topics=topics if isinstance(topics, list) else [],
                status=row.InterviewSession.status,
                mode=row.InterviewSession.mode,
                questions_asked=row.InterviewSession.questions_asked,
                overall_score=row.overall_score,
                started_at=row.InterviewSession.started_at,
                completed_at=row.InterviewSession.completed_at,
                duration_seconds=row.InterviewSession.duration_seconds,
            )
        )
    return summaries


# ══════════════════════════════════════════════════════════════════════════════════════════
# WHAT A PERSON CAN DO WITH THEIR OWN DATA
#
# Both of these existed only as admin actions, which meant the answer to "can I leave?" and
# "what do you hold on me?" was "email someone and hope". DPDP §11 and §12 make them rights
# rather than courtesies, and they are also the plainest kind of user experience: an account
# somebody cannot leave is one they were never fully in control of.
#
# THE DELETION REUSES THE ADMIN PATH RATHER THAN REIMPLEMENTING IT. That path is tested and
# carries two hard-won details — a Core DELETE so the database cascade runs (the ORM NULLs
# children instead and 500s on any NOT NULL column), and Supabase auth removed BEFORE our rows,
# because a working login attached to no data silently recreates the account on next sign-in.
# A second implementation would have neither.
# ══════════════════════════════════════════════════════════════════════════════════════════


class ExportedData(BaseModel):
    """Everything held about one account, as the person themselves may read it."""

    exported_at: datetime
    account: dict
    profile: dict | None
    sessions: list[dict]
    reports: list[dict]
    resumes: list[dict]
    payments: list[dict]
    feedback: list[dict]
    #: Named plainly, because §5 requires telling people who their data is shared with and a
    #: list they have to infer is not a disclosure.
    shared_with: list[str]
    #: Every consent answer, including the purposes never asked. DPDP §11 gives a right
    #: to a summary of the data held, and "what did I agree to" is the part of that a
    #: person is most likely to actually want.
    consents: list[dict]


@router.get("/me/export", summary="Everything we hold about you")
async def export_my_data(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ExportedData:
    """
    One JSON document containing this account's data.

    SCOPED TO THE CALLER BY THE TOKEN, never by a parameter. There is deliberately no
    `user_id` argument — an export endpoint that accepted one would be the single most
    valuable IDOR in the product, returning another candidate's resume, transcript and
    assessment in one request.

    WHAT IS DELIBERATELY NOT HERE: the answer keys. `questions.ideal_answer` belongs to the
    question bank rather than to the candidate, and an export is a supported way to read every
    one of them if it carries the questions in full. The candidate's OWN answers are included;
    what a good answer would have been is not.

    RAW ROWS RATHER THAN A RENDERED REPORT, because the purpose is portability — somebody
    should be able to read it, or hand it to another service, without this product's UI.
    """
    from app.models.billing import CreditEvent
    from app.models.report import Report, ResumeFile
    from app.models.session import Answer, InterviewFeedback
    from app.models.user import Profile, User
    from app.services.legal.consent import summary as consent_summary
    from app.services.legal.disclosure import active_processors

    uid = current_user.user_id

    user = await db.scalar(select(User).where(User.id == uid))
    profile = await db.scalar(select(Profile).where(Profile.user_id == uid))

    sessions = (
        await db.execute(
            select(InterviewSession).where(InterviewSession.user_id == uid)
        )
    ).scalars().all()

    # The candidate's own words, joined through their sessions — `answers` has no user_id.
    answers = (
        await db.execute(
            select(Answer, InterviewSession.id)
            .join(InterviewSession, Answer.session_id == InterviewSession.id)
            .where(InterviewSession.user_id == uid)
        )
    ).all()
    answers_by_session: dict[str, list[dict]] = {}
    for answer, session_id in answers:
        answers_by_session.setdefault(str(session_id), []).append(
            {
                "answered_at": answer.created_at.isoformat() if answer.created_at else None,
                "answer": answer.content,
            }
        )

    reports = (
        await db.execute(select(Report).where(Report.user_id == uid))
    ).scalars().all()
    resumes = (
        await db.execute(select(ResumeFile).where(ResumeFile.user_id == uid))
    ).scalars().all()
    payments = (
        await db.execute(select(CreditEvent).where(CreditEvent.user_id == uid))
    ).scalars().all()
    feedback = (
        await db.execute(select(InterviewFeedback).where(InterviewFeedback.user_id == uid))
    ).scalars().all()

    logger.info("user_exported_their_data", user_id=str(uid))

    return ExportedData(
        exported_at=datetime.now(UTC),
        account={
            "email": user.email if user else current_user.email,
            "joined_at": user.created_at.isoformat() if user and user.created_at else None,
        },
        profile=(
            {
                "full_name": profile.full_name,
                "bio": profile.bio,
                "target_company": profile.target_company,
                "experience_years": profile.experience_years,
                "linkedin_url": profile.linkedin_url,
                "github_url": profile.github_url,
                "timezone": profile.timezone,
            }
            if profile
            else None
        ),
        sessions=[
            {
                "id": str(s.id),
                "status": str(s.status),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "your_answers": answers_by_session.get(str(s.id), []),
            }
            for s in sessions
        ],
        reports=[
            {
                "session_id": str(r.session_id),
                "overall_score": _as_float_or_none(r.overall_score),
                "readiness_level": r.readiness_level,
                "summary": r.executive_summary,
                "strengths": r.strengths,
                "weaknesses": r.weaknesses,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        resumes=[
            {
                "filename": r.filename,
                "uploaded_at": r.created_at.isoformat() if r.created_at else None,
                # The extracted TEXT is theirs and is included; the storage path is an internal
                # location and tells them nothing useful.
                "extracted_text": getattr(r, "extracted_text", None),
            }
            for r in resumes
        ],
        payments=[
            {
                "at": p.created_at.isoformat() if p.created_at else None,
                "feature": p.feature,
                "kind": p.kind,
                "change": p.delta,
            }
            for p in payments
        ],
        feedback=[
            {
                "session_id": str(f.session_id),
                "stars": f.stars,
                "comment": f.comment,
            }
            for f in feedback
        ],
        # DERIVED, NOT WRITTEN OUT. This list used to be five hardcoded strings, and
        # they had already drifted: it described ZhipuAI as the "standby" provider
        # when AI_PROVIDER defaults to `glm`, i.e. ZhipuAI is the PRIMARY one and the
        # resume goes there first. A §5 disclosure that names the wrong recipient is
        # worse than none, because it is a statement the candidate relied on.
        # services/legal/disclosure.py reads the same settings the request path reads.
        shared_with=[
            f"{p.name} ({p.country}) — {p.purpose}" for p in active_processors()
        ],
        consents=await consent_summary(db, uid),
    )


def _as_float_or_none(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class DeleteAccountRequest(BaseModel):
    """Typing your own email is the confirmation."""

    #: THE CONFIRMATION IS THEIR EMAIL, NOT A CHECKBOX. This is irreversible and removes the
    #: interviews, reports and resumes they paid for — a misclick must not be able to do it,
    #: and a checkbox is one misclick.
    confirm_email: str


@router.post("/me/delete", summary="Delete your account and everything in it")
async def delete_my_account(
    request: DeleteAccountRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Delete the calling account. Irreversible.

    POST RATHER THAN DELETE, because a body is required for the confirmation and proxies and
    some HTTP clients drop bodies on DELETE — the same reason the admin route is a POST.

    NO `user_id` PARAMETER ANYWHERE. The account deleted is the one the token names. An
    endpoint that took an id would be a way to delete somebody else.

    THE ORDER MATTERS AND IS NOT ARBITRARY: the Supabase login, then the files, then our rows.
    Removing our rows first would leave a working login attached to nothing, and the next
    sign-in would recreate the account as though the deletion never happened. Failing to
    remove the login is therefore fatal to the whole operation rather than tolerated — and
    because it is fatal, nothing destructive may happen before it, or the refusal lies about
    what has already been lost.
    """
    from fastapi import HTTPException
    from sqlalchemy import delete as sa_delete

    from app.api.v1.admin import _delete_stored_files, _delete_supabase_user
    from app.models.user import User
    from app.services.legal.retention import deidentify_retained_records

    user = await db.scalar(select(User).where(User.id == current_user.user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    if request.confirm_email.strip().lower() != (user.email or "").strip().lower():
        raise HTTPException(
            status_code=400,
            detail="Type your account email exactly to confirm deletion.",
        )

    supabase_uid = user.supabase_uid

    # THE LOGIN GOES FIRST, AND THE FILES ONLY ONCE IT IS GONE.
    #
    # This used to delete the stored resumes first and then, if the Supabase call failed,
    # raise a 502 saying "Nothing has been deleted". That sentence was false: the CVs were
    # already gone from the bucket, and because `get_db` rolls the transaction back on the
    # exception, the `resume_files` rows survived pointing at objects that no longer existed.
    # A person who retried then saw a resume listed that could not be downloaded, and the
    # message had told them nothing had happened.
    #
    # Deleting the login first makes the failure path honest — a 502 now genuinely means
    # nothing was removed — and costs nothing, because `_delete_stored_files` reads the file
    # paths out of rows this function has not deleted yet.
    #
    # The ordering constraint that motivated the original note is unchanged and is the reason
    # this cannot simply be reordered the other way: our ROWS must go after the login, or the
    # next sign-in silently recreates the account. Files are not part of that constraint.
    if not await _delete_supabase_user(supabase_uid):
        raise HTTPException(
            status_code=502,
            detail="Could not remove your login. Nothing has been deleted — please try again.",
        )

    files_removed = await _delete_stored_files(db, user.id)

    # ── WHAT SURVIVES, AND WHY IT HAS TO ─────────────────────────────────────
    #
    # BEFORE the delete, not after: `credit_events`, `offer_redemptions` and
    # `consent_events` are ON DELETE SET NULL since migration 023, so the moment the
    # user row goes their `user_id` is NULL and there is nothing left to match on.
    #
    # These are financial and evidential records. The Companies Act §128(5) requires
    # eight financial years of books and DPDP §8(7) makes erasure yield to a
    # retention obligation under another law, so the previous behaviour — cascading
    # them away — destroyed records the business is required to hold, silently, on a
    # path the user triggers themselves. It also made a single-use offer code
    # reusable by deleting and re-registering.
    #
    # Retaining them still identified would be a rename of the problem rather than a
    # fix, so the identity is replaced by a salted one-way digest: the amounts and
    # dates remain, the person does not. Same transaction as the delete, so it is
    # both or neither.
    #
    # The resume, its text, the file, every answer, transcript, score and report are
    # NOT retained. They are the sensitive data, nothing requires keeping them, and
    # they cascade away exactly as before.
    retained = await deidentify_retained_records(db, current_user.user_id)

    # A CORE DELETE so the database's ON DELETE CASCADE runs. `db.delete(user)` goes through
    # the ORM, which NULLs children rather than deferring to the database and raises on any
    # NOT NULL column — this is exactly what made account deletion 500 before.
    await db.execute(sa_delete(User).where(User.id == current_user.user_id))
    db.expunge(user)

    logger.warning(
        "user_deleted_their_own_account",
        user_id=str(current_user.user_id),
        resume_files_removed=files_removed,
        retained_deidentified=retained,
    )
    return {
        "deleted": True,
        "resume_files_removed": files_removed,
        # Told to the user, not just logged. Somebody exercising an erasure right is
        # entitled to know that the financial records do not go, and why.
        "retained_deidentified": retained,
        "retention_note": (
            "Payment and credit records are kept for 8 years as company law requires, "
            "with your identity removed from them. Everything else is gone."
        ),
    }
