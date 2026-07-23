'use client';

import { useInterview } from '@/hooks/useInterview';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, Mic, Send, StopCircle, ArrowRight } from 'lucide-react';
import { toast } from 'sonner';

export default function LiveSessionPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const { useNextQuestion, submitAnswer, completeSession } = useInterview();

  const { data, isLoading, refetch } = useNextQuestion(sessionId);
  const [answer, setAnswer] = useState('');
  const [feedback, setFeedback] = useState<{
    tech: number;
    comm: number;
    fb: string;
    strengths: string[];
    weaknesses: string[];
    bluffing: boolean;
  } | null>(null);

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
        }
      }
    );
  };

  const handleNext = () => {
    setAnswer('');
    setFeedback(null);
    refetch();
  };

  if (isLoading) {
    return <div className="flex min-h-screen items-center justify-center bg-background"><Loader2 className="animate-spin text-primary h-8 w-8" /></div>;
  }

  if (data?.question === null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="text-center glass p-10 rounded-2xl max-w-md border-border/50">
          <h2 className="text-2xl font-bold mb-4">Interview Complete!</h2>
          <p className="text-muted-foreground mb-8">You&apos;ve reached the end of this track. Generating your final report...</p>
          <button
            onClick={() => completeSession.mutate(sessionId)}
            className="bg-primary text-primary-foreground px-6 py-3 rounded-xl font-bold w-full"
          >
            View Final Report
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Header */}
      <header className="h-16 border-b border-border/50 flex items-center justify-between px-6 bg-surface/50">
        <div className="flex items-center gap-3">
          <div className="h-3 w-3 bg-red-500 rounded-full animate-pulse" />
          <span className="font-semibold text-sm">Live Session Recording</span>
        </div>
        <button
          onClick={() => completeSession.mutate(sessionId)}
          className="flex items-center gap-2 text-xs font-medium text-destructive hover:bg-destructive/10 px-3 py-1.5 rounded-lg transition-colors"
        >
          <StopCircle className="h-4 w-4" /> End Interview
        </button>
      </header>

      {/* Main workspace */}
      <main className="flex-1 flex flex-col md:flex-row p-6 gap-6 max-w-7xl mx-auto w-full">

        {/* Left: Question Area */}
        <div className="flex-1 flex flex-col gap-6">
          <div className="glass rounded-2xl border border-border/50 p-8 h-full">
            <span className="badge-medium mb-4 inline-block">Question</span>
            <h1 className="text-2xl font-bold leading-relaxed">
              {data?.question?.content || 'Loading question...'}
            </h1>

            <AnimatePresence>
              {feedback && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mt-8 pt-8 border-t border-border/50"
                >
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-4">AI Evaluation</h3>
                  <div className="flex gap-4 mb-4">
                    <div className="bg-surface rounded-lg p-4 flex-1 text-center border border-border/50">
                      <p className="text-2xl font-bold text-emerald-400">{feedback.tech}/10</p>
                      <p className="text-xs text-muted-foreground mt-1">Technical Accuracy</p>
                    </div>
                    <div className="bg-surface rounded-lg p-4 flex-1 text-center border border-border/50">
                      <p className="text-2xl font-bold text-blue-400">{feedback.comm}/10</p>
                      <p className="text-xs text-muted-foreground mt-1">Communication</p>
                    </div>
                  </div>
                  <p className="text-sm leading-relaxed text-foreground/80">{feedback.fb}</p>

                  {feedback.bluffing && (
                    <p className="mt-3 text-xs font-semibold text-amber-400">
                      This answer sounded confident but may not be fully accurate — review the gaps below.
                    </p>
                  )}

                  {(feedback.strengths.length > 0 || feedback.weaknesses.length > 0) && (
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      {feedback.strengths.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-1.5">Strengths</p>
                          <ul className="space-y-1 text-sm text-foreground/80 list-disc list-inside">
                            {feedback.strengths.map((s, i) => <li key={i}>{s}</li>)}
                          </ul>
                        </div>
                      )}
                      {feedback.weaknesses.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-orange-400 mb-1.5">Gaps</p>
                          <ul className="space-y-1 text-sm text-foreground/80 list-disc list-inside">
                            {feedback.weaknesses.map((w, i) => <li key={i}>{w}</li>)}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  <button
                    onClick={handleNext}
                    className="mt-6 flex items-center gap-2 text-primary text-sm font-bold hover:opacity-80 transition-opacity"
                  >
                    Next Question <ArrowRight className="h-4 w-4" />
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Right: Answer Area */}
        <div className="flex-1 flex flex-col glass rounded-2xl border border-border/50 p-6">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-semibold text-muted-foreground">Your Answer</span>
            <button className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground">
              <Mic className="h-3 w-3" /> Voice Mode (Soon)
            </button>
          </div>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            disabled={!!feedback || submitAnswer.isPending}
            placeholder="Type your answer here as if you were speaking to an interviewer..."
            className="flex-1 w-full bg-surface/50 border border-border/50 rounded-xl p-4 resize-none focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
          <div className="mt-4 flex justify-end">
            <button
              onClick={handleSubmit}
              disabled={!!feedback || submitAnswer.isPending || !answer.trim()}
              className="flex items-center gap-2 bg-primary text-primary-foreground px-6 py-3 rounded-xl font-bold hover:bg-primary/90 disabled:opacity-50 transition-all"
            >
              {submitAnswer.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Submit Answer
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
