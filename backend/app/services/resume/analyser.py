"""
Resume analysis — services/resume/analyser.py

Runs the `resume_analyzer` prompt over extracted resume text and returns a
validated ResumeAnalysisResponse.

Kept separate from the upload endpoint so the analysis can be re-run without
re-uploading the file (a provider outage at upload time must not permanently cost
the candidate their personalised interview).
"""

from __future__ import annotations

import structlog

from app.services.ai.base_provider import CostTier
from app.services.ai.schemas import ResumeAnalysisResponse

logger = structlog.get_logger(__name__)

#: Caps on what the analyser is asked to return. These are prompt inputs, not
#: post-hoc truncation: asking for fewer items directly reduces output tokens,
#: which is where the cost is (output bills ~5x input).
MAX_SKILLS = 20
MAX_PROJECTS = 6

#: Output budget. Measured shape: 20 skills + 6 projects + focus + quality lands
#: around 1.6k tokens, so this leaves real headroom. Sized deliberately rather
#: than guessed — an undersized ceiling truncates the JSON and the whole call is
#: wasted, which is exactly how report generation was silently failing.
_ANALYSIS_MAX_TOKENS = 2600

#: Resume analysis happens once per upload and shapes every subsequent interview,
#: so it is worth more than the cheapest tier — but the rubric is fully specified
#: in the prompt, so it does not need reasoning either.
_ANALYSIS_COST_TIER = CostTier.BALANCED


async def analyse_resume(
    resume_text: str,
    *,
    track_name: str = "General",
    company_name: str = "General",
) -> ResumeAnalysisResponse:
    """
    Analyse resume text into skills, projects, experience and interview focus.

    Raises whatever the AI layer raises (AIProviderUnavailableError,
    AIValidationError) -- the caller decides whether that is fatal. It is not:
    an unanalysed resume still has its text stored, so the interviewer can read
    it directly even when the structured analysis is missing.
    """
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="resume_analyzer",
        user_content=resume_text,
        track_name=track_name,
        company_name=company_name,
        max_skills=str(MAX_SKILLS),
        max_projects=str(MAX_PROJECTS),
    )

    analysis, _raw = await generate_structured(
        ResumeAnalysisResponse,
        messages,
        max_tokens=_ANALYSIS_MAX_TOKENS,
        cost_tier=_ANALYSIS_COST_TIER,
        context="resume_analysis",
    )

    logger.info(
        "resume_analysed",
        skills=len(analysis.skills),
        projects=len(analysis.projects),
        priority_topics=len(analysis.interview_focus.priority_topics),
        seniority=analysis.experience.seniority_level,
    )
    return analysis


def build_interview_context(
    analysis: ResumeAnalysisResponse | None,
    resume_text: str,
    *,
    max_chars: int = 2500,
) -> str:
    """
    Condense a resume into the block handed to the interviewer prompt.

    Prefers the structured analysis over raw text because it is *directed*: it
    names the specific projects to ask about by name, separates skills claimed
    explicitly from ones merely implied, and states which gaps to probe. That is
    what makes "you listed <project> — how did you handle X there?" possible
    instead of something generic.

    Note it is not necessarily shorter than the raw text — for a one-page resume
    it is often longer, since it adds structure the original lacked. The bound is
    max_chars, and the win is guidance, not token count.

    Falls back to trimmed raw text when analysis is unavailable, so an interview
    is still personalised even if the analyser failed.
    """
    if analysis is None:
        return resume_text[:max_chars].strip()

    lines: list[str] = []

    exp = analysis.experience
    if exp.primary_stack or exp.total_years:
        stack = ", ".join(exp.primary_stack[:8]) or "not stated"
        lines.append(
            f"Experience: {exp.seniority_level} level, ~{exp.total_years:g} year(s). "
            f"Primary stack: {stack}."
        )

    # Projects first and in full: they are the only place a resume contains
    # something concrete enough to build a real question from.
    if analysis.projects:
        lines.append("\nProjects the candidate claims (ask about these by name):")
        for project in analysis.projects:
            tech = ", ".join(project.technologies[:6])
            detail = project.description.strip()
            scale = "; ".join(project.scale_indicators[:2])
            parts = [f"- {project.name}"]
            if project.role:
                parts.append(f"({project.role})")
            if tech:
                parts.append(f"— tech: {tech}")
            if detail:
                parts.append(f"— {detail}")
            if scale:
                parts.append(f"— scale: {scale}")
            lines.append(" ".join(parts))

    # Explicit claims are fair game to probe hard; a passing mention is not.
    explicit = [s.name for s in analysis.skills if s.confidence == "explicit"]
    inferred = [s.name for s in analysis.skills if s.confidence != "explicit"]
    if explicit:
        lines.append(f"\nSkills claimed explicitly: {', '.join(explicit[:14])}")
    if inferred:
        lines.append(f"Skills only implied: {', '.join(inferred[:10])}")

    focus = analysis.interview_focus
    if focus.priority_topics:
        lines.append(f"\nPriority topics for this candidate: {', '.join(focus.priority_topics[:8])}")
    if focus.strong_areas:
        lines.append(f"Strong areas: {', '.join(focus.strong_areas[:6])}")
    if focus.weak_areas:
        lines.append(f"Likely gaps worth probing: {', '.join(focus.weak_areas[:6])}")
    if focus.personalization_notes:
        lines.append(f"\nNotes: {focus.personalization_notes}")

    context = "\n".join(lines).strip()
    return context[:max_chars]
