"""
Every route requires authentication unless it is on this list.

WHY THIS TEST EXISTS. The same reasoning as test_rls_coverage.py, one layer up. Nothing in
the codebase connects "I added an endpoint" to "I must require a user", and the failure is
silent: an endpoint with no `CurrentUser` parameter works perfectly in every manual test,
because the developer testing it is logged in anyway. It is only unauthenticated for the
people who were never supposed to reach it.

The risk grew with billing. An unauthenticated route that spends an AI call is somebody
else's money, and an unauthenticated route that touches `user_plans` is a free upgrade.

SO THE ALLOWLIST IS THE POINT, not the scan. A new public route does not fail because it is
wrong — some of them are genuinely meant to be public — it fails because it has not been
argued for. Adding a name here should require writing down why, which is exactly the pause
that was missing.
"""

from __future__ import annotations

import pathlib
import re

API = pathlib.Path(__file__).resolve().parent.parent / "app" / "api" / "v1"

#: Routes that are deliberately reachable without a token, and the reason each one is.
#:
#: Every entry has been checked for what it can actually return to a stranger.
INTENTIONALLY_PUBLIC = {
    # Liveness. Returns no user data and is required by the platform's health checks.
    "health_check",
    # The store. Requiring a login to see what something costs is the one place where auth
    # actively loses the sale, and it exposes only what is on the marketing site.
    "list_items",
    # Razorpay has no user token to present. Authenticated by HMAC-SHA256 over the raw body
    # with a constant-time comparison — see services/billing/razorpay.py.
    "razorpay_webhook",
    # Static constants (the rating ladder and tier bars) so onboarding copy can explain the
    # system before a candidate has any history. Contains no user data of any kind.
    "get_base",
    # A shared report. Gated on the OWNER having explicitly enabled sharing plus knowledge of
    # an unguessable UUID, and 404s rather than 403s so it cannot confirm a report exists.
    "get_public_report",
    # The privacy notice, the processor list and the grievance contact. PUBLIC BECAUSE DPDP §5
    # requires notice BEFORE processing begins — which is before there is an account to
    # authenticate, and the register page links to it. Contains no user data: the processor
    # list is derived from this deployment's own configuration and the contact is a published
    # one. Every other route in api/v1/legal.py takes CurrentUser, because those are about
    # one person's answers.
    "get_disclosure",
}


def _unauthenticated_routes() -> set[str]:
    """
    Every route handler whose decorator-plus-signature mentions no user dependency.

    Reads the full signature by matching parentheses rather than by line, because most of
    these declarations span several lines and a line-based scan reports handlers as
    unauthenticated purely because their `CurrentUser` is on the next line.
    """
    found: set[str] = set()
    for path in sorted(API.glob("*.py")):
        src = path.read_text()
        for m in re.finditer(r"@router\.(?:get|post|put|patch|delete)\(", src):
            dm = re.compile(r"\n(?:async )?def (\w+)\(", re.S).search(src, m.start())
            if not dm:
                continue
            i = dm.end() - 1
            depth = 0
            sig_end = None
            for j in range(i, len(src)):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        sig_end = j
                        break
            if sig_end is None:
                continue
            block = src[m.start() : sig_end + 1]
            if not re.search(r"CurrentUser|current_user|require_admin|AdminUser", block):
                found.add(dm.group(1))
    return found


class TestEveryRouteIsAuthenticated:
    def test_no_unexpected_route_is_public(self):
        unexpected = sorted(_unauthenticated_routes() - INTENTIONALLY_PUBLIC)
        assert not unexpected, (
            "These routes take no authenticated user. If that is deliberate, add the name to "
            f"INTENTIONALLY_PUBLIC with the reason: {unexpected}"
        )

    def test_the_allowlist_has_no_dead_entries(self):
        # A name left here after the route gained auth — or was deleted — is an allowlist
        # that has stopped describing reality, and the next reader trusts it anyway.
        stale = sorted(INTENTIONALLY_PUBLIC - _unauthenticated_routes())
        assert not stale, f"INTENTIONALLY_PUBLIC lists routes that are not public: {stale}"

    def test_the_scanner_actually_finds_things(self):
        # Guards against the regex silently matching nothing — which would make this whole
        # file pass forever while checking absolutely nothing.
        assert len(_unauthenticated_routes()) >= 3


