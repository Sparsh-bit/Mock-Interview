"""
What `Settings` is allowed to say about itself, and why it is not a pytest hook.

THE LEAK. Pydantic generates a repr containing every field value. On a machine with a
real .env that is 4.5 KB including the Supabase JWT secret (signs every auth token),
the service key (bypasses Row Level Security entirely), both model-provider keys and
the database password.

Nobody has to write that string for it to escape. pytest prints the repr of every
local in a failing frame, so ONE failing assertion in a test that happens to hold
`settings` publishes all of it into a CI log — and CI logs are readable by everyone
who can read the build, outlive the branch, and are the last place anyone looks for a
credential. `logger.exception` in a request handler does the same thing, so does a
Sentry event that got past the scrubber, and so does a debugger.

WHY THE FIX IS ON THE CLASS AND NOT IN conftest.py. A pytest hook that scrubs failure
output covers pytest. It does not cover the other three, and the object is the same
object in all four.

TWO SEPARATE HOLES, and the second is easy to miss: `__repr__` covers a Settings that
was successfully built. A Settings that FAILS to build raises pydantic's
ValidationError, and every error in it carries `input_value` — for a BaseSettings, the
whole environment-derived dict. That path never touches `__repr__`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import (
    REDACTED_VALUE,
    Settings,
    _is_secret_name,
    _redact_url_credentials,
    settings,
)

BACKEND = Path(__file__).resolve().parents[1]

#: Anything at least this long that is not in the allowlist below is treated as a
#: credential by `test_no_long_opaque_value_survives`. Short enough to catch a 32-char
#: key, long enough not to trip on "postgresql+asyncpg" or a CORS origin.
OPAQUE_LENGTH = 24


class TestTheFieldsThatActuallyHoldCredentials:
    """Named individually rather than looped, so a failure says which one."""

    @pytest.mark.parametrize(
        "field",
        [
            "SUPABASE_JWT_SECRET",
            "SUPABASE_SERVICE_KEY",
            "SUPABASE_ANON_KEY",
            "SECRET_KEY",
            "GLM_API_KEY",
            "ANTHROPIC_API_KEY",
            "NVIDIA_API_KEY",
            "RAZORPAY_KEY_ID",
            "RAZORPAY_KEY_SECRET",
            "RAZORPAY_WEBHOOK_SECRET",
            "ELEVENLABS_API_KEY",
            "FISH_API_KEY",
            "SENTRY_DSN",
        ],
    )
    def test_the_name_is_recognised_as_secret(self, field):
        # Whether or not it is populated on this machine — the rule must not depend
        # on whether the developer running the suite happens to have configured it.
        if not hasattr(Settings, "model_fields") or field not in Settings.model_fields:
            pytest.skip(f"{field} is not a setting on this version of the class")
        assert _is_secret_name(field), (
            f"{field} would be printed in full. Add its distinguishing word to "
            f"_SECRET_NAME_PARTS in core/config.py."
        )

    def test_no_populated_secret_value_appears_in_the_repr(self):
        """The end-to-end version, against whatever this machine actually has set."""
        rendered = repr(settings)
        for name in Settings.model_fields:
            value = getattr(settings, name, None)
            if isinstance(value, str) and value and _is_secret_name(name):
                assert value not in rendered, f"{name} was printed in full"

    def test_str_is_redacted_too(self):
        """`str()` does NOT fall back to `__repr__` when the class defines `__str__`,
        and pydantic's BaseModel defines one. An f-string is the most likely way this
        object ends up in a log line."""
        assert str(settings) == repr(settings)
        assert f"{settings}" == repr(settings)


class TestCredentialsInsideAValue:
    """DATABASE_URL and REDIS_URL match no name pattern — the credential is in the
    value, not named by the key — and DATABASE_URL holds the database password."""

    def test_a_url_password_is_removed(self):
        out = _redact_url_credentials("postgresql+asyncpg://admin:hunter2@db.example.com:5432/app")
        assert "hunter2" not in out
        assert REDACTED_VALUE in out

    def test_the_useful_parts_survive(self):
        # Which database, as whom. Blanking the whole URL would make the repr useless
        # for the thing a repr is for.
        out = _redact_url_credentials("postgresql+asyncpg://admin:hunter2@db.example.com:5432/app")
        assert "db.example.com:5432/app" in out
        assert "admin" in out
        assert out.startswith("postgresql+asyncpg://")

    def test_a_url_with_no_password_is_untouched(self):
        plain = "redis://localhost:6379/0"
        assert _redact_url_credentials(plain) == plain

    def test_the_live_database_url_is_redacted_in_the_repr(self):
        password = re.search(r"://[^:/@\s]+:([^@/\s]+)@", settings.DATABASE_URL)
        if not password:
            pytest.skip("DATABASE_URL on this machine carries no password")
        assert password.group(1) not in repr(settings)


class TestNothingOpaqueSurvivesThatNobodyThoughtOf:
    """The parametrised list above is a list somebody has to remember to extend. This
    is the backstop: any long opaque string in the repr is a finding, whatever it is
    called."""

    #: Long values that are legitimately printable. Each is here because it is
    #: non-secret by nature, not because it happened to trip the check.
    ALLOWED_SUBSTRINGS = (
        "http://localhost",
        "http://127.0.0.1",
        "https://",  # base URLs for providers; public endpoints
        "postgresql",
        "redis://",
        "claude-",
        "gpt-",
        "glm-",
        "/api/",
    )

    #: Whole fields exempted by NAME rather than by substring. A substring wide enough
    #: to cover these two ("nvidia/", or ":" for the voice map) would also cover most
    #: of what the check exists to catch, which would make it quietly vacuous.
    ALLOWED_FIELDS = frozenset(
        {
            # A model identifier, e.g. "nvidia/nemotron-...".
            "NVIDIA_MODEL",
            # A "Name:voiceid,..." map. Voice ids are vendor catalogue identifiers and
            # authorise nothing without the API key, which IS redacted. docs/VOICES.md.
            "TTS_VOICE_IDS",
        }
    )

    def test_no_long_opaque_value_survives(self):
        rendered = repr(settings)
        # NAME='value' pairs. A bare `'([^']{24,})'` also matches the run of text
        # between one value's closing quote and the next value's opening quote.
        for name, value in re.findall(r"(\w+)='([^']*)'", rendered):
            if len(value) < OPAQUE_LENGTH:
                continue
            if REDACTED_VALUE in value:
                continue
            if name in self.ALLOWED_FIELDS:
                continue
            if any(allowed in value for allowed in self.ALLOWED_SUBSTRINGS):
                continue
            pytest.fail(
                f"{name} prints a {len(value)}-character opaque value in full: "
                f"{value[:8]}... — if it is not a credential add it to "
                f"ALLOWED_SUBSTRINGS, if it is, fix _SECRET_NAME_PARTS."
            )


class TestTheConstructionFailurePath:
    """`__repr__` only helps a Settings that was built. One that fails to build raises
    pydantic's ValidationError, whose `input_value` is the whole env-derived dict."""

    def test_a_missing_variable_does_not_print_the_others(self, monkeypatch):
        from app.core import config

        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        # A sentinel that would be in the input dict pydantic echoes back. Assembled
        # at runtime so the literal does not appear in this file — pytest prints the
        # failing test's own source, which would match the search below and turn a
        # passing test into a false failure.
        sentinel = "sentinel-" + "service-key-" + "do-not-print-me"
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", sentinel)
        # model_config is a plain dict; without this the repo .env supplies the
        # variable back and the construction never fails.
        monkeypatch.setitem(config.Settings.model_config, "env_file", None)

        config.get_settings.cache_clear()
        try:
            with pytest.raises(RuntimeError) as caught:
                config.get_settings()
        finally:
            config.get_settings.cache_clear()

        rendered = str(caught.value)
        assert sentinel not in rendered, (
            "the ValidationError echoed the whole settings input back"
        )
        # Still says what to do about it.
        assert "SUPABASE_JWT_SECRET" in rendered
        assert "Field required" in rendered

    def test_the_original_is_not_chained(self, monkeypatch):
        """`raise ... from None`. Chaining would print the ValidationError under
        'The above exception was the direct cause', which is the thing being suppressed."""
        from app.core import config

        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        # model_config is a plain dict; without this the repo .env supplies the
        # variable back and the construction never fails.
        monkeypatch.setitem(config.Settings.model_config, "env_file", None)
        config.get_settings.cache_clear()
        try:
            with pytest.raises(RuntimeError) as caught:
                config.get_settings()
        finally:
            config.get_settings.cache_clear()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None or caught.value.__suppress_context__


