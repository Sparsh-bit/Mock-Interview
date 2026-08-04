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

import re

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.session import get_db
from app.services.activity import log_activity
from app.services.ai import vector_cache
from app.services.progress.rating import Tier
from app.services.progress.recorder import record_round

logger = structlog.get_logger(__name__)
router = APIRouter()

class Panelist(BaseModel):
    """
    One AI participant in the discussion.

    `gender` exists so the client can pick a voice that matches the name. It is
    not cosmetic: a panel where "Riya" speaks in a male voice and "Arjun" in a
    female one is actively confusing to practise against, because the candidate
    tracks who is arguing what by voice, not by reading name labels while trying
    to think of a rebuttal.

    `stance` gives each panelist a fixed disposition, so the three do not collapse
    into one agreeable voice with three names. A real GD has someone pushing,
    someone hedging, and someone trying to synthesise — that is the dynamic a
    candidate has to learn to cut into.

    `role` is the same disposition in three or four words. The UI shows it as a
    chip beside the name so the candidate knows who they are up against before
    anyone speaks; `stance` is prose for the model and is far too long to render.
    Two fields rather than one truncated field, because a chip reading
    "Assertive and data-driven. Opens stro…" tells nobody anything.
    """

    name: str
    gender: str  # "female" | "male" — drives voice selection on the client
    stance: str
    role: str


#: The panel. ONE definition, served to the client via GET /gd/panel, so the
#: names, genders and personas cannot drift between the prompt that generates
#: their turns and the UI that renders and voices them.
#:
#: NOTE: the client also derives each panelist's speaking tempo and how quickly
#: they take the floor by keyword-matching this `stance` prose
#: (frontend/src/lib/speech/persona.ts). Rewording a stance out of its keyword
#: family silently reverts that panelist to a neutral delivery — it degrades
#: quietly rather than breaking, so check persona.ts when editing these.
PANELISTS: list[Panelist] = [
    Panelist(
        name="Riya",
        gender="female",
        stance=(
            "Assertive and data-driven. Opens strong, quotes numbers and examples, "
            "and challenges vague claims directly. Dominates if nobody pushes back."
        ),
        role="Quotes numbers, dominates",
    ),
    Panelist(
        name="Arjun",
        gender="male",
        stance=(
            "Takes the opposing side on principle and argues it well. Interrupts to "
            "disagree, concedes only to a concrete point, and enjoys the debate."
        ),
        role="Argues the other side",
    ),
    Panelist(
        name="Meera",
        gender="female",
        stance=(
            "The synthesiser. Listens, finds the middle ground, and brings quiet "
            "people in — she is usually the one who asks the candidate directly."
        ),
        role="Finds middle ground, pulls you in",
    ),
]

PANELIST_NAMES: list[str] = [p.name for p in PANELISTS]

#: Speaker label the client uses for the real candidate's own turns. Must match
#: the `YOU` constant in the GD page.
_YOU = "You"

_gd_rate_limit = rate_limiter(
    limit=40,
    window_seconds=60,
    key_builder=lambda user_id: f"rate_limit:gd:{user_id}:minute",
    action="continuing a group discussion",
)

#: Predefined topics, grouped the way campus GD rounds actually are. Categories
#: matter because panels rotate between them — a candidate who has only practised
#: tech abstractions is caught out by a social or business motion.
_TOPIC_BANK: list[tuple[str, str]] = [
    # Technology & the industry
    ("Technology", "Should AI tools be allowed in coding interviews?"),
    ("Technology", "Is a college degree still necessary to succeed in tech?"),
    ("Technology", "Will AI create more jobs than it destroys?"),
    ("Technology", "Should social media platforms be liable for what users post?"),
    ("Technology", "Is open source a sustainable way to build critical software?"),
    ("Technology", "Should self-driving cars be allowed on Indian roads?"),
    # Work & careers
    ("Work", "Is remote work better than working from the office?"),
    ("Work", "Is work-life balance a myth in the tech industry?"),
    ("Work", "Should companies prioritise skills over degrees when hiring freshers?"),
    ("Work", "Are online certifications as valuable as formal education?"),
    ("Work", "Should a fresher take a lower salary at a product company over a higher one at a service company?"),
    ("Work", "Is a four-day working week practical for Indian IT services?"),
    # Business & economy
    ("Business", "Should India focus on product companies over service companies?"),
    ("Business", "Do startups create more value for India than established corporates?"),
    ("Business", "Should the government fund electric vehicle subsidies?"),
    ("Business", "Is cash still relevant in a UPI-first India?"),
    # Society
    ("Society", "Does social media do more harm than good?"),
    ("Society", "Should English remain the medium of instruction in higher education?"),
    ("Society", "Is reservation in education still the right tool for equity?"),
    ("Society", "Should smartphones be banned in schools?"),
    # Ethics & judgement — the ones panels use to see how you handle disagreement
    ("Ethics", "Is it ever acceptable to break a rule to do the right thing?"),
    ("Ethics", "Should employers be allowed to monitor employees' work devices?"),
    ("Ethics", "Do we have a right to be forgotten by the internet?"),
]


