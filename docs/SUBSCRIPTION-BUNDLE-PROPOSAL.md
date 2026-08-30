# Proposal: "unlimited practice, pay per real interview"

> **STATUS: PROPOSAL. NOT A DECISION, AND NOT SCHEDULED.**
>
> Nothing in this note is implemented and nothing in it should be implemented until the
> go/no-go thresholds in [§6](#6-gono-go-thresholds) are met against real data. It exists so
> that when somebody asks "should we bring back subscriptions?" — and somebody will — the
> answer is a measurement rather than an argument.
>
> `services/billing/plans.py` documents a deliberate, working pivot **away** from
> subscriptions. This proposal does not overturn that. It describes the one shape that could
> coexist with it, and states in advance what would have to be true for it to be worth
> building.

Related: [[AI-COST-MODEL]] · [[TEMPORARY-token-counter]] · `backend/scripts/item_margin.py` ·
`backend/app/services/billing/plans.py`

---

## 1. What is being proposed

One new purchasable thing, behind a feature flag:

**Practice Pass — ₹199, one month, unlimited communication drills. Interviews and group
discussions are unaffected and still cost ₹49 and ₹39 each.**

That is the whole product change. The name matters less than the split:

| | today | under the Pass |
|---|---|---|
| quizzes | free, unlimited | unchanged — free, unlimited |
| communication drills | ₹19 each, 1 free trial | **included, subject to a fair-use ceiling** |
| mock interviews | ₹49 each | ₹49 each |
| group discussions | ₹39 each | ₹39 each |
| reports | included with the interview | unchanged |

**Why this split and not "unlimited everything".** An interview is the expensive thing and
the thing people actually value — `plans.py` prices it highest for both reasons, and it is
the only item that ends in a full report. Putting it inside a subscription reintroduces
exactly the bet the pivot removed: a student deciding in advance how many interviews they
will sit next month. Practice is the opposite shape. It is the habit, it is cheap to serve,
and its natural cadence is "a bit most days", which is what a monthly price fits.

**Why not just make drills free.** Because at ₹19 they are already priced well above cost
deliberately — `plans.py` says so: "at ₹5 it would be an impulse buy nobody values". Free
practice and a paid interview is a different product with a different funnel; a Pass keeps
practice a paid, valued thing while removing the per-use decision that stops somebody
opening the app on a Tuesday.

---

## 2. The argument against it, stated first

`plans.py`'s docstring is the strongest case against this proposal and it should be read in
full before the case for. Its core claim:

> A subscription asks somebody to bet ₹299 on using the product enough to justify it. The
> users here are campus students with a placement season a few weeks long: they want three
> interviews the week before a drive and nothing for the two months after. For that shape, a
> monthly plan is a bad deal in both directions — they overpay in quiet months and feel
> metered in busy ones.

Three things follow from that, and none of them are answered by this proposal:

1. **The seasonality is real and it is not a hypothesis.** If usage is concentrated into a
   three-week placement window, a monthly price is wrong for almost everybody almost all the
   time, and no amount of packaging fixes it.
2. **A subscription is a bigger decision than a purchase.** "Is one more mock interview worth
   ₹49" is asked at the moment the answer is obviously yes. "Is this worth ₹199 a month" is
   asked cold.
3. **Two pricing models is two paywalls, two support conversations, and two ways for the
   ledger to be wrong about somebody's money.** That cost is real and permanent, and it is
   paid on day one for a benefit that only arrives if the behaviour is there.

**This proposal's only answer to all three is §6: do not build it until the data says the
behaviour exists.** If the thresholds are not met, the honest conclusion is that the pivot
was right and this note should be deleted rather than revisited.

---

## 3. How it coexists with `credit_events`

The hard constraint: **the ledger's invariants do not change.** `credit_events` is
append-only and signed, a balance is one `SUM(delta)`, and there is no stored balance
anywhere. Anything that needs an exception to that is not this feature.

### 3.1 The Pass is a purchase, like everything else

Buying it writes the ordinary `kind='purchase'` row with `detail.amount_paise = 19900`, so
`/admin/revenue` counts it as revenue with no change at all. It differs from a pack only in
what `detail` carries: a period, `{"bundle": "practice_pass", "until": "<ISO date>"}`.

**No new table for entitlement.** The temptation is a `subscriptions` table with a state
machine; the temptation should be refused. A Pass is a purchase row with an end date, and
"is the Pass active" is a predicate over rows this system already has — which is the same
reasoning that removed `period_start`/`period_end` from `user_plans` when subscriptions went
away the first time. Every one of those columns was a place to be wrong about somebody's
money.

### 3.2 A covered consumption is still a consumption

This is the part that matters and it is where an implementation would go wrong.

The wrong design is for `consume` to return early when a Pass is active. That would mean no
`-1` row, and everything downstream that counts consumption breaks silently: report access
finds the session's consume row and would find nothing; `scripts/item_margin.py` divides AI
spend by consume rows and would divide by a number that no longer counts covered sessions;
the "was this free or paid" audit field would have no answer.

The right design writes **both** rows, in one transaction:

```
+1  kind='grant'    feature='communication'  detail={"reason": "bundle_covered", …}
-1  kind='consume'  feature='communication'  detail={"paid_with": "bundle", …}
```

Net zero, so `SUM(delta)` is unchanged and a Pass holder's purchased packs are untouched.
Every session still has exactly one attributable consume row. `paid_with` gains a third value
beside `"trial"` and `"credit"`, which is precisely the question a support ticket asks.

### 3.3 Four things elsewhere that this breaks, and what each needs

Written down because each is invisible until it is wrong.

| what | why it breaks | what it needs |
|---|---|---|
| `/admin/revenue` `free_grants` | counts every `kind='grant'` row. A Pass writes one per drill, so a launch reads as a promotion running away | separate `reason='bundle_covered'` out of that count |
| **Referral qualification** | `referrals.on_paid_consumption` fires on `paid_with == 'credit'`. A Pass holder has paid — more than a drill buyer — but would never qualify a referral | accept `"bundle"` as qualifying, and say so in that module |
| `credits.consume`'s `paid_with` | the "trial first, then credit" derivation assumes two pots | a third branch, checked before the other two |
| `scripts/item_margin.py` | its per-item AI cost divides by consume rows, which is still right; but a Pass drill has **no per-item price**, so its margin line becomes meaningless | price Pass drills against the Pass, not the ₹19 list price — a separate row, not a fudged one |

### 3.4 The feature flag

`PRACTICE_PASS_ENABLED`, default **false**, gating three things: whether the item appears in
`ITEMS`, whether `consume` looks for an active Pass, and whether the paywall offers it. Off
is the current product exactly, with no dead rows and no behaviour change — which is the
property that makes shipping it dark and measuring it safe.

---

## 4. The economics, and the fair-use ceiling

From `scripts/item_margin.py`, at Fish (the default vendor) and measured baseline costs:

```
communication drill    $0.0200 AI + $0.0045 speech  =  $0.0245 to serve
Practice Pass          ₹199  =  $2.358 gross, less 2.36% gateway  =  $2.302 net
```

**$2.302 ÷ $0.0245 = 94 drills before the Pass loses money.**

That number is the whole design constraint, and it is why a ceiling is not optional:

- **Fair use: 3 drills per calendar day, 60 per period.** Sixty is comfortably under 94 and
  is more practice than any candidate does; three a day is more than anyone does in a day.
  The cap exists to bound a script, not to ration a person.
- **The cap is enforced by `consume`, in the same transaction, under the same row lock.** A
  cap enforced anywhere else is a cap a double-click defeats — the argument in
  `credits.py` applies unchanged.
- **Speech is in the arithmetic above and it must stay there.** A drill's speech is one bank
  prompt (shared, cached after the first candidate) plus one generated cross-question. If a
  future drill format makes more of its audio unique, the 94 moves and the ceiling has to
  move with it. `/admin/revenue` now reports `costs.tts_usd`, so this is checkable rather
  than assumed.

**The Pass is worse for us than pay-per-item at every volume below 10 drills/month** (₹199
against 10 × ₹19 = ₹190 of list-price purchases they would otherwise have to make). It is
better for us above that only if those purchases would actually have happened — which is the
entire empirical question and is what §6 measures.

---

## 5. Where the numbers come from

Two sources, and the difference between them is load-bearing.

**The ledger (`credit_events`, `ai_usage`, `tts_usage`) is complete.** Every purchase, every
consumption, every rupee and every dollar of cost is in it for every account, with no
sampling and no consent gate. **Anything that can be answered from the ledger must be
answered from the ledger.**

**Product analytics (PostHog) is consent-gated and therefore a biased sample.** Only accounts
that ticked the optional analytics box at signup, or turned it on in Settings, appear at all
— see `frontend/src/lib/analytics/`. It can answer funnel questions the ledger cannot see
(signup → first resume upload, interview started but never completed), and its rates are
**not** population rates.

So each threshold below names its source, and the two are never mixed inside one figure. A
threshold that needs analytics also names a minimum consent coverage, because a rate computed
on 8% of accounts is a rate about those 8%.

Events available (all from `frontend/src/lib/analytics/events.ts`): `signup`,
`resume_uploaded{is_first}`, `interview_started{is_first}`, `interview_completed{is_first}`,
`purchase{item_id, feature, quantity, price_paise, is_repeat}`.

---

## 6. Go/no-go thresholds

**Measurement window: 60 consecutive days, ending no earlier than 14 days after a placement
season.** A window inside a season measures the spike; a window entirely outside it measures
the trough. Both would be answering a different question.

**All five must hold. Any one failing is a no-go.** They are ordered so the cheapest to check
is first — if G0 fails, stop.

### G0 — Enough data for any of this to mean anything
> **≥ 300 distinct accounts with at least one `kind='purchase'` row in the window.**
> Source: ledger.

Below 300, every rate below has a confidence interval wide enough to contain both the go and
the no-go answer. This is not a business threshold; it is the point at which the others stop
being noise.

### G1 — People buy more than once
> **≥ 35% of purchasing accounts make a second purchase within the window.**
> Source: ledger (`purchase{is_repeat}` in analytics is the cross-check, not the figure).

**The single most important number here.** A subscription is a discount for repeat buyers and
a barrier for everybody else. Below 35% it is a price cut for a minority and a new decision
for the majority — which is precisely the trade the pivot away from subscriptions rejected,
and re-making it on worse evidence would be indefensible.

### G2 — Practice is a habit, not an event
> **Among accounts with ≥ 2 purchases, median communication drills consumed per 30 days ≥ 4,
> and p90 ≤ 60.**
> Source: ledger (`kind='consume'`, `feature='communication'`).

Two bounds, and both are required:

- **The floor (median ≥ 4)** is what makes ₹199 a sane offer to the person buying it. At 4
  drills a month they spend ₹76 today; a Pass is only attractive if their intended volume is
  higher than their actual purchases, which is the behaviour the Pass exists to unlock. Below
  4 there is no habit for a monthly price to attach to.
- **The ceiling (p90 ≤ 60)** is what makes it survivable. 60 is the fair-use cap from §4; if
  the ninetieth percentile is already at it, the cap becomes the product and the complaint
  is guaranteed.

### G3 — There is recurring behaviour at all
> **≥ 25% of accounts that complete a first interview start a second within 30 days.**
> Source: ledger for the interview counts; analytics
> (`interview_completed{is_first:true}` → `interview_started{is_first:false}`) for the timing
> cross-check, **requiring analytics consent coverage ≥ 30% of active accounts** for that
> cross-check to be quoted at all.

This is the seasonality test, and it is the one most likely to fail. `plans.py`'s objection is
that usage is a three-week burst inside a placement season and nothing either side of it. If
that is true, this number is low and a monthly price is wrong however it is packaged. Below
25%, stop — and record that the pivot was correct.

### G4 — The Pass would not lose money on the people most likely to buy it
> **p95 monthly cost-to-serve of communication drills, among accounts with ≥ 2 purchases,
> < ₹80 (≈ $0.94) — that is, under 40% of the Pass price.**
> Source: ledger — `ai_usage` and `tts_usage` joined per user, the same join
> `/admin/revenue` now performs.

The headline arithmetic in §4 uses an average. A subscription is bought disproportionately by
the heaviest users, so the average is the wrong statistic — p95 is the one a flat price has to
survive, the same reasoning `/ai-usage` gives for reporting p95 cost per user. 40% leaves room
for the gateway fee, refunds, hosting, and the practice given away to accounts that never buy.

**This threshold moves if the vendor changes.** At ElevenLabs Creator rates the same drill
costs **$0.0530** rather than $0.0245 — its speech alone goes from $0.0045 to $0.0330 — which
takes break-even from 94 drills to 43 and puts it inside plausible heavy use. Recompute from
`scripts/item_margin.py` before quoting either number.

---

## 7. If it is a go: what shipping actually means

Not a plan — a scope check, so nobody estimates this as "add an item to `plans.py`".

1. `PRACTICE_PASS_ENABLED`, defaulting false, and the item behind it.
2. Period arithmetic in `consume`: is a Pass active, and is this drill inside the fair-use
   ceiling — both inside the existing transaction and the existing row lock.
3. The `paid_with: "bundle"` third branch, and the paired grant/consume write from §3.2.
4. The four downstream corrections in §3.3, each with a test.
5. Paywall and pricing-page copy that makes the split obvious. "Unlimited practice" next to
   "₹49 per interview" is a sentence people misread in the expensive direction, and a refund
   request that begins "I thought interviews were included" is the failure this feature is
   most likely to produce.
6. Renewal, cancellation, and what happens to an in-flight drill when a Pass lapses.
7. A pentest suite at the standard of `test_pentest_referrals.py`: the attack is a Pass that
   is expired, cancelled, or refunded still serving drills, and a fair-use ceiling that a
   concurrent double-click walks past.

Item 6 alone is most of the machinery the pivot deleted. That is the honest cost, and it is
why §6 is written as a gate rather than as a checklist.

---

## 8. Review

Re-check §6 when either becomes true:

- 300 purchasing accounts exist in a 60-day window for the first time (G0 becomes checkable);
- the vendor, the drill format, or the per-item prices change, since §4 and G4 are computed
  from them.

Until then this note is a record of a decision **not** taken, and the reasoning is the point
of it.
