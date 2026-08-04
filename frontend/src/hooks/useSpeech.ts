'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PauseEvent } from '@/lib/speech/delivery';
import { correctTechnicalTerms } from '@/lib/speech/vocabulary';
import {
  allocatePanelVoices,
  type PanelSpeaker,
  type PanelVoice,
} from '@/lib/speech/panel-voices';
import { personaFor } from '@/lib/speech/persona';
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
function speakOnce(utter: SpeechSynthesisUtterance): Promise<void> {
  return new Promise<void>((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(finish, 3000 + utter.text.length * 90);
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
      const chunks = toProsodyChunks(text, { networkVoice: network, finalPauseMs: 250 });

      void (async () => {
        for (let i = 0; i < chunks.length; i++) {
          if (stale()) return;
          const c = chunks[i];
          const utter = new SpeechSynthesisUtterance(c.text);
          if (chosen) {
            utter.voice = chosen;
            utter.lang = chosen.lang;
          } else {
            // Ask for Indian English even without a matching voice object — some
            // engines still pick an en-IN variant from the lang hint alone.
            utter.lang = 'en-IN';
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

  useEffect(() => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window) || !panel.length) return;

    const speakers: PanelSpeaker[] = panel.map((p) => ({
      name: p.name,
      gender: p.gender === 'male' || p.gender === 'female' ? p.gender : 'unknown',
    }));

    /**
     * Commit an allocation, and say whether the real voice list was available.
     *
     * THE BUG THIS FIXES. This used to be `if (!available.length) return;` — so when the
     * voice list was not ready, voiceMap stayed EMPTY. speakAs then read
     * `assigned?.pitch ?? 1` and every panelist got pitch 1.0 and no voice, meaning all
     * three spoke in the browser's default voice at the same pitch. On macOS that default
     * is Samantha, so Arjun sounded female too — the panel was one woman reading three
     * name tags, which is the exact failure this whole layer exists to prevent.
     *
     * And allocatePanelVoices' no-voices branch, which assigns gender-anchored pitches
     * (0.86 male / 1.14 female) precisely for this case, was UNREACHABLE from here. It has
     * a passing unit test, which is why nothing caught it: the fallback worked, it just
     * could never be triggered.
     *
     * So an allocation is always committed. With no voices that is pitch-only, which is
     * degraded but still three distinguishable people.
     */
    const allocate = (): boolean => {
      const available = window.speechSynthesis.getVoices();
      if (available.length) {
        setVoiceMap(allocatePanelVoices(available, speakers));
        return true;
      }
      // Pitch-only fallback, committed once. The functional form matters: this runs on
      // every poll tick below, and unconditionally setting a fresh Map would re-render
      // forever.
      setVoiceMap((prev) => (prev.size ? prev : allocatePanelVoices([], speakers)));
      return false;
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
    (speaker: string, text: string): Promise<void> => {
      if (typeof window === 'undefined' || !('speechSynthesis' in window) || !text.trim()) {
        return Promise.resolve();
      }
      const myGen = genRef.current;
      const live = () => genRef.current === myGen;

      const run = async () => {
        if (!live()) return;
        const assigned = voiceMap.get(speaker);
        const all = window.speechSynthesis.getVoices();
        const chosen = assigned?.voiceURI
          ? (all.find((v) => v.voiceURI === assigned.voiceURI) ?? null)
          : null;
        const persona = personaFor(stanceOf.get(speaker));

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

        if (leadIn > 0) {
          setTakingFloor(speaker);
          await sleep(leadIn);
          // speechSynthesis.cancel() cannot stop an utterance that has not been
          // queued yet, so this check is the ONLY thing standing between a
          // cancelled panelist and talking over the candidate.
          if (!live()) {
            setTakingFloor(null);
            return;
          }
        }
        setTakingFloor(null);
        setSpeakingNow(speaker);
        lastSpeakerRef.current = speaker;

        const network = isNetworkVoice(chosen);
        // Local formant synthesis needs the extra room to stay intelligible;
        // neural voices are already well paced. Persona tempo multiplies on top of
        // whatever rate panel-voices assigned, so neither overwrites the other.
        const baseRate = (assigned?.rate ?? 1) * (network ? 1.0 : 0.94) * persona.tempo;
        // finalPauseMs 0: the next speaker's lead-in owns the gap after a
        // contribution, so adding one here would double it.
        const chunks = toProsodyChunks(text, { networkVoice: network, finalPauseMs: 0 });

        for (const chunk of chunks) {
          if (!live()) break;
          const utter = new SpeechSynthesisUtterance(chunk.text);
          if (chosen) {
            utter.voice = chosen;
            utter.lang = chosen.lang;
          } else {
            utter.lang = 'en-IN';
          }
          // Pitch belongs to panel-voices: it is the value allDistinguishable
          // relies on to keep two panelists sharing one voice tellable apart, so
          // nudging it per chunk would erode that margin for no audible gain.
          utter.pitch = assigned?.pitch ?? 1;
          utter.rate = Math.min(
            1.35,
            Math.max(0.7, Math.round(baseRate * shapingFor(chunk) * 100) / 100),
          );
          await speakOnce(utter);
          if (chunk.pauseAfterMs > 0 && !live()) break;
          if (chunk.pauseAfterMs > 0) await sleep(chunk.pauseAfterMs);
        }
        // A question left hanging makes the NEXT voice wait — this is what stops
        // one panelist answering a question another just put to the candidate.
        heldQuestionRef.current = chunks[chunks.length - 1]?.isQuestion ?? false;
        if (live()) setSpeakingNow(null);
      };

      chainRef.current = chainRef.current.then(run, run);
      return chainRef.current;
    },
    [voiceMap, stanceOf],
  );

  return { voiceMap, speakingNow, takingFloor, speakAs, cancelAll, ready: voiceMap.size > 0 };
}
