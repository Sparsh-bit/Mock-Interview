/**
 * The candidate is warned before the mic opens, not after — readiness.test.ts
 *
 * Asked for as "make sure that you are in a quiet environment and near to the mic or use
 * headphones type these things will prompt the worst user to make the interview smooth", plus
 * "show the warning of not to close the screen the interview is getting prepared", plus "show
 * the warnings of that things that are not completed yet like the uploading of the resume and
 * pending profile".
 *
 * WHAT THESE TESTS PROTECT IS PLACEMENT, and placement is the whole value. Every one of these
 * fixes takes ten seconds and is worth nothing once the interview has started, because the
 * candidate gets one attempt. A tip read after the decision, or a "do not close" on a screen
 * that is not waiting for anything, is noise — and noise is what teaches people to ignore the
 * one warning that matters.
 *
 * Source assertions because vitest runs in the `node` environment here (see vitest.config.ts),
 * so nothing can be mounted. Where a component sits in a file, and what it is conditional on,
 * is checkable either way.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '../..');
const READINESS = readFileSync(
  join(SRC, 'components/interview/InterviewReadiness.tsx'),
  'utf8',
);
const SETUP = readFileSync(join(SRC, 'app/(dashboard)/interview/page.tsx'), 'utf8');
const SESSION = readFileSync(join(SRC, 'app/(interview)/session/[id]/page.tsx'), 'utf8');

/**
 * Source with comments removed.
 *
 * These files explain themselves at length, and prose ABOUT a value is not the value: the
 * no-blocking check below first matched the component's own docstring, which says "no disabled
 * button" precisely to explain that there isn't one. A test that reads the documentation
 * instead of the code passes for the wrong reason, and would keep passing if the code changed.
 */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
}

describe('the environment tips', () => {
  it('cover the three things that actually ruin a transcript', () => {
    // Ordered by damage: background voices get transcribed into the answer, distance clips the
    // ends of sentences, and speakers feed the panel's own voice back as if the candidate said
    // it.
    expect(READINESS).toMatch(/quiet room/i);
    expect(READINESS).toMatch(/headphones/i);
    expect(READINESS).toMatch(/close to the mic/i);
  });

  it('says WHY, not just what', () => {
    // "Use headphones" is an instruction people skip. "On speakers the interviewer's voice can
    // be picked up as if it were yours" is a reason, and a reason is what gets acted on.
    expect(READINESS).toMatch(/transcribed into your answer/i);
    expect(READINESS).toMatch(/picked up as if it were yours/i);
  });

  it('sits immediately above the start button', () => {
    const readinessAt = SETUP.indexOf('<InterviewReadiness />');
    const startAt = SETUP.indexOf('onClick={handleStart}');
    expect(readinessAt).toBeGreaterThan(-1);
    expect(startAt).toBeGreaterThan(-1);
    expect(readinessAt).toBeLessThan(startAt);
    // And close to it: further up the page it is read before the decision is real.
    expect(startAt - readinessAt).toBeLessThan(1200);
  });

  it('never blocks starting', () => {
    // Somebody in a shared room ten minutes before a real drive does not need the product
    // refusing to let them practise. There is no gate here and no disabled button.
    expect(code(READINESS)).not.toMatch(/disabled/);
    expect(code(READINESS)).not.toMatch(/canStart|blockStart/);
  });
});

describe('the missing-setup warnings', () => {
  it('warn about a missing resume and say what it costs', () => {
    expect(READINESS).toMatch(/No resume on file/i);
    // The consequence, in the candidate's terms: generic questions instead of their projects.
    expect(READINESS).toMatch(/general questions/i);
  });

  it('warn about a missing name', () => {
    expect(READINESS).toMatch(/name is not set/i);
  });

  it('offer a route to fixing each one', () => {
    // A warning with no action is a complaint, and the fix is one screen away.
    expect(READINESS).toContain("href: '/profile'");
    expect(READINESS).toMatch(/Upload your resume/);
  });

  it('do not fire while the data is still loading', () => {
    // Flashing "you have no resume" at somebody who has one teaches them the warnings are
    // unreliable, and then the real ones get ignored too. `undefined` means loading and must
    // not read as missing.
    expect(READINESS).toMatch(/resume !== undefined/);
    expect(READINESS).toMatch(/profile !== undefined/);
  });

  it('render nothing when there is nothing missing', () => {
    // A checklist of ticks reads as ceremony. The absence of warnings is the message.
    expect(READINESS).toMatch(/gaps\.length > 0 &&/);
  });

  it('say the interview still works without them', () => {
    // These are warnings, not blocks — the interview is simply less tailored.
    expect(READINESS).toMatch(/can start without these/i);
  });
});

describe('the do-not-close warning while a question is generated', () => {
  it('is inside the generating state, not standing on the page', () => {
    // A permanent warning on a screen that is working is noise people learn to ignore — and
    // then do not read on the one screen where it counts.
    const at = SESSION.indexOf('function GeneratingQuestion');
    const end = SESSION.indexOf('export default function', at);
    const block = SESSION.slice(at, end);
    expect(block).toMatch(/keep this screen open/i);
  });

  it('explains the consequence rather than only forbidding', () => {
    expect(SESSION).toMatch(/would interrupt the interview/i);
  });

  it('says the wait is short, so a slow moment does not read as stuck', () => {
    // "Do not close" alone reads as a threat and makes people anxious at the worst moment.
    // Naming a few seconds is what actually stops the reload.
    expect(SESSION).toMatch(/takes a\s*\n?\s*few seconds|few seconds/i);
  });
});
