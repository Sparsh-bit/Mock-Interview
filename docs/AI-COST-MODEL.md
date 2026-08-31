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
5b. ~~Restructure `interview_plan.md` and `question_generator.md` for prompt caching~~ —
   **done**, and measured rather than projected. Both carried per-request `$placeholders`
   in the system block, which is why caching was off: a unique prefix bills a 1.25x cache
   WRITE on every call and never reads. The varying parts moved into a brief in the user
   turn (`_plan_user_brief`, `_question_user_brief` in
   `services/interview/orchestrator.py`) and the rules are now loaded verbatim.

   **Confirmed from the `ai_usage` ledger**, two live calls per prompt through the real
   provider, not assumed:

   | call | total input | cache **read** | cache write | output | USD |
   |---|---|---|---|---|---|
   | `interview_plan` #1 | 7,222 | 0 | 6,873 | 1,340 | 0.046921 |
   | `interview_plan` #2 | 7,221 | **6,873** | 0 | 1,405 | **0.024181** |
   | `question_generation` | 3,130 | **2,957** | 0 | 280 | **0.005606** |
   | `question_generation` | 3,134 | **2,957** | 0 | 301 | 0.005933 |
   | `question_generation` | 3,143 | **2,957** | 0 | 549 | 0.009680 |

   Against the same calls billed with no cache at all:

   - **`interview_plan`: −43.4% on a hit** ($0.042738 → $0.024181). It is 6,546 tokens, the
     largest prompt in the product, and every interview created used to re-send and re-pay
     for all of it.
   - **`question_generation`: −58.7% on a hit** ($0.013590 → $0.005606) — the same order as
     the GD panel's 59%, and for the same reason: a small output means input dominates.

   THE MISS COSTS 9.8% MORE, and that number matters more than it looks. A cache write bills
   at 1.25x, so the first call in a window is *dearer* than it was — the change is only a
   saving once something reads. That is why the two prompts are worth different amounts:

   - `question_generator` is called once per generated question and repeatedly WITHIN one
     session, so the first question pays the write and every question after it reads, inside
     the entry's own five-minute life. It banks reliably.
   - `interview_plan` is generated once per interview, so its hit rate depends on another
     candidate arriving within five minutes. It is near zero for one user a day and near
     100% during a campus drive — a saving that arrives as the product gets busier, which is
     also when it is most needed.

   The two `question_generator` call sites — the shared-pool batch of five and the
   per-session single question — share one cache entry, because both load the same file
   verbatim. Whichever runs first writes the prefix the other reads.
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
6b. **Route `CostTier.CHEAP` to Claude Haiku** — **built, off by default, and the numbers
   are the reason.** `claude-haiku-4-5` was already in the price sheet at $1/$5 per MTok
   against Sonnet 5's $3/$15 and was never selected by anything: every cost tier resolved to
   the same model, so the cheapest tier in the product still ran on Sonnet.

   It is selectable now, via `ANTHROPIC_CHEAP_MODEL` plus a feature allowlist in
   `services/ai/model_routing.py`. **The allowlist is panel dialogue only** —
   `gd_panel_turn` and `interview_panel_turn`. The other four CHEAP call sites either GRADE
   a candidate (`gd_evaluation`, `communication_evaluation`) or write into a cache served to
   every other candidate on the track (`question_bank`, `study_resources`), and a model that
   marks half a point more generously is a worse product in a way nobody sees from a diff.

   ### The side-by-side

   Nine realistic panel moments — wrong answer, good answer, half-right answer, "I don't
   know", intro, skill check, candidate question, code review, pivot — both models, the real
   `interview_panel.md` system block, identical briefs. Run **twice**, independently.

   | | Sonnet 5 | Haiku 4.5 |
   |---|---|---|
   | usable responses | 9 / 9 | 9 / 9 |
   | schema or `is_valid` failures | 0 | 0 |
   | invented speakers | 0 | 0 |
   | mean words per line | 14.3 / 14.4 | 18.5 / 18.2 |
   | longest line (words) | 23 / 23 | **46 / 41** |
   | **lines over the prompt's 25-word limit** | **0 / 0** | **6 / 6** |
   | name-rule violations | 0 / 0 | 1 / 1 |
   | wrong `asked_question` flag | 2 / 2 | 0 / 1 |
   | mean latency | 2.39s / 2.37s | 2.35s / 2.47s |
   | cost for the nine calls | $0.0516 / $0.0502 | $0.0207 / $0.0152 |

   **Haiku is 60–70% cheaper at the same latency, and it breaks the panel's own rules.**
   `interview_panel.md` says "One or two sentences" and "Twenty-five words". Haiku produced
   six over-length lines out of roughly twenty-one in *both* runs where Sonnet produced
   zero in both; the reproducibility is what makes this a finding rather than a bad sample.
   It used the candidate's name in a turn whose brief said in capitals not to. And on the
   wrong-answer scenario it explained ConcurrentModificationException instead of asking the
   follow-up — the exact lecturing that prompt was rewritten to stop and that
   `tests/test_panel_brevity.py` exists to guard.

   It is fair to Haiku to record what it won: it never invented a speaker, never failed the
   schema, and set `asked_question` correctly more often than Sonnet did.

   ### What it would be worth, and why it is off

   Panel dialogue is ~16 calls in an interview and up to ~26 in a GD round, at roughly
   $0.0057 each on Sonnet. At 65% off that is about **−$0.06 an interview and −$0.10 a GD
   round** — the same order as the Batches API saving, and available on the live path where
   batching can never go.

   It is off because buying it means shipping a panel that breaks its own brevity rule about
   a third of the time, and that is a product decision rather than a default. **What would
   change the answer:** the brevity rule is currently prose in the prompt. A validator on
   the returned turns — reject any line over twenty-five words the way `is_valid` already
   rejects an empty one, and let `generate_structured` retry — would make the rule
   enforceable rather than advisory, at which point Haiku's cost profile makes it the
   obviously correct model for dialogue. That is the next piece of work here, not more
   comparison.

   ### One bug this found, which was the point of measuring

   The first run failed **9 out of 9** on Haiku with `400 invalid_request_error: This model
   does not support the effort parameter`. Haiku 4.5 rejects `output_config.effort` and
   rejects adaptive thinking; Sonnet 5 requires the first and accepts the second. The
   provider now carries a per-model capability table and omits what a model will not take.

   Shipped unmeasured, that would have been close to invisible: a panel turn that 400s
   returns no turns, the caller falls back to putting the bare question, and the interview
   carries on looking slightly flat. That exact symptom has already cost this repo a
   four-round investigation into the wrong layer.

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
