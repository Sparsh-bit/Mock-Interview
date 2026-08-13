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

  it('keeps the answer controls out of the scrolling region', () => {
    expect(CODE).toMatch(/flex-shrink-0 border-t border-border\/50 pt-4/);
  });
});
