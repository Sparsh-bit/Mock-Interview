> Part of the [[index|Hotseat documentation]].

# Uptime monitoring — runbook

**Written to be followed by somebody who is not an engineer.** Every step says what to
click, what to type, and what you should see. Where a choice matters, the reason is one
sentence.

---

## The one thing that makes this different from every other uptime setup

> ### `/api/v1/health` returns **HTTP 200 even when the database is down.**

That is deliberate — the endpoint reports the state of each dependency in its **body** and
lets the caller decide, so that a Redis outage does not make a load balancer pull a working
service out of rotation. The consequence for monitoring is blunt:

**A monitor that only checks the status code will show a green tick through a total database
outage.** Candidates would be unable to sign in, start an interview, or see a report, and the
dashboard would say the service was up.

So every check below asserts on the **response body**, not just the code. If you take one
thing from this page, take that.

---

## What is being monitored today, and what was not

There is currently **one** external check: a free cron pinger hitting `/api/v1/health` every
~10 minutes. Its purpose is **not** monitoring. Render's free tier sleeps a service after 15
minutes idle, and the next request pays a ~37-second boot; the ping exists to prevent that
(see [[DEPLOYMENT]] step 8).

**It alerts nobody.** If the service goes down, the ping fails silently and the first person
to find out is a candidate mid-interview. That is the gap this runbook closes.

The keep-warm ping **stays** — it does a job monitoring does not. Configure it so that a
monitor at a 3-minute interval also keeps the service warm, and the separate pinger becomes
redundant; delete it only once the monitor is confirmed working.

---

## Endpoints to monitor

Three checks. Each answers a different question, and the second is the one worth having.

### 1. Is the API process alive?

| | |
|---|---|
| **URL** | `https://<your-render-host>/api/v1/health` |
| **Method** | `GET` |
| **Frequency** | **every 3 minutes** |
| **Healthy** | HTTP `200`, and the body contains `"status": "ok"` |
| **Alert when** | 2 consecutive failures (~6 minutes) |
| **Regions** | Mumbai (`ap-south-1`) primary; Singapore (`ap-southeast-1`) secondary |

**Why 3 minutes and not 1.** Render's free tier is one small container. A 1-minute check from
several regions is real traffic on a box that is also serving interviews, and it buys 2
minutes of detection speed. Three minutes also sits comfortably under the 15-minute sleep
threshold, so this check keeps the service warm on its own.

**Why 2 consecutive failures and not 1.** A single failed request on a free container is
usually a cold start, not an outage. Alerting on one produces a false alarm most nights,
and an alert people learn to ignore is worse than no alert.

A healthy response looks like this:

```json
{
  "status": "ok",
  "database": "connected",
  "redis": "connected",
  "supabase": "connected",
  "dependencies_healthy": true
}
```

### 2. Are the dependencies actually healthy? — **the important one**

| | |
|---|---|
| **URL** | `https://<your-render-host>/api/v1/health` |
| **Frequency** | **every 5 minutes** |
| **Healthy** | body contains `"dependencies_healthy": true` |
| **Alert when** | 3 consecutive failures (~15 minutes) |

This is the check that catches the outage check 1 cannot see. Read the body to tell which
dependency broke, because the three are **not** equally serious:

| Field | If it says `unreachable` | Severity |
|---|---|---|
| `database` | Nothing works. No sign-in, no interview, no report. | **Page somebody.** |
| `supabase` | Sign-in is broken; existing sessions may continue for a while. | **Page somebody.** |
| `redis` | The app keeps working and **silently stops protecting you** — see below. | **Same day, not 3 a.m.** |

> **Redis being down is a money problem, not an availability problem, and it is invisible at
> the point of failure.** From [[DEPLOY]]: rate limiting **fails open**, so every limit in the
> app stops existing including the 6/hour on report generation; the AI spend cap becomes
> per-process and resets on every restart; and the interview-plan cache always misses at
> roughly $0.065 each. The service looks fine while the bill grows. That is why it is on this
> page at all — nobody would think to check for it.

A longer window (3 failures) is right here because a dependency check crossing the network to
Supabase is legitimately flaky in a way a local process check is not.

### 3. Can a browser actually load the site?

| | |
|---|---|
| **URL** | `https://<your-frontend-host>/` |
| **Frequency** | every 5 minutes |
| **Healthy** | HTTP `200`, and the body contains the product name |
| **Alert when** | 2 consecutive failures |

Checks 1 and 2 pass while the frontend is entirely broken — they are different hosts on
different providers (Render and Cloudflare Pages). Without this, a failed Pages deploy is
invisible.

---

## What NOT to monitor, and why

- **Anything requiring a login.** A monitor needs a credential, that credential lives in the
  monitoring tool, and it is a real account with real interview data behind it. The value is
  not worth a standing credential in a third-party dashboard.
