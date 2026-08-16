import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The microphone must never be open while the panel is speaking.
 *
 * REPORTED FROM A REAL SESSION, with a screenshot. The candidate's answer box contained
 * Priya's own correction, mangled by the recogniser:
 *
 *     she said:  "you keep the fields private and only allow access through public
 *                 getters and setters"
 *     it heard:  "you keep the feels private and only allow access through public catchers"
 *
 * The cause was that the interlock waited on `speakingNow || takingFloor`, and BOTH ARE
 * PER-UTTERANCE. speakAs sets speakingNow back to null the instant one line ends, and the
 * next line's takingFloor is not set until the chained promise resumes and React re-renders.
 * A three-line turn has two of those windows. In them nobody appeared to be talking, so the
 * mic armed — and the next sentence went into the answer.
 *
 * WHY THESE ARE SOURCE ASSERTIONS. The real check would drive the page with a fake
 * recogniser and a fake speech chain, and the honest reason there is no such harness is that
 * the page owns a MediaStream, an AudioContext, MediaPipe and speechSynthesis, none of which
 * exist in jsdom. Pinning the interlock in source is a weaker test than that and a much
 * stronger one than nothing — it catches the exact regression that shipped, which is
 * somebody removing a guard while refactoring and seeing every test still pass.
 */

const PAGE = readFileSync(
  join(process.cwd(), 'src/app/(interview)/session/[id]/page.tsx'),
  'utf8',
);

