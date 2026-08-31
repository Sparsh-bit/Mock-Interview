"""What the production image is allowed to contain.

Everything here was verified once by building the image and reading its layers. These tests
are the cheap standing version of that: they pin the two declarations that decide the answer,
so the next person to edit them finds out at `pytest` time rather than after an image has
been pushed and the credentials in it have to be rotated.

The build itself is not run here — it needs a Docker daemon and ~90 seconds, which does not
belong in a unit suite. `.github/workflows/image-scan.yml` builds and scans the real thing.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCKERIGNORE = REPO / ".dockerignore"
DOCKERFILE = REPO / "Dockerfile"


@pytest.fixture(scope="module")
def dockerignore() -> str:
    return DOCKERIGNORE.read_text()


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text()


class TestSecretsCannotBeCopiedIn:
    """The Dockerfile does `COPY backend/ /app/backend/`, so whatever sits in that directory
    on the builder's machine goes into the image. backend/.env is a location core/config.py
    genuinely supports, and it exists on this machine right now."""

    def test_the_dockerignore_exists_at_all(self):
        # It did not, once. That is the whole reason this file exists.
        assert DOCKERIGNORE.exists()

    @pytest.mark.parametrize("pattern", [".env", ".env.*", "**/.env", "**/.env.*"])
    def test_env_files_are_excluded_at_every_depth(self, dockerignore, pattern):
        # `.env` alone does not cover `backend/.env` — Docker matches from the context root.
        assert pattern in dockerignore.splitlines()

    def test_the_example_is_re_included(self, dockerignore):
        # Placeholders only, and something in the image may want to read the shape.
        assert "!.env.example" in dockerignore

    @pytest.mark.parametrize("pattern", ["*.pem", "*.key", "*.p12", "secrets/"])
    def test_other_credential_shapes_are_excluded(self, dockerignore, pattern):
        assert pattern in dockerignore.splitlines()


class TestNoWheelCacheReachesTheImage:
    """A wheel cache is a second, independent set of .dist-info directories. The image scanner
    reads versions out of .dist-info, so a cache reports package versions that upgrading
    site-packages cannot correct. This has already produced one false-but-accurate finding —
    Trivy reporting PyJWT 2.8.0 and cryptography 49.0.0 after both were upgraded, because it
    was reading the cache."""

    def test_the_host_cache_is_excluded(self, dockerignore):
        assert "**/.uv_cache" in dockerignore.splitlines()

    def test_the_build_does_not_leave_uvs_own_cache_behind(self, dockerfile):
        # The other half. Excluding the host cache does nothing about the one `uv sync`
        # writes to /root/.cache/uv inside the image — 143 MB and 83 .dist-info directories
        # when this was measured. Nothing reads it at runtime; appuser cannot even open it.
        sync = [ln for ln in dockerfile.splitlines() if ln.startswith("RUN uv sync")]
        assert sync, "no `RUN uv sync` line found — has the Dockerfile been restructured?"
        for line in sync:
            assert "--no-cache" in line, f"uv sync leaves its cache in the image: {line!r}"


class TestNoHostPlatformVenv:
    """backend/.venv on this machine is a macOS/aarch64 virtualenv with absolute host paths
    baked into its scripts. Copied into a linux image it is wrong architecture and dead
    weight; the image builds its own with `uv sync`."""

    def test_venvs_are_excluded(self, dockerignore):
        lines = dockerignore.splitlines()
        assert "**/.venv" in lines
        assert "**/venv" in lines

    def test_the_image_builds_its_own(self, dockerfile):
        assert "RUN uv sync" in dockerfile


class TestDevelopmentArtefactsStayOut:
    @pytest.mark.parametrize(
        "pattern",
        ["**/__pycache__", "**/.mypy_cache", "**/.ruff_cache", "**/.pytest_cache", "backend/tests"],
    )
    def test_excluded(self, dockerignore, pattern):
        assert pattern in dockerignore.splitlines()
