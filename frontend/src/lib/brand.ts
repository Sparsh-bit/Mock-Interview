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
   * NOT renamed with the product. This is a live mailbox people already write to, and a brand
   * decision must not silently break support. Move it deliberately, with a forwarding rule.
   */
  supportEmail: 'support@interviewos.app',
} as const;

/** `InterviewOS · Dashboard` — the one place the separator is decided. */
export function pageTitle(page: string): string {
  return `${BRAND.name} · ${page}`;
}
