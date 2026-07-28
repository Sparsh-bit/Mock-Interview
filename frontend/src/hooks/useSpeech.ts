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

  // Accent, applied within the tier.
  if (lang === 'en-in') score += 50;
  else if (lang === 'en-gb') score += 5; // closer to Indian English than en-US
  else if (lang === 'en-us') score += 3;

  // Named Indian voices, best first — breaks ties inside the same tier+accent.
  const idx = INDIAN_VOICE_NAMES.findIndex((n) => name.includes(n));
  if (idx !== -1) score += 20 - idx;

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
