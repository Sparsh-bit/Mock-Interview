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
import { useQuiz, useBankTopics, type QuizDifficulty, type QuizQuestion, type SubmitQuizResponse } from '@/hooks/useQuiz';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { scoreBand } from '@/lib/score-bands';
import { HEAT } from '@/lib/tones';
import { cn } from '@/lib/utils';
import { PageHeader } from '@/components/ui/page-header';

export const runtime = 'edge';

/**
 * The selected difficulty chip.
 *
 * The colours are the shared heat scale (lib/tones) — teal warm-up, amber standard, coral runs
 * hot — so a "hard" quiz and a "hard" track are the same colour. "Any" is neutral indigo
 * because it is the ABSENCE of a choice rather than a level, and giving it a heat would put it
 * on the scale it exists to opt out of.
 *
 * `-soft` fill with `-ink` text rather than white on the solid tone. I wrote these as
 * `bg-accent-amber text-white` first, which measures 3.02:1 — amber is the lightest tone in
 * the palette and tailwind.config.ts says in its own comment that the bare tones are for
 * graphics rather than text. Coral came out at 4.35:1. Only indigo, teal and plum are dark
 * enough for white, and picking per-tone would make four chips in one row inconsistent for a
 * reason no reader could see, so the solid border carries the selected state instead.
 */
