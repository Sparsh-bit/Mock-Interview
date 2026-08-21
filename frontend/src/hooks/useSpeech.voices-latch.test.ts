import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { planPanelAllocation, type AllocationStage } from './useSpeech';
import { allDistinguishable, type PanelSpeaker } from '@/lib/speech/panel-voices';

/**
 * ONE VOICE IDENTITY PER ROUND — the browser half.
 *
 * THE REPORT: "in the starting of the interview the voices changes and then it changed again to
 * the old voices." The neural probe race is the half everyone looks at first, but it only fires
 * on a cold backend. THIS half fired on every browser-voice interview, every time, and needed
 * nothing to fail.
 *
 * `getVoices()` is empty until the engine has enumerated its voices, and Chrome does not
 * deliver them all at once: the local voices (qualityTier 10) arrive first and the network
 * "Google …" ones (tier 800) are appended by a later `voiceschanged`. `allocate` ran from three
 * triggers — an immediate call, a 250ms poll, and that event — and replaced the map wholesale on
 * each one. Since `allocatePanelVoices` ranks its input, a richer pool is not a better
 * assignment of the same voices; it is a DIFFERENT assignment. So the candidate heard:
 *
 *   1. the pitch-only fallback (engine default at 0.86 / 1.14 — a pitched-down Samantha for
 *      Anil on macOS),
 *   2. then real local voices,
 *   3. then different real voices once Google's arrived.
 *
 * Three identity changes before the first answer. A change of voice is the cue humans use for a
 * change of SPEAKER, so this reads as new interviewers joining the call — the candidate spends
 * attention re-identifying the room during the one activity where their whole attention is the
 * thing being measured. That is why a marginally better voice loses to a stable one, and why
 * this is latched rather than kept "best available".
 */

/** Minimal stand-in; the allocator only reads name, lang and voiceURI. */
function voice(name: string, lang = 'en-US'): SpeechSynthesisVoice {
  return {
    name,
    lang,
    voiceURI: `urn:${name.replace(/\s+/g, '-').toLowerCase()}`,
    default: false,
    localService: true,
  } as SpeechSynthesisVoice;
}

/** The interview panel, as api/v1/panel.py defines it. Genders are the point. */
const PANEL: PanelSpeaker[] = [
  { name: 'Anil', gender: 'male' },
  { name: 'Priya', gender: 'female' },
];

/** What macOS/Chrome returns once the local voices have enumerated. */
const LOCAL = [voice('Samantha'), voice('Alex'), voice('Karen', 'en-AU'), voice('Daniel', 'en-GB')];
/** …and what it returns after the network voices are appended by a later `voiceschanged`. */
const LOCAL_PLUS_GOOGLE = [
  ...LOCAL,
  voice('Google US English'),
  voice('Google UK English Male', 'en-GB'),
];

/**
 * Drive the real trigger sequence through the pure planner and report what each speaker ended
 * up sounding like after every step.
 *
 * This is deliberately the whole sequence rather than three separate cases: the bug was not any
 * one allocation being wrong — each of them was individually correct and had a passing test —
 * it was that consecutive allocations DISAGREED.
 */
function driveTriggers(lists: SpeechSynthesisVoice[][]): Array<Map<string, string | null>> {
  let stage: AllocationStage = 'none';
  let committed = new Map<string, string | null>();
  const seen: Array<Map<string, string | null>> = [];
  for (const available of lists) {
    const decision = planPanelAllocation(stage, available, PANEL);
    if (decision) {
      stage = decision.stage;
      committed = new Map(
        [...decision.map].map(([name, v]) => [name, v.voiceURI ?? `pitch:${v.pitch}`]),
      );
    }
    seen.push(new Map(committed));
  }
  return seen;
}

describe('planPanelAllocation — who sounds like whom cannot change mid-interview', () => {
  it('THE REGRESSION: a later, richer voice list does not reassign anybody', () => {
    // Empty (mount) → local voices (poll) → local plus Google (voiceschanged). Steps 2 and 3
    // must be identical; under the old code they were not, and that was the audible flip.
    const [empty, local, plusGoogle] = driveTriggers([[], LOCAL, LOCAL_PLUS_GOOGLE]);

    expect(local.get('Anil')).toBe(plusGoogle.get('Anil'));
    expect(local.get('Priya')).toBe(plusGoogle.get('Priya'));
    // And the first step was genuinely a different, worse identity — so the assertion above is
    // pinning a latch rather than an allocator that happens to be insensitive to its input.
    expect(empty.get('Anil')).not.toBe(local.get('Anil'));
  });

  it('holds through as many further triggers as the browser cares to fire', () => {
    // Safari fires nothing and the poll runs 20 times; Chrome fires `voiceschanged` more than
    // once. Neither may be able to move the round's voices.
    const lists = [[], LOCAL, LOCAL_PLUS_GOOGLE, LOCAL, LOCAL_PLUS_GOOGLE, LOCAL_PLUS_GOOGLE];
    const seen = driveTriggers(lists);
    const settled = seen[1];
    for (const step of seen.slice(1)) {
      expect(step.get('Anil')).toBe(settled.get('Anil'));
      expect(step.get('Priya')).toBe(settled.get('Priya'));
    }
  });

  it('commits SOMETHING with no voices, so the panel is never one default voice', () => {
    /*
     * The older bug, kept pinned because the latch must not resurrect it. `allocate` used to be
     * `if (!available.length) return;`, leaving voiceMap empty — speakAs then read
     * `assigned?.pitch ?? 1` and every panelist got pitch 1.0 and no voice. On macOS the default
     * is Samantha, so Anil sounded female: the panel was one woman reading two name tags.
     */
    const first = planPanelAllocation('none', [], PANEL);
    expect(first).not.toBeNull();
    expect(first!.stage).toBe('pitch-only');
    expect(allDistinguishable(first!.map)).toBe(true);
  });

  it('does not re-commit the pitch-only fallback on every poll tick', () => {
    // Mechanical as well as audible: this runs every 250ms, and handing React a fresh Map each
    // time would re-render for as long as the poll lasts.
    expect(planPanelAllocation('pitch-only', [], PANEL)).toBeNull();
  });

  it('but the pitch-only fallback IS still upgradable, exactly once', () => {
    /*
     * The one thing that must NOT be latched. Safari frequently never fires `voiceschanged` and
     * simply starts returning a populated list, so the poll is the only path off gender-anchored
     * pitches. Latching there would strand those candidates on the fallback for a whole round
     * with real voices sitting unused.
     */
    const up = planPanelAllocation('pitch-only', LOCAL, PANEL);
    expect(up).not.toBeNull();
    expect(up!.stage).toBe('real');
    expect(up!.map.get('Anil')!.voiceURI).not.toBeNull();
    // And that upgrade is the last one.
    expect(planPanelAllocation('real', LOCAL_PLUS_GOOGLE, PANEL)).toBeNull();
  });

  it('a real allocation still gender-matches, which is what it is latching', () => {
    // Latching a WRONG allocation would be worse than the flip. Priya must not be latched onto
    // Alex.
    const got = planPanelAllocation('none', LOCAL, PANEL)!.map;
    expect(got.get('Priya')!.voiceName).toBe('Samantha');
    expect(got.get('Anil')!.voiceName).toBe('Alex');
  });
});

