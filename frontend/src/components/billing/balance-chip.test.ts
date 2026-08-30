import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The way to pricing is never gone — balance-chip.test.ts
 *
 * WHY THIS EXISTS. The header used to carry a permanent "Plans" button, and the comment beside
 * it recorded why: below `lg` the navigation rail is hidden, so this is the ONLY always-visible
 * route to the one action that resolves a 402. A blocked candidate who cannot find the way to
 * unblock themselves concludes the product is broken rather than that they have not bought
 * anything — and phones are what most of them use.
 *
 * I replaced that button with a chip showing what they have left, which is better information
 * and more persuasive. But I wrote `if (!data) return null` for the loading case, and
 * `useBalance` returns no data both while loading AND on any failure. So the link disappeared
 * on a slow or failing network — exactly when somebody is most likely to be stuck.
 *
 * The rule is therefore stronger than "render something": there must be no path through this
 * component that fails to offer /pricing.
 */

const SRC = readFileSync(
  join(process.cwd(), 'src/components/billing/BalanceChip.tsx'),
  'utf8',
);

/** Code with comments removed — this file's own prose discusses `return null`. */
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('the scan sees real code', () => {
  it('found the component', () => {
    expect(CODE).toContain('export function BalanceChip');
    expect(CODE.length).toBeGreaterThan(500);
  });
});

describe('every branch offers a way to buy', () => {
  it('never returns null', () => {
    /*
     * THE ACTUAL REGRESSION, stated as the property rather than as a description of the fix.
     * A `return null` anywhere in here means some state of the balance query renders no link
     * at all, and the two states that do that — loading and errored — are the states a
     * struggling connection sits in.
     */
    expect(CODE, 'a branch of BalanceChip renders nothing, removing the only always-visible route to /pricing on phones').not.toMatch(
      /return\s+null/,
    );
  });

  it('every return renders a link to /pricing', () => {
    // Counted rather than asserted once: the component has a branch per balance state
    // (unlimited, no interview feature, loading, and the real figure) and each must route.
    const links = [...CODE.matchAll(/href="\/pricing"/g)].length;
    const returns = [...CODE.matchAll(/return\s*\(/g)].length;
    expect(links).toBeGreaterThanOrEqual(returns);
    expect(returns).toBeGreaterThanOrEqual(3);
  });

  it('carries an accessible name even when the label is hidden below sm', () => {
    // `hidden` removes an element from the accessibility tree as well as from the layout, so
    // between 0 and 640px the visible text is gone and only aria-label identifies the link.
    // That is the width band this link exists for.
    const ariaLabels = [...CODE.matchAll(/aria-label=/g)].length;
    const returns = [...CODE.matchAll(/return\s*\(/g)].length;
    expect(ariaLabels).toBeGreaterThanOrEqual(returns);
  });

  it('shows no figure until the server has sent one', () => {
    /*
     * The other half of the requirement, and the reason `null` was tempting in the first
     * place: a paying user shown "0 left" during load believes it.
     *
     * SCOPED TO `PlainPlansLink` ITSELF, not to a slice of the file between two markers. The
     * first version of this took `CODE.slice(indexOf('if (!data)'), indexOf('if
     * (data.unlimited)'))` — which was right until I extracted the fallback into its own
     * function at the bottom of the file, at which point the slice covered a region that no
     * longer contained the markup. Mutation-testing caught it: injecting `{left} left` into
     * the fallback survived, because the assertion was reading the wrong text. A window that
     * addresses code by position rather than by name is a window that silently stops
     * pointing at anything (docs/MISTAKES.md P1).
     */
    const start = CODE.indexOf('function PlainPlansLink');
    expect(start, 'PlainPlansLink not found — this test is checking nothing').toBeGreaterThan(0);
    const fallback = CODE.slice(start);

    expect(fallback, 'the no-data fallback prints a count it cannot know').not.toMatch(
      /\{left\}|\{full\}|\{short\}|remaining/,
    );
    expect(fallback).toContain('Plans');
  });
});

describe('the header still uses it', () => {
  it('AppHeader renders the chip', () => {
    // A component that is correct and unmounted helps nobody — NudgeDeck was mounted and
    // rendering nothing for exactly this reason (docs/MISTAKES.md M11).
    const header = readFileSync(
      join(process.cwd(), 'src/components/layout/Header.tsx'),
      'utf8',
    ).replace(/\/\*[\s\S]*?\*\//g, '').replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
    expect(header).toMatch(/<BalanceChip\s*\/>/);
  });
});
