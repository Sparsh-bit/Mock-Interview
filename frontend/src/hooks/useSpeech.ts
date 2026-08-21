'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PauseEvent } from '@/lib/speech/delivery';
import { toSpokenForm } from '@/lib/speech/speakable';
import { correctTechnicalTerms } from '@/lib/speech/vocabulary';
import {
  allocatePanelVoices,
  type PanelSpeaker,
  type PanelVoice,
} from '@/lib/speech/panel-voices';
import { personaFor } from '@/lib/speech/persona';
import {
  BROWSER_TONE,
  fetchUtterance,
  neuralOff,
  playBlob,
  prefetchUtterance,
  resetSpeechRound,
  ttsStatusOnce,
  type SpeechTone,
} from '@/lib/speech/neural-tts';
import { shapingFor, toProsodyChunks } from '@/lib/speech/prosody';
// qualityTier is also re-exported at the bottom of this file, but `export … from`
// creates no local binding, so it has to be imported here to be callable.
import { qualityTier, scoreVoice } from '@/lib/speech/voice-ranking';

// Silence longer than this (between recognized speech) counts as a pause worth
// surfacing — shorter gaps are natural speech rhythm.
const PAUSE_THRESHOLD_MS = 1800;

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

/**
 * Speak one utterance and resolve when it is done.
 *
 * THE WATCHDOG IS NOT OPTIONAL. Both speech paths now AWAIT each utterance so they
 * can hold silence between them, and an utterance the engine drops without firing
 * `end` OR `error` parks the loop forever. That happens for real: on iOS Safari
 * before the page's first gesture-initiated speak(), and on Android Chrome when
 * the tab backgrounds mid-queue. In the interviewer path a parked loop is
 * survivable. In usePanelVoices it parks the shared chain and the panel goes
 * silent for the rest of the round, which is the worst failure this layer has.
 *
 * The budget is generous on purpose — it must never cut off real speech. ~11
 * characters a second is roughly half the slowest rate we ever set, plus 3s of
 * headroom for a cloud voice's fetch.
 */
function speakOnce(
  utter: SpeechSynthesisUtterance,
  onStart?: () => void,
): Promise<void> {
  return new Promise<void>((resolve) => {
    let done = false;
    let started = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      clearTimeout(startFallback);
      // A voice that errors or is cancelled before speaking still has to release the
      // caller's reveal, or a failed utterance would leave the line permanently hidden.
      if (!started) {
        started = true;
        onStart?.();
      }
      resolve();
    };
    const timer = setTimeout(finish, 3000 + utter.text.length * 90);

    /*
     * FIRED WHEN THE VOICE ACTUALLY STARTS, which is what the caller reveals text on.
     *
     * The neural path already waits for its audio before showing the words. This is the
     * BROWSER path, and it had the original bug the whole time: the line was revealed, and
     * then speechSynthesis got around to speaking it. On a cold engine — the first utterance
     * of a session, a Windows machine loading a voice, anything on Safari — that gap is
     * comfortably over a second, so the question arrives on screen and the voice follows.
     *
     * This is the path most people are on until Fish is configured, so "the questions are
     * coming first on the screen and then the AI speaks it" was still true for them after
     * the neural fix.
     */
    utter.onstart = () => {
      if (started) return;
      started = true;
      onStart?.();
    };
    // Some engines never fire onstart at all — it is optional in the spec and Safari has
    // historically skipped it. Reveal anyway after a beat rather than never.
    const startFallback = setTimeout(() => {
      if (started) return;
      started = true;
      onStart?.();
    }, 1200);

    utter.onend = finish;
    utter.onerror = finish;
    window.speechSynthesis.speak(utter);
  });
}

/**
 * Sentinel for "the candidate holds the floor", so the next panelist pays a
 * handover beat rather than continuing as if the candidate never spoke.
 */
const CANDIDATE_FLOOR = '__candidate__';

/**
 * Extra silence when a question was left hanging. A panel that fires its next
 * contribution 0ms after asking you something never actually asked you.
 */
const QUESTION_HANDOVER_MS = 450;

/** Is this voice cloud-backed? Decides chunking and whether to slow it down. */
function isNetworkVoice(voice: SpeechSynthesisVoice | null): boolean {
  // qualityTier does not lowercase internally — its other caller, scoreVoice,
  // lowercases before calling. Passing a raw name scores every voice as plain
  // local synthesis.
  return voice ? qualityTier(voice.name.toLowerCase()) >= 800 : false;
}

