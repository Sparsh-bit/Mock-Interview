> Part of the [[index|Hotseat documentation]].

# What the AI actually costs

Answering the direct question: **the $2/day cap — that is one user doing what, how many
times?**

Short answer: **$2/day is roughly 9 full interviews or 14 group discussions, across every
user on the product combined.** One user doing one interview and one GD in a day spends
**$0.37**, so the current cap supports about **5 such users per day** before it trips and
everybody gets the unscored-report fallback until midnight UTC.

(Both GD figures improved after this document's first version: prompt caching cut the GD
round by 59%. See below.)

That cap is a runaway-loop circuit breaker that has been doing duty as a daily allowance.
It needs raising and, more importantly, splitting per user — see *What to change* below.

---

## How these numbers were produced

Prices are Anthropic list for `claude-sonnet-5`: **$3.00 per million input tokens,
$15.00 per million output**. Output is 5× input, which is why every figure below is
dominated by how much the model *writes*, not how much it reads.

One call was measured end to end and is the anchor for everything else:

| | tokens | cost |
|---|---|---|
| report for a 2-question session | 4,452 in / 2,129 out | **$0.045291** (logged) |

`4452 × $3/M + 2129 × $15/M = $0.045291` — exact, so the pricing path is verified.

From that anchor plus two things that can be measured exactly — the byte size of each
prompt template, and each feature's `max_tokens` in code — the rest follows:

- report system prompt: 10,605 chars ≈ **2,651 tokens**
- so per question-and-answer pair in a report: `(4452 − 2651) / 2` ≈ **900 input tokens**
- and per `question_analysis` entry: `(2129 − 1200) / 2` ≈ **464 output tokens**

Session shape comes from the code, not assumption: `_PLANNED_QUESTION_COUNT = 12`,
`INTERVIEW_MAX_CROSS_QUESTIONS = 4`, `plan_token_budget(12) = 3820`,
`report_token_budget(12) = 5580`, `MAX_PANEL_TURNS = 26`.

**Marked estimates.** Input token counts for features other than the report are derived
from prompt size plus a per-call payload estimate; output is assumed to reach its
`max_tokens` where the response is structurally large (plan, report) and to fall well
short where it is one short question (cross-question, panel turn). Replace all of these
by querying the `ai_usage` ledger once there is real traffic:

```sql
SELECT feature, count(*), round(avg(input_tokens)), round(avg(output_tokens)),
       round(avg(cost_usd), 5), round(sum(cost_usd), 4)
FROM ai_usage GROUP BY feature ORDER BY 6 DESC;
```

---

## One full mock interview — 12 questions, 4 cross-questions, 1 report

| feature | calls | in | out | $/call | $/session | note |
|---|---:|---:|---:|---:|---:|---|
| `interview_plan` | 1 | 2,536 | 3,820 | 0.0649 | **0.0649** | cached — ~$0 on a hit |
| `report_generation` | 1 | 17,059 | 5,580 | 0.1349 | **0.1349** | output hits its 5,580 cap |
| `cross_question` | 4 | 1,093 | 300 | 0.0078 | **0.0311** | only for answers ≥12 words |
| `question_generation` | 0 | 1,043 | 900 | 0.0166 | **0.0000** | fallback only — the plan pre-generates all 12 |
| | | | | | **$0.2309** | cold |
| | | | | | **$0.1660** | with the plan cache hit |

The report is **58%** of an interview's cost, and it is output-bound: 5,580 output tokens
at $15/M is $0.0837 of its $0.1349.

> **This paragraph used to say "prompt caching cannot fix this — there is not enough input
> in it to matter". That was wrong, and it is worth recording why.** The report's input is
> 17,059 tokens, which is not small; what made it uncacheable was that
> `report_generator.md` carried eight `$placeholders`, so the system block differed on every
> report and the provider could never reuse it. The rubric inside it is **2,778 tokens of
> byte-identical text**. Moving the per-session values into a session brief in the user
> message — the same change `_round_brief` made for the GD panel — makes it cacheable, and
> it reads at 0.1x thereafter.

