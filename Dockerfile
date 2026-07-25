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

EXPOSE 8000

# Apply migrations, then start Uvicorn. Render/Cloud Run inject $PORT.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
