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

from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser

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
]


class CommunicationPrompt(BaseModel):
    id: int
    text: str


class EvaluateRequest(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=500)
    transcript: str = Field(min_length=1, max_length=8000)
    duration_seconds: int = Field(ge=1, le=1800)
    filler_count: int = Field(ge=0, le=1000)
    words_per_minute: int = Field(ge=0, le=1000)
    eye_contact_pct: int | None = Field(default=None, ge=0, le=100)


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


@router.get("/prompts", response_model=list[CommunicationPrompt])
async def communication_prompts(current_user: CurrentUser):
    """Return the set of communication-round prompts."""
    return [CommunicationPrompt(id=i, text=t) for i, t in enumerate(_PROMPTS)]


@router.post("/evaluate", response_model=CommunicationResult, dependencies=[Depends(_eval_rate_limit)])
async def evaluate_communication(request: EvaluateRequest, current_user: CurrentUser):
    """Score a spoken answer's delivery via the communication_evaluator prompt."""
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import CommunicationEvaluation  # noqa: PLC0415

    builder = PromptBuilder(get_prompt_loader())
    eye = f"{request.eye_contact_pct}%" if request.eye_contact_pct is not None else "not measured"

    messages = builder.chat(
        system_template="communication_evaluator",
        user_content=f"Candidate's spoken answer (transcribed):\n{request.transcript}",
        prompt_text=request.prompt_text,
        words_per_minute=str(request.words_per_minute),
        filler_count=str(request.filler_count),
        duration_seconds=str(request.duration_seconds),
        eye_contact=eye,
    )

    evaluation, _ = await generate_structured(
        CommunicationEvaluation,
        messages,
        max_tokens=900,
        attempts_per_provider=2,
        context="communication_evaluation",
    )

    return CommunicationResult(
        **evaluation.model_dump(),
        words_per_minute=request.words_per_minute,
        filler_count=request.filler_count,
        eye_contact_pct=request.eye_contact_pct,
    )
