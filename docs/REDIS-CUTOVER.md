# Redis cutover: single instance → managed, replicated

Moving from "a Redis on localhost" to "a Redis somebody else operates". This is a
configuration change plus a verification, not a code change — `backend/app/db/redis.py`
is already written for the managed case.

Related: [[DEPLOY]] · [[DEPLOYMENT]] · [[UPTIME]] · [[OBSERVABILITY]] · [[index]]

**Nothing here requires taking the API down.** Every Redis-backed feature degrades rather
than breaks (`main.py` deliberately refuses to make Redis fatal), so the worst case for a
botched cutover is a window of the degradation described in §6 — not an outage.

---

## What actually changes

| | Before | After |
|---|---|---|
| Scheme | `redis://` | `rediss://` — TLS, verified against the system trust store |
| Failure mode | process dies with the app | server can move underneath a live pool |
| Connection budget | irrelevant | `REDIS_MAX_CONNECTIONS × WEB_REPLICA_COUNT` vs. a ceiling the provider enforces |

Three settings carry the change: `REDIS_URL`, `REDIS_CONNECTION_CEILING`,
`WEB_REPLICA_COUNT`. Defaults for the rest are in `core/config.py` with their reasoning.

---

## 1. Read two numbers off the plan page

Before touching anything, write these down from **your provider's own plan page** —
not from this document, and not from memory. They differ per provider and per plan, and
they change:

1. **Simultaneous connection limit.** → `REDIS_CONNECTION_CEILING`
2. **Idle connection timeout.** Must be comfortably *above*
   `REDIS_HEALTH_CHECK_INTERVAL_SECONDS` (default 30s), or the provider closes idle
   sockets between our health pings and every reuse fails.

There is deliberately no default for `REDIS_CONNECTION_CEILING`. A guessed ceiling
produces an audit that is confidently wrong, which is worse than one that says it does
not know — and at `0` the startup log says exactly that (`redis_connection_ceiling_unknown`).

Also confirm the provider gives you a **`rediss://`** URL. If the dashboard offers both,
take the TLS one.

## 2. Size the pool against that ceiling

```
REDIS_MAX_CONNECTIONS × WEB_REPLICA_COUNT  ≤  REDIS_CONNECTION_CEILING
```

Defaults are `20 × 1 = 20`. Startup warns at 80% of the ceiling
(`redis_pool_budget_near_ceiling`) and again once over it
(`redis_pool_budget_over_ceiling`). Both name the arithmetic, so the log line is
actionable without opening this file.

Past the ceiling the provider **refuses new connections**. The symptom is scattered
errors on random requests, not a clean slowdown — which is why the warning fires early.

If the budget does not fit: lower `REDIS_MAX_CONNECTIONS` before lowering replicas. This
app's Redis calls are short (`INCR`, `GET`, `SETEX`) and a pool is a concurrency limit,
not a throughput limit — 10 per replica is ample at the traffic this service sees.

## 3. Verify TLS works *before* pointing production at it

The end-to-end path is covered by a test that stands up a real TLS server behind a real
self-signed CA and PINGs it through this application's own pool:

```bash
cd backend && uv run pytest tests/test_redis_managed.py -v
```

`test_rediss_url_completes_a_verified_tls_handshake_end_to_end` proves the pool
negotiates TLS and verifies the certificate;
`test_rediss_handshake_fails_when_the_certificate_is_not_trusted` proves the
verification is real rather than nominal. Without the second, the first proves nothing.

Then check the actual provider, from a shell that can reach it:

```bash
cd backend && REDIS_URL='rediss://default:PASSWORD@your-host:6379' \
  uv run python -c "
import asyncio
from app.db.redis import check_redis_connection, url_is_tls
from app.core.config import settings
print('tls:', url_is_tls(settings.REDIS_URL))
print('ping:', asyncio.run(check_redis_connection()))
"
```

Expect `tls: True` and `ping: True`. If TLS is True but ping is False:

| Symptom | Cause | Fix |
|---|---|---|
| `CERTIFICATE_VERIFY_FAILED` | provider uses a private CA | set `REDIS_TLS_CA_CERTS` to their bundle |
| hangs then `redis_health_check_failed` | firewall / wrong port | TLS port is often *not* 6379 |
| `WRONGPASS` / `NOAUTH` | password not URL-encoded | percent-encode `@ : / #` in the password |

`REDIS_TLS_CA_CERTS` is ignored for a `redis://` URL by design — redis-py's plaintext
connection rejects unknown kwargs outright, so a CA path set for production would
otherwise stop a developer's localhost pool from being built at all.

## 4. Set the variables and deploy

On Render (`render.yaml` marks all three `sync: false`, so they are set in the dashboard):

```
REDIS_URL=rediss://default:PASSWORD@your-host:PORT
REDIS_CONNECTION_CEILING=<number from §1>
WEB_REPLICA_COUNT=<numInstances from render.yaml>
```

`WEB_REPLICA_COUNT` is not read by anything that changes behaviour — it exists so the
startup audits can multiply a per-process budget by the fleet size. **A stale value makes
the audits wrong in the optimistic direction**, so change it in the same commit as
`numInstances`.

## 5. Confirm the cutover from the deploy log

Grep the boot log. Green looks like:

```
redis_connected
```

with **no** `redis_` warning above it. Anything else, in order of severity:

| Log event | Meaning |
|---|---|
| `redis_plaintext_in_production` | still on `redis://` — the password is crossing the internet in the clear |
| `redis_pool_budget_over_ceiling` | connections will be refused under load |
| `redis_pool_budget_near_ceiling` | one more replica breaches it |
| `redis_connection_ceiling_unknown` | §1 was skipped; nothing is being checked |
| `redis_unreachable_at_startup_running_degraded` | see §6 |

## 6. What you are exposed to while it is broken

Redis being down is **not** an outage, and that is the design — but three protections
stop existing silently, and two of them cost money:

- **Rate limiting fails open.** `core/rate_limit.py` catches `RedisError` and returns, so
  every limit in the app stops existing — including the one on report generation, the
  most expensive call there is.
- **The AI daily spend cap becomes per-process.** `anthropic_provider._spend_today` falls
  back to a local counter, so the effective ceiling is `AI_DAILY_BUDGET_USD × replicas`
  and it resets on restart. The same applies to `services/tts/spend.py`.
- **The interview-plan semantic cache always misses**, at roughly $0.065 a miss.

This is why `redis_unreachable_at_startup_running_degraded` is logged at ERROR in
production. Alert on it — see [[UPTIME]].

## 7. Rolling back

Set `REDIS_URL` back to the previous value and redeploy. There is no schema, no
migration and no persistent state to unwind: everything in Redis is either a TTL'd cache
entry or a fixed-window counter that repopulates within one window. Anything mid-flight
degrades exactly as in §6 for the length of the redeploy.

---

## Deliberately out of scope

**Redis Cluster, client-side sharding, and distributed locks.** Nothing in this codebase
needs them. All Redis usage is single-key `INCR` / `GET` / `SETEX` against small values;
the one multi-key structure (`plan:sigindex`, ~200 entries) is a bounded list read whole.
A managed primary with automatic failover covers the availability requirement, and the
retry/jitter/health-check settings in §2 cover the blip while it happens.

**Making Redis a hard startup dependency.** Rejected on the same grounds `main.py`
already states: refusing to boot trades a working-but-degraded service for no service.
