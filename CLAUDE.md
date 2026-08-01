# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InterviewOS is an AI-powered mock interview simulation platform (currently scoped to Cognizant Digital Nurture / Java FSE prep). It runs adaptive interview sessions, scores answers across multiple vectors, detects confident-but-wrong ("bluffing") answers, and produces hire/no-hire style reports. Full product context and phased roadmap live in `prompt.md` at the repo root — read it before making architectural decisions, since it documents what's intentionally stubbed vs. fully wired.

This is an npm workspaces monorepo: `frontend` (Next.js) + `backend` (FastAPI/Python, managed with `uv`).

## Commands

Run from the repo root unless noted.

```bash
# Install
npm install                    # frontend + workspace tooling
cd backend && uv sync          # backend (Python deps via uv)

# Dev servers
npm run dev                    # both frontend (port 3000) and backend (port 8000) concurrently
npm run dev:frontend
npm run dev:backend            # cd backend && uv run uvicorn app.main:app --reload --port 8000

# Lint / typecheck
npm run lint                   # frontend eslint + backend ruff
cd backend && uv run mypy app  # backend typecheck (run separately, not in root script)

# Tests
npm run test                   # frontend vitest + backend pytest
npm run test -w frontend       # frontend only
cd backend && uv run pytest    # backend only
cd backend && uv run pytest tests/test_integration.py::test_name -v   # single backend test
npm run test:e2e -w frontend   # Playwright e2e

# Infra (Postgres + Redis for local dev)
docker-compose up -d

# DB migrations (Alembic config lives at repo root database/, not backend/)
cd backend && uv run alembic upgrade head
```

Backend lint/type config: `backend/pyproject.toml` (ruff line-length 100, target py311; mypy non-strict). Frontend uses `next lint` + `tsc --noEmit`.

## Architecture

### Backend (`backend/app`, FastAPI + async SQLAlchemy 2.0)

- **`core/config.py`** — single `Settings` source of truth via pydantic-settings. Loads `.env` from repo root or backend dir. There are no defaults for secrets — missing required env vars fail startup intentionally. Never read `os.environ` directly elsewhere; import `settings`.
- **`main.py`** — app factory with lifespan hooks: configures structlog, initializes the event bus, verifies DB/Redis connectivity at startup (hard-fails in production if DB is unreachable).
- **`api/v1/`** — versioned routers, one module per resource (`auth`, `users`, `questions`, `interview`, `reports`, `resume`, `health`), aggregated in `router.py`.
- **`models/`** — SQLAlchemy models split by domain (`user`, `company`, `question`, `session`, `report`, `system`), all UUID PKs, JSONB for flexible metadata. `models/base.py` has shared mixins.
- **`db/session.py`** / **`db/redis.py`** — async engine/session and Redis connection pooling. Redis backs caching, rate limiting, and the event bus.
- **`events/`** — in-process async `EventBus` (`event_bus.py`) for decoupled domain events (e.g. audit logging without blocking the HTTP response path). Handlers registered in `handlers.py`.
- **`services/ai/`** — AI provider abstraction. `base_provider.py` defines the interface; `glm_provider.py` is the current implementation (GLM via a NVIDIA NIM-compatible endpoint, configured through `AI_PROVIDER`/`GLM_*` env vars). `json_validator.py` + `response_parser.py` enforce that AI responses match required Pydantic shapes, retrying on malformed output. Swap providers by adding a new class conforming to `BaseAIProvider` and wiring it in `provider_factory.py` — don't special-case provider logic in callers.
- **`services/interview/orchestrator.py`** — intended to be the interview state machine (`pending` → `active` → `completed`, adaptive question selection). Per `prompt.md`, this is currently a simplified sequential-question stub, not the full adaptive engine — check current state before assuming adaptive behavior is live.
- **`prompts/`** — AI prompt templates as Markdown (`interviewer.md`, `resume_analyzer.md`, `report_generator.md`, `coding_evaluator.md`, `hr_interviewer.md`), loaded via `prompt_loader.py`. Edit prompts here rather than inlining prompt strings in service code.
- **`core/security.py`** — verifies Supabase-issued JWTs locally (no network round-trip to Supabase for auth checks).
- **`knowledge/`** — YAML-based question bank / interview pattern data (e.g. `knowledge/questions/java_core.yaml`), seeded into the DB rather than hardcoded.
- Database is Postgres (asyncpg) hosted on Supabase; `backend/alembic.ini` sets `script_location = ../database/migrations`, so the migration environment and versions live at repo-root `database/migrations/` (not under `backend/`) — run Alembic commands from `backend/` but be aware migrations live one level up.
- `events/event_bus.py` is a hand-rolled in-process async pub/sub (not Redis-backed) — explicitly designed to be swappable for Redis pub/sub or Kafka later; don't assume events cross process boundaries today.
- Only one backend test file currently exists: `backend/tests/test_integration.py`.

### Frontend (`frontend/src`, Next.js 15 App Router, React 19, TypeScript)

- Route groups: `app/(auth)` (login/register), `app/(dashboard)` (dashboard, tracks, interview setup, analytics, reports, profile, settings, achievements), `app/(interview)/session` (the live interview-taking flow) — these are separate layouts, not URL segments.
- **`lib/api/`** — hand-rolled isomorphic `ApiClient` (`client.ts`) used from both Server and Client Components, with pluggable `tokenProvider`, retry/backoff, and interceptor pipeline. `browser.ts` exposes a memoized singleton for Client Components (`getBrowserApiClient()`); a parallel server-side factory exists for Server Components — don't call the browser singleton during SSR. All backend calls should go through this client, not raw `fetch`.
- **`lib/supabase/`** — Supabase client setup for auth (session/token retrieval feeds the `ApiClient` token provider).
- **`middleware.ts`** — route protection based on Supabase auth session.
- State/data-fetching: TanStack Query wraps the `ApiClient`; don't introduce a second data-fetching layer (e.g. SWR) alongside it.
- Styling: Tailwind CSS v3 + shadcn/ui conventions, dark-mode-first design system defined in `tailwind.config.ts` / `globals.css`. Framer Motion for animation-heavy surfaces (landing page, dashboard).
- Frontend talks to the backend via `NEXT_PUBLIC_API_URL` (browser) / `INTERNAL_API_URL` (Next.js server-side rewrites in dev); both point at the FastAPI server on port 8000 locally. `next.config.ts` proxies `/api/v1/:path*` to the backend in dev, so client code can call same-origin paths.
- `components/` is currently thin (only `layout/{Header,Sidebar}.tsx` and `providers.tsx`) — the shadcn/ui component library described in `prompt.md` is aspirational/in-progress, not fully built out yet.

## Working notes

- `prompt.md` tracks phase-by-phase project status (what's built vs. stubbed vs. planned). Treat it as living project context, not just a README — check it when unsure whether a feature (e.g. adaptive questioning, voice mode, PDF reports, Stripe billing) is actually implemented or still a placeholder.
- `.env.example` currently contains real-looking Supabase/DB and AI provider credentials rather than placeholders — treat these as sensitive; do not copy them into commits, logs, or new example files, and flag if asked to regenerate this file.
- CI (`.github/workflows/ci.yml`) only runs lint + typecheck for both frontend and backend — it does not run the test suites and there is no deploy step. Don't assume passing CI means tests passed.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
