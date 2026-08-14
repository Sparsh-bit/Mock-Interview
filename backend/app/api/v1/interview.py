import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import get_db
from app.models.session import InterviewSession
from app.services.billing.credits import consume
from app.services.interview.orchestrator import InterviewOrchestrator

logger = structlog.get_logger(__name__)

router = APIRouter()

_interview_start_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_INTERVIEW_PER_HOUR,
    window_seconds=3600,
    key_builder=lambda user_id: CacheKeys.rate_limit_interview(user_id),
    action="starting an interview session",
)

_ai_answer_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_ai(user_id),
    action="submitting an answer",
)


async def _verify_session_ownership(
    db: AsyncSession, session_id: uuid.UUID, current_user: CurrentUser
) -> None:
    """Ensure the session belongs to the current user, else 404."""
    result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == current_user.user_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Session not found")

class StartSessionRequest(BaseModel):
    track_id: uuid.UUID

class PlanRequest(BaseModel):
    #: Required because InterviewSession.track_id is a non-null foreign key. On a custom
    #: setup it is a CARRIER ONLY — see `custom_setup` — and nothing about the interview is
    #: derived from it.
    track_id: uuid.UUID
    company: str = ""
    program: str = ""
    #: True when the candidate typed their own employer instead of picking one from the
    #: catalogue.
    #:
    #: THIS IS WHAT STOPS A SALES INTERVIEW BEING AN ACCENTURE ONE. The form must send a
    #: track_id whatever happens, so without this flag the backend cannot tell "they chose
    #: Cognizant Java FSE" from "they typed Morani Plastics and the chip was left selected
    #: from before". Those look identical on the wire and mean opposite things.
    #:
    #: When it is true the track is not consulted for the role, the company, the domain or
    #: whether the interview is technical — only what the candidate typed counts.
    custom_setup: bool = False
    prompt: str = ""
    resume_text: str = ""

class PauseMark(BaseModel):
    """Where a pause fell, as a word offset into the answer."""

    #: Index of the word the pause preceded, so the transcript can be rendered
    #: with the hesitation shown in position rather than as a bare count.
    wordIndex: int = 0  # noqa: N815 - matches the browser payload exactly
    seconds: int = 0


class DeliveryMetrics(BaseModel):
    filler_count: int = 0
    pause_count: int = 0
    total_pause_seconds: int = 0
    words: int = 0
    speaking_seconds: int = 0
    #: Individual pauses. Bounded so a pathological client cannot post an
    #: unbounded array into a JSONB column.
    pauses: list[PauseMark] = Field(default_factory=list, max_length=200)
    #: Language that would end a real interview, and the words themselves.
    #: Distinct from filler_count because they are different mistakes needing
    #: different advice: a filler is a habit, this is one event that costs the
    #: offer. Casual language ("damn") is deliberately NOT counted here — see
    #: CASUAL_WORDS in frontend/src/lib/speech/delivery.ts.
    unprofessional_count: int = 0
    unprofessional_words: list[str] = Field(default_factory=list, max_length=40)

class SubmitAnswerRequest(BaseModel):
    question_id: uuid.UUID
    content: str
    delivery: DeliveryMetrics | None = None

