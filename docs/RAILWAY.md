> Part of the [[index|InterviewOS documentation]].

# Moving the backend from Render to Railway

**No application code changes are required.** This note says why, and what does have to
move — because two of those things fail *silently* rather than loudly, which is worse.

- Related: [[DEPLOY]] · [[DEPLOYMENT]] · [[MULTI-REPLICA]] · [[REDIS-CUTOVER]]

---

## Why the code needs no changes

Checked against the repository rather than assumed:

| | |
|---|---|
| **The app never reads `PORT`.** | Only the Dockerfile's `CMD` does, as `${PORT:-8000}`, and it binds `0.0.0.0`. Railway injects `PORT` exactly as Render does. |
| **No Render SDK, header or API is used.** | A grep for `render.com`, `onrender`, `RENDER_*` across `backend/app` and `frontend/src` returns nothing outside comments and two test fixtures that assert error pages do *not* leak the host name. |
| **Migrations are host-agnostic.** | `scripts/boot.py` takes a Postgres advisory lock (`db/boot_lock.py`) so concurrent replicas cannot race the same DDL. It runs from `CMD`, so it needs no pre-deploy hook — Render's `preDeployCommand` was an optimisation, not a dependency, and Railway has no equivalent. |
| **The frontend's CSP is derived, not hardcoded.** | `next.config.ts` builds `connect-src` from `NEXT_PUBLIC_API_URL`. Point that at the Railway URL and the policy follows. |

## The Railway service, settings that are not env vars

`railway.json` at the repo root sets the builder, the Dockerfile path, and the health
check. Two things it cannot set, which must be right in the dashboard:

**Root Directory must stay empty (the repo root).** Not `backend/`. The Dockerfile
copies both `backend/` and `database/`, because `backend/alembic.ini` points
`script_location` at repo-root `database/migrations/`. With the root directory set to
`backend/`, the build cannot see the migrations and the container dies on its first
`alembic upgrade head`.

**Pick the region closest to Supabase and Redis.** Render was Singapore. The latency
that matters is the round trip between the API and those two, not to the user —
`docs/DEPLOYMENT.md` says to keep all three in one region.

## Environment variables

**Copy every one across.** `render.yaml` lists them all by name, and none of them is
Render-specific — they are Supabase, model providers, Razorpay, Judge0, budgets and
tuning.

**Do not set `PORT`.** Railway injects it. Setting it by hand overrides the injection
and the health check then hits a port nothing is listening on.

Three need thought rather than copying:

### `REDIS_URL` — the one that can fail silently

**The two deployment notes disagree about what Redis this is**, and the answer decides
whether the value can be copied at all:

- `docs/DEPLOY.md §Redis` says a **separate Render Key Value service, using its
  internal connection URL**. An internal Render hostname resolves only inside Render's
  network. Copied to Railway it will never connect.
- `docs/DEPLOYMENT.md` says **Upstash**, which is external and copies across untouched.

Check the dashboard before migrating. If it is Render Key Value, provision Redis
elsewhere first — Railway's own Redis plugin, or Upstash — and take the new URL.

**Why this is the dangerous one:** Redis being unreachable is *deliberately not* a
startup failure. Everything degrades instead of breaking, so the service comes up
green and:

- rate limiting **fails open**
- the AI daily spend cap becomes **per-process**, so the real ceiling is
  `AI_DAILY_BUDGET_USD × replicas`
- the interview-plan cache misses every time, at roughly **$0.065 a miss**

Grep the deploy logs for `redis_unreachable_at_startup_running_degraded`.

### `CORS_ORIGINS`

Unchanged if the frontend stays on Cloudflare Pages — it lists the *frontend's* origin,
not the API's. It must remain a **JSON array string**: `["https://your-frontend"]`. A
bare URL fails to parse and the browser cannot call the API at all.

### `WEB_REPLICA_COUNT`

Must equal `numReplicas` in `railway.json`. It changes no behaviour on its own; it is
what the Redis and database startup audits multiply per-process connection budgets by.
Stale, it makes both audits wrong in the optimistic direction — the failure mode where
nothing warns. Raising replicas means revisiting `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`REDIS_MAX_CONNECTIONS` and `REPORT_CONCURRENCY` in the same change; see the long note
on `numInstances` in `render.yaml`, which stays the reference for that reasoning.

## Things outside the repository that must be updated

These are not code and nothing in CI will catch them:

1. **`NEXT_PUBLIC_API_URL` and `INTERNAL_API_URL`** on the Cloudflare Pages project →
   the Railway URL. **The frontend must then be REBUILT**, not merely re-configured:
   `next.config.ts` bakes the CSP at build time, so an env-var change alone leaves the
   old API origin in `connect-src` and the browser blocks every call.
2. **The Razorpay webhook URL** → `https://<railway-host>/api/v1/billing/webhook`.
   Until it is changed, payments still succeed at Razorpay and credits are never
   granted, because the grant happens on the webhook.
3. **Any Supabase IP allowlist**, if one is set. The egress IP changes.
4. **`render.yaml`** can be deleted once the cutover is verified — but only then. It is
   currently the only complete list of the environment variables the service needs.

## Verifying the cutover

```bash
curl https://<railway-host>/api/v1/health
# {"status":"ok","database":"connected","redis":"connected","supabase":"connected",
#  "dependencies_healthy":true}
```

`redis` must say `connected`. If it says anything else the service will still serve
traffic and will quietly cost money — see above.
