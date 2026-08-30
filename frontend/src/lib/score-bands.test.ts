import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
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

describe('every band carries the tones its call sites need', () => {
  it('has a stroke for the report ring and an ink for its numeral', () => {
    /*
     * BOTH WERE ONCE DERIVED BY STRING SURGERY on other fields — `bar.replace('bg-','stroke-')`
     * for the ring and `chip.split(' ').find(c => c.startsWith('text-'))` for the numeral.
     * Both worked, and both made the colour of the product's headline score depend on the
     * internal spelling and CLASS ORDER of unrelated strings: reordering `chip` for
     * readability would have silently changed it.
     */
    for (const band of SCORE_BANDS) {
      expect(band.stroke, band.label).toMatch(/^stroke-accent-\w+$/);
      expect(band.ink, band.label).toMatch(/^text-accent-\w+-ink$/);
    }
  });

  it('stroke, bar, chip and ink all name the same hue', () => {
    // A band whose ring is emerald and whose numeral is teal would be reporting two different
    // verdicts about one score, which is the exact failure this module was created to end.
    for (const band of SCORE_BANDS) {
      const hue = band.bar.replace('bg-accent-', '');
      expect(band.stroke, band.label).toBe(`stroke-accent-${hue}`);
      expect(band.ink, band.label).toBe(`text-accent-${hue}-ink`);
      expect(band.chip, band.label).toContain(`accent-${hue}-soft`);
      expect(band.chip, band.label).toContain(`accent-${hue}-ink`);
    }
  });

  it('no call site rebuilds a tone from another field', () => {
    // The habit, not just the instance. Scans the pages that draw scores.
    const files = [
      'src/app/(dashboard)/report/[id]/page.tsx',
      'src/app/(dashboard)/report/page.tsx',
      'src/app/(dashboard)/dashboard/page.tsx',
      'src/app/(dashboard)/gd/page.tsx',
    ];
    for (const f of files) {
      const src = readFileSync(join(process.cwd(), f), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
        .replace(/\/\/.*$/gm, '');
      expect(src, `${f} rebuilds a class from another band field`).not.toMatch(
        /\.(bar|chip|ink|stroke)\s*\.\s*(replace|split)\s*\(/,
      );
    }
  });
});

describe('nowhere else decides what a score means', () => {
  /**
   * FIVE SEPARATE ANSWERS TO ONE QUESTION existed in this codebase, and I found the fourth and
   * fifth only because I went looking after fixing the first three:
   *
   *   composer.py            85 / 70 / 55 / 40   the words the candidate reads
   *   report/[id]/page.tsx   75 / 50 / 30        the bars on the report
   *   r/[reportId]/page.tsx  75 / 50 / 30        the PUBLIC shared report
   *   lib/utils.ts           85 / 70 / 55 / 40   right numbers, different words, no callers
   *   dashboard (mine)       70 / 50             invented while "fixing" the problem
   *
   * Each was written by somebody solving a local problem correctly. Nothing in either language
   * could see two of them at once, so the drift was invisible until a 72 printed "Good" beside
   * a bar the colour of a 51.
   *
   * This scans for the SHAPE — a comparison of a score-ish name against a threshold that then
   * chooses an accent class — rather than for the specific numbers, because the next copy will
   * have different numbers. That is the whole point.
   */
  const THRESHOLD_THEN_TONE =
    /(?:score|pct|percent|overall|rating|avg)\w*\s*>=\s*\d{2}[\s\S]{0,80}?accent-\w+/gi;

  it('finds the pages it means to scan', () => {
    const files = scorePages();
    expect(files.length).toBeGreaterThanOrEqual(8);
    expect(files.some((f) => f.includes('report'))).toBe(true);
  });

  it('no page bands a score with its own thresholds', () => {
    const offenders: string[] = [];
    for (const file of scorePages()) {
      const code = readFileSync(file, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
        .replace(/\/\/.*$/gm, '');
      for (const m of code.matchAll(THRESHOLD_THEN_TONE)) {
        /*
         * NOT EVERY THRESHOLDED PERCENTAGE IS A SCORE. The admin page shades cache saturation
         * — how full a table is against its row cap — where 90% is a WARNING, the opposite of
         * what 90 means as a score. Loosening the regex to miss it would also miss the next
         * real one, so the exception is declared in the source instead, on the line above.
         *
         * Checked against the ORIGINAL source rather than the comment-stripped copy, because
         * the marker is itself a comment.
         */
        const raw = readFileSync(file, 'utf8');
        const idx = raw.indexOf(m[0].slice(0, 30));
        const near = idx >= 0 ? raw.slice(Math.max(0, idx - 400), idx) : '';
        if (near.includes('@not-a-score')) continue;
        offenders.push(`${file.replace(process.cwd() + '/', '')}: ${m[0].replace(/\s+/g, ' ').slice(0, 90)}`);
      }
    }
    expect(
      offenders,
      'These pick a colour from a score using thresholds of their own. Import from ' +
        'lib/score-bands instead — it mirrors composer.py, which produces the WORD printed ' +
        'next to the colour:\n' + offenders.join('\n'),
    ).toEqual([]);
  });
});

/** Source files that draw scores. */
function scorePages(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry) && !entry.includes('.test.') && !full.includes('score-bands'))
        out.push(full);
    }
  };
  walk(join(process.cwd(), 'src'));
  return out;
}