class TestTheWebhookIsNotAccidentallyOpen:
    def test_it_verifies_a_signature_before_doing_anything(self):
        src = (API / "billing.py").read_text()
        body = src[src.index("async def razorpay_webhook") :]
        verify_at = body.index("verify_signature")
        # Nothing that mutates a plan may appear before the signature check. An ordering
        # mistake here is a free Pro upgrade for anyone who finds the URL.
        for mutation in ("items_from_payment", "grant(", "db.commit()"):
            assert body.index(mutation) > verify_at, f"{mutation} runs before verification"

    def test_it_is_idempotent_on_the_payment_id(self):
        # Razorpay retries until it gets a 2xx, so the same payment WILL arrive more than
        # once. Without this a customer who paid for five interviews receives fifteen.
        src = (API / "billing.py").read_text()
        assert "CreditEvent.payment_ref == outcome.payment_id" in src


class TestAdminCannotBeSelfGranted:
    """
    "non users cannot be admin unless they are assigned".

    The property is that `users.is_admin` has exactly ONE write path and it is behind the
    admin dependency. Asserted structurally rather than behaviourally, because the failure
    would be a NEW write somewhere — a signup hook reading a JWT claim, a seed script, a
    convenience endpoint — and no test of the existing paths would notice one appearing.
    """

    def test_only_one_place_in_the_app_writes_is_admin(self):
        import pathlib
        import re

        app = pathlib.Path(__file__).resolve().parent.parent / "app"
        writes = []
        for f in app.rglob("*.py"):
            for i, line in enumerate(f.read_text().splitlines(), 1):
                # An assignment to is_admin, not a comparison or a read into a response.
                if re.search(r"\.is_admin\s*=(?!=)", line):
                    writes.append(f"{f.relative_to(app)}:{i}")

        # ASSERTED ON THE FILE, NOT THE LINE, AND THE STRICTNESS IS UNCHANGED.
        #
        # The security property is "exactly one write path, and it is in the admin router".
        # A second write anywhere still fails this (the list grows); a write moved to
        # another file still fails it (the name changes). The line NUMBER was never part of
        # the property — it only pinned where the write happened to sit, so adding an
        # import above it failed a security test for a reason that had nothing to do with
        # security. A test that cries wolf on unrelated edits is one people learn to
        # re-baseline without reading, which is how the real regression gets waved through.
        #
        # The message still prints file:line, so a failure points at the exact offender.
        locations = [w.rsplit(":", 1)[0] for w in writes]
        assert locations == ["api/v1/admin.py"], (
            f"is_admin is written in {writes}. Granting admin must happen in exactly one "
            "place, behind the AdminUser dependency — a second write path is a privilege "
            "escalation waiting for somebody to find it."
        )

    def test_that_one_place_is_behind_the_admin_dependency(self):
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/admin.py"
        ).read_text()
        sig = src[src.index("async def update_user") : src.index("async def update_user") + 400]
        assert "current_user: AdminUser" in sig

    def test_nothing_grants_admin_at_signup(self):
        # The dangerous shape is a JWT claim or an email allowlist being trusted to promote
        # an account on first login. There is no such path, and there must not be one.
        import pathlib

        auth = (
            pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/auth.py"
        ).read_text()
        security = (
            pathlib.Path(__file__).resolve().parent.parent / "app/core/security.py"
        ).read_text()
        for src in (auth, security):
            assert ".is_admin =" not in src

    def test_the_column_defaults_to_false(self):
        from app.models.user import User

        assert User.__table__.c.is_admin.default.arg is False