- **`POST` anything.** A synthetic monitor that starts an interview spends real money on a
  model call every few minutes, and pollutes the `ai_usage` ledger that [[AI-COST-MODEL]]
  and every budget decision are derived from.
- **Response time as a pager.** A cold start is ~37 seconds by design on the free tier. A
  latency alert would fire nightly. Record the number, chart it, do not page on it.

---

## Alert conditions, in one place

| Condition | Route it to | Urgency |
|---|---|---|
| Check 1 fails twice | Email + phone/push | **Now** |
| `dependencies_healthy: false` with `database` or `supabase` unreachable | Email + phone/push | **Now** |
| `dependencies_healthy: false` with only `redis` unreachable | Email | Same day |
| Frontend check fails twice | Email + phone/push | **Now** |
| Any check recovers | Email | Informational — always send these, or nobody learns how long an outage lasted |

**Send recovery notifications.** A tool that only tells you about failure leaves you unable to
answer "how long was it down", which is the first question anybody asks.

---

## Setting it up

### Option A — Checkly (recommended: the checks live in this repository)

`monitoring/checkly.config.ts` and `monitoring/checks/health.check.ts` are committed here, so
the check definitions are reviewed and versioned like any other code. Nobody can quietly widen
a threshold in a dashboard.

**Human steps — these cannot be done from the repository:**

1. Create a free account at <https://www.checklyhq.com> (no card on the free plan).
2. **User settings → API keys → Create API key.** Copy it.
3. Note your **Account ID** from **Account settings**.
4. In a terminal, from the repository root:

   ```bash
   export CHECKLY_API_KEY='<the key from step 2>'
   export CHECKLY_ACCOUNT_ID='<the id from step 3>'
   export HOTSEAT_API_URL='https://<your-render-host>'
   export HOTSEAT_APP_URL='https://<your-frontend-host>'
   export HOTSEAT_ALERT_EMAIL='<who should be woken up>'

   npx checkly@latest test --config monitoring/checkly.config.ts   # dry run, no deploy
   npx checkly@latest deploy --config monitoring/checkly.config.ts
   ```

   `test` runs every check once and prints the result. **Do that first** — if it fails, the
   URLs are wrong and deploying would create three checks that alert immediately.

5. In the Checkly UI, **Alerts → Alert channels**, confirm the email channel was created and
   **click the confirmation link in the email**. An unconfirmed channel silently sends nothing.
6. Add a phone or push channel for the two "Now" rows in the table above. Email alone does not
   wake anybody.

`npx` is used rather than a committed dependency on purpose: the CLI is needed a few times a
year, and adding it to `package.json` would make every CI run download it.

### Option B — UptimeRobot (no repository changes, fastest to set up)

Free, no card, and it can check the response body — which is the only feature that matters
here.

1. Create an account at <https://uptimerobot.com>.
2. **+ New monitor** → type **Keyword**. **Not "HTTP(s)"** — that type only checks the status
   code, and this endpoint returns 200 while the database is down.
3. URL: `https://<your-render-host>/api/v1/health`
4. **Keyword type: "does not exist"**, keyword: `"dependencies_healthy": true`
   That fires when the phrase is *absent*, which covers both a degraded dependency and the
   service being down entirely.
5. Interval: **5 minutes** (the free plan's floor).
6. Repeat for `https://<your-frontend-host>/` with keyword type "exists" and the product name.
7. **My settings → Alert contacts** — add an email, and confirm it.

The free plan cannot express "2 consecutive failures", so expect the occasional cold-start
false alarm. That is the cost of Option B.

---

## When an alert fires

1. **Open `/api/v1/health` yourself** and read the body. It names the broken dependency.
2. **Database or Supabase unreachable** → check the Supabase dashboard for an incident or a
   paused project. A free Supabase project pauses after a week of inactivity.
3. **Redis unreachable** → check Upstash. Then grep the Render logs for
   `redis_unreachable_at_startup_running_degraded`, which spells out what has stopped
   protecting you.
4. **Everything reports connected but the check still fails** → the container is likely
   restarting. Render dashboard → **Logs**. A crash loop shows as repeated startup lines.
5. **Nothing responds at all** → confirm the Render service exists and has not been suspended.
   As of this writing `interviewos-api.onrender.com` returns 404 from Render's own router,
   which is what a deleted or never-recreated service looks like.

---

## Still needs a human

- Creating the Checkly or UptimeRobot account and confirming the alert channels.
- Deciding **who** gets woken up, and adding a phone or push channel for them. Email-only
  alerting is monitoring you will not hear.
- Filling in the two hostnames. This runbook writes them as `<your-render-host>` and
  `<your-frontend-host>` because **there is no live deployment to read them from**:
  `interviewos-api.onrender.com/api/v1/health` returns 404 and `interviewos.dev` does not
  resolve. Put the real values in [[DEPLOY]] when the service is next deployed.
