> Part of the [[index|Hotseat documentation]].

# Deploying — environment variables and migrations

Written to be platform-neutral. Currently deployed on **Render**; the Render-specific notes
are called out where they differ, and nothing here assumes a particular host beyond that.

Three migrations are pending against production: **013, 014, 015**. All three apply and
reverse cleanly against a local Postgres, and the whole test suite (493 backend, 112
frontend) is green. What follows is what a deploy needs, in order, and why each step is
there rather than optional.

I could not run the migration myself: `DATABASE_URL` in the local `.env` points at the
Docker Postgres on `localhost:5433`, and the Supabase Postgres password is not in the repo.
That is the correct state for a checked-in file — it just means step 3 is yours to run.

---

## 1. Environment variables

### Required — the app refuses to start without these

There are deliberately no defaults for secrets, so a missing one fails at startup rather
than silently running wrong.

| variable | notes |
|---|---|
| `DATABASE_URL` | must start `postgresql+asyncpg://` — see §2 for which host to use |
| `SUPABASE_URL` | project URL |
| `SUPABASE_ANON_KEY` | ships in the browser bundle; not a secret, but required |
| `SUPABASE_SERVICE_KEY` | server-side only, never expose |
| `SUPABASE_JWT_SECRET` | used to verify tokens locally, so no round trip to Supabase per request |

### Required in practice — these have defaults, and the defaults are wrong in production

**This is the section that matters.** None of these will stop the app booting. Each one
quietly changes behaviour, and two of them are security or cost problems.

| variable | default | why the default is wrong deployed |
|---|---|---|
| `ENVIRONMENT` | `development` | **Security.** In development the app allows `localhost` CORS origins *and* a permissive `192.168.*` regex with `allow_credentials=True`, and permits `ALLOW_UNVERIFIED_JWT` to take effect. Set it to `production`. |
| `REDIS_URL` | `redis://localhost:6379/0` | **Three silent degradations** — see below. There is no localhost Redis on a managed host. |
| `AI_PROVIDER` | `glm` | The cost model, prompt caching and budgets in [[AI-COST-MODEL]] all describe Anthropic. Left at the default you are running a different model entirely. Set `anthropic`. |
| `AI_FALLBACK_PROVIDER` | `nvidia` | Set to whatever you actually want as the standby — this is what serves a user who has spent their daily allowance. |
| `ANTHROPIC_API_KEY` | `""` | Required if `AI_PROVIDER=anthropic`. |
| `CORS_ORIGINS` | `["http://localhost:3000", …]` | The frontend cannot call the API until this lists its real origin. |

### Worth setting explicitly

| variable | default | notes |
|---|---|---|
| `AI_DAILY_BUDGET_USD` | `60` | Circuit breaker across all users, not an allowance. Needs Redis to be global rather than per-instance. |
| `AI_USER_DAILY_BUDGET_USD` | `1.20` | ≈3 interviews or 8 GD rounds per user per day. |
| `ANTHROPIC_PROMPT_CACHING` | `true` | Worth ~59% of every GD round. Only leave it off to rule caching out while debugging. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | Lower to `5` / `10` behind a pooler — see §2. |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | Only change if your project issues something else. |
| `ALLOW_UNVERIFIED_JWT` | `false` | Leave unset. It is a full auth bypass and additionally requires `ENVIRONMENT=development`. |

### REDIS_URL — the one that costs money

Redis is deliberately **not** a hard startup failure: every Redis-backed feature degrades
rather than breaking, so refusing to boot would trade a working-but-degraded service for no
service. But without it, three things stop protecting you and none announces itself at the
point of failure:

1. **Rate limiting fails OPEN.** `core/rate_limit.py` catches `RedisError` and returns, so
   every limit in the app stops existing — including the 6/hour on report generation, the
   most expensive call there is.
2. **The AI spend cap becomes per-process.** `_spend_today` falls back to a local counter, so
   the effective ceiling is `AI_DAILY_BUDGET_USD × instance count`, and it resets to zero on
   every restart or redeploy.
3. **The interview-plan cache always misses**, so every plan is bought again at ~$0.065.

Startup now logs this as an **error** in production with those consequences spelled out, so
grep the deploy logs for `redis_unreachable_at_startup_running_degraded`.

### Render-specific

* **`PORT`** is injected by Render and your start command must use it:
  `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`. A hardcoded port binds to the
  wrong one and health checks fail.
* **Redis** is a separate Render service (Key Value / Redis). Use its *internal* connection
  URL — the external one costs latency on every request.
* **Cold starts matter more here.** A free instance spins down after inactivity, so the next
  request pays a ~37s boot out of the gateway's ~100s window. Report generation already
  handles this: the first request a process serves gets a tighter AI budget, everything after
  it gets the full one. A paid instance does not spin down and this stops applying.
* **The gateway cuts a request at ~100s** with a 502 that carries no CORS headers, which
  reaches the browser as an opaque failure. The report budget is sized to land inside that.

### Moving to another platform later

Nothing above is Render-specific except `PORT` and where Redis lives. On any host you need:
the five required variables, `ENVIRONMENT=production`, a reachable `REDIS_URL`,
`CORS_ORIGINS`, the AI provider and key, and a start command that binds `0.0.0.0` on
whatever port the platform supplies. If the platform's request timeout is much below ~100s,
lower `_REPORT_AI_BUDGET_*` in `api/v1/reports.py` to match, or reports will be cut off
mid-generation instead of degrading cleanly.

Confirm after deploy:

```bash
curl -s https://<your-api>/api/v1/health | jq
```

