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
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys, cache_get, cache_set, get_redis
from app.db.session import get_db
from app.services.ai.base_provider import ProviderMessage
from app.services.ai.schemas import InterviewPanelTurn
from app.services.interview import context
from app.services.interview.context import InterviewContext
from app.services.interview.open_domain import OpenDomain
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


class PanelInfo(BaseModel):
    """
    Who is on the panel, and what kind of interview this is.

    `technical` exists so the UI can stop showing a code editor to a sales candidate. It is
    resolved from the role by `domains.is_technical` — the same classification the planner
    uses to decide what to ask and the panel uses to decide what to call itself — rather than
    being a fourth opinion about what a role is.
    """

    interviewers: list[Interviewer]
    technical: bool


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

#: Canonical spelling by lowercase name, so a speaker can be recognised however it was written.
_CANONICAL_SPEAKER: dict[str, str] = {name.lower(): name for name in INTERVIEWER_NAMES}

#: Punctuation a model puts on the END of a speaker label. "Priya:" is Priya with a colon on
#: her, not a different person.
_SPEAKER_PUNCTUATION = " \t:-—–.,"


def canonical_speaker(name: str) -> str | None:
    """
    Map whatever the model wrote in `speaker` onto the panel name it meant — or None.

    THIS IS THE FIX FOR "priya is not speaking", and the shape of that bug is worth keeping
    written down, because it is a class of bug rather than one instance.

    The contribution filter used to be `c.speaker in INTERVIEWER_NAMES`: an exact,
    case-sensitive membership test. A model that answered with "priya", "PRIYA", "Priya " or
    "Priya:" had done exactly what the prompt asked — it names the panel and says to use those
    names — and its contribution was DISCARDED. Silently. No log, no fallback, no trace
    anywhere except a candidate noticing that one of the two interviewers never spoke.

    IT FAILS ASYMMETRICALLY, which is why it presents as "one person went quiet" rather than
    "the panel is broken". Whichever name the model happens to capitalise consistently keeps
    working; the other one disappears. Nothing else about the interview looks wrong.

    AND THE CANONICAL SPELLING IS RETURNED, not the input. The browser hands this name straight
    back to /tts/speak to resolve a voice, and it goes into the stored transcript and into the
    report. Passing "priya" through would mean a real name on screen was lowercase, and while
    `panel_voice_id` happens to lowercase its own lookup, relying on that would make every
    downstream consumer responsible for a normalisation this boundary should have done once.
    """
    key = (name or "").strip(_SPEAKER_PUNCTUATION).strip().lower()
    return _CANONICAL_SPEAKER.get(key)

#: Panel dialogue is a CHEAP call and it runs on every question, so it needs its own ceiling
#: separate from the interview limit. A 12-question interview with corrections and a closing
#: sequence is roughly 16 of these.
_panel_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_ai(user_id),
    action="the interview panel speaking",
)


def panel_for(role_title: str = "", open_profile: OpenDomain | None = None) -> list[Interviewer]:
    """
    The panel, with DESIGNATIONS THAT MATCH THE JOB.

    Names, genders and dispositions are fixed — they are tied to the voice ids and to how the
    two of them behave in the room, and there is no reason a sales panel should be paced
    differently from an engineering one. What changes is what they *are*: a sales candidate is
    interviewed by a Regional Sales Manager and an Area Sales Lead, not by a "Senior
    Engineering Manager" and a "Technical Lead".

    This is not cosmetic. The designation is in the prompt the panel is written from and on the
    chip the candidate reads, so a hardcoded engineering title tells them in the first second
    that the simulation does not know which job they applied for — and it pulls the model
    toward technical questions in a role that has none.
    """
    from app.data import domains  # noqa: PLC0415

    # A GENERATED PROFILE WINS, because it is the one that was resolved for THIS field.
    # `profile_for` falls through to the software profile for anything unmatched, so without
    # this a sommelier is interviewed by a "Senior Engineering Manager" and a "Technical
    # Lead" — the exact tell this function was written to remove, reached by a role the
    # keyword list happens not to name rather than by one it names wrongly.
    if open_profile is not None:
        designations = (open_profile.lead_role, open_profile.specialist_role)
    else:
        profile = domains.profile_for(role_title, "")
        designations = (profile["lead_role"], profile["specialist_role"])
    return [
        Interviewer(
            name=i.name,
            gender=i.gender,
            role=designation,
            disposition=i.disposition,
        )
        for i, designation in zip(INTERVIEWERS, designations, strict=True)
    ]


