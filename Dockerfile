# Production image for the InterviewOS FastAPI backend.
# Build context must be the REPO ROOT (not backend/), because Alembic migrations
# live in ../database/migrations relative to backend/ (see backend/alembic.ini).
#
# Used by Render (and any container host). Runs DB migrations on start, then
# serves the ASGI app on $PORT.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# ── Patch the base image before installing anything ───────────────────────
#
# NOT HOUSEKEEPING. `python:3.13-slim` is rebuilt on its own schedule, so between rebuilds it
# carries whatever Debian security updates have been published since — and the image scan
# (.github/workflows/image-scan.yml) fails the build on any HIGH or CRITICAL with a fix
# available. The one that caught this was CVE-2026-14456 in openssl/libssl3t64, fixed in
# 3.5.7-1~deb13u2 while the base still shipped 3.5.6-1~deb13u2. Every TLS connection this
# service makes — Supabase, the model providers, Razorpay — goes through that library.
#
# `upgrade`, not `dist-upgrade`: this must not pull in a new libc or change the base
# distribution underneath a Python built against it. The lists are removed in the same layer,
# or they stay in the image for nothing.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# uv handles the Python deps (matches local dev).
#
# COPIED FROM ASTRAL'S OWN IMAGE RATHER THAN `pip install uv`, AND PIP IS THEN REMOVED.
#
# This started as a smaller change — `pip install --upgrade setuptools uv` — to clear
# CVE-2025-47273 in the base image's setuptools. It did not clear it, and the scan showed why:
# the remaining HIGH findings were not the INSTALLED setuptools (84.0.0, fine) but copies
# VENDORED INSIDE PIP — pip/_vendor/msgpack (GHSA-6v7p-g79w-8964) and pip's bundled setuptools
# metadata at 70.3.0. Upgrading the outer package cannot reach them; only removing pip does.
#
# Which is the right answer anyway: a production image does not need a package manager. Nothing
# in CMD calls pip — alembic, the seed scripts and uvicorn all run through uv, and uv resolves
# and builds with its own frontend. Removing it deletes a whole class of finding that this
# repository can never fix, because the vulnerable code belongs to pip's vendor tree.
#
# The uv version is PINNED. `:latest` would make the image non-reproducible and would let a uv
# release change dependency resolution between two builds of the same commit.
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /usr/local/bin/
RUN python -m pip uninstall -y pip 2>/dev/null || true

# App code + migrations (copy before sync so uv can build the local package
# reliably — a solo deploy favours a robust build over layer-cache micro-opts).
COPY backend/ /app/backend/
COPY database/ /app/database/
WORKDIR /app/backend
# --no-cache: uv otherwise leaves its download cache at /root/.cache/uv — 143 MB of wheel
# archives carrying 83 .dist-info directories. That is the same defect .dockerignore already
# fixes for the HOST cache (backend/.uv_cache), relocated: the image scanner reads package
# versions out of .dist-info, and a cache is a second, independent set of them that no
# upgrade to site-packages can ever correct. It happened once already — Trivy kept reporting
# PyJWT 2.8.0 and cryptography 49.0.0 after both were upgraded. Nothing reads the cache at
# runtime (appuser cannot even open /root), so it is pure weight and pure risk.
RUN uv sync --no-dev --no-cache

# ── Drop root ─────────────────────────────────────────────────────────────
# The container defaults to running as root, which means a remote-code-execution
# bug anywhere in the app — or in any dependency — would own the whole container
# rather than one unprivileged account. Nothing here needs root at runtime: the
# app writes no files outside /tmp and binds a high port.
#
# Done AFTER dependency install so the build steps keep root and the resulting
# tree stays owned correctly.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Boot work, then Uvicorn. Render/Cloud Run inject $PORT.
#
# THE MIGRATION AND THE SEEDS ARE NOT RUN DIRECTLY HERE ANY MORE, and the indirection is
# the point. This chain runs in EVERY replica. Two replicas booting a deploy that carries a
# migration used to apply the same DDL at the same time — the second one got "relation
# already exists", `alembic` exited non-zero, the `&&` short-circuited, and that replica
# never started Uvicorn at all. scripts/boot.py takes a Postgres advisory lock so the work
# happens once between them; it keeps the same fatal/non-fatal split the old chain had
# (a failed migration stops the boot, a failed reference-data seed does not) and the same
# reason for it: the research seed is an idempotent upsert that keeps production in step
# with knowledge/research/*.yaml, and failing to refresh reference data must never stop the
# API from starting.
#
# render.yaml's `preDeployCommand` is the better place for this and runs it once per deploy
# before any instance starts. scripts/boot.py is what keeps the container correct without
# it — under docker-compose, and on any plan with no pre-deploy hook.
CMD ["sh", "-c", "uv run python scripts/boot.py && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
