# InterviewOS — documentation

The hub note. Open the vault at the repo root and this is the page the graph hangs off.

**Why this file exists.** Obsidian's graph is built from `[[wikilinks]]`, not from folders — a
tidy directory of notes that never reference each other renders as a field of unconnected
dots, which is exactly what this vault was. Every link below is a real edge in that graph, so
the graph becomes a map of how the product actually fits together rather than a list of
filenames.

Wikilinks resolve by **filename**, not path, so `[[VOICES]]` keeps working wherever a note is
moved to. Prefer them over relative Markdown links for anything inside this vault.

---

## Start here

- [[prompt]] — the product brief and phase-by-phase status. **Read this before making
  architectural decisions**: it records what is genuinely wired versus what is still a
  placeholder. Living context, not a README.
- `CLAUDE.md` at the repo root — build commands, architecture, and the conventions an agent
  needs. Deliberately left at the root rather than moved here, because tooling looks for it
  there.

## Running it

- [[DEPLOY]] — the current deployment runbook: environment variables, the settings that
  actually matter, and what breaks when each one is wrong.
- [[KNOWN-GOOD]] — the state everything was in before the security pass, and why each thing
  is that way
- [[DATA-RESIDENCY]] — where the data actually sits, checked against CERT-In and RBI. The
  answer is "not determined", and the note says why that is the honest finding.
- [[SECURITY-REVIEW]] — the standing quarterly review against the OWASP web, API and LLM
  top tens. A clock rather than an audit: the schedule is enforced by a test that fails when
  the review is overdue, and the log records what each one actually found.
- [[COMPLIANCE]] — DPDP Act and adjacent regimes: what the code does, the gaps, what has
  since been built (consent ledger, age gate, self-service export and erasure, retention),
  and the blocker list that needs a lawyer and a named officer rather than more code
- [[AUTOPAY-EMANDATE]] — the auto top-up mandate flow, traced end to end and **not built**:
  what Razorpay's recurring rails actually require, where RBI's Additional Factor
  Authentication happens, and the one thing it is blocked on (a Razorpay test account)
- [[DEPLOYMENT]] — the older, longer infrastructure write-up. Overlaps [[DEPLOY]]; where they
  disagree, [[DEPLOY]] is newer.
- [[OBSERVABILITY]] — what a log line is allowed to contain (the PII audit and its result),
  and how the logs get somewhere durable: Render's native drain, not an in-process shipper.
- [[RATE-LIMIT-HEADROOM]] — peak RPM/ITPM/OTPM at 200 concurrent users, as a script you
  run rather than a number you quote. The finding: output tokens bind first, not
  requests — and the report semaphore, not the provider, is what sets the peak.
- [[MULTI-REPLICA]] — the audit of every piece of in-process state against running more
  than one of us: what is safe, what is a tradeoff already written down, and the two
  things that were genuinely broken — one of which was the container's boot chain
  rather than anything in the application.
- [[REDIS-CUTOVER]] — moving Redis from localhost to a managed, replicated instance:
  the two numbers to read off the plan page first, how to prove `rediss://` works before
  production depends on it, and what stops protecting you while it is broken.
- [[UPTIME]] — the monitoring runbook: which endpoints, what a healthy response looks like,
  how often, and who gets woken up. Written to be followed by a non-engineer. Its central
  point: `/api/v1/health` returns 200 while the database is down, so a status-code-only
  monitor is green through a total outage.
- [[ERROR-TRACKING]] — Sentry on both halves of the app, the five layers that keep a
  candidate's resume and answers out of every event, and how to verify it on a live
  deployment.

## Money

- [[AI-COST-MODEL]] — what each feature costs per call, measured from the real usage ledger
  rather than from vendor rate cards. Every number in the plan catalogue is priced against
  this, so it is the note to re-read before changing an allowance.
- [[SUBSCRIPTION-BUNDLE-PROPOSAL]] — **a proposal, not a decision.** Whether to bring back a
  monthly price, in the one shape that could coexist with the pay-per-item pivot: unlimited
  practice, interviews still bought one at a time. Its point is §6 — five go/no-go thresholds
  to be measured before anybody writes a line of it, and the note says plainly what it means
  if they fail.
- [[TEMPORARY-token-counter]] — the interim `ai_usage` ledger and the admin screen over it.
  Explicitly temporary: it was the stand-in for a credit system, which now exists in
  `backend/app/services/billing/`. This note describes what can be removed.

## Voice

- [[VOICES]] — the panel roster, which voice id belongs to whom, the tone table, per-speaker
  pace, and the one command that stops a voice being wrong again. Start here for anything
  audio.
- [[ELEVENLABS-SETUP]] — **superseded**, kept only for the vendor cost comparison that
  decided the current provider. Do not follow its setup steps. See [[VOICES]].

## The interview itself

- [[INTERVIEW-REDESIGN]] — why the interview is a room with a two-person panel rather than a
  form with questions on it, and the reasoning behind the surfaces that came out of it.

---

## Where the rest of the documentation lives

Most of this codebase explains itself in place, and that is deliberate — a note describing a
function drifts from it, whereas a comment above the function does not. The two places worth
knowing about:

- `backend/app/prompts/*.md` — the AI prompts, as Markdown. These are **product behaviour, not
  documentation**: editing `interview_panel.md` changes what the panel says. They are part of
  the vault and will show in the graph, which is useful, but treat them as source.
- `backend/knowledge/` — hand-maintained YAML reference data (the recruiter catalogue, study
  subtopics, per-company research) read at runtime.

- [[DESIGN-LANGUAGE]] — what InterviewOS looks like, and why
- [[REDESIGN]] — page-by-page progress
