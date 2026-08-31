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
    // THE PROPERTY, not the mechanism. This used to look for `uploadResume.mutate(file` — the
    // literal call — and broke the moment the upload moved into hooks/useResumeUploadFlow.ts
    // so the interview page could share the consent handling the profile page already had.
    // What must stay true is that choosing a file cannot reach the endpoint that SPENDS A
    // CREDIT, whatever the upload is called.
    // SCOPED TO THE HANDLER'S OWN BRACES, not to a character count.
    //
    // This read `CODE.slice(at, at + 500)`, and 500 characters past the upload call now runs
    // clean out of the handler and into the Build button's `onClick={handleGenerate}` — which
    // is correct code doing exactly what it should. The test failed on the button it was never
    // about. A fixed-width window is the "reaching a neighbour" shape in docs/MISTAKES.md P1,
    // and it fails in the direction that looks like a real finding.
    // ANCHORED ON THE FILE INPUT, then the next onChange after it. Anchoring on
    // `onChange={(e) => {` alone finds the COMPANY text field, which is the first one on the
    // page — the third anchor I tried here and the second that silently pointed at the wrong
    // element. `type="file"` appears exactly once and is unambiguous.
    const fileInput = CODE.indexOf('type="file"');
    expect(fileInput, 'no file input on this page').toBeGreaterThan(-1);
    const start = CODE.indexOf('onChange={(e) => {', fileInput);
    expect(start, 'the upload onChange handler could not be found').toBeGreaterThan(-1);
    let depth = 0;
    let i = CODE.indexOf('{', start + 'onChange='.length);
    const from = i;
    do {
      if (CODE[i] === '{') depth++;
      else if (CODE[i] === '}') depth--;
      i++;
    } while (depth > 0 && i < CODE.length);
    const handler = CODE.slice(from, i);

    expect(handler, 'the handler no longer submits the file').toMatch(/resumeUpload\.submit\(file/);
    expect(handler).not.toMatch(/handleGenerate|createPlan\.mutate/);
  });
});

describe('the upload control itself', () => {
  it('is on this page rather than a link to the profile', () => {
    // A real file input on THIS page. The point of the original assertion was that somebody
    // blocked by the required resume field is not sent away to find another page and lose the
    // setup they had already filled in.
    expect(CODE).toMatch(/useResumeUploadFlow/);
    expect(CODE).toMatch(/type="file"/);
    expect(CODE).not.toMatch(/href="\/profile"/);
  });

  it('handles the consent step, which is why it used to fail here', () => {
    /*
     * THE BUG THIS TEST EXISTS FOR. The upload endpoint answers 428 PRECONDITION REQUIRED
     * when no consent row exists. This page called the mutation directly with one generic
     * onError, so an un-consented candidate saw "Could not read that file. Try a PDF, DOCX
     * or plain text." — untrue, unactionable, and unfixable by trying another file. The
     * resume is REQUIRED to start an interview, so the form could not be completed from here
     * at all; the only route was to find the profile page and consent there.
     */
    expect(CODE).toMatch(/awaitingConsent/);
    expect(CODE).toMatch(/<ResumeConsentGate/);
    expect(CODE).toMatch(/consentGranted/);
  });

  it('clears the input so the same file can be retried after a failure', () => {
    // Without this, choosing the identical file twice fires no change event and a failed
    // upload cannot be retried with the file that failed — which is the one they want to try.
    expect(CODE).toMatch(/e\.target\.value = ''/);
  });

  it('cannot be fired twice while one upload is in flight', () => {
    expect(CODE).toMatch(/disabled=\{resumeUpload\.isUploading\}/);
  });

  it('says what happened either way', () => {
    /*
     * ASSERTED AGAINST THE HOOK, because that is where the outcome is now reported from — and
     * checking it here rather than dropping the test is the point: the property is that a
     * candidate is told what happened, not that a particular file contains `onSuccess`.
     *
     * The hook also does something the old inline handler did not: it surfaces the SERVER'S
     * message rather than a generic one, because the server explains exactly why a file could
     * not be read ("that PDF is a scan — upload the original export").
     */
    const flow = readFileSync(
      join(process.cwd(), 'src/hooks/useResumeUploadFlow.ts'),
      'utf8',
    );
    expect(flow).toMatch(/onSuccess/);
    expect(flow).toMatch(/onError/);
    // The 428 branch specifically — that is the whole reason this hook exists, and a
    // version of it that dropped the branch would still satisfy the two assertions above.
    expect(flow).toMatch(/=== 428/);
  });
});
