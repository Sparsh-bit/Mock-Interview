/**
 * Removing the candidate from an error report.
 *
 * This is the browser half of `backend/app/core/observability.py`, and it exists for
 * the same reason: the ordinary working data of this app is a person's resume, the
 * answers they typed, the transcript of what they said out loud, and the Supabase
 * token that authenticated them. All four are in the browser, so all four are within
 * reach of an error tracker unless something takes them out.
 *
 * The browser has one leak the backend does not, and it is the biggest one here:
 * `fetch` breadcrumbs. Sentry records every request the page makes, and the request
 * this page makes most often is `POST /api/v1/interview/{id}/answer` carrying the
 * answer as its body, with the bearer token in a header.
 *
 * Deliberately over-broad. Matching `answer` also matches `answersCorrect`, and
 * losing a counter off an error report is a better failure than keeping a transcript.
 *
 * Kept as pure functions over plain objects so `scrub.test.ts` can assert on them
 * without standing up an SDK.
 */

export const REDACTED = '[redacted]';

/** A backstop against bulk text riding along in a value whose key matched nothing. */
export const MAX_STRING_LENGTH = 1024;

/**
 * A key is redacted if any of these appears anywhere in its lower-cased name.
 * Substring rather than exact, because the same datum is spelled several ways
 * (`resumeText`, `resume_text`, `rawResume`) and an exact list is a list somebody
 * has to remember to extend.
 */
const PII_KEY_PARTS = [
  // Credentials
  'authorization',
  'cookie',
  'password',
  'secret',
  'token',
  'jwt',
  'apikey',
  'api_key',
  'api-key',
  'credential',
  'signature',
  // The candidate's own words
  'resume',
  'answer',
  'transcript',
  'utterance',
  'speech',
  'audio',
  'candidate',
  'feedback',
  // Free-text carriers. These names say nothing about their contents, which is why
  // they are here: `content` is the field an answer is submitted in.
  'content',
  'preview',
  'snippet',
  'excerpt',
  'prompt',
  'body',
  // Direct identifiers
  'email',
  'phone',
  'fullname',
  'full_name',
  'firstname',
  'lastname',
  'address',
  // Correlation handles
  'session_id',
  'sessionid',
  'user_id',
  'userid',
] as const;

const JWT = /\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*/g;
const BEARER = /\bbearer\s+[A-Za-z0-9._~+/=-]{8,}/gi;
const EMAIL = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g;
const UUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;

/**
 * A stable, one-way handle for a UUID.
 *
 * Session ids and user ids are UUIDs and must not be sent. Dropping them outright
 * would also drop the ability to tell "one user hit this 400 times" from "400 users
 * hit it once", which is most of what an error tracker is for. A cheap non-reversible
 * digest keeps that: the same id produces the same handle every time, and the handle
 * cannot be turned back into the id.
 *
 * A correlation token, NOT a lookup key. Nothing may join it back to a row.
 *
 * FNV-1a rather than SHA-256 because hashing here has to be synchronous —
 * `before_send` returns an event, not a promise — and `crypto.subtle.digest` is
 * async-only in the browser. The property required is one-wayness against someone
 * reading the dashboard, not resistance to a chosen-prefix attack.
 */
function uuidHandle(uuid: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < uuid.length; i += 1) {
    hash ^= uuid.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `[uuid:${hash.toString(16).padStart(8, '0')}]`;
}

function isPiiKey(key: string): boolean {
  const lowered = key.toLowerCase();
  return PII_KEY_PARTS.some((part) => lowered.includes(part));
}

/** Redact secrets and identifiers that appear inside an otherwise-kept string. */
export function redactText(value: string): string {
  let out = value
    .replace(JWT, REDACTED)
    .replace(BEARER, REDACTED)
    .replace(EMAIL, '[email]')
    .replace(UUID, (match) => uuidHandle(match.toLowerCase()));
  if (out.length > MAX_STRING_LENGTH) out = `${out.slice(0, MAX_STRING_LENGTH)}…[truncated]`;
  return out;
}

/**
 * Recursively redact PII from an arbitrary JSON-ish value.
 *
 * Depth-limited because a cycle would otherwise hang the reporting path, turning an
 * error into a frozen tab — a strictly worse outcome than a missing error report.
 */
export function scrubValue(value: unknown, depth = 0): unknown {
  if (depth > 12) return REDACTED;
  if (typeof value === 'string') return redactText(value);
  if (Array.isArray(value)) return value.map((item) => scrubValue(item, depth + 1));
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isPiiKey(key) ? REDACTED : scrubValue(item, depth + 1);
    }
    return out;
  }
  return value;
}

type Loose = Record<string, unknown>;

/**
 * `beforeSend`.
 *
 * Always returns an event. Dropping one would make the tracker quietly under-report
 * how often something fails, which is a worse lie than an event with its payload
 * removed.
 */
export function scrubEvent(event: Loose): Loose {
  const scrubbed = scrubValue(event) as Loose;

  // Sentry's own identity block. `id` and `username` are too generic to put on a
  // global key denylist, and the SDK fills this in itself.
  if (scrubbed.user) scrubbed.user = {};

  const request = scrubbed.request as Loose | undefined;
  if (request) {
    if (request.data !== undefined) request.data = REDACTED;
    if (request.cookies !== undefined) request.cookies = REDACTED;
    if (request.query_string !== undefined) request.query_string = REDACTED;
  }

  return scrubbed;
}

/**
 * `beforeBreadcrumb`.
 *
 * The big one in the browser. Sentry records every `fetch` and every XHR, and the
 * request this page makes most often carries an answer in its body. The URL keeps
 * its path (so the failing endpoint is identifiable) and loses its query string.
 */
export function scrubBreadcrumb(crumb: Loose): Loose {
  const category = typeof crumb.category === 'string' ? crumb.category : '';

  if (category === 'fetch' || category === 'xhr') {
    const data = crumb.data as Loose | undefined;
    if (data) {
      const url = typeof data.url === 'string' ? data.url.split('?')[0] : undefined;
      crumb.data = {
        ...(data.method !== undefined ? { method: data.method } : {}),
        ...(data.status_code !== undefined ? { status_code: data.status_code } : {}),
        ...(url !== undefined ? { url: redactText(url) } : {}),
      };
    }
  }

  // Console breadcrumbs carry whatever was logged, which during an interview is the
  // answer being submitted.
  if (category === 'console' && typeof crumb.message === 'string') {
    crumb.message = redactText(crumb.message);
  }

  return scrubValue(crumb) as Loose;
}
