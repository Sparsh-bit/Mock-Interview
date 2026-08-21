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
 * AND IT MAY ONLY DO THAT ONCE. That contract — enhancement, never requirement — is preserved
 * exactly, but it is now STICKY: the first failure of any kind turns neural speech off for the
 * rest of the round rather than letting each utterance re-attempt independently. The fallback
 * is not removed, it is made one-way. See the latch below for why a voice that keeps changing
 * back is worse than the worse of the two voices.
 *
 * WHY AUDIO ELEMENTS RATHER THAN THE WEB AUDIO API. All this needs is "play these bytes,
 * tell me when they finish". An <audio> element's `ended` event does exactly that, and does
 * it more reliably than speechSynthesis' `onend` — which is the event the hands-free
 * microphone depends on to know when to start listening. Web Audio would buy scheduling
 * precision this does not need, at the cost of a context that browsers suspend until a user
 * gesture.
 */

import { ApiError, getBrowserApiClient } from '@/lib/api';
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
 *
 * DELIBERATELY NOT EXPORTED. ttsStatusOnce is the only way to ask, because "once per round" has
 * to be a property of the module rather than a rule each caller remembers — the previous bug
 * was precisely a caller doing its own probing and its own bookkeeping. A second entry point
 * here would let someone reintroduce an unmemoized, unlatched probe without touching anything
 * that looks wrong.
 */
/**
 * How long the round is willing to wait to find out whether neural speech is on.
 *
 * This number is a DEADLINE, not a timeout guess. The caller awaits the answer before the
 * first word of the interview is spoken (see ttsStatusOnce), so every millisecond here is a
 * millisecond of silence a candidate might sit through. Past this point the round proceeds on
 * browser voices — worse-sounding, but decided, which is the whole point of the fix.
 *
 * 2.5s is chosen against what is actually happening in parallel: the first utterance is
 * already downstream of GET /interview/{id}/next and POST /api/v1/panel/turn, and that second
 * one is an LLM generation. So on any deploy that is awake this probe has finished long
 * before it is asked for, and 2.5s only ever bites on a cold backend — which is precisely the
 * case that used to produce the reported bug.
 */
const _STATUS_TIMEOUT_MS = 2_500;

async function fetchTTSStatus(): Promise<TTSStatus | null> {
  try {
    const res = await getBrowserApiClient().get('/api/v1/tts/status', {
      /*
       * NO RETRY, AND OUR OWN TIMEOUT, BOTH DELIBERATE.
       *
       * This is a GET, so without `retry: false` it inherits DEFAULT_RETRY_CONFIG — three
       * attempts, backing off to a 10s ceiling — on top of the client's 30s default timeout.
       * Against a backend that is cold or 502-ing, that is up to a minute of a request whose
       * whole job is to answer a yes/no question before anybody speaks. Meanwhile /next and
       * /panel/turn succeed on an app that woke up in between, the greeting goes out on
       * browser voices, this finally answers "yes", and every line after it switches to Fish.
       * That is exactly the reported "the voices changes" — caused by patience, not failure.
       *
       * An unanswered probe is not an error worth retrying. It is a "no" for this round.
       */
      timeout: _STATUS_TIMEOUT_MS,
      retry: false,
    });
    return res.data as TTSStatus;
  } catch {
    // Unreachable, unauthorised, or the route does not exist on this deploy. All mean the
    // same thing to the caller: use the browser.
    return null;
  }
}

