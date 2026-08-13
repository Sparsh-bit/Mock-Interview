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

import pytest

from app.services.billing.credits import CreditsExhaustedError, consume
from app.services.billing.plans import trial_allowance

API = pathlib.Path(__file__).resolve().parent.parent / "app" / "api" / "v1"


class _Plan:
    """The per-user row. Holds no balance now — only the lock target and the ban flag."""

    def __init__(self, banned=False):
        self.is_banned = banned
        self.ban_reason = None


class _StubDB:
    """Returns the plan row, then the ledger totals. Records what was added."""

    def __init__(self, plan: _Plan | None, net: dict[str, int] | None = None):
        self._plan = plan
        self._net = net or {}
        self.added: list = []
        self.flushed = 0

    async def scalar(self, _stmt):
        return self._plan

    async def execute(self, _stmt):
        # _totals() iterates (feature, sum) pairs.
        return list(self._net.items())

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
class TestTheTrialThenNothing:
    async def test_the_trial_is_spendable_without_buying_anything(self):
        # A brand-new account: no ledger rows at all, and the trial is a constant added at
        # read time rather than rows granted at signup.
        db = _StubDB(_Plan(), net={})
        await consume(db, uuid.uuid4(), "interview")
        assert len(db.added) == 1
        assert db.added[0].delta == -1
        assert db.added[0].kind == "consume"

    async def test_a_spent_trial_with_no_purchases_is_refused(self):
        assert trial_allowance("interview") == 1
        db = _StubDB(_Plan(), net={"interview": -1})
        with pytest.raises(CreditsExhaustedError) as exc:
            await consume(db, uuid.uuid4(), "interview")
        assert exc.value.status_code == 402, "must be 402 so the client offers the store"
        assert exc.value.code == "CREDITS_EXHAUSTED"

    async def test_nothing_is_recorded_when_it_refuses(self):
        # A refusal that still writes a ledger row would charge the user for the 402.
        db = _StubDB(_Plan(), net={"gd": -1})
        with pytest.raises(CreditsExhaustedError):
            await consume(db, uuid.uuid4(), "gd")
        assert db.added == []

    async def test_a_purchase_restores_entitlement(self):
        # trial 1, spent 1, bought 5 -> 5 left.
        db = _StubDB(_Plan(), net={"interview": 4})
        await consume(db, uuid.uuid4(), "interview")
        assert len(db.added) == 1

    async def test_the_features_do_not_share_a_pool(self):
        # Buying interviews must not grant group discussions. The whole point of named
        # allowances over one credit number.
        db = _StubDB(_Plan(), net={"interview": 10, "gd": -1})
        with pytest.raises(CreditsExhaustedError):
            await consume(db, uuid.uuid4(), "gd")

    async def test_the_refusal_says_whether_the_trial_was_the_thing_spent(self):
        # Drives the copy: "you have used your free mock interview" reads very differently
        # from "you have no mock interviews left", and only one of them is true for a
        # first-time user.
        db = _StubDB(_Plan(), net={"interview": -1})
        with pytest.raises(CreditsExhaustedError) as exc:
            await consume(db, uuid.uuid4(), "interview")
        assert exc.value.details["feature"] == "interview"
        assert exc.value.details["trial_used"] is True


@pytest.mark.asyncio
class TestABannedAccountCannotSpend:
    async def test_it_is_refused_before_anything_is_charged(self):
        # Checked under the same row lock that decides entitlement — this is the last gate
        # before something billable happens.
        from app.services.billing.credits import AccountBannedError

        db = _StubDB(_Plan(banned=True), net={"interview": 10})
        with pytest.raises(AccountBannedError) as exc:
            await consume(db, uuid.uuid4(), "interview")
        # 403, not 402: more money does not fix this, and routing it to the store would be
        # both wrong and insulting.
        assert exc.value.status_code == 403
        assert exc.value.details["appealable"] is True
        assert db.added == []


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
