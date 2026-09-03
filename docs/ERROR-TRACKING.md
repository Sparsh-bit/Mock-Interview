> Part of the [[index|InterviewOS documentation]].

# Error tracking

Sentry, on both halves of the app, with the candidate taken out of every event
before it leaves the process.

Both DSNs are **blank by default and blank is a supported state**: nothing
initialises, nothing warns, no network call is made. That is the intended
configuration on a developer's machine and in CI.

| where | package | initialised in | configuration |
|---|---|---|---|
| Backend (Render) | `sentry-sdk[fastapi]` | `app/core/observability.py`, called from `main.py` at import time | `SENTRY_DSN` |
| Browser | `@sentry/browser` | `lib/observability/sentry.ts`, mounted by `components/providers.tsx` | `NEXT_PUBLIC_SENTRY_DSN` |

A DSN is not a secret. It identifies a project and authorises sending events to
it — the same category as the Supabase anon key, and for the same reason it
carries `NEXT_PUBLIC_` on the frontend: the browser cannot report anything
without it. **No DSN is hardcoded anywhere**, and two tests fail if one ever is.

## What is stripped, and why each layer is there

This app's ordinary working data is personal data: a resume, the answers someone
gave, the transcript of what they said out loud, and the token that authenticated
them. Every one of those is collected by default by an error tracker that has not
been told otherwise. Five layers, weakest last:

1. **No local variables.** `include_local_variables=False`. Sentry defaults this
   to **True** and attaches every local of every stack frame — so when the resume
   parser raises, the resume is in the report. No filter helps when the local is
   called `text`, so the collection is off rather than filtered. This is the
   single most important line in `observability.py`.
2. **No request bodies.** `max_request_body_size="never"`, and the browser SDK's
   `sendDefaultPii: false`. The body of `POST /interview/{id}/answer` *is* the
   answer.
3. **Key-based redaction**, recursive, over every event and every breadcrumb.
   Deliberately over-broad — matching `answer` also matches `answersCorrect`, and
   losing a counter is a better failure than keeping a transcript.
4. **Pattern-based redaction** inside the strings that survive: JWTs, `Bearer`
   headers, provider keys, e-mail addresses, and UUIDs.
5. **`register_sensitive_text()`** for what patterns cannot recognise. An answer
   has no shape; once interpolated into an exception message nothing in the string
   says whose words those are. It is registered where it enters the process —
   `POST /interview/{id}/answer` and `resume/extractor.extract_text()` — and
   removed from anything on the way out. Scoped to a `ContextVar`, so it is
   per-request and never crosses between candidates.

Session and user ids become a **stable one-way handle** (`[uuid:1a2b3c4d]`) rather
than disappearing, so "one user hit this 400 times" is still distinguishable from
"400 users hit it once". It is a correlation token, not a lookup key — nothing may
join it back to a row.

**Session Replay is deliberately not installed.** It records the DOM, and the DOM
during an interview is the question and the answer being typed into it. Not
installing it at all is safer than getting masking configuration right. Neither is
performance tracing: spans describe every request the page makes, it is a separate
cost centre, and turning it on needs its own scrubbing review.

Proven by `backend/tests/test_sentry_scrubbing.py` (18 tests, including a real
exception thrown through a real FastAPI route into a capturing transport) and
`frontend/src/lib/observability/scrub.test.ts` (16 tests).

## Verifying it live

The tests prove capture and scrubbing in-process. These steps prove the DSN,
the network path and the CSP — the three things only a real deployment exercises.

### Backend

```bash
# On the Render service, with SENTRY_DSN set:
uv run python -c "
from app.core.observability import init_sentry
import sentry_sdk
assert init_sentry(), 'SENTRY_DSN is not set in this environment'
sentry_sdk.capture_message('interviewos backend error tracking smoke test')
sentry_sdk.flush(timeout=5)
print('sent')
"
```

The event appears in Sentry within a few seconds. Confirm on the event page that
**Additional Data**, **Request** and **User** are empty or redacted, and that no
stack frame has a *Local Variables* section.

### Browser

1. Set `NEXT_PUBLIC_SENTRY_DSN` in the Cloudflare Pages project and redeploy.
   It is a **build-time** variable — it is compiled into the bundle, so setting it
   without a rebuild does nothing.
2. Open the deployed site, and in the console run
   `throw new Error('interviewos browser error tracking smoke test')`.
3. The event should appear in the JavaScript project.

**If nothing arrives, check the CSP first.** `connect-src` in `next.config.ts` is
derived, and it adds the ingest origin only when `NEXT_PUBLIC_SENTRY_DSN` was set
*at build time*. With it missing the browser blocks the POST and the failure is
invisible: the page works, the user sees nothing, and the dashboard stays empty —
which reads as "no errors" rather than "no reporting". A blocked request shows in
the Network tab as `(blocked:csp)` and in the console as a
`Refused to connect` violation.

## Still needs a human

Creating the Sentry organisation and the two projects, and setting the DSNs on
Render and Cloudflare Pages, is account setup that cannot be done from the repo.
Everything else is in version control.
