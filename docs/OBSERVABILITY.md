> Part of the [[index|Hotseat documentation]].

# Logs — what they contain, and where they go

structlog already produces correct JSON in production. Nothing carried it beyond Render's own
log viewer, which keeps a rolling window and is gone when the service restarts. This page
covers both halves: **the PII audit of what goes into a log line**, and **shipping the lines
somewhere durable**.

Related: [[ERROR-TRACKING]] (Sentry, and the same scrubbing rules) · [[UPTIME]] · [[COMPLIANCE]]

---

## Part 1 — the PII audit, and its result

**Stated explicitly, because "we checked" is not a finding.**

### How it was audited

An AST pass over every `logger.debug/info/warning/error/exception/critical` call in
`backend/app/`, matching keyword arguments whose **name** suggested content or a credential —
`preview`, `content`, `resume`, `answer`, `transcript`, `token`, `email`, `body`, `text`,
`prompt`, `input`, `raw`, and a dozen more. 47 call sites matched; each was read.

### What was found — four real leaks

| Where | What it logged | Why it mattered |
|---|---|---|
| `services/resume/extractor.py` | `preview=text[:120]` on a parse failure | The **first 120 characters of a CV** are the name, the e-mail address and the phone number |
| `services/ai/response_parser.py` | `content_preview=content[:400]` on a JSON failure | The model's output **is** the candidate's report, their model answer, or the panel's assessment of what they said |
| `services/ai/response_parser.py` | `content_preview=stripped[:100]` on an array response | Same |
| `services/ai/json_validator.py` | `raw_data_preview=str(data)[:300]` on a schema failure | On a report schema, 300 characters of somebody's assessment |

Plus e-mail addresses logged on three auth paths (`api/v1/auth.py`, `core/security.py`,
`api/v1/admin.py`).

### What was NOT found

Worth recording, so nobody re-audits the same ground:

- **No auth token, JWT or provider key** was logged anywhere. `core/security.py` logs the
  failure reason and never the token.
- **No request body** is logged by any middleware.
- **No answer or transcript** was logged directly — the exposure was always indirect, through
  a preview of the model's output.
- `DB_ECHO` would log every statement **with its parameters** — which on this schema is
  answers and resume text. It defaults to off, is not set anywhere, and is deliberately absent
  from `render.yaml` with a test keeping it absent.

### What was done about it

**Both a call-site fix and an enforcement point**, because either alone is insufficient.

The four call sites now log what a reader actually needs — a length, a marker count, a
delimiter check, the schema keys — instead of the data. A field that is always `[redacted]` is
safe and useless.

`core/logging._redact_pii` then enforces the rule on the way out, once, for **the fifth leak
that has not been written yet**. It runs last of the shared processors and before the
renderer, so it applies to console output on a developer's machine as well as to production
JSON — a leak that only exists locally is still a leak, and it is the one that gets pasted
into a ticket.

It **shares its denylist and its sensitive-value registry with the Sentry scrubber**
(`core/observability.py`) rather than keeping a second copy. Two lists of "what counts as
personal data here" would drift, and the drift would be invisible on both sides.
`register_sensitive_text()` is already called where resume text is extracted and where an
answer is submitted, so those exact strings are removed from log lines too — which is the only
thing that works for text with no recognisable shape.

### What is deliberately NOT redacted, and why

**UUIDs.** `user_id` and `session_id` stay readable in logs. This is a judgement, not an
oversight:

- They are pseudonymous already — a UUID names a row, not a person.
- They are the entire mechanism for triaging an incident.
- Hashing them buys little against an operator who can also read the database, while making
  the logs unusable for the person the logs exist for.
- E-mail addresses **are** redacted, because those identify a person directly — and a
  `user_id` on the same line already answers "who".

**`request_id` survives verbatim**, exempt from every rule. It is echoed in the
`X-Request-ID` response header, so it is the one value a person can quote from a failed
request; a hashed version would find nothing.

**Numbers are never redacted by key name.** `input_tokens` matches the denylist on "token" and
is a count — as are `output_tokens`, `cache_write_tokens` and every field the AI cost ledger in
[[AI-COST-MODEL]] is derived from. An integer cannot be a resume.