/** usePanelVoices' body with comments removed, so an assertion cannot match prose. */
function hookSource(): string {
  const src = readFileSync(new URL('./useSpeech.ts', import.meta.url), 'utf8');
  const body = src.slice(src.indexOf('export function usePanelVoices'));
  return body
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((l) => !l.trim().startsWith('//'))
    .join('\n');
}

/**
 * The hook itself, asserted by source.
 *
 * The same technique panel-voices.test.ts uses, and for the same reason: the fault is in the
 * CALLER's ordering, and there is no DOM in this suite to render a hook into. A passing test on
 * a pure module whose caller ignores it is worse than no test, because it reads as coverage —
 * which is exactly how the empty-voiceMap bug shipped.
 */
describe('usePanelVoices decides before it speaks', () => {
  it('has no unsynchronised neural flag left in it', () => {
    // `const neuralRef = useRef(false)` written from a fire-and-forget effect and read fresh on
    // every utterance WAS the bug: false for the greeting, true for everything after it, and
    // never written false by any failure so each line re-attempted independently.
    const hook = hookSource();
    expect(hook).not.toMatch(/neuralRef/);
  });

  it('awaits the round plan BEFORE it asks for any audio', () => {
    // Ordering is the entire fix, so it is asserted as ordering rather than as presence.
    const hook = hookSource();
    const planAt = hook.indexOf('await resolveRoundVoice()');
    const fetchAt = hook.indexOf('fetchUtterance(');
    expect(planAt).toBeGreaterThan(-1);
    expect(fetchAt).toBeGreaterThan(planAt);
  });

  it('consults the degrade latch per line rather than its own memory of it', () => {
    // The latch lives in neural-tts.ts because that module owns the vendor relationship. A copy
    // of it in the hook would be a second piece of state that has to agree with the first.
    expect(hookSource()).toMatch(/neuralOff\(\)/);
  });

  it('reads TTSStatus.voices, which was fetched and discarded for its whole life', () => {
    // A speaker the server has no voice id for used to 503 once per line, forever — a permanent
    // per-speaker oscillation with a round trip attached to every flip.
    expect(hookSource()).toMatch(/neuralSpeakers/);
  });

  it('starts a fresh round when it mounts', () => {
    // The probe memo and the degrade latch are module scope, so without this the second
    // interview taken in a tab inherits the first one's degrade.
    expect(hookSource()).toMatch(/resetSpeechRound\(\)/);
  });

  it('prefetching defers to the plan instead of giving up on it', () => {
    // `if (!neuralRef.current) return;` meant prefetching was off for exactly the turn it exists
    // for — the first one — so the opening line was both a surprise voice change AND cold,
    // paying the vendor's full ~3.5s on the critical path.
    const hook = hookSource();
    const prefetch = hook.slice(hook.indexOf('const prefetchTurn'));
    expect(prefetch).not.toMatch(/if \(!plan\.neural\) return;\s*for/);
    expect(prefetch).toMatch(/resolveRoundVoice\(\)\.then/);
  });

  it('still commits an allocation with no voices, and still polls for the real list', () => {
    // Held from panel-voices.test.ts, because the latch is the change most likely to take these
    // out by accident.
    const hook = hookSource();
    expect(hook).not.toMatch(/if\s*\(\s*!available\.length\s*\)\s*return\s*;/);
    expect(hook).toMatch(/allocatePanelVoices\(\[\], speakers\)/);
    expect(hook).toMatch(/setInterval/);
    expect(hook).toMatch(/voiceschanged/);
  });

  it('speakAs no longer changes identity when the voice map does', () => {
    // The dependency was what let a queued turn speak through the allocation that existed when
    // it was ENQUEUED — reliably the empty one, on the first turn of every interview.
    const hook = hookSource();
    expect(hook).toMatch(/voiceMapRef\.current\.get\(speaker\)/);
    expect(hook).not.toMatch(/\[voiceMap, stanceOf\]/);
  });
});