@router.post(
    "/start",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_interview_start_rate_limit)],
)
async def start_interview_session(
    request: StartSessionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    orchestrator = InterviewOrchestrator(db)
    session = await orchestrator.start_session(current_user.user_id, request.track_id)
    # Charged in the SAME transaction as the session that was created, so a failure after
    # this point rolls the charge back with it. `get_db` owns the commit — it commits on
    # success and rolls back on any exception — which is what makes this atomic rather than
    # merely careful.
    #
    # Both this and /plan charge, and that is correct rather than a double charge: create_plan
    # builds its own session, so these are two independent ways to begin one interview, not
    # two steps of the same one.
    await consume(db, current_user.user_id, "interview", session_id=session.id)
    return {"session_id": session.id, "status": session.status}

@router.post(
    "/plan",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_interview_start_rate_limit)],
)
async def plan_interview(
    request: PlanRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Generate a company/program-tailored interview plan for the candidate to review."""
    # CHARGED BEFORE THE GENERATION, NOT AFTER.
    #
    # This endpoint is the single most expensive call in the product — the plan is ~$0.065 and
    # it is the gateway to the report, which is another ~$0.135. Charging afterwards would
    # mean an exhausted user still pays us for the generation before being told no, which is
    # the one ordering that costs money to refuse.
    #
    # Safe to charge first because create_plan runs in this same transaction: if generation
    # fails, the rollback takes the charge with it and the candidate is not billed for an
    # interview they never got.
    await consume(db, current_user.user_id, "interview")

    resume_context = await _resolve_resume_context(db, current_user.user_id, request.resume_text)

    orchestrator = InterviewOrchestrator(db)
    plan = await orchestrator.create_plan(
        current_user.user_id,
        request.track_id,
        request.company,
        request.program,
        request.prompt,
        resume_context,
        custom_setup=request.custom_setup,
    )
    return plan


async def _resolve_resume_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    pasted_text: str,
) -> str:
    """
    Decide what the planner is told about the candidate's resume.

    Uploaded resumes have to work without the candidate re-pasting anything —
    that is the whole point of storing one — so this falls back to their active
    resume whenever the request does not carry text of its own.

    Text pasted into the setup form still wins. It is a deliberate, per-interview
    choice ("today I want to be asked about this"), and silently overriding it with
    a months-old stored file would be the more surprising behaviour.

    Prefers the structured analysis over the raw text because it names specific
    projects and separates real claims from passing mentions, which is what lets
    the interviewer ask "you listed <project> — how did you handle X there?"
    instead of something generic. Falls back to raw text when analysis is
    missing, so an interview is still personalised either way.
    """
    from app.models.report import ResumeFile  # noqa: PLC0415
    from app.services.ai.schemas import ResumeAnalysisResponse  # noqa: PLC0415
    from app.services.resume.analyser import build_interview_context  # noqa: PLC0415

    if pasted_text.strip():
        return pasted_text

    resume = await db.scalar(
        select(ResumeFile)
        .where(ResumeFile.user_id == user_id, ResumeFile.is_primary.is_(True))
        .order_by(ResumeFile.created_at.desc())
        .limit(1)
    )
    if resume is None or not resume.parsed_text:
        return ""

    analysis: ResumeAnalysisResponse | None = None
    if resume.interview_focus or resume.parsed_skills or resume.parsed_projects:
        # Rebuilt from the stored columns rather than re-running the analyser: the
        # work was already paid for at upload time.
        try:
            analysis = ResumeAnalysisResponse.model_validate(
                {
                    "skills": [{"name": name} for name in (resume.parsed_skills or [])],
                    "projects": resume.parsed_projects or [],
                    "experience": resume.parsed_experience or {},
                    "interview_focus": resume.interview_focus or {},
                }
            )
        except ValidationError:
            # Stored analysis from an older shape — the raw text still works.
            logger.warning("stored_resume_analysis_unreadable", resume_id=str(resume.id))

    context = build_interview_context(analysis, resume.parsed_text)
    logger.info(
        "interview_using_stored_resume",
        resume_id=str(resume.id),
        analysed=analysis is not None,
        context_chars=len(context),
    )
    return context

@router.post("/{session_id}/approve")
async def approve_interview(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Approve the generated plan and begin the interview."""
    await _verify_session_ownership(db, session_id, current_user)
    orchestrator = InterviewOrchestrator(db)
    ok = await orchestrator.approve_plan(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="No plan found for this session.")
    return {"status": "active"}

class SelfRatingRequest(BaseModel):
    """
    What the candidate said when the panel asked them to rate themselves.

    Bounded 1-10 because that is how the panel asks it, and because an unbounded number is a
    dial rather than an answer.
    """

    rating: int = Field(ge=1, le=10)
    #: What they were asked to rate themselves ON, echoed back from the panel's question.
    #:
    #: Carried rather than assumed, because the panel now asks a sales candidate about sales
    #: and an HR candidate about HR — see _rating_subject in api/v1/panel.py. This used to be
    #: a bare `java_rating`, which stored a sales candidate's answer under the key "java":
    #: harmless while every interview was a Java interview and a straightforward lie
    #: afterwards, in the one record the report reads to judge them against their own claim.
    subject: str = Field(default="", max_length=80)
    #: Areas they said they are strongest in, in their own words. Free text, capped, and only
    #: ever used to STEER topic choice — never matched exactly, because "collections" and
    #: "Collections framework" and "DSA collections" are the same claim.
    strengths: list[str] = Field(default_factory=list, max_length=8)


@router.post("/{session_id}/self-rating")
async def set_self_rating(
    session_id: uuid.UUID,
    request: SelfRatingRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Record the candidate's own estimate of their Java level, and let it shape the interview.

    WHY THIS IS NOT SIMPLY "EASIER IF THEY SAY 3".

    A self-rating is a dial the candidate controls, and this product's entire credential
    value rests on the score being hard to game. If a low rating bought easy questions AND
    the score were computed the same way, the optimal play would be to claim 2/10 every time
    — which would make the number meaningless within a week of anyone noticing.

    So the rating moves TWO things in opposite directions, and that is the whole design:

      * It moves the QUESTIONS. Claim 8 and you get the harder end of the bank; claim 3 and
        you start on foundations. This is the part the candidate wants and it is real.
      * It moves the EXPECTATION the answers are judged against, and it is recorded on the
        session so the report says what was claimed. Clearing a foundation set after
        claiming 3/10 is not the same achievement as clearing it after claiming 9/10, and
        the report is required to know which happened.

    The result is that honesty is the dominant strategy in both directions. Underclaiming
    gets you questions you find easy and a report that says you were asked easy questions.
    Overclaiming gets you questions you cannot answer and a harsher read when you miss them.
    Neither is a shortcut, which is what makes the rating safe to hand the candidate.

    Stored in session_metadata rather than its own column: it is per-session context that only
    the plan and the report read, and it costs a migration to add a column for something no
    query ever filters on.
    """
    await _verify_session_ownership(db, session_id, current_user)

    session = (
        await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))
    ).scalar_one()

    meta = dict(session.session_metadata or {})
    meta["self_rating"] = {
        "rating": request.rating,
        "subject": (request.subject or "").strip()[:80],
        "strengths": [s.strip()[:60] for s in request.strengths if s.strip()][:8],
    }
    # Reassigned rather than mutated in place: JSONB columns are not tracked for in-place
    # mutation by SQLAlchemy, so `meta[...] = x` on the live dict would not be persisted.
    session.session_metadata = meta
    await db.commit()

    logger.info(
        "self_rating_recorded",
        session_id=str(session_id),
        rating=request.rating,
        subject=request.subject,
        strengths=len(meta["self_rating"]["strengths"]),
    )
    return {"status": "recorded", "self_rating": meta["self_rating"]}


class PivotRecordRequest(BaseModel):
    """A topic the candidate declined, and the one the panel offered instead."""

    declined_question: str = Field(default="", max_length=2000)
    offered_topic: str = Field(default="", max_length=120)
    accepted: bool = False


@router.post("/{session_id}/pivot")
async def record_pivot(
    session_id: uuid.UUID,
    request: PivotRecordRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Record that the candidate said they did not know something and was offered another topic.

    THIS IS THE ANTI-FARMING HALF OF THE PIVOT and it is the reason the pivot is safe to
    ship at all. Without it, "I don't know" would be a free instruction to serve easier
    questions, and the optimal strategy for a candidate chasing a rating would be to decline
    every hard question until the interview consisted only of foundations.

    Recording it makes that self-defeating. Every pivot is on the session, so the report
    counts them, and an interview with six pivots is visibly an interview where the candidate
    could not engage with six topics — which is what it was. A candidate who honestly did not
    know one thing has one pivot and it barely registers, which is also what it should be.

    Deliberately NOT a score penalty applied here. The declined question is already an
    unanswered question and is already scored as one; docking again would punish the same
    event twice, and punishing somebody for saying "I don't know" honestly rather than
    bluffing is exactly backwards for a product that detects bluffing.
    """
    await _verify_session_ownership(db, session_id, current_user)

    session = (
        await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))
    ).scalar_one()

    meta = dict(session.session_metadata or {})
    pivots = list(meta.get("pivots") or [])
    pivots.append(
        {
            "declined": request.declined_question[:2000],
            "offered": request.offered_topic[:120],
            "accepted": request.accepted,
        }
    )
    # Bounded. A stuck client looping this must not be able to grow one JSONB row without
    # limit — the cap is far above any real interview's question count.
    meta["pivots"] = pivots[:40]
    session.session_metadata = meta
    await db.commit()
    return {"status": "recorded", "pivots": len(meta["pivots"])}


