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

**THE TARGET PORT IN THE DOMAIN DIALOG MUST BE WHAT RAILWAY INJECTS, NOT THE DOCKERFILE
DEFAULT.** This cost a long outage. `Generate Service Domain` asks for "the port your app is
listening on" and pre-fills **8080**, which is correct: Railway injects `PORT=8080`, and the
Dockerfile's `${PORT:-8000}` therefore binds **8080** — the `8000` default applies only when
`PORT` is unset, which on Railway it never is. `EXPOSE 8000` in the Dockerfile is documentation
of the local default and is not what the platform routes to.

Overriding that field to `8000` produces a perfectly healthy application that is never routed
to: the edge answers `502 {"message":"Application failed to respond"}` with
`x-railway-fallback: true`, and a browser reports every request as a CORS failure because a 502
page carries no CORS headers. The deploy log says `Uvicorn running on http://0.0.0.0:8080` and
`Application startup complete`, so nothing in the symptoms points at the port.

**Confirm it against the log, not against this file:** whatever `Uvicorn running on
http://0.0.0.0:<port>` says is the number that belongs in the dialog.

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

## Serving 200 concurrent candidates

Railway Hobby is what makes this reachable — Render's free plan is 0.1 vCPU and one
process, which is under the CPU this load needs regardless of tuning. But **the plan change
alone does not get there**, and the settings below are not optional extras: three of the four
ceilings at 200 users are per-process budgets that a bigger box does not move.

Assumed load, which is the model in [[RATE-LIMIT-HEADROOM]]: 200 people with a session open
at once — **120 in interviews, 50 in group discussions, 30 idle or on quizzes** — not 200
requests in flight.

### The settings, and the arithmetic behind each

| variable | value | why this number |
|---|---|---|
| `WEB_CONCURRENCY` | **4** | Uvicorn worker processes. One worker is bounded by one core, so 8 vCPU buys nothing until this is raised. The app reads the same variable uvicorn obeys, so `PROCESS_COUNT` follows automatically. |
| `WEB_REPLICA_COUNT` | **1** | Matches `numReplicas` in `railway.json`. Total processes = 1 x 4 = 4, and that product is what every audit multiplies by. |
| `DB_POOL_SIZE` | **5** | (5 + 10) x 4 processes = **60** server connections. At 10/20 it would be 120, which exhausts the Supabase pooler rather than the pool. |
| `DB_MAX_OVERFLOW` | **10** | ⤴ |
| `DB_CONNECTION_CEILING` | **200** on Supabase Nano | "Max client connections", fixed by compute size. 60 needed, so this is not the constraint. |
| `DB_POOLER_POOL_SIZE` | **40** — raised from the Nano default of 15 | **The tightest ceiling in the system**, and the only one that does not divide by the worker count. See below: 15 cannot serve 200. |
| `REDIS_MAX_CONNECTIONS` | **15** | 15 x 4 = **60**. Check against `REDIS_CONNECTION_CEILING` from the Redis plan page. |
| `REPORT_CONCURRENCY` | **4** | **The one that reaches outside the box.** 4 x 4 = 16 fleet-wide slots at ~15,940 output tokens/min each = **255,085 OTPM, 64% of Anthropic's Start tier**. Left at 12 it is 48 slots = 765,257 = **191% — over**. |
| `REPORT_BATCH_ENABLED` | **true** | See below. This is the one that makes a cohort finishing together survivable at all. |
| `AI_DAILY_BUDGET_USD` | **75** | 200 candidates x (interview $0.1096 batched + GD $0.142) = **$50.32/day**. The default $60 leaves 16% headroom for retries; $75 leaves a third. |
| `TTS_DAILY_BUDGET_USD` | **40** | 200 GD rounds x $0.117 + 200 interviews x $0.048 = **~$33/day** on Fish. The default $5 covers 43 rounds of 200. |
| `TTS_PROVIDER` | **fish** | Not `elevenlabs`. ElevenLabs Creator is $1.72 a round — **$344/day** at this volume, roughly 87% of total spend. See [[ELEVENLABS-SETUP]]. |

`AI_USER_DAILY_BUDGET_USD` needs no change: one interview plus one GD is $0.25 against its
$1.20.

### The pooler's pool size is the real ceiling, and compute does not relieve it

Supabase's connection-pooling page shows two numbers that are easy to confuse, and the smaller
one binds:

| Dashboard field | What it limits | Nano |
|---|---|---|
| **Max client connections** | Clients that may connect **to the pooler** | 200, fixed |
| **Connection pool size** | Connections the pooler opens **to real Postgres**, shared by everyone | **15**, editable |

In transaction mode an idle application connection costs zero Postgres backends. One holding an
**open transaction** occupies one of those 15 for as long as it stays open. So the limit on real
concurrency is neither the app's pool (60) nor the client cap (200) — it is **15 simultaneous
open transactions**, and 120 candidates at one exchange every 90s reach up to 24 at full budget.

**It is the one budget that does not divide by the worker count.** Every other ceiling here is
per process and gets multiplied by `PROCESS_COUNT`; the pooler's pool belongs to the database,
so four workers share the same 15. Adding compute to the API cannot help.

**Past it the queue forms inside the pooler** — where nothing in this application can see or log
it. The symptom is requests getting slower with no local explanation.

