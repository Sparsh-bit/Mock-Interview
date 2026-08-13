"""
Catching a shared account without banning honest ones — tests/test_sharing_detection.py

A false positive here locks a paying customer out mid-session, and the population it hits
hardest is the honest one: Indian campus students on phones, moving between mobile data and
college wi-fi, frequently behind carrier-grade NAT and campus NAT at once. A naive
"two IPs, ban" detector would suspend a large share of legitimate users on day one.

So most of what follows tests the DAMPENERS rather than the detection. The detection is
easy; not destroying real accounts with it is the hard part, and every one of these
assertions corresponds to a specific class of false positive.
"""

from __future__ import annotations

from app.services.security.sharing import (
    _OVERLAP_SECONDS,
    _STRIKES_BEFORE_BAN,
    agent_hash,
    client_ip,
    ip_prefix,
)


class TestTheAddressIsReducedToItsNetwork:
    def test_ipv4_collapses_to_a_24(self):
        # THE BIGGEST SOURCE OF FALSE POSITIVES. A phone moving between cell towers changes
        # address constantly inside its carrier's range; the range is the network, and the
        # network is what "where are you" has to mean here.
        assert ip_prefix("203.0.113.7") == ip_prefix("203.0.113.200")
        assert ip_prefix("203.0.113.7") == "203.0.113.0/24"

    def test_a_genuinely_different_network_is_different(self):
        assert ip_prefix("203.0.113.7") != ip_prefix("198.51.100.7")

    def test_ipv6_collapses_to_a_48(self):
        a = ip_prefix("2001:db8:1234:5678::1")
        b = ip_prefix("2001:db8:1234:9999::abcd")
        assert a == b == "2001:db8:1234::/48"

    def test_an_unparseable_address_yields_nothing_rather_than_a_shared_bucket(self):
        # Returning a constant like "unknown" would put every unparseable request in one
        # bucket, so two strangers behind a broken proxy would look like one shared account
        # and ban each other.
        for bad in ("", None, "not-an-ip", "999.999.999.999", "<script>"):
            assert ip_prefix(bad) == ""


class TestTheUserAgentIsNeverStoredRaw:
    def test_it_is_hashed(self):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
        h = agent_hash(ua)
        assert ua not in h
        assert len(h) == 32

    def test_the_same_browser_hashes_the_same(self):
        assert agent_hash("Firefox/121.0") == agent_hash("Firefox/121.0")
        assert agent_hash("Firefox/121.0") != agent_hash("Chrome/120.0")

    def test_a_missing_agent_does_not_crash(self):
        assert agent_hash(None)


class TestTheClientAddress:
    def test_the_leftmost_forwarded_entry_is_the_client(self):
        # Everything after the first entry is a proxy hop.
        assert client_ip({"x-forwarded-for": "203.0.113.7, 10.0.0.1, 10.0.0.2"}, None) == "203.0.113.7"

    def test_it_falls_back_through_real_ip_then_the_socket(self):
        assert client_ip({"x-real-ip": "203.0.113.9"}, None) == "203.0.113.9"
        assert client_ip({}, "203.0.113.11") == "203.0.113.11"

    def test_nothing_at_all_is_empty_rather_than_a_guess(self):
        # Which ip_prefix turns into "", which skips detection — the safe direction.
        assert client_ip({}, None) == ""
        assert ip_prefix(client_ip({}, None)) == ""


class TestTheDampenersAreSetWhereTheyWereArguedFor:
    """
    These constants ARE the safety margin. Asserted so that tightening one — which is the
    natural instinct after seeing a sharer get away with something — is a deliberate act
    with the reasoning in front of you rather than a one-character edit.
    """

    def test_one_overlap_is_never_enough(self):
        # A VPN reconnect, a dual-stack IPv4/IPv6 flip, or a tab left open on another
        # network each produce exactly one clean overlap. Sharing produces them repeatedly.
        assert _STRIKES_BEFORE_BAN >= 3

    def test_the_overlap_window_is_short_enough_to_mean_simultaneous(self):
        # Long windows turn "used it at lunch, friend used it at dinner" into concurrency.
        assert _OVERLAP_SECONDS <= 300

    def test_the_window_is_long_enough_to_survive_a_page_load(self):
        # Too short and two requests from one device seconds apart stop overlapping at all,
        # which would make the detector miss real sharing rather than avoid false positives.
        assert _OVERLAP_SECONDS >= 60


class TestThereIsAlwaysARouteOut:
    def test_the_balance_and_appeal_routes_are_exempt_from_the_ban(self):
        """
        An automated ban with no route out is indefensible. These two ARE the route: the
        balance endpoint is how the client learns it is banned, and the appeal is the
        request for review. If either is blocked, a wrongly-banned paying user has nothing
        but a support email.
        """
        from app.core.security import _is_ban_exempt

        assert _is_ban_exempt("/api/v1/billing/me")
        assert _is_ban_exempt("/api/v1/billing/appeal")
        # And the gate is real for everything else.
        assert not _is_ban_exempt("/api/v1/interview/plan")
        assert not _is_ban_exempt("/api/v1/gd/turn")

    def test_only_an_admin_can_lift_a_ban(self):
        import pathlib

        api = pathlib.Path(__file__).resolve().parent.parent / "app/api/v1"
        # The appeal records a request and must not clear the flag itself — a ban that
        # lifts on request is decorative.
        appeal = (api / "billing.py").read_text()
        block = appeal[appeal.index("async def appeal") :]
        assert "is_banned = False" not in block

        # The unban lives behind AdminUser.
        admin = (api / "admin.py").read_text()
        unban = admin[admin.index("async def unban_user") :]
        assert "current_user: AdminUser" in admin[admin.index("async def unban_user") - 500 :]
        assert "is_banned = False" in unban

    def test_unbanning_clears_the_strike_history(self):
        # Strikes live in Redis for a week. Unbanning without clearing them leaves the
        # account one overlap from a re-ban on evidence already forgiven, which looks
        # exactly like the unban button not working.
        import pathlib

        admin = (
            pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/admin.py"
        ).read_text()
        assert "clear_strikes" in admin
