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

import asyncio
import json
import math
import random
import uuid
from typing import Literal, TypedDict, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import cache_delete, cache_get, cache_set, get_redis
from app.db.session import AsyncSession, get_db
from app.services.activity import log_activity
from app.services.ai import vector_cache

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


class _PickedQuestion(TypedDict):
    """
    One quiz question, normalised across its two possible sources.

    The AI path yields pydantic `QuizQuestion` objects and the bank yields plain dicts. Since
    a single quiz can now be filled from BOTH — the bank tops up whatever the model was short
    — they have to meet in one shape before the answer key is built, or the key and the
    public questions can drift apart depending on where each question came from.

    A TypedDict rather than a bare dict so mypy checks that shape at every construction site;
    the two sources are in different functions and nothing else would catch a mismatch.
    """

    question: str
    options: list[str]
    correct_index: int
    explanation: str
    topic: str
    difficulty: str


def _bank_fill(need: int, exclude: list[str] | None = None) -> list[_PickedQuestion]:
    """
    `need` questions from the curated bank, in the same shape the AI path produces.

    The safety net under the generated quiz. Requiring the AI to return the full count turns
    a persistent undershoot into a raised error, and the honest response to that is not a
    503 — it is the questions we already have sitting in a Python module, needing no vendor
    and no network.

    Returns fewer than `need` only when the bank itself cannot cover it, which the caller
    surfaces rather than papering over.
    """
    from app.data.quiz_bank import QUIZ_BANK  # noqa: PLC0415

    seen = {q.strip().lower() for q in (exclude or [])}
    pool: list[_PickedQuestion] = [
        {
            "question": q["question"],
            "options": list(q["options"]),
            "correct_index": q["correct_index"],
            "explanation": q.get("explanation", ""),
            "topic": topic,
            "difficulty": q.get("difficulty", "medium"),
        }
        for topic, qs in QUIZ_BANK.items()
        for q in qs
        # Not a duplicate of something the model already produced. Two near-identical
        # questions in one quiz is a more obvious defect than a quiz being one short.
        if q["question"].strip().lower() not in seen
    ]
    return random.sample(pool, min(need, len(pool)))


def _topic_slices(topics_str: str, batches: int) -> list[str]:
    """
    Deal the topic list round-robin into `batches` hands, as comma-separated strings.

    WHY THE BATCHES MUST NOT SHARE A PROMPT. Identical prompts produce heavily overlapping
    questions — during measurement the same first question came back on every run — so three
    concurrent batches given the whole topic list would return three near-copies. Dedupe would
    then discard most of them and the curated bank would fill a gap the AI had already been
    paid for: slower, more expensive, and a worse quiz than not batching at all.

    ROUND-ROBIN RATHER THAN CONTIGUOUS BLOCKS, so each batch gets a spread across the whole
    list rather than one end of it. Topic lists here are ordered roughly by theme (Java OOP,
    Collections, ... then Spring, REST, MVC), so contiguous slicing would hand one batch every
    core-language topic and another every framework topic — and a candidate whose framework
    batch timed out would get a quiz with no Spring in it at all. Interleaving means every
    batch is representative, so losing one costs breadth evenly rather than a whole subject.

    Falls back to the FULL list for every batch when there are fewer topics than batches.
    Slicing three topics into three hands gives each batch a single topic and asks it for seven
    questions on it, which is a narrower quiz than the candidate asked for; overlapping prompts
    with dedupe is the better failure here.
    """
    topics = [t.strip() for t in topics_str.split(",") if t.strip()]
    if batches <= 1 or len(topics) < batches:
        return [topics_str] * max(1, batches)
    return [", ".join(topics[i::batches]) for i in range(batches)]


# ─── Endpoints ────────────────────────────────────────────────────────────────


# ─── The shared question pool ─────────────────────────────────────────────────
#
# WHERE THIS SITS. The curated banks in app/data are consulted first and still top up any
# shortfall. The pool sits between them and the model: bank for what it covers, pool instead
# of a fresh generation, model only when the pool cannot cover the request. Nothing about the
# bank path changes.

#: Questions kept per pool row.
#:
#: A cache row is read and written WHOLE, so an uncapped pool eventually becomes the cost the
#: cache exists to avoid. 120 is roughly six maximum-size quizzes — enough that two draws
#: rarely overlap much, small enough that the row stays a few kilobytes of JSON.
_MAX_POOL = 120


