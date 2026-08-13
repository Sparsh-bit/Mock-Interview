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

import asyncio
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
from app.services.tts.base import TONE_PROSODY

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/panel", tags=["Interview Panel"])

#: How long the code verdict may take before the panel speaks without one.
#:
#: Much tighter than /code/analyse's 45s, and for a different reason than cost. That endpoint
#: renders a review the candidate is sitting and reading; this one sits between them hitting
#: submit and anybody in the room saying anything. Silence is the failure mode here, so the
#: budget is set to what a pause between "okay, let me look" and the response can absorb.
#: Past that, an ungrounded review now beats a grounded one later.
_CODE_VERDICT_BUDGET_SECONDS = 18.0


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
    stage: str = Field(
        default="mid",
        pattern=(
            "^(opening|skill_check|mid|follow_up|pivot|code_review|wrapping"
            "|candidate_questions|answering_candidate)$"
        ),
    )
    #: The question the orchestrator chose. Empty for stages that do not ask one.
    question: str = Field(default="", max_length=2000)
    # NOTE: the last answer and the concepts a correct answer covers are NOT accepted from
    # the client. They are read from the database using session_id — see _last_exchange.
    #
    # Two reasons, and the second is the important one. The client would have to be given the
    # bank's expected answer to send it back, which is the answer key; and a correction is
    # only worth anything if it is grounded in what the question actually wanted, so letting
    # the caller supply that would let a wrong "correction" be produced by a wrong caller.
    #: What the candidate asked, for the answering_candidate stage.
    candidate_question: str = Field(default="", max_length=1000)
    candidate_name: str = Field(default="", max_length=80)
    #: For code_review: which language the compiler was set to. The code itself is NOT sent —
    #: it is the last answer, read from the database like everything else here.
    language: str = Field(default="", max_length=20)


class PanelTurnResponse(BaseModel):
    turns: list[dict]
    asked_question: bool
    #: For the pivot stage: the topic the panel offered to move to.
    #:
    #: Returned rather than sent, because the SERVER chooses it — it is the only side that
    #: knows what this session has already covered, and a client-chosen pivot could offer a
    #: candidate the topic they just failed.
    pivot_topic: str = ""


