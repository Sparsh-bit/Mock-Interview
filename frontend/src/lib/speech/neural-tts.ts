/**
 * Neural speech from the server — lib/speech/neural-tts.ts
 *
 * Plays audio synthesised by a real TTS vendor (ElevenLabs, Azure, Google) instead of the
 * browser's speechSynthesis. It is the single biggest change available to how a group
 * discussion feels: three voices that sound like people with opinions rather than one
 * screen reader at three pitches.
 *
 * IT IS AN ENHANCEMENT, NEVER A REQUIREMENT. Every function here fails soft, and the caller
 * is expected to fall back to speechSynthesis on `false`. That is not defensive habit — it
 * is the design:
 *
 *   * neural TTS is metered per CHARACTER and the daily budget can legitimately run out
 *     mid-round, at which point everyone continues on browser voices
 *   * it is a network round trip, so it can be slow or fail on the mobile connections this
 *     product's users are actually on
 *   * it is off by default, because on ElevenLabs' Creator tier a GD round of neural speech
 *     costs roughly twelve times every AI call in that round combined
 *
 * So a TTS outage must be incapable of breaking a discussion. The worst it may do is make
 * one sound worse.
 *
 * WHY AUDIO ELEMENTS RATHER THAN THE WEB AUDIO API. All this needs is "play these bytes,
 * tell me when they finish". An <audio> element's `ended` event does exactly that, and does
 * it more reliably than speechSynthesis' `onend` — which is the event the hands-free
 * microphone depends on to know when to start listening. Web Audio would buy scheduling
 * precision this does not need, at the cost of a context that browsers suspend until a user
 * gesture.
 */

import { getBrowserApiClient } from '@/lib/api';

/**
 * How a line is delivered. Mirrors TONE_PROSODY in backend/app/services/tts/base.py.
 *
 * Kept as a type rather than validated at runtime: an unrecognised name resolves to
 * neutral server-side, so drift between the two lists costs a flat line, never an error.
 */
export type SpeechTone = 'neutral' | 'asking' | 'correcting' | 'affirming' | 'aside';

/**
 * The same five, for BROWSER speech — a rate multiplier and a pitch offset.
 *
 * Needed separately because speechSynthesis has no equivalent of the server's prosody
 * field, and because the fallback is not a rare path: it is what every candidate hears the
 * moment the daily TTS budget is spent. A correction that sounds like a correction only
 * when the vendor is up is a feature that works in the demo and not in the product.
 *
 * Smaller numbers than the server's. speechSynthesis rate compounds with the persona tempo
 * and the voice's own base rate, and stacking three multipliers is how you end up with a
 * panelist who gabbles; the server applies tone to a single fixed baseline instead.
 */
export const BROWSER_TONE: Record<SpeechTone, { rate: number; pitch: number }> = {
  neutral: { rate: 1.0, pitch: 0 },
  asking: { rate: 0.97, pitch: 0 },
  // Lower as well as slower. Dropping pitch is most of what makes a line read as serious
  // rather than merely slow — slow on its own sounds uncertain, which is the opposite of
  // what somebody telling you that you are wrong sounds like.
  correcting: { rate: 0.92, pitch: -0.06 },
  affirming: { rate: 1.03, pitch: 0.04 },
  aside: { rate: 1.06, pitch: 0 },
};

export interface TTSStatus {
  enabled: boolean;
  provider: string | null;
  budget_remaining_usd: number;
  /** Which speakers have a voice configured. A missing one falls back individually. */
  voices: Record<string, boolean>;
}

/**
 * Is neural speech available right now?
 *
 * Asked once per round rather than discovered from a 503 on the first contribution, so a
 * round that is going to use browser voices does so from the start instead of stuttering
 * into it.
 */
export async function fetchTTSStatus(): Promise<TTSStatus | null> {
  try {
    const res = await getBrowserApiClient().get('/api/v1/tts/status');
    return res.data as TTSStatus;
  } catch {
    // Unreachable, unauthorised, or the route does not exist on this deploy. All mean the
    // same thing to the caller: use the browser.
    return null;
  }
}

/**
 * Fetch audio for one utterance, or null.
 *
 * `speaker` is a name — "Riya", "interviewer" — and the SERVER resolves it to a voice id.
 * The client deliberately cannot choose a voice: that is what keeps Meera female, and on a
 * metered vendor it is also what stops a caller selecting an expensive model.
 */
export async function fetchUtterance(
  speaker: string,
  text: string,
  tone?: SpeechTone,
): Promise<Blob | null> {
  const trimmed = text.trim();
  if (!trimmed) return null;
  try {
    const res = await getBrowserApiClient().post(
      '/api/v1/tts/speak',
      // A tone NAME, never prosody numbers — the server owns the mapping. Same reasoning as
      // the speaker name above: this is metered output, and the dial that decides how long
      // an utterance is does not belong in a bundle anyone can edit.
      { speaker, text: trimmed, tone },
      // Longer than the server's own 12s vendor timeout so the server is always the one to
      // give up first — then the failure carries a reason instead of being a bare abort.
      //
      // No responseType needed: parseBody in lib/api/client.ts already returns a Blob for
      // any content type that is not JSON or text, and this comes back as audio/mpeg.
      { timeout: 15_000 },
    );
    const blob = res.data as Blob;
    return blob && blob.size > 0 ? blob : null;
  } catch {
    // 402 (budget spent), 503 (vendor down), or a timeout. Same handling for all three.
    return null;
  }
}

/**
 * Play a blob to completion.
 *
 * Resolves when playback ends, errors, or the watchdog fires — never rejects, because a
 * caller awaiting this is in the middle of a discussion and a rejection would leave the
 * round stalled with no speaker.
 *
 * The watchdog is the same lesson as the speechSynthesis path: a media element that fails
 * to load can emit neither `ended` nor `error`, and an await on that never returns. Here
 * that would silence the panel for the rest of the round.
 */
export function playBlob(
  blob: Blob,
  register: (el: HTMLAudioElement) => void,
  /**
   * Playback rate, from the speaker's persona tempo.
   *
   * WHY THIS MATTERS. persona.ts gives each panelist a stable speaking tempo — the assertive
   * one 9% faster, the synthesiser 8% slower — and that was the main thing separating three
   * voices when they had to share one. Neural audio arrives as a finished file, so without
   * this the tempo differentiation is silently LOST the moment neural speech switches on, and
   * the panel gets less distinguishable rather than more.
   *
   * playbackRate keeps it. Clamped tight because a media element resamples rather than
   * pitch-shifting: past roughly ±12% the voice starts sounding sped-up rather than brisk,
   * which is worse than uniform.
   */
  rate = 1,
): Promise<void> {
  return new Promise<void>((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    let done = false;

    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      // Revoke, or every utterance in a 26-turn round leaks a blob URL for the life of the
      // page.
      URL.revokeObjectURL(url);
      resolve();
    };

    audio.playbackRate = Math.min(1.12, Math.max(0.88, rate));

    // Generous: it must never cut off real speech. An utterance is a couple of sentences, so
    // 30s is far past any legitimate length and still bounded.
    const timer = setTimeout(finish, 30_000);
    audio.onended = finish;
    audio.onerror = finish;

    register(audio);
    // play() rejects if the browser blocks autoplay. By the time a round is running the
    // candidate has clicked to start it, so the page has a gesture — but if it is ever
    // blocked, resolving immediately is right: the caller moves on rather than hanging.
    void audio.play().catch(finish);
  });
}
