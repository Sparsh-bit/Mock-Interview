"""
Resume analysis — services/resume/analyser.py

Runs the resume-analyzer prompts over extracted resume text and returns a
validated ResumeAnalysisResponse.

Kept separate from the upload endpoint so the analysis can be re-run without
re-uploading the file (a provider outage at upload time must not permanently cost
the candidate their personalised interview).

── WHY THIS IS TWO CALLS AND NOT ONE ────────────────────────────────────────────

REPORTED AS "in some cases the resume skills and projects are not been able to
fetch". It was one AI call asking for skills, projects, experience, interview focus
and a quality score as a single JSON object under a 2600-token ceiling, and the
measurement said that object does not fit. Three runs over a realistic two-page
resume (27 skills, 4 projects) against the live providers:

    run 1  118.7s  27 skills,  1 project,  0 priority topics
    run 2  214.5s  AIProviderUnavailableError — nothing at all
    run 3  135.9s  21 skills,  0 projects,  0 priority topics

EVERY attempt of every run came back `stop_reason=max_tokens` /
`finish_reason=length`. Skills are emitted first, so the truncation always landed
in the middle of `projects` — which is exactly the reported symptom, and why it hit
"some" resumes: a thin resume fits under the ceiling and works, a rich one cannot
fit and never works. A truncated body then failed JSON extraction outright, so
`generate_structured` retried it — twice per provider, across two providers, four
billed calls at ~$0.045 each, all truncated the same way, ~$0.18 of waste per
upload. And since the endpoint capped the whole thing at 45 seconds, in production
none of it was ever waited out: the candidate waited 45s and got text_only.

THREE THINGS WERE WRONG AND ALL THREE ARE FIXED HERE.

  1. ONE OVERSIZED ANSWER. Split into two halves that are requested CONCURRENTLY,
     each with its own generous ceiling. Latency on these calls is output-token
     bound, so the wall-clock becomes the larger half instead of the sum, and
     neither half comes close to truncating. Measured after: ~10s for both halves
     together, against a 45s timeout that used to expire with nothing to show.

  2. NO VALIDITY CHECK. Every field of ResumeAnalysisResponse has a default, so
     `{}` validated cleanly and was stored as a successful analysis — first
     attempt, no retry, no fallback provider, `parsing_status="completed"`, and a
     UI that said "Read and analysed" over zero skills and zero projects. This was
     the ONLY `generate_structured` call site in the application without an
     `is_valid` predicate. Both halves have one now, so an empty or misdirected
     answer is a retry rather than a result.

  3. ALL-OR-NOTHING. One failure erased the whole analysis. The halves are
     isolated: `asyncio.wait` (never `wait_for(gather(...))`, which would cancel a
     half that had already succeeded) keeps whatever finished inside the budget,
     and the caller is told which half is missing so it can say so honestly
     instead of reporting a complete analysis.

Fields nothing reads are no longer requested either — see the notes on ResumeSkill
and ResumeQuality in services/ai/schemas.py. Unread output is paid for twice, in
money and in the candidate's waiting time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from app.core.config import settings
from app.services.ai.base_provider import CostTier
from app.services.ai.schemas import (
    ResumeAnalysisResponse,
    ResumeProjectsHalf,
    ResumeSkillsHalf,
)

logger = structlog.get_logger(__name__)

#: Caps on what the analyser is asked to return. These are prompt inputs, not
#: post-hoc truncation: asking for fewer items directly reduces output tokens,
#: which is where the cost is (output bills ~5x input).
MAX_SKILLS = 20
MAX_PROJECTS = 6

#: Output ceilings, per half.
#:
#: MEASURED, not guessed, because the previous number was guessed and was wrong in
#: the one direction that matters. Its comment claimed "20 skills + 6 projects +
#: focus + quality lands around 1.6k tokens"; the real answer overran 2600 on every
#: attempt of every run. An undersized ceiling does not truncate gracefully — the
#: JSON is cut mid-array and the entire billed call is unusable.
#:
#: A skill object is now two keys (~14 tokens), so 20 of them plus the experience
#: block is ~380 tokens: 1200 is over 3x headroom. The projects half is the bigger
#: one — six projects at ~110 tokens plus the focus block is ~880 — so 2000 gives it
#: more than 2x. Both are ceilings on a runaway response, not budgets to spend.
_SKILLS_MAX_TOKENS = 1200
_PROJECTS_MAX_TOKENS = 2000

#: Resume analysis happens once per upload and shapes every subsequent interview,
#: so it is worth more than the cheapest tier — but the rubric is fully specified
#: in the prompt, so it does not need reasoning either.
_ANALYSIS_COST_TIER = CostTier.BALANCED


@dataclass(frozen=True)
class ResumeAnalysisOutcome:
    """
    What came back from the two halves, and what did not.

    The caller needs the distinction. "Skills but no projects" and "a complete
    analysis" are different things to tell a candidate, and collapsing them is how
    an upload came to report "Read and analysed" over an empty analysis. `analysis`
    is None only when BOTH halves failed.
    """

    analysis: ResumeAnalysisResponse | None
    skills_ok: bool
    projects_ok: bool

    @property
    def complete(self) -> bool:
        """True only when both halves returned something usable."""
        return self.skills_ok and self.projects_ok

    def candidate_message(self) -> str | None:
        """
        What to tell the candidate, or None when the analysis is complete.

        Written for them and shown verbatim, so it names what is missing and what
        still works — the resume text is stored either way and interviews use it.
        """
        if self.complete:
            return None
        if self.skills_ok:
            return (
                "Your resume was read and your skills were picked up, but the project "
                "breakdown could not be built this time. Interviews will still use your "
                "resume — re-upload it if you want the project questions."
            )
        if self.projects_ok:
            return (
                "Your resume was read and your projects were picked up, but the skill "
                "list could not be built this time. Interviews will still use your resume."
            )
        return (
            "Your resume was read successfully, but the detailed skill analysis could "
            "not be completed. Interviews will still be based on your resume text."
        )


async def analyse_resume(
    resume_text: str,
    *,
    track_name: str = "General",
    company_name: str = "General",
) -> ResumeAnalysisOutcome:
    """
    Analyse resume text into skills, projects, experience and interview focus.

    Never raises for an AI failure. Each half is isolated and the whole fan-out is
    bounded by RESUME_ANALYSIS_BUDGET_SECONDS, so the caller always gets an outcome
    it can store: a complete analysis, one half of one, or nothing. An unanalysed
    resume still has its text stored, so the interviewer can read it directly.
    """
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415

    builder = PromptBuilder(get_prompt_loader())

    async def _skills_half() -> ResumeSkillsHalf:
        messages = builder.chat(
            system_template="resume_analyzer_skills",
            user_content=resume_text,
            track_name=track_name,
            company_name=company_name,
            max_skills=str(MAX_SKILLS),
        )
        half, _raw = await generate_structured(
            ResumeSkillsHalf,
            messages,
            max_tokens=_SKILLS_MAX_TOKENS,
            cost_tier=_ANALYSIS_COST_TIER,
            # THE CHECK THAT WAS MISSING. A resume with no readable skill is not a
            # thing that exists — extract_text already rejected files with no text —
            # so an empty list means the model answered the wrong question, refused,
            # or was cut off. Retrying is right; storing it as an analysis is not.
            is_valid=lambda h: len(h.skills) > 0,
            context="resume_analysis_skills",
        )
        return half

    async def _projects_half() -> ResumeProjectsHalf:
        messages = builder.chat(
            system_template="resume_analyzer_projects",
            user_content=resume_text,
            track_name=track_name,
            company_name=company_name,
            max_projects=str(MAX_PROJECTS),
        )
        half, _raw = await generate_structured(
            ResumeProjectsHalf,
            messages,
            max_tokens=_PROJECTS_MAX_TOKENS,
            cost_tier=_ANALYSIS_COST_TIER,
            # NOT keyed on `projects`. A fresher's resume can honestly have none,
            # and rejecting that would burn four billed retries to arrive back at
            # the same true answer. priority_topics is the field that actually
            # steers the interview and the prompt says never to return it empty, so
            # that is the one worth retrying for.
            is_valid=lambda h: len(h.interview_focus.priority_topics) > 0,
            context="resume_analysis_projects",
        )
        return half

    skills_task = asyncio.create_task(_skills_half())
    projects_task = asyncio.create_task(_projects_half())

    # ── BOUNDED, AND PARTIAL RESULTS SURVIVE ────────────────────────────────────
    #
    # `generate_structured` has no deadline of its own: it loops every provider
    # twice, and the fallback provider's read timeout is 180 seconds. Unbounded,
    # this call measured 118s to 214s — the browser gives up at 120s for the upload
    # and a managed host's gateway cuts at ~100s, so nobody was ever going to
    # receive the answer it was still working on.
    #
    # `asyncio.wait` RATHER THAN `wait_for(gather(...))`, deliberately: a wait_for
    # around a gather cancels every task when the deadline hits, so a slow projects
    # half would throw away the skills half that already succeeded. That is the
    # all-or-nothing behaviour this rewrite exists to remove.
    done, pending = await asyncio.wait(
        {skills_task, projects_task},
        timeout=settings.RESUME_ANALYSIS_BUDGET_SECONDS or None,
    )
    for task in pending:
        task.cancel()

    def _result(task: asyncio.Task, half: str):  # noqa: ANN202 - the two half types differ
        """Whatever the task produced, or None — never an exception out of here."""
        if task not in done:
            logger.warning("resume_analysis_half_timed_out", half=half)
            return None
        try:
            return task.result()
        except Exception as exc:
            # BROAD ON PURPOSE, BUT NEVER SILENT. Anything a half can raise —
            # AIProviderUnavailableError, a validation failure, a schema surprise —
            # has the same correct response: keep the other half. Letting an
            # unanticipated one escape would turn a recoverable partial analysis
            # into a failed upload, which is worse than what was reported.
            # CancelledError is a BaseException, so the halves cancelled above are
            # reported by the `not in done` branch rather than as failures.
            logger.warning(
                "resume_analysis_half_failed",
                half=half,
                error_type=type(exc).__name__,
                error=str(exc) or type(exc).__name__,
            )
            return None

    skills = _result(skills_task, "skills")
    projects = _result(projects_task, "projects")

    if skills is None and projects is None:
        logger.warning("resume_analysis_failed_both_halves")
        return ResumeAnalysisOutcome(analysis=None, skills_ok=False, projects_ok=False)

    analysis = ResumeAnalysisResponse(
        skills=list(skills.skills) if skills else [],
        experience=skills.experience if skills else ResumeAnalysisResponse().experience,
        projects=list(projects.projects) if projects else [],
        interview_focus=(
            projects.interview_focus if projects else ResumeAnalysisResponse().interview_focus
        ),
    )

    logger.info(
        "resume_analysed",
        skills=len(analysis.skills),
        projects=len(analysis.projects),
        priority_topics=len(analysis.interview_focus.priority_topics),
        seniority=analysis.experience.seniority_level,
        skills_ok=skills is not None,
        projects_ok=projects is not None,
    )
    return ResumeAnalysisOutcome(
        analysis=analysis,
        skills_ok=skills is not None,
        projects_ok=projects is not None,
    )


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