Two levers, and you want both:

1. **Raise the pool size.** The field is editable. 40 is the recommendation; check it against
   Postgres's own limit first, since the pooler's pool is drawn from it:
   ```sql
   SHOW max_connections;   -- Supabase -> SQL Editor
   ```
   Leave headroom for migrations, `psql` sessions and the dashboard itself.

2. **Hold transactions for less time** — now done in all three places that held one across a
   model call: `api/v1/reports.py`, `api/v1/panel.py`, and the cross-question path in
   `services/interview/orchestrator.py`. Each commits after its reads and lets the later write
   re-acquire. `tests/test_process_count.py` fails if any regresses.

Run `uv run python scripts/capacity_preflight.py --users 200` after setting
`DB_POOLER_POOL_SIZE`; it checks this explicitly and says so when the value is unset.

### Why `REPORT_BATCH_ENABLED` is doing the heavy lifting

A cohort does not finish at a uniform rate — they finish together, and the synchronous report
path cannot absorb that. `_report_slots` gives up after `report_ai_budget_seconds() * 0.5` =
**42.5s**, and 16 fleet slots clear ~46 reports a minute, so a burst of 200 simultaneous
completions serves the first ~50 and hands the rest an honest placeholder to retry.

Batching removes the burst instead of queueing it. First-generation reports are submitted to
the provider's batch API and **return before the semaphore is ever acquired** — half price,
answered on the provider's schedule, and drawing on a **separate rate-limit pool** so report
output tokens stop competing with live interview traffic. Retries and completion passes stay
synchronous, which is right: somebody is watching those.

Anything that can go wrong falls through to the synchronous path in the same request — no
batch API on the provider, a refused submission, a spent budget, an unmigrated table. Nobody
gets a worse report, only a more expensive one.

### What is still a ceiling at 200, after all of the above

Two of these used to be listed here as "not solved by any setting". The software side of both
is now handled; what is left is genuinely an account decision, and the distinction matters.

#### Anthropic's monthly spend cap — the tier is still yours to pick

$50.32 a day is **~$1,510/month**, past Start's $500 and past Build's $1,000. Sustained
200-a-day traffic needs the **Scale tier**. No setting changes that.

**What the code now does when the cap is hit.** Anthropic reports a breached spend cap as
`429` with `error_code: enforced_spend_limit_reached` and **no `retry-after`** — a rate limit
by status code, a permanent refusal by nature. `ProviderError.is_spend_cap()` tells the two
apart and the chain treats it like the auth-error and daily-budget cases it already handled:
**straight to `AI_FALLBACK_PROVIDER`, no retry, no backoff.**

Before, it earned the 2s rate-limit sleep *and* a second doomed attempt on the spent provider
first. Inside a panel turn's 12s budget that is a third of the whole thing, spent waiting for
an answer that cannot arrive, at the moment the fallback is the only thing that can still
answer. So the cap is now **survivable** — the product degrades to the fallback model instead
of stalling — but survivable is not the same as sufficient. Watch for
`ai_generate_provider_spend_cap_reached` in the logs; it is logged at ERROR precisely because,
unlike a rate limit, it does not pass on its own.

#### Judge0 — capped fleet-wide, but a real drive still wants a key

`RATE_LIMIT_CODE_EXEC_PER_MINUTE` is keyed **per user**: it caps one candidate at 20 a minute
and is blind to two hundred of them. The default `CODE_EXEC_PROVIDER=judge0` points at the
**public Judge0 CE instance** — free, no key, shared with the whole internet. A campus drive
aimed at it ends in 429s and a blocked egress IP for the entire deployment.

`JUDGE0_DAILY_REQUEST_LIMIT` is now a fleet-wide daily ceiling, counted in **requests** because
a Judge0 CE call costs $0.00 and no money cap can see it. It shares its counter with the burst
rung ([[MULTI-REPLICA]] · `app/db/daily_counter.py`): Redis `INCR` with a per-process fallback,
**reserved before the call** so concurrent submissions cannot all read one-below-the-limit and
proceed. Past it the request is refused locally — a call that is going to be 429'd still costs
the round trip and still counts against the shared instance.

| | |
|---|---|
| **Default** | `0` — disabled. Judge0 CE publishes no per-IP figure, and a guessed ceiling is a check that is confidently wrong. |
| **Set it for a drive** | Pick a number you are willing to be a good citizen at. It is a **fleet** number: `WEB_CONCURRENCY` does not divide it. |
| **Ignored when `JUDGE0_API_KEY` is set** | The guard protects a free shared service. Throttling bought capacity would make the guard the cause of the outage it exists to prevent. |
| **Still true** | If 200 candidates genuinely need coding rounds, set `JUDGE0_API_KEY` (RapidAPI) or self-host. The cap makes exhaustion **graceful**, not absent — past it, candidates are told their code was not run and why. |

#### The one that is only documented

**`get_next_question` still holds a pooled connection across its model call.** Bounded and
acceptable at these numbers — the interview plan pre-generates all 12 questions, so the AI path
there is the fallback plus cross-questions — but it is the largest remaining term: 24 of 60
connections if every call runs to its full 18s budget. The fix, if it is ever needed, is the
one `reports.py` and `panel.py` already use: commit before the model call.

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
