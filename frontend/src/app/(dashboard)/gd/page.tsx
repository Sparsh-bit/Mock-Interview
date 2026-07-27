'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Mic, MicOff, Send, Users, Play, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import { useSpeechRecognition } from '@/hooks/useSpeech';
import { useGD, useGDTopics, type GDTurn, type GDEvaluation } from '@/hooks/useGD';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';
type Phase = 'setup' | 'discussion' | 'results';

const YOU = 'You';

// ─── Realistic GD pacing ──────────────────────────────────────────────────────
// A real GD runs on a clock, not on turn-taking: the panel keeps talking whether
// or not you contribute, and staying quiet costs you the round. These constants
// are what make silence expensive.

/** Total length of the round. Campus GDs are typically 8-10 minutes. */
const GD_DURATION_SEC = 480;
/** How long the panel waits before speaking again on its own. */
const PANEL_INTERVAL_SEC = 18;
/** Seconds before the end when panelists start converging on a conclusion. */
const CLOSING_WINDOW_SEC = 90;
/**
 * How long you may hold the floor (mic live or a draft in progress) before the
 * panel talks over you anyway — as they would in a real room.
 */
const MAX_FLOOR_HOLD_SEC = 20;
/**
 * Hard cap on panel turns per round. The clock fires AI calls autonomously, so
 * without a ceiling one abandoned tab could generate turns until the timer ends.
 */
const MAX_PANEL_TURNS = 26;

const fmtClock = (s: number) =>
  `${Math.floor(Math.max(0, s) / 60)}:${String(Math.max(0, s) % 60).padStart(2, '0')}`;
// Deterministic accent per panelist name (avatar tint).
const PANEL_COLORS: Record<string, string> = {
  Riya: 'bg-accent-violet/15 text-accent-violet',
  Arjun: 'bg-primary/15 text-primary',
  Meera: 'bg-emerald-500/15 text-emerald-600',
};

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

