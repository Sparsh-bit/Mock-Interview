/**
 * The brand, in one place — lib/brand.ts
 *
 * The name was previously written out as a string literal in 33 files: page titles, the
 * Razorpay checkout modal, the share sheet, four auth screens, the receipt, the public report.
 * Renaming meant finding all 33, and missing one meant a candidate paying a company whose name
 * did not match the site they were on — which is exactly the moment a person abandons a
 * payment. It has since been renamed twice, and both times this file was the only edit.
 *
 * So it lives here. Import it; never retype it.
 *
 * WHY "HOTSEAT". It does not name the preparation — it names the CHAIR. The product exists
 * because of a specific feeling: two strangers, one room, and every gap in what you know about
 * to be found in the next twenty minutes. Naming the fear and then making it practisable is a
 * stronger promise than any word about AI, and it earns the interviewer personas instead of
 * apologising for them. "Take the hotseat" is already an instruction, which is a rare thing to
 * get free from a name.
 *
 * It also gives the interface a spine — see docs/DESIGN-LANGUAGE.md. A hotseat is LIT: there
 * is a light on the person in it and everything else in the room is dim. That is a hierarchy
 * rule, not a mood, and it is what stops every page being a stack of identical white cards.
 */

export const BRAND = {
  /** The product name. Sentence case everywhere — never HOTSEAT, never hotSeat. */
  name: 'Hotseat',

  /**
   * What it says under the name. Deliberately about the chair rather than about AI —
   * "AI-powered" describes how it was built, which is our problem, not the candidate's.
   */
  tagline: 'Sit in it before it counts',

  /** The longer line, for meta descriptions and the first run. */
  promise:
    'Take the seat, face a panel that asks what the real one will ask, and find out what they would have said about you — while it still costs you nothing.',

  /**
   * NOT renamed with the product. This is a live mailbox people already write to, and a brand
   * decision must not silently break support. Move it deliberately, with a forwarding rule.
   */
  supportEmail: 'support@interviewos.app',
} as const;

/** `Hotseat · Dashboard` — the one place the separator is decided. */
export function pageTitle(page: string): string {
  return `${BRAND.name} · ${page}`;
}
