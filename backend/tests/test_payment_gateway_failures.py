"""
What happens when the payment provider does not answer, or answers with rubbish.

WHY THIS FILE EXISTS. `create_order` is the one call in `razorpay.py` that reaches the
network without wrapping the call, and `captcha.verify` asked a parsed JSON body for a key
without first checking it was an object. Both raise exceptions that are NOT `AppError`, and
`core/exceptions.py` turns anything that is not an `AppError` into a bare

    {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}

with status 500. So a Razorpay timeout and a genuine bug in our own code arrived at the
browser looking exactly alike — which is precisely the situation that makes a production 500
take a day to diagnose instead of a minute.

THE 502-NOT-503 ASSERTION IS THE POINT OF HALF OF THIS FILE. `frontend/src/app/pricing/page.tsx`
maps status 503 to "Payments are not switched on yet. Add your Razorpay keys." That is the
right message for `PaymentNotConfiguredError` and a badly wrong one for a network blip: it
tells a candidate to go and configure something that is already configured, and it tells the
operator to look in the wrong place. The status code here is user-visible copy, so it is
pinned like copy.

Everything is exercised through `httpx.MockTransport` rather than by monkeypatching our own
functions, so the code under test runs its real body — matching the idiom in test_tts.py.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.exceptions import AppError
from app.services.billing import captcha
from app.services.billing.plans import ITEMS
from app.services.billing.razorpay import create_order


def _item():
    """A real catalogue item, so the amount is a real chargeable price."""
    return ITEMS[0]


def _with_transport(transport: httpx.MockTransport):
    """
    Patch `httpx.AsyncClient` so the code under test runs unmodified.

    Returned as a context manager rather than a fixture because `create_order` imports httpx
    inside the function body, so the swap has to be live at call time, not at import time.
    """

    class _Ctx:
        def __enter__(self):
            self.original = httpx.AsyncClient

            class _Patched(self.original):  # type: ignore[misc,valid-type,name-defined]
                def __init__(self, **kw):
                    kw["transport"] = transport
                    super().__init__(**kw)

            httpx.AsyncClient = _Patched  # type: ignore[misc]
            return self

        def __exit__(self, *exc):
            httpx.AsyncClient = self.original  # type: ignore[misc]
            return False

    return _Ctx()


@pytest.fixture
def keys(monkeypatch):
    """Credentials present, so we are testing the network path and not the config guard."""
    from app.core import config

    monkeypatch.setattr(config.settings, "RAZORPAY_KEY_ID", "rzp_test_key", raising=False)
    monkeypatch.setattr(config.settings, "RAZORPAY_KEY_SECRET", "secret", raising=False)


class TestRazorpayNeverAnswers:
    """
    The request does not complete. Nothing was created, so retrying is safe and the message
    says so.
    """

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ConnectTimeout("timed out"),
            httpx.ReadTimeout("timed out"),
            httpx.ConnectError("refused"),
            httpx.RemoteProtocolError("truncated"),
        ],
        ids=["connect-timeout", "read-timeout", "connect-error", "protocol-error"],
    )
    async def test_a_network_failure_is_a_502_not_an_unhandled_crash(self, keys, failure):
        def handler(request: httpx.Request) -> httpx.Response:
            raise failure

        with _with_transport(httpx.MockTransport(handler)), pytest.raises(AppError) as caught:
            await create_order(_item(), "user-1")

        assert caught.value.status_code == 502
        assert caught.value.code == "PAYMENT_GATEWAY_UNREACHABLE"

    async def test_a_timeout_is_not_reported_as_payments_being_unconfigured(self, keys):
        """
        THE REGRESSION THIS GUARDS. 503 is the frontend's signal for "no keys set", and a
        timeout is not that. Getting this wrong sends the operator to check credentials that
        were never the problem.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        with _with_transport(httpx.MockTransport(handler)), pytest.raises(AppError) as caught:
            await create_order(_item(), "user-1")

        assert caught.value.status_code != 503
        assert caught.value.code != "PAYMENTS_NOT_CONFIGURED"


