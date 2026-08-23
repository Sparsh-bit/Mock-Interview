"""
Auto top-up — tests/test_autopay.py

Money leaving an account without its owner pressing anything, so the tests that matter are
the ones asserting a charge does NOT happen: not when it is off, not when the mandate was
never finished, not twice in a row, not on a suspended account, and not forever against a
card that keeps declining.

`charge_saved_token` is the one function needing live keys and is not exercised here — the
same split `create_order` has, and for the same reason: everything that decides WHETHER to
charge is pure and testable today.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.billing import UserPlan
from app.services.billing.autopay import (
    MAX_FAILURES,
    RETRY_WINDOW,
    is_eligible,
    item_for,
)


def plan(**kw) -> UserPlan:
    base = {
        "user_id": None,
        "source": "signup",
        "is_banned": False,
        "autopay_enabled": True,
        "autopay_item_id": "interview_1",
        "autopay_token": "token_abc",
        "autopay_customer_id": "cust_abc",
        "autopay_last_attempt_at": None,
        "autopay_failures": 0,
    }
    base.update(kw)
    return UserPlan(**base)


class TestWhenAChargeIsRefused:
    def test_off_by_default_means_no_charge(self):
        allowed, reason = is_eligible(plan(autopay_enabled=False))
        assert allowed is False
        assert reason == "not enabled"

    def test_an_unfinished_mandate_is_inert_rather_than_dangerous(self):
        # Enabling records the intent; the mandate is authorised inside Razorpay's sheet.
        # A setup abandoned halfway must not become a charge.
        assert is_eligible(plan(autopay_token=None))[0] is False
        assert is_eligible(plan(autopay_item_id=None))[0] is False

    def test_the_inert_ban_column_no_longer_blocks_a_charge(self):
        """
        THE OPPOSITE OF WHAT THIS ASSERTED, and deliberately so.

        Autopay used to refuse an account with `is_banned` set — correctly, while suspensions
        existed: taking money from somebody who cannot use the product is the worst possible
        combination. Credential-sharing suspension has been removed (see core/security.py), so
        the column is inert and the accounts still carrying it can use the product normally.
        Refusing to top them up would leave a paying customer unable to buy, for a reason that
        no longer exists anywhere else in the system.
        """
        allowed, _ = is_eligible(plan(is_banned=True))
        assert allowed is True

    def test_only_one_attempt_per_window(self):
        # A declined card retried on every request is a card the bank blocks, and a wall of
        # decline messages from their bank rather than one from us.
        recent = datetime.now(UTC) - (RETRY_WINDOW / 2)
        assert is_eligible(plan(autopay_last_attempt_at=recent))[0] is False

    def test_it_may_try_again_once_the_window_has_passed(self):
        old = datetime.now(UTC) - RETRY_WINDOW - timedelta(minutes=1)
        assert is_eligible(plan(autopay_last_attempt_at=old))[0] is True

    def test_it_gives_up_after_repeated_failures(self):
        # A card that has declined three times will decline a fourth. Continuing is not
        # persistence, it is noise on somebody's statement.
        assert is_eligible(plan(autopay_failures=MAX_FAILURES))[0] is False
        assert is_eligible(plan(autopay_failures=MAX_FAILURES - 1))[0] is True

    def test_an_item_that_is_no_longer_sold_stops_it(self):
        # A price change or a removed bundle. Charging the nearest thing would be inventing
        # a purchase nobody made.
        allowed, reason = is_eligible(plan(autopay_item_id="interview_999"))
        assert allowed is False
        assert "no longer sold" in reason

    def test_a_naive_timestamp_does_not_raise(self):
        # Postgres returns tz-aware, but an older row or a fixture might not — and an
        # exception here would surface inside the paywall path and take an interview down.
        naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        assert is_eligible(plan(autopay_last_attempt_at=naive))[0] is True


class TestWhenAChargeIsAllowed:
    def test_a_fully_configured_account_is_eligible(self):
        allowed, reason = is_eligible(plan())
        assert allowed is True
        assert reason == "ok"

    def test_the_item_is_resolved_from_the_catalogue(self):
        # The browser never names a price. The plan row names an ITEM, and its price is
        # looked up server-side — the same rule every other purchase follows.
        item = item_for(plan(autopay_item_id="interview_1"))
        assert item is not None
        assert item.price_paise > 0

    def test_an_unknown_saved_item_resolves_to_nothing(self):
        assert item_for(plan(autopay_item_id="not_a_real_item")) is None


class TestTheThrottleIsRealTime:
    def test_the_window_is_hours_not_minutes(self):
        # Pinned, because "retry sooner" is a tempting change that turns one decline into a
        # dozen on somebody's statement. Six hours is long enough to be obviously deliberate.
        assert timedelta(hours=1) <= RETRY_WINDOW

    def test_the_failure_limit_is_small(self):
        assert 1 <= MAX_FAILURES <= 5