/** Source with comments removed, so an assertion cannot match its own explanation. */
const CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('the microphone interlock', () => {
  it('gates on the turn-level flag, not only the per-utterance ones', () => {
    // The fix. `panelBusy` is set once before the first line and cleared once after the
    // last, so it cannot have the gap the per-utterance signals have.
    expect(CODE).toMatch(/if\s*\(\s*panelBusy\s*\|\|/);
  });

  it('still covers the single-voice fallback path', () => {
    // panelBusy knows nothing about the non-panel path, which is what speaks when the
    // provider is down — and a candidate on the degraded path deserves the same interlock.
    expect(CODE).toMatch(/panelBusy\s*\|\|\s*tts\.speaking/);
  });

  it('holds the flag across the request, not just the speaking', () => {
    // A mic opened while the turn is being WRITTEN is a mic that is already open when the
    // turn arrives. setPanelBusy(true) must precede the network call.
    const busyAt = CODE.indexOf('setPanelBusy(true)');
    const requestAt = CODE.indexOf('panelTurn.mutateAsync');
    expect(busyAt).toBeGreaterThan(-1);
    expect(requestAt).toBeGreaterThan(-1);
    expect(busyAt).toBeLessThan(requestAt);
  });

  it('releases the flag in a finally, so a failure cannot deafen the interview', () => {
    // Without this, one provider error leaves the microphone interlocked for the rest of
    // the session — a worse bug than the one being fixed, and a silent one.
    expect(CODE).toMatch(/finally\s*\{[\s\S]{0,400}?setPanelBusy\(false\)/);
  });

  it('closes an already-open mic when a turn begins', () => {
    // The other direction: the pivot and the code review both speak in response to
    // something the candidate just did, so the mic can already be listening.
    const busyAt = CODE.indexOf('setPanelBusy(true)');
    const closeAt = CODE.indexOf('closeMicRef.current?.()', busyAt);
    const tryAt = CODE.indexOf('try {', busyAt);
    expect(closeAt).toBeGreaterThan(-1);
    expect(closeAt).toBeLessThan(tryAt);
  });

  it('discards what the recogniser already heard when a turn begins', () => {
    // Closing is not enough: the recogniser keeps its own transcript, so a fragment captured
    // in the instant before the close still flows into the answer box afterwards.
    expect(CODE).toContain('resetAnswerRef.current?.()');
  });

  it('never copies a transcript into the answer while the panel has the floor', () => {
    // The last gate before their words become the candidate's answer.
    expect(CODE).toMatch(/if\s*\(panelBusy\)\s*return;[\s\S]{0,120}setAnswer\(stt\.transcript\)/);
  });

  it('re-checks the flag inside the arming timeout', () => {
    // The delay is long enough for the next turn to have started after the check that
    // scheduled it, so the check has to happen again when it fires.
    expect(CODE).toMatch(/pinnedClosedRef\.current\s*\|\|\s*panelBusyRef\.current/);
  });

  it('waits long enough after the last word for the room to be quiet', () => {
    // Most candidates are on a laptop with speakers on, so the panel's last syllable is
    // still physically in the room after the audio element reports that it ended.
    const m = CODE.match(/openMicRef\.current\?\.\(\);\s*\}\s*,\s*(\d+)\)/);
    expect(m).toBeTruthy();
    expect(Number(m![1])).toBeGreaterThanOrEqual(800);
  });

  it('only arms while a question is actually open', () => {
    // The redesign put four more panel turns between questions. Without this the mic arms
    // during a code review and transcribes Anil reading the candidate's own code back.
    expect(CODE).toMatch(/phase !== 'asking' && phase !== 'skill_check'/);
  });

  it('claims the arming guard when the mic opens, not when the timer is scheduled', () => {
    /*
     * Claiming it early made a cancelled arming permanent. This effect has eleven
     * dependencies and its cleanup clears the pending timer, so any of them changing inside
     * the 900ms window cancelled the open — and the re-run then saw the guard already
     * claimed and returned. The microphone never opened for that question, while the
     * interface went on inviting the candidate to speak.
     *
     * Asserted structurally, on the guard sitting inside the timeout body alongside the call
     * that opens the mic, because the ordering is the whole property.
     */
    const timeoutBody = CODE.match(/setTimeout\(\(\)\s*=>\s*\{([\s\S]*?)\},\s*900\)/);
    expect(timeoutBody).toBeTruthy();
    expect(timeoutBody![1]).toMatch(/armedForRef\.current\s*=\s*question\.id/);
    expect(timeoutBody![1]).toMatch(/openMicRef\.current/);
  });

  it('does not gate the skill check on the question being a coding one', () => {
    /*
     * `isCoding` describes the QUESTION, but the arming effect also runs for the skill check,
     * which happens before that question is put and is a spoken moment regardless of what it
     * turns out to be. Unqualified, this returned early during `skill_check` whenever question
     * one happened to be a coding question: the mic never opened, the candidate said their
     * rating into a closed microphone, and parseSelfRating was handed an empty transcript.
     *
     * Intermittent in exactly the way that makes it hard to report, because it depended on
     * the type of the first question the orchestrator happened to pick.
     */
    expect(CODE).toMatch(/if\s*\(isCoding\s*&&\s*phase\s*===\s*'asking'\)\s*return;/);
    // And the unqualified form must not come back.
    expect(CODE).not.toMatch(/if\s*\(isCoding\)\s*return;/);
  });
});

