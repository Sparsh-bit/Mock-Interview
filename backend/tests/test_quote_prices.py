"""
The whole store, priced under one code — tests/test_quote_prices.py

WHAT THIS IS FOR. /pricing has to show a live figure on every tile the moment a code is
applied and revert them all when it is removed. The server answers that in one request, with
the same functions checkout and the webhook use, precisely so the browser never becomes a
second implementation of what money costs.

That makes `_priced_catalogue` a money path, and the failures it can have are the quiet kind:
a scope ignored (the page advertises a discount the till then refuses), a rounding that goes
the wrong way (product given away a rupee at a time), a `covered` flag inverted (every tile
shows full price under a working code). None of those raise. All of them are arithmetic, so
they are tested as arithmetic — no database, no HTTP, no fixtures.

Also pinned here: the trial allowance the items endpoint publishes. /pricing spent weeks
advertising "1 mock interview free" and "1 group discussion free" after both went paid,
because the strip was a sentence typed into a page instead of a number read from plans.py.
"""

from __future__ import annotations

import pytest

from app.api.v1.billing import _priced_catalogue
from app.models.billing import Offer
from app.services.billing.offers import KIND_FIXED, KIND_FREE, KIND_PERCENT
from app.services.billing.plans import FEATURES, ITEMS, TRIAL_ALLOWANCE, items_for


def _offer(kind: str, value: int, applies_to: list[str] | None = None) -> Offer:
    """An unpersisted offer. Only the three fields that decide money are set."""
    return Offer(code="TEST", label="test", kind=kind, value=value, applies_to=applies_to or [])


def _row(rows, item_id: str):
    return next(r for r in rows if r.item_id == item_id)


class TestEveryItemIsPriced:
    def test_one_row_per_catalogue_item(self):
        rows = _priced_catalogue(_offer(KIND_PERCENT, 50))
        assert [r.item_id for r in rows] == [i.id for i in ITEMS], (
            "the page lights up tiles from this list, so a missing row is a tile that keeps "
            "its full price under a code that covers it"
        )

    def test_the_original_price_is_always_the_catalogue_price(self):
        # The struck-through figure. It has to be the real list price whatever the code does,
        # or the saving on screen is measured against a number nobody is charged.
        rows = _priced_catalogue(_offer(KIND_PERCENT, 40))
        for item in ITEMS:
            assert _row(rows, item.id).original_paise == item.price_paise


class TestTheArithmetic:
    def test_a_percentage_comes_off_every_covered_item(self):
        rows = _priced_catalogue(_offer(KIND_PERCENT, 50))
        for item in ITEMS:
            r = _row(rows, item.id)
            assert r.covered is True
            assert r.charged_paise == item.price_paise // 2 or r.charged_paise == round(
                item.price_paise * 0.5
            )

    def test_a_hundred_percent_code_is_free_and_says_so(self):
        rows = _priced_catalogue(_offer(KIND_PERCENT, 100))
        for r in rows:
            assert r.charged_paise == 0
            assert r.is_free is True, (
                "the page routes a zero-rupee order to a confirm sheet instead of Razorpay, "
                "and it decides that from this flag"
            )

    def test_a_flat_price_never_charges_more_than_the_item_costs(self):
        # A ₹99 fixed-price code against a ₹19 drill must not turn a discount into a surcharge.
        cheapest = min(ITEMS, key=lambda i: i.price_paise)
        rows = _priced_catalogue(_offer(KIND_FIXED, cheapest.price_paise + 5_000))
        r = _row(rows, cheapest.id)
        assert r.charged_paise <= cheapest.price_paise

    def test_no_row_is_ever_negative(self):
        for kind, value in ((KIND_PERCENT, 100), (KIND_FREE, 0), (KIND_PERCENT, 99)):
            for r in _priced_catalogue(_offer(kind, value)):
                assert r.charged_paise >= 0
                assert r.charged_paise <= r.original_paise

    def test_is_free_agrees_with_the_number_beside_it(self):
        # Two fields describing one fact. A page that reads `is_free` and a till that reads
        # `charged_paise` must never disagree.
        for kind, value in ((KIND_PERCENT, 100), (KIND_PERCENT, 50), (KIND_FREE, 0)):
            for r in _priced_catalogue(_offer(kind, value)):
                assert r.is_free == (r.charged_paise == 0)


class TestScopeIsHonoured:
    def test_an_empty_scope_covers_everything(self):
        # The ordinary case, and the one that must not be got backwards: an empty `applies_to`
        # has always meant "every item", so reading it as "no item" would switch off every
        # code already in the table.
        rows = _priced_catalogue(_offer(KIND_PERCENT, 25, []))
        assert all(r.covered for r in rows)

    def test_an_item_outside_the_scope_keeps_its_full_price(self):
        interview_ids = [i.id for i in items_for("interview")]
        rows = _priced_catalogue(_offer(KIND_PERCENT, 50, interview_ids))
        for item in ITEMS:
            r = _row(rows, item.id)
            if item.id in interview_ids:
                assert r.covered is True
                assert r.charged_paise < item.price_paise
            else:
                assert r.covered is False, (
                    "an out-of-scope item reported as covered is a tile promising a discount "
                    "that quote() will refuse at the till"
                )
                assert r.charged_paise == item.price_paise, (
                    "an out-of-scope item must show what the candidate will ACTUALLY be "
                    "charged, which is the full price"
                )

    @pytest.mark.parametrize("feature", FEATURES)
    def test_scoping_to_one_feature_leaves_the_others_alone(self, feature: str):
        ids = [i.id for i in items_for(feature)]
        assert ids, f"{feature} has no items — the catalogue changed under this test"
        rows = _priced_catalogue(_offer(KIND_PERCENT, 30, ids))
        assert {r.item_id for r in rows if r.covered} == set(ids)


class TestTheTrialAllowanceIsPublished:
    def test_interviews_and_group_discussions_are_not_free(self):
        # The exact claim /pricing used to make. If either of these ever goes back above zero
        # it must be because someone changed plans.py deliberately, not because a page said so.
        assert TRIAL_ALLOWANCE["interview"] == 0
        assert TRIAL_ALLOWANCE["gd"] == 0

    def test_every_feature_has_a_declared_allowance(self):
        # A feature missing from the map would have the items endpoint publish a default, and a
        # default is exactly the kind of guess this field exists to remove.
        for feature in FEATURES:
            assert feature in TRIAL_ALLOWANCE

    def test_the_items_endpoint_publishes_it_rather_than_the_page_assuming_it(self):
        import inspect

        from app.api.v1 import billing

        src = inspect.getsource(billing)
        assert "trial_allowance=" in src, (
            "the public items response no longer carries the allowance, so the free-tier strip "
            "on /pricing is back to stating a number from memory"
        )
