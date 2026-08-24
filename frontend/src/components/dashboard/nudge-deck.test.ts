/**
 * The nudge deck says only checkable things — nudge-deck.test.ts
 *
 * These cards are the one place in the product that exists to sell, which is exactly why they
 * need a guard. The failure mode is not a crash: it is a card that says "Unlock your potential"
 * to somebody who has done nothing, or that quotes ₹49 from a string literal months after the
 * price moved. Both look fine on screen and both are wrong.
 *
 * Source-text assertions because the vitest environment here is `node`, not jsdom (see
 * vitest.config.ts) — a component rendering framer-motion and next/link cannot be mounted at
 * all. What matters is checkable in the source anyway: where the numbers come from, which words
 * are absent, and whether the Tailwind classes are ones the compiler can actually see.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const DECK = readFileSync(join(__dirname, 'NudgeDeck.tsx'), 'utf8');

/** Source with comments stripped — prose about a rule is not the rule. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
}

const CODE = code(DECK);

describe('prices come from the catalogue, never from the copy', () => {
  it('reads items from the store hook', () => {
    // plans.py on the server is the single source of truth for every price. A rupee figure
    // typed into this file is a figure that goes stale silently the day pricing changes.
    expect(CODE).toMatch(/useStoreItems/);
    expect(CODE).toMatch(/price_rupees/);
  });

  it('has no hardcoded rupee amount', () => {
    // Catches ₹49, Rs 199, "199 rupees" and template literals with a bare number after the
    // symbol. The interpolated `${single.price_rupees}` form passes, which is the point.
    const hardcoded = CODE.match(/(?:₹|Rs\.?\s*)\d+/g) ?? [];
    expect(hardcoded).toEqual([]);
  });

  it('derives the per-unit saving rather than stating it', () => {
    expect(CODE).toMatch(/bundle\.price_rupees\s*\/\s*bundle\.quantity/);
  });
});

/**
 * THE COPY, AND ONLY THE COPY.
 *
 * Scanning the whole file for banned words was the first version of this and it was wrong:
 * `transition-transform` is a Tailwind utility that contains "transform", so the guard failed
 * on a CSS class while claiming the marketing copy was at fault. A rule about wording has to
 * be applied to wording — anything else is a guard that cries wolf, and a guard that cries
 * wolf gets deleted.
 */
const COPY = (DECK.match(/^\s*(?:hook|fact|cta): [\s\S]*?,$/gm) ?? []).join('\n');

describe('DESIGN-RULES compliance', () => {
  it('the scanner actually found the copy', () => {
    // Guards every assertion below from passing vacuously. If the card shape is refactored and
    // these keys are renamed, this fails loudly instead of silently checking an empty string.
    expect(COPY.length).toBeGreaterThan(200);
    expect(COPY).toMatch(/hook:/);
    expect(COPY).toMatch(/fact:/);
  });

  it('uses none of the banned marketing verbs', () => {
    // DESIGN-RULES.md bans "Supercharge / Unlock / Elevate / Transform your X with AI" by
    // name: verb-noun-AI says nothing and appears everywhere.
    for (const banned of ['Supercharge', 'Unlock', 'Elevate', 'Transform']) {
      expect(COPY).not.toMatch(new RegExp(banned, 'i'));
    }
  });

  it('uses none of the banned vague superlatives', () => {
    for (const banned of ['seamless', 'powerful', 'cutting-edge', 'world-class', 'game-chang']) {
      expect(COPY).not.toMatch(new RegExp(banned, 'i'));
    }
  });

  it('has no emoji in the copy', () => {
    // Banned in headings by the rules; banned in all of this copy because a nudge IS a heading.
    expect(COPY).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u);
  });

  it('has no rounded-up stat', () => {
    // "50+", "1000+", "10x" — the rules note we had two of these on the landing page and both
    // were false. Checked against the copy, where a real count is always interpolated.
    expect(COPY).not.toMatch(/\d+\+|\b\d+x\b/);
  });
});

describe('Tailwind classes are ones the compiler can see', () => {
  it('never interpolates a colour token into a class name', () => {
    // `bg-accent-${tone}-soft` is invisible to Tailwind's scanner. It survives dev, because the
    // JIT has already met the literal elsewhere, and silently loses its background in a
    // production build — the hardest failure to catch, since the component still renders.
    expect(CODE).not.toMatch(/(?:bg|text|border)-accent-\$\{/);
    // The eager lookup table is what replaces it.
    expect(CODE).toMatch(/const TONE: Record<Tone,/);
  });

  it('keeps min-w-0 on the scrolling items', () => {
    // A flex item defaults to min-width:auto, so it refuses to shrink below its content and the
    // overflow-x container never scrolls — the row overflows the page instead, which is how a
    // horizontal strip silently becomes a broken phone layout.
    expect(CODE).toMatch(/overflow-x-auto/);
    expect(CODE).toMatch(/min-w-0/);
  });

  it('uses -ink tones for the small text', () => {
    // Only -ink clears 4.5:1 on the warm paper ground; the bare tone on body copy measures
    // 2.9:1 and is a bug, not a style choice.
    expect(CODE).toMatch(/text-accent-\w+-ink/);
  });

  it('honours prefers-reduced-motion on the arrow', () => {
    expect(CODE).toMatch(/motion-reduce:/);
  });
});

describe('it stays silent unless something is true', () => {
  it('renders nothing before the data arrives', () => {
    expect(CODE).toMatch(/if \(!stats \|\| !activity \|\| !balance\) return null;/);
  });

  it('renders nothing when no card qualifies', () => {
    expect(CODE).toMatch(/if \(deck\.length === 0\) return null;/);
  });

  it('is not shown to unmetered operator accounts', () => {
    // An admin sees "unlimited", so a card telling them to buy an interview is nonsense.
    expect(CODE).toMatch(/balance\.unlimited/);
  });

  it('every card is gated on a real condition', () => {
    // The buy card only for somebody with none left; the unused card only for somebody with
    // some; the average card only for somebody who has actually completed an interview.
    expect(CODE).toMatch(/interviewsLeft === 0/);
    expect(CODE).toMatch(/interviewsLeft > 0/);
    expect(CODE).toMatch(/stats\.completed_sessions > 0/);
    expect(CODE).toMatch(/!done\.has\('group_discussion'\)/);
    expect(CODE).toMatch(/!done\.has\('communication'\)/);
  });

  it('a dismissal survives a reload and cannot throw', () => {
    // localStorage throws outright in private windows and with site data blocked, rather than
    // returning null. A dashboard must not die because a nudge could not read its own state.
    expect(CODE).toMatch(/localStorage\.getItem/);
    expect(CODE).toMatch(/localStorage\.setItem/);
    expect((CODE.match(/catch \{/g) ?? []).length).toBeGreaterThanOrEqual(2);
  });
});

describe('the two registers do different jobs', () => {
  it('every card has both a hook and a fact', () => {
    const hooks = (CODE.match(/^\s*hook:/gm) ?? []).length;
    const facts = (CODE.match(/^\s*fact:/gm) ?? []).length;
    expect(hooks).toBeGreaterThan(0);
    expect(facts).toBe(hooks);
  });

  it('no hook carries a number', () => {
    // The Hinglish line is allowed to be casual, so it is not allowed to make a measurable
    // claim. Numbers live in the English fact, where they can be checked.
    const hookLines = DECK.match(/^\s*hook: .*$/gm) ?? [];
    expect(hookLines.length).toBeGreaterThan(0);
    for (const line of hookLines) {
      expect(line).not.toMatch(/\d|\$\{/);
    }
  });
});
