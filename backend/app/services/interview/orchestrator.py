import asyncio
import contextlib
import json
import random
import re
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.exceptions import AIProviderUnavailableError
from app.db.redis import cache_get, cache_set, get_redis
from app.events.base import InterviewStartedEvent, InterviewStartedPayload
from app.events.emitter import get_event_emitter
from app.models.company import InterviewTrack, QuestionCategory
from app.models.question import Question, Topic
from app.models.report import ResumeFile
from app.models.session import Answer, InterviewSession, Score, SessionStatus
from app.prompts.prompt_loader import get_prompt_loader
from app.services.ai import semantic_cache
from app.services.ai.base_provider import CostTier
from app.services.ai.generate import generate_structured
from app.services.ai.prompt_builder import PromptBuilder
from app.services.ai.schemas import GeneratedQuestion, InterviewPlan
from app.services.interview.dont_know import said_dont_know
from app.services.interview.research_lookup import find_research, render_research, slugify


def _business_context(company: str) -> str:
    """
    What this company actually does, for the interview planner.

    Matched from the catalogue by slug, then again with separators stripped:
    candidates type "Tech Mahindra", which slugifies to "tech-mahindra", while the
    catalogue slug is "techmahindra". Without the second attempt every multi-word
    company silently fell through to the generic line — the exact failure this
    function exists to prevent.

    Returns a neutral line when the company genuinely is not one we know, so a
    candidate typing any firm still gets a working interview, just without the
    company-specific framing.
    """
    from app.services.prep import get_company, load_catalogue  # noqa: PLC0415

    slug = slugify(company)
    entry = get_company(slug) or get_company(slug.replace("-", ""))
    if entry is None:
        # Last resort: match on the display name, so "Cognizant Technology
        # Solutions" or a trailing "Ltd" still resolves.
        collapsed = slug.replace("-", "")
        entry = next(
            (
                c
                for c in load_catalogue().companies
                if c.slug in collapsed or collapsed.startswith(c.slug)
            ),
            None,
        )
    if entry is None or not entry.business_context:
        return "(no specific business context on file for this company)"
    return entry.business_context

def _is_java_role(track_name: str, program: str) -> bool:
    """
    Does this role actually get asked Java?

    The curated bank in java_fundamentals is Java, all of it. It is the right list for a
    Digital Nurture Java FSE and it is the WRONG list for a Deloitte Analyst, a Capgemini
    Analyst or an Infosys System Engineer — and handing it to the planner for those roles is
    what made every Analyst interview the same interview.

    Reuses the bank's own role test rather than inventing a second one. `_wants_frameworks`
    already encodes which roles are Java/backend roles, it is exercised by the bank's tests,
    and two role classifiers that disagree is a worse bug than either being slightly wrong.
    """
    from app.data.java_fundamentals import _wants_frameworks  # noqa: PLC0415

    blob = f"{track_name} {program}".lower()
    # The framework roles, plus the ones that are Java-first without being framework-heavy.
    return _wants_frameworks(track_name, program) or any(
        k in blob for k in ("java", "backend", "full stack", "fullstack", "fse")
    )


def _company_topic_block(company: str) -> str:
    """
    What THIS COMPANY actually weights, from the catalogue, as markdown bullets.

    THIS IS THE FIX FOR "why is it asking an Analyst the same thing every time". The planner
    used to be handed a Java fundamentals list whatever the role was, so a Deloitte Analyst —
    a consulting role whose rounds are case reasoning, DBMS and a group discussion — was
    briefed to cover core Java, and got core Java. Every time, because the bank is fixed.

    The catalogue already carries the right answer per company and has done all along:
    Deloitte Analyst is Aptitude & Case Reasoning 22, Programming Fundamentals 18, Data
    Structures 15, DBMS & SQL 15, Group Discussion & Communication 15, OOP 10, HR & Project
    5. Those weights are validated at load to sum to 100, so they are a real distribution and
    the planner can allocate a twelve-question interview across them directly.
    """
    from app.services.prep import get_company, load_catalogue  # noqa: PLC0415

    slug = slugify(company)
    entry = get_company(slug) or get_company(slug.replace("-", ""))
    if entry is None:
        collapsed = slug.replace("-", "")
        entry = next(
            (
                c
                for c in load_catalogue().companies
                if c.slug in collapsed or collapsed.startswith(c.slug)
            ),
            None,
        )
    if entry is None or not entry.topics:
        return ""

    rounds = ""
    if entry.rounds:
        # The rounds matter as much as the weights for a consulting role: knowing there is a
        # group discussion and a case round tells the planner this is not a coding screen.
        rounds = "\nTheir actual rounds: " + " → ".join(entry.rounds) + "\n"
    weights = "\n".join(
        f"- **{t.name}** — {t.weight:g}% of the assessment" for t in entry.topics
    )
    return f"{rounds}\n{weights}"


def _must_cover_block(track_name: str, program: str, company: str = "") -> str:
    """
    What the planner is told this interview must cover.

    ROLE FIRST, and that ordering is the whole point. For a Java role this is the curated
    bank grouped by topic, exactly as before. For everything else it is the company's own
    weighting, and the Java bank is not mentioned at all — because mentioning it is an
    instruction to ask about it, and an Analyst being asked about the JVM is the complaint
    this function now exists to prevent.
    """
    company_block = _company_topic_block(company)

    if not _is_java_role(track_name, program):
        if company_block:
            return (
                "This is NOT a Java/backend role. Do not build the interview around Java "
                "language internals. Cover what this company actually assesses, in roughly "
                f"these proportions:\n{company_block}"
            )
        return (
            "This is NOT a Java/backend role. Build the interview from the role title and "
            "the company research above — programming fundamentals, DBMS and SQL, data "
            "structures, and the reasoning and communication this role is really screened "
            "for. Do not default to Java language internals."
        )

    from app.data.java_fundamentals import for_track  # noqa: PLC0415

    questions = for_track(track_name, program)
    if not questions:
        return company_block or "(no curated fundamentals list — use the company weighting)"

    by_topic: dict[str, list[str]] = {}
    for q in questions:
        by_topic.setdefault(q["topic"], []).append(q["content"])

    lines = []
    for topic, contents in by_topic.items():
        lines.append(f"- **{topic}** — e.g. {contents[0]}")
        for extra in contents[1:]:
            lines.append(f"    - {extra}")
    # The company weighting is added even for a Java role: it is what decides how much of a
    # Java interview is actually DBMS and aptitude, which for a mass recruiter is most of it.
    if company_block:
        lines.append("")
        lines.append("How this company weights the assessment overall:")
        lines.append(company_block)
    return "\n".join(lines)


logger = structlog.get_logger(__name__)

# How many questions the AI pre-generates for a planned interview, and the max
# number of live cross-questions injected during it. Both come from settings so
# the interview length is configurable and, crucially, so the UI can advertise
# the SAME number it will actually ask — these were hardcoded at 6 and 2 while
# the track card advertised its 20-question bank.
_PLANNED_QUESTION_COUNT = settings.INTERVIEW_QUESTION_COUNT
_MAX_CROSS_QUESTIONS = settings.INTERVIEW_MAX_CROSS_QUESTIONS
#: Below this many words an answer cannot support a "dig into what you said"
#: follow-up. Set at 12 because that is roughly a single clause — "it is a
#: virtual machine that runs java code" is 8 — and anything shorter is a
#: non-answer, a mis-fired mic, or a speech-to-text fragment. Feeding one of
#: those to the cross-question prompt does not produce a weak question, it
#: produces a confidently wrong one that puts words in the candidate's mouth.
_MIN_WORDS_FOR_CROSS_QUESTION = 12

