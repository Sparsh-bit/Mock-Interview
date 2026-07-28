'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { PauseEvent } from '@/lib/speech/delivery';

// Silence longer than this (between recognized speech) counts as a pause worth
// surfacing — shorter gaps are natural speech rhythm.
const PAUSE_THRESHOLD_MS = 1800;

/* ─── Types for the (non-standardised) Web Speech API ──────────────────────── */
interface SpeechRecognitionResultLike {
  0: { transcript: string };
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
  // Pauses (silences) detected while recording, tied to word positions in the
  // finalized transcript so the UI can mark exactly where they happened.
  const [pauses, setPauses] = useState<PauseEvent[]>([]);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
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
        if (r.isFinal) finalChunk += r[0].transcript;
        else interimChunk += r[0].transcript;
      }
      if (finalChunk) {
        const clean = finalChunk.trim();
        wordCountRef.current += clean.split(/\s+/).filter(Boolean).length;
        setTranscript((prev) => (prev ? prev + ' ' : '') + clean);
      }
      setInterim(interimChunk);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recognitionRef.current = rec;
    return () => {
      rec.onresult = null;
      rec.onerror = null;
      rec.onend = null;
      try { rec.stop(); } catch { /* already stopped */ }
    };
  }, []);

  const start = useCallback(() => {
    if (!recognitionRef.current || listening) return;
    setInterim('');
    // Reset the pause clock so the first utterance isn't counted as a pause.
    lastActivityRef.current = Date.now();
    try {
      recognitionRef.current.start();
      setListening(true);
    } catch { /* start() throws if already running — ignore */ }
  }, [listening]);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    setListening(false);
  }, []);

  const reset = useCallback(() => {
    setTranscript('');
    setInterim('');
    setPauses([]);
    lastActivityRef.current = 0;
    wordCountRef.current = 0;
  }, []);

  return { supported, listening, transcript, interim, pauses, start, stop, reset };
}

/**
 * Named Indian-English voices, best first. These are the platform voices that
 * actually sound like an Indian interviewer:
 *   neerja/prabhat — Microsoft "Online (Natural)" on Edge, the most natural
 *   rishi          — macOS / iOS en-IN
 *   veena          — older macOS en-IN
 *   heera/ravi     — Windows en-IN
 */
const INDIAN_VOICE_NAMES = ['neerja', 'prabhat', 'rishi', 'veena', 'heera', 'ravi', 'aditi'];

/**
 * Ranks an available voice for interview narration. Higher = better.
 *
 * The interviewer should sound like one consistent Indian-English person, so
 * en-IN outranks everything else by a wide margin. Non-Indian English voices
 * are still scored (rather than rejected) because a machine may have no en-IN
 * voice installed at all, and silence would be worse than a US accent.
 */
function scoreVoice(v: SpeechSynthesisVoice): number {
  const name = v.name.toLowerCase();
  const lang = v.lang?.toLowerCase() ?? '';
  if (!lang.startsWith('en')) return -1;

  let score = 0;

  // Accent is the dominant factor — a natural US voice must never outrank a
  // plain Indian one, so this gap has to exceed every quality bonus below.
  if (lang === 'en-in') score += 100;
  else if (lang === 'en-gb') score += 5; // closer to Indian English than en-US
  else if (lang === 'en-us') score += 3;
  else score += 1;

  // Prefer a recognised Indian voice by name, in order.
  const idx = INDIAN_VOICE_NAMES.findIndex((n) => name.includes(n));
  if (idx !== -1) score += 40 - idx * 2;

  // Quality tie-breakers within the same accent.
  if (name.includes('natural') || name.includes('online')) score += 8;
  if (name.includes('google')) score += 6;
  if (name.includes('premium') || name.includes('enhanced')) score += 5;

  // Penalize known novelty/robotic voices.
  if (/albert|bad news|bahh|bells|boing|bubbles|cellos|fred|jester|organ|superstar|trinoids|whisper|wobble|zarvox/.test(name)) {
    score -= 200;
  }
  return score;
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
      const utter = new SpeechSynthesisUtterance(text);
      const chosen =
        window.speechSynthesis.getVoices().find((v) => v.voiceURI === voiceURI) ?? null;
      if (chosen) {
        utter.voice = chosen;
        utter.lang = chosen.lang;
      } else {
        // Ask for Indian English even without a matching voice object — some
        // engines will still pick an en-IN variant from the lang hint alone.
        utter.lang = 'en-IN';
      }
      // Conversational, not newsreader: a touch slower than default with a
      // neutral pitch is the closest this API gets to a real interviewer.
      utter.rate = 0.92;
      utter.pitch = 1.0;
      utter.onstart = () => setSpeaking(true);
      utter.onend = () => setSpeaking(false);
      utter.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(utter);
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
