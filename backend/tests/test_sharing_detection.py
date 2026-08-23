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

    def test_an_appeal_still_cannot_lift_its_own_ban(self):
        """
        The half of "only an admin can lift a ban" that is still true, and must stay true.

        A ban that clears itself on request is decorative. The appeal records a request and
        nothing else — the route out is an admin, or the expiry below.
        """
        import pathlib

        api = pathlib.Path(__file__).resolve().parent.parent / "app/api/v1"
        appeal = (api / "billing.py").read_text()
        block = appeal[appeal.index("async def appeal") :]
        assert "is_banned = False" not in block
        assert "lift_ban" not in block

    def test_the_admin_unban_is_still_behind_admin_auth(self):
        import pathlib

        api = pathlib.Path(__file__).resolve().parent.parent / "app/api/v1"
        admin = (api / "admin.py").read_text()
        at = admin.index("async def unban_user")
        assert "current_user: AdminUser" in admin[at - 500 :]
        # The clearing itself now lives in the shared helper — see
        # test_both_ways_out_go_through_one_helper for why that is the stronger assertion.
        assert "lift_ban(" in admin[at:]

    def test_both_ways_out_go_through_one_helper(self):
        """
        WHY THIS REPLACED A PIN ON `is_banned = False` INSIDE admin.py.

        There are now two ways a ban ends — an admin lifting it, and the cooling-off window
        expiring — and "what unbanning means" is six field writes plus clearing the Redis
        strike counter. Two copies of that would drift, and the half that gets forgotten is
        always the strike counter, because forgetting it is invisible: the account unbans
        fine and is re-banned a day later by evidence somebody already forgave, which looks
        exactly like the unban not working.

        So the assertion is no longer "admin.py clears the flag" — it is "nobody clears the
        flag except the one helper".
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        sharing = (root / "app/services/security/sharing.py").read_text()

        # The helper does the whole job.
        lift = sharing[sharing.index("async def lift_ban") :]
        for required in ("is_banned = False", "banned_at = None", "clear_strikes"):
            assert required in lift, f"lift_ban no longer does {required}"
        # Strikes must be cleared, or the lift is undone by stale evidence.
        assert "unbanned_count" in lift, "the repeat-offender counter must survive a lift"

        # And nowhere else writes the flag off.
        for path in ("app/api/v1/admin.py", "app/api/v1/billing.py", "app/core/security.py"):
            src = (root / path).read_text()
            assert "is_banned = False" not in src, (
                f"{path} clears the ban itself; it must call lift_ban so the strike counter "
                "cannot be forgotten"
            )

    def test_a_suspension_is_never_permanent(self):
        """
        THE REPORTED BUG: "once the id gets suspended then it is not opening even if we log
        out from everywhere".

        That was accurate. `is_banned` is a column, logout never touched it, and nothing else
        lifted it — so a heuristic detector produced an irreversible penalty, recoverable only
        by an admin who might be asleep, on students whose placement window is measured in
        days. The evidence for the ban expired in a week; the ban did not.

        The window escalates for repeats so it is not a standing licence to share, and it is
        capped so it can never become permanent again. Both properties are asserted, because
        losing either one rebuilds the lockout.
        """
        from app.core.config import settings
        from app.services.security.sharing import suspension_window_hours

        first = suspension_window_hours(0)
        assert first > 0, "a first suspension must expire on its own"
        assert first == settings.ACCOUNT_SUSPENSION_HOURS

        # A repeat costs more than a first offence.
        assert suspension_window_hours(1) > first
        assert suspension_window_hours(5) > suspension_window_hours(1)

        # But never unbounded, however many repeats.
        assert suspension_window_hours(10_000) == settings.ACCOUNT_SUSPENSION_MAX_HOURS
        assert suspension_window_hours(10_000) < float("inf")

    def test_the_expiry_can_be_switched_off_without_editing_code(self):
        """Zero restores the original admin-only behaviour, for an operator who wants it."""
        from app.core.config import settings
        from app.services.security.sharing import suspension_window_hours

        original = settings.ACCOUNT_SUSPENSION_HOURS
        try:
            settings.ACCOUNT_SUSPENSION_HOURS = 0
            assert suspension_window_hours(0) == 0.0
            assert suspension_window_hours(3) == 0.0
        finally:
            settings.ACCOUNT_SUSPENSION_HOURS = original

    def test_a_blocked_request_tells_the_client_it_is_appealable(self):
        """
        WHY THE SCREEN WAS A DEAD END, and it was not the appeal being unreachable.

        core/security.py — the auth dependency every request passes through — raised a bare
        HTTPException carrying the suspension sentence as prose. The client cannot tell an
        untyped 403 from any other failure, so it rendered the generic data-error card: "this
        is usually temporary, wait a moment and try again", a Try again button that can never
        succeed, and no link to the appeal the sentence tells the user to find.

        The typed error carries `code: ACCOUNT_BANNED` and `details.appealable`, which is what
        the client routes on — a contract frontend/src/lib/api/error-envelope.test.ts already
        pinned before anything rendered it.
        """
        import pathlib

        from app.core.exceptions import AccountBannedError

        err = AccountBannedError(reason="shared_account")
        assert err.status_code == 403
        assert err.code == "ACCOUNT_BANNED"
        assert err.details["appealable"] is True

        security = (
            pathlib.Path(__file__).resolve().parent.parent / "app/core/security.py"
        ).read_text()
        assert "raise AccountBannedError(" in security
        # The prose 403 must not come back: it is indistinguishable from any other forbidden
        # response on the client, which is the whole defect.
        assert "This account is suspended because it was used from two places at " not in (
            security
        ), "the message belongs to AccountBannedError, not duplicated as prose here"
