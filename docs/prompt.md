> Part of the [[index|InterviewOS documentation]].

# InterviewOS — Project Summary & Blueprint

## Product Vision & Main Idea
**InterviewOS** is a production-grade, AI-powered mock interview platform, starting with a focus on **Cognizant Digital Nurture (Java FSE)**. 
Unlike standard chatbots or static Q&A banks, InterviewOS is an **interview simulation engine**. It reproduces the full experience of a real technical interview:
- **Adaptive Questioning**: Questions adapt to the candidate's performance. Strong answers trigger deeper, more difficult follow-ups; weak answers prompt hints or easier concepts.
- **Resume-Personalized Sessions**: AI analyzes the candidate's uploaded resume to tailor questions to their specific experience and projects.
- **Real-Time Structured Evaluation**: Every answer is scored across multiple vectors (technical accuracy, communication clarity, completeness, confidence).
- **Bluffing Detection**: The AI detects confident but factually incorrect answers and challenges them.
- **Detailed Actionable Reports**: After the session, the user receives a "Hire/No-Hire" verdict, topic-by-topic scores, and a prioritized improvement roadmap.

## Architecture & Technology Stack
The platform follows a modern, scalable architecture designed for production.

**Frontend (Next.js 15 App Router)**
- **Tech Stack**: React 19, TypeScript, Tailwind CSS (v3), shadcn/ui (design system), Framer Motion (animations).
- **Data Fetching & State**: TanStack Query (React Query) for server state caching, native `fetch` API wrapped in a robust, isomorphic API client (`ApiClient` with interceptors and retry logic).
- **Styling**: A premium dark-mode-first aesthetic (glassmorphism, gradient text, subtle glows) configured in `tailwind.config.ts` and `globals.css`.

**Backend (FastAPI)**
- **Tech Stack**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (Async), Alembic, Pydantic, Structlog.
- **AI Integration**: Abstracted `AIProvider` layer. AI business logic is isolated. Currently implemented with **GLM 5.2 (ZhipuAI)**, with structured JSON outputs strictly validated via Pydantic.
- **Database**: PostgreSQL (via asyncpg) hosted on Supabase. Uses UUID primary keys and JSONB for flexible metadata.
- **Cache & Pub/Sub**: Redis (Upstash) for caching, rate limiting, and an in-process async event bus (`EventBus`) for decoupled domain events (e.g., saving audit logs without blocking the HTTP response).

**Infrastructure & Auth**
- **Auth**: Supabase Auth (JWT) verified locally on the FastAPI backend without network round-trips.
- **Storage**: Supabase Storage for resumes and generated PDF reports (stubs prepared).
- **CI/CD**: GitHub Actions workflows for linting, type-checking, and testing.

---

## What Has Been Completed (Phases 1 & 2)

### 1. Backend Core & Infrastructure (Phase 1)
- **Monorepo Setup**: Configured root `package.json`, `.github/workflows/ci.yml`, and `docker-compose.yml`.
- **Database schema (17 tables)**: Fully defined SQLAlchemy models (`User`, `Profile`, `Company`, `InterviewTrack`, `Question`, `InterviewSession`, `Score`, `Report`, etc.) and generated the initial Alembic migration.
- **Async Database & Redis**: Integrated async SQLAlchemy engine (`db/session.py`) and Redis connection pooling (`db/redis.py`).
- **Event-Driven Architecture**: Created an async `EventBus` (`events/`) to emit and handle domain events (Interview Started, Answer Evaluated, etc.) without blocking requests.
- **Structured Logging & Error Handling**: Configured `structlog` for JSON logs and a centralized exception hierarchy with custom FastAPI exception handlers.
- **Auth & Security**: Implemented JWT validation (`core/security.py`) to verify Supabase tokens locally and load the application user.

### 2. AI Abstraction Layer
- Built the `BaseAIProvider` and `GLMProvider` (`services/ai/`).
- Created a robust prompt management system (`prompts/prompt_loader.py`) utilizing Markdown templates (`interviewer.md`, `resume_analyzer.md`, `report_generator.md`).
- Implemented robust AI output parsing and Pydantic validation (`json_validator.py`, `response_parser.py`) to ensure the AI always returns the exact JSON shape required by the business logic, with automatic retries on failure.

