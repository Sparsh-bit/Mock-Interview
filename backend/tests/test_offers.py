"""
Promo codes and offers — tests/test_offers.py

This is money. The tests that matter most are the ones asserting somebody CANNOT get
something: cannot name their own price, cannot use a code twice, cannot use a switched-off
code, and cannot turn off the amount check by claiming an offer that does not exist.

The DB-backed paths (redeem, the unique index, the row lock) need Postgres and live in
test_integration.py's fixtures. Everything here is the pure arithmetic and the payment
parsing, which is where the exploitable mistakes actually are.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.billing import Offer
from app.services.billing import razorpay
from app.services.billing.offers import (
    KIND_FIXED,
    KIND_FREE,
    KIND_PERCENT,
    MIN_CHARGEABLE_PAISE,
    OfferError,
    _apply,
    _window_message,
    charge_for,
)
from app.services.billing.plans import get_item


def offer(**kw) -> Offer:
    """An Offer with sane defaults, not persisted."""
    base = {
        "code": "TEST",
        "label": "Test",
        "kind": KIND_PERCENT,
        "value": 50,
        "applies_to": [],
        "enabled": True,
        "is_public": False,
        "starts_at": None,
        "ends_at": None,
        "max_redemptions": None,
        "requires_captcha": False,
    }
    base.update(kw)
    return Offer(**base)


ITEM = get_item("interview_1")  # ₹49 = 4900 paise


class TestTheDiscountArithmetic:
    def test_a_percent_offer_takes_that_percent_off(self):
        assert _apply(offer(kind=KIND_PERCENT, value=50), 4900) == 2450
        assert _apply(offer(kind=KIND_PERCENT, value=25), 4900) == 3675

    def test_rounding_favours_the_candidate(self):
        # 33% of 4900 is 1617 exactly; a price that does not divide cleanly must round the
        # DISCOUNT up rather than down. A discount that rounds against the person using it
        # is the kind of thing that ends up on Twitter.
        assert _apply(offer(kind=KIND_PERCENT, value=33), 999) <= 999 - (999 * 33) // 100

    def test_a_fixed_offer_sets_the_final_price(self):
        # "₹1 for a launch offer" — the value IS the price, not the discount.
        assert _apply(offer(kind=KIND_FIXED, value=100), 4900) == 100

    def test_a_free_offer_is_zero(self):
        assert _apply(offer(kind=KIND_FREE), 4900) == 0

    def test_a_discount_below_one_rupee_becomes_free(self):
        # Razorpay refuses anything under ₹1, so 95% off a ₹19 drill is not a cheap order —
        # it is an impossible one. The candidate gets the drill rather than an error from a
        # payment provider they never chose to involve.
        assert _apply(offer(kind=KIND_PERCENT, value=99), 1900) == 0
        assert _apply(offer(kind=KIND_FIXED, value=50), 4900) == 0

    def test_the_boundary_is_exactly_one_rupee(self):
        assert _apply(offer(kind=KIND_FIXED, value=MIN_CHARGEABLE_PAISE), 4900) == 100
        assert _apply(offer(kind=KIND_FIXED, value=MIN_CHARGEABLE_PAISE - 1), 4900) == 0

    def test_a_discount_can_never_raise_the_price(self):
        # A "fixed" offer configured above list must not charge more than the item costs.
        assert _apply(offer(kind=KIND_FIXED, value=99_999), 4900) == 4900

    def test_a_percent_over_100_or_under_0_is_clamped(self):
        assert _apply(offer(kind=KIND_PERCENT, value=250), 4900) == 0
        assert _apply(offer(kind=KIND_PERCENT, value=-5), 4900) == 4900

    def test_an_unknown_kind_refuses_rather_than_charging_full_price(self):
        # Silently meaning "no discount" would charge full price against a code the candidate
        # was told would work — they would pay ₹49 believing they had paid ₹25.
        with pytest.raises(OfferError):
            _apply(offer(kind="nonsense"), 4900)


class TestTheWindow:
    def test_an_offer_with_no_dates_is_live(self):
        assert _window_message(offer(), datetime.now(UTC)) is None

    def test_before_the_start_it_is_not_yet_active(self):
        now = datetime.now(UTC)
        msg = _window_message(offer(starts_at=now + timedelta(days=1)), now)
        assert msg and "not active yet" in msg

    def test_after_the_end_it_has_expired(self):
        now = datetime.now(UTC)
        msg = _window_message(offer(ends_at=now - timedelta(seconds=1)), now)
        assert msg and "expired" in msg

    def test_the_message_distinguishes_the_two(self):
        # "Invalid code" for an expired one sends the candidate hunting for a typo that is
        # not there. The reason has to be actionable.
        now = datetime.now(UTC)
        early = _window_message(offer(starts_at=now + timedelta(days=1)), now)
        late = _window_message(offer(ends_at=now - timedelta(days=1)), now)
        assert early != late


class TestThePaymentCannotBeUnderpaid:
    """
    The guard that protects every purchase, and the new hole that had to not be opened.

    `notes` is attacker-influenced: it travels to Razorpay and back. The amount is the only
    fact. Adding `offer_code` to the notes meant adding a field that, handled naively, turns
    the amount check off — so a ₹1 payment annotated `item_id=interview_5` would buy five.
    """

    def _payment(self, *, amount: int, item_id: str, notes_extra: dict | None = None) -> dict:
        notes = {"item_id": item_id, "user_id": "11111111-1111-1111-1111-111111111111"}
        notes.update(notes_extra or {})
        return {
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test",
                        "order_id": "order_test",
                        "status": "captured",
                        "amount": amount,
                        "notes": notes,
                    }
                }
            }
        }

    def test_a_full_price_payment_is_accepted_and_already_verified(self):
        out = razorpay.items_from_payment(self._payment(amount=4900, item_id="interview_1"))
        assert out is not None
        assert out.amount_verified is True
        assert out.offer_code == ""

    def test_an_underpayment_with_no_offer_is_still_refused(self):
        # The original guard, unchanged. This is the one that stops a ₹1 payment buying five
        # interviews, and nothing about offers may weaken it.
        assert razorpay.items_from_payment(self._payment(amount=100, item_id="interview_5")) is None

    def test_claiming_an_offer_does_not_silently_accept_the_amount(self):
        # THE HOLE THAT MUST NOT EXIST. A discounted payment is legitimately below list, so
        # the pure check cannot apply — but skipping it would make `offer_code` a free pass.
        # It comes back flagged as UNVERIFIED so the webhook is obliged to check it.
        out = razorpay.items_from_payment(
            self._payment(amount=100, item_id="interview_5", notes_extra={"offer_code": "ANYTHING"})
        )
        assert out is not None
        assert out.amount_verified is False, "a claimed offer must not count as verified"
        assert out.offer_code == "ANYTHING"

    def test_the_offer_code_is_normalised_to_uppercase(self):
        out = razorpay.items_from_payment(
            self._payment(amount=100, item_id="interview_1", notes_extra={"offer_code": "diwali25"})
        )
        assert out and out.offer_code == "DIWALI25"

    def test_an_uncaptured_payment_is_never_granted(self):
        body = self._payment(amount=4900, item_id="interview_1")
        body["payload"]["payment"]["entity"]["status"] = "authorized"
        assert razorpay.items_from_payment(body) is None

    def test_an_unknown_item_is_never_guessed_at(self):
        assert razorpay.items_from_payment(self._payment(amount=4900, item_id="nope")) is None


class TestTheWebhookRecomputesTheExpectedPrice:
    def test_charge_for_matches_the_quote_arithmetic(self):
        # The webhook re-derives from the offer row rather than trusting what came back
        # through the gateway. A legitimate payment must match exactly, or every discounted
        # purchase would be rejected.
        o = offer(kind=KIND_PERCENT, value=50)
        assert charge_for(o, ITEM) == _apply(o, ITEM.price_paise)

    def test_a_free_code_expects_zero(self):
        assert charge_for(offer(kind=KIND_FREE), ITEM) == 0

    def test_a_payment_short_of_the_discounted_price_is_short(self):
        # 50% off ₹49 is ₹24.50. Paying ₹1 against that code is still an underpayment, and
        # the webhook's comparison is what catches it.
        expected = charge_for(offer(kind=KIND_PERCENT, value=50), ITEM)
        assert expected == 2450
        assert expected > 100


class TestTheOrderCannotBeBuiltBelowRazorpaysFloor:
    async def test_a_zero_amount_order_is_a_programming_error(self):
        # A fully-discounted item must be granted directly. Reaching create_order with zero
        # means the free path was skipped, and failing loudly beats sending Razorpay an order
        # it will reject in front of the candidate.
        with pytest.raises(ValueError, match="below Razorpay"):
            await razorpay.create_order(ITEM, "user", charged_paise=0)

    async def test_an_amount_under_one_rupee_is_refused(self):
        with pytest.raises(ValueError, match="below Razorpay"):
            await razorpay.create_order(ITEM, "user", charged_paise=99)
