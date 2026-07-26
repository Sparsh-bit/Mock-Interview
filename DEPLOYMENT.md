# InterviewOS — Free Deployment Guide (no credit card required)

This deploys the whole app for **$0**, with **no credit card** on any provider.

## The stack

| Piece | Provider | Free? | Notes |
|---|---|---|---|
| Frontend (Next.js) | **Cloudflare Pages** | ✅ no card | You know Cloudflare. (Vercel is an even simpler no-card alternative.) |
| Backend (FastAPI) | **Render** (free web service) | ✅ no card | Handles the long ~110 s AI calls. Sleeps after 15 min idle → first request cold-starts (~50 s). Mitigated with a free keep-warm ping (step 8). |
| Database (Postgres) | **Supabase** | ✅ no card | You already have this project. |
| Cache/Redis | **Upstash** | ✅ no card | 256 MB / 500 k commands/mo free. |
| Code compiler | **Public Piston API** | ✅ no host needed | `https://emkc.org/api/v2/piston` — free, public. |
| AI models | **GLM + NVIDIA** free keys | ✅ | Already configured. |
| DNS / CDN / WAF | **Cloudflare** | ✅ no card | Front the whole app. |

> **Why not Cloudflare for the backend?** Cloudflare Workers run V8/JS (Python Workers are Pyodide-beta) and can't run FastAPI + asyncpg + 110 s requests. Cloudflare hosts the **frontend + CDN**; the Python backend goes on Render.

---