const HEAT_SELECTED: Record<string, string> = {
  any: 'border-accent-indigo bg-accent-indigo-soft text-accent-indigo-ink',
  easy: `${HEAT.easy.border} ${HEAT.easy.chip}`,
  medium: `${HEAT.medium.border} ${HEAT.medium.chip}`,
  hard: `${HEAT.hard.border} ${HEAT.hard.chip}`,
};

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
  // null = any difficulty. The bank always reported each question's level to
  // the client but there was no way to ask for one, so wanting a hard round
  // meant re-rolling until enough hard questions happened to come up.
  const [bankDifficulty, setBankDifficulty] = useState<QuizDifficulty | null>(null);

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
      startBankQuiz.mutate(
        { topic: bankTopic, count, minutes, difficulty: bankDifficulty },
        { onSuccess, onError },
      );
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
          <PageHeader
            eyebrow="Practice"
            title="Practice Quiz"
            description="Multiple-choice practice for common fresher-interview topics — instant from a curated bank, or freshly AI-generated for a specific company/topic."
          />
        </motion.div>

        <motion.div variants={fadeUp}>
          {/* THE LIT ELEMENT on the setup view — docs/DESIGN-LANGUAGE §1. Everything on this
              screen exists to configure one quiz and press start, so this panel is the
              subject and the copy around it is not. */}
          <Card variant="outline" className="lit space-y-6 p-5 sm:p-8">
            {/* Mode toggle */}
            {/* Stacked below sm. Two 104px columns cannot hold "Instant practice" and
                "AI-generated" at text-sm without breaking mid-word. */}
            <div className="grid grid-cols-1 gap-2 rounded-xl border border-border p-1 sm:grid-cols-2">
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

                {/* Difficulty. Levels a topic has none of are disabled rather than
                    offered and then 404'd — the count comes from the same endpoint
                    as the topic list, so it cannot disagree with the bank. */}
                <div className="mt-4">
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Difficulty
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {([null, 'easy', 'medium', 'hard'] as const).map((level) => {
                      const selected = bankTopics?.find((t) => t.topic === bankTopic);
                      const available =
                        level === null
                          ? true
                          : !selected || selected[level] > 0;
                      const n =
                        level === null
                          ? null
                          : selected
                            ? selected[level]
                            : (bankTopics ?? []).reduce((sum, t) => sum + t[level], 0);
                      return (
                        <button
                          key={level ?? 'any'}
                          type="button"
                          disabled={!available}
                          onClick={() => setBankDifficulty(level)}
                          className={cn(
                            'rounded-lg border px-3 py-1.5 text-xs font-medium capitalize transition-colors',
                            /*
                             * THE HEAT SCALE — docs/DESIGN-LANGUAGE §2. Every level was the
                             * same indigo, so the one control on this page whose entire
                             * purpose is "how hard do you want this" said nothing until you
                             * read the words. Teal is a warm-up, amber is the real thing,
                             * coral is the round that decides it, and "Any" stays neutral
                             * because it is the absence of a choice rather than a level.
                             *
                             * Deliberately NOT emerald/coral, which mean passed and failed on
                             * the score bands. Hard is not bad.
                             */
                            bankDifficulty === level
                              ? HEAT_SELECTED[level ?? 'any']
                              : 'border-border bg-surface-elevated text-muted-foreground hover:text-foreground',
                            !available && 'cursor-not-allowed opacity-40 hover:text-muted-foreground',
                          )}
                          title={!available ? `No ${level} questions for this topic yet` : undefined}
                        >
                          {level ?? 'Any'}
                          {n !== null && <span className="ml-1 opacity-70">({n})</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
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
                              ? 'border-accent-indigo/50 bg-accent-indigo-soft text-accent-indigo-ink'
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
                      count === c
                        ? 'border-accent-indigo/50 bg-accent-indigo-soft text-accent-indigo-ink'
                        : 'border-border text-muted-foreground hover:text-foreground'
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
                      minutes === m
                        ? 'border-accent-indigo/50 bg-accent-indigo-soft text-accent-indigo-ink'
                        : 'border-border text-muted-foreground hover:text-foreground'
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
        {/*
          THE NEGATIVE MARGIN HAS TO MATCH THE SHELL'S PADDING, and `-mx-6` matched neither
          of the two values it actually has.

          (dashboard)/layout.tsx pads the content region `px-4 sm:px-8`. This bar bleeds to
          the edges by cancelling that padding, so below sm it was pulling 24px against 16px
          of padding — 8px past the viewport edge on each side. That is 16px of content wider
          than the screen, which is a horizontal scrollbar on the whole page, on the one
          screen in the product where the candidate is against a clock.

          Mirrored per breakpoint instead, so the bleed is exact at both.
        */}
        <div className="sticky top-0 z-10 -mx-4 flex flex-wrap items-center justify-between gap-2 border-b border-border/60 bg-background/80 px-4 py-3 backdrop-blur-md sm:-mx-8 sm:px-8">
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
                      selected
                        ? 'border-accent-indigo/50 bg-accent-indigo-soft text-foreground'
                        : 'border-border hover:border-accent-indigo/40'
                    )}
                  >
                    <span
                      className={cn(
                        'flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border text-[11px] font-bold',
                        selected
                          ? 'border-accent-indigo bg-accent-indigo text-white'
                          : 'border-border text-muted-foreground'
                      )}
                    >
                      {String.fromCharCode(65 + oi)}
                    </span>
                    {/* Wrapped and `min-w-0`: a bare text node is an anonymous flex item that
                        cannot be told to break, and quiz options are full of unbreakable
                        tokens — `HashMap<String,List<Integer>>`, `ConcurrentModificationException`
                        — which pushed the button past the card edge. */}
                    <span className="min-w-0 break-words">{opt}</span>
                  </button>
                );
              })}
            </div>
          </Card>
        ))}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="min-w-0 text-xs text-muted-foreground">
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
    /*
     * The shared bands, not thresholds of this page's own. `percentage` is a candidate's
     * performance out of 100 — the same kind of number as an interview score — so a 72% quiz
     * and a 72 interview must not be different colours, and until now they were: this used
     * 70/40 against lib/score-bands' 85/70/55/40.
     *
     * That made this the sixth independent answer in the product to "what does this score
     * mean". score-bands.test.ts now fails the build if a seventh appears.
     */
    const tone = scoreBand(pct).ink;
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
            <Card className={cn('space-y-3 p-6', r.is_correct ? 'border-accent-emerald/30' : 'border-accent-coral/30')}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-semibold leading-relaxed">
                  <span className="mr-2 text-muted-foreground">Q{idx + 1}.</span>
                  {r.question}
                </h3>
                {r.is_correct ? (
                  <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-accent-emerald-ink" />
                ) : (
                  <XCircle className="h-5 w-5 flex-shrink-0 text-accent-coral-ink" />
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
                        isCorrect && 'border-accent-emerald/40 bg-accent-emerald/10',
                        isSelected && !isCorrect && 'border-accent-coral/40 bg-accent-coral/10',
                        !isCorrect && !isSelected && 'border-border/50'
                      )}
                    >
                      <span className="font-mono text-[11px] text-muted-foreground">{String.fromCharCode(65 + oi)}</span>
                      <span className="min-w-0 flex-1 break-words">{opt}</span>
                      {isCorrect && <span className="text-[11px] font-semibold text-accent-emerald-ink">Correct</span>}
                      {isSelected && !isCorrect && <span className="text-[11px] font-semibold text-accent-coral-ink">Your answer</span>}
                    </div>
                  );
                })}
              </div>
              {r.selected_index === null && (
                <p className="flex items-center gap-1.5 text-xs text-accent-amber-ink">
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
      <Loader2 className="h-8 w-8 animate-spin text-accent-amber" />
    </div>
  );
}
