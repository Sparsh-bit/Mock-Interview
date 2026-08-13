'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Mic, MicOff, RefreshCw, RotateCcw, Send, MessageSquare, BookOpen, Timer } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import { useSpeechRecognition } from '@/hooks/useSpeech';
import {
  useCommunicationPrompts,
  useReadingPassages,
  useEvaluateCommunication,
  useCommunicationCrossQuestion,
  type CommunicationResult,
} from '@/hooks/useCommunication';
import { summarizeDelivery } from '@/lib/speech/delivery';
import { fadeUp, scalePop, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { PageHeader } from '@/components/ui/page-header';
import { Paywall, paywallFromError, type PaywallInfo } from '@/components/billing/Paywall';
import { CreditMeter } from '@/components/billing/CreditMeter';

export const runtime = 'edge';

type Mode = 'speaking' | 'reading';

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

function fmt(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

export default function CommunicationPage() {
  const { data: prompts } = useCommunicationPrompts();
  const { data: passages } = useReadingPassages();
  const evaluate = useEvaluateCommunication();
  const crossQ = useCommunicationCrossQuestion();
  const stt = useSpeechRecognition();

  const [mode, setMode] = useState<Mode>('speaking');
  const [promptIdx, setPromptIdx] = useState(0);
  const [passageIdx, setPassageIdx] = useState(0);
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState<CommunicationResult | null>(null);
  //: Set from the server's 402, never from a cached balance — see the note in the
  //: interview setup page for why the request is always attempted first.
  const [paywall, setPaywall] = useState<PaywallInfo | null>(null);
  // Cross-question follow-up (speaking mode): the AI probes the candidate's
  // answer; their follow-up appends to the same transcript so delivery analysis
  // naturally covers both answers.
  const [crossQuestion, setCrossQuestion] = useState<string | null>(null);
  const startRef = useRef<number | null>(null);
  const elapsedRef = useRef(0);

  // Reading-mode countdown.
  const [secondsLeft, setSecondsLeft] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const promptText = prompts?.[promptIdx]?.text ?? 'Tell me about yourself.';
  const passage = passages?.[passageIdx];

  useEffect(() => {
    if (stt.transcript) setAnswer(stt.transcript);
  }, [stt.transcript]);

  const clearTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  };
  useEffect(() => () => clearTimer(), []);

  const stopRecording = () => {
    stt.stop();
    clearTimer();
    if (startRef.current) elapsedRef.current += (Date.now() - startRef.current) / 1000;
    startRef.current = null;
  };

  const startRecording = () => {
    if (!answer) stt.reset();
    startRef.current = Date.now();
    stt.start();
    // In reading mode, run a countdown for the passage's time budget.
    if (mode === 'reading' && passage) {
      setSecondsLeft(passage.seconds);
      clearTimer();
      timerRef.current = setInterval(() => {
        setSecondsLeft((s) => {
          if (s <= 1) {
            clearTimer();
            stopRecording();
            toast.info("Time's up — submit to see how you did.");
            return 0;
          }
          return s - 1;
        });
      }, 1000);
    }
  };

  const toggleMic = () => {
    if (stt.listening) stopRecording();
    else startRecording();
  };

  const reset = () => {
    stt.stop();
    stt.reset();
    clearTimer();
    setAnswer('');
    setResult(null);
    setCrossQuestion(null);
    elapsedRef.current = 0;
    startRef.current = null;
    setSecondsLeft(0);
  };

  // Ask the AI for ONE follow-up that probes the candidate's answer. Their
  // reply appends to the same transcript, then they submit for feedback.
  const askFollowUp = () => {
    if (stt.listening) stopRecording();
    crossQ.mutate(
      { prompt_text: promptText, transcript: answer },
      {
        onSuccess: (q) => {
          setCrossQuestion(q);
          toast.info('Follow-up added — tap the mic and answer it too.');
        },
        onError: (err: Error) => toast.error(err.message || 'Could not generate a follow-up.'),
      }
    );
  };

  const next = () => {
    reset();
    if (mode === 'speaking' && prompts?.length) setPromptIdx((i) => (i + 1) % prompts.length);
    if (mode === 'reading' && passages?.length) setPassageIdx((i) => (i + 1) % passages.length);
  };

  const switchMode = (m: Mode) => {
    if (m === mode) return;
    reset();
    setMode(m);
  };

  const handleSubmit = () => {
    if (stt.listening) stopRecording();
    const seconds = Math.max(1, Math.round(elapsedRef.current));
    const summary = summarizeDelivery({ text: answer, seconds, pauses: stt.pauses });
    evaluate.mutate(
      {
        prompt_text:
          mode === 'reading'
            ? `Read this passage aloud clearly and fluently: ${passage?.text ?? ''}`
            : crossQuestion
              ? `${promptText}\n\nFollow-up asked: ${crossQuestion}`
              : promptText,
        transcript: answer,
        duration_seconds: seconds,
        filler_count: summary.fillerCount,
        words_per_minute: summary.wpm,
        pause_count: summary.pauseCount,
        total_pause_seconds: summary.totalPauseSec,
        mode,
      },
      {
        onSuccess: setResult,
        onError: (err: Error) => {
          // The allowance is spent. Shown as a panel rather than a toast: this is not a
          // transient failure to dismiss, and the candidate has just spoken a whole answer —
          // they are owed an explanation and a next step, not a message that fades.
          const blocked = paywallFromError(err);
          if (blocked) {
            setPaywall(blocked);
            return;
          }
          toast.error(err.message || 'Could not evaluate your answer.');
        },
      }
    );
  };

  const summary = summarizeDelivery({
    text: answer,
    seconds: Math.max(1, Math.round(elapsedRef.current)),
    pauses: stt.pauses,
  });

  // ─── Result view ──────────────────────────────────────────────────────────
  if (result) {
    const tone =
      result.overall_score >= 7 ? 'text-accent-emerald-ink' : result.overall_score >= 4 ? 'text-accent-amber-ink' : 'text-accent-coral-ink';
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.06)} className="mx-auto max-w-3xl space-y-6 pb-12">
        <motion.div variants={fadeUp}>
          <Card className="flex flex-col items-center gap-2 p-8 text-center">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {mode === 'reading' ? 'Reading Fluency Score' : 'Communication Score'}
            </p>
            <p className={cn('text-5xl font-bold tracking-tight', tone)}>
              {result.overall_score.toFixed(1)}<span className="text-2xl text-muted-foreground">/10</span>
            </p>
            <div className="mt-2 flex flex-wrap justify-center gap-2 text-xs">
              <span className="rounded-full border border-border px-3 py-1">{result.words_per_minute} wpm</span>
              <span className="rounded-full border border-border px-3 py-1">{result.filler_count} filler words</span>
              <span
                className={cn(
                  'rounded-full border px-3 py-1',
                  result.pause_count > 3
                    ? 'border-accent-coral/40 bg-accent-coral/10 text-accent-coral-ink'
                    : 'border-border'
                )}
              >
                {result.pause_count} pauses{result.total_pause_seconds ? ` · ${result.total_pause_seconds}s` : ''}
              </span>
              {result.eye_contact_pct !== null && (
                <span className="rounded-full border border-border px-3 py-1">{result.eye_contact_pct}% eye contact</span>
              )}
            </div>
            <div className="mt-4 flex gap-2">
              <Button variant="secondary" onClick={reset}><RotateCcw className="h-4 w-4" /> Try again</Button>
              <Button onClick={next}><RefreshCw className="h-4 w-4" /> Next</Button>
            </div>
          </Card>
        </motion.div>

        {/* Transcript with fillers in red + pause markers */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-2 p-6">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Your delivery (filler words in <span className="text-accent-coral-ink">red</span>, pauses marked)
            </p>
            <div className="rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm">
              <DeliveryTranscript text={answer} pauses={stt.pauses} />
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
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-accent-emerald-ink">Strengths</p>
                  <ul className="space-y-1 text-sm text-foreground/80">
                    {result.strengths.map((s, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-emerald" />{s}</li>)}
                  </ul>
                </div>
              )}
              {result.improvements.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-accent-amber-ink">To improve</p>
                  <ul className="space-y-1 text-sm text-foreground/80">
                    {result.improvements.map((s, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-amber" />{s}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </Card>
        </motion.div>
      </motion.div>
    );
  }

  // ─── Blocked: the communication allowance is spent ────────────────────────
  //
  // The answer is deliberately NOT cleared. They spoke it, and if they upgrade in another tab
  // and come back, throwing away a transcript they cannot easily reproduce would be its own
  // small betrayal.
  if (paywall) {
    return (
      <div className="mx-auto mt-10 max-w-2xl space-y-6">
        <Paywall info={paywall} />
        <div className="text-center">
          <button
            type="button"
            onClick={() => setPaywall(null)}
            className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            Back to your answer
          </button>
        </div>
      </div>
    );
  }

  // ─── Answer / reading view ──────────────────────────────────────────────────
  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-3xl space-y-6">
      <motion.div variants={fadeUp}>
        <CreditMeter />
      </motion.div>
      <motion.div variants={fadeUp}>
          <PageHeader
            eyebrow="Practice"
            title="Communication Round"
            description="Speak aloud and we measure your pace, filler words and pauses — with delivery feedback like a real HR round."
          />
        </motion.div>

      {/* Mode tabs */}
      <motion.div variants={fadeUp} className="flex gap-2">
        <button
          onClick={() => switchMode('speaking')}
          className={cn(
            'flex flex-1 items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold transition-colors',
            mode === 'speaking' ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'
          )}
        >
          <MessageSquare className="h-4 w-4" /> Speaking Prompts
        </button>
        <button
          onClick={() => switchMode('reading')}
          className={cn(
            'flex flex-1 items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold transition-colors',
            mode === 'reading' ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'
          )}
        >
          <BookOpen className="h-4 w-4" /> Reading Comprehension
        </button>
      </motion.div>

      <motion.div variants={fadeUp}>
        <Card className="p-8">
          {mode === 'speaking' ? (
            <>
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <MessageSquare className="h-3.5 w-3.5" /> Prompt
              </div>
              <h2 className="text-xl font-semibold leading-relaxed tracking-[-0.01em]">{promptText}</h2>
              {crossQuestion && (
                <div className="mt-4 rounded-xl border border-primary/30 bg-primary/5 p-3">
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-primary">
                    Follow-up (answer this too)
                  </p>
                  <p className="text-sm font-medium text-foreground/90">{crossQuestion}</p>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <BookOpen className="h-3.5 w-3.5" /> Read aloud — {passage?.title ?? 'Passage'}
                </div>
                <span
                  className={cn(
                    'flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold',
                    secondsLeft > 0 && secondsLeft <= 10
                      ? 'border-accent-coral/40 bg-accent-coral/10 text-accent-coral-ink'
                      : 'border-border text-muted-foreground'
                  )}
                >
                  <Timer className="h-3 w-3" />
                  {secondsLeft > 0 ? fmt(secondsLeft) : `${passage?.seconds ?? 0}s`}
                </span>
              </div>
              <p className="rounded-xl border border-border/50 bg-surface-elevated p-4 text-base leading-relaxed text-foreground/90">
                {passage?.text ?? 'Loading passage…'}
              </p>
            </>
          )}

          {!stt.supported ? (
            <p className="mt-6 rounded-lg border border-accent-amber/30 bg-accent-amber/10 p-3 text-sm text-accent-amber-ink">
              Your browser doesn&apos;t support speech recognition. Please use Chrome or Edge for the spoken round.
            </p>
          ) : (
            <div className="mt-6 flex flex-col items-center gap-5">
              <button
                onClick={toggleMic}
                disabled={evaluate.isPending}
                className={cn(
                  'relative flex h-24 w-24 items-center justify-center rounded-full transition-[color,background-color,border-color,box-shadow,transform,opacity] disabled:opacity-50',
                  stt.listening ? 'bg-destructive text-destructive-foreground shadow-glow' : 'bg-primary text-primary-foreground shadow-glow hover:shadow-glow-lg'
                )}
              >
                {stt.listening && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-destructive opacity-40" />}
                {stt.listening ? <MicOff className="h-9 w-9" /> : <Mic className="h-9 w-9" />}
              </button>
              <p className="text-sm font-medium text-muted-foreground">
                {stt.listening
                  ? 'Listening… tap to stop'
                  : answer
                    ? 'Tap to continue, or submit for feedback'
                    : mode === 'reading'
                      ? 'Tap the mic and read the passage aloud'
                      : 'Tap the mic and answer aloud'}
              </p>

              {/* Live transcript with fillers in red + pause markers */}
              <div className="min-h-[96px] w-full rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm">
                <DeliveryTranscript text={answer} pauses={stt.pauses} interim={stt.listening ? stt.interim : ''} />
              </div>

              {/* Live delivery mini-stats */}
              {answer && (
                <div className="flex flex-wrap justify-center gap-2 text-xs text-muted-foreground">
                  <span className="rounded-full border border-border px-2.5 py-0.5">{summary.words} words</span>
                  <span className="rounded-full border border-border px-2.5 py-0.5">{summary.wpm} wpm</span>
                  <span className={cn('rounded-full border px-2.5 py-0.5', summary.fillerCount > 3 && 'border-accent-coral/40 text-accent-coral-ink')}>
                    {summary.fillerCount} fillers
                  </span>
                  <span className={cn('rounded-full border px-2.5 py-0.5', summary.pauseCount > 3 && 'border-accent-coral/40 text-accent-coral-ink')}>
                    {summary.pauseCount} pauses
                  </span>
                </div>
              )}

              {evaluate.isPending ? (
                <AIWorkingIndicator messages={['Analyzing your delivery…', 'Scoring clarity & pauses…', 'Writing feedback…']} />
              ) : crossQ.isPending ? (
                <AIWorkingIndicator messages={['Thinking of a follow-up question…']} />
              ) : (
                <div className="flex w-full items-center justify-between">
                  <span className="text-xs text-muted-foreground/70">{summary.words} words</span>
                  <div className="flex gap-2">
                    <Button variant="ghost" onClick={next}>Skip</Button>
                    {mode === 'speaking' && !crossQuestion && (
                      <Button variant="secondary" onClick={askFollowUp} disabled={!answer.trim()}>
                        <MessageSquare className="h-4 w-4" /> Ask me a follow-up
                      </Button>
                    )}
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
        {mode === 'reading'
          ? 'Tip: read at a steady, natural pace. Long pauses and filler sounds are highlighted in red.'
          : 'Tip: aim for a clear structure — a short intro, your main point with an example, and a one-line wrap-up.'}
      </motion.div>
    </motion.div>
  );
}