class GDTopic(BaseModel):
    id: int
    text: str
    category: str


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
    #: The candidate's first name. The panel prompt has always been told to "pull
    #: them in by name" — with no name supplied, so the model either invented one
    #: or fell back to "you", which is exactly what makes a simulated panel feel
    #: like a chatbot rather than three people in a room.
    candidate_name: str = Field(default="", max_length=60)


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


#: What _candidate_name returns when the user has no usable name. A phrase no
#: panelist will ever say aloud, which is what makes it safe to match against.
_NO_NAME = "the candidate"


def _candidate_name(raw: str) -> str:
    """
    A name the panel can actually say, or a neutral fallback.

    Strips to the first word: the panel says "Sparsh, what do you think" and not
    "Sparsh Sharma, what do you think", which nobody says out loud. Falls back to
    "the candidate" rather than an empty string, because an empty substitution
    leaves the prompt reading "pull in  by name" and the model fills the gap with
    an invented name.
    """
    first = (raw or "").strip().split()[:1]
    cleaned = "".join(c for c in (first[0] if first else "") if c.isalpha() or c in "-'")
    return cleaned or _NO_NAME


def _mentions(text: str, name: str) -> bool:
    """
    Does `text` name this person as a person, rather than as a substring?

    Word boundaries are not optional here. Real first names in this user base are
    short, and a plain substring test is wrong for most of them: "Om" is inside
    "from", "company" and "problem"; "Sai" is inside "said"; "Ved" is inside
    "advised"; "Ria" is inside "criteria". For a candidate named Om, a substring
    test would match nearly every line the panel says.
    """
    return re.search(rf"(?<![\w']){re.escape(name)}(?![\w'])", text, re.IGNORECASE) is not None


def _round_brief(request: GDTurnRequest) -> str:
    """
    Everything about THIS round, as the user message.

    This content used to be substituted into the gd_panel system template, which meant no
    two calls shared a system prefix and prompt caching could never pay. A GD round is up
    to 26 turns each re-sending the same ~2100-token rulebook, so moving the variable part
    down here turns 25 of those 26 system reads into cache hits at 0.1x input — about 37%
    off the most expensive feature in the product.

    Section headings mirror the ones the system prompt refers to, so the rules can point
    at "the unanswered-question count in the user message" and mean something findable.
    """
    return "\n".join(
        [
            "## This round",
            "",
            "### Your panel",
            _render_panel(),
            "",
            f"### The candidate's name\n{_candidate_name(request.candidate_name)}",
            "",
            f"### Topic\n{request.topic}",
            "",
            "### Discussion so far",
            _render_transcript(request.history, window=_TRANSCRIPT_WINDOW),
            "",
            "### Current situation",
            _describe_situation(request),
            "",
            f"Discussion phase: {request.phase}",
            f"Direct questions the candidate has left unanswered: {request.ignored_questions}",
            "",
            "Give the next panelist contribution(s) now, as JSON.",
        ]
    )


