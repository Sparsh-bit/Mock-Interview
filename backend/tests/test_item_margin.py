"""
The margin report is arithmetic somebody will price against — tests/test_item_margin.py

`scripts/item_margin.py` produces the number that answers "does ₹49 actually cover a mock
interview once speech is paid for". Nothing enforces it at runtime, so the only thing
standing between a wrong constant and a pricing decision made on it is this file.

FOUR FAILURE MODES, and they are not equally likely:

  1. A NEW AI CALL SITE APPEARS AND ITS SPEND VANISHES. `_AI_FEATURE_TO_BILLABLE` maps the
     `context=` label to a billable feature. A label missing from it is not an error at
     runtime — the script prints a warning that a reader may not read, and that feature's
     cost is in NO margin line. This is the one that actually happens, because adding an AI
     call is routine and nobody adding one thinks about a report script. Pinned twice
     below: against the admin endpoint's label table, and against every `context="..."` in
     the source.

  2. THE SPEECH MODEL LOSES A FEATURE. A new billable feature with no `SpeechProfile`
     raises a KeyError inside the report rather than quietly costing zero, but only if
     something exercises it.

  3. THE ARITHMETIC DRIFTS. Margin is price - payment fee - AI - speech, per vendor, times
     quantity for a bundle. Checked against figures computed by hand here, not by
     re-running the function's own expression.

  4. THE REPORT CHANGES A PRICE. It must not. The brief for this script was explicit that
     pricing is a product decision; a report that mutates `plans.ITEMS` on its way past
     would be the worst possible bug in it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.v1.ai_usage import FEATURE_LABELS as LEDGER_LABELS
from app.services.billing.plans import FEATURES, ITEMS, get_item
from scripts.item_margin import (
    _AI_FEATURE_TO_BILLABLE,
    _MEASURED_AI_COST_PER_ITEM,
    SPEECH,
    VendorScenario,
    feature_costs,
    item_margins,
    vendor_scenarios,
)

_APP = Path(__file__).resolve().parents[1] / "app"

#: Two vendors an order of magnitude apart, so a bug that silently uses one price for both
#: cannot pass. Deliberately NOT the live constants — those move, and a test that moves with
#: them tests nothing about the arithmetic.
_FISH = VendorScenario(name="cheap", usd_per_char=10.0 / 1_000_000, detail="test")
_PREMIUM = VendorScenario(name="premium", usd_per_char=100.0 / 1_000_000, detail="test")
_SCENARIOS = [_FISH, _PREMIUM]


class TestEveryAiCallSiteIsAccountedFor:
    """
    No AI spend may fall outside the report.

    Both directions matter. A label the script does not know about disappears from the cost
    lines; a label the script knows about that no longer exists is dead weight that hides a
    rename. The first is a wrong number, so it is a hard failure; the second is only allowed
    for entries the file explicitly documents as historical.
    """

    def test_every_ledger_label_the_admin_view_knows_about_is_mapped(self):
        missing = sorted(set(LEDGER_LABELS) - set(_AI_FEATURE_TO_BILLABLE))
        assert not missing, (
            f"ai_usage.FEATURE_LABELS has {missing} and scripts/item_margin.py does not. "
            "Their spend would be reported against no catalogue item."
        )

    def test_every_context_label_in_the_source_is_mapped(self):
        """
        The stronger pin: the SOURCE, not a second table that can itself go stale.

        `ai_usage.FEATURE_LABELS` is hand-maintained, so a new call site could be missing
        from both it and the script and the test above would still pass. Every billed call
        goes through `generate_structured(context=...)`, so scanning for that literal finds
        the call sites themselves.
        """
        found = set()
        for path in _APP.rglob("*.py"):
            found |= set(re.findall(r'context="([a-z0-9_]+)"', path.read_text()))
        assert found, "found no context= labels at all — the scan is broken, not the map"

        missing = sorted(found - set(_AI_FEATURE_TO_BILLABLE))
        assert not missing, (
            f"these call sites bill AI and are not in _AI_FEATURE_TO_BILLABLE: {missing}"
        )

    def test_labels_the_source_no_longer_produces_are_documented_as_historical(self):
        """
        A mapping entry with no call site is either a rename's history or a leftover.

        The ledger is append-only, so old labels legitimately survive in the data — but each
        one must be a deliberate entry under the LEGACY heading rather than a line somebody
        forgot to delete, or the map becomes impossible to reason about.
        """
        source = (
            Path(__file__).resolve().parents[1] / "scripts" / "item_margin.py"
        ).read_text()
        legacy_block = source.split("LEGACY LABELS", 1)
        assert len(legacy_block) == 2, "the LEGACY LABELS section has been removed"

        live = set()
        for path in _APP.rglob("*.py"):
            live |= set(re.findall(r'context="([a-z0-9_]+)"', path.read_text()))

        for label in set(_AI_FEATURE_TO_BILLABLE) - live:
            assert f'"{label}"' in legacy_block[1], (
                f"{label!r} is mapped but no call site produces it, and it is not under "
                "the LEGACY LABELS heading. Either it is a rename's history (document it "
                "there) or the entry is dead."
            )

    def test_unbillable_features_are_marked_none_not_dropped(self):
        """
        Free features cost real money and must be visible, not absent.

        `None` means "no purchase pays for this", which the report totals as acquisition
        cost. Deleting the entry instead would put the same spend in the unmapped warning,
        which reads like a bug rather than like a business fact.
        """
        for free in ("quiz_generation", "resume_analysis_skills", "question_bank"):
            assert free in _AI_FEATURE_TO_BILLABLE
            assert _AI_FEATURE_TO_BILLABLE[free] is None

    def test_every_mapped_billable_target_is_a_real_feature(self):
        targets = {v for v in _AI_FEATURE_TO_BILLABLE.values() if v is not None}
        assert targets <= set(FEATURES), f"maps to features that do not exist: {targets}"


class TestEveryBillableFeatureCanBePriced:
    """A feature with no speech profile or no fallback cost cannot appear in the report."""

    @pytest.mark.parametrize("feature", FEATURES)
    def test_it_has_a_speech_profile(self, feature):
        assert feature in SPEECH

    @pytest.mark.parametrize("feature", FEATURES)
    def test_it_has_a_measured_fallback(self, feature):
        assert _MEASURED_AI_COST_PER_ITEM[feature] > 0

    @pytest.mark.parametrize("feature", FEATURES)
    def test_at_least_one_ai_call_site_bills_to_it(self, feature):
        assert feature in set(_AI_FEATURE_TO_BILLABLE.values()), (
            f"{feature} is sold but no AI call site is attributed to it — its AI cost "
            "would read as zero and its margin as pure profit"
        )


class TestTheSpeechModel:
    """
    Shared audio is cached; per-candidate audio never is. The two must not be conflated.
    """

    def test_a_gd_round_has_no_shared_audio(self):
        """
        Every GD contribution is unique text, so the audio cache can never hit — config.py
        says so where it explains TTS_CACHE_TTL_SECONDS. Cold and steady cost are therefore
        the same number, and a model that discounts GD speech is wrong about the largest
        speech bill in the product.
        """
        gd = SPEECH["gd"]
        assert gd.shared_chars == 0
        assert gd.cold_chars == gd.steady_chars == gd.unique_chars

    def test_an_interview_is_mostly_shared_audio_and_gets_much_cheaper_warm(self):
        interview = SPEECH["interview"]
        assert interview.shared_chars > interview.unique_chars
        assert interview.steady_chars < interview.cold_chars

    def test_steady_state_never_exceeds_cold(self):
        for feature, profile in SPEECH.items():
            assert profile.steady_chars <= profile.cold_chars, feature

    def test_the_gd_round_matches_the_character_count_base_py_prices_from(self):
        """
        services/tts/base.py builds its whole vendor cost table on "~7,800 characters a
        round". If this model disagreed with that figure, two files in the repository would
        be quoting different speech bills for the same round.
        """
        assert SPEECH["gd"].cold_chars == 7_800


class TestCostPerItem:
    def test_ledger_spend_is_divided_by_items_actually_delivered(self):
        costs = feature_costs(
            {"interview": 3.0, "gd": 1.0}, {"interview": 10, "gd": 4}, _SCENARIOS
        )
        assert costs["interview"].ai_cost_usd == pytest.approx(0.3)
        assert costs["interview"].ai_source == "ledger"
        assert costs["gd"].ai_cost_usd == pytest.approx(0.25)

    def test_no_items_falls_back_to_the_measured_figure_and_says_so(self):
        """
        The alternative is a divide-by-zero guard returning 0.0, which renders as a 100%
        margin — a report that looks healthy precisely when it has no data.
        """
        costs = feature_costs({}, {}, _SCENARIOS)
        for feature in FEATURES:
            assert costs[feature].ai_source == "measured-fallback"
            assert costs[feature].ai_cost_usd == _MEASURED_AI_COST_PER_ITEM[feature]

    def test_ai_spend_with_no_delivered_items_still_falls_back_rather_than_dividing(self):
        """
        Spend without a consume row is real: an interview that failed after the AI calls and
        rolled the charge back leaves exactly this. Dividing by zero items must not happen,
        and silently attributing that spend to no item must not either — it stays in
        `ai_total_usd` where a reader can see it.
        """
        costs = feature_costs({"gd": 9.99}, {"gd": 0}, _SCENARIOS)
        assert costs["gd"].ai_source == "measured-fallback"
        assert costs["gd"].ai_total_usd == pytest.approx(9.99)

    def test_speech_is_priced_per_vendor_at_that_vendors_rate(self):
        costs = feature_costs({}, {}, _SCENARIOS)
        gd = costs["gd"]
        assert gd.tts_cost_usd["cheap"] == pytest.approx(7_800 * 10.0 / 1_000_000)
        assert gd.tts_cost_usd["premium"] == pytest.approx(7_800 * 100.0 / 1_000_000)
        # A tenfold price difference must show up as a tenfold cost difference.
        assert gd.tts_cost_usd["premium"] == pytest.approx(
            gd.tts_cost_usd["cheap"] * 10
        )


class TestMarginArithmetic:
    def test_margin_is_price_less_fee_less_ai_less_speech(self):
        costs = feature_costs({}, {}, _SCENARIOS)
        rows = {r.item_id: r for r in item_margins(
            costs, _SCENARIOS, payment_fee_rate=0.02, inr_per_usd=100.0
        )}

        row = rows["gd_1"]
        # ₹39 at ₹100/USD is $0.39; 2% of that is $0.0078; AI is the measured $0.1423;
        # speech is 7,800 chars at $10/M = $0.078.
        assert row.price_usd == pytest.approx(0.39)
        assert row.payment_fee_usd == pytest.approx(0.0078)
        assert row.ai_cost_usd == pytest.approx(0.1423)
        assert row.tts_cost_usd["cheap"] == pytest.approx(0.078)
        assert row.margin_usd["cheap"] == pytest.approx(0.39 - 0.0078 - 0.1423 - 0.078)

    def test_a_bundle_multiplies_both_costs_by_its_quantity(self):
        """
        A five-pack costs five interviews to deliver. Forgetting the quantity would make
        every bundle look like the product's most profitable item, which is exactly
        backwards — bundles are discounted.
        """
        costs = feature_costs({}, {}, _SCENARIOS)
        rows = {r.item_id: r for r in item_margins(costs, _SCENARIOS)}
        one, five = rows["interview_1"], rows["interview_5"]
        assert five.ai_cost_usd == pytest.approx(one.ai_cost_usd * 5)
        assert five.tts_cost_usd["cheap"] == pytest.approx(one.tts_cost_usd["cheap"] * 5)
        # And the discount is real: five cost less than five singles.
        assert five.price_inr < one.price_inr * 5

    def test_the_expensive_vendor_never_shows_a_better_margin(self):
        costs = feature_costs({}, {}, _SCENARIOS)
        for row in item_margins(costs, _SCENARIOS):
            assert row.margin_pct["premium"] <= row.margin_pct["cheap"], row.item_id

    def test_the_ai_only_figure_is_always_the_optimistic_one(self):
        """
        `ai_only_margin_pct` reproduces what plans.py documents. It omits speech and the
        payment fee, so it must be the highest number on every row — the gap is the point of
        the whole report.
        """
        costs = feature_costs({}, {}, _SCENARIOS)
        for row in item_margins(costs, _SCENARIOS):
            for vendor in ("cheap", "premium"):
                assert row.ai_only_margin_pct >= row.margin_pct[vendor], row.item_id

    def test_a_margin_can_go_negative_rather_than_being_clamped(self):
        """
        The report's job is to say when an item loses money. A max(0, ...) anywhere in this
        arithmetic would hide the only finding worth acting on.
        """
        ruinous = [VendorScenario(name="ruinous", usd_per_char=0.01, detail="test")]
        costs = feature_costs({}, {}, ruinous)
        rows = item_margins(costs, ruinous)
        assert any(r.margin_usd["ruinous"] < 0 for r in rows)
        assert any(r.margin_pct["ruinous"] < 0 for r in rows)

    def test_every_catalogue_item_appears_exactly_once(self):
        costs = feature_costs({}, {}, _SCENARIOS)
        ids = [r.item_id for r in item_margins(costs, _SCENARIOS)]
        assert sorted(ids) == sorted(i.id for i in ITEMS)
        assert len(ids) == len(set(ids))


class TestTheReportChangesNoPrice:
    """
    Explicit in the brief: this is a report, not a pricing decision.
    """

    def test_running_the_report_leaves_every_catalogue_price_untouched(self):
        before = {i.id: i.price_paise for i in ITEMS}
        costs = feature_costs({"interview": 99.0}, {"interview": 1}, _SCENARIOS)
        item_margins(costs, _SCENARIOS, payment_fee_rate=0.5, inr_per_usd=1.0)
        assert {i.id: i.price_paise for i in ITEMS} == before
        # And the authoritative lookup still returns the same numbers.
        assert get_item("interview_1").price_paise == before["interview_1"]

    def test_the_script_never_imports_anything_that_writes(self):
        """
        A report that can UPDATE is a report that will, eventually, by accident. The whole
        file is read-only by construction; this pins that nothing in it writes to the
        database or mutates settings.
        """
        source = (
            Path(__file__).resolve().parents[1] / "scripts" / "item_margin.py"
        ).read_text()
        for forbidden in ("db.add(", "db.commit(", "session.add(", ".update(", "DELETE"):
            assert forbidden not in source, f"the margin report contains {forbidden!r}"


class TestVendorScenariosComeFromTheVendorModules:
    """
    Retyped prices go stale silently. These must be the same constants the live providers
    charge against, so a vendor price edit moves the report with it.
    """

    def test_both_vendors_are_priced_and_elevenlabs_is_the_expensive_one(self):
        scenarios = {s.name: s for s in vendor_scenarios()}
        assert set(scenarios) == {"fish", "elevenlabs"}
        assert scenarios["fish"].usd_per_char > 0
        assert scenarios["elevenlabs"].usd_per_char > scenarios["fish"].usd_per_char

    def test_fish_is_priced_at_the_constant_fish_py_bills_from(self):
        from app.services.tts.fish import _USD_PER_CHAR

        fish = next(s for s in vendor_scenarios() if s.name == "fish")
        assert fish.usd_per_char == _USD_PER_CHAR

    def test_elevenlabs_is_priced_at_the_configured_model_and_tier(self):
        """
        The tier alone varies the per-character price nearly twofold (see
        `_USD_PER_CREDIT_BY_TIER`), so quoting a fixed one would be confidently wrong on any
        deployment that is not on Creator.
        """
        from app.core.config import settings
        from app.services.tts.elevenlabs import (
            _CREDITS_PER_CHAR,
            _USD_PER_CREDIT_BY_TIER,
        )

        expected = _CREDITS_PER_CHAR.get(settings.ELEVENLABS_MODEL, 1.0) * (
            _USD_PER_CREDIT_BY_TIER.get(
                (settings.ELEVENLABS_TIER or "creator").lower(),
                _USD_PER_CREDIT_BY_TIER["creator"],
            )
        )
        eleven = next(s for s in vendor_scenarios() if s.name == "elevenlabs")
        assert eleven.usd_per_char == pytest.approx(expected)
