import { describe, expect, it } from 'vitest';

import { parseSelfRating } from './self-rating';

/**
 * The panel ASKS for this out loud, so it arrives as a transcript rather than a slider
 * value. These tests are mostly about the ways a nervous student actually says a number.
 *
 * The asymmetry that matters: returning null is cheap — the page falls back to a slider and
 * asks. Returning the WRONG number is not, because it silently changes which questions the
 * candidate gets and what their report judges them against, with nothing on screen to say so.
 */
describe('parseSelfRating', () => {
  it('reads a bare spoken number', () => {
    expect(parseSelfRating('seven')?.rating).toBe(7);
    expect(parseSelfRating('8')?.rating).toBe(8);
  });

  it('reads "out of ten" in both forms', () => {
    expect(parseSelfRating("I'd say around 7 out of 10")?.rating).toBe(7);
    expect(parseSelfRating('6/10 sir')?.rating).toBe(6);
    expect(parseSelfRating('seven out of ten')?.rating).toBe(7);
  });

  it('"out of 10" wins over a stray number earlier in the sentence', () => {
    // "2 years" is not a rating. The explicit form is unambiguous, so it takes precedence
    // over position rather than competing with it.
    expect(parseSelfRating('I have 2 years experience, so 8 out of 10')?.rating).toBe(8);
  });

  it('takes the last number when someone corrects themselves', () => {
    // "six, no, seven" is how people actually answer this.
    expect(parseSelfRating('six, no, seven')?.rating).toBe(7);
    expect(parseSelfRating('maybe 6 or 7')?.rating).toBe(7);
  });

  it('rounds a decimal rather than rejecting it', () => {
    expect(parseSelfRating('7.5')?.rating).toBe(8);
  });

  it('picks up the areas they named', () => {
    const r = parseSelfRating('6 out of 10, mostly collections and OOP');
    expect(r?.rating).toBe(6);
    expect(r?.strengths).toContain('collections');
    expect(r?.strengths).toContain('oop');
  });

  it('does not record both "spring" and "spring boot" for one claim', () => {
    const r = parseSelfRating('8, I am good at spring boot');
    expect(r?.strengths).toContain('spring boot');
    expect(r?.strengths).not.toContain('spring');
  });

  it('returns null rather than guessing when there is no number', () => {
    // The page then shows a slider and asks. Guessing here would set the difficulty of the
    // whole interview from a sentence that contained no rating.
    expect(parseSelfRating("I'm alright at Java I suppose")).toBeNull();
    expect(parseSelfRating('')).toBeNull();
    expect(parseSelfRating('   ')).toBeNull();
  });

  it('returns null for a number that cannot be a rating out of ten', () => {
    expect(parseSelfRating('about 45')).toBeNull();
    expect(parseSelfRating('0')).toBeNull();
  });

  it('ignores an out-of-range number and takes the in-range one', () => {
    expect(parseSelfRating('I did 40 problems, I would say 7')?.rating).toBe(7);
  });

  it('never returns a rating outside 1-10', () => {
    for (const t of ['seven', '10', '1', '7 out of 10', '99', '7.5', 'six or seven']) {
      const r = parseSelfRating(t);
      if (r) {
        expect(r.rating).toBeGreaterThanOrEqual(1);
        expect(r.rating).toBeLessThanOrEqual(10);
      }
    }
  });

  it('caps the areas it records', () => {
    const everything =
      '7 out of 10 — oop collections strings exceptions multithreading jvm memory lambda ' +
      'stream spring hibernate jdbc rest dsa algorithm solid';
    expect(parseSelfRating(everything)!.strengths.length).toBeLessThanOrEqual(8);
  });
});
