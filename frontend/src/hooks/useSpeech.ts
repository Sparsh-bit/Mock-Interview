'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

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
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    setSupported(true);
    const rec = new Ctor();
    rec.lang = 'en-US';
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let finalChunk = '';
      let interimChunk = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalChunk += r[0].transcript;
        else interimChunk += r[0].transcript;
      }
      if (finalChunk) setTranscript((prev) => (prev ? prev + ' ' : '') + finalChunk.trim());
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
  }, []);

  return { supported, listening, transcript, interim, start, stop, reset };
}

/**
/**
 * Ranks an available voice for interview narration. Higher = better.
 * The browser default on macOS Chrome is often a low-quality/compact voice,
 * so we explicitly prefer the natural network/enhanced voices that are
 * actually pleasant to listen to.
 */
function scoreVoice(v: SpeechSynthesisVoice): number {
  const name = v.name.toLowerCase();
  const isEnglish = v.lang?.toLowerCase().startsWith('en');
  if (!isEnglish) return -1;
  let score = 0;
  if (v.lang.toLowerCase() === 'en-us') score += 3;
  else if (v.lang.toLowerCase().startsWith('en')) score += 1;
  // High-quality network voice Chrome exposes on macOS/desktop.
  if (name.includes('google')) score += 10;
  // macOS downloadable natural voices.
  if (name.includes('premium') || name.includes('enhanced') || name.includes('natural')) score += 8;
  // Microsoft "Online (Natural)" voices on Edge/Windows.
  if (name.includes('natural') || name.includes('online')) score += 6;
  // Decent built-in macOS voices, in rough quality order.
  for (const [i, good] of ['samantha', 'ava', 'allison', 'alex', 'victoria'].entries()) {
    if (name.includes(good)) score += 5 - i * 0.5;
  }
  // Penalize known novelty/robotic voices.
  if (/albert|bad news|bahh|bells|boing|bubbles|cellos|fred|jester|organ|superstar|trinoids|whisper|wobble|zarvox/.test(name)) {
    score -= 20;
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
        utter.lang = 'en-US';
      }
      // Slightly slower + natural pitch reads more clearly for an interviewer.
      utter.rate = 0.95;
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

  return { supported, speaking, speak, cancel, voices, voiceURI, setVoiceURI };
}