def _aimed_at_candidate(text: str, name: str, others: list[str]) -> bool:
    """
    Is this contribution putting a question to the CANDIDATE?

    Used only as a fallback for a genuine invitation the model forgot to flag, and
    it has to clear two bars, because a bare trailing "?" is not evidence. The
    panel questions each other constantly — "Where's that number from, Riya?" —
    and every one of those ends in a question mark. Treating any "?" as addressing
    the candidate put "They're asking you directly" on screen for a question asked
    of somebody else, then counted their non-answer as an ignored question and fed
    that into their engagement score.

    `name` is the candidate's speakable first name, or "the candidate" when they
    have none — a phrase no panelist will ever utter, so callers pass it through
    and it simply never matches. `others` is the rest of the panel.
    """
    if not text.rstrip().endswith("?"):
        return False
    if name != _NO_NAME and _mentions(text, name):
        return True
    # A question that names another panelist belongs to them, not to us.
    if any(_mentions(text, p) for p in others):
        return False
    # Nobody named, second person present. Panelists address each other by name,
    # so a bare "you" in an unaddressed question is the candidate — which is what
    # keeps "So what do you think?" working.
    return bool(re.search(r"(?<!\w)(you|your|you're)(?!\w)", text, re.IGNORECASE))


def other_panelists(name: str) -> list[str]:
    """The panel minus the candidate, for name-collision-safe attribution."""
    lowered = name.lower()
    return [p for p in PANELIST_NAMES if not (name != _NO_NAME and p.lower() == lowered)]


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
            "in BY NAME and ask for their take."
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


def _render_panel() -> str:
    """The panel and their dispositions, for the prompt."""
    return "\n".join(f"- {p.name} ({p.gender}): {p.stance}" for p in PANELISTS)


@router.get("/panel", response_model=list[Panelist], summary="Who the AI panel is")
async def gd_panel(current_user: CurrentUser):
    """
    The panel definition, so the client can render and VOICE each participant
    correctly.

    Served rather than duplicated in the frontend: the names appear in the prompt,
    in the transcript, in the voice allocation and in the evaluation, and a copy
    that drifts means "Riya" speaks in Arjun's voice, or a contribution from a
    panelist the UI has never heard of is silently dropped.
    """
    return PANELISTS

@router.get("/topics", response_model=list[GDTopic])
async def gd_topics(current_user: CurrentUser):
    """Predefined group-discussion topics, with their category."""
    return [
        GDTopic(id=i, text=text, category=cat)
        for i, (cat, text) in enumerate(_TOPIC_BANK)
    ]


class GDPrepareRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=300)


class GDPrepareResponse(BaseModel):
    statement: str
    framing: str
    points_for: list[str]
    points_against: list[str]
    usable: bool
    reason: str