def _rating_subject(ctx: InterviewContext) -> str:
    """
    What the panel asks the candidate to rate themselves on.

    THE SALES BUG. The prompt used to reason from the role title itself, and every branch it
    offered was technical — Java, or "programming fundamentals" when it could not tell. A
    sales role fell into that last branch and got asked to rate itself in Java, which tells a
    candidate in the first ten seconds that the simulation does not know what job they
    applied for.

    No prompt wording fixes that, because the model is not the thing that knows. `domains.py`
    is: it already resolves a role title to one of twelve families, each with a validated
    topic weighting, and the orchestrator already plans the interview from it. Deciding the
    subject HERE and handing the model a noun is the same fix, in the same place, as
    `_render_panel` resolving the panel's designations rather than inventing them.

    Falls back to a phrase with no technology in it. A rating question that names no subject
    is odd; one that names the wrong subject is disqualifying.
    """
    from app.data import domains  # noqa: PLC0415
    from app.services.interview.orchestrator import _is_java_role  # noqa: PLC0415

    # A NON-TECHNICAL ROLE IS NEVER ASKED TO RATE ITSELF IN A LANGUAGE, whatever its title
    # happens to contain. Checked before the Java branch rather than after, because "Sales
    # Engineer" and "Solutions Consultant" both contain words that trip a keyword test.
    if ctx.is_technical and _is_java_role(ctx.role, ""):
        return "Java"

    # RESOLVED FOR THIS FIELD, so it beats both branches below. The model was asked for a
    # phrase that reads naturally in "how would you rate yourself in ___", which is a
    # judgement about the field and exactly what the fall-through at the bottom of this
    # function admits it cannot make.
    if ctx.open_domain is not None:
        return ctx.open_domain.rating_subject

    if ctx.domain_matched:
        profile = domains.profile_for(ctx.role, "")
        # The heaviest topic in the family is what the role is really screened on, and it is
        # already weighted for exactly this reason. Sales opens on prospecting and objection
        # handling; mechanical on design and thermodynamics.
        top = max(profile["topics"], key=lambda t: t[1])[0]
        if ctx.is_technical:
            return top
        # For a non-technical role the family label reads better out loud than its top topic
        # — "how would you rate yourself in sales and business development" is a question a
        # person asks; "in prospecting and pipeline" is a form field.
        return profile["label"]

    return "the core skills for this role"


def _render_panel(role_title: str = "", open_profile: OpenDomain | None = None) -> str:
    return "\n".join(
        f"- {i.name} ({i.gender}, {i.role}): {i.disposition}"
        for i in panel_for(role_title, open_profile)
    )


