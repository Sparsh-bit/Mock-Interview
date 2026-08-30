"""
The GLM SDK still signs its own tokens after PyJWT was forced past its pin.

WHY THIS FILE EXISTS. `zhipuai` requires `pyjwt >=2.8.0,<2.9.0`, and 2.8.0 carries two HIGH
advisories (CVE-2026-32597, CVE-2026-48526) fixed in 2.12.0 and 2.13.0. The upper bound means
no ordinary resolution can take the fix, so the production image shipped a vulnerable JWT
library and the Trivy gate failed the build — correctly.

`[tool.uv] override-dependencies` forces PyJWT forward past that pin. Overriding a declared
constraint is exactly the kind of change that works on the day it is made and breaks silently
later, and the failure would be invisible in every other test: nothing else in this suite
calls the GLM SDK's token signer, so a break would first appear as 401s from the model
provider in production, reported as "the AI is down".

THE APPLICATION'S OWN JWT VERIFICATION IS NOT INVOLVED. core/security.py uses python-jose, not
PyJWT, so this is only about zhipuai signing outbound API tokens — which is also why the
override was judged safe: nothing attacker-controlled reaches this path.
"""

from __future__ import annotations

import jwt
import pytest
from zhipuai.core._jwt_token import generate_token

# A structurally valid GLM key: `<id>.<secret>`. Not a real credential and does not need to
# be — the signer never contacts anything.
FAKE_KEY = "abcdef0123456789.0123456789abcdef"


def test_pyjwt_is_past_the_versions_with_advisories():
    """
    The reason the override exists. If a future resolution drops back below 2.13.0 — a
    lockfile regenerated without the override, say — the image goes back to shipping a
    vulnerable JWT library and the only other thing that would notice is a CI run that
    already takes several minutes to get there.
    """
    major, minor, *_ = (int(part) for part in jwt.__version__.split(".")[:2])
    assert (major, minor) >= (2, 13), (
        f"PyJWT is {jwt.__version__}; CVE-2026-32597 and CVE-2026-48526 are fixed in 2.12.0 "
        f"and 2.13.0. Check that [tool.uv] override-dependencies is still in pyproject.toml."
    )


def test_the_glm_sdk_still_produces_a_token():
    token = generate_token(FAKE_KEY)
    assert isinstance(token, str)
    assert token.count(".") == 2, "not a three-part JWT"


def test_the_token_keeps_the_shape_the_glm_api_expects():
    """
    GLM rejects a token whose header lacks `sign_type: SIGN`, and the payload must carry the
    key id, an expiry and a timestamp. A PyJWT change that altered header handling would
    produce a token that still parses locally and is refused by the provider — which is the
    failure mode worth pinning, because it looks like an outage rather than a dependency.
    """
    token = generate_token(FAKE_KEY)

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
    assert header["sign_type"] == "SIGN"

    payload = jwt.decode(
        token,
        FAKE_KEY.split(".")[1],
        algorithms=["HS256"],
        # The signer sets no audience, so verification must not demand one.
        options={"verify_aud": False},
    )
    assert payload["api_key"] == FAKE_KEY.split(".")[0]
    assert payload["exp"] > payload["timestamp"]


def test_a_malformed_key_is_refused_rather_than_signed():
    # A key with no `.` is a configuration mistake. Signing it would produce a token the
    # provider rejects, which reads as an outage instead of a bad setting.
    #
    # The SDK raises a bare `Exception` wrapping the ValueError, so the assertion is on the
    # MESSAGE rather than the type — `pytest.raises(Exception)` would also pass if the call
    # started failing for an entirely unrelated reason, which is the shape ruff's B017 is
    # warning about.
    with pytest.raises(Exception, match="invalid api_key"):
        generate_token("no-separator-here")
