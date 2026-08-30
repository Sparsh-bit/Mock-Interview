# Data residency and CERT-In — what is actually true

A verification, not a plan. The question asked was: **where do the database, Redis and any
payment-adjacent data physically sit, and does that satisfy RBI's localisation expectation
and CERT-In's current directions?**

- Checked on **2026-08-31**, against the repository at the tip of `ops/observability-and-compliance`
- Related: [[COMPLIANCE]] · [[SECURITY-REVIEW]] · [[DEPLOY]] · [[RAILWAY]] · [[index]]

> **This is an engineer's reading, not legal advice.** Two of the four conclusions below turn
> on a definition a lawyer should confirm, and both are marked.

---

## The one-line answer

**The hosting region could not be determined from this repository, and every piece of
documented intent points outside India.**

| Regime | Explicit call |
|---|---|
| **CERT-In — 180-day logs within Indian jurisdiction** | 🔴 **NON-COMPLIANT** |
| **CERT-In — 6-hour incident reporting** | 🔴 **NON-COMPLIANT** |
| **CERT-In — registered point of contact** | 🔴 **NON-COMPLIANT** |
| **RBI payment-system data localisation** | 🟢 **COMPLIANT by delegation** — the duty binds Razorpay, not a merchant. One caveat needs a lawyer, below |
| **DPDP §16 cross-border transfer** | 🟢 **COMPLIANT today** — no restricted-country list is notified. Exposed, with a 13 May 2027 deadline |

The two CERT-In log/reporting items are unmet **regardless of which region the answer turns
out to be**, because one is about where logs live *and how long*, and the other is about
having a process at all.

The first two are the ones to act on. They are unmet regardless of which region the answer
turns out to be, because one is about *where logs live* and the other is about *having a
process at all*.

---

## 1. Where is it actually hosted?

**Not determined.** Stated plainly because the honest answer to a verification question is
sometimes "I could not verify it", and a guess here would be worse than the gap.

| Component | What the repository says | Confidence |
|---|---|---|
| **Backend (API)** | `render.yaml` declares `region: singapore` | **Low — the file marks itself unconfirmed** |
| **Postgres + Storage (Supabase)** | Nothing. The project URL lives in `.env`, which is git-ignored | **None** |
| **Redis** | Nothing. `REDIS_URL` lives in `.env` | **None** |
| **Frontend** | Cloudflare Pages | Global anycast — no single region, and it holds no data |
| **Payments** | Razorpay | India (the company is RBI-authorised and India-based) |

### How this was checked, and what did *not* work

`render.yaml` carries an unusually candid header: it says `region` and `plan` are "the
documented intent and **NOT confirmed fact**", because at the time it was written there was
no live service to reconcile against. That is still true — nothing responds today.

**I tried to establish the region from DNS and it does not work.** `interviewos-api.onrender.com`
resolves through `gcp-us-west1-1.origin.onrender.com`, which reads like Oregon and would
contradict the declared Singapore. **It is not evidence.** A control against a service name
that certainly does not exist —
`definitely-not-a-real-service-xyz42.onrender.com` — resolves to the *same* edge, as does an
unrelated live Render service. The `*.onrender.com` wildcard points at Render's routing
layer, not at where a service runs. Recorded here because the wrong conclusion was one
command away and somebody will try the same thing again.

**`.env` was not readable in this environment**, which is correct — it holds live
credentials — so the Supabase and Redis regions genuinely cannot be established from here.

### A migration is in flight, which matters

[[RAILWAY]] documents moving the backend from Render to Railway, and says: *"Pick the region
closest to Supabase and Redis. Render was Singapore."* So the intent is unchanged and remains
**outside India**. Whoever completes that migration is choosing the region that decides most
of this note, and should decide it deliberately rather than by picking the default.

### What was changed so this stops being unanswerable

`DATA_REGION` is now a setting. Unset, `/privacy` tells the candidate in as many words that
the region has not been confirmed. Set, it names the region, using the same
derived-from-configuration mechanism `services/legal/disclosure.py` already uses for AI
processors — because a notice naming the wrong country is worse than no notice.

**Set it to whatever the Supabase dashboard says, and update the table above.** That is a
five-minute task for somebody with the dashboard open, and it closes most of this note.

---

## 2. CERT-In — the directions actually in force

**Source:** CERT-In Directions under §70B(6) of the IT Act 2000, No. 20(3)/2022-CERT-In,
dated **28 April 2022** — <https://www.cert-in.org.in>. Checked 2026-08-31: **still in
force, unamended in substance.**

| Requirement | Direction | Status here |
|---|---|---|
| **Report cyber incidents within 6 hours** of noticing, or of being made aware | Direction (ii) | ❌ **Not met** |
| **Enable logs of all ICT systems and maintain them for 180 days *within the Indian jurisdiction*** | Direction (iv) | ❌ **Not met** |
| Synchronise system clocks to NPL/NIC NTP | Direction (i) | ⚠️ Not verifiable from the repository — a host setting |
| Registered point of contact with CERT-In | Direction (iii) | ❌ Not met, and not visible in the repository |

