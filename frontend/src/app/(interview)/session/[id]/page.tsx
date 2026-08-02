'use client';

import { useInterview } from '@/hooks/useInterview';
import { useParams } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Loader2,
  Send,
  StopCircle,
  Sparkles,
  Mic,
  MicOff,
  Volume2,
  WifiOff,
  RefreshCw,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CodingWorkspace } from '@/components/interview/CodingWorkspace';
import { PresenceMonitor } from '@/components/interview/PresenceMonitor';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import type { CodeLanguage } from '@/hooks/useCode';
import { useSpeechRecognition, useSpeechSynthesis } from '@/hooks/useSpeech';
import { summarizeDelivery } from '@/lib/speech/delivery';
import { fadeUp, scalePop, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

/**
 * Full-panel "generating the next question" animation. Scoring is deferred to
 * the final report, so between questions the candidate sees this calm indicator
 * (never a raw spinner or a blank screen) while the AI prepares what's next.
 */
function GeneratingQuestion({ label }: { label: string }) {
  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={scalePop}
      className="flex flex-col items-center gap-5 py-16 text-center"
    >
      <div className="relative flex h-16 w-16 items-center justify-center">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/20" />
        <span className="absolute inline-flex h-12 w-12 rounded-full bg-primary/10" />
        <Sparkles className="relative h-7 w-7 text-primary" />
      </div>
      <div className="flex items-center gap-1.5">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="h-2 w-2 rounded-full bg-primary"
            animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
          />
        ))}
      </div>
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
    </motion.div>
  );
}