#: The fewest AI-generated questions a plan may contribute before we stop trusting
#: it and top the rest up from the bank.
#:
#: This used to be a bare `>= 4` in three places, and it is the bug behind
#: "it said 20 questions and asked me 8". The planner is told to produce
#: INTERVIEW_QUESTION_COUNT questions; when the model returned fewer — which it
#: does when the token budget runs short or the topic list is narrow — the
#: validator waved it through and the candidate silently got a third of the
#: interview they were promised. Nothing measured the gap, so nothing reported it.
#:
#: Two thirds, floored at 4, because a plan that short is a signal the model
#: misunderstood the brief and is better replaced than padded — while a plan a
#: couple of questions light is fine to finish from the bank.
_MIN_AI_PLAN_QUESTIONS = max(4, (_PLANNED_QUESTION_COUNT * 2) // 3)

#: First-person markers. A focus that uses one is the candidate talking about
#: themselves rather than naming topics, so the plan it produces is theirs and
#: must not go in the shared cache. "Spring Boot, SQL, DBMS" has none of these;
#: "I struggle with multithreading" and "my internship at <employer>" both do.
#:
#: Deliberately a plain word list, not a classifier. The cost of a false positive
#: is one uncached plan generation; the cost of a false negative is one
#: candidate's details reaching another. Those are not close, so this errs
#: heavily towards not caching.
_PERSONAL_FOCUS_MARKERS = frozenset(
    {"i", "im", "i'm", "ive", "i've", "id", "i'd", "my", "mine", "me", "myself",
     "we", "our", "ours", "us"}
)


def _is_personal_focus(focus: str) -> bool:
    """True when the free-text focus reads as the candidate describing themselves."""
    words = re.findall(r"[a-z']+", focus.lower())
    return any(w in _PERSONAL_FOCUS_MARKERS for w in words)


# Plan reuse cache: we accumulate up to N distinct AI-generated plan variants
# per (company, program, focus) signature in Redis. Once N exist, a matching
# request instantly reuses a random variant instead of paying for another
# generation — fast, cheaper, AND still varied (live cross-questions make every
# run different regardless). The same lookup seam can later be swapped for
# pgvector semantic matching without touching callers.
_MAX_PLAN_VARIANTS = 4
_PLAN_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
# Hard cap on how long we wait for the AI to build the plan before falling back
# to a DB-backed plan, so plan creation returns within a predictable time.
_PLAN_AI_BUDGET_SECONDS = 110.0

#: Output-token budget for a plan, scaled to the number of questions asked.
#:
#: THIS WAS A FLAT 2500 AND IT IS THE ROOT CAUSE OF THREE SEPARATE COMPLAINTS.
#: A planned question carries content, topic_name, difficulty, question_type,
#: expected_keywords and ideal_answer — measured at roughly 165 output tokens
#: each, so a 20-question plan needs about 3,300 plus the topics array. At 2500
#: the JSON truncated mid-array, the parse failed, both providers were exhausted,
#: and every single plan silently fell back to the bank. That one ceiling produced:
#:
#:   * "it says 20 questions and asks fewer" — the bank was smaller than the target
#:   * "the same questions every time"       — the bank is fixed content
#:   * "it never asks what I prepared"       — the bank was five questions
#:
#: The fix is the same shape as report_token_budget(): a fixed part for the topics
#: array plus a per-question allowance, capped so a pathological question_count
#: cannot request an unbounded response. 260 per question rather than the measured
#: 165, because a truncated plan costs the full call AND yields nothing — paying
#: for headroom is strictly cheaper than paying twice.
_PLAN_TOKENS_FIXED = 700
_PLAN_TOKENS_PER_QUESTION = 260
_PLAN_TOKENS_MAX = 10_000

#: Upper bound on a recorded session duration. Public because api/v1/users.py
#: needs the same bound when deriving a duration for sessions completed before it
#: was being stored.
#:
#: A candidate can open an interview and walk away, and the raw gap between
#: started_at and completed_at would then be counted as practice. Ninety minutes
#: is roughly triple the longest plausible session — twelve to twenty questions at
#: a minute or two each is 25-40 minutes — so it cannot clip a real one, while
#: keeping an abandoned tab from inflating the dashboard.
#:
#: Set at three hours first, which was too loose: four abandoned test sessions
#: contributed twelve fictional hours to a "14.3h practised" reading.
MAX_SESSION_SECONDS = 90 * 60


def plan_token_budget(question_count: int) -> int:
    """Output-token budget for a plan covering ``question_count`` questions."""
    count = max(0, question_count)
    return min(_PLAN_TOKENS_FIXED + count * _PLAN_TOKENS_PER_QUESTION, _PLAN_TOKENS_MAX)


class InterviewOrchestrator:
    """State machine and business logic for conducting an interview."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.emitter = get_event_emitter()
        self.prompt_builder = PromptBuilder(get_prompt_loader())

    async def start_session(self, user_id: uuid.UUID, track_id: uuid.UUID) -> InterviewSession:
        """Transitions a session from pending to active and selects the first question."""
        session = await self.db.scalar(
            select(InterviewSession).where(
                InterviewSession.user_id == user_id,
                InterviewSession.track_id == track_id,
                InterviewSession.status.in_([SessionStatus.PENDING, SessionStatus.ACTIVE])
            )
        )
        if not session:
            session = InterviewSession(
                id=uuid.uuid4(),
                user_id=user_id,
                track_id=track_id,
                status=SessionStatus.ACTIVE,
                mode="text",
                started_at=datetime.now(UTC),
            )
            self.db.add(session)
        else:
            session.status = SessionStatus.ACTIVE
            if not session.started_at:
                session.started_at = datetime.now(UTC)

        await self.db.flush()

        with contextlib.suppress(Exception):
            await self.emitter.emit(InterviewStartedEvent(
                event_id=uuid.uuid4(),
                user_id=user_id,
                session_id=session.id,
                payload=InterviewStartedPayload(
                    track_id=track_id,
                    track_name="",
                    mode="text",
                )
            ))

        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def create_plan(
        self,
        user_id: uuid.UUID,
        track_id: uuid.UUID,
        company: str,
        program: str,
        focus: str,
        resume_text: str = "",
    ) -> dict:
        """
        Generate the full interview plan up front (topics + pre-generated
        questions tailored to company/program/focus), persist the questions,
        and store the ordered plan on the session. The candidate reviews the
        topics and calls approve_plan() before the interview starts. Serving
        questions from this plan is instant, so the interview is fluent.

        Returns {session_id, topics, question_count}.
        """
        session = InterviewSession(
            id=uuid.uuid4(),
            user_id=user_id,
            track_id=track_id,
            status=SessionStatus.ACTIVE,
            mode="text",
            started_at=datetime.now(UTC),
        )
        self.db.add(session)
        await self.db.flush()

        # Prefer resume text the candidate pasted in setup (always available);
        # otherwise fall back to a parsed resume on file, if any.
        # What this candidate has already been asked. Drives three things: the
        # planner is told to avoid them, the bank top-up deprioritises them, and a
        # repeat setup skips the plan cache entirely.
        seen_ids, seen_texts = await self._already_asked(user_id)

        resume_summary = resume_text.strip() or await self._resume_summary(user_id)
        # Personalised plans are per-candidate and must NOT be shared via the
        # cache. Only generic (company/program/focus) plans are cacheable.
        #
        # The resume half of this was always here. The focus half was not, and it
        # is the same leak: "Anything specific?" is a free-text box whose
        # placeholder invites first person ("I struggle with multithreading"), the
        # text goes into the plan prompt, and the resulting plan is stored under a
        # signature derived from that same text. Two candidates who write
        # something close enough share a bucket — so if one of them typed "I
        # interned at <employer> on their payments API", the other can be served
        # questions shaped by it.
        personalized = (
            bool(resume_text.strip())
            or not resume_summary.startswith("(No resume")
            or _is_personal_focus(focus)
        )

        plan: InterviewPlan | None = None

        # 1) Try to reuse a previously-generated plan variant (instant, no LLM).
        # Look for a semantically-equivalent setup we've already paid to plan —
        # "Cognizant / Gen C / Java FSE" should reuse "Cognizant / GenC / Java
        # Full Stack Engineer" rather than regenerate it. On a hit we also top
        # this bucket up below, so near-identical setups pool their variants.
        cache_key: str | None = None
        variants: list[dict] = []
        # A candidate who has answered questions here before must not be handed a
        # cached plan. The cache holds at most _MAX_PLAN_VARIANTS per signature, so
        # on a fourth or fifth attempt a reused variant is very likely to be one
        # they have already sat — which is exactly the "same questions every time"
        # complaint. Paying for one generation is the right trade for a retake.
        is_retake = bool(seen_ids)
        if not personalized and not is_retake:
            cache_key = await semantic_cache.find_similar_key(company, program, focus)
            if cache_key:
                variants = await self._load_plan_variants(cache_key)
                if len(variants) >= _MAX_PLAN_VARIANTS:
                    with contextlib.suppress(Exception):
                        plan = InterviewPlan(**random.choice(variants))
                    if plan is not None:
                        logger.info("interview_plan_cache_hit", key=cache_key, variants=len(variants))

        # 2) Cache miss (or personalised) → generate with the AI. Keep it snappy:
        # one attempt per provider, lean tokens, and a HARD time cap so we never
        # hang; on failure we fall back to a solid DB-backed plan.
        if plan is None:
            # Which fundamentals this role is really asked. Scoped so a Spring
            # dependency-injection question never lands in an aptitude-first
            # mass-recruiter round, where it would burn one of a dozen slots on
            # something the candidate will not be asked.
            track_name = await self.db.scalar(
                select(InterviewTrack.name).where(InterviewTrack.id == track_id)
            )
            must_cover = _must_cover_block(track_name or "", program, company)

            messages = self.prompt_builder.chat(
                system_template="interview_plan",
                user_content="Design the interview plan now, following the rules and output format.",
                must_cover=must_cover,
                already_asked=(
                    "\n".join(f"- {t}" for t in seen_texts[-40:])
                    if seen_texts
                    else "(this is their first interview — nothing to avoid)"
                ),
                company=company.strip() or "a general tech company",
                program=program.strip() or "Software Engineer (fresher)",
                focus=focus.strip() or "(no specific focus — cover the standard areas for this role)",
                resume=resume_summary,
                question_count=str(_PLANNED_QUESTION_COUNT),
                # Cached research on how this company really interviews. Costs a
                # single indexed row read — the alternative, a live web search
                # per interview, would be billed every session for information
                # that changes a few times a year.
                research=render_research(await find_research(self.db, company, program)),
                # What the firm actually builds and sells. This is what stops a
                # "Cognizant" interview being a generic one with the name swapped
                # in: knowing healthcare claims are its biggest business lets the
                # planner frame a DBMS question the way Cognizant really would.
                business_context=_business_context(company),
            )
            try:
                plan, _ = await asyncio.wait_for(
                    generate_structured(
                        InterviewPlan,
                        messages,
                        max_tokens=plan_token_budget(_PLANNED_QUESTION_COUNT),
                        attempts_per_provider=1,
                        is_valid=lambda p: len(p.questions) >= _MIN_AI_PLAN_QUESTIONS,
                        cost_tier=CostTier.BALANCED,
                        context="interview_plan",
                    ),
                    timeout=_PLAN_AI_BUDGET_SECONDS,
                )
            except (AIProviderUnavailableError, TimeoutError):
                logger.warning("interview_plan_ai_unavailable_using_fallback", session_id=str(session.id))

            # Store a freshly-generated generic plan as a reusable variant. On a
            # semantic hit we top up that bucket; on a miss we register this
            # signature so the next similar setup finds it.
            if (
                plan is not None
                and len(plan.questions) >= _MIN_AI_PLAN_QUESTIONS
                and not personalized
                # A retake's plan was shaped by this candidate's own history,
                # so it is no more reusable than a resume-personalised one.
                and not is_retake
            ):
                store_key = cache_key or await semantic_cache.register(company, program, focus)
                await self._save_plan_variant(store_key, variants, plan)

        if plan is not None and len(plan.questions) >= _MIN_AI_PLAN_QUESTIONS:
            planned_ids, topics = await self._persist_plan(track_id, plan, session.id)
        else:
            planned_ids, topics = await self._fallback_plan(track_id, session.id, seen_ids)

        # Keep the promise. The dashboard advertises INTERVIEW_QUESTION_COUNT
        # questions per interview, so an interview that serves fewer is the
        # product lying to a candidate who is trying to prepare — and it happened
        # every time the model returned a short plan.
        #
        # Topping up from the bank rather than asking the model again: a second
        # generation costs another 2500 tokens and the same amount of waiting, to
        # fill a gap that curated questions fill just as well.
        if len(planned_ids) < _PLANNED_QUESTION_COUNT:
            before = len(planned_ids)
            planned_ids = await self._top_up_plan(track_id, planned_ids, seen_ids)
            if len(planned_ids) != before:
                logger.info(
                    "interview_plan_topped_up",
                    session_id=str(session.id),
                    ai_questions=before,
                    final=len(planned_ids),
                    target=_PLANNED_QUESTION_COUNT,
                )
            if len(planned_ids) < _PLANNED_QUESTION_COUNT:
                # The bank could not cover the gap either. Logged loudly rather
                # than shrugged at, because the number shown to the candidate is
                # len(planned_ids) and it will not match what the dashboard said.
                logger.warning(
                    "interview_plan_below_target",
                    session_id=str(session.id),
                    got=len(planned_ids),
                    target=_PLANNED_QUESTION_COUNT,
                    hint="seed more questions for this track",
                )

        session.session_metadata = {
            "company": company,
            "program": program,
            "focus": focus,
            "topics": topics,
            "planned_question_ids": planned_ids,
            "cross_question_ids": [],
            "approved": False,
            "cross_asked": 0,
        }
        await self.db.commit()
        await self.db.refresh(session)

        return {"session_id": session.id, "topics": topics, "question_count": len(planned_ids)}

    async def _load_plan_variants(self, cache_key: str) -> list[dict]:
        """Load cached plan variants for a signature (best-effort, never raises)."""
        try:
            raw = await cache_get(get_redis(), cache_key)
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    return data
        except Exception as exc:  # noqa: BLE001 — cache is best-effort
            logger.warning("plan_cache_load_failed", key=cache_key, error=str(exc))
        return []

    async def _save_plan_variant(
        self, cache_key: str, variants: list[dict], plan: InterviewPlan
    ) -> None:
        """Append a freshly-generated plan variant to the cache (best-effort)."""
        try:
            updated = [*variants, plan.model_dump()][-_MAX_PLAN_VARIANTS:]
            await cache_set(get_redis(), cache_key, json.dumps(updated), ttl=_PLAN_CACHE_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 — cache is best-effort
            logger.warning("plan_cache_save_failed", key=cache_key, error=str(exc))

    async def _persist_plan(
        self, track_id: uuid.UUID, plan: InterviewPlan, session_id: uuid.UUID
    ) -> tuple[list[str], list[str]]:
        """
        Persist a plan's questions as Question rows; return (ordered_ids, topics).

        Owned by `session_id`, never added to the shared bank. A planned question
        can be tailored to the candidate's resume — "you mentioned building a
        payments service at <employer>" — and that is their CV, not reference
        content for the next person who picks this track.
        """
        planned_ids: list[str] = []
        for gq in plan.questions:
            if not gq.content.strip():
                continue
            topic = await self._get_or_create_topic(track_id, gq.topic_name)
            q = Question(
                id=uuid.uuid4(),
                topic_id=topic.id,
                session_id=session_id,
                content=gq.content.strip(),
                difficulty=gq.difficulty,
                question_type=gq.question_type,
                expected_keywords=gq.expected_keywords,
                ideal_answer=gq.ideal_answer or None,
            )
            self.db.add(q)
            await self.db.flush()
            planned_ids.append(str(q.id))
        return planned_ids, (plan.topics or [])

    async def _already_asked(self, user_id: uuid.UUID) -> tuple[set[uuid.UUID], list[str]]:
        """
        Every question this candidate has already ANSWERED, across all their
        sessions: (ids, texts).

        Nothing tracked this before, which is the whole reason retakes felt
        repetitive — the bank was sampled fresh each time with no memory, so the
        same easy questions came up again and again. Ids feed the bank filters;
        texts go to the planner so it does not regenerate a question the candidate
        has already seen in different words.

        Answered rather than merely served, deliberately: a question shown in a
        session the candidate abandoned is not one they have practised, so it is
        fair to ask again.
        """
        rows = (
            await self.db.execute(
                select(Question.id, Question.content)
                .join(Answer, Answer.question_id == Question.id)
                .join(InterviewSession, InterviewSession.id == Answer.session_id)
                .where(InterviewSession.user_id == user_id)
                .distinct()
            )
        ).all()
        return {r[0] for r in rows}, [r[1] for r in rows if r[1]]

    async def _drop_declined_topic(
        self, session: InterviewSession, question: Question, meta: dict
    ) -> int:
        """
        The candidate said they do not know this topic. Take it out of the rest of the plan.

        THIS IS THE HALF THAT WAS MISSING, and its absence is what "the AI runs on a roadmap"
        was describing. A decline already did three things: it was detected server-side by
        dont_know.py, the panel pivoted and offered another topic, and the pivot was recorded
        so declining could not be farmed for easier questions. What none of that did was
        change WHICH QUESTIONS COME NEXT. The plan is built up front and walked in order, so a
        candidate who said "sorry, I have not studied multithreading" was asked about
        multithreading again two questions later, and again after that. Every part of the
        pivot worked except the part that would have made it mean anything.

        A real interviewer does not need to be told twice. They drop the topic and spend the
        time somewhere the candidate can actually show you something — which is also the
        fairer interview, because minutes spent re-confirming a known gap are minutes not
        spent finding a strength.

        SCOPED TO THE TOPIC, NOT THE DIFFICULTY. Declining one hard question about collections
        does not mean collections is off the table — but this cannot tell those apart from the
        answer text, and the safe direction is the one the candidate stated. They said they do
        not know it; believe them. The report still counts the pivot, so this cannot be used to
        shrink the interview for free.

        NEVER EMPTIES THE PLAN. Pruning down to nothing would end the interview at the moment
        the candidate admitted a gap, which reads as a punishment for honesty. The caller tops
        the plan back up from other topics instead, so the interview stays its advertised
        length and simply goes somewhere else — the pivot the panel just promised out loud.

        Returns how many questions were dropped, for the caller to log. Mutates `meta`; the
        caller owns the commit, since it is already writing the session in the same
        transaction and two commits here would be a partial update on failure.
        """
        topic_id = question.topic_id
        if topic_id is None:
            return 0

        planned: list[str] = list(meta.get("planned_question_ids") or [])
        if not planned:
            return 0

        answered = {
            str(a)
            for a in (
                await self.db.scalars(
                    select(Answer.question_id).where(Answer.session_id == session.id)
                )
            ).all()
        }

        # Only unanswered ones are candidates for removal — an answered question stays in the
        # plan because the plan is also the record of what was asked.
        unanswered = [q for q in planned if q not in answered]
        if len(unanswered) <= 1:
            # One question left is the last question. Dropping it ends the interview on a
            # decline, which is exactly the abrupt finish this must not cause.
            return 0

        same_topic = {
            str(q)
            for q in (
                await self.db.scalars(
                    select(Question.id).where(
                        Question.id.in_([uuid.UUID(q) for q in unanswered]),
                        Question.topic_id == topic_id,
                    )
                )
            ).all()
        }
        if not same_topic:
            return 0

        meta["planned_question_ids"] = [q for q in planned if q not in same_topic]
        # Remembered so the top-up cannot immediately put the topic back, and so a later
        # decline on a second topic accumulates rather than replaces.
        declined = {str(t) for t in (meta.get("declined_topic_ids") or [])}
        declined.add(str(topic_id))
        meta["declined_topic_ids"] = sorted(declined)
        return len(same_topic)

    async def _top_up_plan(
        self,
        track_id: uuid.UUID,
        planned_ids: list[str],
        seen_ids: set[uuid.UUID] | None = None,
        exclude_topic_ids: set[uuid.UUID] | None = None,
    ) -> list[str]:
        """
        Fill a short plan out to _PLANNED_QUESTION_COUNT from the shared bank.

        Only bank questions (session_id IS NULL) are eligible, and only ones not
        already in the plan — the same tenancy rule as every other pool read, so a
        top-up can never pull in a question generated inside somebody else's
        interview.

        Prefers, in order: questions this candidate has never answered, then
        topics the plan does not already cover. So a retake pulls different
        questions rather than the same easy ones, and a plan eight questions light
        does not get four more on the topic it already spent half the interview on.

        Seen questions are a preference, not a hard exclusion — once the bank is
        exhausted, repeating a question the candidate has practised is better than
        serving a short interview. That fallback is logged, because it means the
        bank needs more content.

        `exclude_topic_ids` IS A HARD EXCLUSION, unlike everything else here, and it is the
        one that matters for how the interview feels. Those are topics the candidate has
        already said out loud that they do not know. Handing them back a question on one is
        the single most obviously robotic thing this product can do — it proves nobody was
        listening — so unlike `seen_ids` it is never relaxed, not even when the bank runs dry.
        A short interview is a much smaller failure than asking somebody about threads
        thirty seconds after they told you they have not studied threads.
        """
        need = _PLANNED_QUESTION_COUNT - len(planned_ids)
        if need <= 0:
            return planned_ids

        chosen = {uuid.UUID(q) for q in planned_ids}

        async def _bank() -> list[Question]:
            return list(
                await self.db.scalars(
                    select(Question)
                    .join(Topic, Question.topic_id == Topic.id)
                    .join(QuestionCategory, Topic.category_id == QuestionCategory.id)
                    .where(
                        QuestionCategory.track_id == track_id,
                        Question.session_id.is_(None),
                    )
                )
            )

        declined_topics = exclude_topic_ids or set()

        def _eligible(qs: list[Question]) -> list[Question]:
            # The declined-topic filter is applied at the same moment as the already-chosen
            # one, so it survives the seed-and-retry below. Filtering afterwards would let a
            # freshly seeded question on a declined topic straight back in.
            return [q for q in qs if q.id not in chosen and q.topic_id not in declined_topics]

        pool = _eligible(await _bank())
        if not pool:
            await self._ensure_seed_questions(track_id, [])
            pool = _eligible(await _bank())
        if not pool:
            return planned_ids

        # Which topics the plan already uses, so the top-up broadens rather than
        # deepens.
        used_topics: set[uuid.UUID] = set()
        if chosen:
            used_topics = {
                t
                for t in await self.db.scalars(
                    select(Question.topic_id).where(Question.id.in_(chosen))
                )
                if t is not None
            }

        rank = {"easy": 0, "medium": 1, "hard": 2}
        seen_ids = seen_ids or set()

        def _bucket(q: Question) -> int:
            # 0 best: never answered, and a topic this plan has not used.
            # 1: never answered, topic already used.
            # 2: answered before, new topic.  3 worst: answered before, seen topic.
            return (2 if q.id in seen_ids else 0) + (1 if q.topic_id in used_topics else 0)

        groups: dict[int, list[Question]] = {0: [], 1: [], 2: [], 3: []}
        for q in pool:
            groups[_bucket(q)].append(q)
        for group in groups.values():
            random.shuffle(group)
            group.sort(key=lambda q: rank.get(getattr(q.difficulty, "value", q.difficulty), 1))

        ordered = groups[0] + groups[1] + groups[2] + groups[3]
        picked = ordered[:need]
        repeats = sum(1 for q in picked if q.id in seen_ids)
        if repeats:
            logger.info(
                "interview_plan_reused_seen_questions",
                count=repeats,
                hint="the bank is exhausted for this candidate; add more questions",
            )
        return planned_ids + [str(q.id) for q in picked]

    async def _fallback_plan(
        self,
        track_id: uuid.UUID,
        session_id: uuid.UUID,
        seen_ids: set[uuid.UUID] | None = None,
    ) -> tuple[list[str], list[str]]:
        """
        Build a solid interview plan WITHOUT the AI — a warm-up intro question
        followed by a spread of the track's existing questions (seeded if the
        track is empty). Guarantees the plan feature always returns quickly and
        never just hangs when the AI provider is slow or down.

        `seen_ids` are questions this candidate has already answered in a previous
        session; they go last. This path is not the rare exception it reads as —
        the AI plan takes seconds and times out often enough that the fallback is
        what many candidates actually get, so it has to give a retake different
        questions too. Making only the top-up seen-aware left a measured 15 of 20
        questions repeated on a second attempt.

        Returns (ordered_question_ids, topic_names).
        """
        # 1) Warm-up "tell me about yourself" opener, always first.
        intro_topic = await self._get_or_create_topic(track_id, "Introduction")
        intro = Question(
            id=uuid.uuid4(),
            topic_id=intro_topic.id,
            # Owned by the session. Generic text, but a fresh row is created per
            # fallback plan, so leaving it in the bank would fill the pool with
            # thousands of identical opener rows and skew every later query.
            session_id=session_id,
            content=(
                "To start, tell me a little about yourself — your background, and the "
                "project or skill you're most proud of."
            ),
            difficulty="easy",
            question_type="conceptual",
            expected_keywords=["background", "projects", "skills", "motivation"],
            ideal_answer=None,
        )
        self.db.add(intro)
        await self.db.flush()
        ordered_ids = [str(intro.id)]
        topics = ["Introduction"]

        # 2) Existing questions for this track (seed if empty), ordered like a
        #    real interview: easy → medium → hard, preferring a NEW topic at each
        #    step so it flows across areas instead of drilling one. Within a
        #    difficulty tier we shuffle for variety across retakes.
        async def _track_questions() -> list[Question]:
            # Bank rows only. Without the session_id filter this pulled every
            # question ever generated under the track — including live
            # cross-questions that quote another candidate's answer verbatim,
            # which is how "you mentioned 'annual function' in your answer"
            # reached someone who had never said it.
            return list(
                await self.db.scalars(
                    select(Question)
                    .join(Topic, Question.topic_id == Topic.id)
                    .join(QuestionCategory, Topic.category_id == QuestionCategory.id)
                    .where(
                        QuestionCategory.track_id == track_id,
                        Question.session_id.is_(None),
                    )
                )
            )

        rows = await _track_questions()
        if not rows:
            await self._ensure_seed_questions(track_id, [])
            rows = await _track_questions()

        rank = {"easy": 0, "medium": 1, "hard": 2}
        seen_ids = seen_ids or set()
        tiers: dict[int, list[Question]] = {0: [], 1: [], 2: []}
        for q in rows:
            diff = getattr(q.difficulty, "value", q.difficulty)
            tiers[rank.get(diff, 1)].append(q)
        for tier in tiers.values():
            # Shuffle for variety across retakes, then float anything this
            # candidate has already answered to the back of its tier. A stable
            # sort keeps the shuffle meaningful within each group.
            random.shuffle(tier)
            tier.sort(key=lambda q: q.id in seen_ids)

        ordered: list[Question] = []
        used_topics: set = set()
        need = _PLANNED_QUESTION_COUNT - 1
        # First pass: easy→medium→hard, one per new topic where possible.
        for tier_idx in (0, 1, 2):
            for q in tiers[tier_idx]:
                if len(ordered) >= need:
                    break
                if q.topic_id not in used_topics:
                    ordered.append(q)
                    used_topics.add(q.topic_id)
        # Second pass: fill any remaining slots (topic repeats allowed), keeping order.
        if len(ordered) < need:
            chosen = {id(q) for q in ordered}
            for tier_idx in (0, 1, 2):
                for q in tiers[tier_idx]:
                    if len(ordered) >= need:
                        break
                    if id(q) not in chosen:
                        ordered.append(q)
                        chosen.add(id(q))

        ordered_ids.extend(str(q.id) for q in ordered)

        # ONE query for every topic in the plan, not one per question.
        #
        # This was `db.get(Topic, q.topic_id)` inside the loop. The identity map made it
        # at most one round trip per DISTINCT topic rather than per question, which is why
        # it never looked slow — but a 12-question plan still spans several topics, so a
        # cold session start paid several sequential round trips where one does. At a
        # thousand candidates starting interviews inside the same few minutes, which is
        # exactly what a campus drive looks like, that difference is thousands of extra
        # queries against a shared pool.
        topic_ids = list(dict.fromkeys(q.topic_id for q in ordered if q.topic_id))
        if topic_ids:
            topic_result = await self.db.execute(select(Topic).where(Topic.id.in_(topic_ids)))
            by_id = {t.id: t for t in topic_result.scalars()}
            # Ordered by the PLAN, not by whatever order the database returned, because
            # this list is shown to the candidate as the topics they will be asked about.
            for q in ordered:
                topic = by_id.get(q.topic_id)
                if topic and topic.name not in topics:
                    topics.append(topic.name)

        return ordered_ids, topics

    async def _resume_summary(self, user_id: uuid.UUID) -> str:
        """
        Build a compact text summary of the candidate's primary (or most recent
        successfully-parsed) resume so the planner can ask resume-based
        questions. Returns a plain placeholder when no parsed resume exists.
        """
        resume = await self.db.scalar(
            select(ResumeFile)
            .where(
                ResumeFile.user_id == user_id,
                ResumeFile.parsing_status == "completed",
            )
            .order_by(ResumeFile.is_primary.desc(), ResumeFile.created_at.desc())
            .limit(1)
        )
        if not resume:
            return "(No resume uploaded — ask standard questions for the role; skip resume-specific questions.)"

        parts: list[str] = []
        if resume.parsed_skills:
            parts.append("Skills: " + ", ".join(resume.parsed_skills[:20]))
        if resume.parsed_projects:
            proj_titles: list[str] = []
            for p in resume.parsed_projects[:5]:
                if isinstance(p, dict):
                    title = p.get("name") or p.get("title") or ""
                    desc = p.get("description") or p.get("summary") or ""
                    proj_titles.append(f"{title} — {desc}".strip(" —"))
                elif isinstance(p, str):
                    proj_titles.append(p)
            if proj_titles:
                parts.append("Projects:\n" + "\n".join(f"- {t}" for t in proj_titles if t))
        if resume.parsed_experience:
            with contextlib.suppress(Exception):
                parts.append("Experience: " + str(resume.parsed_experience)[:600])

        return "\n".join(parts) if parts else (
            "(Resume uploaded but no structured content extracted — ask standard questions for the role.)"
        )

    async def approve_plan(self, session_id: uuid.UUID) -> bool:
        """Mark a planned interview as approved so questions can be served."""
        session = await self.db.get(InterviewSession, session_id)
        if not session or not session.session_metadata:
            return False
        meta = dict(session.session_metadata)
        meta["approved"] = True
        session.session_metadata = meta
        await self.db.commit()
        return True

    async def get_next_question(self, session_id: uuid.UUID) -> Question | None:
        """
        Adaptively selects the next question based on the candidate's last
        answer, not a random pick:
          - Difficulty follows the AI's suggested_difficulty_adjustment from
            the previous answer (increase on strong answers, decrease on weak).
          - Among candidates at the target difficulty, prefers questions whose
            expected_keywords overlap the concepts the candidate MISSED, so the
            interview probes exactly the gaps they just revealed -- then falls
            back to concepts they mentioned (to go deeper), then anything.
        The first question of a session has no prior signal, so it starts at
        medium difficulty.
        """
        session = await self.db.get(InterviewSession, session_id)
        if not session or session.status != SessionStatus.ACTIVE:
            return None

        answered = await self.db.scalars(
            select(Answer.question_id).where(Answer.session_id == session_id)
        )
        answered_ids = list(answered.all())

        # Planned-interview path: serve pre-generated questions instantly, with
        # the occasional live cross-question. Takes precedence when a plan exists.
        meta = session.session_metadata or {}
        if meta.get("planned_question_ids") is not None:
            return await self._next_planned_question(session, answered_ids)

        # The adaptive path's length comes from the same setting the UI advertises.
        # This was a hardcoded 10, so raising INTERVIEW_QUESTION_COUNT to 20 moved
        # the number on the dashboard and not the interview.
        if len(answered_ids) >= _PLANNED_QUESTION_COUNT:
            return None

        target_difficulty, focus_concepts = await self._adaptive_signals(session_id)

        # Primary path: generate a fresh question with the AI so no two
        # interviews are identical and follow-ups probe what the candidate
        # actually said. Falls through to DB selection if generation fails.
        generated = await self._generate_question(
            session, answered_ids, target_difficulty, focus_concepts, len(answered_ids) + 1
        )
        if generated is not None:
            return generated

        # Fallback candidate pool: unanswered questions in this track.
        query = (
            select(Question)
            .join(Topic, Question.topic_id == Topic.id)
            .join(QuestionCategory, Topic.category_id == QuestionCategory.id)
            .where(
                QuestionCategory.track_id == session.track_id,
                Question.session_id.is_(None),
            )
        )
        if answered_ids:
            query = query.where(Question.id.notin_(answered_ids))
        candidates = list(await self.db.scalars(query))

        # Last resort: any unanswered BANK question, from any track. This was
        # `select(Question)` with no filter whatsoever — every question in the
        # database, every session's, every company's.
        if not candidates:
            fallback = select(Question).where(Question.session_id.is_(None))
            if answered_ids:
                fallback = fallback.where(Question.id.notin_(answered_ids))
            candidates = list(await self.db.scalars(fallback))

        if not candidates:
            return await self._ensure_seed_questions(session.track_id, answered_ids)

        return self._rank_question(candidates, target_difficulty, focus_concepts)

    async def _next_planned_question(
        self, session: InterviewSession, answered_ids: list[uuid.UUID]
    ) -> Question | None:
        """
        Serve the next pre-generated question from the plan (instant). Before
        serving, occasionally inject a live cross-question that probes the
        candidate's most recent answer — kept to _MAX_CROSS_QUESTIONS and never
        two in a row, so the interview stays fluent.

        IDEMPOTENT. `GET /next` is a read to every caller, but the cross-question
        branch spends an AI call, writes a row and increments a counter. The
        client retries once on failure and refetches after every submit, and
        cross-question generation is the slowest thing in the flow — so a request
        that timed out client-side while still running server-side used to come
        back and generate a *second* cross-question from the same answer. That
        burned the per-session budget on questions nobody saw, and swapped the
        question out from under a candidate who was already reading it.

        A generated-but-unanswered cross-question is therefore parked on the
        session and returned as-is until it is answered.
        """
        meta = dict(session.session_metadata or {})
        if not meta.get("approved"):
            return None

        planned = meta.get("planned_question_ids", [])
        cross_ids = set(meta.get("cross_question_ids", []))
        answered_str = {str(a) for a in answered_ids}
        remaining = [qid for qid in planned if qid not in answered_str]

        # Already produced a cross-question the candidate has not answered yet?
        # Hand back the same one. This is what makes repeat calls free.
        pending = meta.get("pending_cross_id")
        if pending and pending not in answered_str:
            parked = await self.db.get(Question, uuid.UUID(pending))
            if parked is not None:
                return parked
            # The row is gone (session deleted and recreated, manual cleanup).
            # Drop the stale pointer rather than looping on a dead id.
            meta.pop("pending_cross_id", None)
            session.session_metadata = meta
            await self.db.commit()

        # Occasional cross-question: after every 3rd answer, if we still have
        # planned questions left, haven't hit the cross-question cap, and the
        # last answered question wasn't itself a cross-question.
        answered_count = len(answered_ids)
        last_answer = await self.db.scalar(
            select(Answer)
            .where(Answer.session_id == session.id)
            # created_at alone is not a total order: it defaults to now(), which
            # in Postgres is the TRANSACTION timestamp, so two answers written in
            # one transaction tie and the winner is whatever the planner returns.
            # Breaking the tie on id keeps "the last answer" deterministic, and
            # feeding the wrong answer to the cross-question prompt is precisely
            # how a candidate gets asked about something they never discussed.
            .order_by(Answer.created_at.desc(), Answer.id.desc())
            .limit(1)
        )
        last_was_cross = bool(last_answer and str(last_answer.question_id) in cross_ids)
        if (
            remaining
            and last_answer is not None
            and answered_count > 0
            and answered_count % 3 == 0
            and meta.get("cross_asked", 0) < _MAX_CROSS_QUESTIONS
            and not last_was_cross
        ):
            last_q = await self.db.get(Question, last_answer.question_id)
            cross = await self._generate_cross_question(last_q, last_answer.content, session.id)
            if cross is not None:
                meta["cross_asked"] = meta.get("cross_asked", 0) + 1
                meta["cross_question_ids"] = [*meta.get("cross_question_ids", []), str(cross.id)]
                meta["pending_cross_id"] = str(cross.id)
                session.session_metadata = meta
                await self.db.commit()
                return cross

        if not remaining:
            return None
        return await self.db.get(Question, uuid.UUID(remaining[0]))

    async def _generate_cross_question(
        self, last_question: Question | None, last_answer: str, session_id: uuid.UUID
    ) -> Question | None:
        """
        Generate one follow-up probing the candidate's last answer. Best-effort.

        Two guards, both learned from a real failure. The question is owned by
        `session_id` because it quotes the candidate verbatim. And an answer too
        short to have said anything gets no cross-question at all: the prompt's
        whole job is to dig into what they said, so handing it two words leaves
        the model nothing to dig into and it fills the gap by attributing the
        expected answer to them — which is how a candidate got asked to explain
        terms the question itself claimed they had used.
        """
        if last_question is None:
            return None
        if len(last_answer.split()) < _MIN_WORDS_FOR_CROSS_QUESTION:
            return None
        topic = await self.db.get(Topic, last_question.topic_id)
        topic_name = topic.name if topic else "General"

        messages = self.prompt_builder.chat(
            system_template="cross_question",
            user_content="Generate the cross-question now, following the output format.",
            topic=topic_name,
            last_question=last_question.content,
            last_answer=last_answer,
        )
        try:
            parsed, _ = await generate_structured(
                GeneratedQuestion,
                messages,
                max_tokens=1200,
                attempts_per_provider=1,
                is_valid=lambda q: len(q.content.strip()) >= 15,
                cost_tier=CostTier.BALANCED,
                context="cross_question",
            )
        except AIProviderUnavailableError:
            return None

        q = Question(
            id=uuid.uuid4(),
            topic_id=last_question.topic_id,
            # THE tenancy boundary. This question quotes the candidate's own
            # words; it must never be reachable from another session's pool.
            session_id=session_id,
            content=parsed.content.strip(),
            difficulty=parsed.difficulty,
            question_type=parsed.question_type,
            expected_keywords=parsed.expected_keywords,
            ideal_answer=parsed.ideal_answer or None,
        )
        self.db.add(q)
        await self.db.flush()
        return q

    async def _generate_question(
        self,
        session: InterviewSession,
        answered_ids: list[uuid.UUID],
        target_difficulty: str,
        focus_concepts: list[str],
        question_number: int,
    ) -> Question | None:
        """
        Generate a fresh interview question via the AI (question_generator
        prompt) and persist it as a Question row so answers can FK to it.
        Returns None on any AI/validation failure so the caller can fall back
        to DB selection -- generation is best-effort, never a hard blocker.
        """
        track = await self.db.get(InterviewTrack, session.track_id) if session.track_id else None
        track_name = track.name if track else "Cognizant Digital Nurture — Java FSE"

        # Topics available for this track (falls back to the CDN Java FSE set).
        topic_rows = await self.db.scalars(
            select(Topic.name)
            .join(QuestionCategory, Topic.category_id == QuestionCategory.id)
            .where(QuestionCategory.track_id == session.track_id)
        )
        topics = [t for t in topic_rows if t]
        topics_str = ", ".join(topics) if topics else (
            "Java OOP, Collections & HashMap internals, Exception Handling, JVM/JDK/JRE, "
            "Multithreading, SQL, Spring Boot, REST APIs, MVC, Design Patterns, PL/SQL"
        )

        # Already-asked question texts, to avoid repeats.
        asked_texts: list[str] = []
        if answered_ids:
            rows = await self.db.scalars(select(Question.content).where(Question.id.in_(answered_ids)))
            asked_texts = [c for c in rows if c]
        already_asked = "\n".join(f"- {t}" for t in asked_texts) if asked_texts else "(none yet)"
        focus_str = ", ".join(focus_concepts) if focus_concepts else "(none — this is a fresh topic)"

        messages = self.prompt_builder.chat(
            system_template="question_generator",
            user_content="Generate the next interview question now, following the rules and output format.",
            track_name=track_name,
            topics=topics_str,
            difficulty=target_difficulty,
            question_number=str(question_number),
            already_asked=already_asked,
            focus_concepts=focus_str,
            candidate_experience_years="not specified",
        )

        # Best-effort: generation failing (both providers) is not fatal — the
        # caller falls back to DB selection — so we swallow the unavailable error.
        try:
            parsed, _ = await generate_structured(
                GeneratedQuestion,
                messages,
                # Generous headroom: the reasoning model spends tokens
                # "thinking", and too small a budget truncates the JSON so the
                # question comes out half-written (e.g. "Can you explain").
                max_tokens=1600,
                attempts_per_provider=1,
                is_valid=lambda q: len(q.content.strip()) >= 15,
                cost_tier=CostTier.BALANCED,
                context="question_generation",
            )
        except AIProviderUnavailableError:
            return None

        topic = await self._get_or_create_topic(session.track_id, parsed.topic_name)
        question = Question(
            id=uuid.uuid4(),
            topic_id=topic.id,
            # Aimed at the gaps THIS candidate just revealed, so it belongs to
            # this session and not to the bank.
            session_id=session.id,
            content=parsed.content.strip(),
            difficulty=parsed.difficulty,
            question_type=parsed.question_type,
            expected_keywords=parsed.expected_keywords,
            ideal_answer=parsed.ideal_answer or None,
        )
        self.db.add(question)
        await self.db.commit()
        await self.db.refresh(question)
        return question

    async def _get_or_create_topic(self, track_id: uuid.UUID, topic_name: str):
        """Get-or-create a Topic (and its parent category) by name under a track."""
        cat = await self.db.scalar(
            select(QuestionCategory).where(QuestionCategory.track_id == track_id).limit(1)
        )
        if not cat:
            cat = QuestionCategory(
                id=uuid.uuid4(), track_id=track_id, name="General",
                slug=f"general-{uuid.uuid4().hex[:6]}", order_index=0, is_active=True,
            )
            self.db.add(cat)
            await self.db.flush()

        clean = (topic_name or "General").strip() or "General"
        topic = await self.db.scalar(
            select(Topic).where(Topic.category_id == cat.id, Topic.name == clean).limit(1)
        )
        if not topic:
            topic = Topic(
                id=uuid.uuid4(), category_id=cat.id, name=clean,
                slug=f"{clean.lower().replace(' ', '-')[:40]}-{uuid.uuid4().hex[:6]}", order_index=0,
            )
            self.db.add(topic)
            await self.db.flush()
        return topic

    async def _adaptive_signals(self, session_id: uuid.UUID) -> tuple[str, list[str]]:
        """
        Derive (target_difficulty, focus_concepts) from the most recent scored
        answer in this session. Returns ("medium", []) when there's no prior
        answer to adapt from.
        """
        last_score = await self.db.scalar(
            select(Score)
            .where(Score.session_id == session_id)
            .order_by(Score.created_at.desc())
            .limit(1)
        )
        if not last_score:
            # NOTHING SCORED YET, so the only evidence available is what the candidate said
            # about themselves when the panel asked. This is the one and only place the
            # self-rating touches question selection.
            #
            # It sets the STARTING POINT and nothing more. From the first scored answer
            # onwards the adaptive signal below takes over completely, which is the property
            # that makes handing the candidate this dial safe: an overclaim buys two hard
            # questions and is then corrected by evidence, and an underclaim buys two easy
            # ones and is corrected the same way. The claim is also recorded on the session,
            # so the report knows what was promised — see set_self_rating in api/v1/interview.
            return await self._opening_signals_from_self_rating(session_id)

        raw = last_score.raw_evaluation or {}
        adjustment = raw.get("suggested_difficulty_adjustment", "maintain")

        # Base the "current" difficulty on the last answered question, then step
        # it per the AI's recommendation.
        order = ["easy", "medium", "hard"]
        last_answer = await self.db.scalar(
            select(Answer)
            .where(Answer.id == last_score.answer_id)
        )
        current = "medium"
        if last_answer:
            last_q = await self.db.get(Question, last_answer.question_id)
            if last_q and last_q.difficulty in order:
                current = last_q.difficulty
        idx = order.index(current)
        if adjustment == "increase":
            idx = min(idx + 1, len(order) - 1)
        elif adjustment == "decrease":
            idx = max(idx - 1, 0)
        target_difficulty = order[idx]

        # Prefer probing what they missed; if nothing missed, deepen what they raised.
        focus = list(raw.get("missed_concepts") or [])
        if not focus:
            focus = list(raw.get("mentioned_concepts") or [])
        return target_difficulty, focus

    async def _opening_signals_from_self_rating(
        self, session_id: uuid.UUID
    ) -> tuple[str, list[str]]:
        """
        Where to start, given only what the candidate claimed about themselves.

        Bands rather than a curve, because the difficulty axis has three values and pretending
        a 10-point self-assessment resolves more finely than that would be false precision.

        Defaults to ("medium", []) — exactly the old behaviour — whenever there is no rating,
        so a session that never ran the skill_check stage is completely unaffected.
        """
        session = await self.db.get(InterviewSession, session_id)
        rating = ((session.session_metadata or {}) if session else {}).get("self_rating") or {}
        java = rating.get("java")
        if not isinstance(java, int):
            return "medium", []

        if java <= 4:
            target = "easy"
        elif java <= 7:
            target = "medium"
        else:
            target = "hard"

        # Their claimed strengths become the opening focus concepts, which is what makes
        # "the skills the interviewer has to ask" actually steer the questions rather than
        # just being recorded. They flow into _rank_question's keyword overlap exactly as
        # AI-derived concepts do, so a candidate who says "collections and multithreading"
        # gets asked about collections and multithreading.
        focus = [str(x) for x in (rating.get("strengths") or []) if str(x).strip()][:8]
        return target, focus

    @staticmethod
    def _rank_question(
        candidates: list[Question], target_difficulty: str, focus_concepts: list[str]
    ) -> Question:
        """
        Pick the best candidate: highest keyword overlap with focus_concepts,
        with a bonus for matching the target difficulty. Deterministic tie-break
        by id keeps behavior testable.
        """
        focus_lower = {c.lower() for c in focus_concepts}

        def score(q: Question) -> tuple[int, int, str]:
            keywords = {k.lower() for k in (q.expected_keywords or [])}
            overlap = len(keywords & focus_lower)
            difficulty_match = 1 if q.difficulty == target_difficulty else 0
            return (overlap, difficulty_match, str(q.id))

        # Sort descending on (overlap, difficulty_match); stable, deterministic.
        return sorted(candidates, key=score, reverse=True)[0]

    async def _ensure_seed_questions(self, track_id: uuid.UUID, answered_ids: list[uuid.UUID]) -> Question | None:
        """
        Last-resort questions when a track has an empty bank.

        JAVA ONLY, AND ONLY FOR JAVA ROLES. This is the other half of why a Deloitte Analyst
        got the same interview every time: when AI planning failed or the bank was empty,
        this seeded the Java fundamentals set for whatever the track was — the same ~37
        questions, in the same order, forever.

        For a non-Java role it now seeds nothing and returns None. That is not a worse
        outcome than it looks: the caller treats None as "no more questions", which ends the
        interview cleanly and lets the candidate reach their report, whereas the alternative
        is filling a consulting screen with questions about the JVM. Being asked about the
        wrong subject is worse than being asked less, because it is the thing that makes a
        practice interview feel fake.
        """
        from app.models.company import QuestionCategory
        from app.models.question import QuestionDifficulty, QuestionType, Topic

        track = await self.db.get(InterviewTrack, track_id)
        track_name = track.name if track else ""
        if not _is_java_role(track_name, ""):
            logger.info(
                "seed_skipped_non_java_role",
                track_id=str(track_id),
                track_name=track_name,
                reason="the curated seed bank is Java; seeding it here would ask this role "
                "about the wrong subject",
            )
            return None

        cat = await self.db.scalar(select(QuestionCategory).where(QuestionCategory.track_id == track_id))
        if not cat:
            cat = QuestionCategory(
                id=uuid.uuid4(),
                track_id=track_id,
                name="Java Core",
                slug="java-core",
                order_index=0,
                is_active=True,
            )
            self.db.add(cat)
            await self.db.flush()

        # The shared bank, not a copy. There used to be five questions hardcoded
        # here and five more in knowledge/questions/java_core.yaml, which only a
        # manual seed script read — two divergent sets, neither big enough to fill
        # a twelve-question interview, which is why a short AI plan had nothing to
        # be topped up from. app/data/java_fundamentals.py is now the one source.
        from app.data.java_fundamentals import JAVA_QUESTION_BANK  # noqa: PLC0415

        # One Topic row per bank topic. The report groups scores by topic, so
        # seeding everything under a single "Java Fundamentals" topic — as this
        # did — made the topic breakdown a single bar and told a candidate nothing
        # about where they were weak.
        # Fetch every existing topic for this category in one query, then fill the gaps.
        # This looked up each bank topic individually — around twenty round trips — and
        # while seeding only runs when the bank is empty, it runs INSIDE a candidate's
        # first request, so they wore all of it.
        wanted = list(dict.fromkeys(q["topic"] for q in JAVA_QUESTION_BANK))
        existing_topics = {
            t.name: t
            for t in (
                await self.db.execute(
                    select(Topic).where(Topic.category_id == cat.id, Topic.name.in_(wanted))
                )
            ).scalars()
        }

        topic_rows: dict[str, Topic] = {}
        for name in wanted:
            row = existing_topics.get(name)
            if not row:
                row = Topic(
                    id=uuid.uuid4(),
                    category_id=cat.id,
                    name=name,
                    slug=f"{name.lower().replace(' ', '-').replace('&', 'and')[:40]}-{uuid.uuid4().hex[:6]}",
                    order_index=0,
                )
                self.db.add(row)
                await self.db.flush()
            topic_rows[name] = row

        _DIFFICULTY = {"easy": QuestionDifficulty.EASY, "medium": QuestionDifficulty.MEDIUM}
        _TYPE = {"conceptual": QuestionType.CONCEPTUAL, "practical": QuestionType.PRACTICAL}
        sample_questions = [
            {
                "content": q["content"],
                "difficulty": _DIFFICULTY[q["difficulty"]],
                "type": _TYPE[q["type"]],
                "keywords": q["keywords"],
                "ideal": q["ideal"],
                "topic_id": topic_rows[q["topic"]].id,
            }
            for q in JAVA_QUESTION_BANK
        ]

        # And one query for every bank question that already exists, rather than one per
        # question — this is the bigger of the two, because the bank is ~37 questions.
        # Bank questions are session_id IS NULL by definition (migration 010), so this is
        # the same predicate the loop used, hoisted out of it.
        wanted_contents = [sq["content"] for sq in sample_questions]
        # Whole rows, not just contents: the branch below reuses the existing Question
        # object when the bank question is already seeded.
        already = {
            q.content: q
            for q in (
                await self.db.execute(
                    select(Question).where(
                        Question.content.in_(wanted_contents),
                        Question.session_id.is_(None),
                    )
                )
            ).scalars()
        }

        created_questions = []
        for sq in sample_questions:
            existing = already.get(str(sq["content"]))
            if not existing:
                q = Question(
                    id=uuid.uuid4(),
                    topic_id=sq["topic_id"],
                    content=sq["content"],
                    difficulty=sq["difficulty"],
                    question_type=sq["type"],
                    expected_keywords=sq["keywords"],
                    ideal_answer=sq["ideal"],
                )
                self.db.add(q)
                created_questions.append(q)
            else:
                created_questions.append(existing)

        await self.db.commit()

        for q in created_questions:
            if q.id not in answered_ids:
                return q

        return created_questions[0] if created_questions else None

    async def submit_answer(
        self,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        content: str,
        delivery: dict | None = None,
    ) -> dict:
        """
        Record the candidate's answer — no scoring here. Scoring is deferred to
        the end of the interview (report generation), so there's no per-answer
        AI wait and no score shown mid-interview; the flow stays fluent.

        `delivery` (optional) carries the client-measured speaking metrics for
        this answer — filler words, pauses, words and speaking seconds. It is
        stored BOTH ways on purpose:

          on the answer   in full, including where each pause fell, so the
                          detailed analysis can replay the candidate's own answer
                          back to them with the hesitations marked in position.
          on the session   as running totals, which is what the report's headline
                          delivery figures ("16 filler words, 131 wpm") are built
                          from.

        Only the totals were kept before, so the pause positions were discarded at
        the point of submission and the detail could never be recovered.
        """
        session = await self.db.get(InterviewSession, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        # The question must be one this session could actually have been asked:
        # a bank question, or one generated for this session. Nothing checked
        # this before — the endpoint verified the SESSION belonged to the caller
        # and then filed the answer against whatever question_id arrived.
        #
        # It matters beyond hygiene. The cross-question generator reads the most
        # recent answer and its question and asks the model to probe "what they
        # said about this", so a mismatched pair produces a follow-up about a
        # topic the candidate never discussed — the same symptom as the pool
        # leak, reached a different way. A stale client render replaying an old
        # question id is enough to trigger it.
        question = await self.db.get(Question, question_id)
        if question is None:
            raise ValueError(f"Question {question_id} not found.")
        if question.session_id is not None and question.session_id != session_id:
            raise ValueError("That question belongs to a different interview session.")

        ans = Answer(
            id=uuid.uuid4(),
            session_id=session_id,
            question_id=question_id,
            content=content,
            delivery=delivery or None,
            word_count=int(delivery.get("words") or 0) if delivery else None,
            response_time_seconds=(
                int(delivery.get("speaking_seconds") or 0) if delivery else None
            ),
        )
        self.db.add(ans)
        session.questions_asked = (session.questions_asked or 0) + 1

        # Clear the parked cross-question once it has been answered, so the next
        # /next call is free to move on instead of serving it again.
        meta_pending = dict(session.session_metadata or {})
        if meta_pending.get("pending_cross_id") == str(question_id):
            meta_pending.pop("pending_cross_id", None)
            session.session_metadata = meta_pending

        if delivery:
            meta = dict(session.session_metadata or {})
            agg = dict(meta.get("delivery") or {})
            for key in (
                "filler_count",
                "pause_count",
                "total_pause_seconds",
                "words",
                "speaking_seconds",
                "unprofessional_count",
            ):
                agg[key] = (agg.get(key) or 0) + int(delivery.get(key) or 0)
            agg["answers"] = (agg.get("answers") or 0) + 1
            # The distinct words, not a count, because the report quotes them back:
            # "you said X" is actionable in a way "1 incident" is not. Deduped
            # across the whole session and capped, since this lands in JSONB.
            said = {str(w).strip().lower() for w in (delivery.get("unprofessional_words") or [])}
            if said:
                merged = sorted(set(agg.get("unprofessional_words") or []) | said)
                agg["unprofessional_words"] = merged[:40]
            meta["delivery"] = agg
            session.session_metadata = meta

        await self.db.flush()

        # THEY DECLINED THE TOPIC — so stop asking about it.
        #
        # After the flush, because the decline is judged on an answer that must already be
        # persisted: _drop_declined_topic reads back which planned questions are unanswered,
        # and this one has to count as answered or it would be pruned as though it were still
        # to come.
        #
        # Guarded on there being a plan at all. The adaptive path picks each question from
        # live signals and has no roadmap to prune; it is _adaptive_signals' job to steer
        # there, and pruning a plan that does not exist would be a silent no-op wearing the
        # costume of a feature.
        declined = said_dont_know(content)
        if declined and (session.session_metadata or {}).get("planned_question_ids") is not None:
            meta = dict(session.session_metadata or {})
            dropped = await self._drop_declined_topic(session, question, meta)
            if dropped:
                # Topped back up from OTHER topics so the interview keeps its advertised
                # length. Without this, honesty would visibly shorten the interview — which
                # is both unfair and an incentive to bluff, the exact behaviour this product
                # exists to detect.
                meta["planned_question_ids"] = await self._top_up_plan(
                    session.track_id,
                    list(meta.get("planned_question_ids") or []),
                    exclude_topic_ids={
                        uuid.UUID(t) for t in (meta.get("declined_topic_ids") or [])
                    },
                )
                session.session_metadata = meta
                # SQLAlchemy does not track in-place mutation of a JSONB dict, so the
                # reassignment above is what marks it dirty. Flagging it explicitly as well,
                # because the reassignment is easy to "tidy away" in a later refactor and the
                # failure would be a silent no-write.
                flag_modified(session, "session_metadata")
                logger.info(
                    "interview_dropped_declined_topic",
                    session_id=str(session_id),
                    topic_id=str(question.topic_id),
                    questions_dropped=dropped,
                )

        answered = await self.db.scalar(
            select(func.count()).select_from(Answer).where(Answer.session_id == session_id)
        )
        await self.db.commit()

        return {
            "status": "recorded",
            "questions_answered": answered or 0,
            # DID THEY DECLINE, rather than answer badly?
            #
            # Decided here rather than in the browser, and that is not incidental. The rule
            # is subtle enough to need its own module and forty tests (see dont_know.py),
            # and a client-side copy would drift from it the first time either changed —
            # producing a panel that offers somebody an easier topic in the middle of a
            # correct answer. It also keeps the behaviour identical for any future client.
            #
            # The caller uses this to run the panel's `pivot` stage, and the same value has
            # already been used above to prune the declined topic out of the rest of the plan.
            # One evaluation, reused: dont_know.py is deliberately subtle, and calling it
            # twice on the same text is an invitation for the spoken pivot and the pruning to
            # disagree about whether the candidate declined at all.
            #
            # The answer is still recorded and scored exactly as it always was, because
            # "I don't know" IS an answer to a question and is graded as one.
            "declined": declined,
        }

    async def complete_session(self, session_id: uuid.UUID):
        session = await self.db.get(InterviewSession, session_id)
        if session:
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.now(UTC)

            # Record how long it took. `duration_seconds` was declared on the
            # model and summed by /users/me/stats, but nothing ever wrote it — so
            # "Hours practiced" on the dashboard was structurally 0 for every user
            # forever, not because they had not practised.
            #
            # Clamped at both ends. Below zero is impossible but a clock change
            # could produce it; the upper bound stops a session left open
            # overnight from claiming twelve hours of practice, which would be a
            # lie in the more flattering direction.
            if session.started_at:
                started = session.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                elapsed = int((session.completed_at - started).total_seconds())
                session.duration_seconds = max(0, min(elapsed, MAX_SESSION_SECONDS))

            await self.db.commit()
