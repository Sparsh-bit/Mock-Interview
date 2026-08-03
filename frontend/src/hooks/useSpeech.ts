'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { PauseEvent } from '@/lib/speech/delivery';
import { correctTechnicalTerms } from '@/lib/speech/vocabulary';
import { allocatePanelVoices, type PanelVoice } from '@/lib/speech/panel-voices';
import { scoreVoice } from '@/lib/speech/voice-ranking';

// Silence longer than this (between recognized speech) counts as a pause worth
// surfacing — shorter gaps are natural speech rhythm.
const PAUSE_THRESHOLD_MS = 1800;

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
    rec.onresult = (e) => {
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
      try { rec.stop(); } catch { /* already stopped */ }
    };
  }, []);

  const start = useCallback(() => {
    if (!recognitionRef.current || listening) return;
    wantListeningRef.current = true;
    setError(null);
    setInterim('');
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
    lastActivityRef.current = 0;
    wordCountRef.current = 0;
    confidenceSumRef.current = 0;
    confidenceCountRef.current = 0;
  }, []);

  return {
    supported, listening, transcript, interim, pauses, error, confidence,
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

  const speak = useCallback(
    (text: string) => {
      if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();

      const chosen =
        window.speechSynthesis.getVoices().find((v) => v.voiceURI === voiceURI) ?? null;
      const isNeural = /natural|online|google/i.test(chosen?.name ?? '');

      // Speak sentence by sentence. The engine puts a natural breath between
      // utterances, so this alone makes long questions read like speech instead
      // of one flat run — and it keeps very long text from being truncated.
      const chunks = toSpeechChunks(text);

      chunks.forEach((chunk, i) => {
        const utter = new SpeechSynthesisUtterance(chunk);
        if (chosen) {
          utter.voice = chosen;
          utter.lang = chosen.lang;
        } else {
          // Ask for Indian English even without a matching voice object — some
          // engines still pick an en-IN variant from the lang hint alone.
          utter.lang = 'en-IN';
        }
        // Neural voices are already well paced; slowing them down is what makes
        // them sound artificial. Local synthesis needs the extra room.
        utter.rate = isNeural ? 1.0 : 0.92;
        utter.pitch = 1.0;

        // Track speaking across the whole queue, not per chunk, so the UI
        // indicator doesn't flicker between sentences.
        if (i === 0) utter.onstart = () => setSpeaking(true);
        if (i === chunks.length - 1) utter.onend = () => setSpeaking(false);
        utter.onerror = () => setSpeaking(false);

        window.speechSynthesis.speak(utter);
      });
    },
    [voiceURI]
  );

  const cancel = useCallback(() => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
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
export function usePanelVoices(panel: Array<{ name: string; gender: string }>) {
  const [voiceMap, setVoiceMap] = useState<Map<string, PanelVoice>>(new Map());
  const [speakingNow, setSpeakingNow] = useState<string | null>(null);

  //: Serialises playback. Every speakAs chains onto this promise, so N calls in
  //: one render still play in order rather than on top of each other.
  const chainRef = useRef<Promise<void>>(Promise.resolve());
  //: Set false by cancelAll so an in-flight queue stops instead of draining.
  const activeRef = useRef(true);

  const panelKey = panel.map((p) => `${p.name}:${p.gender}`).join('|');

  useEffect(() => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window) || !panel.length) return;

    const allocate = () => {
      const available = window.speechSynthesis.getVoices();
      // Voices load asynchronously; an empty list here is normal on first paint.
      if (!available.length) return;
      setVoiceMap(
        allocatePanelVoices(
          available,
          panel.map((p) => ({
            name: p.name,
            gender: p.gender === 'male' || p.gender === 'female' ? p.gender : 'unknown',
          })),
        ),
      );
    };

    allocate();
    window.speechSynthesis.addEventListener('voiceschanged', allocate);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', allocate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelKey]);

  const cancelAll = useCallback(() => {
    activeRef.current = false;
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setSpeakingNow(null);
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
      activeRef.current = true;

      const run = async () => {
        if (!activeRef.current) return;
        const assigned = voiceMap.get(speaker);
        const all = window.speechSynthesis.getVoices();
        const chosen = assigned?.voiceURI
          ? (all.find((v) => v.voiceURI === assigned.voiceURI) ?? null)
          : null;

        setSpeakingNow(speaker);
        for (const chunk of toSpeechChunks(text)) {
          if (!activeRef.current) break;
          await new Promise<void>((resolve) => {
            const utter = new SpeechSynthesisUtterance(chunk);
            if (chosen) {
              utter.voice = chosen;
              utter.lang = chosen.lang;
            } else {
              utter.lang = 'en-IN';
            }
            utter.pitch = assigned?.pitch ?? 1;
            utter.rate = assigned?.rate ?? 1;
            // Resolve on error too — a failed utterance must not stall the queue
            // and leave the discussion silent for the rest of the round.
            utter.onend = () => resolve();
            utter.onerror = () => resolve();
            window.speechSynthesis.speak(utter);
          });
        }
        if (activeRef.current) setSpeakingNow(null);
      };

      chainRef.current = chainRef.current.then(run, run);
      return chainRef.current;
    },
    [voiceMap],
  );

  return { voiceMap, speakingNow, speakAs, cancelAll, ready: voiceMap.size > 0 };
}