def _pool_key(*, track_name: str, company: str, topics: str) -> str:
    """
    The cache key for a shared quiz pool.

    SYLLABUS AND CONFIG ONLY. These are the exact four inputs the generation prompt receives
    minus the count, which does not change what a question IS. Nothing here is derived from a
    candidate, which is what makes the row shareable at all — see the note on `quiz_pool` in
    vector_cache.CACHEABLE_FEATURES.

    Topics are truncated for the same reason `question_bank` truncates them: the embedding
    stops discriminating long before the string does, and an unbounded key is an unbounded
    write.
    """
    return f"{track_name} | {company} | {topics[:300]}"


def _valid_pool_row(row: object) -> bool:
    """
    Does this cached row still match `_PickedQuestion`?

    NOT DEFENSIVENESS FOR ITS OWN SAKE. A cache row is JSONB written by whatever version of
    this code was deployed when it was stored, and rows outlive deploys. A row missing
    `correct_index` would build an answer key with a hole in it, and a row whose `options` had
    become a string would render as four one-character choices — both would reach a candidate
    as a broken quiz rather than as an error anybody sees.

    Checking is also what makes the cast at the call site honest: after this filter the shape is
    known, not assumed. A row that fails is simply dropped, so a stale pool degrades to a
    smaller pool and then to a generation, which is the same path a miss takes.
    """
    if not isinstance(row, dict):
        return False
    if not isinstance(row.get("options"), list) or len(row["options"]) < 2:
        return False
    if not isinstance(row.get("correct_index"), int) or isinstance(row.get("correct_index"), bool):
        return False
    if not 0 <= row["correct_index"] < len(row["options"]):
        return False
    return all(
        isinstance(row.get(field), str) and row.get(field)
        for field in ("question", "explanation", "topic", "difficulty")
    )


def _norm_q(question: object) -> str:
    """A question's identity for dedupe: its text, case- and space-insensitive."""
    if isinstance(question, dict):
        text = question.get("question") or question.get("content") or ""
    else:
        text = getattr(question, "question", "") or getattr(question, "content", "")
    return " ".join(str(text).split()).strip().lower()


