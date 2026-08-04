'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Mic, MicOff, Send, Users, Play, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { useCandidateName } from '@/hooks/useCandidateName';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import { useSpeechRecognition, usePanelVoices } from '@/hooks/useSpeech';
import {
  useGD,
  useGDPanel,
  useGDTopics,
  type GDEvaluation,
  type GDPanelist,
  type GDPreparedTopic,
  type GDTopic as GDTopicRow,
  type GDTurn,
} from '@/hooks/useGD';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { PageHeader } from '@/components/ui/page-header';

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
/** Longest the countdown will wait on a panelist before assuming the engine hung. */
const MAX_FLOOR_WAIT_SEC = 45;

const fmtClock = (s: number) =>
  `${Math.floor(Math.max(0, s) / 60)}:${String(Math.max(0, s) % 60).padStart(2, '0')}`;
// Deterministic accent per panelist name (avatar tint).
/**
 * One tone per panelist, assigned by their position in the panel the SERVER sent.
 *
 * Position rather than name: the roster lives in api/v1/gd.py, and a name map here
 * would quietly grey out every panelist the day someone is renamed or a fourth is
 * added. Order is stable within a discussion, which is all consistency requires.
 */
const PANEL_TONES = [
  'bg-accent-violet/15 text-accent-violet',
  'bg-primary/15 text-primary',
  'bg-accent-emerald/15 text-accent-emerald-ink',
  'bg-accent-amber/15 text-accent-amber-ink',
  'bg-accent-teal/15 text-accent-teal-ink',
];

function panelTone(speaker: string, panel: GDPanelist[]): string {
  const i = panel.findIndex((p) => p.name === speaker);
  return i >= 0 ? PANEL_TONES[i % PANEL_TONES.length] : 'bg-secondary text-muted-foreground';
}

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

/**
 * Who is talking and who is listening — the strip above the transcript.
 *
 * A real GD is largely read off faces: you know who has the floor, and when you
 * speak you can see who is actually paying attention to you and who is waiting to
 * cut in. None of that survives into a chat log, so it is stated explicitly here.
 *
 * `listeningTo` is not decoration. When the candidate takes the floor, one
 * panelist is waiting on them specifically — the one who asked the question — and
 * knowing that changes who you answer. The user asked for exactly this: "it must
 * tell that which person is listning to the user when the user speaks".
 */