/* ─── Types for the (non-standardised) Web Speech API ──────────────────────── */
interface SpeechRecognitionResultLike {
  0: { transcript: string; confidence?: number };
  isFinal: boolean;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: { length: number; [i: number]: SpeechRecognitionResultLike };
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives?: number;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  //: Audio-flow events. Chrome fires both; Safari fires speechstart. Optional
  //: because they are not in every engine — a missing one costs nothing, since
  //: onresult sets the same flag.
  onsoundstart?: (() => void) | null;
  onspeechstart?: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/**
 * Speech-to-text via the browser's Web Speech API (Chrome/Edge/Safari).
 * Feature-detected: `supported` is false where unavailable so callers can
 * fall back to typing. Accumulates finalized transcript; exposes interim
 * text live while the candidate is still speaking.
 */
export function useSpeechRecognition() {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [interim, setInterim] = useState('');
  //: A message the UI can show when recognition genuinely cannot continue —
  //: microphone permission denied, no device. Previously an error just set
  //: listening=false and said nothing, so a candidate whose mic was blocked saw
  //: an idle button and no explanation.
  const [error, setError] = useState<string | null>(null);
  //: Mean confidence of the finalised results, 0-1, or null when the engine does
  //: not report it. Low confidence is why a transcript can read as nonsense —
  //: surfacing it lets the UI tell the candidate to repeat rather than letting a
  //: garbled answer be scored as if it were what they said.
  const [confidence, setConfidence] = useState<number | null>(null);
  /**
   * Has ANY audio above the engine's noise floor arrived since the mic opened?
   *
   * This is the only way to tell "thinking in silence" apart from "system input
   * muted or the wrong device selected". Neither raises an error event, and
   * watching the transcript cannot separate them — a timer on transcript growth
   * accuses a candidate composing an answer of having a broken microphone, at the
   * moment of maximum concentration. Sound is the signal; words are not.
   */
  const [heardSound, setHeardSound] = useState(false);
  // Pauses (silences) detected while recording, tied to word positions in the
  // finalized transcript so the UI can mark exactly where they happened.
  const [pauses, setPauses] = useState<PauseEvent[]>([]);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  //: Does the CANDIDATE still want to be recording? Distinct from whether the
  //: engine happens to be running, which is the whole point — see the restart
  //: logic in `onend`.
  const wantListeningRef = useRef(false);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const confidenceSumRef = useRef(0);
  const confidenceCountRef = useRef(0);
  // Timing state for pause detection (refs so handlers see live values).
  const lastActivityRef = useRef<number>(0);
  const wordCountRef = useRef<number>(0);

  useEffect(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    setSupported(true);
    const rec = new Ctor();
    // en-IN, not en-US: the candidates are Indian, and the recogniser
    // transcribes Indian-accented English markedly better with this hint.
    rec.lang = 'en-IN';
    rec.continuous = true;
    rec.interimResults = true;
    // Ask for alternatives so the engine reports a confidence figure it is willing
    // to stand behind. We still take the top result — picking a lower-ranked
    // alternative would be guessing — but the confidence is what lets the UI warn
    // that an answer may have been misheard.
    rec.maxAlternatives = 3;
    // Proof that audio is reaching the engine, from whichever of these the
    // platform implements.
    rec.onsoundstart = () => setHeardSound(true);
    rec.onspeechstart = () => setHeardSound(true);

    rec.onresult = (e) => {
      // Also here, so an engine that fires neither event above still clears the
      // "we cannot hear you" warning as soon as anything is recognised.
      setHeardSound(true);
      const now = Date.now();
      // Gap since the last recognized speech → a pause. Attributed to the
      // current word position so we can render a marker right there.
      if (lastActivityRef.current) {
        const gapMs = now - lastActivityRef.current;
        if (gapMs >= PAUSE_THRESHOLD_MS) {
          const seconds = Math.round(gapMs / 1000);
          const at = wordCountRef.current;
          setPauses((prev) => [...prev, { wordIndex: at, seconds }]);
        }
      }
      lastActivityRef.current = now;

      let finalChunk = '';
      let interimChunk = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          finalChunk += r[0].transcript;
          const c = r[0].confidence;
          // Chrome reports 0 for some results rather than omitting the field;
          // averaging those in would drag the figure to meaningless.
          if (typeof c === 'number' && c > 0) {
            confidenceSumRef.current += c;
            confidenceCountRef.current += 1;
          }
        } else {
          interimChunk += r[0].transcript;
        }
      }
      if (finalChunk) {
        // Correct the technical terms before the text is ever stored or shown.
        // The recogniser has no domain vocabulary, so "HashMap" arrives as
        // "hash map" and "JVM" as "jvm" — see lib/speech/vocabulary.ts.
        const clean = correctTechnicalTerms(finalChunk.trim());
        wordCountRef.current += clean.split(/\s+/).filter(Boolean).length;
        setTranscript((prev) => (prev ? prev + ' ' : '') + clean);
        if (confidenceCountRef.current > 0) {
          setConfidence(confidenceSumRef.current / confidenceCountRef.current);
        }
      }
      setInterim(interimChunk);
    };
    /**
     * Errors, split by whether they are recoverable.
     *
     * `no-speech` and `aborted` are routine — Chrome raises no-speech whenever a
     * candidate thinks for a moment, and aborted whenever we call stop(). Treating
     * them as fatal is what made the mic die mid-answer. The genuinely fatal ones
     * are permission and hardware, and those are the ones worth telling the
     * candidate about.
     */
    rec.onerror = (e) => {
      const kind = e.error;
      if (kind === 'not-allowed' || kind === 'service-not-allowed') {
        wantListeningRef.current = false;
        setError('Microphone access is blocked. Allow it in your browser settings, or type your answer instead.');
        setListening(false);
        return;
      }
      if (kind === 'audio-capture') {
        wantListeningRef.current = false;
        setError('No microphone found. Plug one in, or type your answer instead.');
        setListening(false);
        return;
      }
      // no-speech, aborted, network — transient. onend handles the restart.
    };

    /**
     * THE FIX FOR "IT GETS CONFUSED WHAT I AM SAYING".
     *
     * Chrome ends a recognition session on its own after a few seconds of silence,
     * `continuous = true` notwithstanding. This handler used to just set
     * listening=false — so the moment a candidate paused to think, the engine
     * stopped, the mic button went idle, and every word after that pause was
     * never transcribed. The answer that got submitted was whatever they said
     * before their first pause, which reads as the software mishearing them when
     * it had actually stopped listening.
     *
     * So: if the candidate has not pressed stop, start it again. The small delay
     * matters — calling start() synchronously inside onend throws
     * InvalidStateError because the engine has not finished tearing down.
     */
    rec.onend = () => {
      if (!wantListeningRef.current) {
        setListening(false);
        return;
      }
      restartTimerRef.current = setTimeout(() => {
        if (!wantListeningRef.current) return;
        try {
          rec.start();
        } catch {
          // Already running, or torn down mid-restart. Either way the next
          // onend will try again while the candidate still wants to record.
        }
      }, 250);
    };

    recognitionRef.current = rec;
    return () => {
      wantListeningRef.current = false;
      if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
      rec.onresult = null;
      rec.onerror = null;
      rec.onend = null;
      rec.onsoundstart = null;
      rec.onspeechstart = null;
      try { rec.stop(); } catch { /* already stopped */ }
    };
  }, []);

  const start = useCallback(() => {
    if (!recognitionRef.current || listening) return;
    wantListeningRef.current = true;
    setError(null);
    setInterim('');
    setHeardSound(false);
    // Reset the pause clock so the first utterance isn't counted as a pause.
    lastActivityRef.current = Date.now();
    try {
      recognitionRef.current.start();
      setListening(true);
    } catch { /* start() throws if already running — ignore */ }
  }, [listening]);

  const stop = useCallback(() => {
    // Clear intent FIRST, or the onend handler restarts the engine we just asked
    // to stop.
    wantListeningRef.current = false;
    if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
    recognitionRef.current?.stop();
    setListening(false);
  }, []);

  const reset = useCallback(() => {
    setTranscript('');
    setInterim('');
    setPauses([]);
    setError(null);
    setConfidence(null);
    setHeardSound(false);
    lastActivityRef.current = 0;
    wordCountRef.current = 0;
    confidenceSumRef.current = 0;
    confidenceCountRef.current = 0;
  }, []);

  return {
    supported, listening, transcript, interim, pauses, error, confidence, heardSound,
    start, stop, reset,
  };
}

// Voice ranking lives in lib/speech/voice-ranking.ts — see the note there about
// the import cycle. Re-exported so existing callers and tests are unaffected.
export { INDIAN_VOICE_NAMES, qualityTier } from '@/lib/speech/voice-ranking';
export { scoreVoice };

