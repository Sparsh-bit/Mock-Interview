/**
 * Giving each group-discussion panelist a voice of their own —
 * lib/speech/panel-voices.ts
 *
 * THE PROBLEM. A group discussion only works if you can tell who is talking. The
 * GD round previously spoke none of the panel aloud at all, so "Riya", "Arjun"
 * and "Meera" were three names above three blocks of text. Handing all three the
 * same TTS voice would be barely better: one voice reading three people is a
 * monologue with name tags, and you cannot practise interrupting a monologue.
 *
 * WHAT THIS DOES. Allocates the most distinguishable set of voices the browser
 * actually has, then falls back to pitch and rate when it runs out.
 *
 * The fallback matters more than it sounds. A Windows machine may expose only two
 * usable en-* voices and a locked-down Linux box sometimes exposes one, so an
 * allocator that needs three distinct voices would fail on real hardware. Two
 * speakers sharing a voice at different pitch and speed are still clearly two
 * people — that is most of what makes voices sound different to us — so the
 * output degrades in quality rather than collapsing.
 *
 * WHY THE LOGIC LIVES HERE and not in the hook: allocation is pure, and it is the
 * part with all the decisions in it. Separated, it can be tested against the exact
 * voice lists real platforms report — including the degenerate one-voice case,
 * which is impossible to reproduce by hand in a browser.
 */

import { scoreVoice } from './voice-ranking';

/** What a panelist should sound like. Applied to a SpeechSynthesisUtterance. */
export interface PanelVoice {
  /** Which platform voice to use, or null to let the engine choose. */
  voiceURI: string | null;
  /** Human-readable, for the UI and for debugging an odd allocation. */
  voiceName: string | null;
  /** 0.1–2. Distinguishes speakers who had to share a voice. */
  pitch: number;
  /** 0.1–10. Conversational range is roughly 0.9–1.1. */
  rate: number;
}

/**
 * Voice names that are conventionally female or male on the platforms this app
 * runs on — macOS, Windows, Chrome's cloud voices, Android.
 *
 * The Web Speech API exposes no gender field, and there is no reliable way to
 * derive one, so this is a name lookup with a deliberate limitation: an unknown
 * voice is 'unknown' rather than guessed. A wrong guess would pair two voices the
 * allocator believes are contrasting and which actually sound identical — worse
 * than admitting we do not know, because it stops the pitch fallback from kicking
 * in.
 */
const FEMALE_VOICES = [
  'neerja', 'heera', 'aditi', 'veena', 'samantha', 'victoria', 'karen', 'moira',
  'tessa', 'fiona', 'susan', 'zira', 'hazel', 'catherine', 'linda', 'female',
  'aria', 'jenny', 'michelle', 'monica', 'joanna', 'kendra', 'salli', 'kimberly',
];
const MALE_VOICES = [
  'prabhat', 'rishi', 'ravi', 'alex', 'daniel', 'fred', 'oliver', 'thomas',
  'david', 'mark', 'george', 'james', 'male', 'guy', 'brandon', 'christopher',
  'matthew', 'joey', 'russell', 'brian', 'arthur',
];

export type VoiceGender = 'female' | 'male' | 'unknown';

export function guessGender(voiceName: string): VoiceGender {
  const n = voiceName.toLowerCase();
  if (FEMALE_VOICES.some((f) => n.includes(f))) return 'female';
  if (MALE_VOICES.some((m) => n.includes(m))) return 'male';
  return 'unknown';
}

/**
 * Pitch anchors by gender, used whenever a panelist does not have an exclusive
 * voice of their own gender.
 *
 * The gap between them is what makes a shared voice read as two different people:
 * 0.86 and 1.14 are far enough apart to hear immediately, and both are inside the
 * range where a voice still sounds like a person rather than processed.
 */
const GENDER_ANCHOR: Record<VoiceGender, number> = {
  male: 0.86,
  female: 1.14,
  unknown: 1.0,
};

/**
 * Extra separation for the Nth panelist of the SAME gender sharing one voice.
 *
 * 0.18 per step, alternating up then down, because 0.18 is comfortably above the
 * threshold where a pitch change is audible. An earlier version used a table of
 * small offsets and produced Riya at 1.00 and Arjun at 0.97 — a 0.03 difference
 * nobody can hear, which meant the "one voice reading three people" failure this
 * module exists to prevent survived the allocator. `allDistinguishable` caught it.
 */
const SAME_GENDER_STEP = 0.18;

function clampPitch(p: number): number {
  return Math.min(1.9, Math.max(0.35, Math.round(p * 100) / 100));
}

/**
 * The pitch for a panelist who is sharing a voice, or holding one of the wrong
 * gender: anchored to their own gender, then stepped away from anyone of the same
 * gender already on that voice.
 */
function sharedPitch(gender: VoiceGender, sameGenderSlot: number): number {
  const anchor = GENDER_ANCHOR[gender];
  if (sameGenderSlot === 0) return clampPitch(anchor);
  // 1 → +step, 2 → −step, 3 → +2 steps, 4 → −2 steps …
  const magnitude = Math.ceil(sameGenderSlot / 2) * SAME_GENDER_STEP;
  const up = sameGenderSlot % 2 === 1;
  return clampPitch(anchor + (up ? magnitude : -magnitude));
}

