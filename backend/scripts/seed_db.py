import asyncio
import re
import uuid

import yaml
from sqlalchemy import select

from app.db.session import AsyncSessionFactory
from app.models.company import Company, InterviewTrack, QuestionCategory
from app.models.question import FollowUpQuestion, Question, QuestionDifficulty, QuestionType, Topic


async def seed_companies_and_tracks(session):
    """
    Make every company in the catalogue actually interviewable.

    Driven by knowledge/companies/catalogue.yaml rather than a list hardcoded here.
    Those were two separate systems and they had already drifted: /prepare offered
    roadmaps for twelve recruiters while the interview screen only ever showed the
    two seeded by hand, so a candidate could plan for Infosys and then find no
    Infosys interview to sit. One source of truth removes the drift by construction
    — adding a company to the YAML now gives it a roadmap AND an interview.

    Each program in the catalogue becomes a track. Keyed by slug and upserted, so
    re-running is safe and renaming a program updates rather than duplicates.
    """
    from app.services.prep import load_catalogue  # noqa: PLC0415

    catalogue = load_catalogue()
    total_tracks = 0

    for entry in catalogue.companies:
        company = await session.scalar(select(Company).where(Company.slug == entry.slug))
        if not company:
            company = Company(
                id=uuid.uuid4(),
                name=entry.name,
                slug=entry.slug,
                description=entry.short or entry.name,
                is_active=True,
            )
            session.add(company)
            await session.flush()
        else:
            # Keep the name and description in step with the catalogue, and
            # re-activate anything previously switched off.
            company.name = entry.name
            company.description = entry.short or entry.name
            company.is_active = True

        for program in entry.programs:
            track_slug = _track_slug(entry.slug, program.name)
            track = await session.scalar(
                select(InterviewTrack).where(InterviewTrack.slug == track_slug)
            )
            if not track:
                track = InterviewTrack(
                    id=uuid.uuid4(),
                    company_id=company.id,
                    name=program.name,
                    slug=track_slug,
                    description=program.detail or f"{entry.name} {program.name} interview",
                    is_active=True,
                )
                session.add(track)
            else:
                track.company_id = company.id
                track.name = program.name
                track.description = program.detail or track.description
                track.is_active = True
            total_tracks += 1

        await session.flush()
        print(f"  {entry.name}: {len(entry.programs)} track(s)")

    print(f"  -> {len(catalogue.companies)} companies, {total_tracks} tracks")


#: Slugs the original hand-seeded tracks used. Mapped explicitly so the two
#: companies that existed before the catalogue keep their slugs — a session or
#: report already pointing at "java-fse" must not be orphaned by a rename.
_LEGACY_TRACK_SLUGS = {
    ("cognizant", "GenC"): "genc",
    ("cognizant", "GenC Next"): "genc-next",
    ("cognizant", "GenC Pro"): "genc-pro",
    ("cognizant", "Digital Nurture — Java FSE"): "java-fse",
    ("tcs", "Ninja"): "ninja",
    ("tcs", "Digital"): "digital",
}


def _track_slug(company_slug: str, program_name: str) -> str:
    """
    Stable slug for a company + program.

    Legacy slugs win, so existing sessions keep resolving. Everything else is
    namespaced by company, because program names collide across recruiters —
    "Analyst" belongs to both Capgemini and Deloitte, and an un-namespaced slug
    would silently hand one company's track to the other.
    """
    legacy = _LEGACY_TRACK_SLUGS.get((company_slug, program_name))
    if legacy:
        return legacy
    suffix = re.sub(r"[^a-z0-9]+", "-", program_name.lower()).strip("-")
    return f"{company_slug}-{suffix}"


async def seed_knowledge_base():
    """Seed the database with the core Cognizant Java FSE questions."""
    async with AsyncSessionFactory() as session:
        # Every company and track we support, so none of them are UI-only stubs.
        await seed_companies_and_tracks(session)

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
            with open("knowledge/questions/java_core.yaml") as f:
                data = yaml.safe_load(f)
        except Exception:
            try:
                with open("backend/knowledge/questions/java_core.yaml") as f:
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
