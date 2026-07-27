"""
Quiz Endpoints — api/v1/quiz.py

Timed multiple-choice quiz, AI-generated fresh each attempt so questions
differ every time.

POST /quiz/start           — generate a quiz for a track; returns questions
                             WITHOUT the answer key (stored server-side in
                             Redis so answers can't be read from the network).
POST /quiz/{quiz_id}/submit — grade the candidate's selected options and return
                             the score + per-question correctness + explanations.
"""

from __future__ import annotations

import json
import random
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import cache_delete, cache_get, cache_set, get_redis
from app.db.session import AsyncSession, get_db
from app.services.activity import log_activity

logger = structlog.get_logger(__name__)
router = APIRouter()

_QUIZ_TTL_SECONDS = 2 * 60 * 60  # answer key lives 2h — long enough for any timed quiz

_quiz_rate_limit = rate_limiter(
    limit=20,
    window_seconds=3600,
    key_builder=lambda user_id: f"rate_limit:quiz:{user_id}:hourly",
    action="starting a quiz",
)


# ─── Schemas ──────────────────────────────────────────────────────────────────


class StartQuizRequest(BaseModel):
    track_id: uuid.UUID | None = None
    count: int = Field(default=8, ge=3, le=20)
    minutes: int = Field(default=10, ge=1, le=60)
    # Optional free-text focus + target company, typed by the candidate.
    topic: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=120)


class QuizOption(BaseModel):
    id: str
    question: str
    options: list[str]
    topic: str
    difficulty: str


class StartQuizResponse(BaseModel):
    quiz_id: str
    minutes: int
    questions: list[QuizOption]


class SubmitQuizRequest(BaseModel):
    # question_id -> selected option index
    answers: dict[str, int] = Field(default_factory=dict)


class QuizResultItem(BaseModel):
    question_id: str
    question: str
    options: list[str]
    correct_index: int
    selected_index: int | None
    is_correct: bool
    explanation: str
    topic: str


