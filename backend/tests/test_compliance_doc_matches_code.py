"""
docs/COMPLIANCE.md against the code it describes.

A compliance note is read by people deciding what is safe to do, and it is the kind of
document that goes stale silently — nothing fails when a paragraph stops being true.
Two of its claims had: it said the product had **no age gate** months after one was
built, and it left the DPDP §16 deadline open-ended after the Rules were notified.

Only claims that can be checked mechanically are pinned here. The judgement in that
document — whether self-declaration discharges §9, whether to keep sending resumes to
China — is a lawyer's, and a test asserting on it would be pretending otherwise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMPLIANCE = REPO / "docs" / "COMPLIANCE.md"
LEGAL_API = REPO / "backend" / "app" / "api" / "v1" / "legal.py"
REGISTER_PAGE = REPO / "frontend" / "src" / "app" / "(auth)" / "register" / "page.tsx"


@pytest.fixture(scope="module")
def doc() -> str:
    return COMPLIANCE.read_text(encoding="utf-8")


class TestTheAgeGateClaim:
    """The gate is real: a required, non-defaulting field, an unticked box, and a
    refusal to change it afterwards."""

    def test_the_gate_exists_in_the_api(self):
        source = LEGAL_API.read_text(encoding="utf-8")
        # Required and non-defaulting. `age_18_plus: bool = False` would be a
        # pre-ticked box in a different costume.
        assert re.search(r"^\s*age_18_plus:\s*bool\s*$", source, re.MULTILINE), (
            "age_18_plus is no longer a required, non-defaulting field"
        )

    def test_the_gate_exists_on_the_signup_screen(self):
        assert "I am 18 or older" in REGISTER_PAGE.read_text(encoding="utf-8")

    def test_it_cannot_be_flipped_later(self):
        # Every measurement already taken would survive the flip.
        source = LEGAL_API.read_text(encoding="utf-8")
        assert "PURPOSE_AGE_18_PLUS" in source
        assert "cannot be changed here" in source

    def test_the_document_does_not_still_say_there_is_none(self, doc):
        stale = [
            "no date of birth and has no age gate",
            "has no way to know which it is talking to",
            "Doing neither is the current position and is the riskiest one",
        ]
        found = [phrase for phrase in stale if phrase in doc]
        assert not found, (
            f"COMPLIANCE.md still claims there is no age gate: {found}. "
            "One exists — see api/v1/legal.py."
        )

    def test_the_document_names_the_field(self, doc):
        # So the next reader can check the claim in one grep rather than trusting it.
        assert "age_18_plus" in doc


class TestTheCrossBorderDeadline:
    """DPDP Rules 2025 were notified 13 November 2025; Rule 15, which operationalises
    §16, comes into force eighteen months later."""

    def test_the_rule_15_date_is_stated(self, doc):
        assert "13 May 2027" in doc, (
            "COMPLIANCE.md no longer states when Rule 15 comes into force"
        )

    def test_the_notification_date_is_stated(self, doc):
        assert "13 November 2025" in doc

    def test_it_still_says_the_list_is_not_notified(self, doc):
        # The deadline being known does not mean the restricted-country list exists.
        # If that changes, this is the line that has to change with it.
        assert "not been notified" in doc or "not notified" in doc

    def test_it_is_no_longer_vague_about_the_deadline(self, doc):
        section = doc[doc.index("### §16") :]
        # `"---"` alone matches the `|---|` inside the destinations table; the section
        # break is a horizontal rule on its own line.
        section = section[: section.index("\n---\n")]
        assert "13 May 2027" in section, (
            "the §16 section itself does not carry the date; a reader of that section "
            "alone still gets the vague version"
        )