/*
 * ONE PROBE PER ROUND, AND EVERY CALLER AWAITS THE SAME ANSWER.
 *
 * THE BUG THIS EXISTS FOR, reported verbatim: "in the starting of the interview the voices
 * changes and then it changed again to the old voices."
 *
 * The probe used to be fired from an effect in usePanelVoices with its result dropped into a
 * ref — `void fetchTTSStatus().then((s) => { neuralRef.current = !!s?.enabled })`. Nothing
 * awaited it. So the interview's first line read that ref while it was still `false`, spoke on
 * browser voices, and the lines after it — once the probe had landed — spoke on Fish. One
 * unsynchronised boolean, two different people saying consecutive sentences.
 *
 * Memoizing the promise is what makes "asked once" mean asked once even when several call
 * sites (speakAs, prefetchTurn, the mount effect) all want the answer in the same tick, and
 * what lets them AWAIT it instead of racing it.
 *
 * WHY THIS CANNOT DEADLOCK — the property the caller is relying on when it awaits this
 * before speaking, so it is worth stating rather than trusting:
 *
 *   1. fetchTTSStatus is try/catch → return null. It has no throw path, so this promise can
 *      never reject and an `await` on it can never propagate an error into the speech chain.
 *   2. It is raced against a timer that is already running. Even if the underlying fetch
 *      never settles — a hung socket, a proxy holding the connection open, a service worker
 *      that swallowed it — the race settles at the cap. "Slow" and "hung" are not the same
 *      failure, and only the race covers the second one.
 *   3. The result is memoized, so N awaiters share one settled value: the tenth line of the
 *      interview pays nothing at all, not even a cache lookup round trip.
 *
 * The worst case is therefore bounded at _STATUS_TIMEOUT_MS once per round, and its outcome
 * is a decision (browser voices, for the whole round) rather than a stall.
 */
let _statusPromise: Promise<TTSStatus | null> | null = null;

