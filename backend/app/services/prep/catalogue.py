"""
Campus recruiter catalogue — services/prep/catalogue.py

Loads knowledge/companies/catalogue.yaml and turns a company's topic weights into
a dated study roadmap.

Served straight from YAML rather than seeded into Postgres, unlike the research
data. This is read-only reference material with no user state attached, so a table
would add a migration, a seed script and a way for the database to disagree with
the file — for nothing. The file IS the source of truth, and it cannot drift from
itself.

Parsed once at import and cached: it is a few kilobytes and never changes at
runtime, so re-reading per request would be pure waste.
"""

from __future__ import annotations

import datetime as dt
import math
import pathlib
from functools import lru_cache

import structlog
import yaml
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

_KNOWLEDGE_DIR = (
    pathlib.Path(__file__).resolve().parents[2].parent / "knowledge" / "companies"
)

#: Topic weights must sum to this. Enforced at load so a typo surfaces at startup
#: rather than as a quietly mis-weighted roadmap months later.
_WEIGHT_TOTAL = 100
#: Rounding slack — a set summing to 99 or 101 is a typo worth failing on, but
#: floats from YAML can be a hair off.
_WEIGHT_TOLERANCE = 0.51


class Topic(BaseModel):
    name: str
    #: Share of the technical assessment, as a percentage.
    weight: float = Field(ge=0, le=100)


class Program(BaseModel):
    name: str
    detail: str = ""


class Company(BaseModel):
    slug: str
    name: str
    short: str = ""
    #: "mass_recruiter" | "consulting" | "product" — drives grouping in the UI and
    #: sets expectations, since the bar differs enormously between them.
    tier: str = "mass_recruiter"
    hires_per_year: str = ""
    drive_window: str = ""
    eligibility: str = ""
    accent: str = "#008ae6"
    programs: list[Program] = Field(default_factory=list)
    rounds: list[str] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)


class Catalogue(BaseModel):
    #: When a human last checked these entries against a first-party source.
    verified: dt.date
    companies: list[Company]


class Resource(BaseModel):
    title: str
    #: Absent for exercises ("write five small programs"), which are instructions
    #: rather than links. The UI must handle a resource with no URL.
    url: str | None = None
    author: str | None = None
    #: practice | reference | docs | book | course | exercise
    kind: str = "reference"
    #: free | freemium | paid — stated plainly so nobody clicks into a paywall.
    cost: str = "free"
    note: str = ""


class ResourceLibrary(BaseModel):
    verified: dt.date
    topics: dict[str, ResourceTopic]


class ResourceTopic(BaseModel):
    aliases: list[str] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)


class RoadmapTopic(BaseModel):
    name: str
    weight: float
    hours: int
    #: 1-based phase this topic falls in.
    phase: int
    resources: list[Resource] = Field(default_factory=list)


class RoadmapPhase(BaseModel):
    phase: int
    title: str
    starts_on: dt.date
    ends_on: dt.date
    topics: list[RoadmapTopic]
    hours: int


class Roadmap(BaseModel):
    company_slug: str
    company_name: str
    weeks: int
    hours_per_week: int
    total_hours: int
    target_date: dt.date
    phases: list[RoadmapPhase]
    #: Topics the budget could not fund at all, heaviest-first order preserved.
    #: Non-empty means the plan is a triage, not full coverage.
    omitted_topics: list[str] = Field(default_factory=list)
    #: Plain warning when the time available cannot cover the syllabus. Null when
    #: the plan is genuinely complete.
    feasibility_warning: str | None = None
    #: Restates that eligibility is indicative, so the UI cannot forget to.
    disclaimer: str


@lru_cache(maxsize=1)
def load_catalogue() -> Catalogue:
    """
    Read and validate the catalogue.

    Raises at import/startup on a malformed file rather than returning a partial
    catalogue — a company silently missing its topics would produce an empty
    roadmap that looks like a working feature.
    """
    raw = yaml.safe_load((_KNOWLEDGE_DIR / "catalogue.yaml").read_text())
    catalogue = Catalogue.model_validate(raw)

    for company in catalogue.companies:
        total = sum(t.weight for t in company.topics)
        if abs(total - _WEIGHT_TOTAL) > _WEIGHT_TOLERANCE:
            raise ValueError(
                f"{company.slug}: topic weights sum to {total}, expected "
                f"{_WEIGHT_TOTAL}. An unbalanced set produces a roadmap that "
                "under-weights something important."
            )

    logger.info(
        "company_catalogue_loaded",
        companies=len(catalogue.companies),
        verified=str(catalogue.verified),
    )
    return catalogue


@lru_cache(maxsize=1)
def load_resources() -> ResourceLibrary:
    """Read the topic -> resources library."""
    raw = yaml.safe_load((_KNOWLEDGE_DIR / "resources.yaml").read_text())
    library = ResourceLibrary.model_validate(raw)
    logger.info("resource_library_loaded", topics=len(library.topics))
    return library


def _normalise(name: str) -> str:
    """Lowercase and strip punctuation so near-miss topic names still match."""
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch.isspace()).strip()


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    """
    Normalised alias -> topic key.

    Built once. Catalogue topic names vary slightly between companies ("Data
    Structures" vs "Data Structures & Algorithms"), and a lookup that missed would
    silently show a topic with nothing to study — which looks like the feature is
    broken rather than like data is missing.
    """
    index: dict[str, str] = {}
    for key, topic in load_resources().topics.items():
        index[_normalise(key.replace("_", " "))] = key
        for alias in topic.aliases:
            index[_normalise(alias)] = key
    return index