export function toSpeechChunks(text: string, minChars = 12): string[] {
  const sentences = text
    .replace(/\s+/g, ' ')
    .trim()
    .split(/(?<=[.!?])\s+/)
    .filter(Boolean);

  const chunks: string[] = [];
  for (const sentence of sentences) {
    const last = chunks[chunks.length - 1];
    // Merge a stub onto the previous chunk rather than speaking it alone. Only
    // the incoming sentence's length matters — testing the previous chunk too
    // chained normal sentences together and undid the per-sentence pacing.
    if (last && (sentence.length < minChars || last.length < minChars)) {
      chunks[chunks.length - 1] = `${last} ${sentence}`;
    } else {
      chunks.push(sentence);
    }
  }
  return chunks.length ? chunks : [text];
}

/**
 * Text-to-speech via the browser's SpeechSynthesis API. Used to read the
 * interviewer's question aloud in voice mode. Auto-selects the best-sounding
 * installed voice and lets the caller override it.
 */
export function useSpeechSynthesis() {
  const [supported, setSupported] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceURI, setVoiceURI] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    setSupported(true);

    const loadVoices = () => {
      const all = window.speechSynthesis.getVoices().filter((v) => v.lang?.toLowerCase().startsWith('en'));
      if (!all.length) return;
      const ranked = [...all].sort((a, b) => scoreVoice(b) - scoreVoice(a));
      setVoices(ranked);
      // Only auto-pick if the user hasn't chosen one yet.
      setVoiceURI((current) => current ?? ranked[0]?.voiceURI ?? null);
    };

    loadVoices();
    // Voices load asynchronously in most browsers.
    window.speechSynthesis.addEventListener('voiceschanged', loadVoices);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', loadVoices);
  }, []);

  /**
   * Which generation of playback is current. Bumped by `speak` and `cancel`.
   *
   * Bumping in `speak` is correct HERE, unlike in usePanelVoices: there is one
   * interviewer, and a new question supersedes the previous one outright. Without
   * it, two overlapping calls — `speak` is called from an effect on question
   * change — interleave, because cancel() resolves the first loop's pending
   * utterance and it then carries on reading the previous question.
   */
  const genRef = useRef(0);

  const speak = useCallback(
    (text: string) => {
      if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();
      const gen = ++genRef.current;
      const stale = () => genRef.current !== gen;

      const chosen =
        window.speechSynthesis.getVoices().find((v) => v.voiceURI === voiceURI) ?? null;
      // Replaces an inline /natural|online|google/ test, so the interviewer and the
      // GD panel now agree on what counts as a neural voice.
      const network = isNetworkVoice(chosen);
      // Neural voices are already well paced; slowing them is what makes them
      // sound artificial. Local synthesis needs the extra room to stay legible.
      const baseRate = network ? 1.0 : 0.92;
      // finalPauseMs 250: unlike the panel there is no next speaker whose lead-in
      // owns the gap after the last sentence, so a statement would otherwise end
      // abruptly the moment the audio stops.
      // Same spoken-form pass as the panel path. This is the single-voice fallback used when
      // the panel is unavailable, and it reads the same questions — so it hit the same
      // "equal equal" bug and would have kept hitting it.
      const chunks = toProsodyChunks(toSpokenForm(text), {
        networkVoice: network,
        finalPauseMs: 250,
      });

      void (async () => {
        for (let i = 0; i < chunks.length; i++) {
          if (stale()) return;
          const c = chunks[i];
          const utter = new SpeechSynthesisUtterance(c.text);
          if (chosen) {
            utter.voice = chosen;
            utter.lang = chosen.lang;
          } else {
            // Neutral English, not en-IN. Some engines pick a variant from the lang hint
            // alone even with no matching voice object, and the en-IN variants they ship
            // are the oldest formant synths in the range — see the accent note in
            // voice-ranking.ts. The RECOGNISER stays en-IN: that one is listening to a real
            // Indian speaker and needs the right model. This one is only choosing an accent
            // to speak in, and a good neutral voice beats a robotic local one.
            utter.lang = 'en-US';
          }
          // The interviewer slows on the question itself and on the clause they
          // end on. That is the "your turn" cue; without it a candidate is
          // guessing when to start talking. Pitch stays flat — a question lift is
          // both inaudible at any safe size and ignored outright by cloud voices.
          utter.rate = Math.min(1.35, Math.max(0.7, Math.round(baseRate * shapingFor(c) * 100) / 100));
          utter.pitch = 1.0;
          // `speaking` is driven by onstart, as it already was. What IS fixed here:
          // the old code attached `onerror = () => setSpeaking(false)` to EVERY
          // chunk, so one failed utterance mid-queue reported the interviewer as
          // finished while the rest of the question was still audible. speakOnce
          // resolves on error instead, and only the loop's exit clears the flag.
          if (i === 0) {
            utter.onstart = () => {
              if (!stale()) setSpeaking(true);
            };
          }
          await speakOnce(utter);
          if (c.pauseAfterMs > 0 && !stale()) await sleep(c.pauseAfterMs);
        }
        if (!stale()) setSpeaking(false);
      })();
    },
    [voiceURI]
  );

  const cancel = useCallback(() => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    genRef.current += 1;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  // The single voice actually in use, for display. Resolved from the live voice
  // list because `voices` state can lag the engine's async load.
  const activeVoice =
    typeof window !== 'undefined' && 'speechSynthesis' in window && voiceURI
      ? (window.speechSynthesis.getVoices().find((v) => v.voiceURI === voiceURI) ?? null)
      : null;

  return { supported, speaking, speak, cancel, voices, voiceURI, setVoiceURI, activeVoice };
}

/* ─── Group-discussion panel voices ────────────────────────────────────────── */

/**
 * Gives each GD panelist their own voice and plays their turns one at a time.
 *
 * TWO REQUIREMENTS THIS EXISTS TO MEET, both of which the GD round previously
 * failed because it spoke nothing aloud at all:
 *
 *   THREE DIFFERENT VOICES, gender-matched to the name. Delegated to
 *   `allocatePanelVoices`, which is pure and tested — including against the
 *   hardware that only has one usable voice.
 *
 *   ONE PERSON SPEAKS AT A TIME. This is a queue, not a set of parallel calls.
 *   `speechSynthesis` will happily accept three utterances at once and interleave
 *   them, which sounds like a crowd rather than a discussion and makes the round
 *   impossible to follow. Each turn waits for the previous one to finish.
 *
 * `speakingNow` is the name of whoever currently holds the floor, which the UI
 * uses to show who is talking — and, by being null, who is listening.
 */
/**
 * What this round decided about voices. Resolved once, then never revisited.
 *
 * It is a plan rather than a boolean because there are three separate questions and they have
 * different answers: is neural speech on at all, which vendor is it (for the UI to say so),
 * and which individual speakers have a voice id on the server. Collapsing them into one flag
 * is what made a partly-configured panel behave as though it were fully broken, one 503 at a
 * time.
 */
