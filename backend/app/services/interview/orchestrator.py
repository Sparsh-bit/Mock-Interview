import asyncio
import contextlib
import hashlib
import json
import random
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AIProviderUnavailableError
from app.db.redis import cache_get, cache_set, get_redis
from app.events.base import InterviewStartedEvent, InterviewStartedPayload
from app.events.emitter import get_event_emitter
from app.models.company import InterviewTrack, QuestionCategory
from app.models.question import Question, Topic
from app.models.report import ResumeFile
from app.models.session import Answer, InterviewSession, Score, SessionStatus
from app.prompts.prompt_loader import get_prompt_loader
from app.services.ai.generate import generate_structured
from app.services.ai.prompt_builder import PromptBuilder
from app.services.ai.schemas import GeneratedQuestion, InterviewPlan

logger = structlog.get_logger(__name__)

# How many questions the AI pre-generates for a planned interview, and the
# max number of live cross-questions injected during it (kept small so the
# interview stays fluent — most questions are served instantly from the plan).
_PLANNED_QUESTION_COUNT = 6
_MAX_CROSS_QUESTIONS = 2
# Plan reuse cache: we accumulate up to N distinct AI-generated plan variants
# per (company, program, focus) signature in Redis. Once N exist, a matching
# request instantly reuses a random variant instead of waiting on the slow
# free-tier model — fast AND still varied (and live cross-questions make every
# run different regardless). This is the free "now" phase; the same lookup seam
# can later be swapped for pgvector semantic matching without touching callers.
_MAX_PLAN_VARIANTS = 4
_PLAN_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
# Hard cap on how long we wait for the AI to build the plan before falling back
# to a DB-backed plan, so plan creation returns within a predictable time.
_PLAN_AI_BUDGET_SECONDS = 110.0


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
        resume_summary = resume_text.strip() or await self._resume_summary(user_id)
        # Resume-personalised plans are per-candidate, so they must NOT be shared
        # via the cache. Only generic (company/program/focus) plans are cacheable.
        personalized = bool(resume_text.strip()) or not resume_summary.startswith("(No resume")

        plan: InterviewPlan | None = None

        # 1) Try to reuse a previously-generated plan variant (instant, no LLM).
        cache_key = self._plan_cache_key(company, program, focus)
        variants: list[dict] = []
        if not personalized:
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
            messages = self.prompt_builder.chat(
                system_template="interview_plan",
                user_content="Design the interview plan now, following the rules and output format.",
                company=company.strip() or "a general tech company",
                program=program.strip() or "Software Engineer (fresher)",
                focus=focus.strip() or "(no specific focus — cover the standard areas for this role)",
                resume=resume_summary,
                question_count=str(_PLANNED_QUESTION_COUNT),
            )
            try:
                plan, _ = await asyncio.wait_for(
                    generate_structured(
                        InterviewPlan,
                        messages,
                        max_tokens=2500,
                        attempts_per_provider=1,
                        is_valid=lambda p: len(p.questions) >= 4,
                        context="interview_plan",
                    ),
                    timeout=_PLAN_AI_BUDGET_SECONDS,
                )
            except (AIProviderUnavailableError, TimeoutError):
                logger.warning("interview_plan_ai_unavailable_using_fallback", session_id=str(session.id))

            # Store a freshly-generated generic plan as a reusable variant.
            if plan is not None and len(plan.questions) >= 4 and not personalized:
                await self._save_plan_variant(cache_key, variants, plan)

        if plan is not None and len(plan.questions) >= 4:
            planned_ids, topics = await self._persist_plan(track_id, plan)
        else:
            planned_ids, topics = await self._fallback_plan(track_id)

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

    @staticmethod
    def _plan_cache_key(company: str, program: str, focus: str) -> str:
        """Stable cache key for a (company, program, focus) plan signature."""
        sig = "|".join(
            part.strip().lower()
            for part in (company or "", program or "", focus or "")
        )
        digest = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]  # noqa: S324 — cache key, not security
        return f"plan:variants:{digest}"

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
        self, track_id: uuid.UUID, plan: InterviewPlan
    ) -> tuple[list[str], list[str]]:
        """Persist a plan's questions as Question rows; return (ordered_ids, topics)."""
        planned_ids: list[str] = []
        for gq in plan.questions:
            if not gq.content.strip():
                continue
            topic = await self._get_or_create_topic(track_id, gq.topic_name)
            q = Question(
                id=uuid.uuid4(),
                topic_id=topic.id,
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

    async def _fallback_plan(self, track_id: uuid.UUID) -> tuple[list[str], list[str]]:
        """
        Build a solid interview plan WITHOUT the AI — a warm-up intro question
        followed by a spread of the track's existing questions (seeded if the
        track is empty). Guarantees the plan feature always returns quickly and
        never just hangs when the AI provider is slow or down.

        Returns (ordered_question_ids, topic_names).
        """
        # 1) Warm-up "tell me about yourself" opener, always first.
        intro_topic = await self._get_or_create_topic(track_id, "Introduction")
        intro = Question(
            id=uuid.uuid4(),
            topic_id=intro_topic.id,
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
            return list(
                await self.db.scalars(
                    select(Question)
                    .join(Topic, Question.topic_id == Topic.id)
                    .join(QuestionCategory, Topic.category_id == QuestionCategory.id)
                    .where(QuestionCategory.track_id == track_id)
                )
            )

        rows = await _track_questions()
        if not rows:
            await self._ensure_seed_questions(track_id, [])
            rows = await _track_questions()

        rank = {"easy": 0, "medium": 1, "hard": 2}
        tiers: dict[int, list[Question]] = {0: [], 1: [], 2: []}
        for q in rows:
            diff = getattr(q.difficulty, "value", q.difficulty)
            tiers[rank.get(diff, 1)].append(q)
        for tier in tiers.values():
            random.shuffle(tier)

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

        for q in ordered:
            ordered_ids.append(str(q.id))
            topic = await self.db.get(Topic, q.topic_id)
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

        if len(answered_ids) >= 10:
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
            .where(QuestionCategory.track_id == session.track_id)
        )
        if answered_ids:
            query = query.where(Question.id.notin_(answered_ids))
        candidates = list(await self.db.scalars(query))

        # Fallback to any unanswered question if the track pool is empty.
        if not candidates:
            fallback = select(Question)
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
        """
        meta = dict(session.session_metadata or {})
        if not meta.get("approved"):
            return None

        planned = meta.get("planned_question_ids", [])
        cross_ids = set(meta.get("cross_question_ids", []))
        answered_str = {str(a) for a in answered_ids}
        remaining = [qid for qid in planned if qid not in answered_str]

        # Occasional cross-question: after every 3rd answer, if we still have
        # planned questions left, haven't hit the cross-question cap, and the
        # last answered question wasn't itself a cross-question.
        answered_count = len(answered_ids)
        last_answer = await self.db.scalar(
            select(Answer).where(Answer.session_id == session.id).order_by(Answer.created_at.desc()).limit(1)
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
            cross = await self._generate_cross_question(last_q, last_answer.content)
            if cross is not None:
                meta["cross_asked"] = meta.get("cross_asked", 0) + 1
                meta["cross_question_ids"] = [*meta.get("cross_question_ids", []), str(cross.id)]
                session.session_metadata = meta
                await self.db.commit()
                return cross

        if not remaining:
            return None
        return await self.db.get(Question, uuid.UUID(remaining[0]))

    async def _generate_cross_question(
        self, last_question: Question | None, last_answer: str
    ) -> Question | None:
        """Generate one follow-up probing the candidate's last answer. Best-effort."""
        if last_question is None:
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
                context="cross_question",
            )
        except AIProviderUnavailableError:
            return None

        q = Question(
            id=uuid.uuid4(),
            topic_id=last_question.topic_id,
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
                context="question_generation",
            )
        except AIProviderUnavailableError:
            return None

        topic = await self._get_or_create_topic(session.track_id, parsed.topic_name)
        question = Question(
            id=uuid.uuid4(),
            topic_id=topic.id,
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
            return "medium", []

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
        from app.models.company import QuestionCategory
        from app.models.question import QuestionDifficulty, QuestionType, Topic

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

        top = await self.db.scalar(select(Topic).where(Topic.category_id == cat.id))
        if not top:
            top = Topic(
                id=uuid.uuid4(),
                category_id=cat.id,
                name="Java Fundamentals",
                slug="java-fundamentals",
                order_index=0,
            )
            self.db.add(top)
            await self.db.flush()

        sample_questions = [
            {
                "content": "Explain the difference between HashMap, Hashtable, and ConcurrentHashMap in Java. When would you use each?",
                "difficulty": QuestionDifficulty.MEDIUM,
                "type": QuestionType.CONCEPTUAL,
                "keywords": ["HashMap", "ConcurrentHashMap", "Thread safety", "Synchronized", "Bucket lock"],
                "ideal": "HashMap is unsynchronized and allows nulls. Hashtable is thread-safe via method locking. ConcurrentHashMap provides high concurrency using bucket-level locking.",
            },
            {
                "content": "What is the difference between final, finally, and finalize() in Java?",
                "difficulty": QuestionDifficulty.EASY,
                "type": QuestionType.CONCEPTUAL,
                "keywords": ["final keyword", "finally block", "finalize method", "Garbage collection"],
                "ideal": "final is a modifier for constants/methods/classes. finally is a try-catch block for cleanup. finalize() was a GC method deprecated in Java 9.",
            },
            {
                "content": "Explain Java's Memory Model: Heap vs Stack memory, Garbage Collection algorithms, and Metaspace.",
                "difficulty": QuestionDifficulty.HARD,
                "type": QuestionType.CONCEPTUAL,
                "keywords": ["Heap", "Stack", "Metaspace", "G1GC", "ZGC", "Garbage Collection"],
                "ideal": "Stack holds method frames and local primitives/references. Heap stores objects. Metaspace stores class metadata. GC reclaims unreferenced heap memory.",
            },
            {
                "content": "What is the Java Stream API? Explain intermediate vs terminal operations with examples.",
                "difficulty": QuestionDifficulty.MEDIUM,
                "type": QuestionType.PRACTICAL,
                "keywords": ["Stream API", "map", "filter", "collect", "Lazy evaluation"],
                "ideal": "Streams allow functional sequence processing. Intermediate operations (filter, map) are lazy. Terminal operations (collect, count) trigger execution.",
            },
            {
                "content": "How do Functional Interfaces and Lambda Expressions work in Java 8+? Give examples of Function, Predicate, and Consumer.",
                "difficulty": QuestionDifficulty.MEDIUM,
                "type": QuestionType.CONCEPTUAL,
                "keywords": ["FunctionalInterface", "Lambda", "Predicate", "Function", "Consumer"],
                "ideal": "Functional Interfaces have exactly one abstract method. Lambdas provide inline implementation. Predicate returns boolean, Function returns a transformed value, Consumer takes input with no return.",
            },
        ]

        created_questions = []
        for sq in sample_questions:
            existing = await self.db.scalar(select(Question).where(Question.content == sq["content"]))
            if not existing:
                q = Question(
                    id=uuid.uuid4(),
                    topic_id=top.id,
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
        this answer — filler words, pauses, words and speaking seconds — which
        we accumulate on the session so the final report can analyse delivery
        (e.g. "you paused a lot") across the whole interview.
        """
        session = await self.db.get(InterviewSession, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        ans = Answer(
            id=uuid.uuid4(),
            session_id=session_id,
            question_id=question_id,
            content=content,
        )
        self.db.add(ans)
        session.questions_asked = (session.questions_asked or 0) + 1

        if delivery:
            meta = dict(session.session_metadata or {})
            agg = dict(meta.get("delivery") or {})
            for key in ("filler_count", "pause_count", "total_pause_seconds", "words", "speaking_seconds"):
                agg[key] = (agg.get(key) or 0) + int(delivery.get(key) or 0)
            agg["answers"] = (agg.get("answers") or 0) + 1
            meta["delivery"] = agg
            session.session_metadata = meta

        await self.db.flush()
        answered = await self.db.scalar(
            select(func.count()).select_from(Answer).where(Answer.session_id == session_id)
        )
        await self.db.commit()

        return {"status": "recorded", "questions_answered": answered or 0}

    async def complete_session(self, session_id: uuid.UUID):
        session = await self.db.get(InterviewSession, session_id)
        if session:
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.now(UTC)
            await self.db.commit()
