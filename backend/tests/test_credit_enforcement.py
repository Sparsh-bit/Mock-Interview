"""
Entitlement is enforced on the server — tests/test_credit_enforcement.py

The paywall in the UI is a courtesy. Every metered endpoint is reachable directly with a valid
token, and the user who has spent their allowance is exactly the user with a reason to try.
A disabled button costs an attacker one `curl`.

So two properties are pinned here:

  * `consume` refuses when the allowance is spent, and refuses with 402 rather than 403 —
    the client routes 402 to the upgrade sheet, so the wrong status shows a dead end where an
    offer belongs.
  * EVERY metered endpoint actually calls it. That one is a source assertion in the spirit of
    test_rls_coverage.py: the failure it catches is not a wrong line of code, it is a missing
    one, and nothing else in the suite would notice a new route shipping free.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.billing.credits import CreditsExhaustedError, consume
from app.services.billing.plans import get_plan

API = pathlib.Path(__file__).resolve().parent.parent / "app" / "api" / "v1"


class _Plan:
    def __init__(self, plan_id="free", period_start=None, period_end=None):
        now = datetime.now(UTC)
        self.plan_id = plan_id
        self.period_start = period_start or now - timedelta(days=1)
        self.period_end = period_end or now + timedelta(days=29)


class _StubDB:
    """Returns the plan row, then the usage count. Records what was added."""

    def __init__(self, plan: _Plan | None, used: int):
        self._returns = [plan, used]
        self.added: list = []
        self.flushed = 0

    async def scalar(self, _stmt):
        return self._returns.pop(0) if self._returns else 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
class TestItRefusesWhenTheAllowanceIsSpent:
    async def test_the_last_unit_is_allowed(self):
        # Free gives 2 interviews; one used means one left.
        db = _StubDB(_Plan("free"), used=1)
        await consume(db, uuid.uuid4(), "interview")
        assert len(db.added) == 1, "the consumption was not recorded"

    async def test_one_past_the_allowance_is_refused(self):
        db = _StubDB(_Plan("free"), used=2)
        with pytest.raises(CreditsExhaustedError) as exc:
            await consume(db, uuid.uuid4(), "interview")
        assert exc.value.status_code == 402, "must be 402 so the client offers an upgrade"
        assert exc.value.code == "CREDITS_EXHAUSTED"

    async def test_nothing_is_recorded_when_it_refuses(self):
        # A refusal that still writes a ledger row would charge the user for the 402.
        db = _StubDB(_Plan("free"), used=99)
        with pytest.raises(CreditsExhaustedError):
            await consume(db, uuid.uuid4(), "gd")
        assert db.added == []

    async def test_the_refusal_carries_what_the_paywall_needs_to_render(self):
        db = _StubDB(_Plan("free"), used=5)
        with pytest.raises(CreditsExhaustedError) as exc:
            await consume(db, uuid.uuid4(), "communication")
        details = exc.value.details
        assert details["feature"] == "communication"
        assert details["plan_id"] == "free"
        assert details["allowance"] == 5
        # The client must never have to parse the message string to know what ran out.
        assert "used" in details

    async def test_a_paid_plan_allows_what_free_refuses(self):
        db = _StubDB(_Plan("pro"), used=2)
        await consume(db, uuid.uuid4(), "interview")
        assert len(db.added) == 1

    async def test_an_unlimited_feature_is_allowed_but_still_recorded(self):
        # Usage data on the unmetered tiers is what tells you whether the next price change
        # is safe, and it costs one insert.
        assert get_plan("pro").allowances["communication"] >= 1_000_000
        db = _StubDB(_Plan("pro"), used=10_000)
        await consume(db, uuid.uuid4(), "communication")
        assert len(db.added) == 1

    async def test_the_charge_is_attributed_to_the_plan_in_force_at_the_time(self):
        # Denormalised at write time so a later upgrade cannot rewrite history — "what was
        # this user entitled to at the time" is what a billing dispute asks.
        db = _StubDB(_Plan("starter"), used=0)
        await consume(db, uuid.uuid4(), "interview")
        assert db.added[0].plan_id == "starter"


class TestNoMeteredRouteCanForgetToCharge:
    """
    Source assertions. The failure mode is a MISSING call, which no behavioural test of the
    existing routes can see — a new endpoint that never charges passes every one of them.
    """

    def test_the_interview_entry_points_charge(self):
        src = (API / "interview.py").read_text()
        # Both /start and /plan begin an interview: create_plan builds its own session, so
        # they are alternative entry points rather than two steps of one flow.
        assert src.count('consume(db, current_user.user_id, "interview"') == 2

    def test_the_group_discussion_charges_once_per_round(self):
        src = (API / "gd.py").read_text()
        assert 'consume(' in src and '"gd"' in src
        # Guarded on an empty history — a round is 26 turns, and charging per turn would
        # make "1 group discussion" buy a twenty-sixth of one.
        assert "if not request.history:" in src

    def test_the_communication_round_charges(self):
        src = (API / "communication.py").read_text()
        assert 'consume(db, current_user.user_id, "communication"' in src

    def test_quizzes_are_never_charged(self):
        # Free forever, on every tier: they cost nothing to serve from the curated bank and
        # they are the habit that brings somebody back on a day they have no time for an
        # interview. A charge appearing here is a product decision, not a refactor.
        src = (API / "quiz.py").read_text()
        assert "consume(" not in src


class TestTheChargeIsUndoneWhenTheWorkFails:
    """
    A charge must never outlive the thing it paid for.

    `get_db` commits on success and rolls back on any exception, so a charge that is left
    UNCOMMITTED inside the request is automatically undone by a failing AI call. An explicit
    `db.commit()` between the charge and the work defeats that: the ledger row is banked, the
    generation then fails, and the candidate has spent an interview on a vendor outage and
    received nothing.

    That is invisible in normal operation — it only appears when the provider is down, which
    is exactly when you cannot afford to also be taking people's allowance. So it is pinned
    in source.
    """

    def _charge_then_commit_before_work(self, filename: str) -> bool:
        src = (API / filename).read_text()
        body = src[src.index("consume(") :]
        # Anything committing within the few lines after the charge and before the endpoint
        # returns is the mistake this guards against.
        window = body[: body.index("return")] if "return" in body else body
        return "db.commit()" in window

    def test_the_group_discussion_does_not_bank_the_charge_early(self):
        assert not self._charge_then_commit_before_work("gd.py")

    def test_the_communication_round_does_not_bank_the_charge_early(self):
        assert not self._charge_then_commit_before_work("communication.py")

    def test_the_interview_does_not_bank_the_charge_early(self):
        assert not self._charge_then_commit_before_work("interview.py")

    def test_consume_itself_never_commits(self):
        # The contract in credits.py: the caller owns the transaction. A commit inside
        # `consume` would make every call site non-atomic at once.
        src = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app/services/billing/credits.py"
        ).read_text()
        assert "db.commit()" not in src
        assert "await db.flush()" in src
