> Part of the [[index|Hotseat documentation]].

# Anthropic rate-limit headroom at 200 concurrent users

The estimate lives in `backend/scripts/rate_limit_headroom.py` and is meant to be **run**,
not quoted — every assumption is a named constant you can change and re-run:

```bash
cd backend && uv run python scripts/rate_limit_headroom.py
```

Related: [[AI-COST-MODEL]] · [[MULTI-REPLICA]] · [[DEPLOY]] · [[TEMPORARY-token-counter]]

**Nothing here contacted Anthropic or read an account.** The tier limits are the published
figures; the load model is derived from this repository and from [[AI-COST-MODEL]].

---

## The answer

| | peak RPM | peak ITPM | peak OTPM |
|---|---:|---:|---:|
| **A** — 200 concurrent users, steady state | 207 | 194,138 | 111,333 |
| **B** — a cohort's reports land together | 103 | 584,880 | 191,314 |
| *Start tier limit (`claude-sonnet-5`)* | *1,000* | *2,000,000* | *400,000* |

**Both scenarios fit inside the Start tier, and the binding constraint is neither of the
two people usually worry about.** It is **output tokens**:

- Scenario A: OTPM at **28%** of the Start limit (RPM at 21%, ITPM at 10%)
- Scenario B: OTPM at **48%** (RPM at 10%, ITPM at 29%)

Two structural reasons, and they compound:

1. **OTPM is one fifth of ITPM on every published tier** (400k vs 2M on Start).
2. **This product's expensive call is one that writes a lot.** A report is 5,580 output
   tokens against 17,059 input — and it is 58% of an interview's cost.

### The number to watch

Scenario B scales linearly with the replica count, because what bounds the report burst is
not the provider — it is `_report_slots`, `REPORT_CONCURRENCY` per process:

| replicas | peak OTPM | % of Start tier |
|---:|---:|---:|
| 1 | 191,314 | 47.8% |
| 2 | 382,629 | **95.7%** |
| 3 | 573,943 | **143.5% — over** |
| 4 | 765,257 | **191.3% — over** |

**The semaphore is the rate limiter.** That is worth knowing before anyone raises
`REPORT_CONCURRENCY` to make reports faster, or raises `numInstances` to serve more users:
either one moves this number, and at the current default the second replica lands at 96% of
the tier limit. [[MULTI-REPLICA]] lists this among the four things that must move together
with the replica count; this table is why.

---

## Two properties of Anthropic's limits do most of the work

Both are from the published rate-limit documentation, and both are easy to get backwards:

**`cache_read_input_tokens` do not count toward ITPM** on this model. Only
`input_tokens + cache_creation_input_tokens` do. The GD panel re-sends a 2,856-token static
rulebook on all 26 turns of a round, and 25 of those are cache reads — so the feature that
looks like the ITPM problem is not one. Counting them would overstate GD's ITPM by roughly
9×. A test pins this so the model cannot quietly start counting them.

**`max_tokens` does not count toward OTPM.** Only tokens actually generated. So the report's
`ANTHROPIC_MAX_OUTPUT_TOKENS` ceiling of 12,288 is irrelevant here, and its measured ~5,580
is what matters. There is no rate-limit reason to lower a `max_tokens`.

---

## Every assumption, stated so it can be attacked

The script labels each input `[CODE]`, `[MEASURED]`, or `[ASSUMED]`. Only the third kind can
really be wrong, so those are the ones to argue with.

### The one that matters most

**"200 concurrent users" is read as 200 people with a session open at the same moment — not
200 requests in flight.** The difference is about two orders of magnitude, because a
candidate spends most of an interview reading and typing rather than waiting on a model. If
the intended meaning was 200 simultaneous in-flight calls, every figure above is wrong and
the answer is simply *"far past Start tier"*. **Check this reading first.**

### The rest

| Assumption | Value | Why, and which way it errs |
|---|---|---|
| Seconds per interview exchange | 90s | Not in the code — it is human behaviour. Deliberately brisk: too low **overstates** the request rate, which is the safe direction for a headroom estimate. |
| Activity mix | 60% interview / 25% GD / 15% idle-or-quiz | A guess about a campus cohort. `idle_or_quiz` makes **no** metered call — quizzes are unlimited on every tier and served from the banks in `app/data`. |
| Report input tokens per call | 17,059 ÷ 3 | **The one under-estimate, flagged rather than hidden.** [[AI-COST-MODEL]] measured 17,059 for a *single-call* report; the composer now splits it into 3 calls that each re-send the system block, so real input is higher. It affects ITPM, which has the most headroom of the three. |

### Taken from the code, and pinned by a test

`INTERVIEW_QUESTION_COUNT` (12), `INTERVIEW_MAX_CROSS_QUESTIONS` (4), `REPORT_CONCURRENCY`
(12), `BATCH_SIZE` (6), `WEB_REPLICA_COUNT` (1), and the derived **3 provider calls per
report** (one summary + one per batch of 6).

That last one is a correction: [[AI-COST-MODEL]] prices a report as a single call, which is
right for dollars and **wrong for RPM**. `backend/tests/test_rate_limit_headroom.py` asserts
each of these against its source, so the analysis cannot keep printing confident numbers
about a system that has moved underneath it. The `[ASSUMED]` constants are deliberately
**not** pinned — a test would only make a judgement call look settled.

---

## Rate limits are not the ceiling this product hits first

Worth saying plainly, because it reframes the question:

- The Start tier's **monthly spend cap is $500**. At $0.1544 for a warm interview
  ([[AI-COST-MODEL]]) that is ~3,238 interviews a month, ~108 a day.
- `AI_DAILY_BUDGET_USD` defaults to **$60/day** — **$1,800/month**. That is already over the
  Start cap ($500) *and* over Build's ($1,000).

So the first wall is **the spend cap, not RPM**, and the circuit breaker is currently
configured above two of the three tiers' monthly ceilings. Reaching a spend cap returns
HTTP 429 with `error_code: enforced_spend_limit_reached` and **no `retry-after` header**, so
the SDK's automatic retries cannot recover from it — it is a different failure from a rate
limit that happens to share a status code, and worth telling apart in logs.

## What would make this analysis obsolete

1. **Real traffic.** Every `[MEASURED]` figure here descends from one logged call. The
   `ai_usage` ledger exists to replace them — the SQL is in [[AI-COST-MODEL]].
2. **The Message Batches API for reports.** [[AI-COST-MODEL]] item 6: batch requests bill at
   50% *and* draw on a separate limit pool, which would take the binding constraint —
   report OTPM — off the Messages API bucket entirely. It is the single largest change
   available to both cost and headroom.
3. **A different model.** Limits are per-model and not pooled: `claude-sonnet-5` has its own
   bucket, explicitly separate from Sonnet 4.x.
