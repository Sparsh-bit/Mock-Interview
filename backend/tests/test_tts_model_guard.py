"""
A retired Fish backend is refused, not attempted — tests/test_tts_model_guard.py

REPORTED: "the fish audio api is not working properly the voice is changing to the older
voices". Diagnosed against the live API, and it was two faults stacked:

  1. THE ACCOUNT HAS NO API CREDIT. Every current backend — s1, speech-1.6, speech-1.5,
     s1-mini, and no model header at all — answers HTTP 402 in under a second: "Insufficient
     API credit. API credit is managed independently from platform credit." The key itself is
     valid; `GET /model` returns 200 with it. So neural speech cannot work until API credit is
     topped up, and that is an account action, not a code change.

  2. THE CONFIGURED BACKEND WAS RETIRED, AND A RETIRED FISH BACKEND HANGS. `s2.1-pro-free`
     was this repo's default and its config note claimed it "returns real audio on a
     zero-credit key in ~3.5s" — true when written, false now. Retested: the TCP connect and
     the TLS handshake succeed and then nothing comes back. Measured at 35s and at 60s.

FAULT 2 IS WHY THE SYMPTOM WAS "THE VOICES CHANGE" RATHER THAN "THERE ARE NO VOICES". A 402
is instant, so the client's degrade latch closes before the first word and the whole round
runs on browser speech — consistent, and obviously worse, but not confusing. A hang makes the
first line wait out the 12s client timeout in silence and only then fall back, so the panel
starts on one voice and continues on another. And `httpx` raises `ReadTimeout` with an EMPTY
message, so the log line read "fish request failed: " and named nothing.

These tests pin the guard. They make no network calls: the whole point is that a retired
model is refused before a request is ever made.
"""

from __future__ import annotations

import pytest

from app.services.tts import factory
from app.services.tts.base import TTSError


@pytest.fixture(autouse=True)
def _reset_provider_singleton():
    """
    The factory memoises into a module global. Without this the first test to build a
    provider would serve it to all the others and the config changes below would do nothing.
    """
    factory._provider = None
    yield
    factory._provider = None


class TestARetiredBackendIsRefused:
    def test_the_one_that_was_actually_configured(self, monkeypatch):
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "fish")
        monkeypatch.setattr(factory.settings, "FISH_MODEL", "s2.1-pro-free")
        with pytest.raises(TTSError, match="retired"):
            factory.get_tts_provider()

    def test_the_message_names_the_fix_and_the_separate_credit(self, monkeypatch):
        """
        An operator reading this has to learn two things they cannot guess: which models are
        current, and that Fish bills API credit separately from platform credit — which is
        why an account with a paid subscription can still be refused.
        """
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "fish")
        monkeypatch.setattr(factory.settings, "FISH_MODEL", "s2.1-pro-free")
        with pytest.raises(TTSError) as excinfo:
            factory.get_tts_provider()
        message = str(excinfo.value)
        assert "s1" in message
        assert "API credit" in message
        assert "separately from platform credit" in message

    @pytest.mark.parametrize("model", sorted(factory._RETIRED_FISH_MODELS))
    def test_every_listed_retirement_is_refused(self, model: str, monkeypatch):
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "fish")
        monkeypatch.setattr(factory.settings, "FISH_MODEL", model)
        with pytest.raises(TTSError):
            factory.get_tts_provider()


class TestACurrentBackendIsBuilt:
    @pytest.mark.parametrize("model", ["s1", "speech-1.6", "speech-1.5", "s1-mini"])
    def test_the_models_that_answer_are_accepted(self, model: str, monkeypatch):
        """
        Verified live: each of these answers in under a second. On a key with no API credit
        that answer is a 402 — which is the honest state of the account rather than a hang,
        and the client turns it into an immediate, permanent fall back to browser speech.
        """
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "fish")
        monkeypatch.setattr(factory.settings, "FISH_MODEL", model)
        monkeypatch.setattr(factory.settings, "FISH_API_KEY", "sk-test-not-a-real-key")
        provider = factory.get_tts_provider()
        assert provider.provider_name == "fish"

    def test_the_default_in_config_is_not_a_retired_one(self):
        """
        THE ONE THAT WOULD HAVE CAUGHT IT. The retired backend was the DEFAULT in
        core/config.py, so a fresh checkout and any deployment that never set the variable
        both got the hang. Guarding only the runtime path would leave that intact.
        """
        from app.core.config import Settings

        default = Settings.model_fields["FISH_MODEL"].default
        assert default not in factory._RETIRED_FISH_MODELS, (
            f"FISH_MODEL defaults to {default!r}, which is retired — a fresh checkout would "
            "hang on every line instead of failing fast"
        )