type RoundVoicePlan = {
  neural: boolean;
  provider: string | null;
  /**
   * Lowercased names of speakers the server can voice, or null for "the server told us
   * nothing about individual speakers, so try everyone" — see resolveRoundVoice.
   */
  neuralSpeakers: Set<string> | null;
};

/**
 * Longest the browser path will wait for the real voice list before speaking anyway.
 *
 * Only the BROWSER path ever waits: it is the only one that reads voiceMap, so a round on
 * neural audio pays nothing for this. And the wait overlaps the speaker's handover beat
 * (90-970ms), so in practice most of it is already being spent on silence that has to happen
 * regardless.
 *
 * The alternative to waiting is not "speak sooner", it is "speak in the wrong voice and then
 * change" — which is the flip this fix exists to remove.
 */
const ALLOCATION_WAIT_MS = 1200;

export function usePanelVoices(
  panel: Array<{ name: string; gender: string; stance?: string }>,
) {
  const [voiceMap, setVoiceMap] = useState<Map<string, PanelVoice>>(new Map());
  const [speakingNow, setSpeakingNow] = useState<string | null>(null);
  //: Has the floor but has not started yet — the handover beat. Kept separate from
  //: speakingNow because claiming a voice is audible during 90-970ms of silence is
  //: a worse lie than showing nothing.
  const [takingFloor, setTakingFloor] = useState<string | null>(null);

  //: Serialises playback. Every speakAs chains onto this promise, so N calls in
  //: one render still play in order rather than on top of each other.
  const chainRef = useRef<Promise<void>>(Promise.resolve());
  /**
   * Which generation of playback is current. Bumped ONLY by cancelAll.
   *
   * A boolean was wrong, and subtly. `speakAs` has to mark itself live at call
   * time, so with a flag it wrote `active = true` synchronously — meaning
   * cancelAll() followed by any speakAs in the same tick flipped the flag back on
   * and the CANCELLED run woke up at its next await and finished speaking over the
   * candidate. A counter cannot be un-cancelled: each run captures the generation
   * it was queued in and stops the moment that is no longer current.
   *
   * speakAs must never bump it. Bumping on queue would make the second
   * contribution of one panel turn cancel the first.
   */
  const genRef = useRef(0);

  /**
   * THE ROUND'S VOICE IDENTITY, AS A PROMISE RATHER THAN A FLAG.
   *
   * THE BUG, reported verbatim: "in the starting of the interview the voices changes and then
   * it changed again to the old voices."
   *
   * This used to be `const neuralRef = useRef(false)`, written once, optimistically, from a
   * fire-and-forget effect — and read fresh on every single utterance. Two failures came out
   * of that one line:
   *
   *   THE FIRST LINE RACED THE PROBE. Nothing awaited the fetch, so the greeting read `false`,
   *   spoke on browser voices, and by the second line the probe had landed and the panel
   *   switched to Fish. "The voices changes."
   *
   *   AND NOTHING LATCHED. The ref was never written false by any failure, so a single 402 or
   *   503 downgraded ONE line and left the next one trying again. "And then it changed again
   *   to the old voices" — over and over, for the rest of the interview.
   *
   * A promise fixes both, because it is the only shape that can be AWAITED by the thing that
   * needs the answer. Resolved once per round, before anybody speaks; the degrade latch in
   * neural-tts.ts makes what happens after monotonic.
   */
  const planRef = useRef<Promise<RoundVoicePlan> | null>(null);
  //: The audio element currently playing, so cancelAll can stop it. Browser speech is
  //: cancelled through speechSynthesis.cancel(); an <audio> element is not.
  const audioRef = useRef<HTMLAudioElement | null>(null);

  //: Who spoke last, so a lead-in beat is only spent on an actual handover.
  const lastSpeakerRef = useRef<string | null>(null);
  //: Did the last thing said end in a question? If so the next voice waits longer.
  const heldQuestionRef = useRef(false);

  const panelKey = panel.map((p) => `${p.name}:${p.gender}`).join('|');

  /**
   * Each panelist's stance, for deriving their delivery.
   *
   * Must be declared after `panelKey` — reading a `const` in the same scope above
   * its declaration is a TDZ ReferenceError on every render. `panel` alone is the
   * dependency, since the caller memoizes it, and stance is deliberately NOT part
   * of `panelKey`: editing a stance must never re-run voice allocation and change
   * everyone's voice mid-discussion.
   */
  const stanceOf = useMemo(() => new Map(panel.map((p) => [p.name, p.stance])), [panel]);

  const [neuralProvider, setNeuralProvider] = useState<string | null>(null);

  /**
   * Ask the server ONCE whether neural speech is on for this round, and hand every caller the
   * same answer.
   *
   * Once, not per utterance: a round is up to 40 contributions and the answer does not change
   * mid-round, so probing each time would add a round trip to every one of them to learn
   * something already known. If it says no — off, unconfigured, or budget spent — every
   * utterance goes straight to speechSynthesis with no wasted attempt. `enabled` already folds
   * in the budget, so a round that starts with the budget spent never tries.
   *
   * What is new is that the answer is a promise the callers AWAIT rather than a ref they
   * happen to read. The memoization lives in ttsStatusOnce, so even the request is shared;
   * this wrapper only turns the raw status into the decision the speech path actually needs.
   *
   * AND IT IS THE FIRST CONSUMER TTSStatus.voices HAS EVER HAD. The server has always reported
   * which speakers have a voice id configured, per name, precisely so a partly-configured
   * panel degrades one voice at a time — and the client fetched that map and dropped it on the
   * floor. Every line for an unvoiced speaker therefore went out, 503'd, and fell back, which
   * is a permanent per-speaker oscillation with a round trip attached to each flip. Reading it
   * here means an unvoiced speaker is on browser voices from their first word and stays there,
   * while the speakers who do have voices keep them.
   */
  const resolveRoundVoice = useCallback((): Promise<RoundVoicePlan> => {
    planRef.current ??= ttsStatusOnce().then((status) => {
      const listed = Object.entries(status?.voices ?? {});
      const plan: RoundVoicePlan = {
        neural: !!status?.enabled,
        provider: status?.enabled ? status.provider : null,
        /*
         * null, not an empty Set, when the server listed nothing.
         *
         * An empty map and a map of all-false mean opposite things. A backend older than the
         * per-speaker field, or one that grew a speaker this deploy's status route does not
         * know about, would otherwise silently put a perfectly working panel on browser voices
         * — a worse regression than the bug being fixed. So "no information" means try
         * everyone, and a speaker who turns out to have no voice id 503s once and latches the
         * round, which is still consistent even though it is not optimal.
         */
        neuralSpeakers: listed.length
          ? new Set(listed.filter(([, ok]) => ok).map(([name]) => name.toLowerCase()))
          : null,
      };
      setNeuralProvider(plan.provider);
      return plan;
    });
    return planRef.current;
  }, []);

  /**
   * A mounted panel hook IS a round, so this is where a round begins.
   *
   * resetSpeechRound clears the module-scope probe memo and the degrade latch in
   * neural-tts.ts. Doing it on mount rather than asking the page to remember is what makes
   * "one round" true for the second interview taken in a tab as well as the first: those
   * module-level values survive client-side navigation, so without this a single 402 in one
   * interview would put every subsequent interview on browser voices with nothing in the code
   * having changed.
   *
   * The probe is then kicked off immediately — not awaited here — so it is already in flight
   * by the time the first utterance awaits it, exactly as it was before. The difference is
   * only that somebody now waits for the answer.
   */
  useEffect(() => {
    resetSpeechRound();
    void resolveRoundVoice();
  }, [resolveRoundVoice]);

  /**
   * How far this panel's browser-voice allocation has got. See planPanelAllocation.
   *
   * A ref, not state: it is read inside the poll callback below, which is created once per
   * panel and would otherwise close over a stale value and re-commit forever.
   */
  const stageRef = useRef<AllocationStage>('none');
  /**
   * Resolves when the real voice list has been allocated — or at the cap, whichever is first.
   *
   * THE SECOND FLIP, and the one that is guaranteed rather than racy, so it is probably what
   * the user actually heard. `getVoices()` is empty until the engine has enumerated its
   * voices, so the first allocation of an interview is frequently the pitch-only fallback: the
   * engine default voice at 0.86 for a man and 1.14 for a woman, which on macOS is a
   * pitched-down Samantha for Anil. Seconds later the real list arrives and Anil becomes an
   * actual male voice. Nothing to do with neural TTS at all — that flip happened on every
   * browser-voice interview, every time.
   *
   * So the first utterance waits for the allocation the same way it waits for the neural
   * probe: bounded, once, and then it speaks in whatever identity was settled on.
   */
  const allocationRef = useRef<Promise<void> | null>(null);
  /**
   * The live voice map, for speakAs to read at the moment it speaks rather than at the moment
   * it was built.
   *
   * speakAs is a useCallback, and it used to list `voiceMap` as a dependency — so a turn
   * already queued and awaiting its handover beat was speaking through the map that existed
   * when it was created. With the allocation now latched that window is small, but "small" is
   * not the contract: the whole point is that a line cannot be spoken in an identity the round
   * has already moved on from. A ref removes the window rather than shrinking it, and it drops
   * a dependency that changed identity mid-turn.
   */
  const voiceMapRef = useRef(voiceMap);
  voiceMapRef.current = voiceMap;

  useEffect(() => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window) || !panel.length) return;

    const speakers: PanelSpeaker[] = panel.map((p) => ({
      name: p.name,
      gender: p.gender === 'male' || p.gender === 'female' ? p.gender : 'unknown',
    }));

    // A genuinely different panel must reallocate from scratch — this is the only thing that
    // reopens the latch, and it is keyed on panelKey, which is names and genders only. Editing
    // a stance deliberately does not reach here; that would change everyone's voice mid-round
    // for a change that has nothing to do with voices.
    stageRef.current = 'none';
    let settleAllocation: () => void = () => {};
    const realAllocation = new Promise<void>((resolve) => {
      settleAllocation = resolve;
    });
    // Capped, because an engine with genuinely no usable voices never settles the promise and
    // the first line must still be spoken. The cost of the cap is that a very slow enumeration
    // can still be beaten by the first utterance — but the pitch-only fallback it would speak
    // through is a deliberate, gender-anchored identity rather than the empty map that used to
    // put the whole panel in one default voice.
    allocationRef.current = Promise.race([realAllocation, sleep(ALLOCATION_WAIT_MS)]);

    /**
     * Commit an allocation if this trigger has anything new to say, and report whether the
     * real voice list has landed.
     *
     * THE FIRST BUG THIS FIXES, which shipped. This used to be `if (!available.length)
     * return;` — so when the voice list was not ready, voiceMap stayed EMPTY. speakAs then
     * read `assigned?.pitch ?? 1` and every panelist got pitch 1.0 and no voice, meaning all
     * three spoke in the browser's default voice at the same pitch. On macOS that default is
     * Samantha, so Arjun sounded female too — the panel was one woman reading three name
     * tags, which is the exact failure this whole layer exists to prevent. And
     * allocatePanelVoices' no-voices branch, which assigns gender-anchored pitches (0.86 male
     * / 1.14 female) precisely for this case, was UNREACHABLE from here: it had a passing unit
     * test, which is why nothing caught it. The fallback worked, it just could never be
     * triggered. So an allocation is always committed.
     *
     * THE SECOND BUG, which is the reported one. This function has three triggers — the
     * immediate call, the 250ms poll and the `voiceschanged` listener — and it used to REPLACE
     * the map wholesale on every successful call. `allocatePanelVoices` sorts its input by
     * scoreVoice, and Chrome appends its network "Google …" voices (qualityTier 800) AFTER the
     * local ones (10) on a later `voiceschanged`. So the pool reordered and Anil and Priya
     * were reassigned to entirely different voices, mid-interview, with nothing having failed.
     *
     * The decision of what to commit is now planPanelAllocation, which is pure and tested
     * against exactly that three-step sequence. All this closure does is apply it.
     */
    const allocate = (): boolean => {
      const decision = planPanelAllocation(
        stageRef.current,
        window.speechSynthesis.getVoices(),
        speakers,
      );
      if (decision) {
        stageRef.current = decision.stage;
        setVoiceMap(decision.map);
      }
      if (stageRef.current !== 'real') return false;
      // Release the first utterance. Idempotent — a resolved promise cannot be re-resolved —
      // which matters because the poll and the event can both land after the latch closed.
      settleAllocation();
      return true;
    };

    if (allocate()) return;

    /*
     * POLL, because `voiceschanged` cannot be relied on.
     *
     * getVoices() is empty until the engine has enumerated its voices, and the event that
     * announces it is inconsistent: Chrome fires it, sometimes late; Safari frequently
     * never fires it at all and simply starts returning a populated list. Listening only
     * for the event means Safari users get the pitch-only fallback for the whole round
     * even though real voices were available seconds in.
     *
     * 250ms x 20 is five seconds — well past when any engine has settled, and it stops
     * either way, so a browser with genuinely no voices costs five seconds of a timer
     * rather than an endless one.
     */
    let tries = 0;
    const poll = window.setInterval(() => {
      tries += 1;
      if (allocate() || tries >= 20) window.clearInterval(poll);
    }, 250);

    window.speechSynthesis.addEventListener('voiceschanged', allocate);
    return () => {
      window.clearInterval(poll);
      window.speechSynthesis.removeEventListener('voiceschanged', allocate);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelKey]);

  const cancelAll = useCallback(() => {
    genRef.current += 1;
    // Stop neural audio too. speechSynthesis.cancel() below does nothing to an <audio>
    // element, so without this the candidate takes the floor and a panelist keeps talking
    // over them — and their microphone transcribes it into their own answer.
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setSpeakingNow(null);
    setTakingFloor(null);
    // The candidate has the floor now, so whoever speaks next pays a full beat.
    lastSpeakerRef.current = CANDIDATE_FLOOR;
    heldQuestionRef.current = false;
    // A fresh chain, so a later speakAs is not queued behind the cancelled one.
    chainRef.current = Promise.resolve();
  }, []);

  /**
   * Queue one panelist's turn. Resolves when they have finished speaking.
   *
   * Sentence-chunked like the interviewer voice: the engine puts a natural breath
   * between utterances, and it keeps a long turn from being truncated by the
   * per-utterance limits some engines impose.
   */
  const speakAs = useCallback(
    (
      speaker: string,
      text: string,
      opts: {
        /**
         * Fires the moment this speaker actually takes the floor — after their handover
         * beat, before their first word.
         *
         * This exists so the TRANSCRIPT can be revealed in step with the voice. A panel
         * turn returns one or two contributions at once, and pushing both into the
         * transcript on arrival meant the candidate read Arjun's line while Riya was still
         * speaking: the text ran several seconds ahead of the room. Revealing on this
         * callback puts them back together.
         *
         * Not fired if the utterance is cancelled before it starts, which is deliberate —
         * a contribution that was talked over was never said, so it should not appear.
         */
        onStart?: () => void;
        /**
         * How this line is delivered — see SpeechTone.
         *
         * The panel tags every turn, because it is the only thing that knows which line is
         * the correction. Putting a question and telling somebody their answer is wrong in
         * one flat register is the clearest tell that nobody is in the room, and it is not
         * something better writing can fix: the words already say it, the voice does not.
         */
        tone?: SpeechTone;
      } = {},
    ): Promise<void> => {
      if (typeof window === 'undefined' || !('speechSynthesis' in window) || !text.trim()) {
        // No speech engine at all. Fire onStart anyway: the caller uses it to reveal the
        // text, and silently withholding the transcript would be far worse than showing it
        // without audio.
        opts.onStart?.();
        return Promise.resolve();
      }
      const myGen = genRef.current;
      const live = () => genRef.current === myGen;

      const run = async () => {
        if (!live()) return;
        const persona = personaFor(stanceOf.get(speaker));

        /*
         * WHICH VOICE THIS ROUND USES IS DECIDED BEFORE THE FIRST WORD, NOT DISCOVERED DURING IT.
         *
         * This await is the fix for "in the starting of the interview the voices changes". The
         * neural probe used to be read from a ref that an async effect had not written yet, so
         * the greeting spoke on browser voices and everything after it spoke on Fish — the
         * voice of the interview changed one sentence in, for no reason the candidate could
         * see. Awaiting means the decision exists before there is any sound to be inconsistent
         * with.
         *
         * It cannot hang and it cannot cost anything perceptible; both properties are proved
         * in the comment on ttsStatusOnce, and neither is an assumption about the network.
         */
        const plan = await resolveRoundVoice();
        // A new suspension point, and cancelAll can land inside any of them. Without this
        // check a panelist cancelled while the probe was in flight would wake up and talk over
        // the candidate — the same lesson as the lead-in sleep below.
        if (!live()) return;

        /*
         * `neuralOff()` is the round's degrade latch, not a per-line retry. Once it is true it
         * stays true, so this expression can go from neural to browser exactly once in a round
         * and never back — which is the whole no-oscillation guarantee, expressed here.
         *
         * `neuralSpeakers` is per speaker: an interviewer the server has no voice id for is on
         * browser voices from their first line while the rest of the panel keeps theirs, rather
         * than 503-ing once per line forever.
         */
        const useNeural =
          plan.neural && !neuralOff() && (plan.neuralSpeakers?.has(speaker.toLowerCase()) ?? true);

        /*
         * THE BEAT BEFORE SPEAKING.
         *
         * There was previously zero gap anywhere: the chain started the next
         * speaker the microsecond the previous one stopped, and both contributions
         * of one turn were queued in the same tick. That single fact is most of why
         * the panel read as a chatbot taking turns — a real handover is 200ms-plus
         * of silence, and how long it is tells you who the person is. The
         * contrarian latches on in 90ms; the synthesiser waits half a second
         * because she actually listened.
         *
         * Only on a genuine handover: a panelist continuing after themselves does
         * not pause to take a floor they already hold.
         */
        let leadIn =
          lastSpeakerRef.current && lastSpeakerRef.current !== speaker ? persona.leadInMs : 0;
        if (heldQuestionRef.current) leadIn += QUESTION_HANDOVER_MS;

        /*
         * THE AUDIO IS FETCHED BEFORE THE TEXT IS REVEALED, AND THE FETCH STARTS FIRST.
         *
         * This ordering was the real cause of "the text comes first and the voice after".
         * onStart — which puts the line on screen — used to fire, and only THEN did the
         * vendor request go out. Fish takes about three and a half seconds to synthesise a
         * sentence, so the candidate read the whole line, waited, and then heard it. No
         * amount of work further up the page could fix that, because the gap was created
         * here, inside the utterance itself.
         *
         * Two changes. The request is started NOW, before the handover pause, so those two
         * waits overlap instead of stacking — a 520ms lead-in is 520ms of the synthesis
         * paid for free. And onStart moves below the await, so the words appear at the
         * moment the voice does. `takingFloor` stays set across the whole wait, which is
         * what makes it read as somebody drawing breath rather than as a stall.
         */
        /*
         * SPOKEN FORM, NOT THE WRITTEN ONE.
         *
         * "==" is correct on screen and wrong in the ear — the panel read it out as "equal
         * equal" and "===" as "equal equal equal", and said "oop" as a word instead of
         * O-O-P. Only the copy handed to the synthesiser goes through this; `text` is what
         * appears in the thread and what ends up in the transcript, because a transcript
         * saying "double equals" would be quoted back at the candidate in a follow-up and
         * printed in their report as though somebody had typed it.
         */
        /*
         * Still needed HERE for the browser fallback below, which does its own chunking and
         * therefore needs the spoken string in hand.
         *
         * The NEURAL call no longer gets it, and that is the fix rather than an oversight:
         * neural-tts.ts now normalises at its own boundary, so it must be handed the line as
         * written. Passing `spoken` here again would key the fetch on doubly-converted text
         * and reintroduce exactly the prefetch miss that change removes — see _spoken.
         */
        const spoken = toSpokenForm(text);

        const audioPromise = useNeural ? fetchUtterance(speaker, text, opts.tone) : null;

        setTakingFloor(speaker);
        /*
         * THE HANDOVER BEAT AND THE VOICE-LIST WAIT ARE SPENT TOGETHER, NOT ONE AFTER THE OTHER.
         *
         * Same trick as starting the vendor fetch before the pause: the browser path has to
         * know its voice before it speaks, and it also has to wait a persona-length beat before
         * it speaks. Running both at once means a 520ms lead-in pays for 520ms of the voice
         * enumeration for free, and the cap is only ever reached by a browser that is genuinely
         * still thinking about it.
         *
         * Only the browser path waits. The neural path never reads voiceMap, so making it wait
         * would be pure latency for nothing.
         */
        const allocationGate = useNeural ? null : allocationRef.current;
        if (leadIn > 0 || allocationGate) {
          await Promise.all([allocationGate, leadIn > 0 ? sleep(leadIn) : null]);
          // speechSynthesis.cancel() cannot stop an utterance that has not been
          // queued yet, so this check is the ONLY thing standing between a
          // cancelled panelist and talking over the candidate.
          if (!live()) {
            setTakingFloor(null);
            return;
          }
        }

        const blob = audioPromise ? await audioPromise : null;
        if (!live()) {
          setTakingFloor(null);
          return;
        }

        /*
         * THE LINE THAT TRIGGERS THE DEGRADE IS THE ONE MOST LIKELY TO BE SPOKEN WRONG.
         *
         * Neural was attempted and came back with nothing, so the latch has just closed and
         * this line — right now, not the next one — is on the browser path. It skipped the
         * allocation gate above, because a neural line has no reason to wait for a voice list it
         * will never read. Without this it would speak through whatever voiceMap happened to
         * hold, and the flip would survive in miniature at precisely the moment the round
         * changes identity: one line in the engine default, everything after it in the real
         * allocation.
         *
         * Usually free — the vendor round trip it just spent is longer than the enumeration this
         * waits for, so the promise is already resolved. `takingFloor` is deliberately still set
         * across it, which reads as somebody drawing breath rather than as a stall.
         */
        if (!blob && useNeural && allocationRef.current) {
          await allocationRef.current;
          if (!live()) {
            setTakingFloor(null);
            return;
          }
        }

        setTakingFloor(null);
        setSpeakingNow(speaker);
        lastSpeakerRef.current = speaker;
        /*
         * THE REVEAL, fired once, by whichever path actually produces sound.
         *
         * It used to fire here unconditionally, which is correct for the neural path — the
         * audio is already downloaded by this point — and WRONG for the browser fallback,
         * where speechSynthesis has not been handed the utterance yet. On a cold engine that
         * is over a second, so the line appeared and the voice followed. Anyone without Fish
         * configured was still seeing the original bug.
         *
         * Guarded because both paths must be able to call it and only the first may win.
         */
        let revealed = false;
        const reveal = () => {
          if (revealed) return;
          revealed = true;
          opts.onStart?.();
        };

        /*
         * NEURAL SPEECH FIRST, browser speech as the fallback.
         *
         * Tried only when the server said it is available (checked once per round, not per
         * utterance), and any failure — budget spent, vendor down, slow connection — falls
         * straight through to speechSynthesis below. The candidate hears a worse voice, not
         * silence, which is the only acceptable failure mode inside a live discussion.
         *
         * The audio element is registered so cancelAll can stop it: without that, taking
         * the floor would silence the queue but leave the current utterance playing over
         * the candidate, and their own microphone would transcribe it into their answer.
         */
        if (blob) {
          // Neural: the bytes are in hand, so the words and the first syllable land together.
          reveal();
          // The persona tempo applies to neural audio too, via playbackRate. Without it
          // the per-panelist pacing — the whole reason three voices were tellable apart
          // before — would vanish the moment neural speech came on.
          await playBlob(
            blob,
            (el) => {
              audioRef.current = el;
            },
            persona.tempo,
          );
          audioRef.current = null;
          // A neural utterance is one audio file, so there is no per-clause pause to
          // hold and no question-handover to add here — the vendor's own delivery
          // carries it. Only the next speaker's lead-in still applies.
          heldQuestionRef.current = /\?\s*$/.test(text.trim());
          if (live()) setSpeakingNow(null);
          return;
        }

        // Tone for browser speech. The server applies its own on the neural path above, so
        // this is only reached when neural audio was unavailable — which is exactly when it
        // matters most, since that is the path a spent budget puts everyone on.
        const toneShape = BROWSER_TONE[opts.tone ?? 'neutral'] ?? BROWSER_TONE.neutral;

        /*
         * RESOLVED HERE, AFTER THE GATE, AND FROM THE REF.
         *
         * These two lines used to sit at the top of `run`, which meant a queued turn read the
         * allocation as it was when the turn was QUEUED — before the voice list had arrived, on
         * the first turn of every interview. Reading them after the allocation gate, through
         * voiceMapRef rather than a captured value, is what makes "who sounds like whom" a
         * property of the round rather than of when a line happened to be enqueued.
         */
        const assigned = voiceMapRef.current.get(speaker);
        const chosen = assigned?.voiceURI
          ? (window.speechSynthesis.getVoices().find((v) => v.voiceURI === assigned.voiceURI) ??
            null)
          : null;

        const network = isNetworkVoice(chosen);
        // Local formant synthesis needs the extra room to stay intelligible;
        // neural voices are already well paced. Persona tempo multiplies on top of
        // whatever rate panel-voices assigned, so neither overwrites the other.
        const baseRate =
          (assigned?.rate ?? 1) * (network ? 1.0 : 0.94) * persona.tempo * toneShape.rate;
        // finalPauseMs 0: the next speaker's lead-in owns the gap after a
        // contribution, so adding one here would double it.
        // The browser path needs the same treatment — it is what every candidate hears once
        // the daily TTS budget is spent, and speechSynthesis mangles operators just as badly.
        const chunks = toProsodyChunks(spoken, { networkVoice: network, finalPauseMs: 0 });

        for (const chunk of chunks) {
          if (!live()) break;
          const utter = new SpeechSynthesisUtterance(chunk.text);
          if (chosen) {
            utter.voice = chosen;
            utter.lang = chosen.lang;
          } else {
            // Same reasoning as the interviewer path above.
            utter.lang = 'en-US';
          }
          // Pitch is panel-voices' to set — it is the value allDistinguishable relies on to
          // keep two panelists on one voice tellable apart. Tone only OFFSETS it, by at most
          // 0.06, which is well inside that margin and still audible as gravity.
          utter.pitch = Math.max(0.5, Math.min(2, (assigned?.pitch ?? 1) + toneShape.pitch));
          utter.rate = Math.min(
            1.35,
            Math.max(0.7, Math.round(baseRate * shapingFor(chunk) * 100) / 100),
          );
          // Browser: reveal on the engine's own onstart, not before handing it the text.
          await speakOnce(utter, reveal);
          if (chunk.pauseAfterMs > 0 && !live()) break;
          if (chunk.pauseAfterMs > 0) await sleep(chunk.pauseAfterMs);
        }
        // A question left hanging makes the NEXT voice wait — this is what stops
        // one panelist answering a question another just put to the candidate.
        // Nothing spoke — no chunks, or every one was cancelled. The line still has to
        // appear: a candidate must never be left with a silent, blank screen because the
        // speech engine had nothing to say.
        reveal();
        heldQuestionRef.current = chunks[chunks.length - 1]?.isQuestion ?? false;
        if (live()) setSpeakingNow(null);
      };

      chainRef.current = chainRef.current.then(run, run);
      return chainRef.current;
    },
    // voiceMap is deliberately absent: it is read through voiceMapRef inside `run`, so a
    // reallocation no longer changes this callback's identity mid-turn.
    [stanceOf, resolveRoundVoice],
  );

  /**
   * Start synthesising every line of a turn at once, before any of them is spoken.
   *
   * A panel turn arrives as two or three lines and used to be synthesised one at a time, in
   * order, each one starting only after the previous had finished playing. At roughly three
   * and a half seconds a line that is ten seconds of dead air inside what is meant to be a
   * conversation — and dead air between two people talking is the most artificial thing a
   * room can do.
   *
   * Called with the whole turn the moment it arrives, every line is in flight while the
   * first is still speaking, so the second follows the first by its handover beat alone.
   *
   * Cheap to call and safe to over-call: requests are deduplicated by speaker, tone and
   * exact text, and a failed prefetch is indistinguishable from one never made.
   */
  const prefetchTurn = useCallback(
    (lines: { speaker: string; text: string; tone?: SpeechTone }[]) => {
      /*
       * WAITS FOR THE PLAN INSTEAD OF HARD-RETURNING ON IT.
       *
       * This used to open with `if (!neuralRef.current) return;`, which meant that while the
       * probe was unresolved — i.e. for the first turn of the interview, the one this
       * optimisation exists for — prefetching was silently off. The two failures compounded:
       * the first line was both a surprise voice change AND cold, paying Fish's full ~3.5s on
       * the critical path. Deferring instead of giving up costs nothing, because the plan is
       * already in flight from mount and the lines are not needed until the turn is spoken.
       */
      void resolveRoundVoice().then((plan) => {
        if (!plan.neural || neuralOff()) return;
        for (const l of lines) {
          // Skip a speaker the server cannot voice rather than paying a request to be told so.
          if (plan.neuralSpeakers && !plan.neuralSpeakers.has(l.speaker.toLowerCase())) continue;
          prefetchUtterance(l.speaker, l.text, l.tone);
        }
      });
    },
    [resolveRoundVoice],
  );

  return {
    voiceMap,
    speakingNow,
    takingFloor,
    prefetchTurn,
    speakAs,
    cancelAll,
    //: Which vendor is speaking, or null for browser voices. Exposed so the UI can say so —
    //: a candidate hearing flat system speech should know the round is on standby voices
    //: rather than assume that is how the product sounds.
    neuralProvider,
  };
}