@router.get("/{session_id}/next")
async def get_next_question(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _verify_session_ownership(db, session_id, current_user)
    orchestrator = InterviewOrchestrator(db)
    question = await orchestrator.get_next_question(session_id)
    if not question:
        return {"question": None, "message": "Session complete or no questions available."}

    # IS THIS A FOLLOW-UP TO WHAT THEY JUST SAID?
    #
    # The reported bug was "I cannot see the cross questions", and the feature was working
    # the whole time — it was just invisible. The orchestrator generates a follow-up after
    # every third answer, records its id on the session, and serves it as the next
    # question. This endpoint then returned it with the same four fields as any other, so
    # the client had no way to know, the panel delivered it through the generic `mid` stage
    # as though it were a new topic, and the one moment the interview is most obviously
    # listening to you looked exactly like the moments it is not.
    #
    # Read from the session's own record rather than inferred from the question row, because
    # `cross_question_ids` is what the orchestrator actually keys its own logic on — a second
    # derivation could disagree with it.
    # `session` cannot be None here — _verify_session_ownership above already 404s otherwise
    # — but the guard is kept rather than asserted away: this reads a label, and a label is
    # never worth an AttributeError inside a live interview.
    session = await db.get(InterviewSession, session_id)
    meta = (session.session_metadata or {}) if session else {}
    cross_ids = set(meta.get("cross_question_ids", []))

    return {
        "question": {
            "id": question.id,
            "content": question.content,
            "type": question.question_type,
            "difficulty": question.difficulty,
            "is_follow_up": str(question.id) in cross_ids,
        }
    }

@router.post("/{session_id}/answer", dependencies=[Depends(_ai_answer_rate_limit)])
async def submit_answer(
    session_id: uuid.UUID,
    request: SubmitAnswerRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _verify_session_ownership(db, session_id, current_user)
    orchestrator = InterviewOrchestrator(db)
    result = await orchestrator.submit_answer(
        session_id,
        request.question_id,
        request.content,
        delivery=request.delivery.model_dump() if request.delivery else None,
    )
    return result

@router.post("/{session_id}/complete")
async def complete_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _verify_session_ownership(db, session_id, current_user)
    orchestrator = InterviewOrchestrator(db)
    await orchestrator.complete_session(session_id)
    return {"message": "Session completed"}
