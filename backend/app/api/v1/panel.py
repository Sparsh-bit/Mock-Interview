"""
The two-person interview panel — api/v1/panel.py

A real campus interview is not one person reading questions. It is two or three people who
know each other, who talk to each other as much as to you, who correct you on the spot when
you are wrong, and who at the end ask whether you have anything to ask them. That last
exchange is the one candidates remember.

This wraps the existing question flow in that room. The orchestrator still chooses WHICH
question to ask — none of the adaptive logic, session scoping or tenancy protection changes.
This decides who says it, what they say to each other around it, and what happens when the
answer was wrong.

WHY A LAYER RATHER THAN A REWRITE. Question selection carries the parts of this app that
were hardest to get right: the per-session question ownership from migration 010, the
_already_asked guard, plan top-up, cross-question scoping. Rebuilding all of that inside a
"panel engine" to gain dialogue would risk the correctness for the presentation. So the
panel sits on top and is free to fail — if it does, the caller still has the question and can
put it to the candidate the old way.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/panel", tags=["Interview Panel"])


class Interviewer(BaseModel):
    """
    One member of the interview panel.

    `gender` drives voice selection on the client, and it is not cosmetic — the same lesson
    the GD panel taught: a candidate tracks who is asking what by voice while thinking of an
    answer, so a mismatch makes the round harder to follow for reasons unrelated to the
    questions.

    `role` is the chip beside the name; `disposition` is prose for the model. Two fields
    because a chip reading the first forty characters of a paragraph tells nobody anything.
    """

    name: str
    gender: str  # "male" | "female"
    role: str
    disposition: str


#: The panel. ONE definition, served to the client via GET /panel/interviewers, so names,
#: genders and personas cannot drift between the prompt that writes their dialogue and the
#: UI that renders and voices them.
#:
#: Two people, with different jobs in the room. A panel where both behave identically is one
#: person with two name tags — the same failure the GD panel was built to avoid.
INTERVIEWERS: list[Interviewer] = [
    Interviewer(
        name="Anil",
        gender="male",
        role="Senior Engineering Manager",
        disposition=(
            "Leads the interview. Warm but economical — greets, sets the pace, decides when "
            "to move on, and closes. Hands over to Priya out loud. When an answer is wrong "
            "he does not dwell on it; he lets the correction land and moves the room along."
        ),
    ),
    Interviewer(
        name="Priya",
        gender="female",
        role="Technical Lead",
        disposition=(
            "The specialist. Digs into the actual answer, and is the one who CORRECTS a "
            "wrong answer plainly and briefly, without sarcasm. Asks the sharper follow-ups. "
            "Speaks a little faster than Anil and interrupts herself when she is thinking."
        ),
    ),
]

INTERVIEWER_NAMES: list[str] = [i.name for i in INTERVIEWERS]

#: Panel dialogue is a CHEAP call and it runs on every question, so it needs its own ceiling
#: separate from the interview limit. A 12-question interview with corrections and a closing
#: sequence is roughly 16 of these.
_panel_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_ai(user_id),
    action="the interview panel speaking",
)


def _render_panel() -> str:
    return "\n".join(f"- {i.name} ({i.gender}, {i.role}): {i.disposition}" for i in INTERVIEWERS)


class PanelTurnRequest(BaseModel):
    session_id: uuid.UUID
    #: Where the interview is. Drives which behaviour the prompt follows.
    stage: str = Field(default="mid", pattern="^(opening|mid|wrapping|candidate_questions|answering_candidate)$")
    #: The question the orchestrator chose. Empty for stages that do not ask one.
    question: str = Field(default="", max_length=2000)
    #: What the candidate last said, so a wrong answer can be corrected in the room.
    last_answer: str = Field(default="", max_length=4000)
    #: The expected concepts for the LAST question, so the correction is grounded in the
    #: bank's own answer rather than whatever the model recalls. This is what stops a
    #: "correction" that is itself wrong.
    last_expected: str = Field(default="", max_length=2000)
    #: What the candidate asked, for the answering_candidate stage.
    candidate_question: str = Field(default="", max_length=1000)
    candidate_name: str = Field(default="", max_length=80)


class PanelTurnResponse(BaseModel):
    turns: list[dict]
    asked_question: bool


@router.get("/interviewers", summary="Who is on the panel")
async def get_interviewers(current_user: CurrentUser) -> list[Interviewer]:
    return INTERVIEWERS


@router.post(
    "/turn",
    dependencies=[Depends(_panel_rate_limit)],
    summary="What the panel says at this point in the interview",
)
async def panel_turn(
    request: PanelTurnRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PanelTurnResponse:
    # Reused from the GD panel rather than copied: it is the same job — reduce whatever the
    # profile holds to something a person would actually say out loud — and two copies of a
    # name rule is two rules that drift.
    from app.api.v1.gd import _candidate_name  # noqa: PLC0415
    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import InterviewPanelTurn  # noqa: PLC0415

    name = _candidate_name(request.candidate_name)

    brief = "\n".join(
        [
            "## This moment",
            "",
            "### The panel",
            _render_panel(),
            "",
            f"### The candidate\n{name}",
            "",
            f"### Stage\n{request.stage}",
            "",
            f"### The question to put\n{request.question or '(none for this stage)'}",
            "",
            f"### What the candidate last said\n{request.last_answer or '(nothing yet)'}",
            "",
            "### What a correct answer to THAT last question covers",
            request.last_expected or "(not available — do not invent a correction)",
            "",
            f"### What the candidate just asked you\n{request.candidate_question or '(nothing)'}",
            "",
            "Write the panel's dialogue for this moment now, as JSON.",
        ]
    )

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat_static(system_template="interview_panel", user_content=brief)

    try:
        turn, _ = await generate_structured(
            InterviewPanelTurn,
            messages,
            max_tokens=500,
            attempts_per_provider=1,
            is_valid=lambda t: bool(t.turns),
            cost_tier=CostTier.CHEAP,
            context="interview_panel_turn",
            # The system block is static — see the note at the top of interview_panel.md.
            # A 12-question interview is ~16 of these calls re-sending the same ~1400-token
            # rulebook, so this reads from cache rather than paying for it every time.
            cache_system=True,
        )
    except AIProviderUnavailableError:
        # The panel is presentation. If it is unavailable the caller still has the question
        # and puts it to the candidate the old way — a dialogue failure must never cost
        # somebody their interview.
        logger.warning("panel_turn_unavailable", session_id=str(request.session_id))
        return PanelTurnResponse(turns=[], asked_question=False)

    # Only real panel members may speak. The model must never be able to put words in the
    # candidate's mouth — the same guard the GD panel carries, for the same reason.
    valid = [
        {"speaker": c.speaker, "text": c.text.strip()}
        for c in turn.turns
        if c.text.strip() and c.speaker in INTERVIEWER_NAMES
    ][:4]

    return PanelTurnResponse(turns=valid, asked_question=turn.asked_question and bool(valid))