class TestAgainstRealPytestFailureOutput:
    """
    The claim is about what lands in a CI log, so this measures a CI log: a real
    pytest process, a real failing assertion holding `settings`, and a search of
    everything it printed for the real values this machine has configured.

    Run out-of-process because pytest's assertion rewriting and local-variable
    reporting are what is under test, and they only happen in a real run.
    """

    FAILING_TEST = '''
from app.core.config import settings


def test_deliberately_fails_while_holding_settings():
    config = settings                      # a local, so pytest prints its repr
    also = {"cfg": settings, "url": settings.DATABASE_URL}
    assert config.APP_NAME == "this assertion is meant to fail", also
'''

    def test_a_failing_test_prints_no_real_secret(self, tmp_path):
        from app.core.config import Settings
        from app.core.config import settings as live

        target = tmp_path / "test_leak_probe.py"
        target.write_text(self.FAILING_TEST)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(target), "-vv", "-l", "--tb=long", "--no-cov", "-p",
             "no:cacheprovider"],
            capture_output=True,
            text=True,
            cwd=BACKEND,
        )
        output = result.stdout + result.stderr

        assert "test_deliberately_fails_while_holding_settings" in output, (
            f"the probe test did not run at all:\n{output[-2000:]}"
        )
        assert result.returncode != 0, "the probe was supposed to fail"

        leaked = []
        for name in Settings.model_fields:
            value = getattr(live, name, None)
            if (
                isinstance(value, str)
                and len(value) >= OPAQUE_LENGTH
                and _is_secret_name(name)
                and value in output
            ):
                leaked.append(name)

        assert not leaked, (
            f"pytest's failure output contains the real value of: {', '.join(leaked)}. "
            f"This is what reaches CI logs."
        )

    def test_the_probe_would_have_caught_the_old_behaviour(self, tmp_path):
        """A leak test that cannot fail proves nothing. This asserts the search above
        genuinely finds a secret when one IS printed, by printing one on purpose."""
        from app.core.config import Settings
        from app.core.config import settings as live

        secret_field = next(
            (
                name
                for name in Settings.model_fields
                if _is_secret_name(name)
                and isinstance(getattr(live, name, None), str)
                and len(getattr(live, name)) >= OPAQUE_LENGTH
            ),
            None,
        )
        if secret_field is None:
            pytest.skip("no populated secret on this machine to prove the detector with")

        target = tmp_path / "test_leak_control.py"
        target.write_text(
            "from app.core.config import settings\n\n\n"
            "def test_prints_a_secret_on_purpose():\n"
            f"    leaked = settings.{secret_field}\n"
            "    assert leaked == 'nope', leaked\n"
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(target), "-vv", "-l", "--no-cov", "-p",
             "no:cacheprovider"],
            capture_output=True,
            text=True,
            cwd=BACKEND,
        )
        output = result.stdout + result.stderr
        assert getattr(live, secret_field) in output, (
            "the detector cannot see a secret even when one is deliberately printed — "
            "the test above is vacuous"
        )


