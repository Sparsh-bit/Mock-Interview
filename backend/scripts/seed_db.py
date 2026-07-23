import asyncio
import uuid
import yaml
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.db.session import AsyncSessionFactory
from app.models.company import Company, InterviewTrack, QuestionCategory
from app.models.question import Question, FollowUpQuestion, QuestionDifficulty, QuestionType, Topic

async def seed_knowledge_base():
    """Seed the database with the core Cognizant Java FSE questions."""
    async with AsyncSessionFactory() as session:
        # Create Company
        company = await session.scalar(select(Company).where(Company.slug == "cognizant"))
        if not company:
            company = Company(
                id=uuid.uuid4(),
                name="Cognizant",
                slug="cognizant",
                description="Cognizant Digital Nurture program",
                is_active=True,
            )
            session.add(company)
            await session.flush()
        else:
            company.is_active = True

        # Create Track
        track = await session.scalar(select(InterviewTrack).where(InterviewTrack.slug == "java-fse"))
        if not track:
            track = InterviewTrack(
                id=uuid.uuid4(),
                company_id=company.id,
                name="Digital Nurture — Java FSE",
                slug="java-fse",
                description="Java Full Stack Engineer Track",
                is_active=True,
            )
            session.add(track)
            await session.flush()
        else:
            track.is_active = True

        # Parse YAML
        try:
            with open("knowledge/questions/java_core.yaml", "r") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            try:
                with open("backend/knowledge/questions/java_core.yaml", "r") as f:
                    data = yaml.safe_load(f)
            except Exception as e2:
                print(f"Error reading YAML: {e2}")
                return

        topics_cache = {}

        cat = await session.scalar(select(QuestionCategory).where(QuestionCategory.slug == "java-core", QuestionCategory.track_id == track.id))
        if not cat:
            cat = QuestionCategory(
                id=uuid.uuid4(),
                track_id=track.id,
                name="Java Core",
                slug="java-core",
                order_index=0,
                is_active=True,
            )
            session.add(cat)
            await session.flush()
        else:
            cat.is_active = True

        for q_data in data.get("questions", []):
            topic_name = q_data["topic"]
            if topic_name not in topics_cache:
                top = await session.scalar(select(Topic).where(Topic.slug == topic_name.lower().replace(" ", "-"), Topic.category_id == cat.id))
                if not top:
                    top = Topic(
                        id=uuid.uuid4(),
                        category_id=cat.id,
                        name=topic_name.replace("-", " ").title(),
                        slug=topic_name.lower().replace(" ", "-"),
                        order_index=len(topics_cache)
                    )
                    session.add(top)
                    await session.flush()
                topics_cache[topic_name] = top

            top = topics_cache[topic_name]

            existing = await session.scalar(select(Question).where(Question.content == q_data["content"]))
            if not existing:
                q = Question(
                    id=uuid.uuid4(),
                    topic_id=top.id,
                    content=q_data["content"],
                    difficulty=QuestionDifficulty(q_data["difficulty"]),
                    question_type=QuestionType(q_data["type"]),
                    expected_keywords=q_data["expected_keywords"],
                    ideal_answer=q_data["ideal_answer"],
                )
                session.add(q)
                await session.flush()

                for f_data in q_data.get("follow_ups", []):
                    f = FollowUpQuestion(
                        id=uuid.uuid4(),
                        parent_question_id=q.id,
                        content=f_data["content"],
                        trigger_condition=f_data["trigger"],
                    )
                    session.add(f)

                await session.flush()
                print(f"Added question: {q_data['content'][:30]}...")

        await session.commit()
        print("Seed complete.")

if __name__ == "__main__":
    asyncio.run(seed_knowledge_base())