class TestTheStatusEndpointSaysWhyItIsOff:
    """
    "i cannot still listen the fish audio voices i can only listen the default browser voices."

    The account was funded ($10 balance), the key was Active, the voice ids were correct, and
    the Fish dashboard showed ZERO requests and no usage data for the key. Zero requests is
    the tell: the client asks /tts/status once per round and, told `enabled: false`, correctly
    stops asking. So nothing reached the vendor, nothing appeared on their dashboard, and there
    was nothing anywhere to read.

    `enabled: false` was returned identically for FOUR different causes:

        TTS_ENABLED is false
        FISH_API_KEY is not set
        FISH_MODEL names a retired backend
        the daily TTS budget is spent

    and the endpoint caught the provider's own exception and threw the message away. An
    operator could not tell which of the four they had, and neither could anybody reading this
    code. That is the same defect as the Fish client raising ReadTimeout with an empty message
    and the AI provider logging a failure without its reason — three instances of one habit.

    ADMIN-ONLY IN THE RESPONSE, AND ALWAYS IN THE LOGS. "FISH_API_KEY is not set" names the
    vendor and admits a misconfiguration, and this product was explicitly told to keep
    deployment detail out of the browser. The operator needs it; a candidate must not have it.
    """

    def test_the_status_model_carries_a_reason(self):
        from app.api.v1.tts import TTSStatus

        assert "reason" in TTSStatus.model_fields
        # Defaults to empty, so a healthy response says nothing and no caller has to special-case it.
        assert TTSStatus.model_fields["reason"].default == ""

    def test_every_disabled_path_fills_it(self):
        import inspect

        from app.api.v1 import tts

        src = inspect.getsource(tts.tts_status)
        # The four causes, each named where it is detected.
        assert "TTS_ENABLED is false" in src
        assert "daily TTS budget spent" in src
        # The provider's own message, not a generic string — it is what distinguishes a missing
        # key from a retired model.
        assert "str(exc) or type(exc).__name__" in src

    def test_a_provider_that_cannot_be_built_is_logged_at_error(self):
        """
        The one place in this codebase where a TTS failure IS an error rather than an info.
        Everywhere else, degrading to browser speech is a normal operating state. Here
        TTS_ENABLED is true — the operator has asked for neural speech and the provider cannot
        be constructed at all. That will not fix itself, and every round until it is fixed is
        silently worse.
        """
        import inspect

        from app.api.v1 import tts

        src = inspect.getsource(tts.tts_status)
        assert 'logger.error(\n            "tts_provider_unavailable"' in src
        # The two values that identify the cause without a redeploy.
        assert "provider=settings.TTS_PROVIDER" in src
        assert "model=settings.FISH_MODEL" in src

    def test_the_reason_is_withheld_from_ordinary_users(self):
        import inspect

        from app.api.v1 import tts

        src = inspect.getsource(tts.tts_status)
        assert "def _for(reason: str) -> str:" in src
        assert "return reason if is_admin else \"\"" in src

    def test_admin_is_read_from_the_contextvar_and_not_off_current_user(self):
        """
        THE MISTAKE THIS ASSERTION EXISTS FOR, made while writing the fix above.

        AuthenticatedUser carries id, supabase_uid and email — NOT is_admin. Every other admin
        check in this codebase runs a separate `select(User.is_admin)`. So
        `getattr(current_user, "is_admin", False)` is False for everybody, always: the reason
        would have been invisible to the one person who needs it, while looking like it worked.
        """
        import inspect

        from app.api.v1 import tts
        from app.core.security import AuthenticatedUser

        # Asserted on the class rather than an instance: __init__ takes real arguments and
        # constructing one here would test the constructor, not the absence of the attribute.
        assert "is_admin" not in inspect.getsource(AuthenticatedUser)
        # Comments stripped, because the fix's own comment QUOTES the mistake it describes —
        # so an assertion over the raw source would match the explanation and fail. Same
        # convention as components/account-isolation.test.ts: no assertion may be satisfied,
        # or defeated, by its own prose.
        code = "\n".join(
            line.split("#", 1)[0] for line in inspect.getsource(tts.tts_status).splitlines()
        )
        assert "current_user_is_admin.get()" in code
        assert 'getattr(current_user, "is_admin"' not in code