export function ttsStatusOnce(): Promise<TTSStatus | null> {
  _statusPromise ??= Promise.race([
    fetchTTSStatus(),
    new Promise<null>((resolve) => {
      setTimeout(() => resolve(null), _STATUS_TIMEOUT_MS);
    }),
  ]);
  return _statusPromise;
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

/*
 * THE ONE-WAY DEGRADE LATCH.
 *
 * The second half of "and then it changed again to the old voices". Once neural speech was on,
 * every utterance made its own independent attempt, and every kind of failure — a 402 when
 * Fish's own credit ran out or the daily budget was spent, a 503 when the vendor timed out at
 * 12s, a client-side timeout — produced a single browser-voiced line and left the decision
 * untouched. So line N was Fish, line N+1 was the system voice, line N+2 was Fish again. The
 * candidate is not hearing a degraded panel; they are hearing a different person every other
 * sentence, mid-question, while trying to answer one.
 *
 * There is a specific production shape that makes this deterministic rather than unlucky:
 * api/v1/tts.py checks the response CACHE before the daily budget, on purpose, so that a hit
 * stays free. Past the budget, therefore, the fixed question bank still returns 200 neural
 * audio while unique AI-written panel prose 402s. Neural and browser then alternate line by
 * line for the rest of the interview, by design, with nothing failing anywhere.
 *
 * WHY OSCILLATION IS WORSE THAN EITHER STATE ON ITS OWN. An all-Fish interview sounds like a
 * panel. An all-browser interview sounds like a screen reader, which is worse but is at least
 * a consistent, legible thing: one voice, one room, and the candidate stops noticing it inside
 * a minute. Alternating between them is worse than the worse of the two, because a change of
 * voice is the cue humans use for a change of SPEAKER. Anil asking a follow-up in a different
 * voice from the question he just asked reads as a new interviewer joining, so the candidate
 * spends attention re-identifying the room instead of answering — during the one activity
 * where their whole attention is the thing being measured. Consistently worse audio costs
 * quality; inconsistent audio costs comprehension.
 *
 * So the FIRST failure of any class closes the round, permanently. One rule, no counters, and
 * therefore provably non-oscillating: there is no code path that sets this back to false.
 * Allowing "one transient strike" was considered and rejected — a counter is a second piece of
 * state that has to be right, and inside a live interview a candidate would rather hear one
 * consistent voice than a better voice that changes every other line.
 *
 * WHAT THIS COSTS, so that whoever reads the spend graph next month is not surprised: because
 * the server serves cache hits even past the budget, one transient blip now forfeits audio
 * that has ALREADY BEEN PAID FOR on the fixed question bank for the remainder of the
 * interview. That is a real regression in value-per-rupee, accepted knowingly under the
 * consistency contract above. It is not an oversight.
 */
let _neuralOff = false;

/** Has this round given up on neural speech? Monotonic within a round. */
export function neuralOff(): boolean {
  return _neuralOff;
}

/**
 * Give up on neural speech for the rest of the round.
 *
 * `budget` is a 402 — a permanent condition until midnight UTC. `vendor` is everything else:
 * 503, a client timeout, or a 200 carrying no audio. They are deliberately handled
 * identically, because the difference only matters to a retry policy and there is no retry
 * here by construction.
 *
 * There is no third reason for an unconfigured speaker. usePanelVoices reads
 * TTSStatus.voices and never asks for a speaker the server has no voice id for, so that case
 * cannot reach a request at all — it degrades that one speaker from their first line instead
 * of the whole round, which is what the per-speaker map is for.
 *
 * `_inflight` is emptied as part of closing the latch, and that is load-bearing rather than
 * tidiness: a turn is prefetched three lines at a time, so without this a request that was
 * already in flight when the latch closed would still resolve with good audio and hand one
 * neural line to a round that has committed to browser voices — reintroducing the exact
 * alternation the latch exists to stop, at the worst possible moment.
 */
export function degradeNeural(reason: 'budget' | 'vendor'): void {
  if (_neuralOff) return;
  _neuralOff = true;
  _inflight.clear();
  // INFO, NOT WARN, AND THE LEVEL IS THE POINT. Once per round, not once per line —
  // whoever reads a candidate's console after a complaint about the voices needs this line
  // and its reason.
  //
  // But a spent budget is a NORMAL operating state for a metered vendor, and this module's
  // own header is explicit that neural speech is an enhancement whose loss may only make a
  // round sound worse. Logging a designed-for degradation at warn level makes a healthy
  // system look like a broken one — which is a mistake this codebase has already made and
  // fixed once, where three refused /admin/overview probes per page load were logged as
  // warnings for every ordinary user (see components/account-isolation.test.ts). Same
  // reasoning, same level.
  console.info(
    `[tts] neural speech is off for the rest of this round (${reason}); browser voices from here.`,
  );
}

/**
 * Start a new round: forget the probe and the degrade.
 *
 * REQUIRED, NOT HYGIENE. `_statusPromise` and `_neuralOff` are module scope, which makes
 * "round" mean "for as long as this module stays loaded" — and a second interview started by
 * client-side navigation does not reload it. Without this call, one 402 in one interview
 * silently puts every later interview in the same tab on browser voices, and the user's report
 * becomes "the voices are bad now" with nothing in the code having changed. usePanelVoices
 * calls it when it mounts, which is exactly once per round.
 */
export function resetSpeechRound(): void {
  _statusPromise = null;
  _neuralOff = false;
  _inflight.clear();
}

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
  // The round has already committed to browser voices. Warming audio it will never play would
  // bill a metered vendor for nothing.
  if (_neuralOff) return;
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
  // Checked here as well as in the caller, so there is no ordering of calls that can slip a
  // neural line into a round that has degraded — including a line whose audio was already
  // warm when the latch closed.
  if (_neuralOff) return null;
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
    if (blob && blob.size > 0) return blob;
    // A 200 with no bytes in it. Rare, and a vendor or proxy fault rather than a budget one —
    // but still a line that cannot be spoken neurally, so it closes the round like any other.
    degradeNeural('vendor');
    return null;
  } catch (err) {
    /*
     * 402 (budget spent), 503 (vendor down), or a timeout — and the status code is READ here
     * rather than discarded, which it was: this catch used to be a bare `catch { return null }`
     * that collapsed all three into one indistinguishable null. That is why the caller could
     * not latch even if it had wanted to; it had no way to tell a permanent condition from a
     * transient one, and the information was sitting on the ApiError it was throwing away.
     *
     * Both reasons latch. They are separated only so the console line says which happened.
     */
    degradeNeural(err instanceof ApiError && err.status === 402 ? 'budget' : 'vendor');
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
