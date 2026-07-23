'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Mic, MicOff, RefreshCw, RotateCcw, Send, MessageSquare } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { useSpeechRecognition } from '@/hooks/useSpeech';
import {
  useCommunicationPrompts,
  useEvaluateCommunication,
  countFillers,
  wordsPerMinute,
  type CommunicationResult,
} from '@/hooks/useCommunication';
import { fadeUp, scalePop, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-semibold">
        <span>{label}</span>
        <span className="text-primary">{value.toFixed(1)}/10</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-primary to-accent-violet"
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(value * 10, 100)}%` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
    </div>
  );
}

export default function CommunicationPage() {
  const { data: prompts } = useCommunicationPrompts();
  const evaluate = useEvaluateCommunication();
  const stt = useSpeechRecognition();

  const [promptIdx, setPromptIdx] = useState(0);
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState<CommunicationResult | null>(null);
  const startRef = useRef<number | null>(null);
  const elapsedRef = useRef(0);

  const promptText = prompts?.[promptIdx]?.text ?? 'Tell me about yourself.';

  useEffect(() => {
    if (stt.transcript) setAnswer(stt.transcript);
  }, [stt.transcript]);

  const toggleMic = () => {
    if (stt.listening) {
      stt.stop();
      if (startRef.current) elapsedRef.current += (Date.now() - startRef.current) / 1000;
      startRef.current = null;
    } else {
      if (!answer) { stt.reset(); }
      startRef.current = Date.now();
      stt.start();
    }
  };

  const nextPrompt = () => {
    if (!prompts || prompts.length === 0) return;
    stt.stop(); stt.reset();
    setAnswer(''); setResult(null); elapsedRef.current = 0; startRef.current = null;
    setPromptIdx((i) => (i + 1) % prompts.length);
  };

  const retry = () => {
    stt.stop(); stt.reset();
    setAnswer(''); setResult(null); elapsedRef.current = 0; startRef.current = null;
  };

  const handleSubmit = () => {
    if (stt.listening) toggleMic();
    const seconds = Math.max(1, Math.round(elapsedRef.current));
    const wpm = wordsPerMinute(answer, seconds);
    const fillers = countFillers(answer);
    evaluate.mutate(
      {
        prompt_text: promptText,
        transcript: answer,
        duration_seconds: seconds,
        filler_count: fillers,
        words_per_minute: wpm,
      },
      {
        onSuccess: setResult,
        onError: (err: Error) => toast.error(err.message || 'Could not evaluate your answer.'),
      }
    );
  };

  const wordCount = answer.trim() ? answer.trim().split(/\s+/).length : 0;

  // ─── Result view ──────────────────────────────────────────────────────────
  if (result) {
    const tone = result.overall_score >= 7 ? 'text-emerald-600' : result.overall_score >= 4 ? 'text-amber-600' : 'text-red-600';
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.06)} className="mx-auto max-w-3xl space-y-6 pb-12">
        <motion.div variants={fadeUp}>
          <Card className="flex flex-col items-center gap-2 p-8 text-center">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Communication Score</p>
            <p className={cn('text-5xl font-bold tracking-tight', tone)}>{result.overall_score.toFixed(1)}<span className="text-2xl text-muted-foreground">/10</span></p>
            <div className="mt-2 flex flex-wrap justify-center gap-2 text-xs">
              <span className="rounded-full border border-border px-3 py-1">{result.words_per_minute} wpm</span>
              <span className="rounded-full border border-border px-3 py-1">{result.filler_count} filler words</span>
              {result.eye_contact_pct !== null && (
                <span className="rounded-full border border-border px-3 py-1">{result.eye_contact_pct}% eye contact</span>
              )}
            </div>
            <div className="mt-4 flex gap-2">
              <Button variant="secondary" onClick={retry}><RotateCcw className="h-4 w-4" /> Try again</Button>
              <Button onClick={nextPrompt}><RefreshCw className="h-4 w-4" /> Next prompt</Button>
            </div>
          </Card>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <ScoreBar label="Clarity" value={result.clarity_score} />
            <ScoreBar label="Structure" value={result.structure_score} />
            <ScoreBar label="Confidence" value={result.confidence_score} />
            <ScoreBar label="Conciseness" value={result.conciseness_score} />
          </Card>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card className="space-y-3 p-6">
            <p className="text-sm leading-relaxed text-foreground/85">{result.feedback}</p>
            {result.pace_feedback && <p className="rounded-lg bg-secondary/60 p-3 text-xs text-muted-foreground">🗣️ {result.pace_feedback}</p>}
            {result.filler_feedback && <p className="rounded-lg bg-secondary/60 p-3 text-xs text-muted-foreground">💬 {result.filler_feedback}</p>}
            <div className="grid gap-4 sm:grid-cols-2">
              {result.strengths.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-600">Strengths</p>
                  <ul className="space-y-1 text-sm text-foreground/80">
                    {result.strengths.map((s, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-emerald-500" />{s}</li>)}
                  </ul>
                </div>
              )}
              {result.improvements.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-amber-600">To improve</p>
                  <ul className="space-y-1 text-sm text-foreground/80">
                    {result.improvements.map((s, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-amber-500" />{s}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </Card>
        </motion.div>
      </motion.div>
    );
  }

  // ─── Answer view ────────────────────────────────────────────────────────────
  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-3xl space-y-6">
      <motion.div variants={fadeUp}>
        <h1 className="text-2xl font-bold tracking-tight">Communication Round</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Speak your answer aloud. We measure your pace, filler words, and clarity, and the AI gives delivery feedback — just like a real HR round.
        </p>
      </motion.div>

      <motion.div variants={fadeUp}>
        <Card className="p-8">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <MessageSquare className="h-3.5 w-3.5" /> Prompt
          </div>
          <h2 className="text-xl font-bold leading-relaxed tracking-[-0.01em]">{promptText}</h2>

          {!stt.supported ? (
            <p className="mt-6 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700">
              Your browser doesn&apos;t support speech recognition. Please use Chrome or Edge for the spoken communication round.
            </p>
          ) : (
            <div className="mt-6 flex flex-col items-center gap-5">
              <button
                onClick={toggleMic}
                disabled={evaluate.isPending}
                className={cn(
                  'relative flex h-24 w-24 items-center justify-center rounded-full transition-all disabled:opacity-50',
                  stt.listening ? 'bg-destructive text-destructive-foreground shadow-glow' : 'bg-primary text-primary-foreground shadow-glow hover:shadow-glow-lg'
                )}
              >
                {stt.listening && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-destructive opacity-40" />}
                {stt.listening ? <MicOff className="h-9 w-9" /> : <Mic className="h-9 w-9" />}
              </button>
              <p className="text-sm font-medium text-muted-foreground">
                {stt.listening ? 'Listening… tap to stop' : answer ? 'Tap to continue, or submit for feedback' : 'Tap the mic and answer aloud'}
              </p>
              <div className="min-h-[96px] w-full rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm leading-relaxed">
                {answer || stt.interim ? (
                  <span>{answer} <span className="text-muted-foreground/60">{stt.listening ? stt.interim : ''}</span></span>
                ) : (
                  <span className="text-muted-foreground/50">Your spoken answer will appear here…</span>
                )}
              </div>
              {evaluate.isPending ? (
                <AIWorkingIndicator messages={['Analyzing your delivery…', 'Scoring clarity & structure…', 'Writing feedback…']} />
              ) : (
                <div className="flex w-full items-center justify-between">
                  <span className="text-xs text-muted-foreground/70">{wordCount} words</span>
                  <div className="flex gap-2">
                    <Button variant="ghost" onClick={nextPrompt}>Skip</Button>
                    <Button onClick={handleSubmit} disabled={!answer.trim()}>
                      <Send className="h-4 w-4" /> Get feedback
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      </motion.div>

      <motion.div variants={scalePop} className="text-center text-xs text-muted-foreground">
        Tip: aim for a clear structure — a short intro, your main point with an example, and a one-line wrap-up.
      </motion.div>
    </motion.div>
  );
}
