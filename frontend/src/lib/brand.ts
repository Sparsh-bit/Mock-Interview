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

/**
 * THE TWO HALVES OF THE WORDMARK, and the reason they are named here rather than in the nav.
 *
 * The public header sets the second half in gold - the one piece of gold above the fold that
 * is not a button, which teaches the colour before the colour is asked to mean "press this".
 * That needs the name in two pieces, and MkNav had them as two hardcoded string literals.
 *
 * WHICH REINTRODUCED EXACTLY THE BUG THIS FILE EXISTS TO PREVENT, and then shipped two more:
 *
 *   1. A rename here would have left the header still reading the old name, on the most
 *      visited surface the product has.
 *   2. The literals were `'Interview'` and `' OS'` - with a leading space - so the header
 *      rendered "Interview OS" while every other surface rendered "InterviewOS". The brand
 *      was spelled two different ways on one page.
 *   3. The first half alone was hidden below 360px, so a narrow phone got a bare gold "OS".
 *
 * `name` is composed FROM these rather than sitting beside them, so the halves cannot drift
 * out of step with the whole the way two independent literals did. Renaming is still one edit.
 */
const NAME_HEAD = 'Interview';
const NAME_TAIL = 'OS';

export const BRAND = {
  /**
   * The product name.
   *
   * Renamed three times now — InterviewOS → Mockingbird → InterviewOS → InterviewOS — and every
   * one of those was a single-line edit here, which is the entire argument for this file. It
   * was originally retyped in 33 places.
   */
  name: `${NAME_HEAD}${NAME_TAIL}`,

  /**
   * The name pre-split for the two-tone header. `head + tail === name` by construction, and
   * a test asserts it anyway so a future edit cannot quietly break the identity.
   */
  wordmark: { head: NAME_HEAD, tail: NAME_TAIL },

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
  /**
   * The operator. Who "we" is in every policy, and the entity a candidate is contracting with.
   *
   * WHY THIS IS HERE AND NOT IN THE PROSE. Every policy spoke in the first person — "we will
   * refund you", "we do not promise" — and nothing in the product said who that was. A refund
   * promise from an unnamed party is not one anybody can hold, and three separate obligations
   * land on the same fact: the Consumer Protection (E-Commerce) Rules 2020 require an
   * e-commerce entity to display its legal name; DPDP's §5 notice is given BY a Data Fiduciary
   * and has to say which; and a gateway's merchant terms assume the merchant is identifiable
   * to the payer.
   *
   * It sits beside `name` for the reason CLAUDE.md gives for `name` existing here at all: the
   * product name was written out in 33 files and has been renamed twice. A company name is the
   * same kind of fact and acquires the same problem the moment it is typed into six documents.
   *
   * DISTINCT FROM `name` ON PURPOSE. The product is what is sold; the company is who sells it.
   * Collapsing them would satisfy a "the operator is named" check while identifying nobody.
   */
  company: 'Concilio Solutions',
  supportEmail: 'interview@concilio.solutions',
} as const;

/** `InterviewOS · Dashboard` — the one place the separator is decided. */
export function pageTitle(page: string): string {
  return `${BRAND.name} · ${page}`;
}