export default function LiveSessionPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const { useNextQuestion, submitAnswer, completeSession } = useInterview();

  const { data, isLoading, isFetching, isError, refetch } = useNextQuestion(sessionId);
  const [answer, setAnswer] = useState('');
  const [answered, setAnswered] = useState(0);
  // Voice is the primary way to answer; typing is a fallback when the mic or
  // browser can't do speech recognition, so a candidate is never stuck.
  const [typing, setTyping] = useState(false);

  const stt = useSpeechRecognition();
  const tts = useSpeechSynthesis();
  // Track how long the candidate actually spoke this answer, for pace/delivery.
  const speakStartRef = useRef<number | null>(null);
  const speakSecondsRef = useRef(0);

  const question = data?.question ?? null;
  const isCoding = question?.type === 'coding';
  const questionText = question?.content;
  const useTyping = typing || !stt.supported;

  // Show the generating animation while the next question is being prepared
  // (initial load, refetch after submit, or a live cross-question being built).
  const preparing = isLoading || (isFetching && !question) || submitAnswer.isPending;

  // Read each new question aloud (voice-first feel) unless typing. Coding
  // questions are read too — a real interviewer states the problem out loud,
  // and they were previously the one type left silent.
  useEffect(() => {
    if (!useTyping && questionText && tts.supported) {
      tts.speak(questionText);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionText]);

  useEffect(() => {
    if (stt.transcript) setAnswer(stt.transcript);
  }, [stt.transcript]);

  const toggleMic = () => {
    if (stt.listening) {
      stt.stop();
      if (speakStartRef.current) {
        speakSecondsRef.current += (Date.now() - speakStartRef.current) / 1000;
        speakStartRef.current = null;
      }
    } else {
      if (!answer) {
        stt.reset();
        speakSecondsRef.current = 0;
      }
      speakStartRef.current = Date.now();
      stt.start();
    }
  };

  // Submit the answer, then immediately advance to the next question — no
  // per-question score is shown (all scoring appears at the end in the report).
  const submitContent = (content: string) => {
    if (!content.trim() || !question) return;
    stt.stop();
    tts.cancel();
    if (speakStartRef.current) {
      speakSecondsRef.current += (Date.now() - speakStartRef.current) / 1000;
      speakStartRef.current = null;
    }

    // Delivery metrics for the end-of-interview report (skip for coding, where
    // "speaking" doesn't apply).
    const seconds = Math.max(1, Math.round(speakSecondsRef.current));
    const summary = summarizeDelivery({ text: content, seconds, pauses: stt.pauses });
    const delivery = isCoding
      ? undefined
      : {
          filler_count: summary.fillerCount,
          pause_count: summary.pauseCount,
          total_pause_seconds: summary.totalPauseSec,
          words: summary.words,
          speaking_seconds: seconds,
          // The individual pauses, not just the count. The detailed analysis
          // replays the answer with hesitations marked in position, which a
          // total cannot reconstruct — and this is the only moment the
          // positions exist, so dropping them here loses them for good.
          pauses: stt.pauses,
        };

    submitAnswer.mutate(
      { sessionId, questionId: question.id, content, delivery },
      {
        onSuccess: (res) => {
          setAnswered(res.questions_answered);
          setAnswer('');
          stt.reset();
          speakSecondsRef.current = 0;
          refetch();
        },
        onError: (err: Error) => {
          toast.error(err.message || 'Failed to submit answer. Please try again.');
        },
      }
    );
  };

  const handleSubmit = () => submitContent(answer);

  // ─── Loading / preparing ──────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <GeneratingQuestion label="Preparing your first question…" />
      </div>
    );
  }

  // ─── Network / server error — clean retry, no console/toast storm ─────────
  if (isError) {
    return (
      <div className="hero-wash flex min-h-screen items-center justify-center bg-background p-6">
        <motion.div
          initial="hidden"
          animate="visible"
          variants={scalePop}
          className="glass max-w-md rounded-2xl border-border/50 p-10 text-center"
        >
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-destructive/10">
            <WifiOff className="h-7 w-7 text-destructive" />
          </div>
          <h2 className="mb-3 text-xl font-semibold">Connection hiccup</h2>
          <p className="mb-8 text-sm leading-relaxed text-muted-foreground">
            We couldn&apos;t load the next question. Your progress is saved — just try again.
          </p>
          <Button className="w-full" onClick={() => refetch()}>
            <RefreshCw className="h-4 w-4" /> Retry
          </Button>
        </motion.div>
      </div>
    );
  }

  // ─── Interview complete ───────────────────────────────────────────────────
  if (question === null && !preparing) {
    return (
      <div className="hero-wash flex min-h-screen items-center justify-center bg-background p-6">
        <motion.div
          initial="hidden"
          animate="visible"
          variants={scalePop}
          className="glass max-w-md rounded-2xl border-border/50 p-10 text-center"
        >
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <Sparkles className="h-7 w-7 text-primary" />
          </div>
          <h2 className="mb-3 text-2xl font-semibold">Interview Complete</h2>
          <p className="mb-8 text-sm leading-relaxed text-muted-foreground">
            Nicely done{answered ? ` — you answered ${answered} question${answered === 1 ? '' : 's'}` : ''}.
            We&apos;ll now score every answer and build your full report.
          </p>
          <Button
            className="w-full"
            onClick={() => completeSession.mutate(sessionId)}
            loading={completeSession.isPending}
          >
            View Final Report
          </Button>
        </motion.div>
      </div>
    );
  }

  const wordCount = answer.trim() ? answer.trim().split(/\s+/).length : 0;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Header */}
      <header className="flex h-16 items-center justify-between border-b border-border/50 bg-surface/60 px-6 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-coral opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-coral" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Live Interview Session</span>
          {answered > 0 && (
            <span className="ml-1 rounded-full bg-surface-elevated px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
              {answered} answered
            </span>
          )}
        </div>
        <button
          onClick={() => completeSession.mutate(sessionId)}
          className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
        >
          <StopCircle className="h-4 w-4" /> End Interview
        </button>
      </header>

      {/* Main workspace */}
      <motion.main
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.1)}
        className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 p-6 md:flex-row"
      >
        {/* Left: Question Area */}
        <motion.div variants={fadeUp} className="flex flex-1 flex-col gap-6">
          <div className="glass flex h-full flex-col rounded-2xl border-border/50 p-8">
            <AnimatePresence mode="wait">
              {preparing ? (
                <GeneratingQuestion key="gen" label="Thinking about your next question…" />
              ) : (
                <motion.div
                  key={question?.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.35 }}
                >
                  <div className="mb-5 flex items-center gap-2">
                    <Badge variant="primary">Question</Badge>
                    {question?.difficulty && (
                      <span className={`badge-${question.difficulty}`}>{question.difficulty}</span>
                    )}
                  </div>
                  <h1 className="text-2xl font-semibold leading-relaxed tracking-[-0.01em]">
                    {question?.content}
                  </h1>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Optional live presence check (camera + mic, on-device only) */}
          <PresenceMonitor />
        </motion.div>

        {/* Right: Answer Area */}
        <motion.div
          variants={fadeUp}
          className="glass flex flex-1 flex-col rounded-2xl border-border/50 p-6"
        >
          <div className="mb-4 flex items-center justify-between">
            <span className="text-sm font-semibold text-muted-foreground">
              {isCoding ? 'Your Solution' : 'Your Answer'}
            </span>
            <div className="flex items-center gap-2">
              {isCoding && <Badge variant="violet">Coding round</Badge>}
              {tts.supported && questionText && (
                <button
                  onClick={() => (tts.speaking ? tts.cancel() : tts.speak(questionText))}
                  title="Read question aloud"
                  className={cn(
                    'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                    tts.speaking
                      ? 'border-primary/30 bg-primary/10 text-primary'
                      : 'border-border text-muted-foreground hover:text-foreground'
                  )}
                >
                  <Volume2 className="h-3 w-3" /> {tts.speaking ? 'Speaking…' : 'Hear question'}
                </button>
              )}
            </div>
          </div>

          {/* One consistent interviewer voice — Indian English, auto-selected.
              No picker: the interviewer is a person, and letting the voice
              change mid-session broke that illusion. */}
          {!useTyping && tts.supported && tts.activeVoice && (
            <div className="mb-4 flex items-center gap-2">
              <span className="flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground">
                <Volume2 className="h-3 w-3" />
                Interviewer voice: {tts.activeVoice.name}
                {!tts.activeVoice.lang.toLowerCase().startsWith('en-in') && (
                  <span
                    className="text-accent-amber-ink"
                    title="No Indian English voice is installed on this device, so the closest available one is used."
                  >
                    · not en-IN
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => tts.speak('Hi, I will be your interviewer today. Let us begin.')}
                className="rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                Preview
              </button>
            </div>
          )}

          {isCoding ? (
            <CodingWorkspace
              disabled={preparing}
              submitting={submitAnswer.isPending}
              problemTitle="Coding question"
              problemDescription={question?.content ?? ''}
              difficulty={question?.difficulty ?? 'medium'}
              onSubmit={({ language, code }: { language: CodeLanguage; code: string }) =>
                submitContent(`\`\`\`${language}\n${code}\n\`\`\``)
              }
            />
          ) : useTyping ? (
            /* Typing fallback */
            <>
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                disabled={preparing}
                placeholder="Type your answer here as if you were speaking to an interviewer…"
                className="ease-out-expo w-full flex-1 resize-none rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm leading-relaxed transition-shadow focus:border-primary/40 focus:shadow-glow focus:outline-none"
              />
              <div className="mt-3 flex items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground/70">
                  {wordCount} {wordCount === 1 ? 'word' : 'words'}
                </span>
                <div className="flex items-center gap-3">
                  {stt.supported && (
                    <button
                      onClick={() => setTyping(false)}
                      className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Use voice instead
                    </button>
                  )}
                  <Button onClick={handleSubmit} disabled={preparing || !answer.trim()} loading={submitAnswer.isPending}>
                    <Send className="h-4 w-4" /> Submit &amp; Next
                  </Button>
                </div>
              </div>
            </>
          ) : (
            /* Voice-first answer UI */
            <div className="flex flex-1 flex-col items-center justify-center gap-5 py-4">
              <button
                onClick={toggleMic}
                disabled={preparing}
                aria-label={stt.listening ? 'Stop recording' : 'Start recording'}
                className={cn(
                  'relative flex h-24 w-24 items-center justify-center rounded-full transition-all disabled:opacity-50',
                  stt.listening
                    ? 'bg-destructive text-destructive-foreground shadow-glow'
                    : 'bg-primary text-primary-foreground shadow-glow hover:shadow-glow-lg'
                )}
              >
                {stt.listening && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-destructive opacity-40" />
                )}
                {stt.listening ? <MicOff className="h-9 w-9" /> : <Mic className="h-9 w-9" />}
              </button>

              <p className="text-sm font-medium text-muted-foreground">
                {stt.listening
                  ? 'Listening… tap to stop'
                  : answer
                    ? 'Tap the mic to add more, or submit'
                    : 'Tap the mic and speak your answer'}
              </p>

              {/* Live transcript — filler words in red, pauses marked */}
              <div className="min-h-[96px] w-full flex-1 overflow-y-auto rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm leading-relaxed">
                <DeliveryTranscript
                  text={answer}
                  pauses={stt.pauses}
                  interim={stt.listening ? stt.interim : ''}
                />
              </div>

              <div className="flex w-full items-center justify-between gap-3">
                <button
                  onClick={() => {
                    stt.stop();
                    setTyping(true);
                  }}
                  className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                >
                  Trouble with the mic? Type instead
                </button>
                <div className="flex items-center gap-2">
                  {answer && !submitAnswer.isPending && (
                    <button
                      onClick={() => {
                        setAnswer('');
                        stt.reset();
                      }}
                      className="rounded-lg border border-border px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                    >
                      Clear
                    </button>
                  )}
                  <Button onClick={handleSubmit} disabled={preparing || !answer.trim()} loading={submitAnswer.isPending}>
                    <Send className="h-4 w-4" /> Submit &amp; Next
                  </Button>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      </motion.main>
    </div>
  );
}
