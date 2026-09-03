import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { BRAND } from '@/lib/brand';
import { POLICIES } from '@/lib/legal/policies';

/**
 * The policies must say who "we" is — lib/legal/operator.test.ts
 *
 * THE GAP THIS CLOSES, and it is substantive rather than cosmetic. Every policy spoke in the
 * first person — "we will refund you", "we do not promise", "tell us and tell your bank" —
 * and no document anywhere in the product identified who that was. A refund promise from an
 * unnamed party is not a promise anybody can hold.
 *
 * Three separate obligations land on the same fact:
 *
 *   * India's Consumer Protection (E-Commerce) Rules 2020 require an e-commerce entity to
 *     display its legal name and contact details.
 *   * DPDP's §5 notice is given BY a Data Fiduciary; the notice has to say which one.
 *   * A payment gateway's merchant terms assume the merchant is identifiable to the payer,
 *     and the refund policy names Razorpay as the route.
 *
 * WHY IT LIVES IN `BRAND` AND NOT IN THE PROSE. CLAUDE.md's rule is that the product name is
 * written in exactly one place because it has already been renamed twice; a company name is
 * the same kind of fact and acquires the same problem the moment it is typed into six
 * documents. `legal-pages.test.ts` already forbids retyping the PRODUCT name in policy prose
 * for that reason — this extends the same discipline to the operator.
 *
 * WHAT IS DELIBERATELY NOT ASSERTED HERE: a registered address or a company identifier. Those
 * are facts only the operator can supply, and inventing a plausible one would be worse than
 * leaving the gap visible — the same argument docs/COMPLIANCE.md makes about the grievance
 * officer. When they are known they belong in `BRAND` beside the name.
 */

describe('the operator is named in the single source', () => {
  it('BRAND carries a company', () => {
    expect(BRAND.company).toBeTruthy();
    expect(typeof BRAND.company).toBe('string');
  });

  it('the company is not the product name', () => {
    // THE VACUITY GUARD. Defaulting the company to the product name would satisfy every
    // assertion below while identifying nobody — the product is what is sold, the company is
    // who sells it, and a policy needs the second.
    expect(BRAND.company).not.toBe(BRAND.name);
  });

  it('the support address belongs to the company domain', () => {
    // A contact on an unrelated domain undercuts the identification it is supposed to support.
    const domain = BRAND.supportEmail.split('@')[1] ?? '';
    const firstWord = BRAND.company.split(/\s+/)[0].toLowerCase();
    expect(domain.toLowerCase()).toContain(firstWord);
  });
});

describe('every policy identifies who is providing the service', () => {
  it.each(Object.entries(POLICIES))('%s names the operator', (_slug, policy) => {
    const text = policy.sections.flatMap((s) => s.body).join(' ');
    expect(text).toContain(BRAND.company);
  });

  it.each(Object.entries(POLICIES))('%s still reaches its contact address', (_slug, policy) => {
    const text = policy.sections.flatMap((s) => s.body).join(' ');
    expect(text).toContain(BRAND.supportEmail);
  });
});

describe('the operator is stated once, not scattered', () => {
  it('no policy retypes the company as a literal', () => {
    /*
     * The same rule legal-pages.test.ts applies to the product name. The company must be
     * interpolated from BRAND, so a rename is one edit — this reads the module source rather
     * than the rendered strings, because the rendered strings are exactly what interpolation
     * produces and would pass either way.
     *
     * Resolved from import.meta.url rather than the cwd, so the test does not depend on which
     * directory vitest was launched from.
     */
    const source = readFileSync(new URL('./policies.ts', import.meta.url), 'utf8');
    const literal = BRAND.company;
    expect(source.includes(`'${literal}'`)).toBe(false);
    expect(source.includes(`"${literal}"`)).toBe(false);
  });
});

describe('naming the operator cannot take a legal page down', () => {
  /*
   * Source assertions rather than a rendered tree, matching consent.test.ts: the rule is that
   * something is ABSENT - an unguarded read - and rendering the happy path proves nothing
   * about the payload shape that arrives during a deploy.
   */
  const body = readFileSync(
    new URL('../../components/legal/DisclosureBody.tsx', import.meta.url),
    'utf8',
  );

  it('the fiduciary is rendered behind a guard', () => {
    /*
     * The frontend and the backend deploy independently, so for the minutes between one
     * shipping and the other a new frontend can be talking to a backend that predates the
     * `fiduciary` field. `DisclosureBody` destructures it and reads `.name`; unguarded, that
     * is a TypeError, and this component renders the /privacy page and the pre-upload consent
     * sheet - a 500 on the document that explains how to exercise a data right.
     */
    expect(body).toMatch(/\{fiduciary && \(/);
  });

  it('the type marks it optional, so the guard cannot be removed as dead code', () => {
    const shape = readFileSync(new URL('./disclosure.ts', import.meta.url), 'utf8');
    expect(shape).toContain('fiduciary?:');
  });

  it('the backend still always sends it', () => {
    // The field is optional to the RENDERER only. If the payload stopped carrying it, the
    // section would silently vanish rather than fail, so the backend keeps its own test.
    const server = readFileSync(
      new URL('../../../../backend/app/services/legal/disclosure.py', import.meta.url),
      'utf8',
    );
    expect(server).toContain('"fiduciary": _fiduciary_block()');
  });
});