export default function GDPage() {
  const { data: topics } = useGDTopics();
  const { panelTurn, evaluate } = useGD();
  const stt = useSpeechRecognition();

  const [phase, setPhase] = useState<Phase>('setup');
  const [topicIdx, setTopicIdx] = useState(0);
  const [customTopic, setCustomTopic] = useState('');
  const [history, setHistory] = useState<GDTurn[]>([]);
  const [draft, setDraft] = useState('');
  const [result, setResult] = useState<GDEvaluation | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // ─── Live discussion state ────────────────────────────────────────────────
  /** Seconds left in the round. */
  const [timeLeft, setTimeLeft] = useState(GD_DURATION_SEC);
  /** Seconds until the panel speaks again unprompted. */
  const [nextTurnIn, setNextTurnIn] = useState(PANEL_INTERVAL_SEC);
  /** The panel has asked you something and is waiting. */
  const [awaiting, setAwaiting] = useState(false);
  /** Direct questions you never answered. At 2 the panel writes you off. */
  const [ignored, setIgnored] = useState(0);
  const [silentFor, setSilentFor] = useState(0);
  const [panelTurns, setPanelTurns] = useState(0);

  // Refs mirror state the 1s tick reads, so the interval never needs to be torn
  // down and rebuilt on every keystroke (which would reset the countdown).
  const holdRef = useRef(0);
  const firingRef = useRef(false);
  const stateRef = useRef({ history, awaiting, ignored, silentFor, panelTurns, timeLeft });
  stateRef.current = { history, awaiting, ignored, silentFor, panelTurns, timeLeft };

  const topic = customTopic.trim() || topics?.[topicIdx]?.text || 'Is remote work better than working from the office?';

  const gdPhase: 'opening' | 'discussion' | 'closing' =
    history.length === 0 ? 'opening' : timeLeft <= CLOSING_WINDOW_SEC ? 'closing' : 'discussion';

  useEffect(() => {
    if (stt.transcript) setDraft(stt.transcript);
  }, [stt.transcript]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [history]);

  /** Ask the panel for its next contributions, carrying the current pressure state. */
  const firePanelTurn = useCallback(
    (overrides?: { history?: GDTurn[]; resetPressure?: boolean }) => {
      if (firingRef.current) return;

      const s = stateRef.current;
      const hist = overrides?.history ?? s.history;

      // If they were asked and still haven't spoken, that's one more unanswered
      // question — counted here, at the moment the panel gives up waiting.
      let nextIgnored = overrides?.resetPressure ? 0 : s.ignored;
      if (!overrides?.resetPressure && s.awaiting) {
        nextIgnored = s.ignored + 1;
        setIgnored(nextIgnored);
      }

      firingRef.current = true;
      setNextTurnIn(PANEL_INTERVAL_SEC);
      holdRef.current = 0;

      panelTurn.mutate(
        {
          topic,
          history: hist,
          awaiting_candidate: overrides?.resetPressure ? false : s.awaiting,
          ignored_questions: nextIgnored,
          candidate_silent_seconds: overrides?.resetPressure ? 0 : s.silentFor,
          phase: hist.length === 0 ? 'opening' : s.timeLeft <= CLOSING_WINDOW_SEC ? 'closing' : 'discussion',
        },
        {
          onSuccess: (data) => {
            if (data.contributions.length) {
              setHistory((h) => [...h, ...data.contributions]);
              setPanelTurns((n) => n + 1);
            }
            // Being addressed puts you on the spot; otherwise the panel is
            // talking amongst itself and the slate is clean again.
            setAwaiting(data.addressed_candidate);
            if (nextIgnored >= 2) setIgnored(0); // panel moved on — stop nagging
          },
          onError: (e: Error) => toast.error(e.message || 'Panel could not respond.'),
          onSettled: () => { firingRef.current = false; },
        }
      );
    },
    [panelTurn, topic]
  );

  // ─── The clock: this is what makes the GD feel real ───────────────────────
  // One 1s tick drives the round timer, the "panel speaks next" countdown, and
  // your silence counter. The panel advances on this clock whether or not you
  // say anything.
  useEffect(() => {
    if (phase !== 'discussion') return;

    const id = setInterval(() => {
      const s = stateRef.current;

      setTimeLeft((t) => Math.max(0, t - 1));
      setSilentFor((n) => n + 1);

      // You "hold the floor" while the mic is live or a draft is in progress —
      // but only for so long, then the panel talks over you.
      const holdingFloor = stt.listening || draft.trim().length > 0;
      if (holdingFloor && holdRef.current < MAX_FLOOR_HOLD_SEC) {
        holdRef.current += 1;
        return;
      }

      if (s.panelTurns >= MAX_PANEL_TURNS) return;

      setNextTurnIn((n) => {
        if (n <= 1) {
          firePanelTurn();
          return PANEL_INTERVAL_SEC;
        }
        return n - 1;
      });
    }, 1000);

    return () => clearInterval(id);
  }, [phase, stt.listening, draft, firePanelTurn]);

  // Guards against the time-up effect firing twice (and against ending a round
  // that's already being scored).
  const endingRef = useRef(false);

  const endDiscussion = useCallback(() => {
    if (endingRef.current) return;
    endingRef.current = true;
    evaluate.mutate(
      { topic, history: stateRef.current.history, ignored_questions: stateRef.current.ignored },
      {
        onSuccess: (data) => { setResult(data); setPhase('results'); },
        onError: (e: Error) => {
          endingRef.current = false;
          toast.error(e.message || 'Could not score the discussion.');
        },
      }
    );
  }, [evaluate, topic]);

  // Time's up — score it automatically, the way a real round gets called.
  useEffect(() => {
    if (phase === 'discussion' && timeLeft === 0) endDiscussion();
  }, [phase, timeLeft, endDiscussion]);

  const start = () => {
    setHistory([]);
    setResult(null);
    setTimeLeft(GD_DURATION_SEC);
    setNextTurnIn(PANEL_INTERVAL_SEC);
    setAwaiting(false);
    setIgnored(0);
    setSilentFor(0);
    setPanelTurns(0);
    holdRef.current = 0;
    firingRef.current = false;
    endingRef.current = false;
    setPhase('discussion');
    // Opening positions, so the room is already talking when you arrive.
    firePanelTurn({ history: [], resetPressure: true });
  };

  const toggleMic = () => {
    if (stt.listening) stt.stop();
    else { stt.reset(); setDraft(''); stt.start(); }
  };

  const submitPoint = () => {
    if (!draft.trim()) return;
    if (stt.listening) stt.stop();
    const next = [...history, { speaker: YOU, text: draft.trim() }];
    setHistory(next);
    setDraft('');
    stt.reset();
    // You answered: pressure clears and the panel reacts to you immediately.
    setAwaiting(false);
    setIgnored(0);
    setSilentFor(0);
    holdRef.current = 0;
    firePanelTurn({ history: next, resetPressure: true });
  };

  const myContributions = history.filter((t) => t.speaker === YOU).length;
  /** The most recent thing said to you — echoed in the "answer now" banner. */
  const lastPanelLine = [...history].reverse().find((t) => t.speaker !== YOU);

  // ─── Setup ──────────────────────────────────────────────────────────────
  if (phase === 'setup') {
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-2xl space-y-8">
        <motion.div variants={fadeUp}>
          <h1 className="text-2xl font-bold tracking-tight">Group Discussion</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Practice a GD with AI participants (Riya, Arjun, Meera). They make points; you jump in with yours by voice. At the end you get scored on contribution, relevance, clarity, and engagement.
          </p>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card className="space-y-5 p-8">
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">Pick a topic</label>
              <div className="space-y-2">
                {(topics ?? []).map((t, i) => (
                  <button
                    key={t.id}
                    onClick={() => { setTopicIdx(i); setCustomTopic(''); }}
                    className={cn(
                      'w-full rounded-xl border px-4 py-3 text-left text-sm transition-colors',
                      !customTopic && topicIdx === i ? 'border-primary bg-primary/10 text-foreground' : 'border-border hover:border-primary/40'
                    )}
                  >
                    {t.text}
                  </button>
                ))}
              </div>
            </div>
            <Button className="w-full" onClick={start} loading={panelTurn.isPending}>
              <Play className="h-4 w-4" /> Start Discussion
            </Button>
          </Card>
        </motion.div>
      </motion.div>
    );
  }

  // ─── Results ────────────────────────────────────────────────────────────
  if (phase === 'results' && result) {
    const tone = result.overall_score >= 7 ? 'text-emerald-600' : result.overall_score >= 4 ? 'text-amber-600' : 'text-red-600';
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.06)} className="mx-auto max-w-3xl space-y-6 pb-12">
        <motion.div variants={fadeUp}>
          <Card className="flex flex-col items-center gap-2 p-8 text-center">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Group Discussion Score</p>
            <p className={cn('text-5xl font-bold tracking-tight', tone)}>{result.overall_score.toFixed(1)}<span className="text-2xl text-muted-foreground">/10</span></p>
            <p className="text-xs text-muted-foreground">You made {myContributions} contribution{myContributions === 1 ? '' : 's'}</p>
            <Button className="mt-4" onClick={() => setPhase('setup')}><Users className="h-4 w-4" /> New discussion</Button>
          </Card>
        </motion.div>
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <ScoreBar label="Contribution" value={result.contribution_score} />
            <ScoreBar label="Relevance" value={result.relevance_score} />
            <ScoreBar label="Clarity" value={result.clarity_score} />
            <ScoreBar label="Engagement" value={result.engagement_score} />
          </Card>
        </motion.div>
        <motion.div variants={fadeUp}>
          <Card className="space-y-3 p-6">
            <p className="text-sm leading-relaxed text-foreground/85">{result.feedback}</p>
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

  // ─── Discussion ─────────────────────────────────────────────────────────
  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] max-w-3xl flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Topic</p>
          <h2 className="text-lg font-bold leading-snug">{topic}</h2>
        </div>
        <div className="shrink-0 text-right">
          <p
            className={cn(
              'font-mono text-2xl font-bold tabular-nums',
              timeLeft <= CLOSING_WINDOW_SEC ? 'text-amber-600' : 'text-foreground'
            )}
          >
            {fmtClock(timeLeft)}
          </p>
          <p className="text-[11px] font-medium text-muted-foreground">
            {gdPhase === 'closing' ? 'wrapping up' : `${myContributions} point${myContributions === 1 ? '' : 's'} made`}
          </p>
        </div>
      </div>

      {/* The panel advances on this bar whether or not you speak. */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-[11px] font-medium text-muted-foreground">
          <span>
            {panelTurn.isPending
              ? 'someone is jumping in…'
              : stt.listening || draft.trim()
                ? `you have the floor — ${Math.max(0, MAX_FLOOR_HOLD_SEC - holdRef.current)}s`
                : `panel speaks again in ${nextTurnIn}s`}
          </span>
          {ignored > 0 && (
            <span className="font-semibold text-red-600">
              {ignored} question{ignored === 1 ? '' : 's'} unanswered
            </span>
          )}
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className={cn(
              'h-full rounded-full transition-[width] duration-1000 ease-linear',
              awaiting ? 'bg-red-500' : 'bg-primary/60'
            )}
            style={{ width: `${(1 - nextTurnIn / PANEL_INTERVAL_SEC) * 100}%` }}
          />
        </div>
      </div>

      {/* You've been put on the spot — answer or get talked over. */}
      {awaiting && !panelTurn.isPending && (
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-red-600">
            They&apos;re asking you directly
          </p>
          {lastPanelLine && (
            <p className="mt-1 text-sm leading-snug text-foreground/85">
              <span className="font-semibold">{lastPanelLine.speaker}:</span> {lastPanelLine.text}
            </p>
          )}
          <p className="mt-1.5 text-[11px] text-red-600/80">
            Answer before the panel moves on — silence costs you marks.
          </p>
        </motion.div>
      )}

      <Card className="flex-1 overflow-hidden p-0">
        <div ref={scrollRef} className="h-full space-y-4 overflow-y-auto p-6">
          {history.map((t, i) => {
            const mine = t.speaker === YOU;
            return (
              <div key={i} className={cn('flex gap-3', mine && 'flex-row-reverse')}>
                <div className={cn('flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold',
                  mine ? 'bg-primary text-primary-foreground' : PANEL_COLORS[t.speaker] ?? 'bg-secondary text-muted-foreground')}>
                  {t.speaker[0]}
                </div>
                <div className={cn('max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
                  mine ? 'bg-primary/10 text-foreground' : 'bg-surface-elevated')}>
                  <p className="mb-0.5 text-[11px] font-semibold text-muted-foreground">{t.speaker}</p>
                  {t.text}
                </div>
              </div>
            );
          })}
          {panelTurn.isPending && (
            <div className="flex items-center gap-2 pl-11 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> panelists are responding…
            </div>
          )}
        </div>
      </Card>

      {/* Your input */}
      <Card className="p-4">
        {evaluate.isPending ? (
          <div className="flex justify-center py-2"><AIWorkingIndicator messages={['Scoring your participation…', 'Weighing contribution & engagement…']} /></div>
        ) : (
          <>
            <div className="min-h-[44px] rounded-lg border border-border/50 bg-surface-elevated p-2.5 text-sm">
              <DeliveryTranscript
                text={draft}
                pauses={stt.pauses}
                interim={stt.listening ? stt.interim : ''}
                emptyLabel="Tap the mic and speak your point…"
              />
            </div>
            <div className="mt-2.5 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {stt.supported && (
                  <Button variant={stt.listening ? 'destructive' : 'secondary'} size="sm" onClick={toggleMic} disabled={panelTurn.isPending}>
                    {stt.listening ? <><MicOff className="h-4 w-4" /> Stop</> : <><Mic className="h-4 w-4" /> Speak</>}
                  </Button>
                )}
                <Button size="sm" onClick={submitPoint} disabled={!draft.trim() || panelTurn.isPending}>
                  <Send className="h-4 w-4" /> Add point
                </Button>
              </div>
              <Button variant="ghost" size="sm" onClick={endDiscussion} disabled={myContributions === 0}>
                <CheckCircle2 className="h-4 w-4" /> End & get feedback
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
