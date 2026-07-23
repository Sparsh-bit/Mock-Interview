'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Mic, MicOff, Send, Users, Play, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { useSpeechRecognition } from '@/hooks/useSpeech';
import { useGD, useGDTopics, type GDTurn, type GDEvaluation } from '@/hooks/useGD';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

type Phase = 'setup' | 'discussion' | 'results';

const YOU = 'You';
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

  const topic = customTopic.trim() || topics?.[topicIdx]?.text || 'Is remote work better than working from the office?';

  useEffect(() => {
    if (stt.transcript) setDraft(stt.transcript);
  }, [stt.transcript]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [history]);

  const start = () => {
    setHistory([]);
    setResult(null);
    setPhase('discussion');
    // Kick off with opening panelist statements.
    panelTurn.mutate(
      { topic, history: [] },
      {
        onSuccess: (data) => setHistory(data.contributions),
        onError: (e: Error) => toast.error(e.message || 'Could not start the discussion.'),
      }
    );
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
    // Panelists respond to the candidate's point.
    panelTurn.mutate(
      { topic, history: next },
      {
        onSuccess: (data) => data.contributions.length && setHistory((h) => [...h, ...data.contributions]),
        onError: (e: Error) => toast.error(e.message || 'Panel could not respond.'),
      }
    );
  };

  const endDiscussion = () => {
    evaluate.mutate(
      { topic, history },
      {
        onSuccess: (data) => { setResult(data); setPhase('results'); },
        onError: (e: Error) => toast.error(e.message || 'Could not score the discussion.'),
      }
    );
  };

  const myContributions = history.filter((t) => t.speaker === YOU).length;

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
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Topic</p>
        <h2 className="text-lg font-bold leading-snug">{topic}</h2>
      </div>

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
              {draft || stt.interim ? (
                <span>{draft} <span className="text-muted-foreground/60">{stt.listening ? stt.interim : ''}</span></span>
              ) : (
                <span className="text-muted-foreground/50">Tap the mic and speak your point…</span>
              )}
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
