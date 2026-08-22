import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The room goes quiet when the round is scored — app/(dashboard)/gd/end-of-round.test.ts
 *
 * REPORTED: "after generating the report in gd the speakers are not stopping."
 *
 * `endDiscussion` called `evaluate.mutate` and nothing else. Two consequences, and both were
 * audible:
 *
 *   1. NOTHING CANCELLED THE VOICES. A contribution still playing — or already fetched and
 *      queued behind it — carried on through the whole evaluation and over the top of the
 *      results screen. The unmount cleanup at the bottom of that component catches navigating
 *      AWAY from the page; discussion -> results does not unmount anything, so it never ran.
 *
 *   2. THE PANEL KEPT GOING. `phase` only flips to 'results' inside the success callback, so
 *      for the ten to twenty seconds of evaluation the phase is still 'discussion' — the 1s
 *      tick kept running and kept queueing new turns for a discussion that was already being
 *      marked.
 *
 * The second is the one that made it look broken rather than merely untidy: new speech STARTED
 * after the round ended.
 */

const SRC = readFileSync(join(process.cwd(), 'src/app/(dashboard)/gd/page.tsx'), 'utf8');

/** Comments stripped, so no assertion can be satisfied by its own explanation. */
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('ending a discussion silences it', () => {
  it('cancels the panel voices before scoring starts', () => {
    const fn = CODE.slice(CODE.indexOf('const endDiscussion'), CODE.indexOf('evaluate.mutate('));
    expect(fn).toContain('panelVoices.cancelAll()');
  });

  it('stops the microphone too', () => {
    // Leaving it live means the recogniser keeps transcribing into a draft for a discussion
    // that has already been scored.
    const fn = CODE.slice(CODE.indexOf('const endDiscussion'), CODE.indexOf('evaluate.mutate('));
    // Written without the /s flag: this tsconfig targets below es2018, where dotAll is not
    // available, and `[\s\S]` is the portable equivalent.
    expect(fn).toMatch(/stt\.listening[\s\S]*stt\.stop\(\)/);
  });

  it('does it BEFORE the mutation, not in the success callback', () => {
    // Scoring takes ten to twenty seconds. Cancelling on success would leave the panel talking
    // for all of it, which is the bug.
    const fn = CODE.slice(CODE.indexOf('const endDiscussion'), CODE.indexOf('const endDiscussion') + 900);
    expect(fn.indexOf('cancelAll()')).toBeLessThan(fn.indexOf('evaluate.mutate('));
  });
});

describe('the panel does not start anything new once the round has ended', () => {
  it('the tick bails out on the ending flag', () => {
    // `phase` is still 'discussion' throughout evaluation, so the existing
    // `if (phase !== 'discussion') return` guard does not cover this window. The ref is the
    // only thing that knows.
    const tick = CODE.slice(CODE.indexOf('const id = setInterval('), CODE.indexOf('const id = setInterval(') + 400);
    expect(tick).toContain('if (endingRef.current) return;');
  });

  it('the flag is declared above the tick that reads it', () => {
    // A `const` declared below the effect that closes over it is a use-before-declaration
    // error, which is why the declaration moved up to the other tick refs.
    expect(CODE.indexOf('const endingRef = useRef(false)')).toBeLessThan(
      CODE.indexOf('const id = setInterval('),
    );
  });
});

describe('a round can still be retried and restarted', () => {
  it('a failed evaluation clears the flag so the round resumes', () => {
    // Otherwise a transient scoring failure would leave a live discussion permanently frozen —
    // silent panel, dead clock, no way back.
    // Sliced from `endDiscussion` rather than from the first `onError:` in the file — there
    // are several mutations on this page and the first one is not this one.
    const fn = CODE.slice(CODE.indexOf('const endDiscussion'), CODE.indexOf('const endDiscussion') + 1200);
    const onError = fn.slice(fn.indexOf('onError:'));
    expect(onError).toContain('endingRef.current = false');
  });

  it('starting a new discussion clears it as well', () => {
    const start = CODE.slice(CODE.indexOf("setPhase('discussion')") - 600, CODE.indexOf("setPhase('discussion')"));
    expect(start).toContain('endingRef.current = false');
  });
});
