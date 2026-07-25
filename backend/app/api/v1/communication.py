"""
Communication Round Endpoints — api/v1/communication.py

An AI-proctored spoken communication round. The candidate speaks an answer
to a prompt; the client measures objective delivery metrics (speaking pace,
filler words, eye contact from the on-device camera check) and sends them
with the transcript. The AI scores clarity, structure, confidence, and
conciseness and gives delivery feedback.

GET  /communication/prompts        — a set of common communication prompts
POST /communication/evaluate       — score a spoken answer + delivery metrics
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.session import get_db
from app.services.activity import log_activity

logger = structlog.get_logger(__name__)
router = APIRouter()

_eval_rate_limit = rate_limiter(
    limit=30,
    window_seconds=60,
    key_builder=lambda user_id: f"rate_limit:comms:{user_id}:minute",
    action="evaluating a communication answer",
)

# Common HR / communication-round prompts freshers face. Served as-is
# (no AI needed to pick a prompt) so this is instant.
_PROMPTS = [
    "Tell me about yourself.",
    "Why do you want to work for this company?",
    "Describe a challenging situation you faced and how you handled it.",
    "What are your greatest strengths and weaknesses?",
    "Where do you see yourself in five years?",
    "Tell me about a time you worked in a team.",
    "Why should we hire you?",
    "Describe a project you are proud of.",
    "How do you handle pressure or tight deadlines?",
    "Are you comfortable relocating and with night shifts?",
    "Explain a technical concept you know well to a non-technical person.",
    "What motivates you, and how do you stay productive?",
]

# Reading-comprehension passages: the candidate reads one aloud within a time
# limit; we measure reading pace, fillers and pauses, and the AI rates fluency.
# Each has a suggested time budget (seconds) sized to a calm ~130 wpm read.
_PASSAGES = [
    {
        "title": "Cloud Computing",
        "seconds": 45,
        "text": (
            "Cloud computing delivers computing services such as servers, storage, "
            "databases, and software over the internet. Instead of owning physical "
            "infrastructure, organisations rent resources on demand and pay only for "
            "what they use. This flexibility lets teams scale quickly, reduce upfront "
            "costs, and focus on building products rather than maintaining hardware."
        ),
    },
    {
        "title": "The Importance of Teamwork",
        "seconds": 40,
        "text": (
            "Great software is rarely built alone. Strong teams combine different "
            "strengths, review each other's work, and communicate openly when problems "
            "arise. When members trust one another, they share ideas freely and recover "
            "from mistakes faster. Collaboration, not individual brilliance, is what "
            "ships reliable products on time."
        ),
    },
    {
        "title": "Artificial Intelligence",
        "seconds": 50,
        "text": (
            "Artificial intelligence enables machines to perform tasks that normally "
            "require human intelligence, such as recognising speech, translating "
            "languages, and making decisions. Modern systems learn patterns from large "
            "amounts of data rather than following fixed rules. As these tools become "
            "more capable, using them responsibly and understanding their limits matters "
            "just as much as building them."
        ),
    },
    {
        "title": "Databases and Data",
        "seconds": 40,
        "text": (
            "A database is an organised collection of information that a program can "
            "quickly store and retrieve. Relational databases arrange data into tables "
            "with rows and columns, and use keys to link related records. Choosing the "
            "right structure early makes an application faster, safer, and much easier "
            "to grow over time."
        ),
    },
]


class CommunicationPrompt(BaseModel):
    id: int
    text: str


class ReadingPassage(BaseModel):
    id: int
    title: str
    text: str
    seconds: int


class EvaluateRequest(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=2000)
    transcript: str = Field(min_length=1, max_length=8000)
    duration_seconds: int = Field(ge=1, le=1800)
    filler_count: int = Field(ge=0, le=1000)
    words_per_minute: int = Field(ge=0, le=1000)
    eye_contact_pct: int | None = Field(default=None, ge=0, le=100)
    pause_count: int = Field(default=0, ge=0, le=1000)
    total_pause_seconds: int = Field(default=0, ge=0, le=3600)
    mode: str = Field(default="speaking")  # "speaking" | "reading"


class CommunicationResult(BaseModel):
    clarity_score: float
    structure_score: float
    confidence_score: float
    conciseness_score: float
    overall_score: float
    pace_feedback: str
    filler_feedback: str
    feedback: str
    strengths: list[str]
    improvements: list[str]
    # Echo the objective metrics back for the scorecard.
    words_per_minute: int
    filler_count: int
    eye_contact_pct: int | None
    pause_count: int = 0
    total_pause_seconds: int = 0


@router.get("/prompts", response_model=list[CommunicationPrompt])
async def communication_prompts(current_user: CurrentUser):
    """Return the set of communication-round prompts."""
    return [CommunicationPrompt(id=i, text=t) for i, t in enumerate(_PROMPTS)]


@router.get("/passages", response_model=list[ReadingPassage])
async def reading_passages(current_user: CurrentUser):
    """Return curated reading-comprehension passages for the reading mode."""
    return [
        ReadingPassage(id=i, title=str(p["title"]), text=str(p["text"]), seconds=int(p["seconds"]))
        for i, p in enumerate(_PASSAGES)
    ]


class CrossQuestionRequest(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=2000)
    transcript: str = Field(min_length=1, max_length=8000)


class CrossQuestionResponse(BaseModel):
    question: str


@router.post("/cross-question", response_model=CrossQuestionResponse, dependencies=[Depends(_eval_rate_limit)])
async def communication_cross_question(request: CrossQuestionRequest, current_user: CurrentUser):
    """
    Generate ONE spoken follow-up (cross-question) that digs into what the
    candidate just said — the same natural probing a real interviewer does after
    your first answer. Falls back to a sensible generic follow-up if the AI is
    unavailable, so the round never dead-ends.
    """
    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import GeneratedQuestion  # noqa: PLC0415

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="cross_question",
        user_content="Generate the cross-question now, following the output format.",
        topic="Communication",
        last_question=request.prompt_text,
        last_answer=request.transcript,
    )
    try:
        parsed, _ = await generate_structured(
            GeneratedQuestion,
            messages,
            max_tokens=1000,
            attempts_per_provider=1,
            is_valid=lambda q: len(q.content.strip()) >= 12,
            context="communication_cross_question",
        )
        return CrossQuestionResponse(question=parsed.content.strip())
    except AIProviderUnavailableError:
        return CrossQuestionResponse(
            question="Can you give me a specific example that shows what you just described?"
        )


@router.post("/evaluate", response_model=CommunicationResult, dependencies=[Depends(_eval_rate_limit)])
async def evaluate_communication(
    request: EvaluateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Score a spoken answer's delivery via the communication_evaluator prompt."""
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import CommunicationEvaluation  # noqa: PLC0415

    builder = PromptBuilder(get_prompt_loader())
    eye = f"{request.eye_contact_pct}%" if request.eye_contact_pct is not None else "not measured"
    pauses_desc = (
        f"{request.pause_count} noticeable pause(s) totalling ~{request.total_pause_seconds}s"
        if request.pause_count
        else "no long pauses"
    )
    mode_desc = (
        "reading a passage aloud (assess fluency, pace and pauses)"
        if request.mode == "reading"
        else "answering a spoken interview question"
    )

    messages = builder.chat(
        system_template="communication_evaluator",
        user_content=f"Candidate's spoken answer (transcribed):\n{request.transcript}",
        prompt_text=request.prompt_text,
        words_per_minute=str(request.words_per_minute),
        filler_count=str(request.filler_count),
        duration_seconds=str(request.duration_seconds),
        eye_contact=eye,
        pauses=pauses_desc,
        mode=mode_desc,
    )

    evaluation, _ = await generate_structured(
        CommunicationEvaluation,
        messages,
        max_tokens=900,
        attempts_per_provider=2,
        context="communication_evaluation",
    )

    await log_activity(
        db,
        current_user.user_id,
        activity_type="communication",
        title=f"Communication Round — {request.prompt_text[:80]}",
        score=round(evaluation.overall_score * 10, 1),
        details={
            **evaluation.model_dump(),
            "words_per_minute": request.words_per_minute,
            "filler_count": request.filler_count,
            "eye_contact_pct": request.eye_contact_pct,
            "pause_count": request.pause_count,
            "total_pause_seconds": request.total_pause_seconds,
            "mode": request.mode,
        },
    )

    return CommunicationResult(
        **evaluation.model_dump(),
        words_per_minute=request.words_per_minute,
        filler_count=request.filler_count,
        eye_contact_pct=request.eye_contact_pct,
        pause_count=request.pause_count,
        total_pause_seconds=request.total_pause_seconds,
    )
