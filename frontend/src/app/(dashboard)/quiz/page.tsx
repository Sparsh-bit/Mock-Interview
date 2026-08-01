'use client';

import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { motion } from 'framer-motion';
import { AlertTriangle, CheckCircle2, Clock, Loader2, ListChecks, RotateCcw, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { useQuiz, useBankTopics, type QuizQuestion, type SubmitQuizResponse } from '@/hooks/useQuiz';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';
type Phase = 'setup' | 'exam' | 'results';
type Mode = 'instant' | 'ai';

const COUNT_OPTIONS = [5, 8, 10, 15];
const MINUTE_OPTIONS = [5, 10, 15, 20];
// Common fresher-interview topics across most companies — quick presets.
const PRESET_TOPICS = [
  'Core Java & OOP',
  'Data Structures',
  'SQL & Databases',
  'Aptitude & Reasoning',
  'Operating Systems',
  'OOPS Concepts',
  'DBMS',
  'Computer Networks',
];

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function QuizPage() {
  // useSearchParams requires a Suspense boundary in the App Router. Without it the
  // page opts the whole route into client-side rendering and Next warns at build.
  return (
    <Suspense
      fallback={<div className="mt-10 text-center text-sm text-muted-foreground">Loading…</div>}
    >
      <Quiz />
    </Suspense>
  );
}

function Quiz() {
  const { startQuiz, startBankQuiz, submitQuiz } = useQuiz();
  const searchParams = useSearchParams();
  // Arriving from a roadmap topic: "Take a quiz on DBMS & SQL" should land the
  // candidate IN the quiz, not on a settings form they have to fill in again.
  const presetTopic = searchParams.get('topic') ?? '';
  const autostart = searchParams.get('autostart') === '1';
  const { data: bankTopics } = useBankTopics();
  const [phase, setPhase] = useState<Phase>('setup');
  const [mode, setMode] = useState<Mode>('instant');
  const [count, setCount] = useState(8);
  const [minutes, setMinutes] = useState(10);
  const [topic, setTopic] = useState(presetTopic);
  const [company, setCompany] = useState('');
  const [bankTopic, setBankTopic] = useState(presetTopic); // '' = mix of all topics

  const [quizId, setQuizId] = useState<string>('');
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [results, setResults] = useState<SubmitQuizResponse | null>(null);
  const submittedRef = useRef(false);

  const starting = startQuiz.isPending || startBankQuiz.isPending;

  // The topic field is a comma-separated list so several preset topics can be
  // combined (e.g. "Core Java & OOP, SQL & Databases"). Clicking a chip toggles
  // it in or out; typing custom text still works alongside the chips.
  const selectedTopics = topic
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);

  const toggleTopic = (t: string) => {
    const exists = selectedTopics.some((s) => s.toLowerCase() === t.toLowerCase());
    const next = exists
      ? selectedTopics.filter((s) => s.toLowerCase() !== t.toLowerCase())
      : [...selectedTopics, t];
    setTopic(next.join(', '));
  };

  const handleStart = () => {
    const onSuccess = (data: { quiz_id: string; questions: QuizQuestion[]; minutes: number }) => {
      setQuizId(data.quiz_id);
      setQuestions(data.questions);
      setAnswers({});
      setSecondsLeft(data.minutes * 60);
      submittedRef.current = false;
      setPhase('exam');
    };
    const onError = (err: Error) => toast.error(err.message || 'Could not start the quiz.');

    if (mode === 'instant') {
      startBankQuiz.mutate({ topic: bankTopic, count, minutes }, { onSuccess, onError });
    } else {
      startQuiz.mutate({ count, minutes, topic, company }, { onSuccess, onError });
    }
  };

  // Fire the preset quiz exactly once. A ref rather than state because this must
  // not re-fire when the component re-renders mid-quiz — which would discard the
  // candidate's answers and restart them without warning.
  const autostartedRef = useRef(false);
  useEffect(() => {
    if (!autostart || autostartedRef.current || phase !== 'setup') return;
    if (startQuiz.isPending || startBankQuiz.isPending) return;
    autostartedRef.current = true;
    handleStart();
    // handleStart is stable enough for this one-shot; re-running on its identity
    // would defeat the guard above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autostart, phase]);

  const handleSubmit = useCallback(() => {
    if (submittedRef.current) return;
    submittedRef.current = true;
    submitQuiz.mutate(
      { quizId, answers },
      {
        onSuccess: (data) => {
          setResults(data);
          setPhase('results');
        },
        onError: (err: Error) => {
          submittedRef.current = false;
          toast.error(err.message || 'Could not submit the quiz.');
        },
      }
    );
  }, [quizId, answers, submitQuiz]);

  // Countdown timer — auto-submits when it hits zero.
  useEffect(() => {
    if (phase !== 'exam') return;
    if (secondsLeft <= 0) {
      toast.info("Time's up — submitting your quiz.");
      handleSubmit();
      return;
    }
    const id = setInterval(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearInterval(id);
  }, [phase, secondsLeft, handleSubmit]);

  const resetToSetup = () => {
    setPhase('setup');
    setResults(null);
    setQuestions([]);
    setAnswers({});
  };

  // ─── Setup ──────────────────────────────────────────────────────────────
  if (phase === 'setup') {
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-2xl space-y-8">
        <motion.div variants={fadeUp}>
          <h1 className="text-2xl font-bold tracking-tight">Practice Quiz</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Multiple-choice practice for common fresher-interview topics — instant from a curated bank, or freshly AI-generated for a specific company/topic.
          </p>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card className="space-y-6 p-8">
            {/* Mode toggle */}
            <div className="grid grid-cols-2 gap-2 rounded-xl border border-border p-1">
              <button
                onClick={() => setMode('instant')}
                className={cn(
                  'rounded-lg px-4 py-2 text-sm font-semibold transition-colors',
                  mode === 'instant' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                Instant practice
              </button>
              <button
                onClick={() => setMode('ai')}
                className={cn(
                  'rounded-lg px-4 py-2 text-sm font-semibold transition-colors',
                  mode === 'ai' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                AI-generated
              </button>
            </div>
            <p className="-mt-3 text-xs text-muted-foreground">
              {mode === 'instant'
                ? 'Curated common-fresher questions, loads instantly.'
                : 'Fresh questions written by AI for your company/topic (takes up to a minute).'}
            </p>

            {mode === 'instant' ? (
              <div>
                <label htmlFor="bank-topic" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Topic
                </label>
                <select
                  id="bank-topic"
                  value={bankTopic}
                  onChange={(e) => setBankTopic(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-elevated px-4 py-2.5 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                >
                  <option value="">Mixed — all topics</option>
                  {(bankTopics ?? []).map((t) => (
                    <option key={t.topic} value={t.topic}>
                      {t.topic} ({t.count})
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <>
                <div>
                  <label htmlFor="quiz-company" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Company you&apos;re preparing for <span className="font-normal normal-case">(optional)</span>
                  </label>
                  <Input
                    id="quiz-company"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder="e.g. Cognizant, TCS, Infosys, Accenture…"
                  />
                </div>

                <div>
                  <label htmlFor="quiz-topic" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Topic or request <span className="font-normal normal-case">(optional — pick one or more)</span>
                  </label>
                  <Input
                    id="quiz-topic"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="e.g. HashMap internals, SQL joins, OOP concepts…"
                  />
                  <div className="mt-2 flex flex-wrap gap-2">
                    {PRESET_TOPICS.map((t) => {
                      const active = selectedTopics.some((s) => s.toLowerCase() === t.toLowerCase());
                      return (
                        <button
                          key={t}
                          type="button"
                          aria-pressed={active}
                          onClick={() => toggleTopic(t)}
                          className={cn(
                            'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                            active
                              ? 'border-primary bg-primary/10 text-primary'
                              : 'border-border text-muted-foreground hover:text-foreground'
                          )}
                        >
                          {t}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            )}

            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Number of questions
              </label>
              <div className="flex flex-wrap gap-2">
                {COUNT_OPTIONS.map((c) => (
                  <button
                    key={c}
                    onClick={() => setCount(c)}
                    className={cn(
                      'rounded-lg border px-4 py-2 text-sm font-medium transition-colors',
                      count === c ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'
                    )}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Time limit (minutes)
              </label>
              <div className="flex flex-wrap gap-2">
                {MINUTE_OPTIONS.map((m) => (
                  <button
                    key={m}
                    onClick={() => setMinutes(m)}
                    className={cn(
                      'rounded-lg border px-4 py-2 text-sm font-medium transition-colors',
                      minutes === m ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'
                    )}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {starting && mode === 'ai' ? (
              <div className="flex flex-col items-center gap-3 py-4">
                <AIWorkingIndicator
                  messages={[
                    'Generating your quiz…',
                    'Writing fresh questions…',
                    'Building answer options…',
                    'Almost ready…',
                  ]}
                />
              </div>
            ) : (
              <Button className="w-full" onClick={handleStart} loading={starting}>
                <ListChecks className="h-4 w-4" /> Start Quiz
              </Button>
            )}
          </Card>
        </motion.div>
      </motion.div>
    );
  }

  // ─── Exam ───────────────────────────────────────────────────────────────
  if (phase === 'exam') {
    const answeredCount = Object.keys(answers).length;
    const lowTime = secondsLeft <= 30;
    return (
      <div className="mx-auto max-w-3xl space-y-6 pb-24">
        {/* Sticky timer bar */}
        <div className="sticky top-0 z-10 -mx-6 flex items-center justify-between border-b border-border/60 bg-background/80 px-6 py-3 backdrop-blur-md">
          <span className="text-sm font-medium text-muted-foreground">
            {answeredCount}/{questions.length} answered
          </span>
          <span
            className={cn(
              'flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-bold tabular-nums',
              lowTime ? 'border-destructive/40 bg-destructive/10 text-destructive' : 'border-border text-foreground'
            )}
          >
            <Clock className="h-3.5 w-3.5" /> {formatTime(secondsLeft)}
          </span>
        </div>

        {questions.map((q, idx) => (
          <Card key={q.id} className="space-y-4 p-6">
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-sm font-semibold leading-relaxed">
                <span className="mr-2 text-muted-foreground">Q{idx + 1}.</span>
                {q.question}
              </h3>
              <Badge variant="neutral">{q.topic}</Badge>
            </div>
            <div className="space-y-2">
              {q.options.map((opt, oi) => {
                const selected = answers[q.id] === oi;
                return (
                  <button
                    key={oi}
                    onClick={() => setAnswers((a) => ({ ...a, [q.id]: oi }))}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-colors',
                      selected ? 'border-primary bg-primary/10 text-foreground' : 'border-border hover:border-primary/40'
                    )}
                  >
                    <span
                      className={cn(
                        'flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border text-[11px] font-bold',
                        selected ? 'border-primary bg-primary text-primary-foreground' : 'border-border text-muted-foreground'
                      )}
                    >
                      {String.fromCharCode(65 + oi)}
                    </span>
                    {opt}
                  </button>
                );
              })}
            </div>
          </Card>
        ))}

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            {answeredCount < questions.length
              ? `${questions.length - answeredCount} unanswered — unanswered questions are marked wrong.`
              : 'All questions answered.'}
          </p>
          <Button onClick={handleSubmit} loading={submitQuiz.isPending}>
            <CheckCircle2 className="h-4 w-4" /> Submit Quiz
          </Button>
        </div>
      </div>
    );
  }

  // ─── Results ──────────────────────────────────────────────────────────────
  if (phase === 'results' && results) {
    const pct = results.percentage;
    const tone = pct >= 70 ? 'text-emerald-600' : pct >= 40 ? 'text-amber-600' : 'text-red-600';
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.06)} className="mx-auto max-w-3xl space-y-6 pb-12">
        <motion.div variants={fadeUp}>
          <Card className="flex flex-col items-center gap-2 p-8 text-center">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Your Score</p>
            <p className={cn('text-5xl font-bold tracking-tight', tone)}>{pct}%</p>
            <p className="text-sm text-muted-foreground">
              {results.score} of {results.total} correct
            </p>
            <Button variant="secondary" className="mt-4" onClick={resetToSetup}>
              <RotateCcw className="h-4 w-4" /> New Quiz
            </Button>
          </Card>
        </motion.div>

        {results.results.map((r, idx) => (
          <motion.div key={r.question_id} variants={fadeUp}>
            <Card className={cn('space-y-3 p-6', r.is_correct ? 'border-emerald-500/30' : 'border-red-500/30')}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-semibold leading-relaxed">
                  <span className="mr-2 text-muted-foreground">Q{idx + 1}.</span>
                  {r.question}
                </h3>
                {r.is_correct ? (
                  <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-emerald-600" />
                ) : (
                  <XCircle className="h-5 w-5 flex-shrink-0 text-red-600" />
                )}
              </div>
              <div className="space-y-1.5">
                {r.options.map((opt, oi) => {
                  const isCorrect = oi === r.correct_index;
                  const isSelected = oi === r.selected_index;
                  return (
                    <div
                      key={oi}
                      className={cn(
                        'flex items-center gap-2 rounded-lg border px-3 py-2 text-sm',
                        isCorrect && 'border-emerald-500/40 bg-emerald-500/10',
                        isSelected && !isCorrect && 'border-red-500/40 bg-red-500/10',
                        !isCorrect && !isSelected && 'border-border/50'
                      )}
                    >
                      <span className="font-mono text-[11px] text-muted-foreground">{String.fromCharCode(65 + oi)}</span>
                      <span className="flex-1">{opt}</span>
                      {isCorrect && <span className="text-[11px] font-semibold text-emerald-600">Correct</span>}
                      {isSelected && !isCorrect && <span className="text-[11px] font-semibold text-red-600">Your answer</span>}
                    </div>
                  );
                })}
              </div>
              {r.selected_index === null && (
                <p className="flex items-center gap-1.5 text-xs text-amber-600">
                  <AlertTriangle className="h-3.5 w-3.5" /> Not answered
                </p>
              )}
              {r.explanation && (
                <p className="rounded-lg bg-secondary/60 p-3 text-xs text-muted-foreground">{r.explanation}</p>
              )}
            </Card>
          </motion.div>
        ))}
      </motion.div>
    );
  }

  return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
    </div>
  );
}
