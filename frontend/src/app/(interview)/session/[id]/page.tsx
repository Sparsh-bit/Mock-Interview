'use client';

import { useInterview } from '@/hooks/useInterview';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, Mic, Send, StopCircle, ArrowRight, CheckCircle2, AlertTriangle, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { fadeUp, scalePop, staggerContainer, easeOutExpo } from '@/lib/motion';

interface Feedback {
  tech: number;
  comm: number;
  fb: string;
  strengths: string[];
  weaknesses: string[];
  bluffing: boolean;
}

function ScoreDial({ label, value, accent }: { label: string; value: number; accent: 'primary' | 'violet' }) {
  const color = accent === 'primary' ? 'text-primary' : 'text-accent-violet';
  const ring = accent === 'primary' ? 'stroke-primary' : 'stroke-accent-violet';
  const circumference = 2 * Math.PI * 26;
  const offset = circumference - (value / 10) * circumference;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative h-16 w-16">
        <svg className="h-16 w-16 -rotate-90" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r="26" strokeWidth="5" className="stroke-border/60" fill="none" />
          <motion.circle
            cx="32"
            cy="32"
            r="26"
            strokeWidth="5"
            fill="none"
            strokeLinecap="round"
            className={ring}
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: offset }}
            transition={{ duration: 0.9, ease: easeOutExpo, delay: 0.15 }}
          />
        </svg>
        <div className={`absolute inset-0 flex items-center justify-center text-sm font-bold ${color}`}>
          {value.toFixed(1)}
        </div>
      </div>
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
    </div>
  );
}

export default function LiveSessionPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const { useNextQuestion, submitAnswer, completeSession } = useInterview();

  const { data, isLoading, refetch } = useNextQuestion(sessionId);
  const [answer, setAnswer] = useState('');
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const handleSubmit = async () => {
    if (!answer.trim() || !data?.question) return;

    submitAnswer.mutate(
      { sessionId, questionId: data.question.id, content: answer },
      {
        onSuccess: (res) => {
          setFeedback({
            tech: res.technical_score,
            comm: res.communication_score,
            fb: res.feedback,
            strengths: res.strengths ?? [],
            weaknesses: res.weaknesses ?? [],
            bluffing: res.is_bluffing_detected,
          });
        },
        onError: (err: Error) => {
          toast.error(err.message || 'Failed to submit answer.');
        },
      }
    );
  };

  const handleNext = () => {
    setAnswer('');
    setFeedback(null);
    refetch();
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (data?.question === null) {
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
          <h2 className="mb-3 text-2xl font-bold">Interview Complete</h2>
          <p className="mb-8 text-sm leading-relaxed text-muted-foreground">
            You&apos;ve reached the end of this track. Generating your final report&hellip;
          </p>
          <Button className="w-full" onClick={() => completeSession.mutate(sessionId)} loading={completeSession.isPending}>
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
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-500 opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-500" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Live Interview Session</span>
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
            <div className="mb-5 flex items-center gap-2">
              <Badge variant="primary">Question</Badge>
              {data?.question?.difficulty && (
                <span className={`badge-${data.question.difficulty}`}>{data.question.difficulty}</span>
              )}
            </div>
            <h1 className="text-2xl font-bold leading-relaxed tracking-[-0.01em]">
              {data?.question?.content || 'Loading question…'}
            </h1>

            <AnimatePresence>
              {feedback && (
                <motion.div
                  initial="hidden"
                  animate="visible"
                  variants={staggerContainer(0.08)}
                  className="mt-8 border-t border-border/50 pt-8"
                >
                  <motion.h3
                    variants={fadeUp}
                    className="mb-5 text-xs font-semibold uppercase tracking-widest text-muted-foreground"
                  >
                    AI Evaluation
                  </motion.h3>

                  <motion.div variants={fadeUp} className="mb-5 flex gap-6">
                    <ScoreDial label="Technical" value={feedback.tech} accent="primary" />
                    <ScoreDial label="Communication" value={feedback.comm} accent="violet" />
                  </motion.div>

                  <motion.p variants={fadeUp} className="text-sm leading-relaxed text-foreground/85">
                    {feedback.fb}
                  </motion.p>

                  {feedback.bluffing && (
                    <motion.div
                      variants={fadeUp}
                      className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 p-3"
                    >
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                      <p className="text-xs font-medium text-amber-300">
                        This answer sounded confident but may not be fully accurate — review the gaps below.
                      </p>
                    </motion.div>
                  )}

                  {(feedback.strengths.length > 0 || feedback.weaknesses.length > 0) && (
                    <motion.div variants={fadeUp} className="mt-5 grid gap-4 sm:grid-cols-2">
                      {feedback.strengths.length > 0 && (
                        <div>
                          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-600">
                            <CheckCircle2 className="h-3.5 w-3.5" /> Strengths
                          </p>
                          <ul className="space-y-1.5 text-sm text-foreground/80">
                            {feedback.strengths.map((s, i) => (
                              <li key={i} className="flex gap-2">
                                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
                                {s}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {feedback.weaknesses.length > 0 && (
                        <div>
                          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-orange-600">
                            <AlertTriangle className="h-3.5 w-3.5" /> Gaps
                          </p>
                          <ul className="space-y-1.5 text-sm text-foreground/80">
                            {feedback.weaknesses.map((w, i) => (
                              <li key={i} className="flex gap-2">
                                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-orange-400" />
                                {w}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </motion.div>
                  )}

                  <motion.div variants={fadeUp}>
                    <Button variant="ghost" className="mt-6 px-0 text-primary hover:bg-transparent hover:opacity-80" onClick={handleNext}>
                      Next Question <ArrowRight className="h-4 w-4" />
                    </Button>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>

        {/* Right: Answer Area */}
        <motion.div variants={fadeUp} className="glass flex flex-1 flex-col rounded-2xl border-border/50 p-6">
          <div className="mb-4 flex items-center justify-between">
            <span className="text-sm font-semibold text-muted-foreground">Your Answer</span>
            <button
              disabled
              className="flex items-center gap-1.5 rounded-full border border-border/60 px-2.5 py-1 text-xs text-muted-foreground/70"
              title="Coming soon"
            >
              <Mic className="h-3 w-3" /> Voice Mode
            </button>
          </div>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            disabled={!!feedback || submitAnswer.isPending}
            placeholder="Type your answer here as if you were speaking to an interviewer…"
            className="ease-out-expo w-full flex-1 resize-none rounded-xl border border-border/50 bg-surface/50 p-4 text-sm leading-relaxed transition-shadow focus:border-primary/40 focus:shadow-glow focus:outline-none"
          />
          <div className="mt-3 flex items-center justify-between">
            {submitAnswer.isPending ? (
              <AIWorkingIndicator />
            ) : (
              <span className="text-xs text-muted-foreground/70">
                {wordCount} {wordCount === 1 ? 'word' : 'words'}
              </span>
            )}
            <Button onClick={handleSubmit} disabled={!!feedback || !answer.trim()} loading={submitAnswer.isPending}>
              <Send className="h-4 w-4" /> Submit Answer
            </Button>
          </div>
        </motion.div>
      </motion.main>
    </div>
  );
}