Non-compliance is punishable under **§70B(7)** — up to one year's imprisonment and/or a
fine. A proposed amendment raising that fine substantially had **not taken effect as of
early 2026**; treat the exposure as real either way, because the criminal limb is already
there.

### The 6-hour clock — why "not met" and not "partly"

There is **no runbook, no template and no registered contact**. The detection half exists and
is good: `audit_logs` carries actor, IP and user agent, tripwires exist, Sentry is wired with
scrubbing. But detection is not reporting, and the clock in the direction starts **when you
become aware** — not when forensics finish, not when a lawyer has been consulted. A team
discovering a breach at 2am with no template and no contact will not make six hours.

This is cheap to fix and is not code: one page, one mailbox, one contact registered.

### The 180-day log clock — two separate failures, and only one is about location

1. **Location.** Logs go wherever the platform puts them. [[OBSERVABILITY]] records that the
   durable path is the host's native log drain, so the logs are in the host's region — which
   is undetermined above and documented as Singapore. The direction says *within the Indian
   jurisdiction*. On the documented intent, **not met**.

2. **Retention, which is unmet regardless of region.** `services/legal/retention.py` defines
   `SECURITY_LOG_RETENTION_DAYS = 180` and `FINANCIAL_RETENTION_YEARS = 8`, and **nothing
   runs on either clock.** There is no scheduled job. The constants describe an intention,
   the privacy disclosure promises that intention, and the code only enforces the
   *de-identification* half of it. This is [[SECURITY-REVIEW]] SR-2026Q3-05.

   Worth being precise about the direction of the failure: for CERT-In the risk is logs
   being kept **too briefly**, not too long. A host's default drain retention is typically
   days to weeks, well short of 180 — so the likely real position is that the logs a
   regulator would ask for **no longer exist**, which is a worse answer than having them in
   the wrong country.

---

## 3. RBI payment-data localisation

**Source:** *Storage of Payment System Data*, RBI/2017-18/153 DPSS.CO.OD No.2785/06.08.005/2017-18,
**6 April 2018**, with the FAQ clarifications of June 2019 — <https://www.rbi.org.in>. Checked
2026-08-31: still the operative requirement. Reserve Bank has additionally required
half-yearly CEO/MD-signed compliance certification since 1 April 2021.

**The obligation binds *Payment System Operators and Providers authorised by RBI* under the
Payment and Settlement Systems Act 2007. Hotseat is a merchant, not a PSO.** Razorpay is the
authorised payment aggregator and carries the localisation duty, including the rule that data
processed abroad must be brought back to India within 24 hours and deleted overseas.

**Verdict: very likely not Hotseat's obligation — ✅ by delegation, with one caveat.**

Supporting facts, checked in the code rather than assumed:

- **No card data ever reaches this system.** Razorpay's hosted checkout means PAN, CVV and
  expiry never touch the backend. [[COMPLIANCE]] already records PCI-DSS as out of scope by
  design, and the same architecture is what keeps the RBI question narrow.
- **What *is* stored** in Supabase: `credit_events.payment_ref` (a Razorpay payment id),
  `user_plans.autopay_token` and `autopay_customer_id` (Razorpay token references), amounts,
  and timestamps. These are **references and tokens, not payment credentials** — a token
  reference is precisely the artefact RBI's tokenisation framework exists so merchants may
  hold *instead of* card data.

> ⚠️ **The caveat is a lawyer's question, not an engineer's.** The 2018 circular's wording
> covers "end-to-end transaction details" and "information collected / carried / processed as
> part of the message or payment instruction". A strict reading could argue that a
> merchant-side ledger of payment ids and amounts, stored outside India, is caught. The
> mainstream reading is that the circular binds PSOs and Razorpay discharges it. **Do not
> treat the ✅ above as settled without confirming that reading.** If it is caught, the fix is
> the same one CERT-In already wants: move the database to an Indian region.

---

## 3a. RBI e-mandate and AFA — the autopay path, traced

**Source:** RBI, *Digital Payments — E-Mandate Framework, 2026*,
**RBI/CO.DPSS.POLC.No.S56/02.14.003/2026-27, dated 21 April 2026** — <https://www.rbi.org.in>.
Checked 2026-08-31. It **consolidates and replaces eight earlier circulars** on recurring
digital transactions, so any note citing the 2019/2021 e-mandate circulars is now out of date.

### Which model is in use

**Razorpay's own recurring rails — the saved-token / subsequent-payment API. Not the
Subscriptions API, and not a custom token vault.**

The proof is one call, in `services/billing/autopay.py`:

```
POST https://api.razorpay.com/v1/payments/create/recurring
  { "amount", "currency", "customer_id", "token", "recurring": "1", "description", "notes" }
```

