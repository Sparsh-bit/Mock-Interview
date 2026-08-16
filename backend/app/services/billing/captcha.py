"""
Captcha verification — services/billing/captcha.py

WHY THIS EXISTS. A ₹1 launch offer or a 100%-off code is worth farming with a script: sign
up, redeem, repeat. The single-use rule is per ACCOUNT, and accounts are free, so without
something that costs a human a second the rule only limits how many times one person can be
bothered to make an email address.

CLOUDFLARE TURNSTILE rather than reCAPTCHA. It is free at any volume, it does not require a
Google account to administer, it usually passes without any interaction at all, and it does
not send this product's users to a third party that profiles them. For a product whose users
are students in India on cheap phones, "usually invisible" matters more than "more accurate".

PER-OFFER, NOT GLOBAL. `Offer.requires_captcha` decides. A public ₹1 offer needs one; a
private code shared with four friends does not, and a captcha in front of everything trains
people to click through it without reading — which is how you end up with a control that
everybody satisfies and nobody notices.

FAILS CLOSED, WITH ONE EXCEPTION. An unverifiable token is a rejection. But if Turnstile is
not CONFIGURED at all, an offer that requires it refuses rather than quietly letting everyone
through: a captcha that silently stops working is worse than no captcha, because the offer
was priced on the assumption it was there.
"""

from __future__ import annotations

import httpx
import structlog

from app.core.config import settings
from app.core.exceptions import AppError

logger = structlog.get_logger(__name__)

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class CaptchaError(AppError):
    """
    The human check did not pass.

    Status set in `__init__` for the same reason OfferError does it: `AppError.__init__`
    defaults to 500 and assigns unconditionally, so a class attribute is overwritten on
    construction and "please complete the verification" arrives as a crash.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=400,
            code="CAPTCHA_FAILED",
        )


async def verify(token: str, *, remote_ip: str | None = None) -> None:
    """
    Check a Turnstile token, or raise.

    `remote_ip` is optional and passed through when known — Cloudflare uses it to score the
    challenge, and omitting it makes the verdict slightly weaker rather than failing.

    A network failure talking to Cloudflare is a REJECTION, not a pass. The alternative is
    that anyone who can disrupt one outbound HTTPS call gets the offer for free, which is a
    much easier attack than solving the captcha.
    """
    if not settings.TURNSTILE_SECRET_KEY:
        # Refusing rather than passing. This offer was configured to need a human, and if
        # the machinery for checking that is missing then the honest answer is that the
        # requirement cannot be met — not that it is waived.
        logger.error(
            "captcha_not_configured",
            reason="an offer requires a captcha but TURNSTILE_SECRET_KEY is unset",
        )
        # NOT "please try again later", WHICH WAS A LIE.
        #
        # Retrying cannot fix an unset key. The old wording described a transient outage,
        # so a candidate refreshed, waited, and refreshed again against a state that would
        # never change on its own — and the operator heard about it as "payments are down"
        # rather than as one missing environment variable.
        #
        # The route that DOES work is named, because it exists: the code is what needs the
        # verification, so the item is still buyable at full price without it. Offering
        # that beats a dead end, even though it is the more expensive path for them.
        raise CaptchaError(
            "This code needs a human verification step that isn't set up on this site yet, "
            "so it can't be used right now. You can still buy without the code — or contact "
            "support if you were promised this discount."
        )

    if not (token or "").strip():
        raise CaptchaError("Please complete the verification below.")

    payload = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(_VERIFY_URL, data=payload)
            body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("captcha_verify_unavailable", error=str(exc))
        raise CaptchaError(
            "We could not complete verification. Please try again."
        ) from exc

    if not body.get("success"):
        logger.info("captcha_rejected", codes=body.get("error-codes"))
        raise CaptchaError("Verification failed. Please try again.")