def _merge_pool(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """
    Add newly generated questions to a pool, without duplicates, oldest trimmed first.

    ORDER IS LOAD-BEARING at the cap: the trim keeps the TAIL, so newly generated questions
    always survive and the oldest fall out. Trimming the other way would make a full pool
    permanently unable to take new material, which is a cache that silently stops learning.
    """
    merged: list[dict] = []
    seen: set[str] = set()
    for item in [*existing, *fresh]:
        norm = _norm_q(item)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        merged.append(item)
    if len(merged) > _MAX_POOL:
        merged = merged[-_MAX_POOL:]
    return merged


def _draw_from_pool(pool: list[dict], *, want: int, rng: random.Random) -> list[dict]:
    """
    Take up to `want` distinct questions from the pool at random.

    RANDOM IS THE POINT, not a detail. A deterministic slice would serve every candidate — and
    every retake — the same quiz, which is the objection the allowlist raised against caching
    quizzes at all. `sample` never repeats within a draw, so a short pool yields what it has
    rather than padding with duplicates.
    """
    if not pool:
        return []
    return rng.sample(pool, k=min(want, len(pool)))


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

    # ── GENERATED IN PARALLEL BATCHES, BECAUSE LATENCY IS OUTPUT-TOKEN-BOUND ──────────
    #
    # MEASURED, not assumed: 5 questions took 8.9s, 7 took 11.0s, and 20 did not finish
    # inside 20s at all. The wall-clock of one call scales with how many questions it is
    # asked to write, so a single request for the maximum count cannot be served inside any
    # budget the browser will wait for — the client aborts at 30s. Raising the budget could
    # not fix that; there is no room above 30 to raise it into.
    #
    # Splitting the count into concurrent batches makes the wall-clock the cost of the
    # LARGEST batch instead of the sum, so a 20-question quiz costs about what a 7-question
    # one does. This is what makes a full-size quiz actually generate rather than always
    # falling through to the bank.
    #
    # THE TOPICS ARE DEALT OUT BETWEEN THE BATCHES, and that is not an optimisation — it is
    # required for correctness. Identical prompts produce heavily overlapping questions (the
    # same first question came back on every run during measurement), so three batches given
    # the same topic list would return three near-copies and dedupe would throw most of them
    # away, leaving the bank to fill a gap that the AI had been paid for. A distinct slice per
    # batch makes them cover different ground, which is also a better quiz.
    # ── THE SHARED POOL, BEFORE ANYTHING IS GENERATED ────────────────────────────────
    #
    # The cheapest AI call is the one never made. (track, company, topics) is the WHOLE of the
    # generation prompt, so a pool built for that triple serves any candidate asking the same
    # thing — see the note on `quiz_pool` in vector_cache.CACHEABLE_FEATURES for why sharing is
    # safe here, and _draw_from_pool for why a hit is still a different quiz each time.
    #
    # A SUFFICIENT POOL SKIPS GENERATION ENTIRELY. Not "asks for fewer" — the batches below are
    # never launched, so a warm pool costs zero tokens and answers in milliseconds instead of
    # the 9-11 seconds a generation measured at.
    #
    # IT DOES NOT SHORT-CIRCUIT THE ENDPOINT. `picked` is filled and the generation is skipped;
    # everything downstream — the bank top-up, the quiz row, the session id, the response — runs
    # exactly as it does on a miss. An early `return` here would have bypassed all of it.
    #
    # FAILS SOFT. vector_cache.lookup swallows its own errors and returns None, so a missing
    # table, a cold index or a broken session is a MISS and the quiz generates as before.
    # Nothing added here can fail a quiz that would otherwise have worked.
    picked: list[_PickedQuestion] = []
    pool_key = _pool_key(track_name=track_name, company=company, topics=topics_str)
    pool: list[dict] = []
    _cached_pool = await vector_cache.lookup(db, feature="quiz_pool", key=pool_key)
    if _cached_pool:
        # VALIDATED, NOT TRUSTED. See _valid_pool_row: rows outlive deploys, and a row from an
        # older shape would reach a candidate as a broken quiz rather than as a visible error.
        pool = [q for q in (_cached_pool.get("questions") or []) if _valid_pool_row(q)]
    _served_from_pool = False
    if len(pool) >= request.count:
        # cast, not ignore: _valid_pool_row above checked every field of _PickedQuestion, so
        # the shape is established rather than asserted. JSONB cannot carry that through.
        picked = cast(
            "list[_PickedQuestion]", _draw_from_pool(pool, want=request.count, rng=random.Random())
        )
        _served_from_pool = True
        logger.info("quiz_served_from_pool", pool_size=len(pool), served=len(picked))

    if not picked:

        batch_max = int(settings.QUIZ_BATCH_MAX_QUESTIONS or request.count) or request.count
        batch_count = max(1, math.ceil(request.count / batch_max))
        per_batch = math.ceil(request.count / batch_count)
        slices = _topic_slices(topics_str, batch_count)

        async def _generate_batch(topics_for_batch: str, want: int) -> list:
            """One batch. Raises whatever `generate_structured` raises; the caller isolates it."""
            # Budget tokens to the BATCH size (~300 tokens/question + buffer), not to the whole
            # quiz — the point of batching is that no single call writes the full count.
            messages = builder.chat(
                system_template="quiz_generator",
                user_content="Generate the quiz now, following the rules and output format.",
                track_name=track_name,
                topics=topics_for_batch,
                count=str(want),
                company=company,
                # Free text the candidate typed into the focus box.
                untrusted={"focus": focus},
            )
            # THE VALIDITY CHECK IS ON THE COUNT, NOT ON EMPTINESS, and that is the fix for "I
            # selected 5 questions and only 3 came".
            #
            # It used to be `bool(q.questions)`. A model asked for five questions and returning
            # three therefore passed validation on the first attempt, and the candidate silently
            # got a shorter quiz than the one they configured — with the score reported out of the
            # number that arrived, so nothing on screen indicated anything had gone wrong. Models
            # undershoot a requested count routinely; nothing else in the pipeline was checking,
            # so the request was effectively a suggestion.
            #
            # Requiring the full count makes a short generation a retry instead of a result.
            # Asking for MORE is fine and is trimmed below — over-delivery is not a defect.
            quiz, _ = await generate_structured(
                QuizGeneration,
                messages,
                max_tokens=min(300 * want + 600, 8000),
                attempts_per_provider=2,
                is_valid=lambda q: len(q.questions) >= want,
                cost_tier=CostTier.BALANCED,
                context="quiz_generation",
            )
            return list(quiz.questions)

        # ── BOUNDED, BECAUSE THE CLIENT IS ────────────────────────────────────────────────
        #
        # `generate_structured` has no deadline of its own: it loops every provider twice, and the
        # fallback provider's read timeout is 180 seconds. The browser aborts at 30
        # (DEFAULT_TIMEOUT_MS, not overridden for this call), so an unbounded server always lost
        # that race — the candidate saw "request timeout" while this endpoint was still generating
        # a quiz that could no longer be delivered to anyone.
        #
        # `asyncio.wait` RATHER THAN `wait_for(gather(...))`, deliberately. A `wait_for` around a
        # `gather` cancels every batch when the deadline hits, so one slow batch would discard the
        # two that already succeeded and the candidate would get an all-bank quiz despite most of
        # it having been generated. `wait` hands back whatever finished, and the batches that did
        # not are simply cancelled — a partly-generated quiz topped up from the bank is strictly
        # better than either extreme.
        tasks = [
            asyncio.create_task(_generate_batch(topic_slice, per_batch)) for topic_slice in slices
        ]
        try:
            done, pending = await asyncio.wait(
                tasks, timeout=settings.QUIZ_GENERATION_BUDGET_SECONDS or None
            )
        except asyncio.CancelledError:
            # THE CANDIDATE CLOSED THE TAB, AND THE BATCHES WOULD HAVE KEPT GENERATING.
            #
            # `create_task` schedules independently of the awaiting coroutine, so cancelling this
            # request does NOT cancel them: without this, every abandoned /quiz/start left four AI
            # calls running to completion, billed, for a quiz nobody would ever see — and a
            # candidate impatiently refreshing would multiply that. Re-raised after cleanup because
            # the request really is cancelled; only the orphans are ours to tidy.
            for task in tasks:
                task.cancel()
            raise
        for task in pending:
            task.cancel()

        generated: list = []
        failures = 0
        for task in tasks:
            if task not in done:
                continue
            try:
                generated.extend(task.result())
            except Exception as exc:
                # ISOLATED PER BATCH. One provider failure or one malformed batch must not cost the
                # candidate the batches that worked; the shortfall is filled from the bank below,
                # which is the same fallback a total outage has always used.
                #
                # BROAD ON PURPOSE, BUT NEVER SILENT. Anything a batch can raise —
                # AIProviderUnavailableError, a validation failure, a schema surprise — has the same
                # correct response here, and letting an unanticipated one escape would turn a
                # recoverable partial quiz into a 500. So it is caught and LOGGED with its type,
                # because a broad catch that says nothing is how a real bug hides for months.
                # `CancelledError` is a BaseException and so is not caught: the batches this loop
                # cancelled on timeout are skipped above rather than reported as failures.
                failures += 1
                logger.warning(
                    "quiz_batch_failed",
                    error_type=type(exc).__name__,
                    error=str(exc) or type(exc).__name__,
                )

        # Deduped across batches before trimming, so a question that two batches both happened to
        # write does not consume two of the candidate's slots. Normalised on text because the
        # duplicate that matters is the one a human would recognise, not a byte-identical string.
        # Declared before the pool check above; reset here so the dedupe below starts clean.
        picked = []
        seen: set[str] = set()
        for q in generated:
            key = q.question.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            picked.append({
                "question": q.question,
                "options": list(q.options),
                "correct_index": q.correct_index,
                "explanation": q.explanation,
                "topic": q.topic,
                "difficulty": q.difficulty,
            })
        # Trimmed to exactly what was asked for. Batches round UP to cover the count, so an
        # over-delivery is the normal case rather than a model quirk.
    picked = picked[: request.count]

    # ── FEED THE POOL WITH WHAT WAS JUST PAID FOR ────────────────────────────────────
    #
    # Merged rather than replaced, so the pool grows across requests with different counts and
    # topic slices and the hit rate climbs instead of resetting each time.
    #
    # ONLY WHEN SOMETHING WAS GENERATED. On a pool hit `pool` and `picked` are the same
    # material, so re-storing would be a write for no gain. Placed before the bank top-up
    # deliberately: the bank's questions are already free and already shared, so putting them
    # in a cache of PAID generations would inflate the row without saving anything.
    #
    # vector_cache.store swallows its own failures, so a successful generation can never be
    # turned into an error by a cache write.
    if picked and not _served_from_pool:
        await vector_cache.store(
            db,
            feature="quiz_pool",
            key=pool_key,
            payload={"questions": _merge_pool(pool, [dict(q) for q in picked])},
        )


    if len(picked) < request.count:
        # TIGHTENING THE VALIDITY CHECK MUST NOT TURN A SHORT QUIZ INTO NO QUIZ.
        #
        # The curated bank fills in: it needs no AI, it is the same shape, and it is already
        # the source for the /bank/start endpoint — a candidate who asked for five questions
        # gets five questions.
        #
        # Logged with the budget and the batch shape so a spike of these reads as "the vendor
        # is slow" rather than "the quiz feature is broken". Those are different operational
        # problems and only one of them is ours.
        logger.warning(
            "quiz_generation_short_falling_back_to_bank",
            count=request.count,
            generated=len(picked),
            batches=batch_count,
            timed_out=len(pending),
            failed=failures,
            budget_seconds=settings.QUIZ_GENERATION_BUDGET_SECONDS,
        )
        picked.extend(
            _bank_fill(request.count - len(picked), exclude=[p["question"] for p in picked])
        )

    if not picked:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not build a quiz right now. Please try again in a moment.",
        )

    quiz_id = str(uuid.uuid4())
    public_questions: list[QuizOption] = []
    answer_key: dict[str, dict] = {}
    for q in picked:
        qid = str(uuid.uuid4())
        options = q["options"]
        # Clamp a possibly-out-of-range correct_index to a valid option.
        raw_correct = q["correct_index"]
        correct = raw_correct if 0 <= raw_correct < len(options) else 0
        public_questions.append(
            QuizOption(
                id=qid,
                question=q["question"],
                options=options,
                topic=q["topic"],
                difficulty=q["difficulty"],
            )
        )
        answer_key[qid] = {
            "question": q["question"],
            "options": options,
            "correct_index": correct,
            "explanation": q["explanation"],
            "topic": q["topic"],
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
    #: How many questions this topic has at each level, so the picker can show
    #: what is actually available instead of offering "hard" on a topic with none.
    easy: int
    medium: int
    hard: int


class StartBankQuizRequest(BaseModel):
    topic: str | None = None  # None = mix across all topics
    count: int = Field(default=8, ge=3, le=30)
    minutes: int = Field(default=10, ge=1, le=60)
    #: None = any difficulty. The bank endpoint has always returned each
    #: question's difficulty to the client but there was no way to ask for one,
    #: so a candidate who wanted a hard round had to keep re-rolling.
    difficulty: Literal["easy", "medium", "hard"] | None = None


@router.get("/bank/topics", response_model=list[BankTopic])
async def bank_topics(current_user: CurrentUser):
    """List curated bank topics and how many questions each has."""
    from app.data.quiz_bank import QUIZ_BANK  # noqa: PLC0415

    def _n(qs: list[dict], level: str) -> int:
        return sum(1 for q in qs if q.get("difficulty") == level)

    return [
        BankTopic(
            topic=t,
            count=len(qs),
            easy=_n(qs, "easy"),
            medium=_n(qs, "medium"),
            hard=_n(qs, "hard"),
        )
        for t, qs in QUIZ_BANK.items()
    ]


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

    # Narrow by difficulty when asked. Deliberately not silent: if the filter
    # leaves nothing, say which combination is empty rather than quietly serving a
    # mixed-difficulty quiz the candidate did not ask for.
    if request.difficulty:
        filtered = [q for q in pool if q.get("difficulty") == request.difficulty]
        if not filtered:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No {request.difficulty} questions"
                    + (f" for '{request.topic}'" if request.topic else "")
                    + " in the bank yet."
                ),
            )
        pool = filtered

    if not pool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No questions in the bank.")

    # SAY SO WHEN THE BANK CANNOT COVER THE REQUEST, rather than quietly serving fewer.
    #
    # `min(count, len(pool))` silently short-changed the candidate in exactly the way the AI
    # path did: ask for fifteen hard SQL questions, get four, with the score reported out of
    # four and nothing on screen saying why. The difficulty filter above already refuses
    # loudly when it empties the pool — this is the same situation one step later, and it
    # deserves the same honesty.
    if len(pool) < request.count:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Only {len(pool)} "
                + (f"{request.difficulty} " if request.difficulty else "")
                + "questions available"
                + (f" for '{request.topic}'" if request.topic else " in the bank")
                + f" — you asked for {request.count}."
            ),
        )

    sample = random.sample(pool, request.count)

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
