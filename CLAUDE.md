# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InterviewOS is an AI-powered mock interview simulation platform (currently scoped to Cognizant Digital Nurture / Java FSE prep). It runs adaptive interview sessions, scores answers across multiple vectors, detects confident-but-wrong ("bluffing") answers, and produces hire/no-hire style reports. Full product context and phased roadmap live in `docs/prompt.md` — read it before making architectural decisions, since it documents what's intentionally stubbed vs. fully wired.

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
- **`services/interview/orchestrator.py`** — intended to be the interview state machine (`pending` → `active` → `completed`, adaptive question selection). Per `docs/prompt.md`, this is currently a simplified sequential-question stub, not the full adaptive engine — check current state before assuming adaptive behavior is live.
- **`prompts/`** — AI prompt templates as Markdown (`interviewer.md`, `resume_analyzer_skills.md` + `resume_analyzer_projects.md`, `report_generator.md`, `coding_evaluator.md`, `hr_interviewer.md`), loaded via `prompt_loader.py`. Edit prompts here rather than inlining prompt strings in service code.
- **`core/security.py`** — verifies Supabase-issued JWTs locally (no network round-trip to Supabase for auth checks).
- **`knowledge/`** — YAML reference data that is hand-maintained and read at runtime: the campus-recruiter catalogue (`knowledge/companies/catalogue.yaml`) and the study-roadmap subtopics (`subtopics.yaml`).
- **`app/data/`** — the question banks, as typed Python rather than YAML: `java_fundamentals.py` (interview questions, easy/medium theory) and `quiz_bank.py` + `quiz_bank_java.py` (MCQs, easy/medium/hard). Python because these carry behaviour with them — `java_fundamentals.for_track()` decides whether a role is asked Spring/JPA questions at all — and because a TypedDict gets checked by mypy where a YAML file does not. `java_fundamentals.py` is the ONE source both the runtime seeder (`orchestrator._ensure_seed_questions`) and `scripts/seed_db.py` read; there used to be two divergent five-question sets and neither could fill a full interview.
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
- `components/` is currently thin (only `layout/{Header,Sidebar}.tsx` and `providers.tsx`) — the shadcn/ui component library described in `docs/prompt.md` is aspirational/in-progress, not fully built out yet.

## Documentation

All product documentation lives in `docs/`, which is also an **Obsidian vault** (the vault
root is the repo root). `docs/index.md` is the hub — every other note is reachable from it by
wikilink, so the graph view is a usable map of the system rather than a field of unconnected
dots. Wikilinks resolve by filename, not path, so `[[VOICES]]` keeps working if a note moves.

- `docs/index.md` — start here
- `docs/prompt.md` — product brief and phase-by-phase status
- `docs/VOICES.md` — panel roster, voice ids, tone and pace
- `docs/AI-COST-MODEL.md` — measured per-feature cost; the basis for plan pricing
- `docs/DEPLOY.md` — the current deployment runbook

`CLAUDE.md` stays at the repo root because tooling expects it there. Prompts in
`backend/app/prompts/*.md` are product behaviour, not documentation — editing one changes what
the AI says.

## Billing and entitlement

- **`services/billing/plans.py`** — the single source of truth for what each tier includes and
  costs. The enforcement layer, paywall copy, pricing page and landing page all read it; never
  write an allowance or price anywhere else.
- **`services/billing/credits.py`** — the only place entitlement is decided. Endpoints call
  `consume(db, user_id, feature)`, which takes `SELECT ... FOR UPDATE` on the user's plan row
  to serialise concurrent starts, then appends to the `credit_events` ledger. It does **not**
  commit: `get_db` commits on success and rolls back on error, so a failed AI call undoes the
  charge. Never `db.commit()` between charging and doing the work.
- Usage is a COUNT over the ledger within the current period, never a stored counter — so the
  monthly reset is a query predicate rather than a cron job that can fail.
- Free tier: 2 interviews, 1 GD, 5 communications, unlimited quizzes. Quizzes are never
  charged on any tier.
- `services/billing/razorpay.py` — signature verification and payment→plan mapping are pure
  functions and fully tested; only `create_order` needs live keys.

## Working notes

- `docs/prompt.md` tracks phase-by-phase project status (what's built vs. stubbed vs. planned). Treat it as living project context, not just a README — check it when unsure whether a feature (e.g. adaptive questioning, voice mode, PDF reports, Stripe billing) is actually implemented or still a placeholder.
- `.env.example` holds **placeholders**, not real credentials — verified key by key
  (`SUPABASE_SERVICE_KEY=your-service-role-key`, `GLM_API_KEY=your-zhipuai-api-key`,
  `DATABASE_URL=…://user:password@host…`). An earlier version of this note claimed the opposite;
  it was wrong. Real values live only in the untracked `.env` (git-ignored) and in the host's
  environment. Keep it that way when editing the file.
- **What the browser is allowed to see.** The only secret-shaped value in the client bundle is
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`, which is designed to be public — it authorises nothing on its
  own, because access is decided by Row Level Security on every table (pinned by
  `test_rls_coverage.py`). Anything given a `NEXT_PUBLIC_` prefix is compiled into the bundle and
  is public by definition, so never put a service key, JWT secret, AI provider key or Razorpay
  secret behind that prefix. `frontend/src/lib/security-headers.test.ts` asserts this, along with
  the response headers, and records what hardening can and cannot achieve — notably that no
  configuration makes a web frontend un-inspectable, and that the real protection is keeping
  prompts, banks, scoring and billing server-side.
- CI (`.github/workflows/ci.yml`) only runs lint + typecheck for both frontend and backend — it does not run the test suites and there is no deploy step. Don't assume passing CI means tests passed.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
