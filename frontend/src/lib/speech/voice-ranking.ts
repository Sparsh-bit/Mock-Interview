/**
 * Ranking the browser's TTS voices — lib/speech/voice-ranking.ts
 *
 * Extracted from hooks/useSpeech.ts to break a circular import: panel-voices.ts
 * needs `scoreVoice` to decide which voices are usable, and useSpeech.ts needs
 * `allocatePanelVoices` to give the GD panel their voices. Each importing the
 * other happens to work under ESM — both are function declarations, so they are
 * hoisted — but it is a cycle, and a cycle that only works by accident of
 * declaration order is not something to leave in place.
 *
 * Pure ranking logic, no React, no browser calls beyond the voice objects handed
 * in. `useSpeech` re-exports these so existing imports keep working.
 */

/**
 * Named Indian-English voices, best first. These are the platform voices that
 * actually sound like an Indian interviewer:
 *   neerja/prabhat — Microsoft "Online (Natural)" on Edge, the most natural
 *   rishi          — macOS / iOS en-IN
 *   veena          — older macOS en-IN
 *   heera/ravi     — Windows en-IN
 */
export const INDIAN_VOICE_NAMES = ['neerja', 'prabhat', 'rishi', 'veena', 'heera', 'ravi', 'aditi'];

/**
 * How good an engine actually sounds, which matters more than accent.
 *
 * Only the top tier is genuinely neural — Microsoft's "Online (Natural)" voices
 * stream from their cloud and are the closest this browser API gets to a Gemini
 * or ChatGPT-style voice. Apple's default voices are formant-synthesis and sound
 * robotic no matter how you tune rate and pitch.
 */
export function qualityTier(name: string): number {
  // Neural, cloud-streamed (Edge). "Neerja Online (Natural)" is both neural AND
  // Indian, which is the ideal case.
  if (name.includes('natural') || name.includes('online')) return 1000;
  // Chrome's network-backed voices — clearly better than local synthesis.
  if (name.includes('google')) return 800;
  // Apple's downloadable higher-quality voices.
  if (name.includes('premium')) return 400;
  if (name.includes('enhanced')) return 300;
  // Default local synthesis.
  return 10;
}

/**
 * Ranks an available voice for interview narration. Higher = better.
 *
 * Quality tier dominates, then accent within that tier. This ordering is
 * deliberate and was a correction: ranking accent first picked Apple's local
 * `Rishi` over Microsoft's neural `Neerja`, which is exactly the robotic
 * "sounds like a TTS engine" result we were trying to avoid. A neural voice
 * reading in a non-Indian accent still sounds far more human than a synthetic
 * Indian one — and where a neural Indian voice exists it wins outright.
 */
export function scoreVoice(v: SpeechSynthesisVoice): number {
  const name = v.name.toLowerCase();
  const lang = v.lang?.toLowerCase() ?? '';
  if (!lang.startsWith('en')) return -1;

  // Known novelty/robotic voices are never acceptable, whatever else matches.
  if (/albert|bad news|bahh|bells|boing|bubbles|cellos|fred|jester|organ|superstar|trinoids|whisper|wobble|zarvox|compact/.test(name)) {
    return -1;
  }

  let score = qualityTier(name);

  /*
   * ACCENT, applied within the tier — and this ordering was deliberately reversed.
   *
   * en-IN used to win by a mile, on the reasoning that a candidate rehearsing a Cognizant
   * panel should hear the accent they will actually face. That reasoning was sound and the
   * result was not: the en-IN voices the platforms actually ship are the WEAKEST in their
   * range — Rishi and Veena are formant synths from a decade ago, Heera and Ravi barely
   * better — so ranking accent above quality reliably picked a robotic voice over a good
   * one. Told to choose, the product should sound like a person with a slightly wrong
   * accent, not like a machine with the right one.
   *
   * en-GB is LAST among the three by request. It is not a quality judgement — it is that a
   * British interviewer is the wrong character entirely for Indian campus placement, and it
   * lands as more incongruous than a neutral American voice does.
   *
   * This only decides the FALLBACK. When Fish is up nobody hears any of this; the roster in
   * TTS_VOICE_IDS is neutral-English and gender-verified against the catalogue.
   */
  if (lang === 'en-us') score += 12;
  else if (lang === 'en-in') score += 8;
  else if (lang === 'en-gb') score += 2;

  // Named Indian voices still break ties INSIDE a tier, which is where the original intent
  // survives: given two equally good voices, the one that sounds like the room wins. What
  // it can no longer do is drag a bad voice above a good one.
  const idx = INDIAN_VOICE_NAMES.findIndex((n) => name.includes(n));
  if (idx !== -1) score += (20 - idx) / 8;

  return score;
}

/**
 * Split text into utterance-sized chunks at sentence boundaries.
 *
 * One long utterance is read as an undifferentiated run, which is a large part
 * of why it sounds mechanical — the engine inserts a natural breath between
 * utterances but not reliably mid-string. Very short fragments are merged back
 * so the delivery doesn't become choppy.
 */
