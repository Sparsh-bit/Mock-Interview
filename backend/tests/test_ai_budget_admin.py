"""
An admin testing the product is not metered onto the standby model — tests/test_ai_budget_admin.py

THE REPORT: "the responses are slow and the interview feels boring", and separately a
production log line the operator shared:

    app.services.ai.anthropic_provider  level=info   ai_user_budget_exceeded
    ai_generate_provider_error  context=interview_plan  provider=anthropic
    ai_generate_falling_back    context=interview_plan  exhausted=anthropic

Nothing was broken and the API key was fine — the operator had spent their own
AI_USER_DAILY_BUDGET_USD (default $1.20, roughly three interviews) testing their own product.
Every interview after that ran on the STANDBY provider. So they were measuring the speed and
quality of a different model from the one their candidates get, without knowing, because the
only trace was one info-level line among thousands.

WHY THIS IS A BUG AND NOT WORKING-AS-INTENDED. services/billing/credits.py already decided
this question for credits, and wrote down why: "ADMINS ARE NOT METERED. Not a perk — it is the
only way the product can be operated. Every check of whether an interview still works, every
reproduction of a reported bug, every demo, runs through the same paths a candidate uses;
metering them means the person answering support tickets runs out of interviews on a Tuesday
and starts testing on a spare account."

The per-user AI budget has exactly that problem and exempted nobody. The principle existed in
one place and had never been applied to the analogous one — which is the bug class that keeps
turning up in this codebase.

WHAT IS DELIBERATELY NOT EXEMPTED: the product-wide breaker. That exists to stop a runaway
loop draining the account overnight, and an admin can write a runaway loop like anybody else.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.ai.usage import current_user_id, current_user_is_admin


class TestTheExemption:
    def test_an_admin_is_recognised_from_the_contextvar(self):
        token = current_user_is_admin.set(True)
        try:
            from app.services.ai.anthropic_provider import _current_user_is_admin

            assert _current_user_is_admin() is True
        finally:
            current_user_is_admin.reset(token)

    def test_an_ordinary_user_is_not(self):
        token = current_user_is_admin.set(False)
        try:
            from app.services.ai.anthropic_provider import _current_user_is_admin

            assert _current_user_is_admin() is False
        finally:
            current_user_is_admin.reset(token)

    def test_the_default_is_metered_not_exempt(self):
        """
        FAIL-CLOSED, and this is the assertion that matters most about the default.

        Anything that does not set the flag — a background task, a cron job, a new code path
        somebody forgets — must be METERED. An exemption that fires by accident is a bill
        nobody chose, and it would be invisible until the invoice.
        """
        from app.services.ai.anthropic_provider import _current_user_is_admin

        assert current_user_is_admin.get() is False
        assert _current_user_is_admin() is False

    def test_the_guard_reads_the_flag_and_the_global_breaker_does_not(self):
        """
        Source assertion on the ORDER of the two guards, because the distinction is the whole
        design and it is not visible from the outside: the per-user allowance exempts admins,
        the product-wide circuit breaker exempts nobody.
        """
        import inspect

        from app.services.ai.anthropic_provider import AnthropicProvider

        # THE GUARD MOVED, AND THAT IS THE POINT OF READING IT HERE. It was inline in
        # `complete`, which was correct while `complete` was the only way to spend money on
        # this provider. `stream` is a second one, so the guard was extracted to
        # `_refuse_if_over_budget` and both call it — a guard living inside one caller is a
        # guard the other caller silently does not have.
        src = inspect.getsource(AnthropicProvider._refuse_if_over_budget)
        user_guard = src.index("_user_daily_budget_usd > 0")
        global_guard = src.index("_daily_budget_usd")
        # The global breaker is checked first — its comment says so, and it is the more urgent
        # fact when both have tripped.
        assert global_guard < user_guard
        assert "not _current_user_is_admin()" in src
        # And the exemption appears only in the per-user branch.
        assert src.count("_current_user_is_admin()") == 1

        # AND BOTH SPENDING PATHS GO THROUGH IT. Without this, extracting the guard would have
        # been free to leave `stream` unguarded and every assertion above would still pass.
        for path in (AnthropicProvider.complete, AnthropicProvider.stream):
            assert "_refuse_if_over_budget()" in inspect.getsource(path), (
                f"{path.__name__} can spend money without checking the budget"
            )


class TestTheAuthDependencySetsIt:
    def test_security_sets_both_contextvars_together(self):
        """
        They must be set in the same place: the id without the flag means every admin is
        metered, which is the bug, and the flag without the id means the scope is unknown and
        the guard is skipped for everyone — a silent removal of per-user metering entirely.
        """
        import inspect

        from app.core import security

        src = inspect.getsource(security)
        assert "current_user_is_admin.set(" in src
        assert "current_user_id.set(" in src

    def test_the_flag_is_read_off_the_user_row(self):
        # Not from the JWT, and not from a second query. The auth dependency already has the
        # row in hand; a provider that queries the users table to decide whether to bill is a
        # provider that can fail for a reason unrelated to AI.
        import inspect

        from app.core import security

        assert 'getattr(user, "is_admin", False)' in inspect.getsource(security)


def test_the_contextvars_are_independent():
    """A user id must not imply admin, or the exemption would apply to everybody."""
    uid_token = current_user_id.set(uuid.uuid4())
    try:
        assert current_user_is_admin.get() is False
    finally:
        current_user_id.reset(uid_token)


@pytest.mark.parametrize("value", [True, False])
def test_setting_and_resetting_leaves_no_residue(value: bool):
    # Contextvars leak across tests in the same event loop if a token is dropped, and a leaked
    # admin flag would silently exempt every later test — and, worse, mislead anybody
    # debugging one.
    token = current_user_is_admin.set(value)
    current_user_is_admin.reset(token)
    assert current_user_is_admin.get() is False