class TestTheConftestLayer:
    """
    The class-level fix cannot help a test that pulls a value out itself —

        assert x == y, {"jwt": settings.SUPABASE_JWT_SECRET}

    by then it is a plain `str` and no `__repr__` is consulted. conftest.py scrubs the
    rendered report for exactly this. It only applies to tests under tests/, so the
    probe has to live there rather than in tmp_path.
    """

    PROBE = '''
from app.core.config import settings


def test_probe_fails_on_purpose():
    ctx = {"cfg": settings, "jwt": settings.SUPABASE_JWT_SECRET}
    print("stdout:", settings.SUPABASE_SERVICE_KEY)
    assert settings.APP_NAME == "DELIBERATE FAILURE", ctx
'''

    def test_a_directly_extracted_secret_is_scrubbed_from_the_report(self):
        from app.core.config import Settings, _is_secret_name
        from app.core.config import settings as live

        probe = BACKEND / "tests" / "test_zz_conftest_scrub_probe.py"
        probe.write_text(self.PROBE)
        try:
            result = subprocess.run(
                # No -s: that disables capture entirely and is not what CI runs.
                [sys.executable, "-m", "pytest", str(probe), "-vv", "-l", "--tb=long",
                 "--no-cov", "-p", "no:cacheprovider"],
                capture_output=True,
                text=True,
                cwd=BACKEND,
            )
        finally:
            probe.unlink(missing_ok=True)

        output = result.stdout + result.stderr
        assert result.returncode != 0, f"the probe was supposed to fail:\n{output[-1500:]}"

        leaked = [
            name
            for name in Settings.model_fields
            if _is_secret_name(name)
            and isinstance(getattr(live, name, None), str)
            and len(getattr(live, name)) >= OPAQUE_LENGTH
            and getattr(live, name) in output
        ]
        assert not leaked, (
            f"these reached the failure report even with the conftest hook: {leaked}"
        )

    def test_the_hook_leaves_passing_runs_alone(self):
        """It rewrites `longrepr` only when a secret is actually present. A green run
        must not pay for that, and must not have its output altered."""
        from tests.conftest import _scrub

        untouched = "nothing secret here at all"
        assert _scrub(untouched, ["some-real-secret-value"]) == untouched

    def test_it_replaces_the_longest_match_first(self):
        """A DSN can embed a key. Shortest-first would replace the inner value and
        leave the outer one half-redacted and still identifying."""
        from tests.conftest import _scrub

        key = "abcdefghijklmnop"
        dsn = f"https://{key}@sentry.example.com/1"
        out = _scrub("see " + dsn, sorted([key, dsn], key=len, reverse=True))
        assert key not in out
        assert "sentry.example.com" not in out
