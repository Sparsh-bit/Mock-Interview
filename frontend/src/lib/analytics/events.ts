/**
 * The event catalogue — lib/analytics/events.ts
 *
 * A CLOSED SET, AND THAT IS THE PII CONTROL. Every other approach to "don't send personal
 * data to the analytics vendor" is a rule somebody has to remember at each call site, and
 * the failure mode is silent: the event ships, the vendor stores it, and nobody finds out
 * until a subject access request or a regulator asks what was sent.
 *
 * Here, an event name that is not in `EVENTS` does not typecheck, and a property key that is
 * not in that event's allowlist is DROPPED at runtime by `scrubProperties` even if it
 * typechecks. Both halves are needed: the type stops the mistake at the keyboard, and the
 * runtime scrub stops it when the value arrives from somewhere the types cannot see — an
 * API response spread into a property bag is the usual way.
 *
 * WHAT MUST NEVER LEAVE, restated so the reason is attached rather than assumed:
 *
 *   resume text          the single most sensitive thing this product holds
 *   answers, transcripts what a candidate said under pressure, verbatim
 *   scores and feedback  a judgement about a named person's employability
 *   emails and names     the identity itself
 *   free text of any kind because you cannot know in advance what somebody typed into it
 *
 * WHAT DOES LEAVE: a pseudonymous account id as the distinct id, and the counts, ids and
 * booleans below. Nothing here is free text, and nothing here is a measurement OF the
 * candidate — these events say what happened in the product, not how well anybody did.
 */

/**
 * Every event this product may send. Adding one is a deliberate act with a review attached.
 *
 * SIX EVENTS, NOT SIXTY. The brief is a funnel — signup, first resume, first interview
 * started and completed, purchase, repeat purchase — and a funnel is answered by a handful
 * of named events. Autocapture would answer it too and would sweep up every click's text
 * along the way, which in this product includes answers and question text; it is switched
 * off in the sink for that reason and this catalogue is what replaces it.
 */
export const EVENTS = {
  SIGNUP: 'signup',
  RESUME_UPLOADED: 'resume_uploaded',
  INTERVIEW_STARTED: 'interview_started',
  INTERVIEW_COMPLETED: 'interview_completed',
  PURCHASE: 'purchase',
} as const;

export type EventName = (typeof EVENTS)[keyof typeof EVENTS];

/** The only value shapes an event property may hold. No objects, no arrays, no free text. */
export type PropertyValue = string | number | boolean;
export type Properties = Record<string, PropertyValue>;

/**
 * Which property keys each event is allowed to carry. Anything else is dropped.
 *
 * `is_first` RATHER THAN A SEPARATE `first_interview_started` EVENT. The brief asks for
 * "first interview started" and "purchase, repeat purchase" as distinct things to measure,
 * and a boolean on one event answers that in a funnel exactly as well as two event names
 * would — while keeping the catalogue small enough that a reader can hold all of it. Two
 * names also drift: the day somebody instruments a third case, "first" and "repeat" stop
 * covering the space and the query silently misses rows.
 */
export const ALLOWED_PROPERTIES: Record<EventName, readonly string[]> = {
  [EVENTS.SIGNUP]: [],
  [EVENTS.RESUME_UPLOADED]: ['is_first'],
  [EVENTS.INTERVIEW_STARTED]: ['is_first'],
  [EVENTS.INTERVIEW_COMPLETED]: ['is_first'],
  // `item_id` and `feature` are catalogue identifiers from plans.py, not user data.
  // `price_paise` is what the server charged, in the unit it charges in.
  [EVENTS.PURCHASE]: ['item_id', 'feature', 'quantity', 'price_paise', 'is_repeat'],
};

/**
 * Property keys that may never be sent, whatever the allowlist says.
 *
 * BELT AND BRACES OVER THE ALLOWLIST, and not redundant with it. The allowlist is per-event
 * and somebody adding an event writes its own allowlist — at which point the allowlist
 * protects nothing against the person adding it. This list is the standing rule that a new
 * event's author has to argue with, and `no-pii.test.ts` fails the build if a new allowlist
 * entry matches it.
 *
 * Matched as a SUBSTRING, case-insensitively, so `candidate_email`, `emailHash` and
 * `user_email_domain` are all caught by `email`. A hash of an email is still derived from
 * one, and a domain still narrows a person to an institution.
 */
export const FORBIDDEN_PROPERTY_SUBSTRINGS: readonly string[] = [
  'email',
  'name',
  'resume',
  'transcript',
  'answer',
  'question',
  'text',
  'content',
  'token',
  'phone',
  'address',
  'dob',
  'birth',
  'score',
  'feedback',
  'password',
  'secret',
  'company',
  'college',
  'university',
];

/** True when this key must never be sent, whatever else says otherwise. */
export function isForbiddenKey(key: string): boolean {
  const lower = key.toLowerCase();
  return FORBIDDEN_PROPERTY_SUBSTRINGS.some((banned) => lower.includes(banned));
}

/**
 * The properties that may actually be sent for this event.
 *
 * Drops rather than throws. A thrown error here would take down the surface that fired the
 * event — a candidate's interview would fail because an analytics property was misnamed —
 * and analytics must never be able to do that. The drop is silent in production and visible
 * in the returned object, which is what the tests assert on.
 */
export function scrubProperties(event: EventName, properties: Properties = {}): Properties {
  const allowed = ALLOWED_PROPERTIES[event] ?? [];
  const out: Properties = {};
  for (const [key, value] of Object.entries(properties)) {
    if (isForbiddenKey(key)) continue;
    if (!allowed.includes(key)) continue;
    if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') {
      continue;
    }
    out[key] = value;
  }
  return out;
}