## 0. Prerequisites
1. Push this repo to **GitHub** (private is fine).
2. Create free accounts (GitHub login, no card): [Supabase](https://supabase.com), [Upstash](https://upstash.com), [Render](https://render.com), [Cloudflare](https://dash.cloudflare.com).
3. Keep your existing **GLM** and **NVIDIA** API keys handy.

---

## 1. Supabase (Database + Auth) — you already have this

1. Open your project → **Settings → Database → Connection string → URI**. Copy it. It looks like:
   `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`
   - Use the **Session pooler / direct** string (port `5432`). The app's config auto-rewrites it to the `asyncpg` driver. If you ever use the *transaction* pooler (`6543`), append `?statement_cache_size=0`.
   - Pick a region **close to your users** (India → Mumbai/Singapore) for low lag.
2. **Settings → API** — copy: **Project URL**, **anon public key**, **service_role key**.
3. **Settings → API → JWT Settings** — copy the **JWT Secret** (this app verifies Supabase tokens).
4. **Storage** → create 3 buckets with the CORRECT privacy (this matters — resumes are personal data):
   - `avatars` → **Public ON** (profile pictures, non-sensitive).
   - `resumes` → **Public OFF (private)** — the backend reads/writes these with the `service_role` key, which works on private buckets; public would needlessly expose candidates' CVs.
   - `reports` → **Public OFF (private)** — personal evaluation data; when PDF export is added, serve it via signed URLs.
   > Rule of thumb: only `avatars` is public. The backend's service-role key accesses `resumes`/`reports` regardless of privacy, so keep them private.
5. **Authentication → URL Configuration** → set **Site URL** to your future frontend URL (fill in after step 6) and add it to **Redirect URLs**.

> Migrations (tables, RLS, `activity_logs`) run automatically on backend deploy (step 5). To run manually instead: `cd backend && DATABASE_URL="<supabase-uri>" uv run alembic upgrade head`.

---

## 2. Upstash (Redis)

1. Create a **Redis database** (any region near your users) → **Type: Regional**.
2. On the database page, copy the **`rediss://…` URL** (TLS). This is your `REDIS_URL`.

---

## 3. Piston (code execution) — nothing to deploy

Use the free public API. You'll just set:
`PISTON_BASE_URL=https://emkc.org/api/v2/piston`

---

## 4. AI keys — nothing to deploy

You already have GLM + NVIDIA keys. They go into the backend env (step 5).

---

## 5. Backend → Render (free web service)

A production `Dockerfile` is in the repo root (build context = repo root, because migrations live in `database/`).

1. Render dashboard → **New → Web Service** → connect your GitHub repo.
2. Settings:
   - **Runtime:** Docker
   - **Dockerfile path:** `./Dockerfile`
   - **Docker build context:** `.` (repo root)
   - **Instance type:** **Free**
   - **Health check path:** `/api/v1/health`
3. Add **Environment Variables** (see the full table in step 9). At minimum:

   | Key | Value |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `LOG_FORMAT` | `json` |
   | `DATABASE_URL` | Supabase URI (step 1) |
   | `REDIS_URL` | Upstash `rediss://…` (step 2) |
   | `SUPABASE_URL` | Supabase Project URL |
   | `SUPABASE_ANON_KEY` | Supabase anon key |
   | `SUPABASE_SERVICE_KEY` | Supabase service_role key |
   | `SUPABASE_JWT_SECRET` | Supabase JWT secret |
   | `AI_PROVIDER` | `glm` |
   | `AI_FALLBACK_PROVIDER` | `nvidia` |
   | `GLM_API_KEY` | your GLM key |
   | `GLM_MODEL` | `glm-4.5-flash` (or your model) |
   | `GLM_BASE_URL` | your GLM base URL |
   | `NVIDIA_API_KEY` | your NVIDIA key |
   | `NVIDIA_MODEL` | your NVIDIA model |
   | `NVIDIA_BASE_URL` | your NVIDIA base URL |
   | `PISTON_BASE_URL` | `https://emkc.org/api/v2/piston` |
   | `CORS_ORIGINS` | `["https://YOUR-FRONTEND-URL"]` ⚠️ JSON array string |

   > **`CORS_ORIGINS` must be a JSON array string**, e.g. `["https://interviewos.pages.dev","https://yourdomain.com"]`. A bare URL will fail to parse.

4. **Create Web Service.** First build runs migrations then boots Uvicorn.
5. Copy the service URL, e.g. `https://interviewos-api.onrender.com`. Test: open `…/api/v1/health` → should return `{"status":"ok",...}`.

---

## 6. Frontend → Cloudflare Pages

Next.js 15 App Router on Pages uses the Cloudflare adapter.

1. Add the adapter locally (one-time), commit:
   ```bash
   cd frontend
   npm install --save-dev @cloudflare/next-on-pages
   ```
2. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git** → pick the repo.
3. Build settings:
   - **Framework preset:** Next.js
   - **Root directory:** `frontend`
   - **Build command:** `npx @cloudflare/next-on-pages@1`
   - **Build output directory:** `.vercel/output/static`
   - **Compatibility flags:** add `nodejs_compat`
4. Environment variables (Production **and** Preview):

   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | your Render URL, e.g. `https://interviewos-api.onrender.com` |
   | `INTERNAL_API_URL` | same Render URL |
   | `NEXT_PUBLIC_APP_URL` | your Pages URL, e.g. `https://interviewos.pages.dev` |
   | `NEXT_PUBLIC_SUPABASE_URL` | Supabase Project URL |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key |

5. **Save and Deploy.** Copy the Pages URL.

> **Simpler alternative (also free, no card):** Vercel → import repo → root `frontend` → set the same `NEXT_PUBLIC_*` vars → deploy. Zero adapter needed. Use this if the Pages adapter gives you trouble.

---

## 7. Wire everything together

1. **Backend CORS:** set Render's `CORS_ORIGINS` to include your real frontend URL (JSON array) → redeploy.
2. **Supabase Auth URLs:** Authentication → URL Configuration → **Site URL** + **Redirect URLs** = your frontend URL (`https://…pages.dev` and your custom domain).
3. **Custom domain (optional, free on Cloudflare):** Pages → Custom domains → add your domain (Cloudflare manages DNS automatically). Update `NEXT_PUBLIC_APP_URL`, Supabase URLs, and `CORS_ORIGINS` to match.

---

## 8. Kill cold-start lag (free)

Render free sleeps after 15 min idle. Keep it warm with a free pinger:
- [cron-job.org](https://cron-job.org) or [UptimeRobot](https://uptimerobot.com) (both free, no card).
- Ping `https://YOUR-RENDER-URL/api/v1/health` every **10 minutes**.

This removes the ~50 s wake delay for real users. (The ~110 s *first-plan* generation is the free AI model's speed, not hosting — it's already cached after the first run per company/program, so repeats are instant.)

---

## 9. Full environment-variable reference

### Backend (Render)
```
ENVIRONMENT=production
LOG_FORMAT=json
DATABASE_URL=postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:5432/postgres
REDIS_URL=rediss://default:<token>@<name>.upstash.io:6379
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon key>
SUPABASE_SERVICE_KEY=<service_role key>
SUPABASE_JWT_SECRET=<jwt secret>
AI_PROVIDER=glm
AI_FALLBACK_PROVIDER=nvidia
GLM_API_KEY=<glm key>
GLM_MODEL=glm-4.5-flash
GLM_BASE_URL=<glm base url>
NVIDIA_API_KEY=<nvidia key>
NVIDIA_MODEL=<nvidia model>
NVIDIA_BASE_URL=<nvidia base url>
PISTON_BASE_URL=https://emkc.org/api/v2/piston
CORS_ORIGINS=["https://interviewos.pages.dev"]
```
Optional: `SENTRY_DSN`, `DB_POOL_SIZE`, `REDIS_DEFAULT_TTL_SECONDS`, `RATE_LIMIT_*`.

### Frontend (Cloudflare Pages / Vercel)
```
NEXT_PUBLIC_API_URL=https://interviewos-api.onrender.com
INTERNAL_API_URL=https://interviewos-api.onrender.com
NEXT_PUBLIC_APP_URL=https://interviewos.pages.dev
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
```

---

## 10. Post-deploy smoke test
1. `GET https://YOUR-RENDER-URL/api/v1/health` → `{"status":"ok","database":"connected","redis":"connected","supabase":"connected"}`
2. Open the frontend → register/login (confirm Supabase redirect works).
3. Start an interview → approve plan → answer a question (mic).
4. Run a quiz, a communication round, a group discussion.
5. Open **Reports** → confirm the session is named by your company/program, shows topics + date/time, and the activity feed expands.

---

## Free-tier limits to know (all $0)
- **Render free**: sleeps after 15 min idle (keep-warm ping fixes it); 512 MB RAM, shared CPU — fine because AI calls are network-bound.
- **Supabase free**: 500 MB DB; project **pauses after ~1 week of zero activity** (a login/query wakes it).
- **Upstash free**: 256 MB, 500 k commands/month.
- **Public Piston**: rate-limited but ample for early usage.
- **Cloudflare Pages**: 500 builds/month, unlimited requests.

When you have revenue, the only paid upgrades worth making first: an always-on backend instance (no sleep) and a faster AI model.
