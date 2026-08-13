"""
Where a roadmap's study resources come from — services/prep/study_resources.py

THE PRINCIPLE: NEVER PAY A MODEL FOR SOMETHING YOU ALREADY OWN, OR FOR SOMETHING EVERY
OTHER USER WILL ALSO NEED.

Study resources for a topic are the clearest case of both. "What should I read to learn
Spring Security" has one right answer, it does not depend on who is asking, and it does not
change between reports. The report generator was nonetheless producing it fresh in every
single report — on the most expensive call in the product, which is output-bound and already
hitting its token cap.

Three tiers, cheapest first. The ordering IS the cost strategy:

  1. CURATED — `knowledge/companies/resources.yaml`, human-verified with a `verified:` date.
     Costs nothing, ever, and cannot hallucinate. Covers the topics this product is actually
     about, which is most of them.

  2. SHARED CACHE — a pgvector entry keyed by topic name, in the same store as the interview
     plan and GD topic caches. The FIRST candidate weak in an uncovered topic pays for one
     small generation; every candidate after that, forever, pays nothing.

  3. GENERATE — only on a miss at both tiers, and deliberately small: three resources, no
     prose. It writes straight back to tier 2, so a given topic is generated at most once
     across the entire user base.

## Why this makes the product cheaper as it grows, rather than more expensive

Per-candidate generations — the report's judgement, a cross-question, a GD turn — cost the
same on user one and user ten thousand. Nothing about scale improves them, so the AI bill
rises exactly in step with usage and the margin never moves.

A shared cache behaves the opposite way. Its key space is the TOPIC SET, which is bounded by
the syllabus rather than by the number of users, so it saturates. Once every topic anyone is
weak in has been generated once, the marginal cost of this feature for every future user is
zero. Cost per user therefore FALLS as the user base grows, which is the property that makes
a lower price sustainable later rather than only affordable now.

That is also why tier 2 is keyed on the topic alone and never on the candidate or the
session. A key that includes anything per-user cannot saturate, and a cache that cannot
saturate is just a slower way to pay full price.

## The tenancy rule still applies, and it is satisfied here

vector_cache.py refuses to globally cache anything derived from a candidate's own answers.
A topic NAME is not that: it is a syllabus label from the question bank, the same string for
everybody, and nothing about the candidate reaches the prompt or the key. This is exactly
the shape the allowlist exists to permit.
"""

from __future__ import annotations

import structlog

from app.db.session import AsyncSession
from app.services.ai import vector_cache
from app.services.prep.catalogue import resources_for

logger = structlog.get_logger(__name__)

#: The cache feature name. Must also be in vector_cache.CACHEABLE_FEATURES, which is checked
#: at runtime rather than trusted to review.
FEATURE = "study_resources"

#: How many resources a roadmap item carries. Three is what the curated library gives and
#: what the UI lays out; more is a link dump rather than a plan, and a candidate with six
#: weeks cannot work through ten books.
_MAX_RESOURCES = 3


def _from_curated(topic: str) -> list[dict]:
    """
    Tier 1. The verified library, mapped into the report's resource shape.

    Returns [] when the topic is not covered, which is the signal to try tier 2 — the
    library's own lookup already logs the miss so an uncovered topic gets noticed and filled
    in by hand, which is always better than generating one.
    """
    found = resources_for(topic)
    if not found:
        return []
    return [
        {
            # The report schema calls this `type` and the library calls it `kind`. Mapped
            # here rather than renamed in either, because the library's field is also read
            # by the /prepare roadmap and the report's is already stored in old reports.
            "type": r.kind,
            "title": r.title,
            "url": r.url,
            "author": r.author,
        }
        for r in found[:_MAX_RESOURCES]
    ]


async def _from_cache(db: AsyncSession, topic: str) -> list[dict] | None:
    """Tier 2. What some earlier candidate's report already paid to generate."""
    try:
        hit = await vector_cache.lookup(db, feature=FEATURE, key=topic)
    except Exception:
        # A cache that is down must never take the report with it. Falling through to a
        # generation costs money; raising costs the candidate their report.
        logger.warning("study_resources_cache_lookup_failed", topic=topic, exc_info=True)
        return None
    if not hit:
        return None
    items = hit.get("resources") if isinstance(hit, dict) else None
    return items if isinstance(items, list) and items else None


async def _generate(db: AsyncSession, topic: str) -> list[dict]:
    """
    Tier 3. Generate once, for everybody.

    Deliberately tiny — three resources and no prose — because this is the fallback for
    topics the curated library does not cover, and the honest fix for those is to add them
    to the YAML rather than to lean on this.

    Returns [] on any failure. A roadmap item with no resources is a smaller problem than a
    report that failed to generate, and the item still carries the topic, the score gap and
    the study-hours estimate, which is most of its value.
    """
    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier, ProviderMessage  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.schemas import StudyResourceList  # noqa: PLC0415

    messages = [
        ProviderMessage(
            role="system",
            content=(
                "You recommend study resources for software-engineering interview topics, "
                "for Indian campus placement candidates.\n\n"
                "Rules:\n"
                "- Only resources that genuinely exist. A dead or invented link wastes a "
                "candidate's evening; if you are not certain a URL is real, omit the url "
                "field and give the title alone.\n"
                "- Prefer official documentation and widely used free practice sites.\n"
                "- Exactly three, ordered by what to do first.\n"
                "- No prose, no explanation outside the JSON."
            ),
        ),
        ProviderMessage(role="user", content=f"Study resources for the topic: {topic}"),
    ]

    try:
        result, _ = await generate_structured(
            StudyResourceList,
            messages,
            # Small on purpose: three short objects. This is the cheapest generation in the
            # product and it happens at most once per topic across all users.
            max_tokens=400,
            attempts_per_provider=1,
            cost_tier=CostTier.CHEAP,
            context=FEATURE,
        )
    except (AIProviderUnavailableError, TimeoutError, ValueError):
        logger.warning("study_resources_generation_failed", topic=topic)
        return []

    items = [
        {"type": r.type, "title": r.title, "url": r.url, "author": r.author}
        for r in result.resources[:_MAX_RESOURCES]
    ]
    if not items:
        return []

    try:
        await vector_cache.store(db, feature=FEATURE, key=topic, payload={"resources": items})
    except Exception:
        # Storing is an optimisation for the NEXT candidate. Failing to store must not lose
        # the resources for this one.
        logger.warning("study_resources_cache_store_failed", topic=topic, exc_info=True)

    return items


async def resolve(db: AsyncSession, topic: str) -> list[dict]:
    """
    Resources for one topic, from the cheapest tier that has them.

    Never raises. Every tier degrades to the next and the last degrades to [].
    """
    curated = _from_curated(topic)
    if curated:
        return curated

    cached = await _from_cache(db, topic)
    if cached:
        return cached

    return await _generate(db, topic)


async def attach_to_roadmap(db: AsyncSession, roadmap: list[dict]) -> list[dict]:
    """
    Fill in `resources` on every roadmap item, in place of whatever the report generator
    said.

    The generator is instructed not to produce them at all; this overwrites regardless,
    because a prompt instruction is a request and this is the guarantee. A model that
    ignores the instruction on one report in fifty must not be able to put an invented URL
    in front of a candidate.

    A roadmap is three items, so the tiers run in sequence rather than concurrently — with
    curated hits being pure function calls, parallelism would add machinery for microseconds.
    """
    for item in roadmap:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            item["resources"] = []
            continue
        item["resources"] = await resolve(db, topic)
    return roadmap
