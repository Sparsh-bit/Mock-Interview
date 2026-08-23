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

describe('abandoning a live interview is warned about', () => {
  const GUARD = readFileSync(join(SRC, 'hooks/useLeaveGuard.ts'), 'utf8');

  it('warns before a close or reload', () => {
    // The only one of the three that can actually PREVENT the loss, so it must exist. The
    // browser supplies its own wording and ignores any custom string, so this cannot explain
    // what is at stake — it can only make the action deliberate.
    expect(GUARD).toContain('beforeunload');
    // Both forms: preventDefault is the modern spec, returnValue is what older Safari and
    // Firefox still require, and those are the browsers this product's users are on.
    expect(GUARD).toMatch(/preventDefault\(\)/);
    expect(GUARD).toMatch(/returnValue/);
  });

  it('notices a tab or app switch', () => {
    expect(GUARD).toContain('visibilitychange');
  });

  it('re-shows the warning if they leave again after dismissing it', () => {
    // Somebody who dismissed it once and left again has demonstrated they did not take it in.
    expect(GUARD).toMatch(/setAcknowledged\(false\)/);
  });

  it('is only armed while there is something to lose', () => {
    // A guard that fires on a finished interview teaches people to click through it.
    expect(SESSION).toMatch(/useLeaveGuard\(phase !== 'done'\)/);
  });

  it('is called before any early return', () => {
    // HOOKS MUST BE UNCONDITIONAL. Placed after the `phase === 'done'` return it was skipped
    // on the completed screen, changing React's hook order between renders — the same mistake
    // eslint caught on the admin page's delete mutation.
    const hookAt = SESSION.indexOf('useLeaveGuard(');
    const firstReturn = SESSION.indexOf('if (phase === ');
    expect(hookAt).toBeGreaterThan(-1);
    expect(hookAt).toBeLessThan(firstReturn);
  });

  it('says the attempt is already counted', () => {
    expect(SESSION).toMatch(/already counted/i);
  });

  it('only calls it FREE when it actually was', () => {
    // "Your free interview will be wasted" is true for somebody on the trial and simply wrong
    // for somebody who bought a five-pack — telling a paying customer they are losing
    // something free reads as the product not knowing what they paid for. Decided from the
    // server's trial_allowance rather than assumed.
    expect(SESSION).toMatch(/trial_allowance/);
    expect(SESSION).toMatch(/isFreeAttempt \?/);
  });
});

describe('the plan-building wait tells them not to close it', () => {
  const SETUP_SRC = readFileSync(join(SRC, 'app/(dashboard)/interview/page.tsx'), 'utf8');

  it('warns while the plan is being built', () => {
    // The longest wait in the product and the one most often read as a stuck page, so it is
    // the wait people abandon.
    expect(SETUP_SRC).toMatch(/keep this page open/i);
  });

  it('says what leaving costs', () => {
    expect(SETUP_SRC).toMatch(/start again/i);
  });

  it('shows it only while the request is in flight', () => {
    // A standing warning on an idle page is noise.
    const at = SETUP_SRC.indexOf('keep this page open');
    expect(SETUP_SRC.slice(Math.max(0, at - 400), at)).toMatch(/createPlan\.isPending/);
  });
});

describe('the setup form says what is blocking the start', () => {
  const SETUP_SRC = readFileSync(join(SRC, 'app/(dashboard)/interview/page.tsx'), 'utf8');

  it('shows the readiness card on the form, in required mode', () => {
    // The resume BLOCKS here — the build button is disabled without one — so it has to be
    // stated as a requirement, not a suggestion.
    expect(SETUP_SRC).toMatch(/<InterviewReadiness[\s\S]*?emphasis="required"/);
  });

  it('passes the pasted-text state so the warning cannot be wrong', () => {
    // The form accepts a stored file OR text pasted into the box, and the card can only see
    // the stored one. Without this a candidate who had just pasted their resume would be told
    // they have none — the fastest way to teach somebody these warnings are wrong.
    expect(SETUP_SRC).toMatch(/resumeSatisfied=\{hasResume\}/);
  });

  it('the button says what it is waiting for instead of being inertly greyed out', () => {
    // A dead control with no reason is indistinguishable from a broken app, and the candidate
    // is one tap from leaving — which is the dropped_off segment.
    expect(SETUP_SRC).toMatch(/Add your resume to continue/);
    expect(SETUP_SRC).toMatch(/Choose a role above to continue/);
  });

  it('names the two requirements separately', () => {
    // "Complete the form" does not say which of the two is missing, and they have different
    // fixes — one is a dropdown, the other is a file.
    const at = SETUP_SRC.indexOf('Choose a role above to continue');
    const near = SETUP_SRC.slice(at - 400, at + 400);
    expect(near).toMatch(/!selectedTrackId/);
    expect(near).toMatch(/!hasResume/);
  });

  it('does not tell them the interview works without a resume on this screen', () => {
    // It does not: the button is disabled. Saying otherwise beside a disabled control is a
    // contradiction that makes every other line less believable.
    const CARD = readFileSync(join(SRC, 'components/interview/InterviewReadiness.tsx'), 'utf8');
    expect(CARD).toMatch(/emphasis !== 'required' &&/);
  });
});
