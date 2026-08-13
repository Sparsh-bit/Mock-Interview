/**
 * How each panelist speaks — lib/speech/persona.ts
 *
 * A panelist's delivery, derived from the disposition the server gives them
 * (backend/app/api/v1/gd.py PANELISTS).
 *
 * WHY IT IS NOT IN panel-voices.ts. That module owns voice and pitch — the
 * question of "can you tell these three apart at all" — and its `rate` field is
 * reserved for separating speakers who had to share one voice, which
 * panel-voices.test.ts pins at 1.0 whenever a panelist has an exclusive voice.
 * Tempo here is a MULTIPLIER on top of that, so both apply without either
 * overwriting the other.
 *
 * Keyword-matched against the stance prose rather than keyed by name: names are
 * data the server owns and may change, dispositions are what actually determine
 * how someone talks. An unmatched stance gets the conversational average, so a
 * new panelist sounds neutral rather than wrong.
 *
 * THERE IS NO VOLUME FIELD, ON PURPOSE. The obvious third channel is
 * `utter.volume`, and it is perceptually empty here. Volume is linear gain: 0.94
 * is −0.54 dB, well under the ~1 dB anyone can hear in ideal conditions and far
 * under what is audible on laptop speakers in a noisy room, which is the actual
 * listening environment. The range that WOULD be audible (~0.78, −2.2 dB) pushes
 * the quiet panelist toward inaudible at low system volume. And the voices this
 * panel will actually use on the machines that matter — Edge "Online (Natural)",
 * Chrome "Google " — are cloud-backed and do not honour per-utterance volume at
 * all. Tempo and lead-in are the two channels that genuinely reach the listener.
 */

/** What a panelist sounds like, over and above which voice they were given. */
export interface SpeakerPersona {
  /**
   * Multiplier on the voice's base rate. Roughly 8% is plainly audible; 25% is
   * comic. The three values below are 9% and 8% apart for that reason — an
   * earlier draft used 1.08 / 1.05 / 0.95, and 3% between the two fast speakers
   * is not a tempo difference, it is a number in a table.
   */
  tempo: number;
  /**
   * Silence before taking the floor from someone else, in ms.
   *
   * This is the channel that carries the most character for the least risk. Under
   * ~80ms reads as a glitch rather than eagerness; over ~700ms reads as the app
   * having hung.
   */
  leadInMs: number;
}

export const DEFAULT_PERSONA: SpeakerPersona = { tempo: 1.0, leadInMs: 300 };

const TRAITS: Array<{ match: RegExp; persona: SpeakerPersona }> = [
  /*
   * Assertive/dominant: takes the floor the moment it is free.
   * Tested first because a stance can read as both assertive and argumentative,
   * and dominance is the stronger signal.
   *
   * TEMPO WAS 1.09 AND IT WAS TOO FAST TO LISTEN TO. This is Riya's stance, and she was
   * reported as unpleasant to hear — not merely brisk.
   *
   * 1.09 was not the whole of it either; it was the top of a stack. The server already
   * applies its own speed per tone (`aside` is 1.08 in TONE_PROSODY), and on the neural
   * path this multiplier was then applied AGAIN as an <audio> playbackRate. An aside from
   * the assertive panelist therefore came out near 1.18 — well past the ~12% at which
   * neural-tts.ts's own comment says a resampled voice stops sounding brisk and starts
   * sounding sped-up. That is the "annoying and disturbed" quality: not the voice, the
   * arithmetic on top of it.
   *
   * Assertiveness now rides almost entirely on the 160ms latch, which is the channel this
   * file already argues carries the most character for the least risk. A small positive
   * tempo is kept so she is still marginally the quickest, which is true to the stance.
   */
  {
    match: /assertive|dominat|opens strong|pushy|aggressive/i,
    persona: { tempo: 1.02, leadInMs: 160 },
  },
  // The contrarian latches on almost before you have finished. Held at his
  // voice's own baseline tempo rather than nudged just below the assertive
  // panelist, because a 3% gap is below the audible threshold this file
  // documents. His signature is the 90ms latch, and that is plenty.
  {
    match: /interrupt|opposing|contrarian|devil'?s advocate|enjoys the debate/i,
    persona: { tempo: 1.0, leadInMs: 90 },
  },
  // The synthesiser speaks to be agreed with rather than to win: slower, and
  // visibly waits before answering.
  {
    match: /synthesis|listens|middle ground|consensus|brings quiet|conciliat/i,
    persona: { tempo: 0.92, leadInMs: 520 },
  },
];

/** The delivery implied by a stance, or the conversational average. */
export function personaFor(stance: string | undefined): SpeakerPersona {
  if (!stance) return DEFAULT_PERSONA;
  for (const t of TRAITS) {
    if (t.match.test(stance)) return t.persona;
  }
  return DEFAULT_PERSONA;
}

/**
 * Are these personas actually distinguishable by ear?
 *
 * Exported for the tests, in the same spirit as `allDistinguishable` in
 * panel-voices.ts: the failure this module exists to prevent is three panelists
 * who are notionally different and audibly identical, and that failure is silent
 * unless something asserts against it.
 */
export function personasDistinguishable(personas: SpeakerPersona[]): boolean {
  for (let i = 0; i < personas.length; i++) {
    for (let j = i + 1; j < personas.length; j++) {
      const tempoGap = Math.abs(personas[i].tempo - personas[j].tempo);
      const leadGap = Math.abs(personas[i].leadInMs - personas[j].leadInMs);
      // Either channel on its own is enough, but one of them has to clear the
      // threshold: 6% of rate, or 60ms of silence before speaking.
      if (tempoGap < 0.06 && leadGap < 60) return false;
    }
  }
  return true;
}
