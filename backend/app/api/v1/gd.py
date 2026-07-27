"""
Group Discussion Endpoints — api/v1/gd.py

An AI-simulated group discussion round. The AI plays several named panelists
who discuss a topic; the real candidate contributes their own points (by
voice or text) between panelist turns. At the end the AI scores how the
candidate participated.

GET  /gd/topics    — common GD topics (instant)
POST /gd/turn      — generate the next AI-panelist contributions given history
POST /gd/evaluate  — score the candidate's participation
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

# Named AI panelists for the simulated discussion.
PANELISTS = ["Riya", "Arjun", "Meera"]

_gd_rate_limit = rate_limiter(
    limit=40,
    window_seconds=60,
    key_builder=lambda user_id: f"rate_limit:gd:{user_id}:minute",
    action="continuing a group discussion",
)

_TOPICS = [
    "Is remote work better than working from the office?",
    "Should AI tools be allowed in coding interviews?",
    "Does social media do more harm than good?",
    "Is a college degree still necessary to succeed in tech?",
    "Should companies prioritise skills over degrees when hiring freshers?",
    "Is work-life balance a myth in the tech industry?",
    "Are online certifications as valuable as formal education?",
    "Should India focus on product companies over service companies?",
]


class GDTopic(BaseModel):
    id: int
    text: str


class Turn(BaseModel):
    speaker: str
    text: str


class GDTurnRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=400)
    history: list[Turn] = Field(default_factory=list, max_length=60)


class GDContributionOut(BaseModel):
    speaker: str
    text: str


class GDTurnResponse(BaseModel):
    contributions: list[GDContributionOut]


class GDEvaluateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=400)
    history: list[Turn] = Field(default_factory=list, max_length=60)


class GDEvaluateResponse(BaseModel):
    contribution_score: float
    relevance_score: float
    clarity_score: float
    engagement_score: float
    overall_score: float
    feedback: str
    strengths: list[str]
    improvements: list[str]


def _render_transcript(history: list[Turn]) -> str:
    if not history:
        return "(the discussion has not started yet)"
    return "\n".join(f"{t.speaker}: {t.text}" for t in history)


@router.get("/topics", response_model=list[GDTopic])
async def gd_topics(current_user: CurrentUser):
    """Return the set of group-discussion topics."""
    return [GDTopic(id=i, text=t) for i, t in enumerate(_TOPICS)]


@router.post("/turn", response_model=GDTurnResponse, dependencies=[Depends(_gd_rate_limit)])
async def gd_turn(request: GDTurnRequest, current_user: CurrentUser):
    """Generate the next 1-2 AI-panelist contributions."""
    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import GDPanelTurn  # noqa: PLC0415

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="gd_panel",
        user_content="Give the next panelist contribution(s) now, as JSON.",
        topic=request.topic,
        panelists=", ".join(PANELISTS),
        transcript=_render_transcript(request.history),
    )

    try:
        turn, _ = await generate_structured(
            GDPanelTurn,
            messages,
            max_tokens=600,
            attempts_per_provider=2,
            is_valid=lambda t: bool(t.contributions),
            cost_tier=CostTier.BALANCED,
            context="gd_panel_turn",
        )
    except AIProviderUnavailableError:
        # Non-fatal: return an empty turn so the candidate can keep going.
        logger.warning("gd_turn_unavailable")
        return GDTurnResponse(contributions=[])

    # Keep only contributions from valid panelist names.
    valid = [
        GDContributionOut(speaker=c.speaker, text=c.text)
        for c in turn.contributions
        if c.text.strip()
    ]
    return GDTurnResponse(contributions=valid[:2])


@router.post("/evaluate", response_model=GDEvaluateResponse, dependencies=[Depends(_gd_rate_limit)])
async def gd_evaluate(
    request: GDEvaluateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Score the candidate's participation in the discussion."""
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import GDEvaluation  # noqa: PLC0415

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="gd_evaluator",
        user_content="Score the candidate's GD participation now, as JSON.",
        topic=request.topic,
        transcript=_render_transcript(request.history),
    )

    evaluation, _ = await generate_structured(
        GDEvaluation,
        messages,
        max_tokens=800,
        attempts_per_provider=2,
        cost_tier=CostTier.CHEAP,
        context="gd_evaluation",
    )
    await log_activity(
        db,
        current_user.user_id,
        activity_type="group_discussion",
        title=f"Group Discussion — {request.topic}",
        score=round(evaluation.overall_score * 10, 1),
        details=evaluation.model_dump(),
    )
    return GDEvaluateResponse(**evaluation.model_dump())
