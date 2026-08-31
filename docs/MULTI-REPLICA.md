> Part of the [[index|InterviewOS documentation]].

# What breaks when there is more than one of us

An audit of every piece of in-process state in `backend/app/`, classified against running
N replicas. Related: [[REDIS-CUTOVER]] · [[DEPLOY]] · [[DEPLOYMENT]] · [[OBSERVABILITY]]

**The headline: almost nothing in the application was broken.** The state that diverges
across replicas is either supposed to (a connection pool, a cold-start flag) or is already
a written-down tradeoff with a shared source of truth behind it. Two things were genuinely
broken, and only one of them was in the application at all — the other was the container's
boot chain, which is the part nobody thinks of as state.

---

## The blocker, stated plainly

**Render's Free compute plan cannot run more than one instance.** Render's own
documentation lists *"Scaling beyond a single instance"* as unsupported on Free, and
autoscaling requires Pro. `render.yaml` declares `plan: free`, so `numInstances` stays at
**1** and every fix below is preparation rather than deployment.

The justified target is **2** — the smallest count that survives one instance dying and
turns a deploy into a rollover instead of a gap. Everything that must move in the same
commit is listed against `numInstances` in `render.yaml`, and
`backend/tests/test_multi_replica.py` fails if the blueprint and the application ever
disagree about the number.

Moving to a paid plan is an account decision, not a code one.

---

## Genuinely broken — fixed

### 1. Every replica ran the migrations

`Dockerfile`'s CMD was `alembic upgrade head && seed_db && seed_research && uvicorn`, and
it runs in **every** replica.

Two replicas booting a deploy that carries a migration both apply the same DDL. Postgres
holds the second behind the first's `ACCESS EXCLUSIVE` lock; the first commits; the
second's `CREATE TABLE` fails with *relation already exists*. Alembic exits non-zero, the
`&&` short-circuits, and **that replica never starts Uvicorn**. The deploy comes up at half
capacity and the cause is one line of Postgres error text in a log nobody is reading. The
seeds are the same race a level down — `SELECT` then `INSERT`, nothing serialising them.

Fixed in two places, deliberately:

- `backend/app/db/boot_lock.py` — a Postgres **advisory lock**. Native primitive over the
  database both replicas already share: no new service, nothing to keep alive. The loser
  waits, finds the work done, and boots.
- `render.yaml`'s `preDeployCommand` — the platform's own answer, which runs the work once
  per deploy before any instance starts. Commented out because it needs the same paid
  instance type as scaling.

The lock is what keeps the container correct *without* the hook: under `docker-compose`, on
a plan with no pre-deploy step, and for whoever edits the CMD back without knowing why it
changed.

### 2. A rotated Supabase signing key cost ten minutes of logins

`core/security.py` cached the JWKS for 600s with exactly one way to notice a rotation:
waiting out the timer. Every request in that window is a 401 on a valid token.

This was already true of a single instance. What N replicas add is that **each holds its
own timer**, so the symptom stops being "everybody is logged out for ten minutes" — bad,
but obvious, and it ends — and becomes "logins fail at random depending on which replica
answers", which reads as an intermittent auth bug rather than a rotation.

`get_signing_keys(kid)` now refetches when asked for a key id it does not hold, rate-limited
to one refetch per 30s. **The cooldown is a security property, not politeness**: the trigger
is attacker-controlled, because a token can carry any `kid` at all, so without a floor every
forged token becomes a request to Supabase's JWKS endpoint through our auth path.

---

## Safe under N replicas

Per-process by nature, and correct that way.