class SubmitQuizResponse(BaseModel):
    score: int
    total: int
    percentage: float
    results: list[QuizResultItem]


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/start", response_model=StartQuizResponse, dependencies=[Depends(_quiz_rate_limit)])
async def start_quiz(
    request: StartQuizRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Generate a fresh AI quiz and return questions without the answer key."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.company import InterviewTrack, QuestionCategory  # noqa: PLC0415
    from app.models.question import Topic  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import QuizGeneration  # noqa: PLC0415

    track_name = "Cognizant Digital Nurture — Java FSE"
    topics_str = (
        "Java OOP, Collections & HashMap internals, Exception Handling, JVM/JDK/JRE, "
        "Multithreading, SQL, Spring Boot, REST APIs, MVC, Design Patterns, PL/SQL"
    )
    if request.track_id:
        track = await db.get(InterviewTrack, request.track_id)
        if track:
            track_name = track.name
        topic_rows = await db.scalars(
            select(Topic.name)
            .join(QuestionCategory, Topic.category_id == QuestionCategory.id)
            .where(QuestionCategory.track_id == request.track_id)
        )
        topics = [t for t in topic_rows if t]
        if topics:
            topics_str = ", ".join(topics)

    builder = PromptBuilder(get_prompt_loader())

    company = (request.company or "").strip() or "a general tech company (Cognizant Digital Nurture style)"
    focus = (request.topic or "").strip() or "(no specific topic — use the track's default topic areas below)"

    messages = builder.chat(
        system_template="quiz_generator",
        user_content="Generate the quiz now, following the rules and output format.",
        track_name=track_name,
        topics=topics_str,
        count=str(request.count),
        company=company,
        focus=focus,
    )

    # Budget tokens to the quiz size (~300 tokens/question + buffer). Tries the
    # primary then fallback provider, retrying each; the free-tier model is slow
    # and occasionally returns empty content, so a non-empty question list is
    # required (raises AIProviderUnavailableError if all attempts fail).
    max_tokens = min(300 * request.count + 600, 8000)
    quiz, _ = await generate_structured(
        QuizGeneration,
        messages,
        max_tokens=max_tokens,
        attempts_per_provider=2,
        is_valid=lambda q: bool(q.questions),
        cost_tier=CostTier.BALANCED,
        context="quiz_generation",
    )

    quiz_id = str(uuid.uuid4())
    public_questions: list[QuizOption] = []
    answer_key: dict[str, dict] = {}
    for q in quiz.questions:
        qid = str(uuid.uuid4())
        # Clamp a possibly-out-of-range correct_index to a valid option.
        correct = q.correct_index if 0 <= q.correct_index < len(q.options) else 0
        public_questions.append(
            QuizOption(id=qid, question=q.question, options=q.options, topic=q.topic, difficulty=q.difficulty)
        )
        answer_key[qid] = {
            "question": q.question,
            "options": q.options,
            "correct_index": correct,
            "explanation": q.explanation,
            "topic": q.topic,
        }

    await cache_set(
        redis,
        f"quiz:answers:{quiz_id}",
        json.dumps({"user_id": str(current_user.user_id), "key": answer_key}),
        ttl=_QUIZ_TTL_SECONDS,
    )

    return StartQuizResponse(quiz_id=quiz_id, minutes=request.minutes, questions=public_questions)


# ─── Curated instant bank (no AI) ───────────────────────────────────────────


class BankTopic(BaseModel):
    topic: str
    count: int


class StartBankQuizRequest(BaseModel):
    topic: str | None = None  # None = mix across all topics
    count: int = Field(default=8, ge=3, le=30)
    minutes: int = Field(default=10, ge=1, le=60)


@router.get("/bank/topics", response_model=list[BankTopic])
async def bank_topics(current_user: CurrentUser):
    """List curated bank topics and how many questions each has."""
    from app.data.quiz_bank import QUIZ_BANK  # noqa: PLC0415

    return [BankTopic(topic=t, count=len(qs)) for t, qs in QUIZ_BANK.items()]


@router.post("/bank/start", response_model=StartQuizResponse)
async def start_bank_quiz(
    request: StartBankQuizRequest,
    current_user: CurrentUser,
    redis: Redis = Depends(get_redis),
):
    """
    Start a quiz from the curated bank — instant, no AI. Randomly samples
    questions (and shuffles each question's options) so repeats vary, then
    reuses the same Redis answer-key + /quiz/{id}/submit grading path.
    """
    from app.data.quiz_bank import QUIZ_BANK  # noqa: PLC0415

    # Build the candidate pool.
    if request.topic and request.topic in QUIZ_BANK:
        pool = [{**q, "topic": request.topic} for q in QUIZ_BANK[request.topic]]
    else:
        pool = [{**q, "topic": t} for t, qs in QUIZ_BANK.items() for q in qs]

    if not pool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No questions in the bank.")

    sample = random.sample(pool, min(request.count, len(pool)))

    quiz_id = str(uuid.uuid4())
    public_questions: list[QuizOption] = []
    answer_key: dict[str, dict] = {}
    for q in sample:
        qid = str(uuid.uuid4())
        # Shuffle options each attempt, tracking where the correct one lands.
        indexed = list(enumerate(q["options"]))
        random.shuffle(indexed)
        shuffled_options = [opt for _, opt in indexed]
        new_correct = next(i for i, (orig, _) in enumerate(indexed) if orig == q["correct_index"])

        public_questions.append(
            QuizOption(
                id=qid,
                question=q["question"],
                options=shuffled_options,
                topic=q["topic"],
                difficulty=q.get("difficulty", "medium"),
            )
        )
        answer_key[qid] = {
            "question": q["question"],
            "options": shuffled_options,
            "correct_index": new_correct,
            "explanation": q.get("explanation", ""),
            "topic": q["topic"],
        }

    await cache_set(
        redis,
        f"quiz:answers:{quiz_id}",
        json.dumps({"user_id": str(current_user.user_id), "key": answer_key}),
        ttl=_QUIZ_TTL_SECONDS,
    )
    return StartQuizResponse(quiz_id=quiz_id, minutes=request.minutes, questions=public_questions)


@router.post("/{quiz_id}/submit", response_model=SubmitQuizResponse)
async def submit_quiz(
    quiz_id: str,
    request: SubmitQuizRequest,
    current_user: CurrentUser,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Grade a submitted quiz against the server-side answer key."""
    raw = await cache_get(redis, f"quiz:answers:{quiz_id}")
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found or expired.")

    payload = json.loads(raw)
    if payload.get("user_id") != str(current_user.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This quiz belongs to another user.")

    answer_key: dict[str, dict] = payload["key"]
    results: list[QuizResultItem] = []
    score = 0
    for qid, meta in answer_key.items():
        selected = request.answers.get(qid)
        is_correct = selected == meta["correct_index"]
        if is_correct:
            score += 1
        results.append(
            QuizResultItem(
                question_id=qid,
                question=meta["question"],
                options=meta["options"],
                correct_index=meta["correct_index"],
                selected_index=selected,
                is_correct=is_correct,
                explanation=meta["explanation"],
                topic=meta["topic"],
            )
        )

    total = len(answer_key)
    # One-shot quiz: the key is consumed on submit so it can't be re-graded.
    await cache_delete(redis, f"quiz:answers:{quiz_id}")

    percentage = round((score / total) * 100, 1) if total else 0.0
    topics = sorted({meta.get("topic", "General") for meta in answer_key.values()})
    await log_activity(
        db,
        current_user.user_id,
        activity_type="quiz",
        title=f"Quiz — {', '.join(topics) or 'General'}",
        score=percentage,
        details={
            "score": score,
            "total": total,
            "percentage": percentage,
            "topics": topics,
        },
    )

    return SubmitQuizResponse(
        score=score,
        total=total,
        percentage=percentage,
        results=results,
    )
