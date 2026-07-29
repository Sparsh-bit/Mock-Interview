import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import get_db
from app.models.session import InterviewSession
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
    track_id: uuid.UUID
    company: str = ""
    program: str = ""
    prompt: str = ""
    resume_text: str = ""

class DeliveryMetrics(BaseModel):
    filler_count: int = 0
    pause_count: int = 0
    total_pause_seconds: int = 0
    words: int = 0
    speaking_seconds: int = 0

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
    resume_context = await _resolve_resume_context(db, current_user.user_id, request.resume_text)

    orchestrator = InterviewOrchestrator(db)
    plan = await orchestrator.create_plan(
        current_user.user_id,
        request.track_id,
        request.company,
        request.program,
        request.prompt,
        resume_context,
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
    return {
        "question": {
            "id": question.id,
            "content": question.content,
            "type": question.question_type,
            "difficulty": question.difficulty
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
