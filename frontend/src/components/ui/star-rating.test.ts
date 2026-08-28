import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The rating must never cost the report — star-rating.test.ts
 *
 * The candidate has paid ₹49 and is one tap from the thing they paid for. The rating is
 * REQUIRED to press the button, by decision — but requiring the gesture is not the same as
 * putting a network call on the critical path to a paid deliverable, and the difference is
 * the whole design:
 *
 *   the GESTURE is required — the button is disabled until a star is chosen
 *   the RESPONSE is not     — the save is fired without being awaited, so a dropped
 *                             connection costs the rating and never the report
 *
 * Source-level assertions because the vitest environment here is `node`: this page mounts
 * framer-motion and next/navigation and cannot be rendered. What is worth pinning is not the
 * markup — it is which promise the button waits on.
 */

const SRC = join(process.cwd(), 'src');

const strip = (s: string) =>
  s
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');

const PAGE = strip(readFileSync(join(SRC, 'app/(interview)/session/[id]/page.tsx'), 'utf8'));
const HOOK = strip(readFileSync(join(SRC, 'hooks/useInterview.ts'), 'utf8'));
const STAR = strip(readFileSync(join(SRC, 'components/ui/star-rating.tsx'), 'utf8'));

describe('the rating is required to continue', () => {
  it('the button is disabled until a star is chosen', () => {
    expect(PAGE).toMatch(/disabled=\{stars === 0\}/);
  });

  it('it says so, rather than leaving a dead button', () => {
    // A disabled button with no explanation is the single most likely reason somebody reaches
    // the end of an interview and leaves without opening their report.
    expect(PAGE).toMatch(/Tap a star to continue/);
  });

  it('the stars start unchosen', () => {
    expect(PAGE).toMatch(/useState\(0\)/);
  });
});

describe('but it can never cost them the report', () => {
  it('the save is not awaited', () => {
    // THE PROPERTY. `await rateInterview.mutateAsync(...)` before completeSession would put a
    // network round trip in front of a paid deliverable.
    expect(PAGE).not.toMatch(/await\s+rateInterview/);
    // Scoped to the RATING. `mutateAsync` is used legitimately elsewhere on this page — the
    // panel turn awaits its own call — so banning it file-wide would fail for the wrong reason.
    expect(PAGE).not.toMatch(/rateInterview\.mutateAsync/);
  });

  it('completing the session is not chained behind the rating', () => {
    // Both are fired; neither waits for the other. If completeSession moved into the
    // rating's onSuccess, a failed rating would strand the candidate on this card.
    const at = PAGE.indexOf('rateInterview.mutate(');
    expect(at).toBeGreaterThan(-1);
    const after = PAGE.slice(at, at + 200);
    expect(after).toMatch(/completeSession\.mutate\(sessionId\)/);
    expect(after).not.toMatch(/onSuccess/);
  });

  it('a failed rating is swallowed rather than shown', () => {
    // There is nothing the candidate can do about a rating that did not save, and a toast on
    // the happy path teaches them the product is broken when it is not.
    const at = HOOK.indexOf('const rateInterview');
    expect(at).toBeGreaterThan(-1);
    const body = HOOK.slice(at, at + 700);
    expect(body).toMatch(/onError: \(\) => \{\}/);
    expect(body).toMatch(/retry: false/);
  });

  it('the rating is not retried after the page has gone', () => {
    // The user is routed to the report the moment completeSession resolves. A background
    // retry firing after unmount is a request nobody is listening to.
    const at = HOOK.indexOf('const rateInterview');
    expect(HOOK.slice(at, at + 700)).toMatch(/retry: false/);
  });
});

describe('the stars are usable without a mouse', () => {
  it('is a radiogroup rather than five buttons', () => {
    // Five buttons put five stops in the tab order and give a screen reader no way to say
    // "3 of 5 selected".
    expect(STAR).toMatch(/role="radiogroup"/);
    expect(STAR).toMatch(/role="radio"/);
    expect(STAR).toMatch(/aria-checked=/);
  });

  it('uses a roving tabindex, so the group is one tab stop', () => {
    expect(STAR).toMatch(/tabIndex=/);
    expect(STAR).toMatch(/: -1/);
  });

  it('arrow keys select, not merely move', () => {
    // Moving focus without selecting leaves a keyboard user unable to choose at all.
    expect(STAR).toMatch(/ArrowRight/);
    expect(STAR).toMatch(/ArrowLeft/);
    const at = STAR.indexOf('ArrowRight');
    expect(STAR.slice(at, at + 200)).toMatch(/onChange\(/);
  });

  it('each star says what it means, not just its number', () => {
    expect(STAR).toMatch(/Poor/);
    expect(STAR).toMatch(/Excellent/);
    expect(STAR).toMatch(/aria-label=\{`\$\{star\}/);
  });

  it('hover never reaches the parent', () => {
    // A rating that changed as the cursor passed over it would submit whatever the pointer
    // happened to be under.
    const at = STAR.indexOf('onMouseEnter');
    expect(STAR.slice(at, at + 120)).toMatch(/setHover\(star\)/);
    expect(STAR.slice(at, at + 120)).not.toMatch(/onChange/);
  });
});

describe('no price or plan copy leaked into the interview flow', () => {
  it('the completion card names no rupee figure', () => {
    // plans.py is the only thing that decides a price. A number typed here goes stale
    // silently, in front of somebody who has just paid.
    const at = PAGE.indexOf('Interview Complete');
    expect(PAGE.slice(at, at + 1600)).not.toMatch(/₹\d/);
  });
});
