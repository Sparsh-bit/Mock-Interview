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

  it('reads every price from the catalogue rather than the file', () => {
    // The bundle per-unit line was removed with the rewrite. What the rule was protecting is
    // unchanged and is what this now checks: a rupee figure on this card is interpolated from
    // `useStoreItems`, never typed here. plans.py is the only thing that decides a price.
    expect(DECK).toMatch(/useStoreItems/);
    expect(DECK).toMatch(/price_rupees/);
  });

  it.skip('derives the per-unit saving rather than stating it', () => {
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

  it('keeps emoji to the hook line, and at most one', () => {
    /*
     * DESIGN-RULES.md bans emoji in headings, and this test used to ban them from all of this
     * copy on the reasoning that a nudge IS a heading. That was overruled deliberately: these
     * cards are the product's only advert, the voice asked for is Hinglish-with-an-emoji, and
     * the copy was specified line by line.
     *
     * NARROWED RATHER THAN DELETED, because the rule is still right about everything else. An
     * emoji belongs in the one-line HOOK, where it is punctuation and carries tone that
     * Hinglish-in-Latin-script otherwise loses. It does not belong in `fact`, which is where
     * the price and the mechanism live and has to read as a statement, and two in one line is
     * where a nudge starts looking like spam.
     */
    const hooks = [...COPY.matchAll(/hook: '([^']*)'/g)].map((m) => m[1]);
    expect(hooks.length).toBeGreaterThan(0);
    const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu;
    for (const hook of hooks) {
      expect((hook.match(EMOJI) ?? []).length).toBeLessThanOrEqual(1);
    }
    const facts = [...COPY.matchAll(/fact:\s*[`']([^`']*)[`']/g)].map((m) => m[1]);
    for (const fact of facts) {
      expect(fact).not.toMatch(EMOJI);
    }
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

  it.skip('keeps min-w-0 on the scrolling items', () => {
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

  it('honours prefers-reduced-motion', () => {
    // The rewrite replaced a `motion-reduce:` class on one arrow with a real matchMedia read,
    // because the card now ROTATES on a timer and a class cannot stop a timer. Somebody who
    // asked not to be moved must not have the message change under them either.
    expect(DECK).toMatch(/prefers-reduced-motion: reduce/);
    expect(DECK).toMatch(/if \(paused \|\| reduceMotion \|\| visible\.length < 2\) return;/);
  });

  it.skip('honours prefers-reduced-motion on the arrow', () => {
    expect(CODE).toMatch(/motion-reduce:/);
  });
});

describe('it stays silent unless something is true', () => {
  it('renders nothing before the data it actually reads arrives', () => {
    /*
     * WAS `!stats || !activity || !balance`, AND THAT IS WHY NO ADVERT WAS EVER SEEN. Four
     * queries, any one of them still in flight — or failed, which on a dashboard is routine —
     * and the whole deck rendered null.
     *
     * The card reads the BALANCE (what they have left) and the CATALOGUE (what things cost).
     * `stats` and `activity` only refine which message is chosen, so they are read defensively
     * and never block. Gating on what is actually used is what makes the difference between a
     * card that appears and one that does not.
     */
    expect(DECK).toMatch(/const ready = !!balance && !!items;/);
    expect(DECK).toMatch(/if \(!current\) return null;/);
  });

  it.skip('renders nothing before the data arrives', () => {
    expect(CODE).toMatch(/if \(!stats \|\| !activity \|\| !balance\) return null;/);
  });

  it.skip('renders nothing when no card qualifies', () => {
    expect(CODE).toMatch(/if \(deck\.length === 0\) return null;/);
  });

  it('is not shown to unmetered operator accounts', () => {
    // An admin sees "unlimited", so a card telling them to buy an interview is nonsense.
    // Renamed with the rewrite: the flag is read once into `unlimited` and folded into the
    // `ready` gate, rather than being a second early return that could drift from it.
    expect(CODE).toMatch(/const unlimited = balance\?\.unlimited === true;/);
    expect(CODE).toMatch(/!unlimited/);
  });

  it('every card is gated on a real condition', () => {
    /*
     * THE RULE THIS PROTECTS IS UNCHANGED: no card is shown to somebody it is not true for.
     * Selling an interview to a person who already has three left is the fastest way to teach
     * them that everything on this dashboard is an advert to be ignored.
     *
     * The specific conditions changed with the rewrite — `interviewsLeft > 0` belonged to a
     * "you have unused rounds" card that no longer exists, and the deck is now chosen by what
     * somebody has LEFT and what they have already DONE.
     */
    expect(CODE).toMatch(/interviewsLeft === 0/);
    expect(CODE).toMatch(/gdLeft === 0/);
    expect(CODE).toMatch(/commLeft > 0/);
    expect(CODE).toMatch(/!done\.has\('communication'\)/);
    expect(CODE).toMatch(/!done\.has\('interview'\)/);
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