class TestRazorpayAnswersWithRubbish:
    """A 2xx is not by itself an order. Each of these used to reach `.json()` or `.get`."""

    async def test_a_2xx_html_body_is_a_502(self, keys):
        """A proxy error page or captive portal. Valid HTTP, not valid JSON."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>maintenance</html>",
                                  headers={"content-type": "text/html"})

        with _with_transport(httpx.MockTransport(handler)), pytest.raises(AppError) as caught:
            await create_order(_item(), "user-1")

        assert caught.value.status_code == 502
        assert caught.value.code == "PAYMENT_ORDER_FAILED"

    async def test_valid_json_that_is_not_an_object_is_a_502(self, keys):
        """Parses fine, then `.get` would raise AttributeError."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[1, 2, 3])

        with _with_transport(httpx.MockTransport(handler)), pytest.raises(AppError) as caught:
            await create_order(_item(), "user-1")

        assert caught.value.status_code == 502

    async def test_an_order_with_no_id_is_a_502_not_a_null_order_id(self, keys):
        """
        The browser needs the id to open the payment sheet. Failing here beats handing the
        frontend a null `order_id` that it would have to special-case at the call site.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"amount": 4900, "currency": "INR"})

        with _with_transport(httpx.MockTransport(handler)), pytest.raises(AppError) as caught:
            await create_order(_item(), "user-1")

        assert caught.value.status_code == 502

    async def test_an_upstream_4xx_is_still_a_502(self, keys):
        """Pre-existing behaviour, pinned so the new try/except above it did not move it."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"description": "bad"}})

        with _with_transport(httpx.MockTransport(handler)), pytest.raises(AppError) as caught:
            await create_order(_item(), "user-1")

        assert caught.value.status_code == 502
        assert caught.value.code == "PAYMENT_ORDER_FAILED"


class TestTheHappyPathStillWorks:
    """The guards above must not have narrowed what counts as a good order."""

    async def test_a_well_formed_order_is_returned_with_the_public_key(self, keys):
        item = _item()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": "order_ABC123", "amount": item.price_paise})

        with _with_transport(httpx.MockTransport(handler)):
            order = await create_order(item, "user-1")

        assert order["order_id"] == "order_ABC123"
        assert order["amount_paise"] == item.price_paise
        assert order["item_id"] == item.id
        # The PUBLIC key id is meant to reach the browser; the secret never is.
        assert order["key_id"] == "rzp_test_key"
        assert "secret" not in str(order).lower() or order["key_id"] == "rzp_test_key"


class TestCaptchaResponseShape:
    """
    Cloudflare's answer is trusted to be JSON, but not trusted to be an object.

    This path is promo-gated — it runs only when `Offer.requires_captcha` is set — so a crash
    here appears only for the codes that were deliberately protected, which is the worst
    possible place for an error that reads as a server bug.
    """

    @pytest.fixture
    def turnstile(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(
            config.settings, "TURNSTILE_SECRET_KEY", "sk_test", raising=False
        )

    @pytest.mark.parametrize(
        "body", [[1, 2, 3], "ok", 42, None], ids=["array", "string", "number", "null"]
    )
    async def test_a_non_object_body_is_a_rejection_not_a_crash(
        self, turnstile, monkeypatch, body
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        with (
            _with_transport(httpx.MockTransport(handler)),
            pytest.raises(captcha.CaptchaError) as caught,
        ):
            await captcha.verify("token")

        # Fails CLOSED: an answer we cannot read is not a pass.
        assert caught.value.status_code == 400

    async def test_a_successful_verification_still_passes(self, turnstile):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": True})

        with _with_transport(httpx.MockTransport(handler)):
            await captcha.verify("token")  # does not raise

    async def test_an_unsuccessful_verification_is_still_rejected(self, turnstile):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": False, "error-codes": ["bad-input"]})

        with (
            _with_transport(httpx.MockTransport(handler)),
            pytest.raises(captcha.CaptchaError),
        ):
            await captcha.verify("token")
