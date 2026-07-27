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

#: Speaker label the client uses for the real candidate's own turns. Must match
#: the `YOU` constant in the GD page.
_YOU = "You"

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
    #: True when the previous panel turn put a direct question to the candidate
    #: and they have not spoken since. Makes the panel press harder.
    awaiting_candidate: bool = False
    #: How many direct questions the candidate has left unanswered. At 2+ the
    #: panel calls out the silence and moves on without them.
    ignored_questions: int = Field(default=0, ge=0, le=20)
    #: Wall-clock seconds since the candidate last spoke. Drives "you've been
    #: quiet" nudges independently of how many panel turns have passed.
    candidate_silent_seconds: int = Field(default=0, ge=0, le=3600)
    #: "opening" | "discussion" | "closing" — in closing the panel converges
    #: and competes for the final summary.
    phase: str = Field(default="discussion", max_length=20)


class GDContributionOut(BaseModel):
    speaker: str
    text: str


class GDTurnResponse(BaseModel):
    contributions: list[GDContributionOut]
    #: True when this turn asks the candidate something directly.
    addressed_candidate: bool = False


class GDEvaluateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=400)
    history: list[Turn] = Field(default_factory=list, max_length=60)
    #: Direct questions the candidate never answered. Real GD evaluators mark
    #: this down hard, so it is scored rather than silently ignored.
    ignored_questions: int = Field(default=0, ge=0, le=20)


class GDEvaluateResponse(BaseModel):
    contribution_score: float
    relevance_score: float
    clarity_score: float
    engagement_score: float
    overall_score: float
    feedback: str
    strengths: list[str]
    improvements: list[str]


#: How many recent turns to show the model. The panel only needs recent context
#: to react coherently, and the autonomous clock means turns are generated
#: continuously — sending the whole transcript every time would make input cost
#: grow quadratically over a single discussion.
_TRANSCRIPT_WINDOW = 14


def _render_transcript(history: list[Turn], window: int | None = None) -> str:
    if not history:
        return "(the discussion has not started yet)"
    shown = history[-window:] if window else history
    lines = [f"{t.speaker}: {t.text}" for t in shown]
    if window and len(history) > window:
        lines.insert(0, f"(...{len(history) - window} earlier turns omitted...)")
    return "\n".join(lines)


def _describe_situation(request: GDTurnRequest) -> str:
    """
    Turn the client's state flags into the plain-English situation block the
    panel prompt branches on. Keeping this on the server means the escalation
    rules live next to the prompt that implements them.
    """
    spoke_at_all = any(t.speaker == _YOU for t in request.history)

    if not request.history:
        return (
            "The discussion is just starting. No one has spoken. Open with two "
            "strong, opposing positions to set the debate up."
        )

    # Closing outranks the give-up branch: near the end the panel should be
    # converging on a conclusion, not still litigating the candidate's silence.
    if request.phase == "closing":
        return (
            "The discussion is nearly out of time. Converge — summarise the "
            "group's position and compete for the final word. One panelist may "
            "offer the candidate a last narrow opening to add something."
        )

    if request.ignored_questions >= 2:
        return (
            f"The candidate has now ignored {request.ignored_questions} direct "
            "questions. Call this out ONCE, plainly and a little dismissively, "
            "then move the discussion on to a new angle WITHOUT them. Do not "
            "ask them anything this turn, and do not dwell on it further."
        )

    if request.awaiting_candidate:
        return (
            "A panelist already put a direct question to the candidate and they "
            "still have not answered. Press harder — re-put it in narrower, "
            "harder-to-dodge terms and show mild impatience."
        )

    if not spoke_at_all:
        return (
            f"The candidate has not spoken at all yet ({request.candidate_silent_seconds}s "
            "in). Carry the argument forward between panelists, then pull them "
            "in by name and ask for their take."
        )

    if request.candidate_silent_seconds >= 25:
        return (
            f"The candidate has been silent for {request.candidate_silent_seconds}s. "
            "Keep the discussion moving on your own, then invite them in by name."
        )

    return (
        "The candidate has just contributed. Engage their point directly — "
        "agree and extend it, or push back with a concrete reason."
    )


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
        transcript=_render_transcript(request.history, window=_TRANSCRIPT_WINDOW),
        situation=_describe_situation(request),
        phase=request.phase,
        ignored_questions=str(request.ignored_questions),
    )

    try:
        turn, _ = await generate_structured(
            GDPanelTurn,
            messages,
            # 1-2 contributions of 1-3 spoken sentences. The autonomous clock
            # makes this the most frequently called AI path in the app, so the
            # budget is deliberately tight — CHEAP tier also keeps replies terse
            # and conversational rather than essay-like.
            max_tokens=400,
            attempts_per_provider=2,
            is_valid=lambda t: bool(t.contributions),
            cost_tier=CostTier.CHEAP,
            context="gd_panel_turn",
        )
    except AIProviderUnavailableError:
        # Non-fatal: return an empty turn so the candidate can keep going.
        logger.warning("gd_turn_unavailable")
        return GDTurnResponse(contributions=[])

    # Keep only non-empty contributions from real panelists — the model must
    # never be allowed to put words in the candidate's mouth.
    valid = [
        GDContributionOut(speaker=c.speaker, text=c.text.strip())
        for c in turn.contributions
        if c.text.strip() and c.speaker in PANELISTS
    ][:2]

    # Trust the model's flag only if it actually asked something; and treat a
    # trailing question mark as addressing the candidate even if it forgot.
    addressed = bool(valid) and (
        turn.addressed_candidate or any(c.text.rstrip().endswith("?") for c in valid)
    )
    # On the give-up turn the panel is explicitly moving on without them.
    if request.ignored_questions >= 2:
        addressed = False

    return GDTurnResponse(contributions=valid, addressed_candidate=addressed)


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
        # Full transcript here (not windowed): scoring participation needs the
        # whole discussion, and this runs once per round rather than on a clock.
        transcript=_render_transcript(request.history),
        ignored_questions=str(request.ignored_questions),
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