### Two changes, measured

| change | mechanism | $/report |
|---|---|---:|
| study resources no longer generated | attached from the verified library instead | **−0.0036** |
| the 2,778-token rubric is cached | placeholders moved to the user message | **−0.0080** |
| | | **−0.0116** |

The resources figure is the measured size of the JSON the model used to emit — 876
characters across three roadmap items, ~237 output tokens of the 5,580 cap. It is the
smaller of the two and was worth doing anyway: a book title or a docs URL is exactly the
kind of plausible detail a model invents, and `resources.yaml` is human-verified.

**Report: $0.1349 → $0.1233 (−8.6%). Warm interview: $0.1660 → $0.1544 (−7.0%).**
`$2/day` goes from 12.0 warm interviews to **13.0**.

### Which of these get cheaper as the product gets busier

This is the distinction that matters for pricing, and only two of the four mechanisms in
this codebase have it:

| mechanism | improves with scale? | why |
|---|---|---|
| **shared vector cache** | **yes, permanently** | keyed by topic/plan, so the key space is bounded by the syllabus, not the user count. It saturates: once every topic has been generated once, it is free for every future user. |
| **provider prompt caching** | **yes, while busy** | an entry lives ~5 minutes and each read refreshes it. Near-zero hit rate at one report a day; near-100% once reports are minutes apart. |
| curated library | no — but already zero | a fixed asset. Costs nothing at any scale. |
| per-candidate generation | **no** | the report's judgement, a cross-question, a GD turn. Identical cost on user one and user ten thousand. |

The last row is the honest limit. Most of what is left in an interview is per-candidate
judgement, and no cache makes that cheaper — which is why the plan cache (−28% on a hit)
and the GD prompt cache (−59%) remain the two biggest wins in this document, and why the
next one is unlikely to come from caching at all. See **What to change** below.

## One full group discussion — 8 minutes, 26 panel turns

| feature | calls | in | out | $/call | $/round | note |
|---|---:|---:|---:|---:|---:|---|
| `gd_panel_turn` | 26 | 336 + 2,856 cached | 350 | **0.0045** | **0.1259** | prompt caching now on — was $0.0119/turn |
| `gd_evaluation` | 1 | 1,463 | 800 | 0.0164 | **0.0164** | |
| `gd_topic_prep` | 1 | 741 | 900 | 0.0157 | *0.0157* | custom topics only — **now cached** |
| | | | | | **$0.1423** | was $0.3562 |

**Prompt caching is now on for this feature and it is measured, not projected.** The
static rulebook is 2,856 tokens; the first turn of a round writes it to cache at 1.25×
($0.0143) and every subsequent turn reads it at 0.1× ($0.0045 against $0.0119 before).
Across 26 turns that is **$0.310 → $0.126, a 59% cut**, and it takes the whole GD round
from $0.356 to **$0.142**. `$2/day` goes from ~6 GD rounds to **~14**.

The cache entry has a 5-minute TTL and each read refreshes it, so with a panel turn every
18 seconds a round stays warm from start to finish.

**The GD round WAS the most expensive thing in the product**, more than a full interview,
and that was not obvious before measuring it. It is 26 small calls rather than one big one,
and unlike everything else it was **input**-dominated: $0.0078 of input against $0.0053 of
output per turn, because every turn re-sent the same static system prompt plus the growing
transcript. At $0.142 it is now cheaper than an interview, and the report is once again the
most expensive single call.

That made it the one place where prompt caching was worth real money, and it is **now
done and measured**: `gd_panel.md` carries no placeholders and is loaded verbatim as the
system block, with the per-round content (roster, topic, transcript, situation, phase,
name) moved into the user message by `_round_brief` in `api/v1/gd.py`. Caching is opt-in
per call (`ProviderRequest.cache_system`) rather than a global setting, because a global
flag would bill a 1.25× cache *write* on every other feature — whose prompts do still
carry per-request substitutions — and never read. Only `gd_panel_turn` opts in.

