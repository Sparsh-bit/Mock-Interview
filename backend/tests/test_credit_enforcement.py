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
    """
    Answers by WHICH TABLE the statement touches, not by call order.

    Call order was the obvious way and it broke the moment `consume` grew an admin check in
    front of the balance read — every test started handing the plan row to the wrong query.
    Matching on the rendered SQL means adding another lookup in front does not silently
    rewrite what these tests are asserting.
    """

    def __init__(
        self,
        plan: _Plan | None,
        net: dict[str, int] | None = None,
        *,
        is_admin: bool = False,
    ):
        self._plan = plan
        self._net = net or {}
        self._is_admin = is_admin
        self.added: list = []
        self.flushed = 0

    async def scalar(self, stmt):
        sql = str(stmt)
        if "users.is_admin" in sql:
            return self._is_admin
        if "user_plans" in sql:
            return self._plan
        # count(*) of consume rows, used only by get_balance.
        return 0

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
class TestAdminsAreNotMetered:
    """
    Not a perk — it is the only way the product can be operated. Every check that an
    interview still works, every reproduction of a reported bug, every demo runs through the
    same paths a candidate uses. Metering them means whoever answers support runs out on a
    Tuesday and starts testing on a spare account, which is how a broken flow reaches
    production unnoticed.
    """

    async def test_an_admin_with_nothing_left_is_still_allowed(self):
        db = _StubDB(_Plan(), net={"interview": -99}, is_admin=True)
        await consume(db, uuid.uuid4(), "interview")

    async def test_no_ledger_row_is_written_for_an_admin(self):
        # Recording admin usage as consumption would push the cost-per-user figures in
        # /ai-usage in the direction of "our users are more expensive than they are", and
        # that number is what the pricing rests on.
        db = _StubDB(_Plan(), net={}, is_admin=True)
        await consume(db, uuid.uuid4(), "interview")
        assert db.added == []

    async def test_a_non_admin_is_still_metered(self):
        # Guards the exemption from becoming a hole: if the admin lookup ever returned
        # truthy by accident, every one of the tests above would still pass.
        db = _StubDB(_Plan(), net={"interview": -1}, is_admin=False)
        with pytest.raises(CreditsExhaustedError):
            await consume(db, uuid.uuid4(), "interview")


@pytest.mark.asyncio
class TestAPreviouslySuspendedAccountCanStillSpend:
    """
    THE OPPOSITE ASSERTION TO THE ONE THAT USED TO BE HERE, and the change is deliberate.

    `consume` used to refuse an account with `is_banned` set, as the last gate before anything
    billable. Credential-sharing suspension has been removed entirely — see the note in
    core/security.py for why — and `is_banned` is now an inert column that some accounts still
    carry from before the removal.

    Those are exactly the accounts that must not stay locked out: they were suspended by a
    detector that fired on a phone changing network, and several of them had paid. So the gate
    is gone, and this test exists to stop it being reinstated as a "safety" check that would
    silently re-break them.
    """

    async def test_the_inert_ban_column_does_not_block_spending(self):
        db = _StubDB(_Plan(banned=True), net={"interview": 10})
        await consume(db, uuid.uuid4(), "interview")
        # The charge was written: one ledger row, not a refusal.
        assert len(db.added) == 1


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
