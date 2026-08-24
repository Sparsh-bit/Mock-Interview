"""
A coupon scoped to features — tests/test_offer_feature_scope.py

An admin thinks "this code is for drills". The `applies_to` column has only ever meant "these
item ids". The gap between those two sentences is where this feature lives, and every failure
in it is silent:

  AN EMPTY SCOPE MEANS EVERY ITEM. It always has — most codes are store-wide. So a misspelt
  feature that expands to nothing does not produce a narrow code, it produces an UNRESTRICTED
  one, and the admin discounts the whole catalogue believing they limited it to drills. That
  is why the validator rejects rather than ignores, and why it is tested first.

  THE EXPANSION IS A SNAPSHOT. Choosing "interviews" records the interview items that exist
  today. That is a deliberate trade against a hand-applied migration, and a trade nobody
  remembers is a trade that gets undone, so it is pinned here with the reasoning attached.

  THE PREVIEW MUST PRICE WHAT CREATION WOULD WRITE. It shares `OfferTerms` with the create
  endpoint for exactly that reason. A preview computed even slightly differently would be a
  preview of a different offer — worse than none, because it would be believed.

No database and no HTTP: all of this is arithmetic and validation over the catalogue.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.api.v1.admin_offers import (
    OfferIn,
    OfferTerms,
    _expand_features,
    _features_covered,
    preview_offer,
)
from app.models.billing import Offer
from app.services.billing import offers
from app.services.billing.offers import KIND_PERCENT
from app.services.billing.plans import FEATURES, ITEMS, items_for


def _terms(features: list[str], *, kind: str = KIND_PERCENT, value: int = 50, items=None):
    return OfferTerms(
        kind=kind, value=value, applies_to_features=features, applies_to=items or []
    )


class TestFeaturesExpandIntoItemIds:
    @pytest.mark.parametrize("feature", FEATURES)
    def test_one_feature_expands_to_exactly_its_items(self, feature: str):
        assert set(_expand_features([feature])) == {i.id for i in items_for(feature)}

    def test_no_feature_expands_to_nothing(self):
        # Which leaves `applies_to` empty, which has always meant "every item". "No feature
        # chosen" therefore keeps meaning "applies to everything", exactly as every offer
        # created before this field behaves.
        assert _expand_features([]) == []

    def test_every_feature_together_covers_the_whole_catalogue(self):
        assert set(_expand_features(list(FEATURES))) == {i.id for i in ITEMS}

    def test_the_expansion_is_a_snapshot_of_today(self):
        # The accepted cost of not adding a column. A feature-scoped code is a frozen list of
        # ids, not a standing rule about a feature — add an item to plans.ITEMS tomorrow and
        # every code created before it simply does not name the new id, so the candidate pays
        # full price on it rather than being handed a discount nobody priced.
        expanded = _expand_features(["interview"])
        assert all(i in {x.id for x in ITEMS} for i in expanded)
        assert set(expanded) == {i.id for i in items_for("interview")}


class TestReadingTheScopeBackOut:
    @pytest.mark.parametrize("feature", FEATURES)
    def test_a_feature_scope_round_trips(self, feature: str):
        assert _features_covered(_expand_features([feature])) == [feature]

    def test_an_empty_stored_scope_reads_back_as_unrestricted(self):
        assert _features_covered([]) == []

    def test_a_hand_picked_item_list_is_not_reported_as_a_feature(self):
        # "The five-pack only" is a real thing an admin can express with `applies_to`, and it
        # is not any feature. Reporting it as one would tick a checkbox in the UI that, if
        # saved, would silently widen the code to the whole feature.
        single = next(i for i in items_for("interview") if i.quantity == 1)
        assert _features_covered([single.id]) == []


class TestAMisspeltFeatureIsRefused:
    def test_unknown_feature_raises(self):
        with pytest.raises(ValidationError):
            _terms(["comunication"])

    def test_the_error_names_what_was_expected(self):
        with pytest.raises(ValidationError) as exc:
            _terms(["reports"])
        assert "reports" in str(exc.value)
        for feature in FEATURES:
            assert feature in str(exc.value)

    def test_report_is_not_a_feature(self):
        # There is no report product. The unlock was removed, so a checkbox for it would be a
        # scope over an item that does not exist — i.e. an unrestricted code.
        assert "report" not in FEATURES
        with pytest.raises(ValidationError):
            _terms(["report"])

    def test_duplicates_and_order_normalise(self):
        # Two equivalent requests must store a byte-identical scope, or `_features_covered`
        # reads them back differently and the UI shows different boxes ticked.
        assert _terms(["gd", "gd"]).applies_to_features == ["gd"]
        assert _terms(list(reversed(FEATURES))).applies_to_features == list(FEATURES)


class TestTheStoredScope:
    def test_features_and_named_items_are_unioned(self):
        five = next(i for i in items_for("interview") if i.quantity > 1)
        terms = OfferIn(
            code="MIX", label="mixed", kind=KIND_PERCENT, value=10,
            applies_to_features=["communication"], applies_to=[five.id],
        )
        assert set(terms.scope) == {five.id} | {i.id for i in items_for("communication")}

    def test_the_scope_is_sorted(self):
        # So two equivalent requests write the same list rather than the order the fields
        # happened to mention them in.
        terms = _terms(list(FEATURES))
        assert terms.scope == sorted(terms.scope)

    def test_both_empty_stays_empty(self):
        assert _terms([]).scope == []


class TestCoversIsTheOnePlaceScopeIsDecided:
    def test_an_empty_scope_covers_every_item(self):
        offer = Offer(code="X", label="x", kind=KIND_PERCENT, value=10, applies_to=[])
        assert all(offers.covers(offer, i) for i in ITEMS)

    def test_a_scoped_offer_covers_only_what_it_names(self):
        ids = [i.id for i in items_for("gd")]
        offer = Offer(code="X", label="x", kind=KIND_PERCENT, value=10, applies_to=ids)
        for item in ITEMS:
            assert offers.covers(offer, item) is (item.id in ids)


class TestThePricePreview:
    """
    What the admin is shown before the code exists. It must equal what creation would produce.
    """

    def _preview(self, terms: OfferTerms):
        # The endpoint takes no database and never persists — see its docstring — so it can be
        # called directly. `current_user` is only there to gate access.
        return asyncio.run(preview_offer(terms, current_user=None))  # type: ignore[arg-type]

    def test_a_row_per_catalogue_item(self):
        rows = self._preview(_terms([]))
        assert [r.item_id for r in rows] == [i.id for i in ITEMS]

    def test_an_unscoped_code_discounts_everything(self):
        rows = self._preview(_terms([], value=50))
        assert all(r.covered for r in rows)
        assert all(r.charged_paise < r.price_paise for r in rows)

    def test_an_uncovered_item_is_shown_at_its_full_price(self):
        rows = self._preview(_terms(["communication"], value=50))
        for r in rows:
            if r.feature == "communication":
                assert r.covered is True
                assert r.charged_paise < r.price_paise
            else:
                assert r.covered is False
                assert r.charged_paise == r.price_paise, (
                    "the point of showing uncovered rows is telling the admin what is NOT "
                    "discounted; a discounted figure there is the opposite of that"
                )

    def test_the_preview_matches_what_creation_would_store(self):
        # The invariant the shared OfferTerms exists to guarantee.
        terms = _terms(["interview"], value=25)
        created = OfferIn(
            code="SAME", label="same", kind=terms.kind, value=terms.value,
            applies_to_features=terms.applies_to_features, applies_to=terms.applies_to,
        )
        offer = Offer(
            code="SAME", label="same", kind=created.kind, value=created.value,
            applies_to=created.scope,
        )
        for row in self._preview(terms):
            item = next(i for i in ITEMS if i.id == row.item_id)
            covered = offers.covers(offer, item)
            assert row.covered is covered
            expected = offers.charge_for(offer, item) if covered else item.price_paise
            assert row.charged_paise == expected, (
                f"{row.item_id}: the preview said {row.charged_paise} and the created code "
                f"would charge {expected}"
            )

    def test_it_writes_nothing(self):
        import inspect

        src = inspect.getsource(preview_offer)
        # No session dependency at all, so nothing can be persisted even by accident.
        assert "db" not in inspect.signature(preview_offer).parameters
        assert "db.add" not in src
        assert "flush" not in src
        assert "commit" not in src
