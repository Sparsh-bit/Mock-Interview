import contextlib
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
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
from app.services.ai.schemas import InterviewerResponse

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
        """Adaptively selects the next question based on session history."""
        session = await self.db.get(InterviewSession, session_id)
        if not session or session.status != SessionStatus.ACTIVE:
            return None

        answered = await self.db.scalars(
            select(Answer.question_id).where(Answer.session_id == session_id)
        )
        answered_ids = list(answered.all())

        # If user answered 10 or more questions in this session, complete session
        if len(answered_ids) >= 10:
            return None

        # Try track-specific selection first
        query = (
            select(Question)
            .join(Topic, Question.topic_id == Topic.id)
            .join(QuestionCategory, Topic.category_id == QuestionCategory.id)
            .where(QuestionCategory.track_id == session.track_id)
        )
        if answered_ids:
            query = query.where(Question.id.notin_(answered_ids))

        query = query.order_by(func.random()).limit(1)
        next_q = await self.db.scalar(query)

        # Fallback to any unanswered question in database
        if not next_q:
            fallback_query = select(Question)
            if answered_ids:
                fallback_query = fallback_query.where(Question.id.notin_(answered_ids))
            next_q = await self.db.scalar(fallback_query.order_by(func.random()).limit(1))

        # Auto-seed core questions if database question table is empty or exhausted
        if not next_q:
            next_q = await self._ensure_seed_questions(session.track_id, answered_ids)

        return next_q

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
        evaluation, raw_content = await self._evaluate_answer(session, question, content)

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
            raw_evaluation={"raw_response": raw_content},
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

        Returns (AnswerEvaluation, raw_response_text).
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
                return parsed.evaluation, last_raw_content
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
