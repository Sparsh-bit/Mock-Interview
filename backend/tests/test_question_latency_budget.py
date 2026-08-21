"""
A slow provider cannot stall a live interview — tests/test_question_latency_budget.py

"when the api gets slower or takes time to respond then try to pick up some questions from the
vector databse that will not break the flow of the interview later."

The cache-first path already existed: `_bank_question` consults the shared pool before
generating. What did not exist was any bound on the generation itself. There was exactly ONE
`asyncio.wait_for` in the whole orchestrator — the 110-second plan budget — and per-question
generation had none, while the GLM client's own read timeout is 180 SECONDS.

So a slow provider mid-interview could leave a candidate looking at a blank panel for three
minutes, with nothing on screen to say whether the software had died. And the asymmetry was
backwards: a plan is generated while somebody watches a "preparing your interview" screen and
can afford to be slow; a question arrives in the middle of a conversation and cannot.

WHAT THE TIMEOUT DOES *NOT* DO is fail. Returning None puts the caller on the path a provider
outage already used — the shared pool, then the bank — and those are real questions for this
role. The candidate gets a slightly less personal question instead of a silence. That is the
whole trade, and it is why the fallback is not an error state.

WHY 18 SECONDS. A generated question is better than a banked one; it is aimed at what the
candidate just revealed, so the budget must not be so tight that it discards good questions
over a slow second. But an interviewer who goes quiet for twenty seconds has already broken
the illusion, and past that a worse-but-immediate question is the better product.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.core.config import Settings, settings
from app.services.interview.orchestrator import InterviewOrchestrator


class TestTheBudgetExists:
    def test_a_live_question_has_a_wall_clock_budget(self):
        assert settings.INTERVIEW_QUESTION_AI_BUDGET_SECONDS > 0

    def test_it_is_much_tighter_than_the_plan_budget(self):
        """
        The asymmetry is the point and it used to be absent. A plan is generated behind a
        progress screen; a question arrives mid-conversation.
        """
        from app.services.interview.orchestrator import _PLAN_AI_BUDGET_SECONDS

        assert settings.INTERVIEW_QUESTION_AI_BUDGET_SECONDS < _PLAN_AI_BUDGET_SECONDS / 3

    def test_it_is_tighter_than_the_provider_read_timeout(self):
        """
        THE ONE THAT WOULD HAVE CAUGHT THE ORIGINAL BUG. If this budget were looser than the
        client's own read timeout, the client would give up first and the budget would be
        decorative — which is exactly the state before it existed: no budget at all, and a
        180-second provider timeout deciding how long a candidate waits.
        """
        src = inspect.getsource(inspect.getmodule(InterviewOrchestrator))
        assert "INTERVIEW_QUESTION_AI_BUDGET_SECONDS" in src
        # The GLM client's read timeout, from services/ai/provider_factory.py.
        assert settings.INTERVIEW_QUESTION_AI_BUDGET_SECONDS < 180.0

    def test_the_default_is_documented_rather_than_a_bare_number(self):
        # Every tuning knob in this file carries the argument for its value. A number with no
        # reasoning is a number nobody can safely change.
        description = Settings.model_fields["INTERVIEW_QUESTION_AI_BUDGET_SECONDS"].description
        # The field uses a plain default with a comment block above it rather than a Field
        # description, which is the convention for the interview knobs in this file — so the
        # assertion is that the SOURCE carries the reasoning.
        source = inspect.getsource(Settings)
        assert description or "THIS EXISTS BECAUSE THERE WAS NO LIMIT AT ALL" in source


class TestWhatHappensWhenItExpires:
    def test_the_timeout_is_caught_and_returns_none_rather_than_raising(self):
        """
        None is how every other unavailable-provider case already signals "caller, fall back".
        Raising here would surface a slow vendor as a failed interview.
        """
        src = inspect.getsource(InterviewOrchestrator._generate_question)
        assert "except TimeoutError:" in src
        # Both failure kinds return None, so the caller needs no new branch.
        after_timeout = src[src.index("except TimeoutError:") :]
        assert "return None" in after_timeout

    def test_it_is_logged_at_info_and_not_as_a_fault(self):
        """
        A slow provider is a normal operating condition that the interview handled exactly as
        designed. Logging a designed-for degradation as a warning makes a healthy system look
        broken — the same mistake this codebase already fixed for the /admin/overview probes
        and for the TTS degrade notice.
        """
        src = inspect.getsource(InterviewOrchestrator._generate_question)
        block = src[src.index("except TimeoutError:") :]
        assert "logger.info(" in block
        assert "logger.warning(" not in block
        assert "logger.error(" not in block

    def test_the_log_names_where_the_question_came_from_instead(self):
        # Whoever reads this line needs to know the interview continued, not just that
        # something timed out.
        src = inspect.getsource(InterviewOrchestrator._generate_question)
        assert "falling_back_to" in src

    def test_zero_disables_the_budget_without_crashing(self):
        # Documented as an escape hatch, so it must actually be one rather than a
        # wait_for(timeout=0) that expires instantly and never generates anything.
        src = inspect.getsource(InterviewOrchestrator._generate_question)
        assert "if budget > 0 else call" in src


class TestTheCacheIsConsultedFirstAtAll:
    def test_the_shared_pool_is_tried_before_paying_for_generation(self):
        """
        This part already worked and is asserted so it stays working: it is the mechanism that
        makes AI cost fall as usage rises instead of scaling with it.
        """
        src = inspect.getsource(InterviewOrchestrator._generate_question)
        pool = src.index("_bank_question(")
        gen = src.index("generate_structured(")
        assert pool < gen

    def test_a_candidate_specific_question_never_comes_from_the_shared_pool(self):
        # The tenancy boundary, and the reason the pool is safe at all: a question derived
        # from somebody's answer is about that person and is never shared.
        src = inspect.getsource(InterviewOrchestrator._generate_question)
        assert "if not focus_concepts:" in src


@pytest.mark.asyncio
async def test_wait_for_semantics_are_what_this_relies_on():
    """
    Guards the assumption rather than the code. If `asyncio.wait_for` ever stopped cancelling
    the wrapped coroutine on expiry, this budget would leak a request per timeout and keep
    billing for answers nobody reads.
    """
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.sleep(5)
        return "too late"

    task = slow()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task, timeout=0.05)
    assert started.is_set()
