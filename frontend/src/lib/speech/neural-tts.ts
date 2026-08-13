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
import { toSpokenForm } from '@/lib/speech/speakable';

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
/*
 * IN-FLIGHT AUDIO, KEYED BY EXACTLY WHAT WAS ASKED FOR.
 *
 * Synthesis is the slowest thing in the room: Fish takes around three and a half seconds for
 * a sentence, and a panel turn is two or three sentences. Fetched one at a time, in order,
 * that is ten seconds of a panel that is supposedly mid-conversation — and the candidate
 * hears the gap as the software thinking, which is the single most artificial thing about it.
 *
 * So the caller can start every line of a turn at once, the moment the turn arrives, and by
 * the time the first speaker finishes the second one's audio is already in memory. The map
 * holds the PROMISE rather than the blob, so a line that is prefetched and then requested
 * while still in flight joins the existing request instead of paying for a second one.
 *
 * Bounded, because these are audio blobs and an interview is long. Oldest out first; a line
 * evicted before it plays simply re-fetches, which is the old behaviour rather than a fault.
 */
const _inflight = new Map<string, Promise<Blob | null>>();
const _MAX_INFLIGHT = 24;

/**
 * THE WRITTEN LINE IS TURNED INTO THE SPOKEN ONE *HERE*, AND ONLY HERE.
 *
 * This module used to take whatever text the caller handed it, and the two callers handed it
 * different things. `speakAs` sent `toSpokenForm(text)`, because that is what should reach the
 * vendor; `prefetchTurn` sent the raw `text`, because that is what it had. Both then keyed the
 * in-flight map on the string they happened to pass.
 *
 * So the keys never matched — for any line containing an operator or a spelled-out acronym,
 * which in a Java interview is most of them. Every consequence of that was invisible and bad:
 *
 *   - the prefetch was a guaranteed miss, so the feature bought nothing at all
 *   - the real fetch started COLD, on the critical path, and the candidate waited the full
 *     ~3.5s Fish takes per line — the exact gap prefetching was written to remove
 *   - and the wasted prefetch still completed, so every line was synthesised TWICE and
 *     billed twice against a metered vendor and the daily budget
 *
 * Normalising at this boundary rather than in the callers is what makes that unfixable-by-
 * accident: there is now no text a caller can pass that produces a key different from the one
 * the fetch uses, because the caller's string is no longer what either is derived from.
 */
function _spoken(text: string): string {
  return toSpokenForm(text).trim();
}

function _key(speaker: string, spokenText: string, tone?: SpeechTone): string {
  return `${speaker}|${tone ?? 'neutral'}|${spokenText}`;
}

/**
 * Start fetching a line's audio without waiting for it.
 *
 * Call this for every line of a turn as soon as the turn arrives. Errors are swallowed here
 * exactly as they are in fetchUtterance — a prefetch that fails must be indistinguishable
 * from one that was never made, or a warm-up would be able to break a round.
 *
 * Pass the line AS WRITTEN. Converting it for the ear is this module's job — see _spoken.
 */
export function prefetchUtterance(speaker: string, text: string, tone?: SpeechTone): void {
  const spoken = _spoken(text);
  if (!spoken) return;
  const k = _key(speaker, spoken, tone);
  if (_inflight.has(k)) return;
  if (_inflight.size >= _MAX_INFLIGHT) {
    const oldest = _inflight.keys().next().value;
    if (oldest !== undefined) _inflight.delete(oldest);
  }
  _inflight.set(k, _fetchNow(speaker, spoken, tone));
}

/** Pass the line AS WRITTEN, exactly as for prefetchUtterance. */
export async function fetchUtterance(
  speaker: string,
  text: string,
  tone?: SpeechTone,
): Promise<Blob | null> {
  const spoken = _spoken(text);
  if (!spoken) return null;
  const k = _key(speaker, spoken, tone);
  const warm = _inflight.get(k);
  if (warm) {
    // Consumed once. Keeping it would hold every line of the interview in memory for the
    // sake of a repeat that does not happen — the server-side cache already covers the case
    // where the same sentence is genuinely said twice.
    _inflight.delete(k);
    return warm;
  }
  return _fetchNow(speaker, spoken, tone);
}

async function _fetchNow(
  speaker: string,
  /** Already through _spoken — this is the string that goes to the vendor verbatim. */
  spoken: string,
  tone?: SpeechTone,
): Promise<Blob | null> {
  try {
    const res = await getBrowserApiClient().post(
      '/api/v1/tts/speak',
      // A tone NAME, never prosody numbers — the server owns the mapping. Same reasoning as
      // the speaker name above: this is metered output, and the dial that decides how long
      // an utterance is does not belong in a bundle anyone can edit.
      { speaker, text: spoken, tone },
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
   * WHY THIS EXISTS. persona.ts gives each panelist a stable speaking tempo, and that was the
   * main thing separating three voices back when they had to share one. Neural audio arrives
   * as a finished file, so without this the tempo differentiation would be silently LOST the
   * moment neural speech switched on.
   *
   * WHY IT IS NOW APPLIED AT A FRACTION OF ITS STRENGTH. On the neural path this multiplier
   * is the SECOND speed adjustment the audio receives — the server has already applied the
   * tone's own speed through the vendor's prosody field, which is real synthesis rather than
   * resampling. Stacking a media-element playbackRate on top of that is what pushed the
   * assertive panelist to roughly 1.18 and produced the reported "disturbed" voice: a
   * resampled 18% is audibly wrong in a way that a synthesised 18% is not.
   *
   * The two paths also do not need the same amount of help. Neural voices are separate voices
   * — different timbre, different speaker entirely — so they are already tellable apart and
   * tempo only has to hint. The BROWSER fallback frequently has to put two panelists on one
   * system voice, and there tempo is doing the real work; that path keeps the full multiplier,
   * applied in useSpeech.ts.
   *
   * So the deviation from 1.0 is damped to 40% here, then clamped to ±5% — inside the range
   * where resampling stays inaudible, rather than at the ±12% edge where it stops being.
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

    audio.playbackRate = Math.min(1.05, Math.max(0.95, 1 + (rate - 1) * 0.4));

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