class PanelTurnRequest(BaseModel):
    session_id: uuid.UUID
    #: Where the interview is. Drives which behaviour the prompt follows.
    stage: str = Field(
        default="mid",
        pattern=(
            "^(opening|skill_check|mid|follow_up|pivot|off_script|code_review|wrapping"
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
    #: For the skill_check stage: what the panel asked them to rate themselves on.
    #:
    #: Returned rather than parsed back out of what was said, for the same reason pivot_topic
    #: is: the server chose it, and the client needs to record it alongside the number so the
    #: report can say "they rated their own sales ability 7/10" rather than guessing which
    #: subject a bare 7 refers to.
    rating_subject: str = ""
    #: For the pivot stage: the topic the panel offered to move to.
    #:
    #: Returned rather than sent, because the SERVER chooses it — it is the only side that
    #: knows what this session has already covered, and a client-chosen pivot could offer a
    #: candidate the topic they just failed.
    pivot_topic: str = ""
    #: The panel's read of what the CANDIDATE last said — "answered", "off_topic",
    #: "unintelligible", "other_language", "asked_us" or "adversarial".
    #:
    #: Surfaced rather than kept internal because it is the only account anything downstream
    #: has of a turn that was not an answer. `off_script.classify` catches the one case that
    #: must not consume a question and is deliberately narrow; the other four are semantic and
    #: only the model can see them. Defaults to "answered" everywhere, including when the
    #: panel could not be generated at all — asserting that somebody did not answer is a claim
    #: worth having evidence for.
    candidate_turn: str = "answered"


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
    except (AIProviderUnavailableError, TimeoutError, ValueError) as exc:
        # Three different failures shared one message: a provider outage, a slow response and a
        # malformed one. They want different responses and read identically without this.
        logger.warning(
            "panel_code_verdict_unavailable",
            session_id=str(session_id),
            language=lang,
            error_type=type(exc).__name__,
            error=str(exc) or type(exc).__name__,
        )
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
    # The SAME resolved context the rest of this module uses. Reading the catalogue track
    # here — as this used to — is how a sales candidate got offered "JVM, JDK & JRE" as the
    # thing to talk about instead.
    ctx = await context.resolve(db, session_id, user_id)

    for topic in _pivot_order_for(ctx):
        if topic.lower() in seen_text:
            continue
        return topic
    return ""


def _pivot_order_for(ctx: InterviewContext) -> list[str]:
    """
    Topics to offer this role, easiest first.

    For a Java role, the curated bank's own topics — those are questions we can actually
    source, which is the constraint that stops a pivot becoming a dead end.

    For anything else, what the company itself says it assesses. Those come from the
    catalogue, are validated to sum to 100, and are ordered by weight — so the first thing
    offered is the thing this employer cares most about, which is also the thing the
    candidate is most likely to have prepared.
    """
    from app.data import domains, java_fundamentals  # noqa: PLC0415
    from app.services.interview.orchestrator import _is_java_role  # noqa: PLC0415
    from app.services.interview.research_lookup import slugify  # noqa: PLC0415
    from app.services.prep import get_company  # noqa: PLC0415

    if ctx.is_technical and _is_java_role(ctx.role, ""):
        return [t for t in _PIVOT_ORDER if t in java_fundamentals.ALL_TOPICS]

    # THE FIELD'S OWN AREAS, heaviest first. Checked before every branch below because all of
    # them are guesses about a role nobody authored: the non-technical branch would offer a
    # sommelier "Situational judgement", and the technical one would offer a firmware
    # candidate "Programming fundamentals, DBMS & SQL". A pivot is the moment a candidate has
    # just admitted a gap, so it is the worst moment to hand them a topic from another field.
    if ctx.open_domain is not None:
        return ctx.open_domain.pivot_topics()

    # A NON-TECHNICAL ROLE GETS ITS OWN DOMAIN'S TOPICS, not the company's assessment
    # weighting. Morani Plastics is not in the catalogue and never will be — the employer
    # here is whoever the candidate typed — but "sales" is a domain we know how to interview
    # for, and offering prospecting or objection handling is a real lifeline where offering
    # "Aptitude & Case Reasoning" from some IT firm's syllabus is not.
    if not ctx.is_technical:
        # AN UNMATCHED ROLE MUST NOT FALL BACK TO THE SOFTWARE PROFILE. `profile_for` resolves
        # to the default domain when nothing matches, and the default is software — so a
        # candidate who told us this is NOT a technical interview would be offered "Data
        # Structures" as their lifeline. The explicit toggle makes this reachable: it is
        # exactly the UPSC and civil-services case, where the title matches no domain and the
        # candidate has said outright that it is not technical.
        # THE CANDIDATE'S STATEMENT BEATS THE KEYWORD MATCH, and this is the general form of
        # the same lesson. If they have said this is not technical and the matched domain IS a
        # technical one, the match is simply wrong — "Civil Services" matching civil
        # ENGINEERING is the case that found it. Trusting the match over the person would mean
        # offering a UPSC aspirant structural design.
        if not ctx.domain_matched or domains.is_technical(ctx.role, ""):
            return list(_GENERAL_NON_TECHNICAL_TOPICS)

        profile = domains.profile_for(ctx.role, "")
        return [
            name
            for name, _weight in sorted(profile["topics"], key=lambda t: -t[1])
            if not any(k in name.lower() for k in ("hr", "behavioural", "behavioral"))
        ]

    # A TECHNICAL ROLE THAT IS NOT A SOFTWARE ROLE GETS ITS OWN FIELD. Mechanical, civil,
    # electrical and chemical are all technical and none of them is asked about DBMS — but
    # this branch went straight from "not a Java role" to the company catalogue and then to a
    # computer-science fallback, so a civil engineer was offered "Programming fundamentals".
    # The domain knows better than the fallback whenever it actually matched.
    if ctx.domain_matched and ctx.domain != "software":
        profile = domains.profile_for(ctx.role, "")
        return [
            name
            for name, _weight in sorted(profile["topics"], key=lambda t: -t[1])
            if not any(k in name.lower() for k in ("hr", "behavioural", "behavioral"))
        ]

    slug = slugify(ctx.company)
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


#: What to offer a non-technical candidate whose role matched no domain we know.
#:
#: Deliberately about reasoning and communication rather than any field's syllabus — these
#: are what every non-technical interview in the country actually probes, and none of them
#: assumes an industry. A UPSC aspirant, a hotel-management fresher and a logistics trainee
#: can all be asked about any of them without the question landing as absurd.
_GENERAL_NON_TECHNICAL_TOPICS: tuple[str, ...] = (
    "Situational judgement",
    "Communication & clarity",
    "Current affairs & awareness",
    "Analytical reasoning",
    "Ethics & decision-making",
)

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


async def _context(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> InterviewContext:
    """
    What this interview is for. Delegates to the ONE resolver.

    This used to be `_role_for_session`, and it joined InterviewTrack and Company — the
    catalogue track the session row points at. That is not what the candidate asked for: the
    setup form preselects the first track when they do not pick one, so anybody typing their
    own employer got an arbitrary IT-services track. A sales interview for Morani Plastics
    was greeted as an "Advanced ASE role at Accenture", with a code editor.

    Everything in this module now reads the same context, so the greeting, the designations,
    the rating subject, the pivot topics and the editor cannot disagree with each other or
    with the plan.
    """
    return await context.resolve(db, session_id, user_id)


@router.get("/interviewers", summary="Who is on the panel")
async def get_interviewers(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    session_id: uuid.UUID | None = None,
) -> PanelInfo:
    """
    The panel for this session, designations included, plus whether this is a technical role.

    `session_id` is optional and the role is read from the session's own track, never accepted
    from the caller — the same rule as everywhere else here, so the chip the candidate reads
    cannot disagree with the panel the prompt was written from. Without it the caller gets the
    default designations.

    `technical` defaults to TRUE when there is no session to resolve. A missing code editor in
    a technical interview costs the candidate the question; a spurious one in a sales
    interview is only clutter. When we do not know, the more forgiving failure is the one to
    take.
    """
    if session_id is None:
        return PanelInfo(interviewers=INTERVIEWERS, technical=True)

    ctx = await _context(db, session_id, current_user.user_id)
    # Both read from the same resolved context, so the chip the candidate sees, the panel the
    # prompt was written from, and the presence of the editor cannot disagree.
    return PanelInfo(interviewers=panel_for(ctx.role, ctx.open_domain), technical=ctx.is_technical)


@dataclass(frozen=True, slots=True)
class _TurnContext:
    """
    Everything both turn endpoints need before a model call, resolved once.

    EXTRACTED BECAUSE THERE ARE NOW TWO ENDPOINTS AND THERE MUST STILL BE ONE ANSWER. The
    streaming turn and the whole turn are the same turn delivered differently: same brief,
    same prompt, same cache key, same pivot topic, same rating subject. Two copies of a
    hundred and thirty lines of brief assembly would be two briefs that drift, and the drift
    would be invisible — both endpoints would keep working, and the panel would simply behave
    slightly differently depending on which one the browser happened to call.
    """

    messages: list[ProviderMessage]
    turn_key: str
    pivot_topic: str
    rating_subject: str


async def _turn_context(
    db: AsyncSession, request: PanelTurnRequest, user_id: uuid.UUID
) -> _TurnContext:
    """Build the prompt, the cache key and the server-chosen values for one turn."""
    from app.api.v1.gd import _candidate_name  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415

    name = _candidate_name(request.candidate_name)
    last_answer, last_expected = await _last_exchange(
        db, request.session_id, user_id
    )

    # Chosen server-side, and only for the stage that uses it — see _pivot_topic for why the
    # client is not allowed to pick. An empty string means there is nothing left to offer,
    # and the prompt is told to close the topic out rather than invent one.
    ctx = await _context(db, request.session_id, user_id)
    role_line = ctx.role_line
    rating_subject = _rating_subject(ctx)
    use_name = await _should_use_name(db, request.session_id, user_id, request.stage)

    pivot_topic = ""
    if request.stage == "pivot":
        pivot_topic = await _pivot_topic(db, request.session_id, user_id)

    code_verdict = ""
    if request.stage == "code_review":
        code_verdict = await _code_verdict(
            db, request.session_id, user_id, request.language
        )

    brief = "\n".join(
        [
            "## This moment",
            "",
            "### The panel",
            _render_panel(ctx.role, ctx.open_domain),
            "",
            f"### The candidate\n{name}",
            "",
            # THE ROLE, in every turn. Without it the panel has no idea what job this is
            # and defaults to Java — which is how an Analyst ended up being asked to rate
            # themselves in a language their role never touches.
            f"### The role they are interviewing for\n{role_line}",
            "",
            # Decided server-side. See _rating_subject — the model is not the thing that
            # knows what a role is screened on, and asked to guess it guesses Java.
            "### What to ask them to rate themselves on (skill_check stage only)",
            rating_subject,
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
            # SAID OUT LOUD FOR THE ONE STAGE WHERE GETTING IT WRONG IS INVISIBLE. On
            # `off_script` the question above is the SAME one the candidate has already heard,
            # and a panel that reads it as a new question says "right, next one" to somebody
            # who has just asked for a repeat.
            (
                "### About the question above\n"
                + (
                    "This is the SAME question they were already asked. They asked you "
                    "something instead of answering it, so you are putting it to them again "
                    "— in different words, without any suggestion that they have used up a "
                    "chance."
                    if request.stage == "off_script"
                    else "(a new question — put it normally)"
                )
            ),
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

    # ── ALREADY WRITTEN? ──────────────────────────────────────────────────────────────
    #
    # "the questions are taking so much time to come in the real interview", with an explicit
    # instruction not to trade quality for speed. So nothing here asks for a cheaper model, a
    # smaller budget or a faster vendor setting: the turn is generated exactly as before. What
    # changes is WHEN.
    #
    # A turn is a pure function of this session's state and this question — panel.py performs no
    # database writes, which is what makes both halves of this safe. So it can be written ahead
    # of time and read back, and the candidate pays for the wait only if nobody got there first.
    #
    # Keyed on the session AND a hash of the stage plus the question text. Session-scoped
    # always: a turn quotes the candidate's own last answer and names their projects, which is
    # precisely what vector_cache's CACHEABLE_FEATURES allowlist exists to keep out of anything
    # shared. Two candidates asked a byte-identical question still get their own.
    turn_digest = hashlib.sha256(
        f"{request.stage}|{request.question}|{request.candidate_question}|{last_answer}".encode()
    ).hexdigest()[:32]
    turn_key = CacheKeys.panel_turn(str(request.session_id), turn_digest)

    return _TurnContext(
        messages=messages,
        turn_key=turn_key,
        pivot_topic=pivot_topic,
        rating_subject=rating_subject,
    )


def _finalise_turn(
    turn: InterviewPanelTurn, request: PanelTurnRequest
) -> tuple[list[dict], bool, str]:
    """
    The validated model output, reduced to what may actually be sent and spoken.

    RETURNS RATHER THAN REMEMBERS, and the separation from `_remember_turn` below is the
    point rather than tidiness. The streaming endpoint has to be able to build this and then
    decide, on the strength of whether the stream actually finished, whether anything is
    saved at all. A function that validated and cached in one step could not offer that
    choice, and a half-written turn frozen into the cache for fifteen minutes would be
    structural rather than avoidable.
    """
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

    # ── THE SPEAKER NAME IS CANONICALISED, NOT MATCHED EXACTLY ───────────────────────────
    #
    # REPORTED AS "priya is not speaking", and this is how a whole panelist goes quiet.
    #
    # The filter below used to be `c.speaker in INTERVIEWER_NAMES`, an exact case-sensitive
    # comparison against ["Anil", "Priya"]. A model that writes "priya", "PRIYA", "Priya " or
    # "Priya:" has said exactly what was asked of it — the prompt names the panel and the
    # instruction is to use those names — but the contribution was DROPPED, silently, with no
    # log and no fallback. Her turn simply did not exist by the time the browser saw it.
    #
    # It also fails asymmetrically, which is why it reads as "one person stopped talking"
    # rather than "the panel is broken": whichever name the model happens to capitalise
    # consistently keeps working, and the other one vanishes.
    #
    # So the name is normalised and mapped back to the CANONICAL spelling — the browser hands
    # this straight to /tts/speak, which resolves a voice by name, so a lowercase "priya"
    # reaching that lookup would find no voice and fall back to browser speech even if it did
    # survive this filter.
    valid: list[dict] = []
    dropped: list[str] = []
    for c in turn.turns:
        text = c.text.strip()
        if not text:
            continue
        canonical = canonical_speaker(c.speaker)
        if canonical is None:
            dropped.append(c.speaker)
            continue
        valid.append({
            "speaker": canonical,
            "text": text,
            # Re-checked here rather than trusted: this is what the browser hands straight
            # back to /tts/speak, and an unrecognised name there would silently become
            # neutral anyway. Normalising at the boundary means the tone in the transcript
            # is the tone that was actually spoken.
            "tone": c.tone if c.tone in TONE_PROSODY else "neutral",
        })
    valid = valid[:4]

    if dropped:
        # NEVER SILENT AGAIN. A dropped contribution is a panelist who did not speak, and the
        # only previous evidence was a candidate noticing that one interviewer had gone quiet.
        logger.warning(
            "panel_contribution_dropped_unknown_speaker",
            speakers=dropped[:4],
            known=INTERVIEWER_NAMES,
        )

    asked_question = turn.asked_question and bool(valid)

    return valid, asked_question, (turn.candidate_turn if valid else "answered")


async def _remember_turn(
    turn_key: str, valid: list[dict], asked_question: bool, candidate_turn: str
) -> None:
    """Store a COMPLETE turn so the same moment is never written twice."""
    # ── REMEMBERED, so the same moment is never written twice ─────────────────────────────
    #
    # Only on success: an empty turn must not be cached, or one provider failure would freeze
    # the bare-question fallback in place for the rest of that question.
    #
    # WHAT THIS IS ACTUALLY FOR. The client retries this call on a network blip and refetches
    # after a reconnect, and each of those used to pay the full generation again — the slowest
    # thing in the flow, repeated for a turn already written. A short TTL because the key
    # includes the candidate's last answer, so it changes as the interview moves; long enough
    # to cover a retry, a reconnect and a page refresh on the same question.
    #
    # No quality is traded for this. The turn is generated by the same model with the same
    # budget; the cache only stops it being generated a second time for the same moment.
    if valid:
        try:
            await cache_set(
                get_redis(),
                turn_key,
                json.dumps(
                    {
                        "turns": valid,
                        "asked_question": asked_question,
                        # STORED, because a cache hit that dropped this would report
                        # "answered" for a turn whose whole point was that they did not.
                        # The key already includes the candidate's last answer, so the read
                        # belongs to the same moment as the words.
                        "candidate_turn": candidate_turn,
                    }
                ),
                ttl=900,
            )
        except Exception as exc:  # noqa: BLE001 — a cache write must never fail a turn
            logger.warning(
                "panel_turn_cache_store_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )


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
    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.schemas import InterviewPanelTurn  # noqa: PLC0415

    turn_ctx = await _turn_context(db, request, current_user.user_id)
    messages, turn_key = turn_ctx.messages, turn_ctx.turn_key
    pivot_topic, rating_subject = turn_ctx.pivot_topic, turn_ctx.rating_subject

    cached_turn = await cache_get(get_redis(), turn_key)
    if cached_turn:
        try:
            payload = json.loads(cached_turn)
            logger.info("panel_turn_cache_hit", session_id=str(request.session_id))
            return PanelTurnResponse(
                # `turns` is a list[dict] on the response model, so the cached shape goes
                # straight back — no re-validation to drift from the live path.
                turns=list(payload.get("turns", [])),
                asked_question=bool(payload.get("asked_question")),
                pivot_topic=pivot_topic,
                rating_subject=rating_subject,
                # Absent on an entry written before this field existed, which is a cache hit
                # from the previous deploy rather than an error.
                candidate_turn=str(payload.get("candidate_turn") or "answered"),
            )
        except Exception as exc:  # noqa: BLE001
            # A malformed cache entry must never cost somebody their turn. Fall through and
            # generate; the store below overwrites it. Logged with the reason, because a
            # recurring parse failure means the shape changed and the cache is dead weight.
            logger.warning(
                "panel_turn_cache_unreadable",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )

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
    except AIProviderUnavailableError as exc:
        # The panel is presentation. If it is unavailable the caller still has the question
        # and puts it to the candidate the old way — a dialogue failure must never cost
        # somebody their interview.
        #
        # THE REASON IS LOGGED NOW, AND ITS ABSENCE HID THE REAL BUG FOR FOUR ROUNDS. An empty
        # turn is what makes the client fall back, and until this commit that fallback spoke
        # through the BROWSER synthesiser — so the visible symptom was "the voices are Google
        # voices and the vendor shows zero requests", which sent every investigation into the
        # TTS layer. The TTS layer was fine. This was the failure, and the log line said only
        # that it had happened.
        #
        # Both providers exhausted means every attempt failed; generate.py now logs each
        # provider's own reason, so this line plus those is enough to say which.
        logger.warning(
            "panel_turn_unavailable",
            session_id=str(request.session_id),
            stage=request.stage,
            error_type=type(exc).__name__,
            error=str(exc) or type(exc).__name__,
            consequence="client speaks the bare question itself",
        )
        return PanelTurnResponse(
            turns=[],
            asked_question=False,
            pivot_topic=pivot_topic,
            rating_subject=rating_subject,
            # No turn means no read of the candidate either. "answered" is the honest default:
            # the interview should not record that somebody failed to answer on the strength
            # of a provider outage.
            candidate_turn="answered",
        )

    valid, asked_question, candidate_turn = _finalise_turn(turn, request)
    await _remember_turn(turn_key, valid, asked_question, candidate_turn)

    return PanelTurnResponse(
        turns=valid,
        asked_question=asked_question,
        pivot_topic=pivot_topic,
        rating_subject=rating_subject,
        # Only when the panel actually spoke. A read attached to a turn that was dropped for
        # having no valid speakers is a judgement about an exchange that never happened.
        candidate_turn=turn.candidate_turn if valid else "answered",
    )


# ─── Streaming ────────────────────────────────────────────────────────────────


def _sse(event: str, payload: dict) -> str:
    """
    One Server-Sent Event.

    A named event per kind rather than one channel the client has to sniff, because the four
    kinds mean genuinely different things — provisional text, a restart, the finished turn, a
    failure — and a client that had to guess would eventually guess a partial turn was a whole
    one. `json.dumps` guarantees no raw newline reaches the wire, which is what would otherwise
    split one event into two.
    """
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post(
    "/turn/stream",
    dependencies=[Depends(_panel_rate_limit)],
    summary="What the panel says, streamed as it is written",
)
async def panel_turn_stream(
    request: PanelTurnRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> StreamingResponse:
    """
    The same turn as POST /turn, delivered as it is written.

    WHY THIS EXISTS. A panel turn is four short spoken lines inside one JSON object, and the
    candidate sees none of it until the object is complete — most of a second of silence at
    the exact moment they are most alert, because the interviewer has stopped talking and they
    are waiting to be asked something. The FIRST line is finished long before the last one
    starts. `scripts/panel_stream_latency.py` measures what that is worth.

    THE SAME TURN, NOT A CHEAPER ONE. Same brief, same prompt, same model, same budget, same
    validation, same ledger entry — `_turn_context` and `_finalise_turn` are shared with the
    whole-turn endpoint so the two cannot drift, and the streaming happens INSIDE
    `generate_structured` so provider fallback, retries and usage recording all still apply.
    What changes is when the bytes arrive.

    ── WHAT IS PROVISIONAL AND WHAT IS TRUE ──────────────────────────────────────────────

    `line` events are PROVISIONAL. They come from `StreamedObjects`, which reads complete
    objects out of a half-written array — good enough to put words on a screen, and not good
    enough to be believed. They may be superseded, and on a retry they are thrown away.

    `done` carries the turn that actually happened: schema-validated as a whole, speaker names
    canonicalised, capped at four lines. A client MUST render from `done` and treat everything
    before it as a preview. That is the same discipline the non-streaming path has always had
    — it is simply visible here.

    ── AN INTERRUPTED STREAM SAVES NOTHING ───────────────────────────────────────────────

    This is the property worth stating plainly, because it is the one that would be a silent
    data bug rather than a visible failure. The Redis turn cache is the only thing this
    endpoint writes, and a poisoned entry would be served for fifteen minutes as though it
    were a complete turn — so the candidate would lose two of their four lines on a retry,
    a reconnect and a refresh, long after the network blip that caused it.

    Three things make that impossible rather than unlikely, and none of them is a check
    somebody has to remember:

      1. A provider stream that ends without its terminator raises inside
         `generate._stream_into`, so a truncated answer is a FAILED ATTEMPT rather than a
         short one.
      2. Nothing reaches `_remember_turn` except a `turn` that came back from
         `generate_structured`, which means it parsed and validated as a whole.
      3. If the client disconnects, this generator is cancelled — and the cache write is
         after the validation, in the same coroutine, so there is no path on which half a
         turn is written.

    `tests/test_panel_streaming.py` asserts all three, including by cutting a stream at every
    single character position.
    """
    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.stream_parser import StreamedObjects  # noqa: PLC0415

    turn_ctx = await _turn_context(db, request, current_user.user_id)

    async def events() -> AsyncIterator[str]:
        # A CACHE HIT IS STILL A STREAM, and it is the fastest one available: the lines are
        # already written, so they go out immediately and the client's rendering path is the
        # same either way. Returning JSON here instead would give the client two shapes to
        # handle for one request.
        cached = await cache_get(get_redis(), turn_ctx.turn_key)
        if cached:
            try:
                payload = json.loads(cached)
                logger.info(
                    "panel_turn_stream_cache_hit", session_id=str(request.session_id)
                )
                for line in payload.get("turns", []):
                    yield _sse("line", line)
                yield _sse(
                    "done",
                    {
                        "turns": list(payload.get("turns", [])),
                        "asked_question": bool(payload.get("asked_question")),
                        "pivot_topic": turn_ctx.pivot_topic,
                        "rating_subject": turn_ctx.rating_subject,
                        "candidate_turn": str(payload.get("candidate_turn") or "answered"),
                    },
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "panel_turn_stream_cache_unreadable",
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )

        parser = StreamedObjects()
        # Buffered rather than yielded from the callback, because `on_delta` is a plain
        # function called from inside the provider loop and an async generator cannot yield
        # from there. Drained between awaits below, which is often enough to be well ahead of
        # the whole-turn path and simple enough to be obviously correct.
        pending: list[str] = []

        def on_delta(delta: str) -> None:
            for obj in parser.feed(delta):
                speaker = canonical_speaker(str(obj.get("speaker", "")))
                text = str(obj.get("text", "")).strip()
                if speaker is None or not text:
                    # Dropped silently HERE and only here: `_finalise_turn` logs the same
                    # rejection against the validated turn, and logging it twice for one line
                    # would read as two panelists having gone quiet.
                    continue
                pending.append(
                    _sse(
                        "line",
                        {
                            "speaker": speaker,
                            "text": text,
                            "tone": obj.get("tone")
                            if obj.get("tone") in TONE_PROSODY
                            else "neutral",
                        },
                    )
                )

        def on_restart() -> None:
            # A RETRY REWRITES THE ANSWER FROM THE BEGINNING. Without telling the client, the
            # second attempt's lines would be appended to the first attempt's and the
            # candidate would watch the panel say everything twice.
            nonlocal parser
            parser = StreamedObjects()
            pending.clear()
            pending.append(_sse("restart", {}))

        task = asyncio.create_task(
            generate_structured(
                InterviewPanelTurn,
                turn_ctx.messages,
                max_tokens=320,
                attempts_per_provider=2,
                is_valid=lambda t: bool(t.turns),
                cost_tier=CostTier.CHEAP,
                context="interview_panel_turn",
                cache_system=True,
                on_delta=on_delta,
                on_restart=on_restart,
            )
        )

        try:
            while not task.done():
                # Short enough that a finished line reaches the browser promptly, long enough
                # that this is not a spin loop. The turn's own latency is unaffected — the
                # generation is running in its own task throughout.
                await asyncio.sleep(0.05)
                while pending:
                    yield pending.pop(0)
            turn, _raw = await task
            while pending:
                yield pending.pop(0)
        except AIProviderUnavailableError as exc:
            # The panel is presentation. The caller still has the question and puts it to the
            # candidate the old way — a dialogue failure must never cost somebody their
            # interview. Same contract as the non-streaming endpoint's empty response.
            logger.warning(
                "panel_turn_stream_unavailable",
                session_id=str(request.session_id),
                stage=request.stage,
                error_type=type(exc).__name__,
                error=str(exc) or type(exc).__name__,
                consequence="client speaks the bare question itself",
            )
            yield _sse(
                "done",
                {
                    "turns": [],
                    "asked_question": False,
                    "pivot_topic": turn_ctx.pivot_topic,
                    "rating_subject": turn_ctx.rating_subject,
                    "candidate_turn": "answered",
                },
            )
            return
        finally:
            # THE CLIENT CLOSING THE TAB MUST NOT LEAVE A CALL RUNNING. Cancelling an
            # already-finished task is a no-op, so this is safe on the happy path too.
            if not task.done():
                task.cancel()

        valid, asked_question, candidate_turn = _finalise_turn(turn, request)
        # AFTER validation, and only after. See the note on this function about why an
        # interrupted stream cannot reach here.
        await _remember_turn(turn_ctx.turn_key, valid, asked_question, candidate_turn)
        yield _sse(
            "done",
            {
                "turns": valid,
                "asked_question": asked_question,
                "pivot_topic": turn_ctx.pivot_topic,
                "rating_subject": turn_ctx.rating_subject,
                "candidate_turn": candidate_turn,
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            # Proxies buffer by default and a buffered SSE stream is a slow non-streaming
            # response with extra steps. Both headers are needed: nginx reads the second.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
