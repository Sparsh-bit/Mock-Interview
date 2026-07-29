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

# uv handles the Python deps (matches local dev).
RUN pip install --no-cache-dir uv

# App code + migrations (copy before sync so uv can build the local package
# reliably — a solo deploy favours a robust build over layer-cache micro-opts).
COPY backend/ /app/backend/
COPY database/ /app/database/
WORKDIR /app/backend
RUN uv sync --no-dev

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

# Apply migrations, seed the company interview research, then start Uvicorn.
# Render/Cloud Run inject $PORT.
#
# The research seed is idempotent (upserts by company+program) and only writes a
# handful of rows, so running it on every boot keeps production in sync with
# knowledge/research/*.yaml with no manual step. It is deliberately non-fatal:
# failing to refresh reference data must never stop the API from starting.
CMD ["sh", "-c", "uv run alembic upgrade head && (uv run python scripts/seed_db.py || echo 'catalogue seed skipped') && (uv run python scripts/seed_research.py || echo 'research seed skipped') && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
