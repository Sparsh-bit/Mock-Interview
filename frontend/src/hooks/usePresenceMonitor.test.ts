import { describe, expect, it } from 'vitest';

import { ABSENT_MS, MULTI_PERSON_MS, accumulate } from './usePresenceMonitor';

/**
 * The second-person warning did not work, and the reason is worth keeping a test around.
 *
 * The old rule was 75 CONSECUTIVE frames with more than one face, reset to zero on any frame
 * that missed. Face detection at the edge of frame — which is exactly where a second person
 * sits — succeeds on most frames, not all. So the run reset every twenty or thirty frames and
 * never reached seventy-five, and the warning was unreachable by construction rather than by
 * mistake. Every test below is really the same test: does a realistic, flickering detection
 * still get through.
 */

/** Run `frames` of ~16ms each, where `hit(i)` says whether the condition held. */
function run(frames: number, hit: (i: number) => boolean, dt = 16): number {
  let acc = 0;
  for (let i = 0; i < frames; i++) acc = accumulate(acc, dt, hit(i));
  return acc;
}

describe('accumulate — sustained presence signals', () => {
  it('crosses the threshold on a clean run', () => {
    // 100 frames × 16ms = 1600ms of a second face, against a 1200ms threshold.
    expect(run(100, () => true)).toBeGreaterThanOrEqual(MULTI_PERSON_MS);
  });

  it('THE REGRESSION: still fires when detection flickers', () => {
    // 85% detection — a genuinely present second person, imperfectly seen. Under the old
    // consecutive-frame rule this produced runs of about six frames and never warned.
    const flaky = (i: number) => i % 7 !== 0;
    expect(run(200, flaky)).toBeGreaterThanOrEqual(MULTI_PERSON_MS);
  });

  it('still fires at 70% detection — poor light, half-turned away', () => {
    expect(run(400, (i) => i % 10 < 7)).toBeGreaterThanOrEqual(MULTI_PERSON_MS);
  });

  it('does NOT fire on someone walking past behind the candidate', () => {
    // Half a second in frame, then gone. A warning here is the cry-wolf failure, and a
    // proctoring signal nobody believes is worse than no signal.
    expect(run(200, (i) => i < 30)).toBe(0);
  });

  it('does NOT fire on a single stray frame, however unlucky the timing', () => {
    expect(run(200, (i) => i === 120)).toBe(0);
  });

  it('drains to zero once the second person genuinely leaves', () => {
    // Present long enough to warn, then gone. The live warning must clear — only the
    // sticky "was detected earlier" one persists, and that is a separate metric.
    let acc = run(200, () => true);
    expect(acc).toBeGreaterThanOrEqual(MULTI_PERSON_MS);
    for (let i = 0; i < 300; i++) acc = accumulate(acc, 16, false);
    expect(acc).toBe(0);
  });

  it('a cleared warning disappears within a couple of seconds, not instantly', () => {
    // Decay is below 1, so draining is slower than filling — deliberately. A warning that
    // vanishes the moment detection blinks reads as twitchy; one that lingers a beat reads
    // as the system being sure. Two seconds is the bound that keeps "a beat" honest.
    let acc = run(60, () => true); // ~960ms banked
    for (let i = 0; i < 125; i++) acc = accumulate(acc, 16, false); // 2s of clear frames
    expect(acc).toBe(0);
  });

  /*
   * THE NUMBER THAT DECIDES WHAT IS DETECTABLE AT ALL.
   *
   * Decay sets a break-even detection rate of decay/(1+decay). Above it the accumulator
   * climbs and the warning fires eventually; below it the accumulator cannot reach the
   * threshold however long the interview runs — that person is invisible forever, not late.
   *
   * At decay 2 the break-even is 67%, which sounds tolerant and is not: a second person
   * half-lit or turned away detects around 60% of frames. These two tests pin the operating
   * point at ~41%, so raising decay for "fewer false positives" has to be a deliberate
   * choice about who stops being detectable, made with the number in front of you.
   */
  it('a second person seen in 50% of frames is still eventually detected', () => {
    expect(run(1200, (i) => i % 2 === 0)).toBeGreaterThanOrEqual(MULTI_PERSON_MS);
  });

  it('but spurious one-in-five detections never accumulate', () => {
    // A poster, a reflection, a photograph on the wall behind the candidate.
    expect(run(3000, (i) => i % 5 === 0)).toBe(0);
  });

  it('is time-based, so the verdict does not depend on the display refresh rate', () => {
    // The other half of the original bug: "75 frames" is 0.6s on a 120Hz laptop and 2.5s on
    // a throttled 30fps one, so the same second person warned or did not warn depending on
    // the hardware. Two refresh rates, one second of wall-clock, same answer.
    const at120 = run(120, () => true, 8.33);
    const at30 = run(30, () => true, 33.3);
    expect(Math.abs(at120 - at30)).toBeLessThan(20);
  });

  it('needs the candidate gone longer than a second person needs to be present', () => {
    // Leaning out of shot to think is normal; being accused of walking out for it is not.
    expect(ABSENT_MS).toBeGreaterThan(MULTI_PERSON_MS);
  });

  it('never goes negative, so a long quiet stretch cannot bank credit', () => {
    // If it could, the accumulator would have to climb out of a hole before warning, and a
    // second person arriving late in a long interview would be missed entirely.
    let acc = 0;
    for (let i = 0; i < 1000; i++) acc = accumulate(acc, 16, false);
    expect(acc).toBe(0);
    expect(run(100, () => true)).toBeGreaterThanOrEqual(MULTI_PERSON_MS);
  });
});
