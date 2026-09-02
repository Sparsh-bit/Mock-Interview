import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { POLICIES, REFUND, TERMS, type Policy } from '@/lib/legal/policies';

/**
 * Terms, refunds and the grievance contact — legal-pages.test.ts
 *
 * WHAT WAS MISSING. `/privacy` existed and was good: server-rendered from the backend's own
 * configuration so the processor list cannot drift, marked draft, and carrying the DPDP
 * §8(9)–(10) grievance contact. Three things that sit beside it did not exist at all —
 * Terms of Service, a Refund and Cancellation policy, and a page a person can be sent to
 * when they want to complain.
 *
 * That is not only a legal gap. Razorpay's own merchant onboarding expects a live site to
 * publish terms, a refund/cancellation policy, a privacy policy and a contact route, so the
 * absence is also a thing that blocks taking money.
 *
 * THE THREE PROPERTIES THESE TESTS EXIST TO HOLD.
 *
 *   ONE CONTACT, NOT TWO. The grievance officer named on /grievance must be the SAME one
 *   named on /privacy, and both must come from the backend's settings rather than being
 *   typed into a page. Two published contacts is worse than one, because a person picks the
 *   wrong one and concludes nobody answered.
 *
 *   NO ORPHANS. A policy page nothing links to is a policy page that does not exist for the
 *   person it is written for. Every one has to be reachable from the footer and from the
 *   signed-in account area.
 *
 *   THE REFUND POLICY HAS TO MATCH THE CODE. There is no refund endpoint, no refund model
 *   and no Razorpay refund call anywhere in this repository — refunds are a human action in
 *   Razorpay's dashboard. A policy promising automatic or self-service refunds would be a
 *   statement a paying customer relied on and the system cannot honour, which is the same
 *   failure mode as a privacy notice naming the wrong country.
 */

const APP = join(process.cwd(), 'src', 'app');
const read = (p: string) => readFileSync(join(process.cwd(), 'src', p), 'utf8');

const LEGAL_ROUTES = ['privacy', 'terms', 'refund', 'grievance'] as const;

describe('the legal pages exist', () => {
  for (const route of LEGAL_ROUTES) {
    it(`/${route} is a real page`, () => {
      expect(existsSync(join(APP, route, 'page.tsx'))).toBe(true);
    });
  }

  it('each declares page metadata so it is not an untitled tab', () => {
    for (const route of LEGAL_ROUTES) {
      const src = read(join('app', route, 'page.tsx'));
      expect(src, `/${route} has no metadata`).toMatch(/export const metadata/);
    }
  });
});

describe('nothing is an orphan', () => {
  const footer = read('components/layout/SiteFooter.tsx');

  for (const route of LEGAL_ROUTES) {
    it(`/${route} is linked from the site footer`, () => {
      expect(footer).toContain(`/${route}`);
    });
  }

  it('the footer is actually rendered on the pages a signed-out visitor sees', () => {
    /*
     * A footer component nobody mounts is the orphan problem one level up.
     *
     * THERE ARE NOW TWO FOOTERS and both are acceptable here: `SiteFooter` is the product's
     * (pricing, the legal pages, a shared report) and `MkFooter` is the public site's, which
     * the landing page renders because a four-column site map is right there and absurd on a
     * legal page. What is NOT acceptable is a signed-out page with neither.
     *
     * The second assertion is the one that keeps this test honest. Accepting either component
     * would otherwise weaken the guarantee to "some footer exists", and a marketing footer
     * with its own hand-typed list of legal routes is exactly the orphan this file exists to
     * prevent — four links that nothing checks. So MkFooter has to take the list from
     * SiteFooter's `LEGAL_LINKS`, which is the declaration the loop above verifies.
     */
    for (const page of ['app/page.tsx', 'app/pricing/page.tsx']) {
      expect(read(page), `${page} renders no footer at all`).toMatch(/SiteFooter|MkFooter/);
    }

    expect(
      read('components/marketing/MkFooter.tsx'),
      'MkFooter declares its own legal links instead of importing LEGAL_LINKS from SiteFooter',
    ).toMatch(/import \{[^}]*\bLEGAL_LINKS\b[^}]*\} from '@\/components\/layout\/SiteFooter'/);
  });

  it('every legal page links to the others, so none is a dead end', () => {
    /*
     * Somebody who has read the privacy notice to the end is the person most likely to want
     * the complaints route. That page previously had no way out of it at all.
     */
    for (const route of LEGAL_ROUTES) {
      const src = read(join('app', route, 'page.tsx'));
      for (const other of LEGAL_ROUTES) {
        expect(src, `/${route} does not link /${other}`).toContain(`"/${other}"`);
      }
    }
  });

  it('the signed-in account area links them too', () => {
    /*
     * The footer is a landing-page thing; somebody who is already paying lives inside the
     * dashboard and never scrolls past a marketing page again. Settings is where they look
     * for "how do I get my money back".
     */
    const settings = read('app/(dashboard)/settings/page.tsx');
    for (const route of LEGAL_ROUTES) {
      expect(settings, `settings does not link /${route}`).toContain(`/${route}`);
    }
  });
});

