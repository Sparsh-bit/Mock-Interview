"""
Credential-stuffing defence on the auth surface — tests/test_auth_rate_limit.py

WHAT THE ARCHITECTURE ACTUALLY IS, because it decides what this file can and cannot pin.

Login, signup and password reset are **not routes on this backend**. `hooks/useAuth.ts`
calls `supabase.auth.signInWithPassword`, `signUp` and `resetPasswordForEmail` directly from
the browser, so those three requests never reach FastAPI. Rate-limiting them is a GoTrue
setting in the Supabase console — outside this repository, unassertable from here, and
recorded as a human blocker in `docs/SECURITY-REVIEW.md` (SR-2026Q3-04) rather than
pretended about.

WHAT *IS* OURS, AND WAS UNPROTECTED.

  `POST /api/v1/auth/profile` is called after every successful auth event and is what
  provisions the application's `users` row. It had no rate limit of any kind. It is the
  account-CREATION surface: a script minting Supabase accounts arrives here, once per
  account, from one place.

  `GET /api/v1/reports/public/{id}` serves a shared report to anyone holding the id. The id
  is an unguessable UUID, which is the real control — but an endpoint with no limit lets
  somebody grind against it as fast as the network allows, and "unguessable" is a statement
  about a rate as much as about an entropy.

AND THE REASON NEITHER COULD BE PROTECTED BEFORE: every limiter built by
`core.rate_limit.rate_limiter()` takes `CurrentUser` as a dependency, so it can only key on
somebody who has already authenticated. There was no way to rate-limit by caller identity on
an unauthenticated route, which is why the two above had nothing. That gap is what
`core/client_ip.py` and `ip_rate_limiter` close.

THE FORWARDED-FOR OBJECTION IS REAL AND IS HANDLED. `docs/COMPLIANCE.md` records the
standing decision that limits key on the authenticated user "never an IP — a forwarded-for
header buys nothing", and it is right: an attacker sets that header to whatever they like.
So the IP is only taken from a header when a trusted proxy is CONFIGURED to have written it,
and the hop is counted from the right-hand end, which is the only end an attacker cannot
extend. Unconfigured, the header is ignored entirely. Both directions are tested below.
"""

from __future__ import annotations

import pytest

from app.core.config import settings

pytestmark = pytest.mark.anyio


class FakeRedis:
    """
    INCR / EXPIRE / TTL over a dict — the whole surface `enforce_limit` uses.

    A fake rather than a real Redis because what is under test is the LIMIT ARITHMETIC, and
    binding that to a running server would make the one test that matters here skip in CI.
    `test_redis_managed.py` is where the real client is exercised against a real server.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


async def _hits_until_429(key: str, limit: int, redis: FakeRedis, attempts: int) -> int | None:
    """How many calls it took to get a 429, or None if `attempts` was never enough."""
    from fastapi import HTTPException

    from app.core.rate_limit import enforce_limit

    for attempt in range(1, attempts + 1):
        try:
            await enforce_limit(
                redis, key=key, limit=limit, window_seconds=60, action="test"
            )
        except HTTPException as exc:
            assert exc.status_code == 429
            return attempt
    return None



def _find_route(app, method: str, path: str):
    """The live route object for one (method, path), following included routers."""
    from tests.test_pentest_authz import _walk  # noqa: PLC0415

    def search(routes, prefix: str = ""):
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                original = getattr(route, "original_router", None)
                context = getattr(route, "include_context", None)
                nested = getattr(context, "prefix", "") if context is not None else ""
                if original is not None:
                    found = search(original.routes, prefix + nested)
                    if found is not None:
                        return found
                continue
            if prefix + getattr(route, "path", "") == path and method in (
                getattr(route, "methods", None) or set()
            ):
                return route
        return None

    assert _walk  # imported so a rename of the walker breaks here too
    route = search(app.routes)
    assert route is not None, f"{method} {path} is not mounted"
    return route


def _dependency_names(route) -> list[str]:
    """
    The names of every dependency callable on a route, including router-level ones.

    `Depends(...)` on a factory-built closure has the factory's inner function name, which
    is why the assertions look for the substring "rate_limit" rather than an exact match:
    `rate_limiter()` and `ip_rate_limiter()` both return a closure called `_check`, so the
    readable name is on the qualname.
    """
    names: list[str] = []
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        for sub in getattr(dependant, "dependencies", []):
            call = getattr(sub, "call", None)
            if call is not None:
                names.append(getattr(call, "__qualname__", getattr(call, "__name__", "")))
    return names


def _public_routes(app) -> list[tuple[str, str]]:
    """Every (method, path) whose handler is on `test_auth_coverage`'s public allowlist."""
    from tests.test_auth_coverage import INTENTIONALLY_PUBLIC  # noqa: PLC0415
    from tests.test_pentest_authz import _walk  # noqa: PLC0415

    found: list[tuple[str, str]] = []
    for method, path in _walk(app.routes):
        route = _find_route(app, method, path)
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and endpoint.__name__ in INTENTIONALLY_PUBLIC:
            found.append((method, path))
    return found


