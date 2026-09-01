"""
A placeholder grievance contact is treated as unset — tests/test_grievance_placeholder.py

WHY THIS EXISTS. `DPO_NAME` and `DPO_EMAIL` were set in production to the literal placeholder
text out of a setup guide:

    DPO_NAME="<a named human, not a role mailbox>"
    DPO_EMAIL="<their address>"

`/privacy` renders both verbatim under "Grievance Officer / Data Protection contact", and
`configured` was `bool(DPO_NAME and DPO_EMAIL)` — so a non-empty string of instructions
counted as an appointed officer. The page told every visitor that the grievance officer was
"<a named human, not a role mailbox>", and the legal disclosure asserted the §8(9) obligation
was discharged.

WHY THIS IS TREATED AS UNSET RATHER THAN AS A STARTUP FAILURE. Refusing to boot would take the
whole API down over legal copy, which is a worse outcome than the gap it is protecting against.
docs/COMPLIANCE.md already argues the right default: an obvious gap beats a plausible
fabrication, because a made-up name looks like the obligation was met. So a placeholder falls
back to exactly the state the setting had before anybody touched it — "no grievance officer has
been appointed yet" — which is true, and is what the page is designed to say.

Same principle as core/security.py refusing the literal `your-jwt-secret`, differing only in
severity: a bad JWT secret is a security hole and fails closed; a bad grievance contact is a
publication mistake and falls back.
"""

from __future__ import annotations

import pytest

from app.services.legal.disclosure import looks_like_placeholder


class TestPlaceholdersAreRecognised:
    @pytest.mark.parametrize(
        "value",
        [
            "<a named human, not a role mailbox>",
            "<their address>",
            "<your full name>",
            "<REDACTED>",
            "your-name-here",
            "YOUR_EMAIL",
            "changeme",
            "TODO",
            "xxx@example.com",
            "name@example.org",
            "",
            "   ",
        ],
    )
    def test_it_is_not_a_real_contact(self, value):
        assert looks_like_placeholder(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "Sparsh Agarwal",
            "privacy@interviewos.net.in",
            "grievance@interviewos.net.in",
            "R. Krishnan",
            "Aditi Rao",
        ],
    )
    def test_a_real_contact_is_left_alone(self, value):
        """
        THE VACUITY GUARD. A detector that flagged everything would permanently suppress the
        contact, which is the same failure as publishing a fake one — just quieter.
        """
        assert looks_like_placeholder(value) is False

    def test_none_is_a_placeholder(self):
        assert looks_like_placeholder(None) is True


@pytest.mark.asyncio
class TestTheDisclosureFallsBackRatherThanPublishingIt:
    async def test_a_placeholder_reads_as_no_officer_appointed(self, monkeypatch):
        from app.core.config import settings
        from app.services.legal import disclosure as mod

        monkeypatch.setattr(settings, "DPO_NAME", "<a named human, not a role mailbox>")
        monkeypatch.setattr(settings, "DPO_EMAIL", "<their address>")

        grievance = mod.disclosure()["grievance"]

        assert grievance["configured"] is False
        # And the placeholder text must not reach the page at all.
        assert not grievance["name"]
        assert not grievance["email"]

    async def test_a_real_contact_is_published(self, monkeypatch):
        from app.core.config import settings
        from app.services.legal import disclosure as mod

        monkeypatch.setattr(settings, "DPO_NAME", "Sparsh Agarwal")
        monkeypatch.setattr(settings, "DPO_EMAIL", "privacy@interviewos.net.in")

        grievance = mod.disclosure()["grievance"]

        assert grievance["configured"] is True
        assert grievance["name"] == "Sparsh Agarwal"
        assert grievance["email"] == "privacy@interviewos.net.in"

    async def test_one_half_missing_is_not_configured(self, monkeypatch):
        """A name with no address is not a contact anybody can reach."""
        from app.core.config import settings
        from app.services.legal import disclosure as mod

        monkeypatch.setattr(settings, "DPO_NAME", "Sparsh Agarwal")
        monkeypatch.setattr(settings, "DPO_EMAIL", "<their address>")

        assert mod.disclosure()["grievance"]["configured"] is False
