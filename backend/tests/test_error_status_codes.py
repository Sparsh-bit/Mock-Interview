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
