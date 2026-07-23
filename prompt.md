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

## Next Steps for the Developer
1. **Run Migrations**: Ensure your Postgres database is running (`docker-compose up -d`) and run Alembic migrations (`cd backend && uv run alembic upgrade head`).
2. **Seed Knowledge Base**: Run a Python script to parse `backend/knowledge/questions/java_core.yaml` and insert it into the database.
3. **Connect Frontend to Backend**: Start both servers (`npm run dev:frontend` and `npm run dev:backend`), log in via the UI, and verify data flows correctly between the Next.js frontend and FastAPI backend.
4. **Begin Phase 3 (Interview Engine UI & State Machine)**.