/**
 * How far a panel's browser-voice allocation has got. Only ever moves forward.
 *
 * `none` — nothing committed; speakAs would read an empty map and put the whole panel in the
 * engine's default voice at pitch 1.0, which is the "Meera has a male voice" report.
 * `pitch-only` — committed with gender-anchored pitches because getVoices() was still empty.
 * Degraded but deliberate, and still upgradable: this is the state Safari can sit in for
 * seconds, and the one the poll and the `voiceschanged` listener exist to get it out of.
 * `real` — committed from the actual voice list. TERMINAL for the life of the panel.
 */
export type AllocationStage = 'none' | 'pitch-only' | 'real';

/**
 * Decide what a voice-list trigger should commit, or null for "leave it alone".
 *
 * THE REPORT THIS ANSWERS: "in the starting of the interview the voices changes and then it
 * changed again to the old voices." The neural probe race is one half of that; this is the
 * other, and it is the half that fired on every browser-voice interview rather than only on a
 * cold backend.
 *
 * `allocate` in usePanelVoices runs from three triggers — an immediate call, a 250ms poll, and
 * the `voiceschanged` event — and it used to replace the map on every one of them that found
 * voices. `allocatePanelVoices` ranks its input with scoreVoice, and Chrome does not deliver
 * its voices all at once: the local ones (qualityTier 10) arrive first and the network "Google
 * …" ones (tier 800) are appended by a later `voiceschanged`. A better pool is not a better
 * assignment of the same voices — it is a DIFFERENT assignment. So Anil was one voice for the
 * greeting, another for the first question, and the candidate heard the interviewer change
 * person twice before answering anything.
 *
 * The rule is therefore monotonic rather than "best available": the first allocation made from
 * a real voice list wins for the rest of the panel's life, and later triggers are ignored. A
 * marginally better voice is worth nothing against a stable one — see the note on the degrade
 * latch in neural-tts.ts for why a change of voice is read as a change of PERSON, and why that
 * costs the candidate more than the audio quality ever gains them.
 *
 * WHAT IS DELIBERATELY NOT LATCHED: the pitch-only fallback. Latching there would strand
 * Safari — which frequently never fires `voiceschanged` at all and simply starts returning a
 * populated list — on gender-anchored pitches for a whole round with real voices sitting
 * unused. The pitch-only commit exists to be replaced exactly once.
 *
 * Pure, so the three-step sequence that produced the bug (empty list → local voices → local
 * plus Google) can be asserted directly, which is not possible from inside the effect.
 */
export function planPanelAllocation(
  stage: AllocationStage,
  available: SpeechSynthesisVoice[],
  speakers: PanelSpeaker[],
): { map: Map<string, PanelVoice>; stage: AllocationStage } | null {
  // Latched. A later, richer voice list is exactly the input that used to reassign everybody.
  if (stage === 'real') return null;
  if (available.length) return { map: allocatePanelVoices(available, speakers), stage: 'real' };
  // Pitch-only, committed once. Returning null on the repeat visits matters mechanically as
  // well as audibly: this runs on every 250ms poll tick, and handing React a fresh Map each
  // time would re-render forever.
  if (stage === 'pitch-only') return null;
  return { map: allocatePanelVoices([], speakers), stage: 'pitch-only' };
}
