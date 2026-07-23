import contextlib
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AIProviderUnavailableError
from app.events.base import (
    AnswerEvaluatedEvent,
    AnswerEvaluatedPayload,
    InterviewStartedEvent,
    InterviewStartedPayload,
)
from app.events.emitter import get_event_emitter
from app.models.company import InterviewTrack, QuestionCategory
from app.models.question import Question, Subtopic, Topic
from app.models.session import Answer, InterviewSession, Score, SessionStatus
from app.prompts.prompt_loader import get_prompt_loader
from app.services.ai.base_provider import ProviderError, ProviderRequest
from app.services.ai.json_validator import AIValidationError, JSONValidator
from app.services.ai.prompt_builder import PromptBuilder
from app.services.ai.provider_factory import get_ai_provider
from app.services.ai.response_parser import ResponseParser
from app.services.ai.schemas import GeneratedQuestion, InterviewerResponse

logger = structlog.get_logger(__name__)

# One evaluation attempt, plus one retry on a malformed/unavailable response —
# after that, fail closed (AIProviderUnavailableError) rather than silently
# persist a made-up score. See prompt.md's "Refined Niche" section: scoring
# must be example-driven and honest, never a fake confident-looking verdict.
_MAX_EVALUATION_ATTEMPTS = 2


class InterviewOrchestrator:
    """State machine and business logic for conducting an interview."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_provider()
        self.emitter = get_event_emitter()
        self.prompt_builder = PromptBuilder(get_prompt_loader())
        self.response_parser = ResponseParser(JSONValidator())

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

        parsed: GeneratedQuestion | None = None
        for attempt in range(2):
            try:
                resp = await self.ai.complete(
                    ProviderRequest(messages=messages, json_mode=True, max_tokens=700)
                )
            except ProviderError:
                logger.warning("question_gen_provider_error", session_id=str(session.id), attempt=attempt)
                continue
            try:
                parsed = self.response_parser.parse(resp.content, GeneratedQuestion)
                break
            except AIValidationError:
                logger.warning("question_gen_validation_failed", session_id=str(session.id), attempt=attempt)
                continue

        if parsed is None or not parsed.content.strip():
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

    async def submit_answer(self, session_id: uuid.UUID, question_id: uuid.UUID, content: str) -> dict:
        """Evaluates an answer using AI and transitions state.

        Raises AIProviderUnavailableError (mapped to HTTP 503 by the global
        exception handler) if the AI evaluation cannot be produced after
        retrying — we never persist a made-up score to mask an AI failure.
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
        await self.db.flush()

        question = await self.db.get(Question, question_id)
        result, raw_content = await self._evaluate_answer(session, question, content)
        evaluation = result.evaluation

        score = Score(
            id=uuid.uuid4(),
            answer_id=ans.id,
            session_id=session_id,
            technical_score=evaluation.technical_score,
            communication_score=evaluation.communication_score,
            completeness_score=evaluation.completeness_score,
            confidence_score=evaluation.confidence_score,
            overall_score=evaluation.overall_score,
            strengths=evaluation.strengths,
            weaknesses=evaluation.weaknesses,
            feedback=evaluation.feedback,
            is_bluffing_detected=evaluation.is_bluffing_detected,
            # Persist the adaptive-selection signals alongside the raw response
            # so get_next_question() can steer topic/difficulty from what the
            # candidate actually said, not a fresh random pick.
            raw_evaluation={
                "raw_response": raw_content,
                "mentioned_concepts": evaluation.mentioned_concepts,
                "missed_concepts": evaluation.missed_concepts,
                "suggested_difficulty_adjustment": result.interview_state.suggested_difficulty_adjustment,
            },
        )
        self.db.add(score)
        await self.db.commit()

        with contextlib.suppress(Exception):
            await self.emitter.emit(AnswerEvaluatedEvent(
                event_id=uuid.uuid4(),
                user_id=session.user_id,
                session_id=session_id,
                payload=AnswerEvaluatedPayload(
                    answer_id=ans.id,
                    question_id=question_id,
                    overall_score=evaluation.overall_score,
                    technical_score=evaluation.technical_score,
                    communication_score=evaluation.communication_score,
                    is_bluffing_detected=evaluation.is_bluffing_detected,
                    evaluation_time_ms=0,
                )
            ))

        return {
            "technical_score": evaluation.technical_score,
            "communication_score": evaluation.communication_score,
            "completeness_score": evaluation.completeness_score,
            "confidence_score": evaluation.confidence_score,
            "overall_score": evaluation.overall_score,
            "strengths": evaluation.strengths,
            "weaknesses": evaluation.weaknesses,
            "feedback": evaluation.feedback,
            "is_bluffing_detected": evaluation.is_bluffing_detected,
        }

    async def _evaluate_answer(
        self, session: InterviewSession, question: Question | None, content: str
    ):
        """
        Evaluate a candidate's answer via the `interviewer` prompt template,
        with a validation-driven schema check and one retry on a malformed
        or unavailable AI response. See app/prompts/interviewer.md for the
        full contract this depends on.

        Returns (InterviewerResponse, raw_response_text).
        """
        track_name = "Unknown Track"
        if session.track_id:
            track = await self.db.get(InterviewTrack, session.track_id)
            if track:
                track_name = track.name

        topic_name = "General"
        subtopic_name = ""
        difficulty_level = question.difficulty if question else "medium"
        if question:
            topic = await self.db.get(Topic, question.topic_id)
            if topic:
                topic_name = topic.name
            if question.subtopic_id:
                subtopic = await self.db.get(Subtopic, question.subtopic_id)
                if subtopic:
                    subtopic_name = subtopic.name

        user_content = (
            f"Question asked: {question.content if question else 'N/A'}\n\n"
            f"Expected concepts: "
            f"{', '.join(question.expected_keywords) if question and question.expected_keywords else 'N/A'}\n\n"
            f"Candidate's answer:\n{content}"
        )

        messages = self.prompt_builder.chat(
            system_template="interviewer",
            user_content=user_content,
            track_name=track_name,
            topic_name=topic_name,
            subtopic_name=subtopic_name,
            difficulty_level=difficulty_level,
            question_count=str(session.questions_asked or 1),
            time_limit_minutes="5",
            candidate_experience_years="not specified",
        )

        last_raw_content = ""
        for attempt in range(_MAX_EVALUATION_ATTEMPTS):
            try:
                ai_resp = await self.ai.complete(
                    ProviderRequest(messages=messages, json_mode=True, max_tokens=800)
                )
            except ProviderError:
                logger.warning(
                    "ai_evaluation_provider_error", session_id=str(session.id), attempt=attempt
                )
                continue

            last_raw_content = ai_resp.content
            try:
                parsed = self.response_parser.parse(ai_resp.content, InterviewerResponse)
                return parsed, last_raw_content
            except AIValidationError:
                logger.warning(
                    "ai_evaluation_validation_failed", session_id=str(session.id), attempt=attempt
                )
                continue

        raise AIProviderUnavailableError(provider=self.ai.provider_name)

    async def complete_session(self, session_id: uuid.UUID):
        session = await self.db.get(InterviewSession, session_id)
        if session:
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.now(UTC)
            await self.db.commit()