# ── 1. The dedicated limit is stricter than the general one ─────────────────────


class TestTheAuthLimitIsStricterThanTheGeneralOne:
    def test_the_settings_say_so(self):
        """
        The invariant, stated where it cannot drift. A dedicated limit that is not tighter
        than the general one is not a defence, it is a second copy of the same number.
        """
        assert settings.RATE_LIMIT_AUTH_PER_MINUTE < settings.RATE_LIMIT_READ_PER_MINUTE, (
            "the auth limit is not stricter than the general read limit, so it can never "
            "trip first and buys nothing"
        )

    async def test_the_auth_limit_trips_and_the_general_limit_has_not(self):
        """
        THE ASSERTION THE TASK ASKS FOR, made behaviourally rather than by comparing two
        integers: drive both limiters with the same traffic and show the auth one refuses
        while the general one is still letting requests through.
        """
        redis = FakeRedis()
        auth_limit = settings.RATE_LIMIT_AUTH_PER_MINUTE
        read_limit = settings.RATE_LIMIT_READ_PER_MINUTE

        tripped_at = await _hits_until_429("rl:auth", auth_limit, redis, attempts=read_limit)

        assert tripped_at is not None, "the auth limit never tripped"
        assert tripped_at == auth_limit + 1

        # The same number of requests against the general bucket: still open.
        general = FakeRedis()
        general_tripped = await _hits_until_429(
            "rl:read", read_limit, general, attempts=tripped_at
        )
        assert general_tripped is None, (
            f"the general limit also refused within {tripped_at} requests, so the "
            "dedicated auth limit is not doing anything the general one would not"
        )

    async def test_the_hourly_auth_limit_bounds_a_slow_grind(self):
        """
        A per-minute limit alone is beaten by waiting. The hourly bucket is what makes the
        total cost of minting accounts from one place bounded rather than merely paced.
        """
        assert settings.RATE_LIMIT_AUTH_PER_HOUR < settings.RATE_LIMIT_AUTH_PER_MINUTE * 60


# ── 2. The IP has to come from somewhere trustworthy ────────────────────────────


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None, peer: str | None = "10.0.0.1"):
        self.headers = headers or {}
        self.client = _FakeClient(peer) if peer else None