## 2. Use the Supabase connection pooler, and keep the app pool small

Use the **transaction pooler** URL — host contains `pooler.supabase.com`, port **6543** —
not the direct `5432` connection:

```
postgresql+asyncpg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

The app detects `:6543` automatically and disables asyncpg's prepared-statement cache. That
is not a tuning preference: asyncpg caches prepared-statement handles per connection, and in
a transaction pooler the backend changes between transactions, so a cached handle points at a
statement that does not exist there. It fails with `InvalidSQLStatementNameError` — and only
once there is enough concurrency for connections to actually be multiplexed, which is the
worst possible time to discover it.

**Keep `DB_POOL_SIZE` small behind the pooler.** The real connection ceiling is
`(DB_POOL_SIZE + DB_MAX_OVERFLOW) × replica count` measured against Postgres's own limit, so
raising it to serve more users exhausts the *database* instead of the pool — and the symptom
is "too many connections" on random requests rather than a clean slowdown. `5 + 10` across
four replicas is 60 server connections, which a paid Supabase instance serves comfortably;
let the pooler do the multiplexing.

---

## 3. Run the migrations

`alembic.ini` lives in `backend/` but `script_location` points at repo-root
`database/migrations/`, so run this from `backend/` with the production `DATABASE_URL`
exported:

```bash
cd backend
export DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres'

uv run alembic current          # expect 012
uv run alembic upgrade head     # applies 013, 014, 015
uv run alembic current          # expect 015 (head)
```

What each one does:

- **013** — `rating_events`, the append-only ledger behind the Interview Rating and the
  cleared-rounds credential.
- **014** — `ai_cache` with a `vector(512)` column and an HNSW index. **Requires the
  `vector` extension**, which is already enabled on your project (confirmed). The migration
  issues `CREATE EXTENSION IF NOT EXISTS vector` anyway so a fresh project works; on yours
  it is a no-op.
- **015** — three composite `(user_id, created_at DESC)` indexes for the reads every page
  does, and drops the four single-column indexes they make redundant. Verified with EXPLAIN
  against 809 rows for one user: the plan becomes a plain `Index Scan` with no Sort node.

All three are transactional and each has a tested `downgrade`. `uv run alembic downgrade 012`
reverses the set.

### If migration 014 fails on the extension

Only relevant if `vector` is somehow not enabled. Enable it from the Supabase dashboard
(Database → Extensions → `vector`) rather than by hand, then re-run. Do **not** drop the
extension on rollback — `014`'s downgrade deliberately leaves it, because something else may
be using it and on Supabase it is dashboard-managed.

---

## 4. Confirm RLS after migrating

Every table in this schema has **RLS enabled with no policies**, and that is deliberate: the
app connects as the table owner and bypasses RLS entirely, while the blanket deny closes the
table to the public anon key — which reaches Postgres through PostgREST, where RLS is *not*
bypassed. The anon key ships in the browser bundle, so a table without this is world-readable
and, worse, world-writable.

`013` and `014` enable it for the tables they add. Verify nothing was missed:

```sql
SELECT relname
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relkind = 'r'
  AND NOT relrowsecurity
  AND relname <> 'alembic_version';
-- expect zero rows
```

`backend/tests/test_rls_coverage.py` fails if a model table has no RLS statement in any
migration, so this should already hold — the query is here because a schema is worth checking
directly rather than trusting a test about the code that builds it.

---

## 5. Smoke test

```bash
# Unauthenticated: should be 401, not 500 and not 200
curl -s -o /dev/null -w '%{http_code}\n' https://<your-api>/api/v1/progress

# A forged token must be refused — this is the ALLOW_UNVERIFIED_JWT check
curl -s -o /dev/null -w '%{http_code}\n' https://<your-api>/api/v1/progress \
  -H 'Authorization: Bearer eyJhbGciOiJub25lIn0.e30.'
```

Then, signed in through the app: load the dashboard (the standing banner should render),
open **Standing**, and run one GD round. After that round, check that prompt caching is
actually reading rather than only writing — this is the difference between saving 59% and
paying 25% extra:

```sql
SELECT feature,
       sum(cached_input_tokens) AS cache_reads,
       sum(cache_write_tokens)  AS cache_writes
FROM ai_usage
WHERE feature = 'gd_panel_turn'
GROUP BY feature;
-- cache_reads should be several times cache_writes after one full round
```

If `cache_reads` is 0, `ANTHROPIC_PROMPT_CACHING` is false or a template placeholder has
crept back into `gd_panel.md`. `backend/tests/test_prompt_caching.py` guards the second case.

---

## What is still not solved

Worth knowing before traffic arrives, rather than after:

- **Report generation is still synchronous from the client's point of view.** It no longer
  holds a database connection while it waits on the model, and concurrency is capped at 4
  per process, so it will not take the API down — but a candidate still waits ~21s on the
  request. Moving it to a background task with polling is a real improvement and a real
  refactor.
- **`AI_DAILY_BUDGET_USD` at $60 is a guess sized from the cost model, not from traffic.**
  Re-derive it from the `ai_usage` ledger after a week; the SQL is in [[AI-COST-MODEL]].
- **The vector cache only covers `gd_topic_prep` and `interview_plan`.** `model_answer`
  cannot be shared (its prompt reads the candidate's own answer) and `quiz_generation` should
  not be (it would serve returning candidates a quiz they have already answered). Both are
  explained in `services/ai/vector_cache.py`.
- **CI runs lint and typecheck only.** A green pipeline does not mean the tests passed.
- **No error tracking or uptime monitoring.** At a thousand users the first sign of trouble
  should not be a user telling you.
