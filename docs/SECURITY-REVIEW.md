# Security review — the standing quarterly

A **recurring** review of this codebase against the three OWASP lists that apply to it. Not
an audit; audits are a thing you do once and then quote for two years. This is a clock.

- **Cadence:** quarterly, on the last working day of the quarter's final month
- **Next review due:** 2026-11-30
- **Enforced by:** `backend/tests/test_security_review_cadence.py` — the suite fails once the
  due date passes. See [[#Why a test and not a calendar invite]]
- Related: [[COMPLIANCE]] · [[KNOWN-GOOD]] · [[MISTAKES]] · [[index]]

> **This is an engineer's review, not a certification.** It reads the code against a public
> checklist. It cannot see the hosting configuration, the contracts, or anything outside the
> repository, and it is not a penetration test — `test_pentest_*.py` is the closest thing to
> that here and it covers what somebody already thought to attack.

---

## Why a test and not a calendar invite

`docs/MISTAKES.md` is largely one lesson written many ways: **a guard that cannot fail
reports success.** A review process that lives in a document is a guard that cannot fail. It
does not go red when it is skipped; it just quietly stops describing the codebase, and the
longer it goes unread the more authoritative it sounds — which is precisely the failure mode
of the trial-allowance note that `CLAUDE.md` now warns about at length.

So the schedule is a test. `test_security_review_cadence.py` parses the log below and fails
when the next review is overdue, when a review entry is missing a category, or when a
category the OWASP lists contain has no row. The failure message says what to do.

**It fails the whole suite, deliberately.** That is disruptive, and it is meant to be: the
alternative is a warning nobody sees. A fourteen-day grace period is built in so that a
review falling on a holiday does not break a deploy, and the due date is a plain string in
this file, so extending it is a one-line commit that shows up in review rather than a
setting somebody flips.

## How to run one

1. Re-read the three lists **from the source** rather than from this file. They change, and
   this file records what was current when it was written, not what is current now. The
   2025 web list, for one, renamed four categories and added two since 2021.
2. Work the categories in order. For each, write down the *evidence* — a file, a test, a
   command and its output — not a judgement. "Covered" with nothing next to it is the same
   as not having looked.
3. Anything that is not covered gets a row with an owner and a decision: fix, accept, or
   defer. **"Accept" is a real answer** and is better than a fix nobody will do; it just has
   to be written down with a reason and a trigger for revisiting.
4. Append a new dated section under [[#Review log]]. Never edit a previous one — the history
   is the point. If a past finding was wrong, add a correction to the current review saying
   so.
5. Move **Next review due** at the top.

## The lists this reviews against

| List | Edition reviewed against | Source |
|---|---|---|
| OWASP Top 10 (web) | **2025** | <https://owasp.org/Top10/2025/> |
| OWASP API Security Top 10 | **2023** (current edition) | <https://owasp.org/API-Security/editions/2023/en/0x11-t10/> |
| OWASP Top 10 for LLM Applications | **2025** | <https://genai.owasp.org/llm-top-10/> |

> **One thing to check next time.** `genai.owasp.org` publishes a resource page for an
> **LLM Top 10 for 2026**, described there as final and dated 2026-08-03, while the project's
> own `llm-top-10/` landing page still lists the 2025 entries. The 2025 entries are what this
> review used, because they are what the canonical list page serves. Confirm which is
> current before the next review and re-run the LLM section against it if it has moved.

---

## Review log

### 2026-08-31 — Q3 2026 (first review)

Reviewer: engineering. Commit: the tip of `ops/observability-and-compliance`.
Scope: `backend/app`, `frontend/src`, `.github/workflows`, `database/migrations`.

#### OWASP Top 10:2025 — web

| # | Category | Status | Evidence / finding |
|---|---|---|---|
| A01:2025 | Broken Access Control | ✅ covered | RLS on every public table, pinned by `test_rls_coverage.py`. Every route requires auth unless allowlisted (`test_auth_coverage.py`). All admin routes refuse non-admins, discovered dynamically so new ones are covered automatically (`test_pentest_authz.py`). Cross-user IDOR tested with real ids (`test_pentest_idor.py`). 303 security tests pass. |
| A02:2025 | Security Misconfiguration | ⚠️ **2 findings** | **SR-2026Q3-01** and **SR-2026Q3-02** below. A CSP exists and is genuinely restrictive; it just does not match what the app loads in two places. |
| A03:2025 | Software Supply Chain Failures | ✅ covered | Dependabot on npm, uv/pip and github-actions (`.github/dependabot.yml`); CodeQL weekly plus per-PR (`codeql.yml`); Trivy image scan that **gates** rather than reports, weekly plus per-PR (`image-scan.yml`). `test_security_workflows.py` fails if any of those is silently disarmed — which is the control that matters, since nothing else in the repo reads `.github/`. |
| A04:2025 | Cryptographic Failures | ✅ covered | Supabase JWTs verified locally with an algorithm allowlist; `alg: none` and confusion attacks refused, pinned by `test_glm_token_signing.py`. HSTS two years, preload-eligible. No secret in the client bundle except the anon key, which is public by design and gated by RLS (`security-headers.test.ts`). |
| A05:2025 | Injection | ✅ covered *(was a finding this quarter)* | No raw SQL anywhere — SQLAlchemy expression language, enforced by a grep test. No `dangerouslySetInnerHTML` (grep: zero hits). **Prompt injection was open and is now closed** — see LLM01. |
| A06:2025 | Insecure Design | ⚠️ **1 finding** | **SR-2026Q3-03**. Otherwise strong: the server prices everything and request models cannot name a price; entitlement is a ledger with `SELECT … FOR UPDATE`, never a stored counter. |
| A07:2025 | Authentication Failures | ⚠️ **1 finding** | **SR-2026Q3-04** — no auth-specific rate limiting. |
| A08:2025 | Software or Data Integrity Failures | ✅ covered | Razorpay signature verification is a pure, fully-tested function (`test_pentest_webhook.py`). Payment idempotency tested. Migration chain asserted linear and single-headed. |
| A09:2025 | Security Logging and Alerting Failures | ⚠️ **1 finding** | **SR-2026Q3-05**. `audit_logs` carries actor, IP and user agent; Sentry scrubbing and log redaction are both tested. The gap is retention and alerting, not capture. |
| A10:2025 | Mishandling of Exceptional Conditions | 🟡 accepted | The rate limiter **fails open** on a Redis error (`core/rate_limit.py`), deliberately, so a limiter outage cannot take down an interview. Recorded as accepted rather than covered. **Trigger to revisit:** the first time Redis is unavailable for more than a few minutes in production, or the first abuse incident that coincides with a Redis incident. Error responses are shaped and status codes tested (`test_error_status_codes.py`). |

#### OWASP API Security Top 10:2023

| # | Category | Status | Evidence / finding |
|---|---|---|---|
| API1:2023 | Broken Object Level Authorization | ✅ covered | `test_pentest_idor.py` across reports, sessions, transcripts and both write paths, with real ids rather than fabricated ones. RLS underneath as the real boundary. |
| API2:2023 | Broken Authentication | ⚠️ finding | Same as **SR-2026Q3-04**. `is_admin` is read from the database and never from the token, so a forged claim grants nothing. No cookie auth anywhere, so there is no ambient credential and CSRF has no vector — the *absence* is pinned by a test. |
| API3:2023 | Broken Object Property Level Authorization | ✅ covered | Pydantic on every request; extra fields dropped rather than assigned, so mass assignment is closed. Answer keys withheld until that user has answered that question. |
| API4:2023 | Unrestricted Resource Consumption | ✅ covered | Per-feature rate limits, upload size cap, a daily AI spend circuit breaker both global and per-user, and bounded `max_tokens`. See A10 for the fail-open caveat. |
| API5:2023 | Broken Function Level Authorization | ✅ covered | `test_pentest_authz.py` **discovers** admin routes by walking included routers rather than listing them, so a new admin route is covered the moment it is added. The `/admin/resumes/flagged` route added this quarter is asserted to fall inside that sweep. |
| API6:2023 | Unrestricted Access to Sensitive Business Flows | ⚠️ finding | Turnstile guards high-value coupon paths — per offer, not on every purchase, which is the right design. **But it is currently broken in production by SR-2026Q3-01**, so the control is not actually running. One redemption per account is enforced by a unique index rather than a read-then-write check. |
| API7:2023 | Server Side Request Forgery | ✅ covered | Checked directly: every outbound URL in `app/` is built from `settings`, never from request data. Judge0, Supabase admin, Razorpay, Turnstile, ElevenLabs and Fish are all configured hosts. No user-supplied URL is fetched anywhere. |
| API8:2023 | Security Misconfiguration | ✅ covered | `/api/docs`, `/api/redoc` and `/api/openapi.json` are all `None` in production. CORS is an explicit origin list, with the permissive localhost regex applied only when `settings.is_development`. |
| API9:2023 | Improper Inventory Management | ✅ covered | One versioned router (`/api/v1`), aggregated in a single `router.py`. No unversioned or legacy surface found. |
| API10:2023 | Unsafe Consumption of APIs | ✅ covered | AI responses are validated against Pydantic shapes and retried on malformed output (`json_validator.py`, `response_parser.py`) rather than trusted. Razorpay's webhook is signature-verified before it is read. |

#### OWASP Top 10 for LLM Applications 2025

| # | Category | Status | Evidence / finding |
|---|---|---|---|
| LLM01:2025 | Prompt Injection | ✅ **fixed this quarter** | Was wide open: 16 candidate-controlled variables were being substituted into **system** messages by `safe_substitute`. Now every one travels through `PromptBuilder.chat(untrusted=…)`, which nonce-fences it, and the system message carries a rule naming fenced blocks as data. Enforced across all call sites by an `ast` test against a declared taint registry (`test_prompt_injection.py`, 41 tests). |
| LLM02:2025 | Sensitive Information Disclosure | 🟡 partial | Resume text is registered as sensitive at the single point it comes into existence, so it can never reach the error tracker (`register_sensitive_text`); redaction and Sentry scrubbing are both tested. **The open item is not a bug but a decision:** resumes are sent to a model provider in China, disclosed in `/privacy` and flagged in [[COMPLIANCE]] §16. Owner: business. |
| LLM03:2025 | Supply Chain | ✅ covered | Same controls as A03. AI provider access is behind a factory with a declared interface, so a provider swap is a class rather than a scatter of call-site changes. |
| LLM04:2025 | Data and Model Poisoning | ⚠️ **1 finding** | **SR-2026Q3-06**. The vector cache has an explicit and well-documented scope model — anything derived from a candidate's own answers is per-user — but one global-scope entry is keyed on candidate-typed text. |
| LLM05:2025 | Improper Output Handling | ✅ covered | Model output is parsed into Pydantic schemas, never `eval`'d, never used to build SQL, and rendered through React's escaping with no `dangerouslySetInnerHTML` anywhere. No model output reaches a shell. |
| LLM06:2025 | Excessive Agency | ✅ N/A by design | The models here have no tools, no function calling and no side effects. They return structured text that the application acts on. There is no agent to over-privilege. |
| LLM07:2025 | System Prompt Leakage | 🟡 accepted | No output filter stops a model echoing its own system prompt into a report or an answer. **Impact assessed as low:** the prompts are product design, not credentials — no key, no secret and no other user's data is in them, and `CLAUDE.md`'s security note already states plainly that the real protection is keeping prompts server-side rather than un-extractable. **Trigger to revisit:** if a prompt ever comes to contain a secret or another user's data, this stops being low. |
| LLM08:2025 | Vector and Embedding Weaknesses | ⚠️ finding | Same as **SR-2026Q3-06** — the cache is the embedding surface here. |
| LLM09:2025 | Misinformation | ⚠️ **1 finding** | **SR-2026Q3-07**. A model writes a hire/no-hire-shaped assessment of a real person and nothing on screen says it is machine-generated. |
| LLM10:2025 | Unbounded Consumption | ✅ covered | Daily AI spend circuit breaker, global and per-user; per-feature rate limits; bounded `max_tokens`; resume text capped at 20k chars at extraction; the injection scanner itself caps at 40k. `test_ai_budget.py`, `test_report_budget.py`. |

---

## Findings from this review

Each carries an id so a later review can say "still open" without restating it.

### SR-2026Q3-01 — the CSP blocks the captcha it is supposed to allow · **high** · open → Task 5

`frontend/next.config.ts` lists `https://challenges.cloudflare.com` in `frame-src` and in
`connect-src`, and **not** in `script-src`. `components/billing/Turnstile.tsx` loads the
widget by injecting `<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">`,
which the policy therefore refuses. The component's own `script.onerror` handler resolves
`false` and returns, so there is no exception and no visible error — the widget simply never
renders.

The consequence is not cosmetic. `Offer.requires_captcha` is the control standing between a
₹1 launch offer and a script farming it with throwaway accounts, and the server refuses
captcha-gated offers when Turnstile is unconfigured. So the current production behaviour is
that every offer requiring human verification is unpurchasable, and the anti-abuse control
that was supposed to be running is not running. **This is why A02 and API6 are linked: a
misconfiguration silently disabled a business-flow control.**

### SR-2026Q3-02 — the CSP and the avatar feature disagree · **low** · open

`img-src` allows `'self' data: blob:` plus exactly three hosts (`*.supabase.co`,
`lh3.googleusercontent.com`, `avatars.githubusercontent.com`). The profile page renders
`<img src={formData.avatar_url}>` with a comment explaining that a plain `<img>` is used
*because* avatars are "user-supplied URLs from arbitrary hosts" and `next/image` would
require an allowlist. Under the live CSP there is an allowlist anyway, and it is the same
three hosts — so an avatar on any other host is blocked and the `onError` handler hides the
element. Nobody is at risk; the code says one thing and the deployment does another, which
is how the next person makes a wrong decision. Either widen the policy deliberately or
correct the comment and validate the field against the three hosts.

### SR-2026Q3-03 — profile URLs are unvalidated strings · **low** · open

`avatar_url`, `linkedin_url` and `github_url` are `str | None` on both the Pydantic request
model and the SQLAlchemy column, with no scheme allowlist and no length bound beyond `Text`.

**This is not currently exploitable and the review should not pretend otherwise.** The only
render site is `<img src>`, where a `javascript:` URL does not execute, and CSP `img-src`
blocks off-allowlist hosts anyway. It is recorded because the distance between here and an
XSS is one `<a href={profile.linkedin_url}>` written by somebody who reasonably assumed a
field called `linkedin_url` contains a LinkedIn URL. A scheme allowlist at the schema is a
few lines and removes the assumption.

### SR-2026Q3-04 — no auth-specific rate limiting · **high** · open → Task 4

Every limiter built by `core/rate_limit.rate_limiter()` takes `CurrentUser` as a dependency,
so it can only key on an **authenticated** caller. Login, signup and password reset are
unauthenticated by definition, and in this architecture they are not backend routes at all —
they are Supabase GoTrue, called directly from the browser. The consequence is that
credential-stuffing defence for this product currently rests entirely on GoTrue's own
limits, which are a hosting-console setting nothing in this repository asserts, reads or
can prove. Assigned to Task 4.

### SR-2026Q3-05 — the log retention clock is a constant, not a job · **medium** · open → Task 6

`services/legal/retention.py` defines `SECURITY_LOG_RETENTION_DAYS = 180` with a comment
citing the CERT-In Directions of April 2022, and `FINANCIAL_RETENTION_YEARS = 8`. **Nothing
purges on either clock** — there is no scheduled job — so both constants describe an
intention rather than a behaviour, and the privacy disclosure promises the intention. There
is separately no evidence in the repository about *where* the logs are held, which is the
other half of what CERT-In asks for. Assigned to Task 6.

### SR-2026Q3-06 — a global cache entry keyed on candidate text · **medium** · mitigated, open

`services/ai/vector_cache.py` documents its tenancy rule carefully and follows it: anything
shaped by one candidate's CV or answers is cached per-user in Redis, and the file explains
exactly why a global cache would otherwise serve candidate B a question about candidate A's
internship.

`gd_topic_prep` is the exception. It is cached in **global** scope keyed on `raw_topic`, the
phrase a candidate types into the topic box, on the stated reasoning that a topic phrase is
public and nothing said in a round reaches it. That reasoning holds for confidentiality and
does not hold for integrity: it means one candidate's typed input produces a payload served
to other candidates. Task 1 fenced `raw_topic`, which removes the injection route into it;
what remains is that a shared cache is keyed on unvalidated user input at all. **Decide
next quarter:** either narrow the key to a catalogue topic, or state the acceptance
explicitly in the file.

### SR-2026Q3-07 — nothing says the assessment is machine-generated · **medium** · open → Task 9

Scores, readiness levels and report prose are model output presented without qualification.
A candidate can reasonably read a report as an evaluation. Assigned to Task 9.

### SR-2026Q3-08 — `CLAUDE.md` understates the CI gate · **low** · open

`CLAUDE.md` states that CI "only runs lint + typecheck for both frontend and backend — it
does not run the test suites", and instructs the reader not to assume passing CI means tests
passed. That is **false as of this review**: `.github/workflows/ci.yml` runs both suites and
a production build, and `codeql.yml` and `image-scan.yml` exist alongside it.

Recorded even though it errs safe. A security note that is wrong is a security note that
gets checked and discarded, and the next wrong one will be wrong in the other direction.

---

## Standing decisions

Things repeatedly re-litigated, settled here so a future review can move past them.

| Decision | Reason |
|---|---|
| Rate limiting fails **open** | A limiter outage must not end a candidate's interview. Revisit on the first Redis incident of any length. See A10. |
| No CSP on the backend | It serves JSON and no HTML. The frontend origin has one, and that is where scripts load. |
| `'unsafe-inline'` and `'unsafe-eval'` on `script-src` | The App Router emits inline bootstrap scripts. Per-request nonces through middleware is a larger change than a hardening pass. The part that matters is kept: an injected `<script src="https://attacker/…">` is still refused. **Revisit when the CSP is next touched** — `unsafe-eval` in particular has no stated justification and may be removable. |
| The MIME allowlist on upload is usability, not security | The content type is whatever the caller typed. What defends the upload is that extraction must succeed on the bytes. |
| Detection heuristics flag; they never refuse | Every signal in `resume/integrity.py` has a legitimate producer. A false rejection costs a real candidate their interview; a false flag costs a reviewer a minute. |
