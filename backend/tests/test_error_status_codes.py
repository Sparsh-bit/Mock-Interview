"""
Every AppError subclass reports the status it means — tests/test_error_status_codes.py

WHY THIS EXISTS. `OfferError` and `CaptchaError` declared `status_code = 400` as a CLASS
attribute. `AppError.__init__` defaults `status_code` to 500 and assigns it unconditionally,
so the class attribute is overwritten the instant the exception is constructed.

The result was a live 500 on every checkout with a promo code applied. "You have already used
this code" — an ordinary, expected outcome that the UI is written to display — reached the
browser as an Internal Server Error with no message. A working guard and a crash looked
identical, and the console said only `500`.

It is worth a test rather than a fix because the mistake is invisible at every point you would
normally catch it: the class reads correctly, mypy is happy, ruff is happy, and the exception
is never constructed in a unit test that checks its status. It only shows up in production, as
the wrong number.
"""

from __future__ import annotations

import inspect
import pkgutil
from importlib import import_module

import pytest
from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import AppError


def _all_app_errors() -> list[type[AppError]]:
    """Every AppError subclass anywhere under app/, found by walking the package."""
    import app

    found: dict[str, type[AppError]] = {}
    for mod in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            module = import_module(mod.name)
        except Exception:
            # A module that cannot import on its own (optional dependency, circular guard)
            # is not this test's problem — skip rather than fail the suite for it.
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, AppError) and obj is not AppError:
                found[f"{obj.__module__}.{obj.__qualname__}"] = obj
    return list(found.values())


ERRORS = _all_app_errors()


def test_the_scanner_found_the_error_classes():
    """Guards the guard: an empty list would make every case below pass vacuously."""
    assert len(ERRORS) >= 5, f"only found {len(ERRORS)} AppError subclasses"


@pytest.mark.parametrize("cls", ERRORS, ids=lambda c: c.__qualname__)
def test_no_subclass_sets_status_code_as_a_class_attribute(cls: type[AppError]):
    """
    THE EXACT MISTAKE. A class attribute is overwritten by `AppError.__init__`, so declaring
    it there is not merely ineffective — it reads as though the status is 400 while every
    instance carries 500.

    Setting it in `__init__` via `super().__init__(status_code=…)` is the only thing that
    works, and is what every correct subclass in this file already does.
    """
    own = cls.__dict__.get("status_code")
    assert own is None, (
        f"{cls.__qualname__} sets `status_code` as a class attribute. "
        "AppError.__init__ assigns self.status_code unconditionally and defaults to 500, so "
        "this is silently ignored and every instance is a 500. Pass it to super().__init__() "
        "instead."
    )


@pytest.mark.parametrize("cls", ERRORS, ids=lambda c: c.__qualname__)
def test_an_instance_does_not_claim_to_be_a_server_error_by_accident(cls: type[AppError]):
    """
    Constructs each one and checks the status it actually carries.

    A genuine 500 is legitimate — some of these really are server faults — so this only
    fails when the class ALSO declares a different intent, which is the contradiction that
    produced the bug. Classes needing constructor arguments this cannot guess are skipped
    rather than failed: a test that cannot build the object has learned nothing about it.
    """
    try:
        instance = cls("test message")  # type: ignore[call-arg]
    except TypeError:
        pytest.skip(f"{cls.__qualname__} needs arguments this test cannot supply")

    declared = getattr(cls, "error_code", None) or cls.__dict__.get("status_code")
    if declared is None:
        return
    assert instance.status_code != 500, (
        f"{cls.__qualname__} declares an intent of its own but instances carry 500."
    )


#: MODULE LEVEL, NOT INSIDE THE TEST. FastAPI resolves a handler's annotations with
#: `get_type_hints`, which cannot see a class defined in a function body — so a locally
#: scoped Pydantic model is not recognised as a request body and is treated as a QUERY
#: model instead. The symptom is a confusing `query.payload: Field required` on a request
#: that plainly has a body, and it cost twenty minutes here.
class _BlankReason(BaseModel):
    reason: str = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("say something")
        return value.strip()


class _ShortReason(BaseModel):
    reason: str = Field(min_length=1, max_length=8)


def _probe_app(model: type[BaseModel]):
    """A one-route app wired to this project's real exception handlers."""
    from fastapi import FastAPI

    from app.core.exceptions import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    if model is _BlankReason:

        @app.post("/probe")
        async def probe_blank(payload: _BlankReason) -> dict:  # pragma: no cover
            return {"ok": payload.reason}
    else:

        @app.post("/probe")
        async def probe_short(payload: _ShortReason) -> dict:  # pragma: no cover
            return {"ok": payload.reason}

    return app


class TestAValidatorThatRaisesValueErrorIs422AndNot500:
    """
    A REAL BUG, FOUND BY ADDING THE FIRST BODY VALIDATOR TO THE REPORTS API.

    `handle_validation_error` passed `exc.errors()` straight into a JSONResponse. For a
    Pydantic v2 `value_error` — which is what any `field_validator` raising `ValueError`
    produces — that dict carries `ctx: {"error": ValueError(...)}`, and a raw exception
    object is not JSON-serialisable. So building the 422 response THREW, the throw fell
    through to the unhandled-exception handler, and the caller got a 500.

    IT WAS ALREADY LIVE. `api/v1/admin_offers.py` has five such validators — the offer kind,
    the value range, the percent bound, the item ids — and every one of them was answering
    500 to a request that was simply malformed. Nothing noticed, because a 500 on a bad
    admin request reads as a bug in the request.

    The second test is the other half of the fix: the response must not echo the input back.
    The structured log already redacts it, and an error body is a poor place to start
    reflecting a caller's own bytes.
    """

    def test_a_whitespace_only_string_is_rejected_with_422(self):
        from fastapi.testclient import TestClient

        response = TestClient(_probe_app(_BlankReason), raise_server_exceptions=False).post(
            "/probe", json={"reason": "   "}
        )

        assert response.status_code == 422, (
            f"a ValueError from a field validator returned {response.status_code}"
        )
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        # The validator's own message is authored by us, never by the caller, and is the
        # actionable half — it has to survive.
        assert "say something" in response.text

    def test_the_error_body_names_the_field_without_echoing_the_value(self):
        from fastapi.testclient import TestClient

        secret = "SENTINEL-a1b2c3-do-not-echo-this-back"
        response = TestClient(_probe_app(_ShortReason), raise_server_exceptions=False).post(
            "/probe", json={"reason": secret}
        )

        assert response.status_code == 422
        assert secret not in response.text, "the error response echoed the caller's input"
        # It still has to say WHICH field, or the message is useless to whoever must fix it.
        assert '"reason"' in response.text
        # And it must not name the dependency or its version.
        assert "pydantic.dev" not in response.text