| What | Where | Why it is fine |
|---|---|---|
| Redis pool `_pool` | `db/redis.py:43` | A pool is meant to be per process. Its *budget* is audited against the fleet — [[REDIS-CUTOVER]] §2 |
| SQLAlchemy `engine` | `db/session.py:57` | Same. Budget audited at startup |
| `_served_a_request` cold-start flag | `api/v1/reports.py:79` | Models *this container's* cold start. Per-replica is the correct semantics — each new replica genuinely has its own |
| Event bus fan-out | `events/event_bus.py:67` | Nothing subscribes across processes. Both handlers act on the request the publishing process is already serving, and one of them persists to `audit_logs`, so the record is shared even though dispatch is not |
| Supabase client `lru_cache`s | `resume.py:129`, `admin.py:153`, `admin_offers.py:790` | HTTP clients. Per-process is the point — it avoids a TLS handshake per request |
| Prompt / YAML caches | `prompt_loader.py:44`, `prep/catalogue.py` | Read-only files shipped in the image; identical on every replica and immutable for the life of a deploy. `reload_all()` has no callers outside dev |
| AI provider chain `_providers`, TTS `_provider` | `provider_factory.py:40`, `tts/factory.py:22` | Connection-pool-owning singletons |
| `_PROVIDER_REGISTRY`, `_INDEX`, `_BY_ID`, the question banks | various | Built at import from code and YAML. Immutable |
| `ContextVar`s — `current_user_id`, `current_user_is_admin`, `_SENSITIVE`, request id | `ai/usage.py`, `observability.py`, `main.py` | Per-task, torn down at request end. Never cross a request, let alone a replica |
| `asyncio.create_task` / `ensure_future` sites | `quiz.py`, `resume.py`, `analyser.py`, `reports.py` | All awaited or cancelled inside the handler that made them. No detached work outlives a request, so nothing is lost when a replica is recycled |
| `part_gate` semaphore | `reports.py:1123` | Per request, not per process |
| Rate limiting, quiz answer keys, TTS audio, plan signature index | `rate_limit.py`, `quiz.py`, `redis.py` | Already in Redis — shared by construction |
| Payment idempotency, credit consumption, autopay breaker, report retry cooldown | `billing.py`, `credits.py`, `autopay.py`, `reports.py` | Postgres, with `SELECT … FOR UPDATE` or a unique ledger. Correct across any number of replicas |

## Known tradeoffs — left alone on purpose

Each of these diverges across replicas. None is worth shared-state machinery, and the
reasoning is recorded where the code is rather than only here.

**AI and TTS daily spend caps** — `anthropic_provider.py:87`, `tts/spend.py:24`.
Redis is the source of truth and the in-process tally is a `max()` against it, so with Redis
up the cap is global. With Redis **down** the effective ceiling becomes
`AI_DAILY_BUDGET_USD × replicas`, and it resets on restart. That is a degradation of an
already-degraded state, and the alternative is worse in the direction that matters: a
Redis-only counter reads `0.0` forever whenever Redis blinks, which is a money guard that
fails **open**. Multiplying a ceiling beats removing it.

**Report concurrency** — `reports.py:102`. `asyncio.Semaphore(REPORT_CONCURRENCY)` is per
process, so provider-facing concurrency is `REPORT_CONCURRENCY × replicas` — 24 simultaneous
~17k-token calls at 12 × 2. The code already says "raise it with replica count, not instead
of it". A distributed semaphore would mean a Redis round trip in the path of the most
latency-sensitive call in the product to bound something the daily spend cap already bounds
by cost. **Measure it against the Anthropic account's rate limits** before scaling — that is
what [[AI-COST-MODEL]] and the headroom analysis are for.

**`ai_cache` eviction counter** — `vector_cache.py:235`. Each replica needs `_EVICT_EVERY`
writes of its own before it trims, so the table's real overshoot bound is
`_EVICT_EVERY × replicas`, not `_EVICT_EVERY`. The comment in the code claimed the tighter
bound and has been corrected. At a 5,000-row cap the difference is noise, and a shared
counter would cost a round trip on every cache write to tighten a bound nothing depends on.

**AI reachability probe** — `ai/reachability.py:73`. A 240s cache behind the health
endpoint, so `/health` can answer differently on different replicas during a provider blip.
That is health checks working correctly: the probe describes *this instance's* view, which
is what a per-instance health check is for.

---

## What would change the answer

This audit is true of the code as it stands. Three changes would each require redoing it:

1. **Anything that schedules work in-process** — a cron, a background sweeper, a retry
   queue. There is none today (`vector_cache.py:520` notes eviction is driven from the write
   path precisely because there is no scheduler). Add one and every replica runs it.
2. **Anything that caches mutable, admin-editable data in a module global.** All the
   caches today hold files from the image. One holding a DB row would go stale on N−1
   replicas after every edit.
3. **Sticky sessions, or anything that assumes the same replica serves a multi-step flow.**
   Nothing does today — interview, quiz, GD and panel state all round-trip through Postgres
   or Redis on every request.
