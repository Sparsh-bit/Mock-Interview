/**
 * Deep-link parameters for the interview setup page — lib/interview/params.ts
 *
 * WHAT THIS REPLACED. This was `lib/interview/drive.ts`, which existed to build and describe a
 * one-click link to one named company's drive on one named date — a hardcoded `'24 August'`
 * label and a `Date.parse('2026-08-24T23:59:59+05:30')` deadline. The card that consumed it is
 * gone from the dashboard, and a module whose only remaining job is to name a date that has
 * already passed is worse than no module: it reads as maintained.
 *
 * What survived is the one thing that was never about that drive — the strict parse of the
 * `?isTechnical=` param, which any share link can carry.
 */

/**
 * `?isTechnical=` parsed STRICTLY against two literals.
 *
 * Anything else — absent, empty, "1", "yes", "TRUE", a typo — returns null, which is the setup
 * page's "work it out from the role" default and therefore exactly today's behaviour. A
 * malformed link degrades to a guess instead of asserting a wrong answer, and asserting the
 * wrong answer here is expensive: `isTechnical` decides whether there is a code editor at all,
 * whether coding questions are asked, and whether the panel are engineers or their own field's
 * managers. A stray "?isTechnical=false" typo'd into a share link would hand a Java FSE
 * candidate an HR round.
 *
 * STILL NOT CASE-INSENSITIVE, and now for a stronger reason than before. It used to be narrow
 * because the only writer was a link this app generated itself. That writer is gone, so every
 * value arriving here is now hand-edited or pasted — which is precisely when a broad parse is
 * dangerous rather than convenient.
 */
export function parseIsTechnical(raw: string | null): boolean | null {
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  return null;
}