async def _last_exchange(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[str, str]:
    """
    The candidate's most recent answer, and what a correct answer to THAT question covers.

    Read server-side rather than accepted from the client. The expected concepts are the
    bank's answer key — handing them to the browser so it can hand them back would put the
    answers in the page for anyone who opens dev tools, and a correction grounded in
    caller-supplied "expectations" is a correction a caller can make wrong.

    Scoped by user_id as well as session_id. Every read in this app is, since the bug that
    quoted one candidate's words at another; a panel that corrected somebody using a
    different candidate's answer would be that same defect wearing a new hat.

    Returns empty strings when there is no previous answer — the opening question, or a
    session whose first answer has not landed. The prompt is explicit that it must not invent
    a correction in that case.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.question import Question  # noqa: PLC0415
    from app.models.session import Answer, InterviewSession  # noqa: PLC0415

    owns = await db.scalar(
        select(InterviewSession.id).where(
            InterviewSession.id == session_id, InterviewSession.user_id == user_id
        )
    )
    if not owns:
        return "", ""

    row = (
        await db.execute(
            select(Answer.content, Question.expected_keywords, Question.ideal_answer)
            .join(Question, Question.id == Answer.question_id)
            .where(Answer.session_id == session_id)
            .order_by(Answer.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return "", ""

    content, keywords, ideal = row
    expected_parts: list[str] = []
    if keywords:
        expected_parts.append("Key concepts: " + ", ".join(str(k) for k in keywords))
    if ideal:
        expected_parts.append(str(ideal))
    return (content or ""), "\n".join(expected_parts)


#: Bug severity, worst first. Used to pick the ONE bug a spoken review mentions.
_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "style": 3}


def summarise_code_verdict(evaluation: object) -> str:
    """
    A full CodingEvaluation, reduced to something a panelist can say in one breath.

    Separate from `_code_verdict` and public so it can be tested without a database or a
    model, because this is where the judgement lives — the rest of that function is a scoped
    read and an AI call.

    THE PANEL HAS A 320-TOKEN OUTPUT BUDGET AND IS MEANT TO SAY TWO SENTENCES. A CodingEvaluation
    carries four scores, every bug, every missed edge case, strengths, improvements and
    follow-ups. Handing all of that to a model that is trying to sound like a person in a room
    is how the panel started lecturing, which is a regression this codebase has already had to
    fix once. So this keeps only what one spoken correction can stand on: whether it is right,
    what the worst thing wrong with it is, and whether the approach was good enough.
    """
    from app.services.ai.schemas import CodingEvaluation  # noqa: PLC0415

    if not isinstance(evaluation, CodingEvaluation):
        return ""

    parts = [
        f"Correctness: {evaluation.correctness_level.replace('_', ' ')} "
        f"({evaluation.correctness_score:.0f}/10).",
        f"Approach: {evaluation.approach.replace('_', ' ')}"
        + ("" if evaluation.is_brute_force_sound else " (and it does not hold up)")
        + ".",
        evaluation.summary.strip(),
    ]
    if evaluation.bugs:
        # THE MOST SERIOUS BUG, not the first one the model happened to list. Order in that
        # list is not meaningful, and a spoken review gets exactly ONE — leading with a style
        # nit while a critical defect goes unmentioned is how a review sounds thorough and is
        # useless. A list read aloud is a document, not a correction.
        worst = min(evaluation.bugs, key=lambda b: _SEVERITY_ORDER.get(b.severity, 9))
        parts.append(f"Main bug ({worst.severity}): {worst.description}")
    if evaluation.edge_cases_missed:
        parts.append(f"Edge case missed: {evaluation.edge_cases_missed[0]}")
    if evaluation.time_complexity and evaluation.optimal_time_complexity:
        if evaluation.time_complexity != evaluation.optimal_time_complexity:
            parts.append(
                f"Complexity: theirs is {evaluation.time_complexity}, "
                f"optimal is {evaluation.optimal_time_complexity}."
            )
        else:
            parts.append(f"Complexity {evaluation.time_complexity} — optimal.")

    return " ".join(p for p in parts if p)


async def _code_verdict(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, language: str
) -> str:
    """
    An actual graded verdict on the code the candidate just submitted, for the panel to
    speak from.

    WHY THIS EXISTS. The `code_review` stage already put the submission in front of the model
    and asked it to write dialogue about it. That is not the same thing as reviewing it, and
    the difference was audible: the panel said something plausible about the code without ever
    establishing whether it WORKS. Reported as the interviewer "not analysing the solution",
    which was accurate — a coding round where nobody checks the answer is theatre.

    Meanwhile the product already had a real evaluator. `coding_evaluator.md` and the
    `CodingEvaluation` schema grade correctness on a four-point scale, name the specific bugs,
    compare the complexity reached against the optimal one, and judge whether a brute force is
    a legitimate pass. It was reachable only from `/code/analyse`, which the interview never
    called. This routes the interview through it.

    GROUNDED THE SAME WAY A CORRECTION IS. Nothing here is accepted from the client except the
    language the editor was set to: the code and the problem are read back out of the database
    under the same user-scoped ownership check as `_last_exchange`, so a review cannot be
    produced against code the candidate did not submit, and the verdict cannot be steered by a
    caller. Only the LANGUAGE comes from the browser, and it is only a hint to the evaluator.

    RETURNS A SHORT STRING BECAUSE THE PANEL SPEAKS IT. The full evaluation is a large object;
    a panel with a 320-token budget that is meant to say two sentences cannot use it, and
    handing over the whole thing is how the panel started lecturing before. Correctness, the
    single most important bug, and the complexity gap is what one spoken correction needs.

    FAILS SOFT TO "". Every failure — no submission, unsupported language, the model being
    slow or down — returns empty, and the brief then tells the panel it has no verdict and
    must not invent one. A coding round with an ungrounded review is a worse product; a coding
    round that 500s because the reviewer was slow is a broken one.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.models.question import Question  # noqa: PLC0415
    from app.models.session import Answer, InterviewSession  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import CodingEvaluation  # noqa: PLC0415

    owns = await db.scalar(
        select(InterviewSession.id).where(
            InterviewSession.id == session_id, InterviewSession.user_id == user_id
        )
    )
    if not owns:
        return ""

    row = (
        await db.execute(
            select(Answer.content, Question.content, Question.difficulty)
            .join(Question, Question.id == Answer.question_id)
            .where(Answer.session_id == session_id)
            .order_by(Answer.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return ""

    source, problem, difficulty = row
    source = (source or "").strip()
    # Below this it is not a submission — it is an empty editor or a candidate who typed a
    # sentence instead of code. Reviewing that produces a confident verdict about nothing.
    if len(source) < 20:
        return ""

    lang = (language or "").lower().strip() or "java"

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="coding_evaluator",
        user_content=f"Review this {lang} submission:\n\n```{lang}\n{source}\n```",
        language=lang,
        problem_title="Interview coding question",
        problem_description=(problem or "(not provided — infer it from the code)"),
        difficulty=str(difficulty or "medium"),
        # The interview does not run the code before reviewing it. Saying "(not run)" rather
        # than leaving these blank matters: the evaluator prompt reasons about stdout when it
        # has it, and an empty string reads as "it produced no output", which is a different
        # and much worse claim than "nobody executed this".
        stdout="(not run)",
        stderr="(none)",
    )

    try:
        evaluation, _ = await asyncio.wait_for(
            generate_structured(
                CodingEvaluation,
                messages,
                max_tokens=1200,
                # One attempt. This sits between the candidate submitting and the panel
                # speaking, so a retry costs more silence than a missing verdict does.
                attempts_per_provider=1,
                cost_tier=CostTier.BALANCED,
                context="panel_code_review",
            ),
            timeout=_CODE_VERDICT_BUDGET_SECONDS,
        )
    except (AIProviderUnavailableError, TimeoutError, ValueError):
        logger.warning("panel_code_verdict_unavailable", session_id=str(session_id), language=lang)
        return ""

    return summarise_code_verdict(evaluation)


async def _pivot_topic(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """
    A topic to offer a candidate who just said they do not know this one.

    THE RULES THAT MATTER, in order of how badly getting them wrong would hurt:

    1. NOT A TOPIC THEY HAVE ALREADY BEEN ASKED. Offering somebody the subject they failed
       two questions ago, as a lifeline, is worse than not offering one.
    2. A topic the bank can actually source questions for. A pivot to something with no
       questions behind it is a dead end mid-interview — so this only ever returns names
       that appear in java_fundamentals, never anything invented.
    3. Foundational first. The point of the pivot is to find ground the candidate can stand
       on, so it walks an explicitly easy-to-hard order rather than picking at random.

    Returns "" when everything is exhausted, and the caller then simply does not pivot —
    which is the honest outcome, not a failure.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.question import Question  # noqa: PLC0415
    from app.models.session import Answer, InterviewSession  # noqa: PLC0415

    owns = await db.scalar(
        select(InterviewSession.id).where(
            InterviewSession.id == session_id, InterviewSession.user_id == user_id
        )
    )
    if not owns:
        return ""

    rows = (
        await db.execute(
            select(Question.topic_id, Question.content)
            .join(Answer, Answer.question_id == Question.id)
            .where(Answer.session_id == session_id)
        )
    ).all()
    # Matched on the question TEXT rather than the topic row, because bank questions and
    # generated ones do not share a topic table consistently — and a pivot that repeats a
    # subject because two ids differed would be the exact failure rule 1 is about.
    seen_text = " ".join((r[1] or "") for r in rows).lower()

    # ROLE-APPROPRIATE, which matters more here than anywhere else. A pivot is offered to
    # somebody who has just admitted they do not know something, so offering a Deloitte
    # Analyst "JVM, JDK & JRE" as a lifeline is worse than offering nothing — it tells them
    # the panel has not understood what they applied for, at the moment they are already
    # uncomfortable.
    from app.models.company import Company, InterviewTrack  # noqa: PLC0415

    role = (
        await db.execute(
            select(InterviewTrack.name, Company.name)
            .join(InterviewSession, InterviewSession.track_id == InterviewTrack.id)
            .join(Company, Company.id == InterviewTrack.company_id)
            .where(InterviewSession.id == session_id)
        )
    ).first()
    track_name = role[0] if role else ""
    company_name = role[1] if role else ""

    for topic in _pivot_order_for(track_name, company_name):
        if topic.lower() in seen_text:
            continue
        return topic
    return ""


def _pivot_order_for(track_name: str, company_name: str) -> list[str]:
    """
    Topics to offer this role, easiest first.

    For a Java role, the curated bank's own topics — those are questions we can actually
    source, which is the constraint that stops a pivot becoming a dead end.

    For anything else, what the company itself says it assesses. Those come from the
    catalogue, are validated to sum to 100, and are ordered by weight — so the first thing
    offered is the thing this employer cares most about, which is also the thing the
    candidate is most likely to have prepared.
    """
    from app.data import java_fundamentals  # noqa: PLC0415
    from app.services.interview.orchestrator import _is_java_role  # noqa: PLC0415
    from app.services.interview.research_lookup import slugify  # noqa: PLC0415
    from app.services.prep import get_company  # noqa: PLC0415

    if _is_java_role(track_name, ""):
        return [t for t in _PIVOT_ORDER if t in java_fundamentals.ALL_TOPICS]

    slug = slugify(company_name)
    entry = get_company(slug) or get_company(slug.replace("-", ""))
    if entry and entry.topics:
        ranked = sorted(entry.topics, key=lambda t: -t.weight)
        # HR and behavioural topics are dropped: a pivot is meant to find technical ground
        # the candidate can stand on, and "shall we talk about your project instead?" reads
        # as giving up on the technical round rather than adapting it.
        return [
            t.name
            for t in ranked
            if not any(k in t.name.lower() for k in ("hr", "behavioural", "behavioral"))
        ]
    # No catalogue entry. These are the areas every Indian campus technical round covers
    # whatever the role is, so they are safe to offer without knowing the employer.
    return [
        "Programming fundamentals",
        "DBMS & SQL",
        "Data structures",
        "OOP concepts",
        "Operating systems",
    ]


#: Easiest first, FOR A JAVA ROLE. A candidate who has just admitted they do not know
#: something is not helped by being offered Hibernate next; they are helped by being offered
#: OOP, which every CS student in the country has covered. The order is the pedagogy.
#:
#: Non-Java roles do not use this list at all — see _pivot_order_for.
_PIVOT_ORDER: list[str] = [
    "OOP & class design",
    "Strings & the String pool",
    "Collections framework",
    "Exception handling",
    "JVM, JDK & JRE",
    "Memory: stack & heap",
    "Java 8 & lambdas",
    "Multithreading",
    "SOLID principles",
    "Spring Boot",
]


async def _should_use_name(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, stage: str
) -> bool:
    """
    Should the panel say the candidate's name in THIS turn?

    DECIDED HERE BECAUSE THE MODEL CANNOT DECIDE IT. Every turn is a separate stateless call
    with no memory of the last one, so an instruction like "don't use their name if you used
    it last turn" is unfollowable — the model has no way to know. Told only to use names
    sparingly, it reached for one every single question, and reported back as: "it is calling
    the name again and again in every question that feels annoying".

    The rule a real panel follows: at hello, at goodbye, and otherwise only now and then. So:
    the social stages always, and during the questions roughly one in three.

    Counting answers rather than turns keeps it stable — a pivot or a code review in the
    middle of a question must not shift the rhythm, because those are the same moment
    continuing rather than a new one.
    """
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.models.session import Answer, InterviewSession  # noqa: PLC0415

    # The moments where a name is what a person would actually say: greeting them, wrapping
    # up, asking whether they have questions, and answering the one they asked.
    if stage in {"opening", "skill_check", "wrapping", "candidate_questions", "answering_candidate"}:
        return True

    owns = await db.scalar(
        select(InterviewSession.id).where(
            InterviewSession.id == session_id, InterviewSession.user_id == user_id
        )
    )
    if not owns:
        return False

    answered = (
        await db.scalar(
            select(func.count()).select_from(Answer).where(Answer.session_id == session_id)
        )
        or 0
    )
    # Every third answered question. Not random: the same candidate replaying the same
    # session should get the same rhythm, and a coin flip per turn would sometimes produce
    # three in a row, which is the exact thing being fixed.
    return answered % 3 == 0


async def _role_for_session(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """
    Which job this interview is for, as one line for the prompt.

    Read from the session's track rather than accepted from the client, for the same reason
    everything else here is: it is what the orchestrator planned the interview against, and a
    caller-supplied role could put the panel and the questions in different jobs.

    Falls back to a neutral line rather than an empty one — a prompt slot that says nothing
    invites the model to assume, and what it assumes is Java.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.session import InterviewSession  # noqa: PLC0415

    row = (
        await db.execute(
            select(InterviewTrack.name, Company.name)
            .join(InterviewSession, InterviewSession.track_id == InterviewTrack.id)
            .join(Company, Company.id == InterviewTrack.company_id)
            .where(InterviewSession.id == session_id, InterviewSession.user_id == user_id)
        )
    ).first()
    if not row:
        return "a general software engineering fresher role"
    track_name, company_name = row
    return f"{track_name} at {company_name}"


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
    last_answer, last_expected = await _last_exchange(
        db, request.session_id, current_user.user_id
    )

    # Chosen server-side, and only for the stage that uses it — see _pivot_topic for why the
    # client is not allowed to pick. An empty string means there is nothing left to offer,
    # and the prompt is told to close the topic out rather than invent one.
    role_line = await _role_for_session(db, request.session_id, current_user.user_id)
    use_name = await _should_use_name(db, request.session_id, current_user.user_id, request.stage)

    pivot_topic = ""
    if request.stage == "pivot":
        pivot_topic = await _pivot_topic(db, request.session_id, current_user.user_id)

    code_verdict = ""
    if request.stage == "code_review":
        code_verdict = await _code_verdict(
            db, request.session_id, current_user.user_id, request.language
        )

    brief = "\n".join(
        [
            "## This moment",
            "",
            "### The panel",
            _render_panel(),
            "",
            f"### The candidate\n{name}",
            "",
            # THE ROLE, in every turn. Without it the panel has no idea what job this is
            # and defaults to Java — which is how an Analyst ended up being asked to rate
            # themselves in a language their role never touches.
            f"### The role they are interviewing for\n{role_line}",
            "",
            "### Using their name this turn",
            (
                "YES — use the candidate's name once in this turn."
                if use_name
                else "NO. Do NOT use the candidate's name anywhere in this turn. You used it "
                "recently and repeating it every question is the single most artificial "
                "thing this panel does. Address them without it."
            ),
            "",
            f"### Stage\n{request.stage}",
            "",
            f"### The question to put\n{request.question or '(none for this stage)'}",
            "",
            f"### What the candidate last said\n{last_answer or '(nothing yet)'}",
            "",
            "### What a correct answer to THAT last question covers",
            last_expected or "(not available — do not invent a correction)",
            "",
            f"### What the candidate just asked you\n{request.candidate_question or '(nothing)'}",
            "",
            f"### Topic to offer instead (pivot stage only)\n{pivot_topic or '(none available)'}",
            "",
            (
                "### The code they submitted (code_review stage only)\n"
                + (
                    f"Language: {request.language or 'unknown'}. The code is what they last "
                    "said, above."
                    if request.stage == "code_review"
                    else "(not a code review)"
                )
            ),
            "",
            # The graded verdict, kept as its own section rather than folded into the block
            # above, because it is a DIFFERENT kind of thing: the code is what the candidate
            # wrote, this is what an evaluator concluded about it. The panel must speak from
            # the conclusion and not re-derive one, for the same reason a correction speaks
            # from the bank's answer key rather than from the model's recollection.
            "### The verdict on that code (code_review stage only)",
            (
                code_verdict
                or (
                    "(not available — say what you can about the code as written, and do NOT "
                    "state whether it is correct, whether it compiles, or what its complexity "
                    "is. You have not been told any of those things.)"
                    if request.stage == "code_review"
                    else "(not a code review)"
                )
            ),
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
            # 320, down from 500, and the ceiling is doing real work rather than just
            # capping cost: the panel was lecturing — three-sentence corrections that
            # explained the concept the candidate had just got wrong — and a budget that
            # comfortably fits a lecture is an invitation to write one. Four short spoken
            # lines plus the JSON scaffolding is about 220 tokens, so this leaves headroom
            # without leaving room for a paragraph.
            #
            # It cannot truncate a response into a failure that costs the candidate anything:
            # a cut-off body fails JSON validation, generate_structured retries, and a second
            # failure returns no turns at all — which the caller already handles by showing
            # the question on its own.
            max_tokens=320,
            # TWO ATTEMPTS, NOT ONE.
            #
            # One attempt meant any single hiccup — a truncated body, a stray prose
            # preamble, one malformed field — produced no turns at all, and the candidate
            # dropped to the bare-question fallback. Reported as "sometimes the old UI comes
            # in with the different question", and "different" is the giveaway: the fallback
            # shows the bank's own wording, while the panel would have rephrased it, so a
            # silent failure looks like being asked something else entirely.
            #
            # A retry is cheap here in a way it is not elsewhere: the system block is cached,
            # so a second attempt bills a few hundred fresh tokens rather than three thousand.
            attempts_per_provider=2,
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
        return PanelTurnResponse(turns=[], asked_question=False, pivot_topic=pivot_topic)

    # Only real panel members may speak. The model must never be able to put words in the
    # candidate's mouth — the same guard the GD panel carries, for the same reason.
    # Nothing usable. Logged rather than silently degraded, because this is invisible from
    # the outside — the interview carries on and only the wording changes — so without a log
    # line there is no way to tell a provider problem from a prompt that stopped working.
    if not turn.turns:
        logger.warning(
            "panel_turn_empty",
            session_id=str(request.session_id),
            stage=request.stage,
            reason="the model returned no usable turns; the caller falls back to the "
            "bare question",
        )

    valid = [
        {
            "speaker": c.speaker,
            "text": c.text.strip(),
            # Re-checked here rather than trusted: this is what the browser hands straight
            # back to /tts/speak, and an unrecognised name there would silently become
            # neutral anyway. Normalising at the boundary means the tone in the transcript
            # is the tone that was actually spoken.
            "tone": c.tone if c.tone in TONE_PROSODY else "neutral",
        }
        for c in turn.turns
        if c.text.strip() and c.speaker in INTERVIEWER_NAMES
    ][:4]

    return PanelTurnResponse(
        turns=valid,
        asked_question=turn.asked_question and bool(valid),
        pivot_topic=pivot_topic,
    )
