'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  ChevronLeft,
  ChevronRight,
  Code2,
  Lightbulb,
  Loader2,
  MessageSquare,
  Sparkles,
  Target,
} from 'lucide-react';
import { toast } from 'sonner';
import { BrandLoader } from '@/components/brand/BrandLoader';
import { DataError } from '@/components/ui/data-error';
import { buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import {
  useDetailedAnalysis,
  useGenerateModelAnswer,
  type AnalysedAnswer,
} from '@/hooks/useData';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';


/** Coding answers arrive as a fenced block, since that is how they were submitted. */
function parseCodeSubmission(answer: string): { language: string; code: string } | null {
  const match = answer.match(/^```(\w+)?\n([\s\S]*?)```$/);
  if (!match) return null;
  return { language: match[1] || 'text', code: match[2].trimEnd() };
}

function AnswerCard({ item, index, sessionId }: { item: AnalysedAnswer; index: number; sessionId: string }) {
  const router = useRouter();
  const generate = useGenerateModelAnswer(sessionId);
  const [open, setOpen] = useState(false);

  const code = item.is_coding ? parseCodeSubmission(item.answer) : null;
  const coaching = item.model_answer;
  const pending = generate.isPending && generate.variables === item.answer_id;

  const reveal = () => {
    setOpen(true);
    if (coaching) return; // Already generated — cached, costs nothing.
    generate.mutate(item.answer_id, {
      onError: (err: unknown) => {
        const message = (err as { message?: string })?.message?.trim();
        toast.error(message || 'Could not build the ideal answer just now.');
        setOpen(false);
      },
    });
  };

  const spoke = item.delivery && item.delivery.words > 0;

  return (
    <motion.div variants={fadeUp}>
      <Card className="overflow-hidden p-0">
        {/* ── The question ───────────────────────────────────────────────── */}
        <div className="border-b border-border/50 bg-secondary/30 p-5">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-xs font-bold text-muted-foreground">Q{index + 1}</span>
            <Badge variant="neutral">{item.topic}</Badge>
            {item.is_coding && <Badge variant="violet">Coding</Badge>}
          </div>
          <p className="text-sm font-semibold leading-relaxed">{item.question}</p>
        </div>

        <div className="space-y-5 p-5">
          {/* ── What they actually said ──────────────────────────────────── */}
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              <MessageSquare className="h-3 w-3" /> What you said
            </p>

            {code ? (
              <pre className="overflow-x-auto rounded-xl border border-border/50 bg-secondary/40 p-4 text-xs leading-relaxed">
                <code>{code.code}</code>
              </pre>
            ) : item.answer.trim() ? (
              /* Rendered through DeliveryTranscript so filler words are marked in
                 red and each pause appears inline at the exact word it happened —
                 the same component the live interview uses, so the candidate sees
                 their delivery presented identically to how they saw it live.

                 The box lives on this wrapper, NOT on the component: it renders an
                 inline <span>, and a border/padding/background on an inline element
                 that wraps is painted once PER LINE FRAGMENT — which drew border
                 edges straight through the middle of the text and left the last
                 line hanging outside the box. Only inline-safe type styles may be
                 passed down. */
              <div className="overflow-hidden break-words rounded-xl border border-border/50 bg-surface/50 p-4">
                <DeliveryTranscript
                  text={item.answer}
                  pauses={item.delivery?.pauses ?? []}
                  className="text-sm leading-relaxed"
                />
              </div>
            ) : (
              <p className="rounded-xl border border-border/50 bg-surface/50 p-4 text-sm italic text-muted-foreground">
                You didn&apos;t answer this one.
              </p>
            )}

            {spoke && item.delivery && (
              <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                {item.delivery.pause_count > 0 && (
                  <span className="rounded-full border border-border px-2 py-0.5 text-muted-foreground">
                    {item.delivery.pause_count} pause{item.delivery.pause_count === 1 ? '' : 's'}
                    {item.delivery.total_pause_seconds ? ` · ${item.delivery.total_pause_seconds}s` : ''}
                  </span>
                )}
                {item.delivery.filler_count > 0 && (
                  <span className="rounded-full border border-border px-2 py-0.5 text-muted-foreground">
                    {item.delivery.filler_count} filler word{item.delivery.filler_count === 1 ? '' : 's'}
                  </span>
                )}
                <span className="rounded-full border border-border px-2 py-0.5 text-muted-foreground">
                  {item.delivery.words} words
                </span>
              </div>
            )}
          </div>

          {/* ── The answer they should have given ────────────────────────── */}
          {!open && !coaching ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={reveal}>
                <Sparkles className="h-3.5 w-3.5" />
                Show the ideal answer
              </Button>
              {item.is_coding && (
                <Button variant="ghost" onClick={() => router.push(`/practice/${item.question_id}?from=/report/${sessionId}/analysis`)}>
                  <Code2 className="h-3.5 w-3.5" />
                  Retry this question
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ) : pending ? (
            <div className="flex items-center gap-2 rounded-xl border border-border/50 bg-surface/50 p-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              Writing the answer you should have given&hellip;
            </div>
          ) : coaching ? (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
              {coaching.verdict_line && (
                <p className="border-l-2 border-primary/40 pl-3 text-sm italic text-muted-foreground">
                  {coaching.verdict_line}
                </p>
              )}

              <div className="rounded-xl border border-accent-emerald/20 bg-accent-emerald/[0.06] p-4">
                <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-accent-emerald-ink">
                  <Lightbulb className="h-3 w-3" /> How to answer this in the real interview
                </p>
                {/* whitespace-pre-line: the model writes spoken prose, and any
                    paragraph breaks it chooses are meaningful. */}
                <p className="whitespace-pre-line text-sm leading-relaxed">{coaching.model_answer}</p>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                {coaching.what_was_missing.length > 0 && (
                  <div>
                    <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-accent-amber-ink">
                      What yours was missing
                    </p>
                    <ul className="space-y-1.5">
                      {coaching.what_was_missing.map((gap, i) => (
                        <li key={i} className="flex gap-2 text-xs text-foreground/85">
                          <span className="mt-0.5 text-accent-amber-ink">•</span>
                          {gap}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {coaching.key_points.length > 0 && (
                  <div>
                    <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      <Target className="h-3 w-3" /> Any good answer must hit
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {coaching.key_points.map((point) => (
                        <span
                          key={point}
                          className="rounded-full border border-border bg-secondary/50 px-2.5 py-0.5 text-xs text-muted-foreground"
                        >
                          {point}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {item.is_coding && (
                <Button variant="secondary" onClick={() => router.push(`/practice/${item.question_id}?from=/report/${sessionId}/analysis`)}>
                  <Code2 className="h-3.5 w-3.5" />
                  Retry this question with optimised code
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              )}
            </motion.div>
          ) : null}
        </div>
      </Card>
    </motion.div>
  );
}

export default function DetailedAnalysisPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const router = useRouter();
  const { data, isLoading, error, refetch, isFetching } = useDetailedAnalysis(sessionId);

  if (isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <BrandLoader label="Loading your analysis" size={56} />
      </div>
    );
  }

  if (error || !data) {
    /*
     * DataError, not a hand-rolled centred card. This had no RETRY — the only way out of a
     * transient network failure was back to the report, and this page is where the candidate's
     * own words live, which is the part of the product they are most likely to reload.
     */
    return (
      <DataError
        title="Could not load your analysis"
        error={error}
        onRetry={() => refetch()}
        retrying={isFetching}
      />
    );
  }

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.06)}
      className="mx-auto max-w-4xl space-y-6 pb-16"
    >
      <motion.div variants={fadeUp}>
        <button
          onClick={() => router.push(`/report/${sessionId}`)}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Back to Report
        </button>
      </motion.div>

      <motion.div variants={fadeUp}>
        {/* The same coloured rule PageHeader draws before every eyebrow in the app — teal,
            because this page is measurement (ROUTE_TONE gives /report teal). This screen sets
            its own title rather than using PageHeader because it is a sub-view of a report
            rather than a destination, but there is no reason for it to opt out of the
            wayfinding. */}
        <p className="mb-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-accent-teal-ink">
          <span aria-hidden className="h-px w-3.5 shrink-0 bg-accent-teal" />
          Detailed analysis
        </p>
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">Answer-by-Answer Analysis</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {data.company_name ? `${data.company_name} · ` : ''}
          {data.track_name} · {data.answers.length} question
          {data.answers.length === 1 ? '' : 's'}. Your exact words, with the pauses and filler words
          marked — and, for any question, the answer you should have given.
        </p>
      </motion.div>

      {data.answers.length === 0 ? (
        <motion.div variants={fadeUp}>
          {/* An empty state that says what happened AND what to do. "No answers were
              recorded" with nothing to press is a dead end on a page somebody navigated to
              from their own report. */}
          <Card variant="flat" className="flex flex-wrap items-center justify-between gap-4 p-6">
            <div className="min-w-0">
              <p className="text-sm font-semibold">No answers were recorded for this round</p>
              <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
                This happens when a session was closed before the first answer was submitted.
                The round itself is still on your report.
              </p>
            </div>
            <button
              onClick={() => router.push(`/report/${sessionId}`)}
              className={cn(buttonVariants({ variant: 'secondary', size: 'md' }), 'shrink-0')}
            >
              Back to the report
            </button>
          </Card>
        </motion.div>
      ) : (
        data.answers.map((item, index) => (
          <AnswerCard key={item.answer_id} item={item} index={index} sessionId={sessionId} />
        ))
      )}
    </motion.div>
  );
}