@router.post(
    "/prepare",
    response_model=GDPrepareResponse,
    dependencies=[Depends(_gd_rate_limit)],
    summary="Turn a candidate's own topic into a discussable motion",
)
async def gd_prepare(
    request: GDPrepareRequest,
    current_user: CurrentUser,
    # Needed only for the topic cache. This endpoint touched no tables before, so the
    # session is new here — it costs one pooled connection for two indexed statements,
    # which buys skipping a $0.016 generation on most requests.
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """
    Prepare a custom topic for discussion.

    A phrase is not a motion: "AI in education" has no sides, so a panel given it
    produces eight people listing facts rather than a discussion. This restates it
    as a proposition with two defensible sides and returns the arguments for each,
    which the candidate reads before the round starts.

    Falls back to using their text verbatim if the AI is unavailable — a candidate
    who typed a topic should get their round, and an unshaped topic still beats an
    error page.
    """
    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import GDPreparedTopic  # noqa: PLC0415

    raw_topic = request.topic.strip()

    # Ask the cache first. Preparing a topic is a $0.016 generation and candidates
    # converge hard on the same handful of phrases — "AI in education", "work from
    # home", "social media" — so most requests after the first week are a restatement
    # of one already paid for. Safe to share globally: the only input is the topic
    # phrase, which is public, and nothing a candidate SAID in a round reaches here.
    cached = await vector_cache.lookup(db, feature="gd_topic_prep", key=raw_topic)
    if cached is not None:
        return GDPrepareResponse(**cached)

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="gd_topic_prep",
        user_content="Prepare this topic now, as JSON.",
        raw_topic=raw_topic,
    )

    try:
        prepared, _ = await generate_structured(
            GDPreparedTopic,
            messages,
            max_tokens=900,
            attempts_per_provider=1,
            # A statement is the one field the round cannot run without.
            is_valid=lambda t: bool(t.statement.strip()) or not t.usable,
            cost_tier=CostTier.BALANCED,
            context="gd_topic_prep",
        )
    except AIProviderUnavailableError:
        logger.warning("gd_prepare_unavailable_using_raw_topic")
        return GDPrepareResponse(
            statement=request.topic.strip(),
            framing="",
            points_for=[],
            points_against=[],
            usable=True,
            reason="",
        )

    response = GDPrepareResponse(
        statement=prepared.statement.strip() or raw_topic,
        framing=prepared.framing.strip(),
        points_for=[p.strip() for p in prepared.points_for if p.strip()][:5],
        points_against=[p.strip() for p in prepared.points_against if p.strip()][:5],
        usable=prepared.usable,
        reason=prepared.reason.strip(),
    )

    # Remember it, so the next candidate who types this topic pays nothing. Stored even
    # when usable is false: "that is a factual question, not a debate" is a verdict
    # worth reusing rather than re-buying. Never raises — failing to remember must not
    # fail the request that produced it.
    await vector_cache.store(
        db, feature="gd_topic_prep", key=raw_topic, payload=response.model_dump(mode="json")
    )
    await db.commit()

    return response


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
    messages = builder.chat_static(
        system_template="gd_panel",
        user_content=_round_brief(request),
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
            # The one call site in the app that may set this. gd_panel.md is loaded
            # verbatim via chat_static and carries no placeholders, so the system block
            # is byte-identical across every turn of every round for every user — which
            # is what makes the cache read rather than only write. A round is up to 26
            # turns re-sending the same ~2100-token rulebook; cached, that is roughly 37%
            # off the most expensive feature in the product. Guarded by
            # tests/test_prompt_caching.py, because breaking it is silent and costs 25%
            # MORE rather than failing.
            cache_system=True,
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
        if c.text.strip() and c.speaker in PANELIST_NAMES
    ][:2]

    # Trust the model's flag first. The bare "?" fallback is only for a genuine
    # invitation it forgot to flag, and it now has to clear two bars.
    #
    # Panelists question EACH OTHER constantly — "Where's that number from,
    # Riya?" — and every one of those ends in a question mark. Treating any
    # trailing "?" as addressing the candidate put "They're asking you directly"
    # on screen for a question asked of somebody else, then counted the
    # candidate's non-answer as an ignored question and fed that into their
    # engagement score.
    name = _candidate_name(request.candidate_name)
    others = other_panelists(name)
    addressed = bool(valid) and (
        turn.addressed_candidate
        or any(_aimed_at_candidate(c.text, name, others) for c in valid)
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

    # A GD feeds the SAME rating as a technical round, deliberately. A candidate who
    # can hold a technical interview but goes silent in a group discussion is not
    # placement-ready, and two separate numbers would let them ignore the half they
    # are worse at — which is the half a real campus drive eliminates them on.
    #
    # session_id is None: a GD round has no InterviewSession row, so the per-session
    # idempotency guard does not apply here. That is correct rather than a gap — a GD
    # is only ever evaluated once, at the end, by the client that ran it.
    #
    # Rated CORE. A GD is not the hardest thing we run, but it is not a warm-up
    # either: eight minutes of holding a floor against three people who argue back is
    # squarely a standard campus round.
    #
    # Only a round the candidate actually took part in. Two reasons, and the product
    # one is the stronger: a discussion you sat out is not evidence of anything, so
    # rating it would put a number on the wrong thing. It also closes the one replay
    # gap here — an interview is guarded by UNIQUE(session_id), and a GD has no
    # session row, so a client could post the same transcript twice. The dampers make
    # that nearly worthless already (same topic gives repeat scale 0.25, and a second
    # round the same day compounds it), but requiring two real contributions means
    # there is nothing to replay unless the candidate genuinely spoke.
    own_points = sum(1 for t in request.history if t.speaker == _YOU and t.text.strip())
    if own_points >= 2:
        await record_round(
            db,
            user_id=current_user.user_id,
            session_id=None,
            kind="gd",
            tier=Tier.CORE,
            # The GD evaluator scores out of 10; the rating engine works out of 100.
            score_out_of_100=float(evaluation.overall_score) * 10,
            topics=[request.topic],
        )
    await db.commit()

    return GDEvaluateResponse(**evaluation.model_dump())