> ### This balance changes the moment logs leave the host
>
> Everything above treats the log stream as **first-party**: the operator can already read the
> database, so a `user_id` in a log tells them nothing new. **A log drain to a third party
> makes that party a processor** — which is a §5 disclosure question, not a logging one. If
> you enable Part 2 below, add the destination to `services/legal/disclosure.py` so candidates
> are told, and re-read this section deciding whether identifiers should still pass.

`backend/tests/test_log_redaction.py` pins all of it, in **both** directions: that the four
leaks stay closed, and that redaction does not blank the fields an incident is diagnosed with.

---

## Part 2 — shipping the logs somewhere durable

### Use Render's native log stream. Do not add a shipping library.

Render supports **Log Streams**: the platform forwards stdout/stderr to a syslog-over-TLS
endpoint. That is the right answer here and it is not a close call:

- **No code, no dependency, no request-path cost.** An in-process shipper — `logging` handler,
  OpenTelemetry exporter, vendor SDK — buys a network call inside the process serving
  interviews. Even "async, best-effort" shippers have a queue that fills, a flush that blocks
  at shutdown, and a failure mode where the log shipper takes the API down. On a 512 MB free
  instance that is a real risk for zero benefit.
- **It survives the process.** Logs from a container that crashed on boot are exactly the ones
  worth having, and an in-process shipper cannot send them because it died with the process.
- **It cannot be forgotten.** It is service configuration, not a call somebody has to make.

The application's only job is to write correct JSON to stdout, which it already does when
`LOG_FORMAT=json`.

### Setting it up

**Human steps — these cannot be done from the repository.** Render log streams are an
account-level setting and are not expressible in `render.yaml`.

1. Create a free account at a syslog destination. Any of these work and none needs a card:
   - **Better Stack (Logs)** — free tier, good search, and it can alert on a log pattern.
     Pairs with the uptime monitoring in [[UPTIME]] if you use Better Stack there too.
   - **Papertrail** — 50 MB/month free, simplest possible setup.
   - **Datadog / Grafana Loki** — if one is already in use elsewhere.
2. In that tool, create a **source** of type **syslog** and copy the host and port it gives
   you (e.g. `logs.betterstack.com:6514`).
3. Render dashboard → your service → **Settings → Log Streams → Add log stream**.
   Paste the endpoint. Render sends over TLS.
4. Save. Logs begin flowing within a minute or so.

### Confirming a real line arrived

```bash
# From anywhere. A request with a request id you choose, so you can find it.
curl -s -H 'X-Request-ID: log-drain-smoke-test-001' \
     https://<your-render-host>/api/v1/health > /dev/null
```

Then search the destination for `log-drain-smoke-test-001`. You should find a line like:

```json
{"event":"application_startup","request_id":"log-drain-smoke-test-001",
 "app":"Hotseat","env":"production","level":"info","timestamp":"..."}
```

`request_id` is chosen deliberately for this: it is the one field exempt from redaction, so it
is guaranteed to arrive verbatim and is searchable.

**While you are there, confirm the redaction end-to-end.** Upload a deliberately unreadable
PDF and search the destination for any fragment of it. The `resume_content_not_a_resume` line
should be present with `chars` and `resume_markers` on it, and **no text from the file**.

> ### Not verified here, and it needs a human
>
> **This runbook has not been confirmed against a live drain**, because there is neither a
> deployed service nor a log destination account: `interviewos-api.onrender.com/api/v1/health`
> answers 404 from Render's own router, and `interviewos.dev` does not resolve. The redaction
> and the JSON shape are tested in-process; the **transport** is the part only a real
> deployment can prove, and the two commands above are how to prove it.

### If Render is ever left behind

Nothing above is Render-specific except step 3. Every managed host has an equivalent
(Fly.io log shipper, Railway drains, Cloud Run → Cloud Logging, ECS → FireLens). The rule that
carries over is the one at the top of this section: **the platform ships the logs; the process
writes JSON to stdout and nothing else.**
