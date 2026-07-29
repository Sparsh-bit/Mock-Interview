"""
Detailed Analysis Endpoints — api/v1/analysis.py

GET  /api/v1/analysis/{session_id}                      — every question, the
                                                          candidate's verbatim
                                                          answer, and its delivery
POST /api/v1/analysis/{session_id}/answers/{answer_id}/model-answer
                                                        — generate (and cache) the
                                                          answer they should have
                                                          given

Split from reports.py deliberately. The report is one AI call producing one stored
document; this is a per-answer, on-demand surface with different caching and cost
behaviour, and folding it into the report would either bloat that call or entangle
two unrelated lifecycles.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import AsyncSession, get_db

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Output budget for one model answer.
#:
#: The prompt sizes the answer to the question (40 words for a definition, up to
#: ~260 for a design question), and the response also carries the gaps, the key
#: points and a verdict line. 900 tokens covers the largest shape with headroom.
#: Sized against the actual response rather than guessed — an undersized ceiling
#: truncates the JSON and the whole billed call is wasted.
_MODEL_ANSWER_MAX_TOKENS = 900

#: Wall-clock cap, well inside a managed host's ~100s gateway cut. A gateway 502
#: carries no CORS headers and reaches the browser as an opaque CORS error.
_MODEL_ANSWER_BUDGET_SECONDS = 45.0

#: Rate limit on model-answer generation.
#:
#: This is a BILLED call reachable by any authenticated user, one per answer, so
#: without a limit a single account could generate them in a loop and drain the
#: daily AI budget for everyone. The daily cap is the backstop; this is the door.
#: Shares the AI bucket so it cannot be used to sidestep the interview limits.
_model_answer_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_ai(user_id),
    action="generating an ideal answer",
)


# ─── Schemas ──────────────────────────────────────────────────────────────────


class PauseMarkOut(BaseModel):
    wordIndex: int  # noqa: N815 - matches the browser payload
    seconds: int


class AnswerDelivery(BaseModel):
    filler_count: int = 0
    pause_count: int = 0
    total_pause_seconds: int = 0
    words: int = 0
    speaking_seconds: int = 0
    pauses: list[PauseMarkOut] = []


class ModelAnswerOut(BaseModel):
    """The cached coaching for one answer."""

    model_answer: str
    what_was_missing: list[str] = []
    key_points: list[str] = []
    verdict_line: str = ""


class AnalysedAnswer(BaseModel):
    answer_id: uuid.UUID
    question_id: uuid.UUID
    question: str
    question_type: str
    topic: str
    #: Exactly what the candidate said or typed. Never cleaned up or re-punctuated:
    #: the point of this view is to show them their own words.
    answer: str
    answered_at: datetime
    delivery: AnswerDelivery | None = None
    #: Present once generated. Null means "not generated yet", not "unavailable" —
    #: the UI offers a button in that case rather than reporting a failure.
    model_answer: ModelAnswerOut | None = None
    is_coding: bool = False


class DetailedAnalysisResponse(BaseModel):
    session_id: uuid.UUID
    track_name: str
    company_name: str
    completed_at: datetime | None
    answers: list[AnalysedAnswer]


class ModelAnswerResult(ModelAnswerOut):
    answer_id: uuid.UUID
    #: True when served from cache — no AI call was made and nothing was billed.
    cached: bool = False


def _coerce_model_answer(raw: dict | None) -> ModelAnswerOut | None:
    """
    Read a cached coaching payload defensively.

    JSONB written by a previous app version may not match the current shape, and
    one bad row must not 500 the whole analysis view.
    """
    if not raw:
        return None
    text = raw.get("model_answer")
    if not isinstance(text, str) or not text.strip():
        return None

    def _strings(key: str) -> list[str]:
        value = raw.get(key)
        return [s for s in value if isinstance(s, str)] if isinstance(value, list) else []

    verdict = raw.get("verdict_line")
    return ModelAnswerOut(
        model_answer=text,
        what_was_missing=_strings("what_was_missing"),
        key_points=_strings("key_points"),
        verdict_line=verdict if isinstance(verdict, str) else "",
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _owned_session(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID):
    """Load the session, 404 if it is not this user's."""
    from app.models.session import InterviewSession  # noqa: PLC0415

    session = await db.scalar(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _coerce_delivery(raw: dict | None) -> AnswerDelivery | None:
    """
    Read a stored delivery blob defensively.

    It is JSONB written by a browser across many app versions, so anything in it
    may be missing or the wrong type. A 500 here would take down the whole
    analysis view over one malformed row.
    """
    if not raw:
        return None
    try:
        pauses = [
            PauseMarkOut(
                wordIndex=int(p.get("wordIndex") or 0),
                seconds=int(p.get("seconds") or 0),
            )
            for p in (raw.get("pauses") or [])
            if isinstance(p, dict)
        ]
        return AnswerDelivery(
            filler_count=int(raw.get("filler_count") or 0),
            pause_count=int(raw.get("pause_count") or 0),
            total_pause_seconds=int(raw.get("total_pause_seconds") or 0),
            words=int(raw.get("words") or 0),
            speaking_seconds=int(raw.get("speaking_seconds") or 0),
            pauses=pauses,
        )
    except (TypeError, ValueError, AttributeError):
        logger.warning("answer_delivery_unreadable")
        return None


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/{session_id}", response_model=DetailedAnalysisResponse)
async def get_detailed_analysis(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Every question from a session with the candidate's verbatim answer.

    Free: a pure database read, no AI. Model answers are generated per question on
    request, so opening this view costs nothing.
    """
    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.question import Question, Topic  # noqa: PLC0415
    from app.models.session import Answer  # noqa: PLC0415

    session = await _owned_session(db, session_id, current_user.user_id)

    rows = (
        await db.execute(
            select(Answer, Question, Topic.name)
            .join(Question, Answer.question_id == Question.id)
            .outerjoin(Topic, Question.topic_id == Topic.id)
            .where(Answer.session_id == session_id)
            .order_by(Answer.created_at.asc())
        )
    ).all()

    track = await db.get(InterviewTrack, session.track_id) if session.track_id else None
    company = await db.get(Company, track.company_id) if track else None

    answers = [
        AnalysedAnswer(
            answer_id=answer.id,
            question_id=question.id,
            question=question.content,
            question_type=str(question.question_type or "conceptual"),
            topic=topic_name or "General",
            answer=answer.content,
            answered_at=answer.created_at,
            delivery=_coerce_delivery(answer.delivery),
            model_answer=_coerce_model_answer(answer.model_answer),
            is_coding=str(question.question_type or "") == "coding",
        )
        for answer, question, topic_name in rows
    ]

    return DetailedAnalysisResponse(
        session_id=session_id,
        track_name=track.name if track else "Interview",
        company_name=company.name if company else "",
        completed_at=session.completed_at,
        answers=answers,
    )


@router.post(
    "/{session_id}/answers/{answer_id}/model-answer",
    response_model=ModelAnswerResult,
    # 200, not 201: idempotent, and returns a cached result as often as it creates one.
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_model_answer_rate_limit)],
)
async def generate_model_answer(
    session_id: uuid.UUID,
    answer_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    The answer the candidate should have given, written against what they said.

    Generated on demand and cached on the answer row: this is a billed call and the
    detailed view is re-read freely, so a second open must not be a second charge.
    """
    import asyncio  # noqa: PLC0415

    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.question import Question, Topic  # noqa: PLC0415
    from app.models.session import Answer  # noqa: PLC0415
    from app.models.user import Profile  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import ModelAnswerResponse  # noqa: PLC0415

    session = await _owned_session(db, session_id, current_user.user_id)

    row = (
        await db.execute(
            select(Answer, Question, Topic.name)
            .join(Question, Answer.question_id == Question.id)
            .outerjoin(Topic, Question.topic_id == Topic.id)
            .where(Answer.id == answer_id, Answer.session_id == session_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Answer not found in this session")
    answer, question, topic_name = row

    # Cached: return the whole stored payload and bill nothing.
    cached = _coerce_model_answer(answer.model_answer)
    if cached is not None:
        return ModelAnswerResult(answer_id=answer.id, cached=True, **cached.model_dump())

    track = await db.get(InterviewTrack, session.track_id) if session.track_id else None
    company = await db.get(Company, track.company_id) if track else None
    profile = await db.scalar(select(Profile).where(Profile.user_id == current_user.user_id))

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="model_answer",
        user_content=(
            "Write the model answer for the question above, judged against what "
            "the candidate actually said."
        ),
        company_name=company.name if company else "the company",
        track_name=track.name if track else "technical",
        question=question.content,
        question_type=str(question.question_type or "conceptual"),
        topic=topic_name or "General",
        candidate_answer=answer.content or "(the candidate gave no answer)",
        candidate_name=(profile.full_name if profile and profile.full_name else "the candidate"),
    )

    try:
        result, _raw = await asyncio.wait_for(
            generate_structured(
                ModelAnswerResponse,
                messages,
                max_tokens=_MODEL_ANSWER_MAX_TOKENS,
                attempts_per_provider=1,
                # BALANCED: the rubric is fully specified in the prompt, so this
                # does not need reasoning on top.
                cost_tier=CostTier.BALANCED,
                context="model_answer",
            ),
            timeout=_MODEL_ANSWER_BUDGET_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "model_answer_unavailable",
            session_id=str(session_id),
            answer_id=str(answer_id),
            error=type(exc).__name__,
        )
        # 503 rather than a fabricated answer: a wrong "ideal answer" is worse
        # than none, because the candidate would go and learn it.
        raise HTTPException(
            status_code=503,
            detail="The ideal answer could not be generated just now. Please try again shortly.",
        ) from exc

    answer.model_answer = result.model_dump(mode="json")
    answer.model_answer_generated_at = datetime.now(UTC)
    await db.commit()

    logger.info(
        "model_answer_generated",
        session_id=str(session_id),
        answer_id=str(answer_id),
        chars=len(result.model_answer),
    )

    return ModelAnswerResult(
        answer_id=answer.id,
        cached=False,
        model_answer=result.model_answer,
        what_was_missing=result.what_was_missing,
        key_points=result.key_points,
        verdict_line=result.verdict_line,
    )