describe('there is exactly one grievance contact', () => {
  it('the grievance page takes its contact from the backend, not from a literal', () => {
    const src = read('app/grievance/page.tsx');
    // The same public endpoint /privacy reads. One source, so the two can never disagree.
    expect(src).toContain('/api/v1/legal/disclosure');
  });

  it('no legal page hardcodes an email address', () => {
    /*
     * THE FAILURE THIS PREVENTS. A second address typed into a page is a second inbox, and
     * a person who writes to the stale one concludes nobody answered. The support address is
     * `BRAND.supportEmail`, and it HAS now moved once (to `interview@concilio.solutions`),
     * which is the case this rule was written for: one line changed and every page followed,
     * because no page had retyped it. Note the support mailbox is not what these pages show
     * anyway — the DPDP contact comes from the backend — so a literal here would be wrong
     * twice over.
     */
    const offenders: string[] = [];
    for (const route of LEGAL_ROUTES) {
      const src = read(join('app', route, 'page.tsx'));
      const emails = src.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g) ?? [];
      for (const email of emails) offenders.push(`/${route}: ${email}`);
    }
    expect(offenders, 'legal pages must render the configured contact, never a literal').toEqual(
      [],
    );
  });

  it('the shared body renders the configured contact and says so when it is unset', () => {
    const body = read('components/legal/DisclosureBody.tsx');
    expect(body).toContain('grievance.configured');
  });
});

describe('the policies say what the system actually does', () => {
  /*
   * ASSERTED ON THE DATA, NOT THE SOURCE TEXT. The first version of this read the file and
   * matched against its own module docstring — which explains what the policy must not say,
   * and therefore contains the forbidden phrase. Reading the exported objects checks the
   * words a candidate will actually be shown, which is the thing that matters.
   */
  const prose = (policy: Policy) =>
    [
      policy.title,
      policy.summary,
      ...policy.sections.flatMap((s) => [s.heading, ...s.body]),
      ...policy.needsLegalReview,
    ].join('\n');

  it('every policy is marked as draft pending legal review', () => {
    /*
     * The same rule the DPDP work already follows: shipped wording states facts an engineer
     * verified, and does not pretend to be a lawyer-reviewed instrument. Marked in the DATA
     * so the page cannot render the text without the caveat.
     */
    for (const policy of Object.values(POLICIES)) {
      expect(policy.draft, `${policy.slug} is not marked draft`).toBe(true);
      expect(policy.needsLegalReview.length).toBeGreaterThan(0);
    }
  });

  it('the refund policy does not promise a self-service refund', () => {
    /*
     * There is no refund endpoint, no refund model and no Razorpay refund call in this
     * repository — refunds are a human action in Razorpay's dashboard. Promising a button
     * that does not exist is the exact shape of the stale trial-allowance note CLAUDE.md
     * warns about: a document describing a more generous product than the code delivers.
     */
    const text = prose(REFUND).toLowerCase();
    expect(text).not.toMatch(/instant refund|automatic refund|refund button|self-service refund/);
    // It must instead say plainly that a person does it, and route them there.
    expect(text).toMatch(/by hand|manually/);
    expect(text).toMatch(/grievance/);
  });

  it('the refund policy names a response window', () => {
    // "We will look at it" with no clock is not a policy.
    expect(prose(REFUND)).toMatch(/\d+\s*business\s*days/i);
  });

  it('the refund policy is honest that there is no subscription to cancel', () => {
    // plans.py opens by saying this product removed subscriptions on purpose, and
    // test_autopay_mandate_compliance.py proves auto top-up cannot charge anybody. A
    // cancellation policy implying a recurring charge exists would contradict both.
    expect(prose(REFUND).toLowerCase()).toMatch(/no subscription|nothing renews/);
  });

  it('the terms disclaim the assessment the way the product does elsewhere', () => {
    /*
     * A report can affect a real hiring decision. The terms must not imply the score is a
     * certified evaluation — the same claim the score surfaces make, and the two must not
     * contradict each other.
     */
    const text = prose(TERMS).toLowerCase();
    expect(text).toMatch(/not a certified/);
    expect(text).toMatch(/generated by an ai|ai language model/);
    expect(text).toMatch(/no guarantee|give no guarantee/);
  });

  it('the terms point at a human review path', () => {
    // Must agree with the dispute route, or the terms promise something that does not exist.
    expect(prose(TERMS).toLowerCase()).toMatch(/reviewed by a person|human review/);
  });

  it('the policies never retype the product name', () => {
    // CLAUDE.md: the name lives in lib/brand.ts and has been renamed twice.
    for (const policy of Object.values(POLICIES)) {
      expect(prose(policy)).not.toMatch(/Hotseat|InterviewOS|Mockingbird/);
    }
  });
});
