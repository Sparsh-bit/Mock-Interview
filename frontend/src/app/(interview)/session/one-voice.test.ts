import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * ONE VOICE AT A TIME, and the pinned question must be the one that was actually asked.
 *
 * Two reports, one file, because both are about the same seam between the panel and the
 * page's own single-voice fallback.
 *
 * 1. "sometimes the old google voice arises in the question's background"
 *
 *    A second voice UNDER the panel, not beside it. `window.speechSynthesis` is a global
 *    queue with two independent owners here: this page's interviewer fallback (`tts`, used
 *    when the panel cannot speak) and usePanelVoices' own browser fallback. usePanelVoices
 *    cancels the queue with `speechSynthesis.cancel()` when it takes the floor — but that
 *    only resolves `tts`'s pending utterance. It does not bump `tts`'s generation counter, so
 *    `tts`'s loop wakes at its next await, decides it is still current, and speaks the REST of
 *    the previous question over the panel's neural audio. The browser's default voice on
 *    Chrome is a Google one, which is exactly what was described.
 *
 *    `tts.cancel()` bumps that counter and is the only thing that stops the loop. It belongs
 *    in `speakTurn`, because "the panel is about to talk" is what that function means.
 *
 * 2. "i cannot see the real question asked by the interviewer"
 *
 *    The pinned block rendered `questionText` — the PLANNED question, phrased for a bank. The
 *    panel asks it in its own words instead, so the candidate was reading a second,
 *    differently-worded copy of a question they had just been asked. That is also the
 *    "everytime the question comes on the screen" half of the same sentence.
 *
 * WHY THESE ARE SOURCE ASSERTIONS. Same reason as mic-interlock.test.ts, which documents it
 * in full: the page owns a MediaStream, an AudioContext, MediaPipe and speechSynthesis, none
 * of which exist in jsdom. This catches the regression that actually happens — somebody
 * removing a guard during a refactor and seeing every test still pass.
 */

const PAGE = readFileSync(
  join(process.cwd(), 'src/app/(interview)/session/[id]/page.tsx'),
  'utf8',
);

/** Source with comments removed, so an assertion cannot match its own explanation. */
const CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('the single-voice fallback and the panel never overlap', () => {
  it('cancels the interviewer fallback when a panel turn begins', () => {
    // The fix. Without this, cancel() from usePanelVoices resolves tts's pending utterance
    // and tts carries on with the next chunk underneath the neural audio.
    expect(CODE).toMatch(/tts\.cancel\(\)/);
  });

  it('cancels it inside speakTurn, not at each call site', () => {
    // Six call sites and counting. The invariant is "the panel is about to speak", which is
    // what speakTurn means — pinning it here is what stops the seventh call site from
    // forgetting.
    const start = CODE.indexOf('const speakTurn');
    expect(start).toBeGreaterThan(-1);
    // From speakTurn's declaration to the request it makes. tts.cancel() has to be in that
    // span: inside the function, and ahead of the network call.
    const preamble = CODE.slice(start, CODE.indexOf('panelTurn.mutateAsync', start));
    expect(preamble).toMatch(/tts\.cancel\(\)/);
  });

  it('cancels BEFORE the request, not after the audio', () => {
    // The request itself takes seconds, and a fallback voice still reading the previous
    // question through all of it is the audible bug. Cancelling after the turn would silence
    // it only once it had already been heard.
    const idxCancel = CODE.indexOf('tts.cancel()');
    const idxRequest = CODE.indexOf('panelTurn.mutateAsync');
    expect(idxCancel).toBeGreaterThan(-1);
    expect(idxRequest).toBeGreaterThan(-1);
    expect(idxCancel).toBeLessThan(idxRequest);
  });

  it('still falls back to one voice when the panel returned nothing', () => {
    // The fallback must survive every refactor. A panel that cannot speak and a page that
    // then says nothing is a silent interview, which is worse than a plainer voice.
    //
    // Asserted on the BRANCH rather than on one expression, because the fallback now does
    // two things — speak the question, and append it to the thread as a line from the lead
    // interviewer — and pinning the old single-line shape made a correct change look broken.
    const branch = CODE.match(/if\s*\(!spoke\)\s*\{([\s\S]*?)\n {6}\}/);
    expect(branch).toBeTruthy();
    expect(branch![1]).toMatch(/tts\.supported/);
    expect(branch![1]).toMatch(/tts\.speak\(questionText\)/);
  });

  it('a question the panel could not dress up still lands in the thread', () => {
    // Otherwise a failed turn leaves the conversation pane blank and the candidate is
    // listening to a question they cannot see — which is how "I cannot see what the
    // interviewers are saying" happened in the first place.
    const branch = CODE.match(/if\s*\(!spoke\)\s*\{([\s\S]*?)\n {6}\}/);
    expect(branch![1]).toMatch(/setPanelLines/);
  });
});

describe('the pinned question is the one that was asked', () => {
  it('prefers the line the panel actually spoke', () => {
    expect(CODE).toMatch(/const\s+pinnedQuestion\s*=\s*askedAloud\?\.text\s*\?\?\s*questionText/);
  });

  it('finds the asking line by walking backwards', () => {
    // A turn can end on an aside or a correction — "Priya, do you want the next one?" is a
    // real closing line — so the question is not necessarily last.
    const memo = CODE.slice(CODE.indexOf('const askedAloud'));
    const body = memo.slice(0, memo.indexOf('const pinnedQuestion'));
    expect(body).toMatch(/i\s*=\s*panelLines\.length\s*-\s*1/);
    expect(body).toMatch(/i--/);
    expect(body).toMatch(/tone\s*===\s*'asking'/);
  });

  it('renders the pinned question rather than the planned text', () => {
    // The regression to catch is somebody putting `questionText` back into the block while
    // refactoring the header, which would silently restore the two-copies bug.
    expect(CODE).toMatch(/\{pinnedQuestion\}/);
  });

  it('attributes it to the interviewer who said it', () => {
    expect(CODE).toMatch(/askedAloud\.speaker/);
  });
});