### 3. Backend APIs (Phase 3 & 4 Foundations)
- **Auth APIs**: Sync Supabase user to DB (`/api/v1/auth/profile`), get current user (`/me`).
- **User APIs**: Profile CRUD, aggregate stats (`/me/stats`), session history (`/me/sessions`).
- **Questions/Tracks APIs**: List interview tracks and detailed topic structures.
- **Interview APIs**: Start session, get next question, submit answer (currently using heuristic scoring as a placeholder for AI), end session.
- **Report & Resume APIs**: Generate report, list/upload resumes.

### 4. Frontend Foundation & UX (Phase 2)
- **Design System**: Set up Tailwind config with brand colors, typography (Inter + JetBrains Mono), and custom animations.
- **API Client**: Built a highly robust, dependency-injected `ApiClient` (`lib/api/`) that works seamlessly across Server Components and Client Components, handling auth headers and retries.
- **Authentication Flow**: Implemented `middleware.ts` for route protection, `useAuth` hook, and premium UI for Login and Registration pages (with Zod validation).
- **Layouts & Navigation**: Created the authenticated Dashboard layout with a collapsible sidebar (`Sidebar.tsx`) and dynamic header (`Header.tsx`).
- **Premium Landing Page**: Built a Framer Motion-powered landing page (`page.tsx`) highlighting features, mock interview visualizations, and a modern dark aesthetic.
- **Dashboard**: Created the main dashboard (`dashboard/page.tsx`) showing stats, recent sessions, and available interview tracks.

---

## What Is Left To Do (Phases 3 to 10)

### Phase 3 & 4: Full Interview Engine State Machine
- **Frontend Interview UI**: Build the actual interview screen where users see the question, timer, and can type/speak their answer.
- **Backend Orchestrator**: Replace the simple "sequential question" logic with a robust State Machine (`services/interview/orchestrator.py`) that handles transitions between `pending`, `active`, and `completed`, selects questions adaptively based on previous performance, and integrates the AI layers.

### Phase 5: Deep AI Integration
- Connect the `GLMProvider` directly to the `/sessions/{id}/answer` endpoint to evaluate technical answers using the `coding_evaluator.md` prompt.
- Integrate the `interviewer.md` prompt to dynamically generate follow-up questions instead of just pulling from the DB.
- Connect the AI report generator to `/reports/{session_id}/generate` to produce rich, actionable PDF reports.

### Phase 6: Resume Intelligence
- Wire up actual Supabase Storage for resume uploads.
- Implement the AI parser using `resume_analyzer.md` to extract skills and context, feeding this into the Interview Orchestrator to personalize questions.

### Phase 7: Voice Interview Mode
- Implement WebRTC/Browser MediaRecorder on the frontend for audio capture.
- Integrate Whisper (or similar STT) to transcribe user speech to text.
- Connect TTS (e.g., ElevenLabs, OpenAI, or GLM Voice) to play the AI interviewer's questions back to the user.

### Phase 8 & 9: Analytics & Reporting
- Build detailed PDF generation for the `/reports/{report_id}/export/pdf` endpoint.
- Develop the Frontend Analytics dashboard showing historical trends, topic mastery, and radar charts.
- Implement streak tracking and advanced gamification.

### Phase 10: Admin Platform & Monetization
- Build an internal Admin UI to curate the Knowledge Base (add new questions/tracks).
- Implement Stripe integration to offer premium tracks or detailed AI feedback beyond a free quota.

---

---

## Refined Niche & Product Direction (authoritative — read before planning any new feature)

**Niche**: not a generic mock-interview site — "the most realistic AI mock interview platform for Cognizant Digital Nurture (Java FSE / GenC / GenC Next)." Depth on one recruiter/track beats breadth across many. Question bank and interviewer behavior should be built and prioritized around the recurring CDN interview pattern: Java OOP, Collections/HashMap internals, Exception Handling, JVM/JDK/JRE, Multithreading, SQL, Spring Boot, REST APIs, MVC, Design Patterns, PL/SQL, simple coding, resume discussion, HR questions (relocation, night shifts), project explanation.

**Adaptive questioning as a tree, not a list**: each answer should determine the next node (e.g. Java → Collections → HashMap → Internal Working → Collision → Load Factor → Rehashing), so no two sessions look identical. This is the direction `orchestrator.py`'s `get_next_question` should evolve toward — not a single difficulty knob, but branching by *topic* and *depth* based on the answer just given.