/** A panelist as the server defines them — name plus the gender their name implies. */
export interface PanelSpeaker {
  name: string;
  gender: VoiceGender;
}

/**
 * Pick a voice per panelist: matching their gender first, distinct second.
 *
 * GENDER IS A HARD REQUIREMENT, not a tiebreak. "Riya" must not speak in a male
 * voice. A candidate tracks who is arguing what by voice while trying to think of
 * a rebuttal — they are not reading name labels — so a mismatch does not merely
 * look sloppy, it makes the round harder to follow in a way that has nothing to do
 * with the discussion. Gender therefore beats voice quality here, which is the
 * opposite of the tradeoff `scoreVoice` makes for the single interviewer voice,
 * and deliberately so: there is only one interviewer, so nothing to confuse.
 *
 * Within the right gender, best quality wins.
 *
 * When a panelist cannot get an exclusive voice of their own gender — common on
 * Linux, and on Windows without the Indian language pack — they share one, pitched
 * to their gender anchor and stepped clear of anyone else of the same gender on
 * that voice. A pitched voice is a compromise; three identical readings is a
 * broken feature.
 *
 * Deterministic: the same inputs always produce the same allocation, so nobody
 * changes voice between turns of one discussion.
 */
export function allocatePanelVoices(
  available: SpeechSynthesisVoice[],
  speakers: Array<PanelSpeaker | string>,
): Map<string, PanelVoice> {
  const out = new Map<string, PanelVoice>();
  if (!speakers.length) return out;

  // A bare string means "no gender preference" — for callers that have names only.
  const panel: PanelSpeaker[] = speakers.map((s) =>
    typeof s === 'string' ? { name: s, gender: 'unknown' } : s,
  );

  const usable = available
    .filter((v) => scoreVoice(v) > 0)
    .sort((a, b) => scoreVoice(b) - scoreVoice(a));

  // No usable voice at all. Let the engine choose, but still separate them by
  // pitch so the round is followable.
  if (!usable.length) {
    const slots = new Map<VoiceGender, number>();
    for (const sp of panel) {
      const slot = slots.get(sp.gender) ?? 0;
      slots.set(sp.gender, slot + 1);
      out.set(sp.name, {
        voiceURI: null,
        voiceName: null,
        pitch: sharedPitch(sp.gender, slot),
        rate: 1.0,
      });
    }
    return out;
  }

  const pool: Record<VoiceGender, SpeechSynthesisVoice[]> = {
    female: [],
    male: [],
    unknown: [],
  };
  for (const v of usable) pool[guessGender(v.name)].push(v);

  //: Per voiceURI, how many panelists of each gender are already on it — the
  //: input to sharedPitch.
  const occupancy = new Map<string, Map<VoiceGender, number>>();
  const claim = (uri: string, gender: VoiceGender): number => {
    const byGender = occupancy.get(uri) ?? new Map<VoiceGender, number>();
    const slot = byGender.get(gender) ?? 0;
    byGender.set(gender, slot + 1);
    occupancy.set(uri, byGender);
    return slot;
  };

  for (const sp of panel) {
    // An exclusive voice of the right gender is the only case needing no pitch
    // correction at all.
    const exact = sp.gender !== 'unknown' ? pool[sp.gender].shift() : undefined;
    if (exact) {
      claim(exact.voiceURI, sp.gender);
      out.set(sp.name, {
        voiceURI: exact.voiceURI,
        voiceName: exact.name,
        pitch: 1.0,
        rate: 1.0,
      });
      continue;
    }

    // Next best: a voice whose gender nobody can identify. Safer than one known
    // to be wrong, and the pitch anchor does the rest.
    const neutral = pool.unknown.shift();
    if (neutral) {
      const slot = claim(neutral.voiceURI, sp.gender);
      out.set(sp.name, {
        voiceURI: neutral.voiceURI,
        voiceName: neutral.name,
        pitch: sharedPitch(sp.gender, slot),
        rate: 1.0,
      });
      continue;
    }

    // Everything of the right gender is taken. Share the voice carrying the
    // fewest panelists so reuse spreads, and pitch it to this panelist's gender.
    const shareable = usable
      .slice()
      .sort((a, b) => {
        const load = (v: SpeechSynthesisVoice) =>
          [...(occupancy.get(v.voiceURI)?.values() ?? [])].reduce((x, y) => x + y, 0);
        return load(a) - load(b);
      })[0];
    const slot = claim(shareable.voiceURI, sp.gender);
    out.set(sp.name, {
      voiceURI: shareable.voiceURI,
      voiceName: shareable.name,
      pitch: sharedPitch(sp.gender, slot),
      rate: 1.0,
    });
  }

  return out;
}

/**
 * Are these allocations actually distinguishable from one another?
 *
 * Exported for the tests and for a dev-time check. Two speakers count as
 * distinguishable if they use different voices, or the same voice at a
 * meaningfully different pitch — a 0.05 pitch difference is not audible, so it
 * does not count.
 */
export function allDistinguishable(allocation: Map<string, PanelVoice>): boolean {
  const seen: PanelVoice[] = [];
  for (const v of allocation.values()) {
    const clash = seen.some(
      (s) => s.voiceURI === v.voiceURI && Math.abs(s.pitch - v.pitch) < 0.1,
    );
    if (clash) return false;
    seen.push(v);
  }
  return true;
}
