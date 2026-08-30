# Data protection compliance — where Hotseat actually stands

An audit of the codebase against India's **Digital Personal Data Protection Act, 2023** and the
regimes that sit alongside it. Written from what the code does, not from what a policy says,
because there is no policy.

**This is not legal advice.** It is an engineer's reading of the statute against the
implementation. Several gaps below are fixed by writing a document and appointing a person, not
by writing code — those are flagged as such, and a lawyer should confirm the interpretation
before you rely on any of it.

- Audited at commit `c4ebe95`
- Related: [[KNOWN-GOOD]] · [[index]] · [[DEPLOY]]

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
undergraduates in India are 17. The code collects **no date of birth and has no age gate**, so
it cannot tell.

Two §9 prohibitions bite directly:

- **No behavioural monitoring of children.** The product measures speech pace, filler words,
  pauses, eye contact and presence.
- **No targeted advertising directed at children.** The dashboard now carries rotating
  promotional cards selected from what the user has and has not bought — which is targeted
  advertising by any ordinary reading.

Neither is a problem for adults. Both are prohibited for under-18s, and right now the product
has no way to know which it is talking to.

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

DPDP §16 permits transfer except to countries the Central Government restricts, and that list
has not been notified. **The exposure is that the list, when it appears, may include China** —
and the resume of every Indian candidate has already been sent there. That is a business
decision rather than a bug, but it should be a decision somebody makes on purpose.

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
6. **Decide the children question.** Either collect date of birth and gate under-18s out of the
   behavioural metrics and the promotional cards, or state that the service is 18+ and enforce
   it at signup. Doing neither is the current position and is the riskiest one.
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
