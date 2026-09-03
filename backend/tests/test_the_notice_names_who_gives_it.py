"""
The disclosure says who is giving it - tests/test_the_notice_names_who_gives_it.py

WHAT WAS MISSING. `disclosure()` is the DPDP §5 notice: it lists what is collected, which
categories of processor see it, which countries it reaches, how long it is kept, and what
rights attach. It did all of that without naming the party responsible for any of it.

A §5 notice is issued BY a Data Fiduciary. A notice that does not identify one leaves the
Data Principal unable to act on it - you cannot exercise a right of erasure, or raise a
grievance, against a party you cannot name. The same fact is what the Consumer Protection
(E-Commerce) Rules 2020 require an e-commerce entity to display, and what a payment
gateway's merchant terms assume is visible to the payer.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.legal.disclosure import disclosure


class TestTheFiduciaryIsIdentified:
    def test_the_payload_carries_a_fiduciary_block(self) -> None:
        assert "fiduciary" in disclosure()

    @pytest.mark.parametrize("field", ["name", "product", "role"])
    def test_every_field_is_present_and_non_empty(self, field: str) -> None:
        value = disclosure()["fiduciary"][field]
        assert isinstance(value, str)
        assert value.strip(), f"{field} is blank, so the notice is issued by nobody"

    def test_the_name_is_the_configured_operator(self) -> None:
        assert disclosure()["fiduciary"]["name"] == settings.OPERATOR_LEGAL_NAME

    def test_it_is_not_a_placeholder(self) -> None:
        """
        `looks_like_placeholder` exists because DPO_NAME was once set in production to the
        literal `<their address>`. The operator name is shipped with a default rather than
        left empty, so the failure mode here is a template string, not a blank.
        """
        from app.services.legal.disclosure import looks_like_placeholder

        assert not looks_like_placeholder(disclosure()["fiduciary"]["name"])


class TestItIdentifiesSomebodyRatherThanRestatingTheProduct:
    def test_the_operator_is_not_the_product(self) -> None:
        """
        THE VACUITY GUARD. Defaulting `OPERATOR_LEGAL_NAME` to `APP_NAME` would satisfy
        every assertion above while identifying nobody: the product is what is sold, the
        company is who sells it, and a notice needs the second. This is the same guard the
        frontend applies to `BRAND.company` against `BRAND.name`.
        """
        assert settings.OPERATOR_LEGAL_NAME != settings.APP_NAME

    def test_the_block_distinguishes_the_two(self) -> None:
        block = disclosure()["fiduciary"]
        assert block["name"] != block["product"]

    def test_the_role_says_what_the_operator_is(self) -> None:
        # The word carries the statutory meaning; "operator" or "company" would not.
        assert "Fiduciary" in disclosure()["fiduciary"]["role"]


class TestTheRestOfTheNoticeIsUnchanged:
    @pytest.mark.parametrize(
        "key", ["notice_version", "draft", "processors", "leaves_india", "grievance", "rights"]
    )
    def test_adding_the_fiduciary_did_not_displace_anything(self, key: str) -> None:
        assert key in disclosure()

    def test_the_fiduciary_is_not_mistaken_for_a_processor(self) -> None:
        """
        The operator holds the data; the processors are third parties acting on its
        instructions. Listing the operator among them would misdescribe both.
        """
        name = disclosure()["fiduciary"]["name"]
        for processor in disclosure()["processors"]:
            assert name not in processor.values()
