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
