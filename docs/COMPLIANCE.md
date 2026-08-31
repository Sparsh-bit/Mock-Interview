# Data protection compliance — where InterviewOS actually stands

An audit of the codebase against India's **Digital Personal Data Protection Act, 2023** and the
regimes that sit alongside it. Written from what the code does, not from what a policy says,
because there is no policy.

**This is not legal advice.** It is an engineer's reading of the statute against the
implementation. Several gaps below are fixed by writing a document and appointing a person, not
by writing code — those are flagged as such, and a lawyer should confirm the interpretation
before you rely on any of it.

- Audited at commit `c4ebe95`
- **Partly remediated since.** See [[#What has since been built]] at the bottom — the
  mechanisms for notice, consent, age, export, erasure and retention now exist in code. The
  table below is kept as the original audit; the status column is annotated where it has
  moved.
- Related: [[KNOWN-GOOD]] · [[index]] · [[DEPLOY]] · [[ERROR-TRACKING]]

---

## The one-line answer

**No. The security is strong; the data-protection compliance is largely absent.**

Those are different things and the difference matters. Nothing here is leaking — two rounds of
penetration testing found one real flaw and it is fixed. What is missing is the *lawful basis*
for holding the data at all: there is no privacy notice, no consent, no way for a person to
get their data out or have it deleted, and no named human to complain to. Under DPDP those are
not nice-to-haves; §5 and §6 make notice-and-consent the precondition for processing.

---

## What personal data this product actually holds

Worth stating plainly, because the obligations scale with it.

| Data | Where | Sensitivity |
|---|---|---|
| Email, name | `users`, `profiles` | Identifiers |
| Bio, LinkedIn, GitHub, avatar URL | `profiles` | Voluntary, unvalidated |
| **Resume file + extracted text** | `resume_files` + Supabase Storage | **High** — education, employers, sometimes phone and address |
| **Interview answers** | `answers` | **High** — the candidate's own words while being assessed |
| **Voice transcripts** | `voice_transcripts` | **High** — speech converted to text, kept with confidence and duration |
| Scores, reports, readiness level | `reports`, `scores`, `rating_events` | **High** — an assessment of a person's employability |
| Delivery metrics (fillers, pauses, pace) | session metadata | Behavioural |
| Payments, offers redeemed | `credit_events`, `offer_redemptions` | Financial |
| **IP address, user agent** | `audit_logs` | Identifiers |

That set — an assessment of someone's professional competence, plus their resume, plus their
recorded speech — is materially more sensitive than a typical SaaS account.

---

## DPDP Act 2023 — obligation by obligation

| § | Obligation | Status | What is missing |
|---|---|---|---|
| 5 | **Notice** before processing, itemised, plain language | ❌ **Absent** | No privacy notice anywhere in the product. Not a page, not a modal, not a line at signup |
| 6 | **Consent** — free, specific, informed, unambiguous, by clear affirmative action | ❌ **Absent** | Nothing is recorded. No consent artefact exists to produce if asked |
| 6(4)–(6) | **Withdrawal** as easy as giving | ❌ **Absent** | No mechanism |
| 6(3) | Notice available in English + 8th Schedule languages | ❌ **Absent** | Follows from having no notice |
| 4, 6(1) | **Purpose limitation** | ⚠️ **Partial** | Data *is* used only for interview prep, but the purpose is never stated to the person, so there is nothing to be limited *to* |
| 8(3) | **Accuracy** — correction possible | ✅ **Met** | Profile is editable |
| 8(5) | **Reasonable security safeguards** | ✅ **Strong** | See [the security list](#security-controls-actually-implemented) |
| 8(6) | **Breach notification** to the Board and to each affected person | ❌ **Absent** | No process, no template, no contact route. CERT-In wants 6 hours (below) |
| 8(7) | **Erase when the purpose is served** or consent withdrawn | ❌ **Absent** | Nothing is ever deleted. No retention period is defined anywhere in the codebase |
| 8(9) | Publish contact of the **Data Protection Officer / person answering questions** | ❌ **Absent** | No such contact exists |
| 8(10) | **Grievance redressal** mechanism | ❌ **Absent** | No route, no address, no SLA |
| 9 | **Children** — verifiable parental consent; **no tracking, no behavioural monitoring, no targeted advertising** | 🔴 **High risk** | See below |
| 10 | Significant Data Fiduciary duties (DPO in India, audit, DPIA) | ⏳ **N/A yet** | Triggered by notification on volume/sensitivity. Plan for it |
| 11 | **Right to access** — a summary of data held and who it was shared with | ❌ **Absent** | No export. A user cannot see what is held |
| 12 | **Right to correction and erasure** | ⚠️ **Partial** | Correction yes. Erasure exists **only as an admin action** — a person cannot delete their own account |
| 14 | **Right to nominate** | ❌ **Absent** | No nominee field |
| 16 | **Cross-border transfer** | 🔴 **Flag** | See below |

### §9 — children, and why it is the sharpest risk here

This product is aimed at **campus placement preparation**. A meaningful share of first-year
undergraduates in India are 17. The code collects no date of birth, but there **is** an age
gate: `age_18_plus` is a required, non-defaulting field on `POST /legal/consent/signup`
(`api/v1/legal.py`), shown as an unticked "I am 18 or older" box on the registration screen
and recorded in the consent ledger like any other answer. It cannot be changed afterwards —
`update_consent` refuses that purpose outright and points at account deletion, because
flipping the flag later would leave every measurement already taken.

Two §9 prohibitions bite directly:

- **No behavioural monitoring of children.** The product measures speech pace, filler words,
  pauses, eye contact and presence.
- **No targeted advertising directed at children.** The dashboard now carries rotating
  promotional cards selected from what the user has and has not bought — which is targeted
  advertising by any ordinary reading.

Neither is a problem for adults. Both are prohibited for under-18s.

**What the gate does and does not settle.** It is a self-declaration, so it discharges §9 only
to the extent self-declaration is accepted — which is the open question below and a lawyer's
call, not an engineering one. What it does settle is that the product no longer has *no way to
know*: there is a recorded, timestamped answer against a notice version for every account, and
a refusal is refused at signup rather than recorded and ignored.

### §16 — cross-border transfer

Personal data leaves India in the ordinary course of a request:

| Destination | What is sent | Where |
|---|---|---|
| **ZhipuAI / GLM** (`open.bigmodel.cn`) | Candidate name, **full resume text**, interview answers | **China** |
| Anthropic | Same | US |
| NVIDIA NIM (`integrate.api.nvidia.com`) | Same | US |
| ElevenLabs | Text to be spoken | US |
| Judge0 (`ce.judge0.com`) | Candidate's submitted code | US/EU |
| Supabase | Everything — it is the database and file store | Region-dependent |
| Razorpay | Payment details | India ✅ |

DPDP §16 permits transfer except to countries the Central Government restricts. **That list
still has not been notified** — but the deadline is no longer open-ended, and this note used
to leave it vague.

The Digital Personal Data Protection Rules, 2025 were notified on **13 November 2025**. Rule
15, which operationalises §16, is in the tranche that comes into force **eighteen months
later — 13 May 2027**. Two earlier dates matter on the way there:

| Date | What starts |
|---|---|
| 13 November 2025 | Rules notified. The Data Protection Board is operational |
| 13 November 2026 | Penalties, and Consent Manager registration |
| **13 May 2027** | **Rule 15 and the rest of the substantive obligations** |

So the position is: transfers to China are lawful today and remain lawful unless and until a
restricted-country notification says otherwise, with 13 May 2027 as the date by which the
framework is fully in force. **The exposure is that the list, when it appears, may include
China** — and the resume of every Indian candidate has already been sent there. Nothing about
that is retroactively fixable, which is why it is a decision to make on purpose rather than a
deadline to wait out.

---

## The other regimes that apply today

**DPDP is not yet fully in force.** Its rules were still being finalised at the time of writing,
so the older regime continues to apply and is the one you would actually be judged against
right now.

| Regime | Applies because | Status |
|---|---|---|
| **IT Act 2000 §43A + SPDI Rules 2011** | You handle "sensitive personal data" of Indian users | ❌ **Rule 4 requires a published privacy policy.** There is none. Rule 5 requires consent for collection. Rule 8 requires "reasonable security practices" — arguably met via ISO-equivalent controls |
| **CERT-In Directions, April 2022** | Any body corporate operating in India | ⚠️ **Two hard requirements unmet:** cyber incidents reportable within **6 hours**, and **logs retained 180 days within India**. Logs currently live wherever Render puts them |
| **GDPR** | Only if you knowingly offer to EU users | ⏳ Not applicable today. If it becomes so: lawful basis, DPIA, EU representative, 72-hour breach notice |
| **PCI-DSS** | Card data | ✅ **Out of scope by design.** Razorpay's hosted checkout means no card data ever touches this system |
| **RBI data localisation** | Payment data must be stored in India | ✅ Razorpay handles it |

---

## Security controls actually implemented

The half that *is* in good shape, and the evidence for each. This is what §8(5) and SPDI Rule 8
are asking about.

### Authentication and session

- **Supabase-issued JWTs, verified locally** — no network round trip per request
- **Algorithm allowlist** — `alg: none` and algorithm-confusion attacks refused; tested
- **Audience verified**; expired and unsigned tokens refused; malformed headers 401 rather than 500
- **`is_admin` read from the database, never from the token** — a forged claim grants nothing
- **No cookie authentication anywhere**, so there is no ambient credential and CSRF has no vector. The *absence* is pinned by a test
- **Single-device login** (migration 020)

### Authorization

- **Row Level Security on every public table**, pinned by `test_rls_coverage.py` — this is the real access control, not the API layer
- **Every route requires auth unless explicitly allowlisted**, pinned by `test_auth_coverage.py`
- **All 18 admin routes refuse non-admins**, discovered dynamically so new routes are covered automatically
- **Session-scoped questions are owner-only**; the answer key is withheld until that user has answered that question
- **Cross-user IDOR tested with real ids** across reports, sessions, transcripts and both write paths

### Input handling

- **Pydantic schemas on every request**; extra fields dropped, not assigned — mass assignment closed
- **Request models cannot name a price** — the server prices everything
- **Uploads**: MIME allowlist, size cap, extraction must succeed on the *bytes*, zip-bomb tolerant
- **Filename sanitised by positive allowlist** before it reaches a storage path — closed a real traversal into other users' folders
- **Open redirect closed** on the login flow
- **No raw SQL anywhere** — SQLAlchemy expression language throughout, enforced by a grep test
- **No `dangerouslySetInnerHTML`**; React escaping intact

### Payments

- **Razorpay signature verification** as a pure, fully tested function
- **One redemption per account enforced by a unique index**, not a read-then-write check
- **Coupon scope per item**, so a flat-price code cannot silently price a bundle at single-item money
- **`SELECT ... FOR UPDATE`** on the plan row serialises concurrent starts

### Operational

- **Rate limits keyed on the authenticated user**, never an IP — a forwarded-for header buys nothing
- **Daily AI spend circuit breaker**, global and per user
- **Cloudflare Turnstile** on high-value coupon paths
- **Audit log** with actor, IP and user agent
- **Secrets never in the bundle** — verified; the only public value is the Turnstile site key
- **Prompts, scoring and billing logic stay server-side**

---

## What to do, in order

The gaps are mostly cheap. The first four are the ones that turn "unlawful" into "lawful".

1. **Publish a privacy notice** and link it from signup, footer and the interview start.
   Itemise: what is collected, why, who it is shared with (name the AI providers and that
   processing occurs outside India), how long it is kept, and the rights available.
   *Required by DPDP §5 and, today, by SPDI Rule 4.*
2. **Capture consent at signup** — an unticked box with a link to the notice, and store
   *what* was consented to, *when*, and *which version* of the notice. Consent you cannot
   evidence is consent you do not have.
3. **Name a grievance officer** and publish the contact. *DPDP §8(9)–(10).* One page and one
   mailbox.
4. **Let a user delete their own account.** The deletion logic already exists and is tested —
   it is currently reachable only by an admin. Exposing it is a small piece of work.
5. **Add "download my data."** One endpoint assembling profile, sessions, answers, reports and
   payments as JSON. *DPDP §11.*
6. **Decide the children question.** ~~Doing neither is the current position.~~ The second
   option was taken: the service states it is 18+ and enforces it at signup (see §9 above).
   What remains is not engineering — whether self-declaration discharges §9 for this audience
   is the lawyer's call listed at the end of this document.
7. **Define retention** and implement it — the first thing here that is real engineering.
   Something like: resumes and transcripts deleted N months after the last session; audit logs
   180 days (CERT-In); financial records 8 years (Companies Act).
8. **Write a breach runbook** with the 6-hour CERT-In clock in it. The tripwires and audit log
   already give you the detection half.
9. **Confirm the cross-border position on ZhipuAI** deliberately, and put it in the notice
   either way.
10. **Add a nominee field.** *DPDP §14.* Small, and easy to forget entirely.

---

## Honest limits of this audit

- Read from the code at one commit. It cannot see policies, contracts or DPAs that exist
  outside the repository — if you already have a signed DPA with Supabase or Razorpay, that
  changes the picture for those processors and not for the others.
- DPDP's rules were still being finalised at the time of writing. Timelines and some
  definitions will move.
- "Reasonable security safeguards" is a legal standard, not a technical one. The controls
  listed above are strong, but whether they clear the bar is a lawyer's call, not mine.


---

## What has since been built

The audit above found the mechanisms absent. They now exist. This section records what the
code does, so the two halves of this note can be read against each other rather than
replacing one with the other.

### Migration 023 — `consent_and_retention`

Two changes that belong together.

**`consent_events`** is an append-only ledger, deliberately shaped like `credit_events`
rather than as booleans on `users`. Every row carries the purpose, whether it was granted,
the notice version it was answered against, where it was answered, and when. Withdrawal is a
**new row with `granted = false`**, never an update — the history is the evidence that the
processing which already happened was lawful at the time, and overwriting it destroys that.

It is a new TABLE and not columns on `users` for the deployment reason `models/user.py`
records: migrations here are applied by hand, so there is always a window where the code is
live and the schema is not, and a new column on `users` puts itself into every SELECT on the
table `get_current_user` reads on every request — which takes the whole application down for
the length of that window.

**Retention.** `credit_events`, `offer_redemptions` and `consent_events` moved from
`ON DELETE CASCADE` to `ON DELETE SET NULL` and gained a `retained_subject` column.

> **This fixed a real defect, not a theoretical one.** `POST /users/me/delete` cascaded the
> financial ledger away. Those are books of account — Companies Act §128(5) wants eight
> financial years, and DPDP §8(7) makes erasure yield to a retention obligation under another
> law — so a person exercising their erasure right destroyed records the business is required
> to hold, silently, on a path they trigger themselves. Cascading `offer_redemptions` was
> also a live abuse vector with nothing to do with law: that table's unique index is what
> stops a single-use code being redeemed twice, so deleting the row made delete-and-
> re-register a way to reuse any code.

Retaining a row that still names the person would be a rename of the problem, so
`services/legal/retention.py` replaces the identity with a **salted one-way digest** in the
same transaction as the delete. Amounts and dates remain; the person does not. The resume,
its extracted text, the stored file, every answer, transcript, score and report are **not**
retained — they are the sensitive data, nothing requires keeping them, and they cascade away
as before.

### What each audit finding now maps to

| § | Was | Now |
|---|---|---|
| 5 | No notice anywhere | `GET /api/v1/legal/disclosure` (public) and `/privacy`. **Derived from the running configuration**, not written out — see below |
| 6 | Nothing recorded | `consent_events`, three separate unticked boxes at signup, version-stamped |
| 6(4)–(6) | No withdrawal | `POST /api/v1/legal/consent` with `granted: false` — the same endpoint as giving it |
| 8(7) | Nothing ever deleted | Self-service deletion, with the retention carve-out above |
| 8(9)–(10) | No contact | `DPO_NAME` / `DPO_EMAIL` / `GRIEVANCE_RESPONSE_DAYS`, surfaced on `/privacy`. **Still unset** — see the blocker list |
| 9 | No age gate | Unticked "I am 18 or older" at signup, refused rather than recorded if false |
| 11 | No export | `GET /api/v1/users/me/export`, now including the consent history |
| 12 | Admin-only erasure | Self-service, and the admin path takes the same retention rule |
| 16 | No transfer disclosure | Country named per processor, shown before the first resume upload |

### The disclosure is derived, and that is the point

`services/legal/disclosure.py` builds the processor list from `AI_PROVIDER`,
`AI_FALLBACK_PROVIDER`, `TTS_PROVIDER` and `CODE_EXEC_PROVIDER` — the same settings the
request path reads.

This replaced a hardcoded list in the export endpoint that **had already drifted**: it
described ZhipuAI as the "standby" provider while `AI_PROVIDER` defaults to `glm`, which
makes ZhipuAI the *primary* recipient of every resume, in China. A notice naming the wrong
recipient is worse than no notice, because it is a statement the candidate relied on. A test
now fails if a provider the factory can build has no disclosure entry.

### Still needs a human — this is the blocker list

None of these can be closed from the repository, and the first two are the ones that keep
the position unlawful rather than merely imperfect.

1. **Appoint a grievance officer and set `DPO_NAME` / `DPO_EMAIL`.** Until then `/privacy`
   says, in as many words, that no officer has been appointed. That is deliberate — an
   obvious gap beats a plausible fabrication, because a made-up name looks like the
   obligation was discharged. *DPDP §8(9)–(10).*
2. **Have a lawyer review and adopt the notice wording.** Everything shipped is marked
   `draft: true` in the payload and rendered as a banner. It states facts an engineer
   verified from the code; it does not attempt the parts that are a legal judgment:
   - the **lawful basis** for each processing purpose;
   - the retention periods as a **commitment** rather than a description of current
     behaviour;
   - whether **self-declared 18+** discharges §9, or whether verifiable parental consent
     machinery is required for a product aimed at campus placement where a meaningful share
     of first-years are 17;
   - the **§16 position on ZhipuAI**. The restricted-country list is still not notified and
     may include China; Rule 15 comes into force 13 May 2027 (see §16 above). The code names
     the destination; whether to keep sending resumes there is a business decision somebody
     should make on purpose, and before that date rather than on it.
   - **§6(3)** — the notice in English plus the 8th Schedule languages. Only English exists.
3. **Decide and document the retention *policy*.** `FINANCIAL_RETENTION_YEARS = 8` and
   `SECURITY_LOG_RETENTION_DAYS = 180` are in `services/legal/retention.py` and are what the
   disclosure promises, but **nothing purges on those clocks yet** — there is no scheduled
   job. Today the constants describe an intention, and the code only enforces the
   *de-identification* half. A purge job is real engineering and needs the policy settled
   first.
4. **CERT-In log localisation.** 180 days of logs held *within India*. Logs currently live
   wherever Render puts them. This is a hosting decision.
5. **§14 nominee.** Still absent. Small, and easy to forget entirely.
6. **Breach runbook** with the 6-hour CERT-In clock. Detection exists; the process does not.
7. **DPAs with the processors.** Whether signed agreements exist with Supabase, Razorpay,
   Anthropic and ZhipuAI is not visible from the repository and changes the analysis for
   each of them.

### Known limits of what was built

Stated plainly, because a remediation note that only lists wins is the same failure mode as
the stale trial-allowance note in `CLAUDE.md`.

- **Consent is recorded after the Supabase account exists**, because a consent row needs a
  user to belong to. An account created and then abandoned before that call leaves an
  account with no consent record. The signup form surfaces the failure and asks the person to
  confirm in Settings; the gap is real and is why age is *also* enforced at the paths that do
  behavioural monitoring rather than only at signup.
- **Age is self-declared.** No document check, no parental-consent flow. Whether that is
  enough is item 2 above.
- **Nothing purges yet.** See item 3.
- **Accounts created before migration 023** have no consent rows at all. They are not
  retroactively blocked, because locking a paying customer out of a product they already
  bought is not a remedy — they read as "never asked", and the resume gate will ask them at
  their next upload.
