"""
One bad half must not cost the candidate the other — tests/test_resume_halves.py

REPORTED: "in some cases the resume skills and projects are not been able to fetch", and
separately "make sure that the resume uploading also works faster".

BOTH SYMPTOMS WERE ONE CAUSE. Resume analysis was a single `generate_structured` call that had
to return skills AND experience AND projects AND interview focus in one structured object.
That made it the largest structured output in the product, and since latency is
output-token-bound it measured 118s to 214s unbounded — past the browser's upload timeout and
past a managed host's gateway cut, so nobody received the answer the server was still working
on. It was also all-or-nothing: one malformed field anywhere in that object failed validation,
and a retry regenerated the whole thing, so a model that fumbled the projects list threw away
a perfectly good skill list four times over and the upload reported nothing.

It is now two concurrent halves, each bounded, each isolated. `analyse_resume` NEVER raises for
an AI failure — it returns a `ResumeAnalysisOutcome` saying which halves worked.

WHAT THESE TESTS PROTECT, and why they are worth having as source-independent behaviour tests
rather than as another source-text pin: the isolation is the entire fix, and it is invisible in
the happy path. Every test below is a partial failure, because a partial failure is the case
that used to lose a candidate's data and the case nobody exercises by hand.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.services.ai.schemas import (
    ResumeInterviewFocus,
    ResumeProject,
    ResumeProjectsHalf,
    ResumeSkill,
    ResumeSkillsHalf,
)
from app.services.resume import analyser as analyser_mod

pytestmark = pytest.mark.asyncio

RESUME = "Ansh Kumar. Skills: Java, Spring Boot. Project: CampusConnect, a Spring Boot app."


def _skills_half() -> ResumeSkillsHalf:
    return ResumeSkillsHalf(skills=[ResumeSkill(name="Java"), ResumeSkill(name="Spring Boot")])


def _projects_half() -> ResumeProjectsHalf:
    return ResumeProjectsHalf(
        projects=[ResumeProject(name="CampusConnect")],
        interview_focus=ResumeInterviewFocus(priority_topics=["Spring Boot"]),
    )


def _fake_generate(*, skills=None, projects=None):
    """
    Stand in for `generate_structured`, routing on the schema it was asked for.

    Each of `skills`/`projects` is either a value to return, or an exception instance to raise,
    or the string "hang" to never return — the three ways a half actually fails in production.
    """

    async def fake(schema, messages, **kwargs):
        want = skills if schema is ResumeSkillsHalf else projects
        if want == "hang":
            await asyncio.Event().wait()
        if isinstance(want, BaseException):
            raise want
        return want, ""

    return fake


@pytest.fixture(autouse=True)
def _fast_budget(monkeypatch):
    """A short budget, so the hang cases finish in test time rather than in real time."""
    monkeypatch.setattr(settings, "RESUME_ANALYSIS_BUDGET_SECONDS", 0.3)


async def _run(monkeypatch, **halves):
    import app.services.ai.generate as gen_mod

    monkeypatch.setattr(gen_mod, "generate_structured", _fake_generate(**halves))
    return await analyser_mod.analyse_resume(RESUME, track_name="Java FSE", company_name="Cog")


async def test_both_halves_succeeding_is_a_complete_analysis(monkeypatch):
    out = await _run(monkeypatch, skills=_skills_half(), projects=_projects_half())
    assert out.complete
    assert out.skills_ok and out.projects_ok
    assert [s.name for s in out.analysis.skills] == ["Java", "Spring Boot"]
    assert [p.name for p in out.analysis.projects] == ["CampusConnect"]
    # Nothing to tell them: a message on a complete analysis is noise that reads as a warning.
    assert out.candidate_message() is None


async def test_a_failed_projects_half_does_not_lose_the_skills(monkeypatch):
    """THE REPORTED BUG. Skills were fetched and then discarded because projects failed."""
    out = await _run(monkeypatch, skills=_skills_half(), projects=RuntimeError("bad json"))
    assert out.skills_ok is True
    assert out.projects_ok is False
    assert out.complete is False
    # The half that worked is fully present...
    assert [s.name for s in out.analysis.skills] == ["Java", "Spring Boot"]
    # ...and the half that did not is empty rather than absent, so the caller can store it.
    assert out.analysis.projects == []
    # The candidate is told precisely what is missing, not given a generic failure.
    message = out.candidate_message()
    assert message and "project" in message.lower()


async def test_a_failed_skills_half_does_not_lose_the_projects(monkeypatch):
    out = await _run(monkeypatch, skills=RuntimeError("bad json"), projects=_projects_half())
    assert out.projects_ok is True
    assert out.skills_ok is False
    assert [p.name for p in out.analysis.projects] == ["CampusConnect"]
    assert out.analysis.skills == []
    message = out.candidate_message()
    assert message and "skill" in message.lower()


async def test_a_hanging_half_is_bounded_and_the_other_half_still_lands(monkeypatch):
    """
    THE LATENCY FIX AND THE ISOLATION FIX ARE THE SAME TEST.

    A half that never answers is what produced the 118-214s measurements. It must now be
    abandoned at the budget, and — the part `wait_for(gather(...))` would have got wrong — the
    half that already succeeded must survive being abandoned's sibling.
    """
    started = asyncio.get_event_loop().time()
    out = await _run(monkeypatch, skills=_skills_half(), projects="hang")
    elapsed = asyncio.get_event_loop().time() - started

    assert elapsed < 3.0, f"the budget did not bound the fan-out ({elapsed:.2f}s)"
    assert out.skills_ok is True, "the successful half was discarded with the hung one"
    assert out.projects_ok is False
    assert [s.name for s in out.analysis.skills] == ["Java", "Spring Boot"]


async def test_both_halves_failing_reports_no_analysis_rather_than_an_empty_one(monkeypatch):
    """
    `analysis is None` ONLY when both halves failed, and that distinction is load-bearing.

    An empty-but-present analysis is what let an upload report "Read and analysed" over
    nothing at all. None means "we have no analysis", which the caller renders differently
    from "we have an analysis with no projects in it".
    """
    out = await _run(monkeypatch, skills=RuntimeError("x"), projects=RuntimeError("y"))
    assert out.analysis is None
    assert out.complete is False
    assert out.skills_ok is False and out.projects_ok is False
    assert out.candidate_message()


async def test_an_ai_failure_never_raises_out_of_the_analyser(monkeypatch):
    """
    The upload must survive any AI outcome. A raised exception here fails the whole upload and
    loses the resume TEXT too — which interviews can use even with no analysis at all.
    """
    from app.core.exceptions import AIProviderUnavailableError

    for boom in (
        AIProviderUnavailableError("down"),
        ValueError("schema surprise"),
        KeyError("missing"),
        TypeError("wrong shape"),
    ):
        out = await _run(monkeypatch, skills=boom, projects=boom)
        assert out.analysis is None
        assert out.complete is False


# ── What the candidate is TOLD happened ──────────────────────────────────────────────────
#
# The isolation above keeps the data. These keep the claim about it honest, which is the other
# half of the reported bug: the profile card read "Read and analysed — your interviews will ask
# about these projects and skills by name" over an upload with zero skills and zero projects,
# because the status was `"completed" if analysis else "text_only"` and an analysis object with
# nothing in it is still an object.


async def test_a_lost_half_is_reported_as_partial_not_completed(monkeypatch):
    """A resume with skills but no projects must not claim a full analysis."""
    out = await _run(monkeypatch, skills=_skills_half(), projects=RuntimeError("provider down"))
    assert out.parsing_status == "partial"
    assert out.complete is False
    # And the candidate is told which half is missing, in words they can act on.
    assert "project" in (out.candidate_message() or "").lower()


async def test_losing_both_halves_is_text_only(monkeypatch):
    out = await _run(
        monkeypatch, skills=RuntimeError("down"), projects=RuntimeError("down")
    )
    assert out.parsing_status == "text_only"
    assert out.analysis is None


async def test_both_halves_landing_is_the_only_completed(monkeypatch):
    out = await _run(monkeypatch, skills=_skills_half(), projects=_projects_half())
    assert out.parsing_status == "completed"
    assert out.candidate_message() is None, "a complete analysis must not carry an error"


async def test_a_resume_that_genuinely_lists_no_projects_is_still_completed(monkeypatch):
    """
    THE NUANCE THAT DECIDES WHERE THE CHECK GOES. Plenty of first-year resumes have no
    projects on them, and the analyser answering "none, and here is what to ask instead" is a
    correct and complete answer — so completeness is keyed on the two HALVES having succeeded,
    never on the merged object being non-empty. Keying it on emptiness would tell those
    candidates their resume failed to analyse every single time they uploaded it.
    """
    empty_projects = ResumeProjectsHalf(
        projects=[], interview_focus=ResumeInterviewFocus(priority_topics=["Java Collections"])
    )
    out = await _run(monkeypatch, skills=_skills_half(), projects=empty_projects)
    assert out.parsing_status == "completed"
    assert out.analysis is not None and out.analysis.projects == []


async def test_an_empty_analysis_can_never_be_called_completed():
    """
    THE REPORTED BUG, PINNED DIRECTLY. This is the exact outcome the old code produced from a
    model that returned `{}` — a non-None analysis with nothing in it — and the exact input on
    which it said "completed".
    """
    from app.services.ai.schemas import ResumeAnalysisResponse

    empty = analyser_mod.ResumeAnalysisOutcome(
        analysis=ResumeAnalysisResponse(), skills_ok=False, projects_ok=False
    )
    assert empty.parsing_status != "completed"
    assert empty.candidate_message() is not None


# ── "not stated" must not cost a whole billed call ───────────────────────────────────────────


async def test_a_null_for_an_unstated_field_does_not_invalidate_the_response():
    """
    MEASURED ON THE FIRST RUN AFTER THE SPLIT, and the last way a good half was still being
    thrown away. The projects half came back complete and well inside its token ceiling, and
    was rejected anyway:

        loc=('projects', 0, 'role')  msg='Input should be a valid string'  input=None

    The resume did not say what the candidate's role on that project was, so the model wrote
    `"role": null` — which is what our own prompt means by an omitted field. Four nulls in one
    otherwise perfect response invalidated the entire call: it cost that run 10 seconds and a
    retry (18.9s against 8.6s), and a second unlucky null would have lost the projects half
    outright, surfacing as exactly the reported "projects are not been able to fetch".
    """
    from app.services.ai.schemas import ResumeProjectsHalf as Projects
    from app.services.ai.schemas import ResumeSkillsHalf as Skills

    half = Projects.model_validate(
        {
            "projects": [
                {
                    "name": "Distributed Task Scheduler",
                    "description": None,
                    "technologies": None,
                    "role": None,
                    "scale_indicators": None,
                }
            ],
            "interview_focus": {"priority_topics": ["Kafka"], "personalization_notes": None},
        }
    )
    # Null becomes the field's own default, so there is one definition of "unset".
    assert half.projects[0].name == "Distributed Task Scheduler"
    assert half.projects[0].role == ""
    assert half.projects[0].technologies == []
    assert half.interview_focus.personalization_notes == ""

    # And the same on the other half, where a null year is the common case.
    skills = Skills.model_validate(
        {"skills": [{"name": "Java", "years_experience": None, "confidence": None}]}
    )
    assert skills.skills[0].name == "Java"
    assert skills.skills[0].confidence == "inferred"


async def test_a_null_analysis_still_reaches_the_interview_context():
    """
    The end of that path: a project whose role was null must still produce a usable line for
    the interviewer prompt rather than a crash or the literal word "None".
    """
    from app.services.ai.schemas import ResumeAnalysisResponse

    analysis = ResumeAnalysisResponse.model_validate(
        {
            "projects": [{"name": "Sched", "role": None, "technologies": ["Kafka"]}],
            "skills": [{"name": "Java", "confidence": "explicit"}],
        }
    )
    context = analyser_mod.build_interview_context(analysis, "raw resume text")
    assert "Sched" in context
    assert "None" not in context