describe('the layout does not move under the candidate', () => {
  it('is exactly one viewport tall so the panes scroll instead of the page', () => {
    // The jumping mic button: the page grew with its content, so every line the panel added
    // pushed the answer controls further down — the mic moved under your thumb between one
    // sentence and the next.
    expect(CODE).toContain('h-[100dvh]');
    expect(CODE).not.toContain('flex min-h-screen flex-col bg-background');
  });

  it('uses dvh rather than vh for the WORKSPACE root', () => {
    // vh is the height with browser chrome HIDDEN, so a 100vh page is permanently taller
    // than the visible area on mobile Safari and Chrome — the bottom of it, which is the
    // mic, sits under the address bar.
    //
    // Scoped to the workspace root on purpose. The loading, error and completed screens are
    // centred full-page cards and `min-h-screen` is right for those: they have no bottom
    // edge to lose and no internal scrolling to bound.
    expect(CODE).not.toMatch(/className="flex h-screen/);
    expect(CODE).toMatch(/className="flex h-\[100dvh\] flex-col overflow-hidden/);
  });

  it('gives the grid min-h-0, without which every overflow rule inside it is ignored', () => {
    // A grid item defaults to min-height:auto — "as tall as my content" — which silently
    // defeats the scrolling panes.
    expect(CODE).toMatch(/grid w-full min-h-0/);
  });

  it('caps both answer inputs so a long answer cannot push Submit off screen', () => {
    /*
     * REPORTED: "when the answer gets so long the submit next buttons hides down".
     *
     * Both inputs read `flex-1 overflow-y-auto` (the voice transcript) and `flex-1`
     * (the typing textarea), and in both cases the overflow never fired. `flex-1` only
     * bounds a child when the flex PARENT has a bounded height — and their parent is the
     * answer channel, which is `flex-shrink-0` and therefore sized to its own content. So
     * `flex-1` resolved to "grow to fit": the box grew with every sentence, the channel
     * grew with it, and Submit & Next slid below the fold at exactly the moment somebody
     * who had just given a long answer wanted to press it.
     *
     * An explicit max-height is what makes the scroll real. Asserted on both, because the
     * two paths are edited independently and only one of them was ever noticed.
     */
    const capped = [...CODE.matchAll(/max-h-\[\d+vh\][^"']*overflow-y-auto|overflow-y-auto[^"']*max-h-\[\d+vh\]|max-h-\[\d+vh\][^"']*resize-none|resize-none[^"']*max-h-\[\d+vh\]/g)];
    expect(capped.length).toBeGreaterThanOrEqual(2);
    // And neither may go back to growing with its content.
    expect(CODE).not.toMatch(/min-h-\[96px\] w-full flex-1 overflow-y-auto/);
    expect(CODE).not.toMatch(/w-full flex-1 resize-none/);
  });

  it('keeps the answer controls out of the scrolling region', () => {
    expect(CODE).toMatch(/flex-shrink-0 border-t border-border\/50 pt-4/);
  });
});

describe('the interview can never get stuck in a phase', () => {
  /*
   * The failure this guards is the worst one this page has: a candidate mid-interview with
   * no way forward. It is not hypothetical — two paths had it. `reviewing` renders no
   * controls at all (no microphone, no submit, only "They are reading your code…"), so if
   * the code-review turn threw before resetting the phase, that message was the rest of
   * their session. The pivot path had the same shape: a throw left the phase on `asking`
   * with `panelForRef` already claimed, so no new turn could fire and `refetch` never ran.
   *
   * Both are now impossible by construction rather than by six separate try/catches, which
   * is what these assert.
   */

  it('speakTurn cannot reject, so no caller needs to defend against it', () => {
    // Six places await it, several from inside `void (async () => …)()` where a rejection is
    // an unhandled promise and nothing recovers. One guarantee at the source beats six
    // wrappers and the chance of forgetting the seventh.
    const body = CODE.slice(CODE.indexOf('const speakTurn'));
    const end = body.indexOf('[sessionId, candidateName]');
    const fn = body.slice(0, end);
    expect(fn).toMatch(/catch\s*\(err\)\s*\{[\s\S]{0,400}?return\s*\{\s*spoke:\s*false/);
  });

  it('the code review resets the phase in a finally', () => {
    // Belt as well as braces. speakTurn cannot reject today; this makes the phase reset
    // survive somebody adding an await above it that can.
    const review = CODE.slice(CODE.indexOf("stage: 'code_review'") - 400);
    expect(review.slice(0, 900)).toMatch(/finally\s*\{[\s\S]{0,300}?setPhase\('asking'\)/);
  });

  it('every phase with no controls of its own is left automatically', () => {
    // `reviewing` is the only phase that renders nothing the candidate can press, so it is
    // the only one where a missing reset is unrecoverable. Its exit must not depend on a
    // button that does not exist.
    const reviewingUi = CODE.match(/phase === 'reviewing'\s*\?\s*'([^']+)'/);
    expect(reviewingUi, 'the reviewing phase should still render a status line').toBeTruthy();
    expect(CODE).toMatch(/setPhase\('reviewing'\)/);
    expect(CODE).toMatch(/finally[\s\S]{0,300}?setPhase\('asking'\)/);
  });

  it('End Interview is reachable from every phase', () => {
    // The universal escape. It sits in the header, outside the phase-dependent panes, and
    // cancels speech before completing so the report is never blocked behind a talking panel.
    const header = CODE.slice(CODE.indexOf('End Interview') - 700, CODE.indexOf('End Interview'));
    expect(header).toContain('panelVoices.cancelAll()');
    expect(header).toContain('completeSession.mutate');
  });
});

describe('the compiler is only built when the role needs one', () => {
  it('is not rendered at all for a non-technical role', () => {
    // Hiding it with a class is not the same thing: a hidden pane still mounts CodeMirror,
    // still pulls in every language mode, and still runs its effects — on a sales interview,
    // for an editor nobody will ever open.
    expect(CODE).toMatch(/\{hasEditor && \(/);
    expect(CODE).not.toMatch(/!hasEditor \? 'hidden'/);
  });

  it('the layout collapses to two columns rather than leaving a gap', () => {
    expect(CODE).toMatch(/lg:grid-cols-\[minmax\(0,1\.7fr\)_minmax\(280px,0\.8fr\)\]/);
  });

  it('the mobile tab bar drops the Compiler tab with it', () => {
    // A tab leading to a pane that does not exist is a dead end on the one layout where
    // panes are the only navigation.
    expect(CODE).toMatch(/hasEditor \? \[\{ id: 'code'/);
  });

  it('a candidate already on the Compiler tab is moved off it', () => {
    // The role is resolved asynchronously, so the tab can be selected before we learn there
    // is no editor — leaving them staring at an empty pane.
    expect(CODE).toMatch(/!hasEditor && mobilePane === 'code'[\s\S]{0,60}setMobilePane\('talk'\)/);
  });
});

describe('three silent contradictions found by auditing rather than by failing', () => {
  /*
   * None of these broke a test, a type check or a lint rule. Each was code whose apparent
   * intent differed from its runtime behaviour — the same family as the promo-code errors
   * that were all 500s because a class attribute was overwritten in __init__.
   */

  it('a failed /next request does not end the interview', () => {
    /*
     * `question` is `data?.question ?? null`, so it is null when the interview is OVER and
     * when the request simply FAILED. Without an isError check the closing sequence fires on
     * a dropped connection: closedRef latches, the phase moves to `closing`, and a candidate
     * who taps Retry gets their question back into a page that has already decided the
     * interview finished — with no way out but End Interview, on an interview that never
     * started.
     */
    const closing = CODE.slice(CODE.indexOf("setPhase('closing')") - 900, CODE.indexOf("setPhase('closing')"));
    expect(closing).toMatch(/if \(isError\) return;/);
    // And the dependency, or the guard reads a stale value.
    expect(CODE).toMatch(/\[question, preparing, phase, isError\]/);
  });

  it('the panel speaks through the CURRENT voice allocation, not the first one', () => {
    /*
     * `speakTurn` is a useCallback on [sessionId, candidateName] and used to call
     * `panelVoices.speakAs` directly — capturing the object from the render that created it.
     * `speakAs` is itself useCallback([voiceMap, stanceOf]), and both settle asynchronously
     * after mount. So every line went out through the speakAs built when the voice map was
     * still EMPTY, and on the browser-speech path Anil and Priya shared one default voice at
     * identical pitch — which is exactly the "the voices are so bad" and "Meera has a male
     * voice" reports. The allocation was working; nothing was reading it.
     */
    expect(CODE).toMatch(/voicesRef\.current\.speakAs/);
    expect(CODE).toMatch(/voicesRef\.current\.prefetchTurn/);
    // The stale form must not come back inside speakTurn.
    const speakTurn = CODE.slice(CODE.indexOf('const speakTurn'), CODE.indexOf('[sessionId, candidateName]'));
    expect(speakTurn).not.toMatch(/panelVoices\.speakAs/);
  });

  it('a non-technical interview never shows a code editor, not even for a frame', () => {
    // `hasEditor` defaults to true while the role query is in flight — the right default,
    // but it meant a sales interview opened as three columns with CodeMirror mounted and
    // then reflowed to two underneath the candidate.
    expect(CODE).toMatch(/if \(isLoading \|\| panelInfoLoading\)/);
    expect(CODE).toMatch(/isLoading: panelInfoLoading/);
  });
});
