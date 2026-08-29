import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { ROUTE_TONE, TONES, type Tone } from './tones';

/**
 * The colours mean one thing each — tones.test.ts
 *
 * The scheme's entire value is agreement: the rail entry, the page header and any card
 * pointing at a destination are the same colour, so the colour becomes a name for the place.
 * The moment two of them disagree the reader learns the colours are arbitrary, and every other
 * use of colour in the product loses its meaning at the same time. That is a worse outcome
 * than having drawn everything grey.
 *
 * Nothing in TypeScript notices that kind of drift — both sides still compile — so it is
 * pinned here.
 */

/** Every href the rail can navigate to, read out of the Sidebar's own source. */
function navHrefs(): { href: string; tone?: string }[] {
  // Read as text rather than imported: Sidebar is a client component that pulls in
  // next/navigation, framer-motion and react-query, none of which belong in a unit test —
  // and the thing under test is a table of literals, which the source states plainly.
  /*
   * SPLIT ON `href:` SO EACH CHUNK IS EXACTLY ONE ITEM, rather than scanning a fixed window
   * after each match. The first version of this looked ahead 220 characters for a `tone:`,
   * which sailed straight past the end of the untoned Profile entry and picked up the tone
   * belonging to the item after it — reporting that Profile was amber when Profile has no
   * tone at all. That is the same "window reaching a neighbour" mistake recorded in
   * docs/MISTAKES.md, re-committed by me in the test written to prevent drift.
   *
   * An item's own text ends where the next item's `href:` begins, so this cannot overrun.
   */
  const chunks = readSidebar().split(/href:\s*/).slice(1);
  return chunks.map((chunk) => {
    const href = chunk.match(/^'([^']+)'/)?.[1] ?? '';
    return { href, tone: chunk.match(/tone:\s*'(\w+)'/)?.[1] };
  });
}

function readSidebar(): string {
  return readFileSync(join(process.cwd(), 'src/components/layout/Sidebar.tsx'), 'utf8');
}

describe('the test can see what it claims to check', () => {
  it('finds the rail entries', () => {
    // A regex that stopped matching would make every assertion below pass over an empty list —
    // the exact vacuous-guard shape this repo has been caught by repeatedly.
    const hrefs = navHrefs();
    expect(hrefs.length).toBeGreaterThanOrEqual(10);
    expect(hrefs.map((h) => h.href)).toContain('/dashboard');
  });

  it('finds tones on the entries that carry them', () => {
    expect(navHrefs().filter((h) => h.tone).length).toBeGreaterThanOrEqual(8);
  });
});

describe('the rail and the page headers agree', () => {
  it('every toned rail entry has the same tone in ROUTE_TONE', () => {
    for (const { href, tone } of navHrefs()) {
      if (!tone) continue;
      expect(ROUTE_TONE[href], `${href} is ${tone} in the rail`).toBe(tone);
    }
  });

  it('every ROUTE_TONE entry names a real tone', () => {
    // A typo'd tone resolves to undefined and the header silently loses its colour — no error,
    // no failed build, just a page that quietly stopped matching the rest of the product.
    for (const [route, tone] of Object.entries(ROUTE_TONE)) {
      expect(Object.keys(TONES), `${route} → ${tone}`).toContain(tone);
    }
  });

  it('leaves Profile and Settings uncoloured', () => {
    // Not an oversight. They are the account rather than a round, and there are only six
    // colours to spend; giving them one would put them on the same footing as the features.
    expect(ROUTE_TONE['/profile']).toBeUndefined();
    expect(ROUTE_TONE['/settings']).toBeUndefined();
  });
});

describe('the tone classes are usable as written', () => {
  it('never builds a class name by interpolation', () => {
    /*
     * THE ONE THAT ACTUALLY BREAKS IN PRODUCTION AND NOWHERE ELSE. Tailwind compiles the
     * classes it can literally see; `bg-accent-${tone}-soft` is assembled at runtime, so the
     * class never enters the stylesheet. It usually still works in dev because the JIT has
     * seen the class elsewhere on the page, then the colour vanishes from the production
     * build with no error anywhere.
     */
    /*
     * COMMENTS STRIPPED FIRST. Without that, this guard failed on the comment at the top of
     * Sidebar.tsx that warns against interpolating a tone — the file explaining the rule was
     * read as breaking it. An assertion that fails on correct code trains you to "fix" things
     * that were already right, which is worse than no assertion.
     */
    const code = readSidebar()
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/.*$/gm, '');
    expect(code).not.toMatch(/(?:bg|text|border|ring)-accent-\$\{/);
  });

  it('gives every tone the full set of roles', () => {
    const roles = ['icon', 'activeBg', 'activeText', 'rail', 'soft', 'ink', 'border', 'ring'];
    for (const [name, tone] of Object.entries(TONES)) {
      for (const role of roles) {
        expect(Object.keys(tone), `${name} is missing ${role}`).toContain(role);
      }
    }
  });

  it('uses the -ink tone wherever the class sets text colour', () => {
    // DESIGN-RULES: `-ink` is the only tone that clears 4.5:1 for small text. `text-accent-amber`
    // on body copy measures 2.9:1 — it is a bug, not a style choice, and it is an easy one to
    // introduce by copying a `rail` value into a text slot.
    for (const [name, tone] of Object.entries(TONES) as [Tone, (typeof TONES)[Tone]][]) {
      expect(tone.icon, name).toMatch(/-ink$/);
      expect(tone.activeText, name).toMatch(/-ink$/);
      expect(tone.ink, name).toMatch(/-ink$/);
    }
  });
});
