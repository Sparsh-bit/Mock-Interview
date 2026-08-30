"""
Who is calling — core/client_ip.py

WHY THIS IS DELICATE ENOUGH TO NEED ITS OWN FILE. `docs/COMPLIANCE.md` records a standing
decision that rate limits key on the authenticated user and "never an IP — a forwarded-for
header buys nothing." That is correct and this module does not overturn it. An
attacker-supplied `X-Forwarded-For` is worth nothing, and treating it as identity is how a
limiter becomes decoration: every request carries a different fake address, every bucket
counts to one, and the endpoint is unlimited while appearing limited.

But an unauthenticated route has no user to key on. Account provisioning and a public
share link are reachable before anybody has logged in, and before this module the codebase
had no way to limit them at all — `rate_limiter()` takes `CurrentUser` as a dependency, so
it cannot be applied to a route that has no current user. That was the actual gap.

THE RESOLUTION IS TO TRUST A HEADER ONLY WHEN WE KNOW WHO WROTE IT.

  · With `TRUSTED_PROXY_HEADER` unset, no header is read at all. The peer address is used,
    which behind a proxy is the proxy — a single bucket for everybody, which is useless but
    is never WRONG. Failing to a useless-but-honest key beats failing to a spoofable one.

  · With it set, the named header is read, because the operator has asserted that a proxy
    they run overwrites it. `cf-connecting-ip` is the single-value case and is preferred.

  · `x-forwarded-for` is a LIST and is append-only, which is the whole subtlety. An
    attacker sends `X-Forwarded-For: 1.1.1.1` and the proxy appends the real address to the
    right. So the left-hand entries are attacker-controlled and the right-hand ones are
    ours, and the hop is counted from the RIGHT. Counting from the left — which is the
    obvious reading of "the client is the first entry" — is precisely how a spoofable
    limiter gets built.

EVERY RESULT IS A VALIDATED IP OR THE STRING "unknown". The value becomes part of a Redis
key, so an unvalidated one lets a caller write keys of their choosing into our keyspace and,
worse, gives them a fresh bucket per request just by varying the junk.
"""

from __future__ import annotations

import ipaddress

from app.core.config import settings

#: What an unidentifiable caller is keyed as. A shared bucket rather than an exemption:
#: callers we cannot tell apart are limited together, which is the conservative direction.
UNKNOWN = "unknown"


def _valid(candidate: str) -> str | None:
    """The address, canonicalised, or None if it is not one."""
    text = candidate.strip()
    if not text or len(text) > 45:
        return None
    # A proxy may append a port. Only strip it for the IPv4 case: an IPv6 address is full
    # of colons and splitting on one would mangle it.
    if text.count(":") == 1 and "." in text:
        text = text.split(":", 1)[0]
    text = text.strip("[]")
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def client_ip(request) -> str:  # noqa: ANN001 - Starlette Request, kept loose for testability
    """
    The caller's address, as a value safe to use as part of a rate-limit key.

    Never raises and never returns an empty string: some ASGI transports give no peer at
    all, and a limiter that throws there is a 500 rather than a limit.
    """
    header_name = (settings.TRUSTED_PROXY_HEADER or "").strip().lower()

    if header_name:
        raw = request.headers.get(header_name) or ""
        if header_name == "x-forwarded-for":
            # Count from the right. See the module header for why the left is worthless.
            hops = max(1, int(settings.TRUSTED_PROXY_HOPS or 1))
            parts = [part for part in (p.strip() for p in raw.split(",")) if part]
            if len(parts) >= hops:
                found = _valid(parts[-hops])
                if found:
                    return found
        else:
            found = _valid(raw)
            if found:
                return found
        # A configured header that is missing or malformed falls through to the peer rather
        # than to a constant — a misconfigured proxy should degrade to one bucket per
        # connection source, not to one bucket for the whole internet.

    peer = getattr(request, "client", None)
    if peer is not None and getattr(peer, "host", None):
        return _valid(peer.host) or UNKNOWN
    return UNKNOWN
