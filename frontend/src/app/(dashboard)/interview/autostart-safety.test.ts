import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Uploading a resume must not buy an interview — autostart-safety.test.ts
 *
 * THE HAZARD, WRITTEN DOWN BECAUSE IT IS INVISIBLE IN THE DIFF THAT CREATES IT.
 *
 * `?autostart=1` submits the setup form on its own once the form is ready, and one of the
 * readiness conditions is `hasResume`. `POST /interview/plan` CHARGES before it generates —
 * the credit is consumed and the ledger row is written first — so an autostart is a purchase.
 *
 * While the only way to get a resume was to visit /profile, that was safe: a resume-less
 * visitor arriving on an autostart link simply did nothing, because the condition could not
 * become true without navigating away. Adding an upload control to THIS page makes it become
 * true a few seconds later, so the effect re-runs and silently spends money the candidate
 * never asked to spend. The one-shot `autostarted` ref is no defence — it has not fired yet,
 * so there is nothing for it to stop.
 *
 * The fix is to gate autostart on whether a resume was already on file when the page loaded,
 * not on whether one exists now. Uploading during the visit has its own outcome — the form
 * unblocks — and pressing the button that is now enabled is one tap, and is the candidate's.
 */

const PAGE = readFileSync(
  join(process.cwd(), 'src/app/(dashboard)/interview/page.tsx'),
  'utf8',
);

/** Source with comments stripped — prose about a rule is not the rule. */
const CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');

describe('autostart cannot be triggered by something the candidate does on this page', () => {
  it('records whether a resume existed when the page loaded', () => {
    expect(CODE).toMatch(/resumeAtArrival/);
    expect(CODE).toMatch(/resumeAtArrival\.current = !!storedResume\?\.has_text/);
  });

  it('the snapshot is taken once, and only after the query resolves', () => {
    // `undefined` is "still loading" and `null` is "no resume". Capturing while undefined
    // would record false for everybody and disable autostart entirely — a silent regression
    // in the opposite direction, where a working deep link quietly stops working.
    expect(CODE).toMatch(/resumeAtArrival\.current === null && storedResume !== undefined/);
  });

  it('the autostart effect refuses unless the resume was already there', () => {
    const at = CODE.indexOf('if (!requestedAutostart || autostarted.current) return;');
    expect(at).toBeGreaterThan(-1);
    const body = CODE.slice(at, at + 800);
    expect(body).toMatch(/if \(resumeAtArrival\.current !== true\) return;/);
  });

  it('the guard sits before the one-shot ref is armed', () => {
    // Arming the ref and THEN refusing would spend the autostart on a call that never
    // happened, leaving the link looking like it did nothing — the same mistake the
    // customSetup guard is written to avoid, and its comment says so.
    const at = CODE.indexOf('if (!requestedAutostart || autostarted.current) return;');
    const body = CODE.slice(at, at + 800);
    const guard = body.indexOf('resumeAtArrival.current !== true');
    const arm = body.indexOf('autostarted.current = true');
    expect(guard).toBeGreaterThan(-1);
    expect(arm).toBeGreaterThan(-1);
    expect(guard).toBeLessThan(arm);
  });

  it('uploading does not call the paid plan endpoint itself', () => {
    // The upload handler must do exactly one thing. Calling handleGenerate from it would be
    // the same purchase by a more obvious route.
    const at = CODE.indexOf('uploadResume.mutate(file');
    expect(at).toBeGreaterThan(-1);
    const handler = CODE.slice(at, at + 500);
    expect(handler).not.toMatch(/handleGenerate|createPlan\.mutate/);
  });
});

describe('the upload control itself', () => {
  it('is on this page rather than a link to the profile', () => {
    expect(CODE).toMatch(/useUploadResume/);
    expect(CODE).toMatch(/type="file"/);
  });

  it('clears the input so the same file can be retried after a failure', () => {
    // Without this, choosing the identical file twice fires no change event and a failed
    // upload cannot be retried with the file that failed — which is the one they want to try.
    expect(CODE).toMatch(/e\.target\.value = ''/);
  });

  it('cannot be fired twice while one upload is in flight', () => {
    expect(CODE).toMatch(/disabled=\{uploadResume\.isPending\}/);
  });

  it('says what happened either way', () => {
    const at = CODE.indexOf('uploadResume.mutate(file');
    const handler = CODE.slice(at, at + 600);
    expect(handler).toMatch(/onSuccess/);
    expect(handler).toMatch(/onError/);
  });
});
