import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { BRAND } from '@/lib/brand';

/**
 * The brand is spelled one way - lib/brand-is-spelled-one-way.test.ts
 *
 * WHAT WENT WRONG, and why a test rather than a careful edit. The public site sets the second
 * half of the product name in gold, which needs the name in two pieces. Those pieces were
 * written out inline on four surfaces - the header pill, the mobile drawer, the marketing
 * footer and the welcome wizard - and every copy carried `' OS'` with a LEADING SPACE. So the
 * four highest-traffic surfaces in the product rendered "Interview OS" while every other
 * surface rendered "InterviewOS", and a fifth copy hid only the FIRST half below 360px, which
 * left a narrow phone showing a bare gold "OS" and no product name at all.
 *
 * None of that is catchable by reading one file, which is the argument for reading all of them.
 */

const SOURCES = [
  'src/components/marketing/MkNav.tsx',
  'src/components/marketing/MkFooter.tsx',
  'src/app/welcome/page.tsx',
  'src/components/layout/SiteFooter.tsx',
] as const;

const read = (rel: string) => readFileSync(new URL(`../../${rel}`, import.meta.url), 'utf8');

describe('the wordmark halves compose the name exactly', () => {
  it('head + tail is the name, with no space introduced', () => {
    expect(`${BRAND.wordmark.head}${BRAND.wordmark.tail}`).toBe(BRAND.name);
  });

  it('neither half is padded', () => {
    for (const half of [BRAND.wordmark.head, BRAND.wordmark.tail]) {
      expect(half).toBe(half.trim());
      expect(half.length).toBeGreaterThan(0);
    }
  });

  it('the name has no internal space, so a split half can never add one', () => {
    expect(BRAND.name).not.toMatch(/\s/);
  });
});

describe('no surface retypes the name', () => {
  it.each(SOURCES)('%s builds the wordmark from BRAND', (rel) => {
    const source = read(rel);
    // The exact shape of the old bug: the first half as a literal next to a gold span.
    expect(source).not.toMatch(
      new RegExp(`${BRAND.wordmark.head}<span[^>]*--mk-gold`),
    );
    // And the general case: either half quoted as a string literal.
    for (const half of [BRAND.wordmark.head, BRAND.wordmark.tail]) {
      expect(source.includes(`'${half}'`)).toBe(false);
      expect(source.includes(`">${half}<`)).toBe(false);
    }
  });

  it('the gold half is only ever painted by the shared component', () => {
    // If a fifth surface hand-rolls the two-tone name, it will reference the gold token
    // beside the wordmark again. Only Brandmark.tsx is allowed to.
    const owner = read('src/components/brand/Brandmark.tsx');
    expect(owner).toContain('BRAND.wordmark.tail');
    for (const rel of SOURCES) {
      expect(read(rel)).not.toContain('BRAND.wordmark.tail');
    }
  });
});

describe('the narrow-viewport wordmark is all-or-nothing', () => {
  it('MkNav never hides one half of the name on its own', () => {
    const nav = read('src/components/marketing/MkNav.tsx');
    /*
     * `hidden ... min-[360px]:inline` must sit on the element that wraps the WHOLE name. If it
     * lands on a half again, that half's sibling survives alone - which is how a phone came to
     * show a gold "OS" with nothing in front of it.
     */
    const halfHidden = /hidden[^"']*min-\[360px\]:inline[^"']*"[^>]*>\s*\{BRAND\.wordmark\.(head|tail)\}/;
    expect(nav).not.toMatch(halfHidden);
    expect(nav).toContain('min-[360px]:inline');
  });
});

describe('the footers name the operator and reach a real mailbox', () => {
  it.each(['src/components/layout/SiteFooter.tsx', 'src/components/marketing/MkFooter.tsx'])(
    '%s puts the company in the copyright line',
    (rel) => {
      expect(read(rel)).toContain('BRAND.company');
    },
  );

  it('no personal address is shipped as the contact', () => {
    /*
     * SiteFooter carried a hardcoded personal Gmail, and it renders on all four legal pages -
     * so the page explaining how to raise a grievance handed over somebody's personal inbox.
     * Any free-mail provider in a footer is the same mistake.
     */
    const freemail = /@(gmail|googlemail|yahoo|hotmail|outlook|proton(mail)?|icloud)\./i;
    for (const rel of [...SOURCES, 'src/components/brand/Brandmark.tsx']) {
      expect(read(rel)).not.toMatch(freemail);
    }
  });

  it('the support address belongs to the operator', () => {
    const domain = BRAND.supportEmail.split('@')[1] ?? '';
    const slug = BRAND.company.split(/\s+/)[0]?.toLowerCase() ?? '';
    expect(domain).toContain(slug);
  });
});