def resources_for(topic_name: str) -> list[Resource]:
    """Resources for a catalogue topic name, or [] if we have none for it."""
    key = _alias_index().get(_normalise(topic_name))
    if key is None:
        # Logged rather than raised: a new topic with no resources yet should
        # degrade to an empty list, not break the whole roadmap. The log is how it
        # gets noticed and filled in.
        logger.info("no_resources_for_topic", topic=topic_name)
        return []
    return load_resources().topics[key].resources


def get_company(slug: str) -> Company | None:
    return next((c for c in load_catalogue().companies if c.slug == slug), None)


def build_roadmap(
    company: Company,
    *,
    weeks: int = 8,
    hours_per_week: int = 10,
    start: dt.date | None = None,
) -> Roadmap:
    """
    Turn a company's topic weights into a dated, phased study plan.

    Derived rather than hand-written per company, so adding a recruiter to the
    catalogue needs only its topics and weights — twelve hand-maintained roadmaps
    would be twelve things to keep in sync.

    How it allocates:

      * Hours are split across topics in proportion to their weight, so what the
        assessment actually tests is what gets the time.
      * Topics are ordered heaviest-first and dealt into phases in that order, so
        the highest-leverage material is covered while motivation is highest and
        there is still time to go back over it.
      * Every topic gets at least one hour. A topic worth 5% of the paper is still
        worth an evening, and rounding it to zero would drop it off the plan
        entirely.
    """
    start = start or dt.date.today()
    weeks = max(1, min(weeks, 52))
    hours_per_week = max(1, min(hours_per_week, 60))
    total_hours = weeks * hours_per_week

    ordered = sorted(company.topics, key=lambda t: t.weight, reverse=True)

    # Three phases reads as a plan; more becomes a wall of dates nobody follows.
    phase_count = min(3, max(1, len(ordered)))
    per_phase = math.ceil(len(ordered) / phase_count)

    # ── Honest allocation ───────────────────────────────────────────────────
    #
    # Every topic used to get max(1, ...) hours, which quietly INVENTED time: at
    # 1 week x 1 hour the budget is 1 hour, but seven topics each floored to 1
    # produced a "7 hour" plan. The page then told someone with one hour that
    # they had a full study plan, which is worse than telling them nothing.
    #
    # So the floor is still one hour per topic — half an hour on a topic is not a
    # real study session — but it is funded from the actual budget, and when the
    # budget runs out the remaining topics are reported as OMITTED rather than
    # conjured into the plan.
    fundable = min(len(ordered), total_hours)
    covered = ordered[:fundable]
    omitted = ordered[fundable:]

    allocations: list[RoadmapTopic] = []
    if covered:
        # Re-normalise over the topics we can actually fund, so their weights still
        # sum to 100 among themselves and the split stays proportional.
        covered_weight = sum(t.weight for t in covered) or 1
        spent = 0
        for index, topic in enumerate(covered):
            phase = index // per_phase + 1
            is_last = index == len(covered) - 1
            # The last topic absorbs the rounding remainder so the plan's total is
            # exactly the budget rather than a hair above it.
            hours = (
                total_hours - spent
                if is_last
                else max(1, round(total_hours * topic.weight / covered_weight))
            )
            hours = max(1, min(hours, total_hours - spent - (len(covered) - index - 1)))
            spent += hours
            allocations.append(
                RoadmapTopic(
                    name=topic.name,
                    weight=topic.weight,
                    hours=hours,
                    phase=phase,
                    resources=resources_for(topic.name),
                )
            )

    warning: str | None = None
    if omitted:
        need = len(ordered)
        warning = (
            f"{total_hours} hours only covers {len(covered)} of {need} topics. "
            f"To touch every topic you need at least {need} hours, and realistically "
            f"{need * 8}. Everything below is ordered by what costs you the most marks "
            "if you skip it."
        )

    titles = {
        1: "Foundations — the heaviest-weighted material first",
        2: "Depth — the topics that separate offers",
        3: "Polish — round out and rehearse",
    }

    weeks_per_phase = max(1, weeks // phase_count)
    phases: list[RoadmapPhase] = []
    for phase_no in range(1, phase_count + 1):
        topics = [a for a in allocations if a.phase == phase_no]
        if not topics:
            continue
        phase_start = start + dt.timedelta(weeks=weeks_per_phase * (phase_no - 1))
        # The last phase absorbs any remainder so the plan always ends on the
        # target date rather than a few days short of it.
        phase_end = (
            start + dt.timedelta(weeks=weeks) - dt.timedelta(days=1)
            if phase_no == phase_count
            else phase_start + dt.timedelta(weeks=weeks_per_phase) - dt.timedelta(days=1)
        )
        phases.append(
            RoadmapPhase(
                phase=phase_no,
                title=titles.get(phase_no, f"Phase {phase_no}"),
                starts_on=phase_start,
                ends_on=phase_end,
                topics=topics,
                hours=sum(t.hours for t in topics),
            )
        )

    return Roadmap(
        company_slug=company.slug,
        company_name=company.name,
        weeks=weeks,
        hours_per_week=hours_per_week,
        total_hours=sum(a.hours for a in allocations),
        target_date=start + dt.timedelta(weeks=weeks),
        phases=phases,
        omitted_topics=[t.name for t in omitted],
        feasibility_warning=warning,
        disclaimer=(
            "Eligibility and drive windows are indicative and change every year. "
            "Always confirm against the company's official notification for your batch."
        ),
    )
