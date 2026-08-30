"""
Where the data actually is — tests/test_data_residency.py

WHY THIS IS A TEST AND NOT ONLY A DOCUMENT. `docs/DATA-RESIDENCY.md` records the
determination: the hosting region **could not be established from this repository**. That is
the finding, and it is a finding with a shelf life — the moment somebody opens the Supabase
dashboard and reads the region, the answer exists and should stop being a mystery in three
different files.

So the region is a SETTING. Unset, the privacy notice says in as many words that the region
has not been confirmed, which is the honest position and is visible to the candidate whose
resume it is. Set, the same notice names it. The mechanism is deliberately the one
`services/legal/disclosure.py` already uses for processors: the notice is DERIVED from the
running configuration rather than written out, because a notice naming the wrong country is
worse than no notice — it is a statement the candidate relied on.

WHAT THIS FILE CANNOT DO. It cannot tell you where the data is. Nothing in a repository can.
It can make sure that the answer, once known, is stated in one place and reaches the person
it is about.
"""

from __future__ import annotations

import pathlib

from app.core.config import settings

_DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "DATA-RESIDENCY.md"


class TestTheRegionIsConfigurableRatherThanAComment:
    def test_the_setting_exists(self):
        assert hasattr(settings, "DATA_REGION")

    def test_it_is_empty_by_default(self):
        """
        UNSET IS THE HONEST DEFAULT. A default of "India" would make every deployment claim
        a residency nobody checked, which is the failure mode `CLAUDE.md` records for the
        stale trial-allowance note: a plausible fabrication is worse than an obvious gap.
        """
        from app.core.config import Settings

        assert Settings.model_fields["DATA_REGION"].default == ""

    def test_an_unset_region_makes_the_notice_say_so(self, monkeypatch):
        from app.services.legal.disclosure import disclosure

        monkeypatch.setattr(settings, "DATA_REGION", "")
        supabase = next(
            p for p in disclosure()["processors"] if p["name"] == "Supabase"
        )

        assert "not confirmed" in supabase["country"].lower()

    def test_a_configured_region_reaches_the_notice(self, monkeypatch):
        from app.services.legal.disclosure import disclosure

        monkeypatch.setattr(settings, "DATA_REGION", "Singapore (ap-southeast-1)")
        supabase = next(
            p for p in disclosure()["processors"] if p["name"] == "Supabase"
        )

        assert "Singapore" in supabase["country"]

    def test_a_region_outside_india_still_counts_as_leaving_india(self, monkeypatch):
        """
        `leaves_india()` gates the cross-border consent screen. A deployment hosted outside
        India must not be able to configure its way out of showing it.
        """
        from app.services.legal.disclosure import leaves_india

        monkeypatch.setattr(settings, "DATA_REGION", "Singapore")
        assert leaves_india() is True

    def test_it_is_documented_as_a_deployment_setting(self):
        """A setting nobody knows to set is a setting nobody sets."""
        deploy = (_DOC.parent / "DEPLOY.md").read_text(encoding="utf-8")
        assert "DATA_REGION" in deploy


class TestTheDeterminationIsRecorded:
    def test_the_residency_note_exists(self):
        assert _DOC.exists(), "the data-residency determination is not written down"

    def test_it_makes_an_explicit_call_rather_than_implying_one(self):
        """
        A verification that reads as prose and never says the word is a verification the
        reader has to interpret. Case-insensitive on the verdict because the note writes it
        as COMPLIANT / NON-COMPLIANT for emphasis.
        """
        text = _DOC.read_text(encoding="utf-8")
        for required in ("CERT-In", "RBI", "180"):
            assert required in text, f"the note never mentions {required}"
        lowered = text.lower()
        assert "non-compliant" in lowered, "no explicit non-compliant call anywhere"
        assert "compliant" in lowered

    def test_it_cites_its_sources(self):
        """
        A regulatory claim without a source is a regulatory claim nobody can re-check, and
        these move. The point of citing them is that the next reader re-reads the direction
        rather than this file.
        """
        text = _DOC.read_text(encoding="utf-8")
        assert "cert-in.org.in" in text or "certin" in text.lower()
        assert "rbi.org.in" in text.lower() or "Reserve Bank" in text

    def test_it_does_not_claim_a_region_it_could_not_verify(self):
        """
        THE ONE THING THIS NOTE MUST NOT DO. The task it answers is a verification task, and
        a verification that guesses is worse than none. `render.yaml` says `singapore` and
        marks itself unconfirmed; DNS says nothing (a control against a service name that
        does not exist resolves to the same Render edge). So the note must say "not
        determined", and if somebody later edits it to assert a region, they must also
        record how they checked.
        """
        text = _DOC.read_text(encoding="utf-8").lower()
        if "confirmed region" in text or "verified region" in text:
            assert "dashboard" in text or "how this was checked" in text
        assert "could not be determined" in text or "not determined" in text