class TestTheClientIpCannotSimplyBeAsserted:
    def test_a_forwarded_header_is_ignored_when_no_proxy_is_configured(self, monkeypatch):
        """
        THE STANDING OBJECTION IN COMPLIANCE.md, honoured. With nothing configured, an
        attacker-supplied `X-Forwarded-For` must buy exactly nothing.
        """
        from app.core.client_ip import client_ip

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADER", "")
        request = _FakeRequest({"x-forwarded-for": "1.2.3.4"}, peer="10.0.0.1")

        assert client_ip(request) == "10.0.0.1"

    def test_a_configured_header_is_read(self, monkeypatch):
        from app.core.client_ip import client_ip

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADER", "cf-connecting-ip")
        request = _FakeRequest({"cf-connecting-ip": "203.0.113.9"}, peer="10.0.0.1")

        assert client_ip(request) == "203.0.113.9"

    def test_forwarded_for_is_counted_from_the_right(self, monkeypatch):
        """
        `X-Forwarded-For` is append-only, so an attacker controls the LEFT of the list —
        they simply send a header and the proxy appends to it. The rightmost hops are the
        ones written by infrastructure we run. Counting from the left is the classic way
        to build a spoofable limiter.
        """
        from app.core.client_ip import client_ip

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADER", "x-forwarded-for")
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        request = _FakeRequest(
            {"x-forwarded-for": "1.1.1.1, 2.2.2.2, 203.0.113.9"}, peer="10.0.0.1"
        )

        assert client_ip(request) == "203.0.113.9"

    def test_extra_hops_are_honoured(self, monkeypatch):
        from app.core.client_ip import client_ip

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADER", "x-forwarded-for")
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
        request = _FakeRequest(
            {"x-forwarded-for": "1.1.1.1, 203.0.113.9, 10.0.0.7"}, peer="10.0.0.1"
        )

        assert client_ip(request) == "203.0.113.9"

    def test_a_junk_header_value_does_not_become_a_key(self, monkeypatch):
        """
        The value becomes part of a Redis key. An unvalidated one is an attacker writing
        keys of their choosing into our keyspace, and a different bogus value per request
        is a limiter that never counts to two.
        """
        from app.core.client_ip import client_ip

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADER", "cf-connecting-ip")
        for junk in ("not-an-ip", "", "   ", "1.2.3.4; rm -rf", "a" * 500, "999.999.999.999"):
            request = _FakeRequest({"cf-connecting-ip": junk}, peer="10.0.0.1")
            assert client_ip(request) in ("10.0.0.1", "unknown"), f"junk accepted: {junk!r}"

    def test_ipv6_survives(self, monkeypatch):
        from app.core.client_ip import client_ip

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADER", "cf-connecting-ip")
        request = _FakeRequest({"cf-connecting-ip": "2001:db8::1"}, peer="10.0.0.1")

        assert client_ip(request) == "2001:db8::1"

    def test_a_request_with_no_peer_at_all_still_yields_a_key(self):
        """
        `request.client` is None for some ASGI transports. A limiter that raises there is
        a limiter that 500s instead of limiting.
        """
        from app.core.client_ip import client_ip

        assert client_ip(_FakeRequest(peer=None)) == "unknown"

    def test_one_ip_gets_one_bucket(self, monkeypatch):
        from app.core.client_ip import client_ip
        from app.db.redis import CacheKeys

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADER", "")
        first = CacheKeys.rate_limit_auth_ip(client_ip(_FakeRequest(peer="10.0.0.1")))
        second = CacheKeys.rate_limit_auth_ip(client_ip(_FakeRequest(peer="10.0.0.2")))

        assert first != second
        assert "10.0.0.1" in first


# ── 3. The limiter is actually attached to the routes ───────────────────────────


