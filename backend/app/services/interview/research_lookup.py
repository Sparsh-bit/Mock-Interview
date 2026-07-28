"""
Company research lookup — services/interview/research_lookup.py

Fetches cached interview intelligence for a (company, program) pair and renders
it for the interview-plan prompt, so plans are grounded in what the company
actually asks instead of the model's general priors.

This replaces a live web search per interview. The research is gathered once,
reviewed, and stored (see scripts/seed_research.py), which makes grounding
effectively free at interview time — a search per session would be billed every
time for information that changes a few times a year.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research import CompanyResearch

logger = structlog.get_logger(__name__)

#: Cap how many cached questions go into the prompt. The whole point is to
#: ground the model, not to hand it a list to copy verbatim — and prompt input
#: is billed, so this stays modest.
_MAX_PROMPT_QUESTIONS = 18


def slugify(value: str) -> str:
    """
    Normalise a free-text company/program into a lookup key.

    Candidates type "GenC Next", "genc-next" and "Gen C Next" for the same
    thing, so punctuation and spacing must not decide whether research is found.
    """
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


#: Common ways candidates refer to a program, mapped onto our slugs. Without
#: this, "Gen C Next" and "NQT" silently miss their research rows.
_PROGRAM_ALIASES: dict[str, str] = {
    "genc": "genc",
    "gen-c": "genc",
    "genc-elevate": "genc",
    "genc-pro": "genc",
    "genc-next": "genc-next",
    "gen-c-next": "genc-next",
    "gencnext": "genc-next",
    "ninja": "ninja",
    "nqt": "ninja",
    "tcs-nqt": "ninja",
    "digital": "digital",
    "tcs-digital": "digital",
}


async def find_research(
    db: AsyncSession, company: str, program: str
) -> CompanyResearch | None:
    """
    Look up research for this company, preferring an exact program match and
    falling back to the company's program-agnostic row, then to any row for the
    company. Returns None when we have nothing cached — callers must treat
    research as optional enrichment, never a requirement.
    """
    company_slug = slugify(company)
    if not company_slug:
        return None

    program_slug = _PROGRAM_ALIASES.get(slugify(program), slugify(program))

    rows = (
        await db.scalars(
            select(CompanyResearch).where(CompanyResearch.company_slug == company_slug)
        )
    ).all()
    if not rows:
        return None

    by_program = {r.program_slug: r for r in rows}
    chosen = by_program.get(program_slug) or by_program.get("") or rows[0]
    logger.info(
        "interview_research_hit",
        company=company_slug,
        requested_program=program_slug,
        matched_program=chosen.program_slug or "(any)",
        questions=len(chosen.previous_questions or []),
    )
    return chosen


def render_research(research: CompanyResearch | None) -> str:
    """
    Render research as the `$research` block for the interview-plan prompt.

    Returns a clear "nothing cached" marker rather than an empty string, so the
    prompt never contains a dangling heading with nothing under it.
    """
    if research is None:
        return (
            "(No cached research for this company. Build a solid, standard "
            "interview for the role and program instead.)"
        )

    lines: list[str] = [
        f"Company: {research.company_name}"
        + (f" — {research.program_name}" if research.program_name else "")
    ]

    if research.rounds:
        lines.append("\nReal interview rounds:")
        for r in research.rounds:
            mins = r.get("duration_minutes")
            head = f"- {r.get('name', 'Round')}"
            if mins:
                head += f" (~{mins} min)"
            lines.append(head)
            if r.get("description"):
                lines.append(f"  {' '.join(str(r['description']).split())}")

    if research.focus_topics:
        lines.append("\nTopics this company emphasises, most first:")
        lines.append("  " + ", ".join(research.focus_topics))

    questions = (research.previous_questions or [])[:_MAX_PROMPT_QUESTIONS]
    if questions:
        lines.append("\nQuestions actually asked in past interviews:")
        for q in questions:
            meta = " · ".join(
                str(x) for x in (q.get("topic"), q.get("difficulty"), q.get("kind")) if x
            )
            lines.append(f"- {q.get('question')}" + (f"  [{meta}]" if meta else ""))

    if research.tips:
        lines.append("\nWhat candidates report about this interview:")
        for t in research.tips:
            lines.append(f"- {t}")

    return "\n".join(lines)
