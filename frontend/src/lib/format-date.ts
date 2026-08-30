/**
 * Dates that read the same on the server and in the browser — lib/format-date.ts
 *
 * WHY THIS EXISTS. `new Date(x).toLocaleDateString()` formats using the AMBIENT locale, which
 * is Node's on the server and the browser's on the client. When those disagree — and they
 * routinely do, Node defaulting to `en-US` while an Indian browser reports `en-IN` — React
 * renders "7/20/2026" into the HTML and then "20/07/2026" on hydration, sees the text differ,
 * and throws away the entire server-rendered tree to re-render it.
 *
 * That was happening on `/demo`, which is linked from the landing page: a visible re-render on
 * one of the first pages a prospective candidate sees, reported by the dev overlay as
 * "Hydration failed because the server rendered text didn't match the client".
 *
 * It is also a correctness problem independent of hydration. With no locale pinned, the same
 * report showed `20/07/2026` to one candidate and `07/20/2026` to another depending on their
 * machine — and for the first nineteen days of a month those two are BOTH VALID READINGS of
 * the same string, so a person cannot tell which they are looking at.
 *
 * `en-IN` rather than the ambient locale: this product is built for Indian campus placement,
 * day-month-year is what its candidates read, and a fixed locale is the only kind that a
 * server and a browser can agree on.
 */

/** The locale every date in the product is formatted in. Deliberately not the browser's. */
const LOCALE = 'en-IN';

/**
 * `20 Jul 2026`.
 *
 * The month is a WORD, which removes the ambiguity entirely rather than merely making it
 * consistent — nobody misreads "20 Jul" whatever they are used to.
 */
export function formatDate(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return '—';
  return d.toLocaleDateString(LOCALE, { day: '2-digit', month: 'short', year: 'numeric' });
}

/** `20 Jul 2026, 14:05` — for lists where two rounds on one day need telling apart. */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return '—';
  return d.toLocaleString(LOCALE, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** `20 Jul` — for dense rows where the year is implied by context. */
export function formatDayMonth(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return '—';
  return d.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' });
}

/**
 * Parse defensively and return null rather than an Invalid Date.
 *
 * `new Date('nonsense')` does not throw — it produces an Invalid Date, whose
 * `toLocaleDateString()` returns the literal string "Invalid Date". Printing that to a
 * candidate is worse than printing nothing, and it is what a null or malformed timestamp from
 * the API would otherwise produce.
 */
function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}