Realised saving: **59% off the round**, better than the 37% projected, because the static
block turned out to be 2,856 tokens rather than the 1,906 estimated from the template
alone.

---

## What $2.00/day buys, across all users combined

| | count |
|---|---:|
| full interviews, cold plan | **8.7** |
| full interviews, plan cache hit | **12.0** |
| full GD rounds | **14.0** (was 5.6 before caching) |
| reports alone | **14.8** |
| users doing 1 interview + 1 GD | **5.4** (was 3.4) |

An earlier note in this repo said "~44 reports/day". That was derived from the
2-question test report at 4.5¢; a real 12-question report is 13.5¢, so the true figure is
**~15**.

---

## What to change

1. **Split the cap per user.** It is global today, so one user — or one test run, which is
   how this was discovered — starves everybody until midnight UTC. Cheap features should
   not be blocked because an expensive one ran.
2. **Raise the global cap to be a circuit breaker, not an allowance.** Its job is stopping
   a runaway loop, and at a thousand users a real day is hundreds of dollars, so $2 cannot
   be both.
3. **Distinguish the two failures in the UI.** "You have used your practice for today" and
   "the service is over its safety limit" must not look the same, and neither should look
   like a crash. Today both produce the unscored-report placeholder.
4. ~~Restructure `gd_panel.md` for prompt caching~~ — **done**, 59% off the GD round.
5. ~~Restructure `report_generator.md` for prompt caching~~ — **done**, with the study
   resources moved to the verified library. 7.0% off a warm interview.
6. **The Message Batches API, for reports** — **built, off by default.** Anthropic bills
   batch requests at **50%**, and a report is the one call in this product that does not
   have to be synchronous — the interview is already over. At $0.1233 that is **−$0.062 a
   report, ~40% of a warm interview**, which is many times everything above put together.
   It composes with the caching win above rather than replacing it: a cached read inside a
   batched request bills at 0.5x the already-reduced cache rate.

   The path exists — `services/ai/batch.py`, `services/report/batch_job.py`,
   `services/report/batch_runner.py`, the `report_jobs` table and a "your report is being
   written" state on the report page that polls `GET /reports/{id}/job`. It is gated on
   `REPORT_BATCH_ENABLED`, which **defaults to false**.

   THE FLAG IS OFF BECAUSE THE REMAINING DECISION IS THE ONE THIS NOTE ALWAYS SAID IT WAS:
   a product decision, not a refactor. Turning it on changes what somebody sees after
   finishing an interview from "here is your report" in ~15s to "we are preparing your
   report" for minutes. That is worth costing before the price is set, because it changes
   what the free tier can afford — and it is not a call to make by choosing a default.

   What is no longer a risk is the thing that made this feel dangerous. A report cannot get
   stuck: submission failure runs the synchronous path in the same request, a session gets
   at most one batch attempt ever (unique on `session_id`), a batch that has not ended by
   `REPORT_BATCH_MAX_WAIT_SECONDS` is abandoned, and a batch that cannot even be reached is
   abandoned after three consecutive failed lookups. Every route out ends somewhere a
   report gets written. `tests/test_report_batch.py` is that argument in full.

   Only `report_generation` and `report_analysis` are eligible, enforced by a closed
   allowlist — nothing a candidate is waiting on may be answered on somebody else's
   schedule.
7. **Shorten the report.** It sits on its 5,580-token output cap, which means the model is
   being truncated rather than choosing to stop — so nobody knows how long it *would* be.
   Output is $0.0837 of $0.1233. Any honest reduction here is money, and a report a
   candidate actually finishes reading is also a better report.
8. **Then re-derive this whole document from the `ai_usage` ledger**, which is what it is
   for. Every estimate above should become a measurement.

Per-user quotas turned out to be exactly what shipped: see
`backend/app/services/billing/`, which meters interviews, GDs and communication drills
against a per-plan allowance. The `ai_usage` ledger it was groundwork for is still the
thing to re-derive this document from (see [[TEMPORARY-token-counter]]).
