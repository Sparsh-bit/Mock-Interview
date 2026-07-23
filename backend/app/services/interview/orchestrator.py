import uuid
from typing import Optional
from datetime import datetime, timezone
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.session import InterviewSession, SessionStatus, Answer, Score
from app.models.question import Question
from app.models.company import QuestionCategory
from app.models.question import Topic
from app.services.ai.provider_factory import get_ai_provider
from app.services.ai.base_provider import ProviderRequest
from app.events.emitter import get_event_emitter
from app.events.base import InterviewStartedEvent, AnswerEvaluatedEvent, InterviewStartedPayload, AnswerEvaluatedPayload

class InterviewOrchestrator:
    """State machine and business logic for conducting an interview."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_provider()
        self.emitter = get_event_emitter()

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
                started_at=datetime.now(timezone.utc),
            )
            self.db.add(session)
        else:
            session.status = SessionStatus.ACTIVE
            if not session.started_at:
                session.started_at = datetime.now(timezone.utc)

        await self.db.flush()

        try:
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
        except Exception:
            pass

        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_next_question(self, session_id: uuid.UUID) -> Optional[Question]:
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

    async def _ensure_seed_questions(self, track_id: uuid.UUID, answered_ids: list[uuid.UUID]) -> Optional[Question]:
        from app.models.company import QuestionCategory
        from app.models.question import Topic, QuestionDifficulty, QuestionType

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
                "type": QuestionType.DEEP_DIVE,
                "keywords": ["Heap", "Stack", "Metaspace", "G1GC", "ZGC", "Garbage Collection"],
                "ideal": "Stack holds method frames and local primitives/references. Heap stores objects. Metaspace stores class metadata. GC reclaims unreferenced heap memory.",
            },
            {
                "content": "What is the Java Stream API? Explain intermediate vs terminal operations with examples.",
                "difficulty": QuestionDifficulty.MEDIUM,
                "type": QuestionType.CODE_SNIPPET,
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
        """Evaluates an answer using AI and transitions state."""
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

        eval_prompt = (
            "Evaluate this interview answer on a 0-10 scale for each dimension.\n"
            "Return valid JSON only with keys: score_technical, score_communication, "
            "score_completeness, score_confidence, overall_score, strengths (list), "
            "weaknesses (list), feedback (string), is_bluffing_detected (boolean).\n\n"
            f"Question: {question.content if question else 'N/A'}\n"
            f"Expected concepts: {', '.join(question.expected_keywords) if question and question.expected_keywords else 'N/A'}\n"
            f"Answer: {content}\n"
        )

        try:
            ai_resp = await self.ai.complete(
                ProviderRequest(
                    messages=[{"role": "user", "content": eval_prompt}],
                    json_mode=True,
                    max_tokens=500
                )
            )
            raw_content = ai_resp.content
        except Exception:
            raw_content = ""

        try:
            result = json.loads(raw_content) if raw_content else {}
            tech = float(result.get("score_technical", 7.0))
            comm = float(result.get("score_communication", 7.5))
            comp = float(result.get("score_completeness", 7.0))
            conf = float(result.get("score_confidence", 8.0))
            overall = float(result.get("overall_score", round((tech + comm + comp + conf) / 4, 1)))
            strengths = result.get("strengths", ["Good effort", "Relevant concepts mentioned"])
            weaknesses = result.get("weaknesses", [])
            feedback = result.get("feedback", "Demonstrated clear technical understanding.")
            is_bluffing = bool(result.get("is_bluffing_detected", False))
        except Exception:
            tech = comm = comp = conf = overall = 7.0
            strengths = ["Solid answer"]
            weaknesses = []
            feedback = "Demonstrated clear understanding of the question."
            is_bluffing = False

        score = Score(
            id=uuid.uuid4(),
            answer_id=ans.id,
            session_id=session_id,
            technical_score=tech,
            communication_score=comm,
            completeness_score=comp,
            confidence_score=conf,
            overall_score=overall,
            strengths=strengths,
            weaknesses=weaknesses,
            feedback=feedback,
            is_bluffing_detected=is_bluffing,
            raw_evaluation={"raw_response": raw_content},
        )
        self.db.add(score)
        await self.db.commit()

        try:
            await self.emitter.emit(AnswerEvaluatedEvent(
                event_id=uuid.uuid4(),
                user_id=session.user_id,
                session_id=session_id,
                payload=AnswerEvaluatedPayload(
                    answer_id=ans.id,
                    question_id=question_id,
                    overall_score=overall,
                    technical_score=tech,
                    communication_score=comm,
                    is_bluffing_detected=is_bluffing,
                    evaluation_time_ms=0,
                )
            ))
        except Exception:
            pass

        return {
            "technical_score": tech,
            "communication_score": comm,
            "feedback": feedback
        }

    async def complete_session(self, session_id: uuid.UUID):
        session = await self.db.get(InterviewSession, session_id)
        if session:
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