function PanelStrip({
  panel,
  speakingNow,
  takingFloor,
  candidateSpeaking,
  listeningTo,
}: {
  panel: GDPanelist[];
  speakingNow: string | null;
  /** Has the floor but has not started yet — the handover beat. */
  takingFloor: string | null;
  candidateSpeaking: boolean;
  listeningTo: string | null;
}) {
  if (!panel.length) return null;
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {panel.map((pl) => {
        const speaking = speakingNow === pl.name;
        // Deliberately NOT folded into `speaking`: claiming a voice is audible
        // during the handover silence is a worse lie than showing nothing.
        const opening = !speaking && takingFloor === pl.name;
        const waitingOnYou = candidateSpeaking && listeningTo === pl.name;
        return (
          <div
            key={pl.name}
            className={cn(
              'flex items-center gap-2.5 rounded-xl border px-3 py-2 transition-colors duration-300',
              speaking
                ? 'border-primary/60 bg-primary/10'
                : opening
                  ? 'border-primary/35 bg-primary/5'
                  : waitingOnYou
                    ? 'border-accent-emerald/50 bg-accent-emerald/10'
                    : 'border-border/60 bg-surface-elevated'
            )}
          >
            <span
              className={cn(
                'relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
                panelTone(pl.name, panel),
                !speaking && !opening && !waitingOnYou && candidateSpeaking && 'opacity-60'
              )}
            >
              {pl.name[0]}
              {/* No pulse ring during the beat — the ring means audio. */}
              {speaking && (
                <motion.span
                  aria-hidden
                  className="absolute inset-0 rounded-full ring-2 ring-primary"
                  animate={{ opacity: [0.35, 1, 0.35], scale: [1, 1.12, 1] }}
                  transition={{ duration: 1.1, repeat: Infinity, ease: 'easeInOut' }}
                />
              )}
            </span>
            <div className="min-w-0">
              <p className="truncate text-xs font-semibold leading-tight">{pl.name}</p>
              <p
                className={cn(
                  'truncate text-[10px] font-medium leading-tight',
                  speaking || opening
                    ? 'text-primary'
                    : waitingOnYou
                      ? 'text-accent-emerald-ink'
                      : 'text-muted-foreground'
                )}
              >
                {speaking ? (
                  <span className="inline-flex items-center gap-1">
                    <SoundBars /> speaking
                  </span>
                ) : opening ? (
                  'about to speak'
                ) : waitingOnYou ? (
                  'listening to you'
                ) : candidateSpeaking ? (
                  'following along'
                ) : (
                  pl.role
                )}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Three bars that move while someone holds the floor. Purely an indicator. */
function SoundBars() {
  return (
    <span aria-hidden className="flex h-2.5 items-end gap-[2px]">
      {[0, 0.15, 0.3].map((delay) => (
        <motion.span
          key={delay}
          className="w-[2px] rounded-full bg-primary"
          animate={{ height: ['30%', '100%', '30%'] }}
          transition={{ duration: 0.7, repeat: Infinity, delay, ease: 'easeInOut' }}
        />
      ))}
    </span>
  );
}

export default function GDPage() {
  const { data: topics } = useGDTopics();
  const { data: panel } = useGDPanel();

  /**
   * The candidate's own first name, so the panel can say it.
   *
   * Resolved automatically per user — profile name, then signup metadata, then the
   * email local part — by the one hook that owns that precedence.
   */
  const { first: candidateName } = useCandidateName();

  /**
   * One voice per panelist, gender-matched, played one at a time.
   * `speakingNow` is who currently holds the floor — and, by being null while the
   * candidate's mic is live, it is how the UI shows the panel is listening.
   */
  const panelVoices = usePanelVoices(
    useMemo(
      () => (panel ?? []).map((p) => ({ name: p.name, gender: p.gender, stance: p.stance })),
      [panel],
    ),
  );
  const { panelTurn, evaluate, prepareTopic } = useGD();
  const stt = useSpeechRecognition();

  const [phase, setPhase] = useState<Phase>('setup');
  const [topicIdx, setTopicIdx] = useState(0);
  const [customTopic, setCustomTopic] = useState('');
  //: The AI-prepared version of a custom topic — a discussable motion plus the
  //: arguments for each side, which the candidate reads before the round starts.
  const [prepared, setPrepared] = useState<GDPreparedTopic | null>(null);
  //: 'bank' = a predefined topic, 'own' = the candidate typed one.
  const [topicMode, setTopicMode] = useState<'bank' | 'own'>('bank');
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
  /**
   * Is a panelist mid-contribution? The countdown must not run while they are.
   *
   * A turn is one or two contributions of one to three sentences — 50-70 spoken
   * words, which is 19-26s of audio at the rate these engines run.
   * PANEL_INTERVAL_SEC is 18, so the countdown was expiring mid-sentence and the
   * next turn was being queued onto a chain that had not drained: the panel became
   * one unbroken wall of voice, and the "panel speaks again in Ns" label was
   * counting down against speech the candidate could still hear. With handover
   * beats and clause pauses added, that overrun only grows. Gated here instead, so
   * the interval now means "18s of silence after the panel stops" — which is what
   * the label always claimed.
   */
  const panelHasFloorRef = useRef(false);
  //: Bounded, so an engine that never fires `onend` (Android Chrome does this when
  //: a tab backgrounds) cannot leave speakingNow stuck and silently kill the round.
  const floorWaitRef = useRef(0);
  const stateRef = useRef({ history, awaiting, ignored, silentFor, panelTurns, timeLeft });
  stateRef.current = { history, awaiting, ignored, silentFor, panelTurns, timeLeft };
  panelHasFloorRef.current = !!(panelVoices.speakingNow || panelVoices.takingFloor);

  /**
   * Topics grouped by category, preserving each topic's index in the flat list.
   *
   * The index is what `topicIdx` refers to, so it has to travel with the topic —
   * grouping and then using the position within a group would select the wrong
   * topic for every category after the first.
   */
  const topicsByCategory = useMemo(() => {
    const groups = new Map<string, Array<{ topic: GDTopicRow; index: number }>>();
    (topics ?? []).forEach((t, index) => {
      const key = t.category || 'General';
      const list = groups.get(key) ?? [];
      list.push({ topic: t, index });
      groups.set(key, list);
    });
    return [...groups.entries()];
  }, [topics]);

  const prepare = useCallback(async () => {
    const raw = customTopic.trim();
    if (raw.length < 3) return;
    try {
      const res = await prepareTopic.mutateAsync(raw);
      if (!res.usable) {
        // The server judged it undiscussable — a factual question, or something
        // with only one defensible side. Say why instead of running a round the
        // panel cannot argue.
        toast.error(res.reason || 'That topic will not work for a group discussion.');
        setPrepared(null);
        return;
      }
      setPrepared(res);
    } catch {
      toast.error('Could not prepare that topic. Try rephrasing it.');
    }
  }, [customTopic, prepareTopic]);

  // A prepared motion beats the raw phrase: "AI in education" has no sides, so a
  // panel given it lists facts instead of arguing. See POST /gd/prepare.
  const topic =
    (topicMode === 'own' ? prepared?.statement || customTopic.trim() : '') ||
    topics?.[topicIdx]?.text ||
    'Is remote work better than working from the office?';

  const gdPhase: 'opening' | 'discussion' | 'closing' =
    history.length === 0 ? 'opening' : timeLeft <= CLOSING_WINDOW_SEC ? 'closing' : 'discussion';

  useEffect(() => {
    if (stt.transcript) setDraft(stt.transcript);
  }, [stt.transcript]);

  /**
   * When the candidate takes the floor, the panel stops talking.
   *
   * Without this the panel's queued turns keep playing over the candidate's own
   * voice, which is both unusable (their mic picks up the synthesised speech and
   * transcribes it into their answer) and the opposite of what taking the floor
   * means. A real panel stops when someone cuts in.
   */
  useEffect(() => {
    if (stt.listening) panelVoices.cancelAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stt.listening]);

  // Leaving the round must not leave a voice talking to an empty screen.
  useEffect(() => () => panelVoices.cancelAll(), []); // eslint-disable-line react-hooks/exhaustive-deps

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
          candidate_name: candidateName,
        },
        {
          onSuccess: (data) => {
            if (data.contributions.length) {
              setPanelTurns((n) => n + 1);
              /*
               * Reveal each contribution AS ITS VOICE STARTS, not all on arrival.
               *
               * A turn returns one or two contributions together. Pushing both into the
               * transcript immediately and then speaking them in sequence meant the
               * candidate read the second person's line while the first was still talking —
               * the text ran seconds ahead of the room, which is the opposite of being in
               * one. Now each line appears when its speaker takes the floor.
               *
               * A contribution cancelled before it starts is never revealed, deliberately:
               * the candidate cut in, so it was never said. That is what makes interrupting
               * mean something, and it keeps the transcript honest about what was actually
               * heard — which matters because the transcript is what gets evaluated.
               */
              void (async () => {
                for (const c of data.contributions) {
                  await panelVoices.speakAs(c.speaker, c.text, {
                    onStart: () => setHistory((h) => [...h, c]),
                  });
                }
              })();
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
    [panelTurn, topic, panelVoices, candidateName]
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

      // A panelist is talking. Do not count down toward interrupting them.
      if (panelHasFloorRef.current && floorWaitRef.current < MAX_FLOOR_WAIT_SEC) {
        floorWaitRef.current += 1;
        return;
      }
      if (!panelHasFloorRef.current) floorWaitRef.current = 0;

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
    floorWaitRef.current = 0;
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
    // The candidate has the floor — whether they spoke it or typed it. This stops
    // anything still queued AND marks the floor as theirs, so the next panelist
    // pays a handover beat instead of continuing their own sentence. Only the mic
    // path called this before, so typed points — the fallback on every device
    // without SpeechRecognition — got no beat at all.
    panelVoices.cancelAll();
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

  /**
   * Which panelist is waiting on the candidate.
   *
   * Whoever spoke last is holding the thread, so they are the one your answer is
   * aimed at — and if the panel put a direct question to you, that is the same
   * person. Null before anyone has spoken.
   */
  const listeningTo = lastPanelLine?.speaker ?? null;

  //: The newest line by whoever currently holds the floor — the one being read.
  const lastSpokenIdx = panelVoices.speakingNow
    ? history.reduce((acc, t, i) => (t.speaker === panelVoices.speakingNow ? i : acc), -1)
    : -1;

  // ─── Setup ──────────────────────────────────────────────────────────────
  if (phase === 'setup') {
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-2xl space-y-8">
        <motion.div variants={fadeUp}>
          <PageHeader
            eyebrow="Practice"
            title="Group Discussion"
            description="Eight minutes, three AI panelists with their own opinions and their own voices. They argue with each other and with you, and they will put you on the spot by name. Score covers contribution, relevance, clarity and engagement."
          />
        </motion.div>

        {/* Who you are up against. Shown before the round so the voices are not
            three anonymous strangers when they start talking. */}
        {!!panel?.length && (
          <motion.div variants={fadeUp}>
            <Card className="p-5">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Your panel</p>
              <div className="grid gap-3 sm:grid-cols-3">
                {panel.map((pl) => (
                  <div key={pl.name} className="rounded-xl border border-border/60 bg-surface-elevated p-3">
                    <div className="flex items-center gap-2">
                      <span className={cn('flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold',
                        panelTone(pl.name, panel))}>
                        {pl.name[0]}
                      </span>
                      <span className="text-sm font-semibold">{pl.name}</span>
                    </div>
                    <p className="mt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">{pl.role}</p>
                    <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">{pl.stance}</p>
                  </div>
                ))}
              </div>
            </Card>
          </motion.div>
        )}

        <motion.div variants={fadeUp}>
          <Card className="space-y-5 p-8">
            {/* Two ways in: a topic off the shelf, or one of your own that the AI
                turns into something actually arguable. */}
            <div className="flex gap-1 rounded-xl bg-secondary p-1">
              {(['bank', 'own'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setTopicMode(m)}
                  className={cn(
                    'flex-1 rounded-lg px-3 py-2 text-xs font-semibold transition-colors',
                    topicMode === m ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {m === 'bank' ? 'Pick a topic' : 'Use my own topic'}
                </button>
              ))}
            </div>

            {topicMode === 'bank' ? (
              <div className="max-h-[22rem] space-y-4 overflow-y-auto pr-1">
                {topicsByCategory.map(([category, items]) => (
                  <div key={category}>
                    <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{category}</p>
                    <div className="space-y-1.5">
                      {items.map(({ topic: t, index }) => (
                        <button
                          key={t.id}
                          onClick={() => setTopicIdx(index)}
                          className={cn(
                            'w-full rounded-xl border px-4 py-2.5 text-left text-sm transition-colors',
                            topicIdx === index
                              ? 'border-primary bg-primary/10 text-foreground'
                              : 'border-border hover:border-primary/40'
                          )}
                        >
                          {t.text}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label htmlFor="gd-own-topic" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    What do you want to discuss?
                  </label>
                  <textarea
                    id="gd-own-topic"
                    value={customTopic}
                    onChange={(e) => { setCustomTopic(e.target.value); setPrepared(null); }}
                    rows={2}
                    placeholder="e.g. AI in education, or work from home for freshers"
                    className="w-full resize-none rounded-xl border border-border bg-surface-elevated px-4 py-3 text-sm outline-none transition-colors focus:border-primary/60"
                  />
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    A phrase is enough. It gets turned into a proper motion with both sides prepared.
                  </p>
                </div>

                <Button
                  variant="secondary"
                  className="w-full"
                  onClick={prepare}
                  loading={prepareTopic.isPending}
                  disabled={customTopic.trim().length < 3}
                >
                  Prepare this topic
                </Button>

                {/* The briefing. A real GD gives you a minute with the slip before
                    it starts — this is that minute. */}
                {prepared && (
                  <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="space-y-3 rounded-xl border border-border/60 bg-surface-elevated p-4">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">The motion</p>
                      <p className="mt-0.5 text-sm font-semibold leading-snug">{prepared.statement}</p>
                    </div>
                    <p className="text-xs leading-relaxed text-foreground/75">{prepared.framing}</p>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-accent-emerald-ink">For</p>
                        <ul className="space-y-1 text-xs leading-snug text-foreground/80">
                          {prepared.points_for.map((pt, i) => (
                            <li key={i} className="flex gap-1.5"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent-emerald" />{pt}</li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-accent-coral-ink">Against</p>
                        <ul className="space-y-1 text-xs leading-snug text-foreground/80">
                          {prepared.points_against.map((pt, i) => (
                            <li key={i} className="flex gap-1.5"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent-coral" />{pt}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      You do not have to take a side yet — the panel will push you into one.
                    </p>
                  </motion.div>
                )}
              </div>
            )}

            <Button
              className="w-full"
              onClick={start}
              loading={panelTurn.isPending}
              disabled={topicMode === 'own' && !prepared}
            >
              <Play className="h-4 w-4" /> Start Discussion
            </Button>
            {topicMode === 'own' && !prepared && (
              <p className="-mt-3 text-center text-[11px] text-muted-foreground">
                Prepare your topic first so the panel has something to argue about.
              </p>
            )}
          </Card>
        </motion.div>
      </motion.div>
    );
  }

  // ─── Results ────────────────────────────────────────────────────────────
  if (phase === 'results' && result) {
    const tone = result.overall_score >= 7 ? 'text-accent-emerald-ink' : result.overall_score >= 4 ? 'text-accent-amber-ink' : 'text-accent-coral-ink';
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

  // ─── Discussion ─────────────────────────────────────────────────────────
  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] max-w-3xl flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Topic</p>
          <h2 className="text-lg font-semibold leading-snug">{topic}</h2>
        </div>
        <div className="shrink-0 text-right">
          <p
            className={cn(
              'font-mono text-2xl font-bold tabular-nums',
              timeLeft <= CLOSING_WINDOW_SEC ? 'text-accent-amber-ink' : 'text-foreground'
            )}
          >
            {fmtClock(timeLeft)}
          </p>
          <p className="text-[11px] font-medium text-muted-foreground">
            {gdPhase === 'closing' ? 'wrapping up' : `${myContributions} point${myContributions === 1 ? '' : 's'} made`}
          </p>
        </div>
      </div>

      {/* Which voices the candidate is actually hearing. Without this, someone on browser
          speech assumes flat system voices are simply how the product sounds. */}
      {!panelVoices.neuralProvider && (
        <p className="-mb-1 text-[10px] text-muted-foreground/70">
          Standby voices — your browser&apos;s built-in speech
        </p>
      )}

      <PanelStrip
        panel={panel ?? []}
        speakingNow={panelVoices.speakingNow}
        takingFloor={panelVoices.takingFloor}
        candidateSpeaking={stt.listening}
        listeningTo={listeningTo}
      />

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
            <span className="font-semibold text-accent-coral-ink">
              {ignored} question{ignored === 1 ? '' : 's'} unanswered
            </span>
          )}
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className={cn(
              'h-full rounded-full transition-[width] duration-1000 ease-linear',
              awaiting ? 'bg-accent-coral' : 'bg-primary/60'
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
          className="rounded-xl border border-accent-coral/30 bg-accent-coral/10 px-4 py-3"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-accent-coral-ink">
            They&apos;re asking you directly
          </p>
          {lastPanelLine && (
            <p className="mt-1 text-sm leading-snug text-foreground/85">
              <span className="font-semibold">{lastPanelLine.speaker}:</span> {lastPanelLine.text}
            </p>
          )}
          <p className="mt-1.5 text-[11px] text-accent-coral-ink/80">
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
                  mine ? 'bg-primary text-primary-foreground' : panelTone(t.speaker, panel ?? []))}>
                  {t.speaker[0]}
                </div>
                <div className={cn('max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed transition-shadow',
                  mine ? 'bg-primary/10 text-foreground' : 'bg-surface-elevated',
                  // Ring the line currently being read aloud, so the text and the
                  // voice are visibly the same contribution.
                  !mine && panelVoices.speakingNow === t.speaker && i === lastSpokenIdx && 'ring-1 ring-primary/40')}>
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