**Interviewer personalities** (selectable per session): Strict (no hints, interrupts, deep follow-ups), Friendly (encouraging, gives hints), HR (behavioral — conflict, leadership, failure, communication), Technical Architect (Spring/microservices/REST/SQL/design patterns only). Implemented as distinct prompt templates/personas layered on the same orchestrator, not separate codepaths.

**Voice interview mode**: real speech in, real speech out (not typing) — MediaRecorder capture, STT (Whisper-class), TTS for the interviewer's questions. See Phase 7 above; this is the mechanism, the personalities above are what should speak through it.

**Webcam + mic behavioral analysis**: eye contact, head movement, "reading from screen" detection, speaking speed, filler-word rate (um/uh/like/basically), long pauses, energy — feeding into a confidence score alongside the technical score. This is new scope beyond current Phase 7-9 and needs its own design pass (privacy/consent handling for webcam/mic capture is a hard requirement here, not optional).

**Scoring must be example-driven, not verdict-only**: don't just say "weak answer" — show the question, the candidate's actual answer, what was missing, the ideal answer, and a numeric score (e.g. 4/10) with sub-scores (accuracy, confidence, examples, depth, communication, grammar). This is the core differentiator and should shape both `coding_evaluator.md` and `report_generator.md` prompt design.

**Question bank as living data, tagged and frequency-ranked**: each question carries difficulty, topic/subtopic, follow-ups, ideal answer, common mistakes, keywords, expected duration, and *asked-frequency* + *company* tags (e.g. "asked 127 times across CTS/Capgemini/Accenture/Infosys"), sourced by clustering recurring questions from public interview-experience write-ups (GeeksforGeeks-style reports, aggregated community discussion) into canonical concepts with a confidence score by frequency — not a static hardcoded list. This is a distinct data pipeline (ingest → cluster → tag → seed `knowledge/questions/`), separate from the live interview app.

**Reporting honesty**: the platform can produce a rich, structured *readiness assessment* (technical-by-topic, communication, confidence, speaking pace, filler-word frequency, resume-discussion quality, coding performance, behavioral performance, a revision roadmap, an estimated readiness %) — it must NOT claim to predict actual hire/reject outcomes from a specific company. Frame outputs as "estimated readiness," never as a hiring prediction.

**Downstream / later-phase ideas** (not yet scoped, don't build speculatively): coding round with hidden test cases, PDF report as a 5-page professional document (overall score + radar chart / question-by-question feedback / weak topics / improvement plan / readiness estimate), and a college/institution admin analytics dashboard (cohort-level average score, weakest topic, placement-readiness aggregate). These are real roadmap items but sequenced after the core adaptive-interview + honest-scoring experience is solid.

**Stack notes vs. this vision**: the vision text names GPT-5.5/Claude/Gemini/Llama and Clerk as example infra — this repo's actual stack is GLM via the existing `BaseAIProvider`/`GLMProvider` abstraction (swap providers there, not per-caller) and Supabase Auth (already fully wired, not Clerk). Treat those as the working choices unless a stack change is explicitly decided and recorded here.

**AI provider routing (2026-07-23)**: `GLMProvider` talks to ZhipuAI's own API (`https://open.bigmodel.cn/api/paas/v4`) directly, not NVIDIA NIM — an NVIDIA NIM deployment of `z-ai/glm-5.2` was tried first but never responded to any chat-completion request (confirmed via direct curl at 150s timeout, while other NIM models responded instantly). `glm-5.2` is a real, valid model on the configured Zhipu account but requires a funded balance (error 1113 "insufficient balance"); `.env` currently runs `GLM_MODEL=glm-4.5-flash` (free tier, confirmed working end-to-end) until the account is topped up, at which point swap back to `glm-5.2` — no code change needed, only the `.env` value.

---

## Next Steps for the Developer
1. **Run Migrations**: Ensure your Postgres database is running (`docker-compose up -d`) and run Alembic migrations (`cd backend && uv run alembic upgrade head`).
2. **Seed Knowledge Base**: Run a Python script to parse `backend/knowledge/questions/java_core.yaml` and insert it into the database.
3. **Connect Frontend to Backend**: Start both servers (`npm run dev:frontend` and `npm run dev:backend`), log in via the UI, and verify data flows correctly between the Next.js frontend and FastAPI backend.
4. **Begin Phase 3 (Interview Engine UI & State Machine)**.
