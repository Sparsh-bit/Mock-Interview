> Part of the [[index|InterviewOS documentation]].

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
at $15/M is $0.0837 of its $0.1349. **Prompt caching cannot fix this** — there is not
enough input in it to matter.

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
5. **Then re-derive this whole document from the `ai_usage` ledger**, which is what it is
   for. Every estimate above should become a measurement.

Per-user quotas are also the natural shape of the credit/subscription system the
`ai_usage` ledger is a placeholder for (see [[TEMPORARY-token-counter]]), so this is
groundwork rather than a detour.
