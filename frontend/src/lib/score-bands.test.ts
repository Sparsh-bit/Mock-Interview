import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { SCORE_BANDS, scoreBand, scoreBarTone, scoreChipTone } from './score-bands';

/**
 * The colours agree with the words — score-bands.test.ts
 *
 * WHY THIS EXISTS. The backend decides what a score is CALLED and the frontend decides what
 * colour it is DRAWN. Those were two independent sets of thresholds — 85/70/55/40 in
 * `composer.score_label`, 75/50/30 in the report page — so a 72 was labelled "Good" beside a
 * bar the same colour as a 51. Neither side was wrong on its own; they had simply never been
 * compared, and nothing in either language could notice.
 *
 * THIS TEST READS THE THRESHOLDS BACK OUT OF THE PYTHON. That is unusual and it is the point:
 * a constant copied into a comment is a claim, and the failure mode here is somebody editing
 * `composer.py` — reasonably, in its own language, with its own tests passing — and never
 * opening a `.ts` file. A guard that only checks TypeScript against TypeScript cannot see
 * that edit at all.
 */

const COMPOSER = join(process.cwd(), '..', 'backend', 'app', 'services', 'report', 'composer.py');

/** The `score_0_100 >= N` floors inside `score_label`, in source order. */
function backendFloors(): number[] {
  const src = readFileSync(COMPOSER, 'utf8');
  const fn = src.slice(src.indexOf('def score_label'));
  const body = fn.slice(0, fn.indexOf('\ndef ', 1));
  return [...body.matchAll(/score_0_100\s*>=\s*(\d+)/g)].map((m) => Number(m[1]));
}

describe('the test can actually see the backend', () => {
  it('finds composer.py where it expects it', () => {
    // Without this, a moved file makes `backendFloors()` throw — or worse, return [] — and
    // every comparison below would pass vacuously against an empty list. That is the exact
    // shape of vacuous guard this repo has been bitten by six times.
    expect(existsSync(COMPOSER), `composer.py not found at ${COMPOSER}`).toBe(true);
  });

  it('extracts a plausible set of floors', () => {
    const floors = backendFloors();
    expect(floors.length).toBeGreaterThan(0);
    // Descending, which is what makes first-match-wins correct on both sides.
    expect([...floors].sort((a, b) => b - a)).toEqual(floors);
  });
});

describe('the frontend bands are the backend bands', () => {
  it('uses exactly the thresholds composer.py uses', () => {
    // -Infinity is the catch-all and has no counterpart in the Python's final bare `return`.
    const ours = SCORE_BANDS.filter((b) => Number.isFinite(b.floor)).map((b) => b.floor);
    expect(ours).toEqual(backendFloors());
  });

  it('has one more band than the backend has thresholds — the floor case', () => {
    expect(SCORE_BANDS.length).toBe(backendFloors().length + 1);
  });

  it('uses the same words the report prints', () => {
    const src = readFileSync(COMPOSER, 'utf8');
    for (const band of SCORE_BANDS) {
      expect(src, `composer.py never returns ${band.label}`).toContain(
        `"${band.label}"`,
      );
    }
  });
});

describe('a score always lands somewhere sensible', () => {
  it.each([
    [100, 'Excellent'],
    [85, 'Excellent'],
    [84.9, 'Good'],
    [70, 'Good'],
    [69, 'Satisfactory'],
    [55, 'Satisfactory'],
    [54, 'Needs Improvement'],
    [40, 'Needs Improvement'],
    [39, 'Significant Gaps'],
    [0, 'Significant Gaps'],
  ])('%s is %s', (score, label) => {
    expect(scoreBand(score).label).toBe(label);
  });

  it('never returns undefined, even for nonsense', () => {
    // This runs inside render. A crash here blanks the report page a candidate paid for.
    for (const s of [-1, -1000, Number.NEGATIVE_INFINITY]) {
      expect(scoreBand(s).label).toBe('Significant Gaps');
    }
  });

  it('green does not reach the middle', () => {
    // The specific thing the old 75/50/30 set got wrong: a 56 drawn green while the report
    // called it Satisfactory. Passing colours start at 70, where the word "Good" starts.
    expect(scoreBarTone(56)).not.toContain('emerald');
    expect(scoreBarTone(56)).not.toContain('teal');
    expect(scoreBarTone(70)).toContain('teal');
  });

  it('every band has a distinct colour', () => {
    // Two bands sharing a colour would make the distinction between them invisible, which
    // is the same as not having drawn it.
    expect(new Set(SCORE_BANDS.map((b) => b.bar)).size).toBe(SCORE_BANDS.length);
    expect(new Set(SCORE_BANDS.map((b) => b.chip)).size).toBe(SCORE_BANDS.length);
  });

  it('chip tones always pair a background with a text colour', () => {
    // A chip with a tinted background and no text colour inherits the body colour, which is
    // how a badge ends up dark-on-dark.
    for (const band of SCORE_BANDS) {
      expect(scoreChipTone(band.floor === -Infinity ? 0 : band.floor)).toMatch(/bg-\S+\s+text-\S+/);
    }
  });
});
