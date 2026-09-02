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
 * THE NAME IS BACK TO "INTERVIEWOS", AND THE LOGO IS NOT. That combination is deliberate and
 * worth stating, because the two look inconsistent if you only read one of them.
 *
 * The mark is a chair with a flame in it. It was drawn while the product was called InterviewOS and
 * it survives the rename intact, because what it depicts — the seat, and the heat of being in
 * it — is true of an interview simulator whatever the simulator is called. The design language
 * built on it (docs/DESIGN-LANGUAGE.md: one lit element per page, heat means difficulty) is
 * about the CHAIR, not about the word, so none of it moves either.
 *
 * The one thing that could not survive is the text-bearing lockup artwork, which has "InterviewOS"
 * in its pixels. `<Lockup>` therefore composes the artwork mark with the name as LIVE TEXT —
 * see components/brand/Brandmark.tsx. A name in an image is a name that cannot be renamed.
 */

export const BRAND = {
  /**
   * The product name.
   *
   * Renamed three times now — InterviewOS → Mockingbird → InterviewOS → InterviewOS — and every
   * one of those was a single-line edit here, which is the entire argument for this file. It
   * was originally retyped in 33 places.
   */
  name: 'InterviewOS',

  /**
   * What it says under the name. Deliberately about the chair rather than about AI —
   * "AI-powered" describes how it was built, which is our problem, not the candidate's.
   */
  tagline: 'Sit in it before it counts',

  /** The longer line, for meta descriptions and the first run. */
  promise:
    'Take the seat, face a panel that asks what the real one will ask, and find out what they would have said about you — while it still costs you nothing.',

  /**
   * MOVED DELIBERATELY, and the old address is not dead. This was `support@interviewos.app`,
   * kept through two product renames on the rule that a live mailbox outlives a brand
   * decision. That rule still holds — this is not a rename following the product, it is a
   * move to a different domain that is actually read.
   *
   * WHICH MEANS THE OLD MAILBOX STILL HAS TO WORK. Changing this line only changes what new
   * visitors are shown; everyone who already has the old address in their sent items, and
   * every page cached or indexed with it, still writes to `support@interviewos.app`. Put a
   * forwarding rule on it before this ships and leave the rule in place indefinitely — a
   * bounce from a support address reads as "this company is gone", which is worse than the
   * inconsistency it fixes.
   *
   * This is NOT the DPDP §8(9)–(10) grievance contact. That is a named human, configured
   * server-side via `DPO_EMAIL`, served from `/api/v1/legal/disclosure`, and deliberately
   * empty until somebody is actually appointed. A role mailbox does not satisfy the statute,
   * so do not point the legal pages here.
   */
  supportEmail: 'interview@concilio.solutions',
} as const;

/** `InterviewOS · Dashboard` — the one place the separator is decided. */
export function pageTitle(page: string): string {
  return `${BRAND.name} · ${page}`;
}
