"""
The disclosure describes the processing without naming the vendors.

WHAT CHANGED AND WHY. `/api/v1/legal/disclosure` published each processor's trading name —
"Anthropic", "ZhipuAI (GLM)", "Fish Audio", "Judge0", "Supabase", "Razorpay". That is a
readable inventory of the stack, and the product owner does not want it public. Naming which
vendor performs a function is a commercial decision, not a legal obligation.

WHAT IS DELIBERATELY KEPT, AND THIS IS THE POINT OF THE FILE. DPDP §16 concerns transfers
OUTSIDE INDIA, and §5 concerns the PURPOSE. Neither depends on the vendor's name. So the
disclosure still says, for every processor, the COUNTRY the processing happens in, WHAT is
sent, and WHY — it simply says "AI interview services" where it used to say "Anthropic".

A candidate can therefore still learn that their resume text leaves India for the United
States and China and what it is used for, which is the substance of the obligation. What they
can no longer do is enumerate the suppliers.

WHAT THIS IS NOT. It is not a way to avoid disclosure: nothing about the data, the countries,
the purposes or the retention changes. Removing the countries WOULD be a disclosure gap, and a
test below fails if anybody tries it.

The catalogue keeps `name` internally — it is how the entries are documented and reasoned
about in code — but `name` is never part of the public payload.
"""

from __future__ import annotations

from app.services.legal.disclosure import _CATALOGUE, active_processors, disclosure

VENDOR_NAMES = [
    "Anthropic",
    "ZhipuAI",
    "GLM",
    "NVIDIA",
    "ElevenLabs",
    "Fish Audio",
    "Judge0",
    "Piston",
    "Supabase",
    "Razorpay",
]


class TestTheVendorNamesAreNotPublished:
    def test_no_trading_name_appears_anywhere_in_the_payload(self):
        import json

        payload = json.dumps(disclosure())
        leaked = [v for v in VENDOR_NAMES if v.lower() in payload.lower()]
        assert leaked == [], f"the disclosure still names suppliers: {leaked}"

    def test_no_processor_entry_carries_a_name_field(self):
        for p in disclosure()["processors"]:
            assert "name" not in p, f"processor entry still has a name field: {p}"

    def test_every_entry_carries_a_generic_category_instead(self):
        for p in disclosure()["processors"]:
            assert p.get("category"), f"processor entry has no category: {p}"
            assert p["category"] not in VENDOR_NAMES


class TestTheObligationIsStillDischarged:
    def test_every_processor_still_names_its_country(self):
        """
        §16 is about transfers outside India. Dropping the vendor name is a commercial choice;
        dropping the COUNTRY would be a disclosure gap, and this is what stops that happening
        by accident later.
        """
        for p in disclosure()["processors"]:
            assert p.get("country"), f"processor entry has no country: {p}"

    def test_every_processor_still_says_what_is_sent_and_why(self):
        for p in disclosure()["processors"]:
            assert p.get("receives")
            assert p.get("purpose")

    def test_the_cross_border_flag_still_works(self):
        # A candidate must still be able to learn that their data leaves the country.
        assert "leaves_india" in disclosure()

    def test_the_draft_flag_survives(self):
        # This text has still not been through a lawyer and must keep saying so.
        assert disclosure()["draft"] is True


class TestTheCatalogueIsStillConfigDerived:
    """
    The property the previous tests protected, restated without depending on trading names.
    A hardcoded list drifted once - it called ZhipuAI the standby provider while AI_PROVIDER
    defaulted to glm, so every resume went to China first and the disclosure said otherwise.
    """

    def test_switching_the_ai_provider_changes_the_active_set(self, monkeypatch):
        from app.core import config as config_mod

        monkeypatch.setattr(config_mod.settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(config_mod.settings, "AI_FALLBACK_PROVIDER", "")
        keys = {p.key for p in active_processors()}
        assert "glm" in keys
        assert "anthropic" not in keys

        monkeypatch.setattr(config_mod.settings, "AI_PROVIDER", "anthropic")
        keys = {p.key for p in active_processors()}
        assert "anthropic" in keys

    def test_every_catalogue_entry_has_a_category(self):
        missing = [k for k, p in _CATALOGUE.items() if not getattr(p, "category", "")]
        assert missing == [], f"catalogue entries without a category: {missing}"

    def test_categories_do_not_accidentally_identify_one_vendor(self):
        """
        THE VACUITY GUARD. A category like "Anthropic Claude API" would satisfy every test
        above while publishing exactly what was meant to be withheld.
        """
        for key, p in _CATALOGUE.items():
            for vendor in VENDOR_NAMES:
                assert vendor.lower() not in p.category.lower(), f"{key}: {p.category}"
