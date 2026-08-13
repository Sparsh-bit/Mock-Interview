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
    # The pricing page. Requiring a login to see what something costs is the one place where
    # auth actively loses the sale, and it exposes only what is on the marketing site.
    "list_plans",
    # Razorpay has no user token to present. Authenticated by HMAC-SHA256 over the raw body
    # with a constant-time comparison — see services/billing/razorpay.py.
    "razorpay_webhook",
    # Static constants (the rating ladder and tier bars) so onboarding copy can explain the
    # system before a candidate has any history. Contains no user data of any kind.
    "get_base",
    # A shared report. Gated on the OWNER having explicitly enabled sharing plus knowledge of
    # an unguessable UUID, and 404s rather than 403s so it cannot confirm a report exists.
    "get_public_report",
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
        for mutation in ("plan_row.plan_id =", "db.commit()", "plan_from_payment"):
            assert body.index(mutation) > verify_at, f"{mutation} runs before verification"

    def test_it_is_idempotent_on_the_payment_id(self):
        # Razorpay retries until it gets a 2xx, so the same payment WILL arrive more than
        # once. Without this a customer who paid once is granted three months.
        src = (API / "billing.py").read_text()
        assert "UserPlan.provider_ref == outcome.payment_id" in src
