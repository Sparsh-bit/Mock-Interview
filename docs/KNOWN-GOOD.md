# Known-good baseline

The state of InterviewOS, and *why each thing is the way it is* — so that a change made under
pressure restores the behaviour rather than merely silencing the symptom.

Written before the first penetration pass and updated after it. Two rounds are now recorded
below; the numbers in [How to tell if something is broken](#how-to-tell-if-something-is-broken)
include their tests.

**Read this before reverting anything.** Several things in here look like bugs and are
deliberate; several others look deliberate and are the scars of real incidents. Both kinds are
marked.

- Baseline: `4867027` (round one) plus round two, unpushed at the time of writing
- Related: [[index]] · [[prompt]] · [[AI-COST-MODEL]] · [[DEPLOY]]

---

## How to tell if something is broken

Run all of it. Anything other than these numbers means something moved.

```bash
docker-compose up -d            # Postgres + Redis. Tests ERROR ~70 times without it.
cd backend && uv run pytest -q --no-cov      # 1876 passed, 2 skipped, 6 warnings
cd backend && uv run ruff check . && uv run mypy app
cd frontend && npm test -- --run             # 685 passed
cd frontend && npx tsc --noEmit && npx next lint && npm run build
```

**The two skipped backend tests are correct.** `test_error_status_codes.py` parametrises over
every `AppError` subclass and skips two whose constructors need arguments it cannot invent.
They are skips, not failures.

**~70 ERRORs mean Docker is not running.** This happened twice during the last session and
looks alarming — asyncpg raises from inside an SSL connection attempt, so the traceback points
at the network layer rather than at the missing container. It is not a regression.

---

## The invariants worth protecting

These are the properties that took real incidents to establish. A pen-test fix that violates
one of them has traded a finding for an outage.

### Money

| Rule | Where | Why it is like that |
|---|---|---|
| One source of truth for every price | `services/billing/plans.py` | A price typed anywhere else goes stale silently. `/pricing` advertised a free interview and a free GD for weeks after both went paid. |
| `consume()` does not commit | `services/billing/credits.py` | `get_db` commits on success and rolls back on error, so a failed AI call undoes the charge. **Never `db.commit()` between charging and doing the work.** |
| Usage is a COUNT over the ledger | `credits.py` | Not a stored counter, so the monthly reset is a query predicate rather than a cron job that can fail. |
| The browser never computes a price | `api/v1/billing.py::_priced_catalogue` | Two implementations of what money costs will disagree, and the one that disagrees in the candidate's favour gives product away. |
| An empty coupon scope means EVERY item | `services/billing/offers.py::covers` | Getting this backwards switches off every code in the table. Reading it as "no items" is the inverted failure. |
| A flat-price coupon can reach a bundle | admin UI warns, does not block | `₹99 flat on the five-pack` is legitimate. A ₹25 flat code on a ₹199 pack sold five interviews for ₹25 — the preview caught it, and the fix was per-item scope, not a block. |

### Reports

The report path has failed in production **three separate ways**. All three are fixed and all
three are subtle enough to be reintroduced by an innocent-looking change.

1. **One call whose length was the failure.** A report used to be a single model call carrying
   the summary *and* one analysis entry per question. Latency is output-token-bound, so long
   interviews — the ones worth reporting on — were the ones guaranteed to time out. Now a
   summary call plus one batch per six questions, concurrent. `services/report/composer.py`.
2. **`wait_for(gather(...))` is all-or-nothing.** At the deadline it cancels *at the gather*,
   so every part that had already succeeded was discarded. Now `asyncio.wait`, which returns
   what finished. **Do not put a deadline back around the whole coroutine.**
3. **A duplicate rating discarded the report.** `record_round` handles the expected duplicate
   `RatingEvent` with a rollback, and reports share that transaction — so a second generation
   silently lost its write and returned 200. The insert is inside a SAVEPOINT now.
   `services/progress/recorder.py`, pinned by `test_rating_savepoint.py`.

There is a tripwire: `report_write_did_not_persist` logs at ERROR if the stored row disagrees
with what was just generated. It has caught this class twice.

### Speech

- `speakOnce` returns whether it **actually made a sound**. `utter.onerror = finish` used to
  report a refused utterance as a spoken one, which silenced one panelist while the other
  worked — speechSynthesis refuses per *voice*, not per page.
- A voice that produced nothing is retried once on the engine default, keeping pitch and rate
  so it still sounds like that person.
- Each panel line is spoken inside its own `try`. A bare `await` in that loop meant a fault on
  Anil's line deleted Priya's from the interview entirely.

### Autostart is a purchase

`?autostart=1` submits the interview setup form on its own, and `POST /interview/plan` charges
**before** it generates. Autostart is therefore gated on whether a resume was on file **when
the page loaded** — not on whether one exists now. Uploading a resume during the visit must
never also mean "and spend money".

Pinned by `src/app/(dashboard)/interview/autostart-safety.test.ts`.

---

## Security posture as it stands

What is already true, so the pen test can start from here rather than rediscovering it.

- **Row Level Security on every table**, pinned by `test_rls_coverage.py`. This is the actual
  access control — not the API layer.
- **The only secret-shaped value in the browser bundle is `NEXT_PUBLIC_SUPABASE_ANON_KEY`**,
  which authorises nothing on its own. Asserted by `security-headers.test.ts`. Anything with a
  `NEXT_PUBLIC_` prefix is public by definition; never put a service key, JWT secret, AI
  provider key or Razorpay secret behind it.
- **JWTs are verified locally** (`core/security.py`) — no network round-trip per request.
- **Razorpay signature verification is a pure function and fully tested.** Only `create_order`
  needs live keys.
- **One redemption per account is enforced by a unique index**, not by a read-then-write check.
  There is deliberately no `per_user_limit` column: a value above 1 would contradict the
  constraint that makes the rule true.
- **Rate limits** on report generation (per hour) and AI requests (per minute), Redis-backed.
- **The daily AI spend cap is a circuit breaker, not an allowance.** `AI_DAILY_BUDGET_USD`
  should sit well above a busy day; `AI_USER_DAILY_BUDGET_USD` is what rations.

### Known weak points — expect the pen test to find these

Listed honestly, because finding them in a report is worse than having written them down.

| Area | What is weak | Notes |
|---|---|---|
| Fallback provider | When either AI budget is exceeded, calls fall through to GLM, which has been rate-limiting | Hitting a cap is currently a hard stop, not a slower model |
| Migration 021 | Applied **by hand** against Supabase | Migrations here are not automatic. Check it is applied before testing offer banners |
| PDF export | `pdf_url` field exists; **the documented route does not** | The module docstring lists `GET /reports/{id}/export/pdf`. It is not implemented |
| 401 burst | Several endpoints 401 together at page load before auth settles | Cosmetic in logs, but it is noise a scan will flag |
| `docs/DEPLOYMENT.md` | Competing variant of `DEPLOY.md` | `CLAUDE.md` names `DEPLOY.md` as current. Four docs are unreachable from the `index.md` hub |

---

## Fixed on the way in

Done immediately before the pen test, so a finding that mentions any of these is either stale
or a regression.

- **Open redirect after login.** `/login?redirectTo=https://evil.example` was pushed
  unvalidated — the victim logs in on the real domain and is delivered to a copy. Now
  `lib/auth/safe-redirect.ts`, which rejects absolute URLs, protocol-relative `//host`,
  backslash variants, `javascript:`/`data:`, and whitespace/tab/newline smuggling.
  **The call site is pinned too** — the pure function was tested first and reverting the call
  site left all 22 tests green, which is a fix that is not a fix.
- **PyPDF2 → pypdf.** PyPDF2 is unmaintained and its last release predates several parser
  hardening fixes. It parses files an anonymous user uploads, which makes it one of the largest
  attack surfaces in the product.
- **Deprecated `HTTP_422_UNPROCESSABLE_ENTITY`** → `..._CONTENT`.
- **`default_response_class=ORJSONResponse` removed.** FastAPI serialises directly now and its
  own notice says that path is faster. It was emitting a deprecation per route — 11 of the 17
  warnings in a full run, which is how a real warning becomes invisible.
- **Five dead `it.skip` tests deleted.** A skipped test is not a guard; it is a comment that
  inflates the count.

---

## Shape of the system

- **84 API routes** across 20 modules in `backend/app/api/v1/`. Heaviest: `billing` (9),
  `interview` (8), `admin_offers` (8), `admin` (8).
- **57 backend test files**, **42 frontend test files**.
- Migrations run to **021**, at repo-root `database/migrations/` — not under `backend/`.
- Frontend route groups: `(auth)`, `(dashboard)`, `(interview)`. `/pricing` is deliberately
  **top-level**, so it renders for logged-out visitors with no dashboard chrome.

### Testing idiom used here

Worth knowing before writing a fix, because it is unusual and deliberate:

- The vitest environment is **`node`, not jsdom**. Components that mount `framer-motion` or
  `next/navigation` cannot be rendered in a test at all. So behaviour that lives in markup is
  pinned by **source-level assertions**, and logic worth testing is pulled into pure modules.
- **Every new guard is mutation-tested** — the behaviour is broken deliberately to confirm the
  test fails. This is not ceremony: in the last session alone, three guards passed while the
  thing they claimed to protect was broken (a count-based assertion with slack, a regex
  matching anywhere in the file, and a window that reached a neighbouring element's attribute).

---

## The security pass

Two rounds, 74 attacks, all kept as tests so "run it again" is one command.

`test_pentest_authz.py` · `test_pentest_idor.py` · `test_pentest_money.py` ·
`test_pentest_uploads.py` · `test_pentest_surface.py`

### What was actually vulnerable

**Path traversal into another candidate's storage folder.** `resumes/{user_id}/{file_id}/
{filename}` was an f-string over the caller's multipart filename, and that user_id segment is
the tenancy boundary in storage. `../../{other_user}/{their_file_id}/resume.pdf` writes into
somebody else's folder from an ordinary authenticated upload. Fixed by `safe_filename` — a
positive character allowlist, because the list of things that mean "parent directory" to some
backend (`..`, `%2e%2e`, `....//`, a backslash, an overlong UTF-8 sequence) is not one anybody
can finish writing.

**Open redirect after login**, closed in the previous commit — see [Fixed on the way in](#fixed-on-the-way-in).

### The trap worth remembering

The admin sweep found **zero admin routes** and only its vacuity assertion caught it. This
FastAPI version does not flatten an included router into the parent list — it keeps an
`_IncludedRouter` that resolves lazily — so `app.routes` reports **5 routes for an app serving
90**. Any security sweep walking `app.routes` finds nothing, passes, and reads as full coverage
forever. `_walk` follows the wrappers; the fixture asserts a floor of 15 admin routes.

### Held under attack

- All 18 admin routes refuse a normal account — including with `is_admin`, `role: admin` and
  `app_metadata.role` in the token. Admin is read from the users table, never the claims.
- Forged tokens: wrong secret, expired, `alg: none`, no subject, wrong audience, seven
  malformed headers. All 401, no 500s.
- IDOR with **real** ids: report, session, transcript, answer key, and both write paths
  (generating a report against another session, answering into one).
- Payments: request models cannot name a price; extra fields are dropped not assigned; forged
  signature and crafted item ids refused.
- Uploads: oversized, empty, zip-bomb DOCX, and non-PDF bytes labelled `application/pdf`.

### Not findings — recorded so they are not re-investigated

- **CSRF.** There is no ambient credential: no route reads or sets a cookie, and a Bearer token
  is not attached automatically. A session cookie would make every state-changing route
  forgeable, so the *absence* is pinned rather than the mitigation.
- **Rate-limit bypass.** Limits key on the authenticated user id, never on an address.
  `request.client.host` is read in two places, both audit records.
- **SSRF.** Nothing fetches a user-supplied URL.
- **Stored XSS.** `linkedin_url`, `github_url` and `avatar_url` are stored unvalidated — safe
  only because nothing binds them to an `href` and nothing uses `dangerouslySetInnerHTML`.
  Both absences are pinned; the day either changes, the unvalidated storage becomes the bug.
- **Answer-key leak.** The practice page requests it; the server withholds it until that user
  has answered that question.
- **Secrets in the bundle.** None. The only `NEXT_PUBLIC` value shipped is the Turnstile site
  key.
- **The public report.** Deliberately narrow — no session id, no transcript, no roadmap.

### Round three — money under concurrency

**One credit cannot be spent twice.** Raced with real transactions, not mocks: a row lock is a
property of the database, so only live connections contending for the same row prove the second
one waited. Two simultaneous starts, five simultaneous starts, and — as the vacuity guard —
three credits against five attempts, which must yield exactly three. It does.

Removing the `FOR UPDATE` is caught. Worth knowing precisely: **only the five-way race catches
it.** The two-way still passes with the lock gone, because two coroutines on one event loop
frequently do not overlap enough to collide. The two-way is kept because it is the real gesture
— a double-click — but the five-way is what holds the property.

**A payment cannot be credited twice.** Five deliveries of one `payment_ref` credit once, which
is not a hypothetical: Razorpay retries on any non-2xx, so repeated delivery is ordinary
traffic. The browser's verify call and the webhook also arrive together in the normal case, and
that pair is raced too.

**The webhook signature is the whole perimeter** — the endpoint is unauthenticated by
necessity, since Razorpay holds no user token. Forgery, tampering-after-signing, six malformed
signature shapes, and an unsigned request are all refused; a correct one verifies, which is the
guard against a function that just returns False and rejects every real payment. The comparison
is `hmac.compare_digest` — a plain `==` returns on the first differing character and recovers
the signature one character at a time, and that mutation is caught.

Replay is guarded by the ledger rather than by cryptography, and that is the right layer: a
replayed body carries a genuine signature, so nothing about HMAC can help.

### Still untested

**RLS against live Supabase.** The policies are pinned as existing (`test_rls_coverage.py`) but
local Postgres does not enforce them, so "they work" is unproven. This is the largest remaining
gap, because RLS is the actual access-control layer.

Also open, and not code: the Fish and Anthropic keys pasted in plaintext still need rotating
(deferred deliberately), and migrations **021 and 022** are not yet applied to Supabase.

---

## If the pen test breaks something

1. **Check the numbers at the top first.** If the suite is green and the build compiles, the
   change is probably safe and the finding is probably about configuration.
2. **Check the invariants above before reverting.** Several are load-bearing in a way that is
   not obvious from the diff — the SAVEPOINT, the no-commit-between-charge-and-work rule, and
   the arrival-time resume snapshot each look removable and are not.
3. **A fix that makes a test pass by editing the test needs a reason written next to it.**
   Three guards were edited deliberately in the last session, each with the reasoning recorded
   in the commit. That is the bar.