That is Razorpay's *Create Subsequent Payment* endpoint. `POST /v1/subscriptions` and
`plan_id` appear nowhere — this product removed subscriptions on purpose. `autopay_token` is
an opaque Razorpay reference and **no card data reaches this system at any point**, which a
test asserts across the whole billing layer.

**So AFA is not ours to perform.** Under the 2026 framework AFA is mandatory *at e-mandate
registration*, for every channel and every amount, and registration happens inside Razorpay's
authorisation transaction. Two further obligations also sit elsewhere: the **24-hour
pre-debit notification is the issuer's**, and **acquirers must ensure their merchants
comply** — so the compliance chain runs through Razorpay, which is the correct place for it
given they hold the licence.

Amounts are comfortably inside the exemption: the dearest pack is **₹199** against a
**₹15,000** ceiling for subsequent transactions without AFA. Pinned by a test, because a
price change is the one thing that could quietly alter the regulatory shape of the feature.

### The finding that changes the answer

**The mandate registration flow does not exist.** `autopay_token` and `autopay_customer_id`
are read in three places and **written in none** — verified by parsing every module with
`ast`, not by grep. Nothing creates a Razorpay customer, nothing runs an authorisation
transaction, and no webhook captures a `token_id`. There is also **no frontend for autopay
anywhere**.

The consequence: `is_eligible()` returns *"no saved mandate"* for every account that will
ever exist, and `charge_saved_token` is unreachable. A second defect confirms it has never
run — Razorpay lists `order_id`, `email` and `contact` among the mandatory parameters for
that endpoint and the call sends none of them, so it would be rejected with a 400 even if a
token appeared.

### The call

> 🟢 **COMPLIANT TODAY — because no money can move.** Auto top-up cannot charge anybody: no
> mandate can be registered, no token exists, and no user interface reaches it.
>
> 🟠 **NEEDS WORK BEFORE IT IS EVER ENABLED**, and the missing piece is exactly the piece
> where AFA lives. The correct implementation is Razorpay's authorisation transaction —
> create a customer, run an authorisation payment through Razorpay's own sheet where the
> issuer performs AFA, and capture `token_id` from the resulting webhook.
>
> **The dangerous way to "finish" this** is to populate `autopay_token` from anywhere else —
> a value copied from the dashboard, a token reused from a one-off payment. That yields a
> working charge that skipped AFA entirely. `tests/test_autopay_mandate_compliance.py` fails
> if any code path gains a write to that column, with a message saying why.

Not a lawyer's question, this one: it is a factual statement about which API is called and
what the code does and does not do. What *would* need confirming is whether the Razorpay
merchant account is onboarded for recurring payments at all — an acquirer-side setting this
repository cannot see, and one the 2026 framework makes the acquirer responsible for.

---

## 4. DPDP cross-border — the position has changed since [[COMPLIANCE]] was written

**Source:** Digital Personal Data Protection Act 2023 §16; **Digital Personal Data Protection
Rules 2025**, notified **November 2025** — <https://www.meity.gov.in>. Checked 2026-08-31.

[[COMPLIANCE]] says "DPDP's rules were still being finalised at the time of writing". **They
are now notified**, and three things follow:

- **Compliance deadline: 13 May 2027.** An 18-month runway from notification. That is the
  date the rest of [[COMPLIANCE]]'s blocker list is working towards.
- **Cross-border stays a negative list.** Transfers are permitted except to countries the
  Central Government notifies as restricted — the opposite of the EU's adequacy model.
- **No restricted-country list has been notified** as of mid-2026.

So sending resumes to ZhipuAI in China is **currently lawful under §16**, and
[[COMPLIANCE]]'s framing of the exposure remains exactly right: the risk is that the list,
when it appears, includes China — by which time every Indian candidate's resume has already
been sent there. That is a business decision somebody should make on purpose, and it now has
a deadline attached to it.

---

## What to do, shortest first

1. **Read the Supabase dashboard and set `DATA_REGION`.** Five minutes, and it turns most of
   §1 from unknown into known.
2. **Register a CERT-In point of contact and write the breach runbook** with the 6-hour clock
   in it. One page, one mailbox. The detection half already exists.
3. **Decide the region deliberately during the Railway migration**, since it is being chosen
   anyway. An Indian region resolves CERT-In §2 *and* the RBI caveat in §3 at once.
4. **Ship a log drain into Indian-region storage with 180-day retention**, or accept
   non-compliance in writing. Note that today's likely position is that the logs are gone
   long before 180 days, which is the worse failure.
5. **Implement the retention clocks** (SR-2026Q3-05). Needs the policy settled first.
6. **Take the §16 decision on ZhipuAI** against the 13 May 2027 date.

## Honest limits

- Read from the repository at one commit, with `.env` unreadable by design. It cannot see
  dashboards, contracts or DPAs.
- "Reasonable" and "payment system data" are legal standards. Items marked ⚠️ turn on a
  reading a lawyer should give.
- Regulatory text moves. Everything above is dated and sourced so the next reader re-checks
  the direction rather than trusting this summary of it — including this one.