class TestTheLimitsAreWiredToTheEndpointsThatNeededThem:
    def test_the_account_provisioning_route_is_limited(self):
        """
        Attachment is the part that silently does not happen. A limiter that exists and is
        wired to nothing is the guard-that-cannot-fail shape MISTAKES.md is about — so this
        reads the LIVE route's dependency list rather than grepping the source, which would
        pass on a limiter that is defined, imported and never applied.
        """
        from app.main import app
        from tests.test_pentest_authz import _walk

        route = _find_route(app, "POST", "/api/v1/auth/profile")
        names = _dependency_names(route)

        assert any("rate_limit" in name for name in names), (
            f"POST /api/v1/auth/profile has no rate limiter attached; its dependencies "
            f"are {names}"
        )
        # Both windows. The minute bucket paces a burst; the hour bucket bounds a grind.
        assert sum("rate_limit" in name for name in names) >= 2, (
            f"only one window is attached: {names}"
        )
        assert _walk  # the helper is imported for _find_route below

    def test_the_public_share_route_is_limited(self):
        from app.main import app

        route = _find_route(app, "GET", "/api/v1/reports/public/{report_id}")

        assert any("rate_limit" in name for name in _dependency_names(route))

    def test_no_other_public_route_was_left_unlimited_by_accident(self):
        """
        Guards the coverage rather than the two examples. Every route reachable without a
        token either has an address-keyed limiter or is named here with a reason — the same
        shape as `test_auth_coverage.py`'s allowlist, and for the same reason: a new public
        route should have to be argued for.
        """
        from app.main import app

        #: Public routes that deliberately carry no address-keyed limiter, and why.
        #:
        #: THE COMMON REASON IS SHARED ADDRESSES. A campus lab or a college NAT puts a whole
        #: cohort behind one IP, and every one of them loads the register page on results
        #: day. A per-address limit tight enough to matter would lock out the cohort; one
        #: loose enough not to would not be a limit. These four return CONSTANTS — no user
        #: data, no database read shaped by the caller, no AI spend — so the thing a limit
        #: would protect is not worth the outage it would cause.
        #:
        #: The share link is deliberately NOT on this list: its id is guessable-in-principle
        #: and grinding against it is the attack, so there the rate is the control.
        exempt = {
            # Liveness. The platform's health checker calls it constantly, by design.
            ("GET", "/api/v1/health"),
            # HMAC-authenticated over the raw body. Limiting it would drop Razorpay's
            # retries, and a dropped payment notification is a paid-for entitlement that
            # never arrives.
            ("POST", "/api/v1/billing/webhook"),
            # The price list, straight out of plans.py. Public so the pricing page works
            # signed out; identical for every caller.
            ("GET", "/api/v1/billing/items"),
            # The privacy notice and processor list. PUBLIC BECAUSE DPDP §5 requires notice
            # before processing, which is before there is an account — and it is fetched by
            # the register page, which is exactly where a cohort hits it at once.
            ("GET", "/api/v1/legal/disclosure"),
            # The rating ladder and tier bars. Static constants for onboarding copy.
            ("GET", "/api/v1/progress/base"),
        }

        unlimited: list[tuple[str, str]] = []
        for method, path in _public_routes(app):
            if (method, path) in exempt:
                continue
            route = _find_route(app, method, path)
            if not any("rate_limit" in name for name in _dependency_names(route)):
                unlimited.append((method, path))

        assert not unlimited, (
            "these routes are reachable without a token and have no rate limiter: "
            f"{sorted(unlimited)}. Add one, or add it to `exempt` above with a reason."
        )

    async def test_the_limiter_dependency_refuses_over_the_limit(self):
        """
        End to end through the real dependency: build it the way the route does, call it
        with a real request object and a fake Redis, and show it raises 429.
        """
        from fastapi import HTTPException

        from app.core.rate_limit import ip_rate_limiter
        from app.db.redis import CacheKeys

        dependency = ip_rate_limiter(
            limit=3,
            window_seconds=60,
            key_builder=CacheKeys.rate_limit_auth_ip,
            action="creating an account",
        )
        redis = FakeRedis()
        request = _FakeRequest(peer="198.51.100.4")

        for _ in range(3):
            await dependency(request, redis)  # type: ignore[arg-type]

        with pytest.raises(HTTPException) as caught:
            await dependency(request, redis)  # type: ignore[arg-type]
        assert caught.value.status_code == 429

    async def test_two_different_ips_do_not_share_a_bucket(self):
        from app.core.rate_limit import ip_rate_limiter
        from app.db.redis import CacheKeys

        dependency = ip_rate_limiter(
            limit=2,
            window_seconds=60,
            key_builder=CacheKeys.rate_limit_auth_ip,
            action="creating an account",
        )
        redis = FakeRedis()

        for _ in range(2):
            await dependency(_FakeRequest(peer="198.51.100.4"), redis)  # type: ignore[arg-type]
        # A different caller is unaffected — otherwise one abuser locks out a campus.
        await dependency(_FakeRequest(peer="198.51.100.5"), redis)  # type: ignore[arg-type]

    async def test_it_fails_open_like_every_other_limiter_here(self):
        """
        The standing decision in SECURITY-REVIEW.md A10: a limiter outage must not take the
        product down. The IP limiter has to behave the same way as the rest, or a Redis
        blip locks everybody out of signing in.
        """
        from redis.exceptions import RedisError

        from app.core.rate_limit import ip_rate_limiter
        from app.db.redis import CacheKeys

        class BrokenRedis(FakeRedis):
            async def incr(self, key: str) -> int:
                raise RedisError("down")

        dependency = ip_rate_limiter(
            limit=1,
            window_seconds=60,
            key_builder=CacheKeys.rate_limit_auth_ip,
            action="creating an account",
        )
        for _ in range(5):
            await dependency(_FakeRequest(peer="198.51.100.4"), BrokenRedis())  # type: ignore[arg-type]


class TestTheGoTrueGapIsRecordedRatherThanPretendedAbout:
    def test_the_security_review_still_names_the_human_blocker(self):
        """
        Login, signup and reset cannot be limited from this repository. The one thing that
        must not happen is the finding quietly disappearing because some adjacent work
        looked like it addressed it.
        """
        import pathlib

        doc = (
            pathlib.Path(__file__).resolve().parents[2] / "docs" / "SECURITY-REVIEW.md"
        ).read_text(encoding="utf-8")

        assert "SR-2026Q3-04" in doc
        assert "GoTrue" in doc
