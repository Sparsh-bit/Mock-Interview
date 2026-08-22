'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useUserSessions } from '@/hooks/useData';
import { useActivity, type ActivityType, type ActivityItem } from '@/hooks/useActivity';
import { DataError } from '@/components/ui/data-error';
import { PageHeader } from '@/components/ui/page-header';
import {
  FileText,
  Loader2,
  Play,
  Calendar,
  MessageSquare,
  Mic,
  ListChecks,
  GraduationCap,
  ChevronDown,
} from 'lucide-react';

export const runtime = 'edge';

const ACTIVITY_META: Record<
  ActivityType,
  { label: string; icon: typeof FileText; tint: string }
> = {
  interview: { label: 'Interview', icon: GraduationCap, tint: 'text-primary bg-primary/10' },
  group_discussion: { label: 'Group Discussion', icon: MessageSquare, tint: 'text-accent-plum-ink bg-accent-plum/10' },
  communication: { label: 'Communication', icon: Mic, tint: 'text-accent-emerald-ink bg-accent-emerald/10' },
  quiz: { label: 'Quiz', icon: ListChecks, tint: 'text-accent-amber-ink bg-accent-amber/10' },
};

const SCORE_LABELS: Record<string, string> = {
  clarity_score: 'Clarity',
  structure_score: 'Structure',
  confidence_score: 'Confidence',
  conciseness_score: 'Conciseness',
  contribution_score: 'Contribution',
  relevance_score: 'Relevance',
  engagement_score: 'Engagement',
  overall_score: 'Overall',
};

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

/**
 * One expandable activity row — a per-section report. Clicking it reveals the
 * scores and feedback stored for that GD / communication / quiz, and links out
 * to the full interview report where applicable.
 */
function ActivityRow({ a }: { a: ActivityItem }) {
  const [open, setOpen] = useState(false);
  const meta = ACTIVITY_META[a.activity_type] ?? ACTIVITY_META.interview;
  const Icon = meta.icon;
  const d = (a.details ?? {}) as Record<string, unknown>;
  const sessionId = typeof d.session_id === 'string' ? d.session_id : null;

  const scoreChips = Object.entries(SCORE_LABELS)
    .filter(([k]) => typeof d[k] === 'number')
    .map(([k, label]) => ({ label, value: d[k] as number }));
  const feedback = typeof d.feedback === 'string' ? d.feedback : '';
  const strengths = asStringArray(d.strengths);
  const improvements = asStringArray(d.improvements);

  const metricChips: string[] = [];
  if (typeof d.words_per_minute === 'number') metricChips.push(`${d.words_per_minute} wpm`);
  if (typeof d.filler_count === 'number') metricChips.push(`${d.filler_count} fillers`);
  if (typeof d.pause_count === 'number') metricChips.push(`${d.pause_count} pauses`);
  if (typeof d.percentage === 'number') metricChips.push(`${d.percentage}%`);
  if (typeof d.total === 'number' && typeof d.score === 'number') metricChips.push(`${d.score}/${d.total} correct`);
  const quizTopics = asStringArray(d.topics);

  const hasDetail =
    a.activity_type !== 'interview' &&
    (scoreChips.length > 0 || feedback || strengths.length || improvements.length || metricChips.length || quizTopics.length);

  return (
    <div className="rounded-xl border border-border bg-surface-elevated shadow-elev-1">
      {/*
        WRAPS BELOW sm, because four fixed things do not fit in 256px.

        The row is: a 40px tile, the title block, the score, and either a "View" link or a
        chevron. On a 320px phone that leaves about 36px for the title block — and the
        meta line inside it (the activity type plus a full date-and-time) has a min-content
        width of roughly 110px, so it OVERFLOWED the block it lives in and drew straight
        over the score beside it. `min-w-0` alone cannot fix that: it lets the block shrink,
        which is precisely what puts its contents on top of the neighbour.

        So the score and the action move to their own line below sm (`basis` on the title
        block forces the break), and stay inline from sm up where there is room.
      */}
      <button
        onClick={() => hasDetail && setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-3 p-4 text-left"
      >
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${meta.tint}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1 basis-[calc(100%-3.5rem)] sm:basis-0">
          {/* `break-words`, not `truncate`. A truncated title is hidden content, and these
              titles are the only thing distinguishing one round from another. */}
          <p className="break-words text-sm font-semibold">{a.title}</p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            <span className="font-medium uppercase tracking-wide">{meta.label}</span>
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              {new Date(a.created_at).toLocaleString([], {
                day: '2-digit',
                month: 'short',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[10px] uppercase text-muted-foreground">Score</p>
          <p className="text-lg font-bold">
            {Math.round(a.score)}<span className="text-xs text-muted-foreground">/100</span>
          </p>
        </div>
        {a.activity_type === 'interview' && sessionId ? (
          <Link
            href={`/report/${sessionId}`}
            onClick={(e) => e.stopPropagation()}
            // min-h-11: 44px, because at py-2 this was a 30px-tall tap target on a phone.
            className="ml-auto inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg bg-primary/10 px-3 py-2 text-xs font-bold text-primary transition-colors hover:bg-primary/20 sm:ml-2 sm:min-h-0"
          >
            <FileText className="h-3.5 w-3.5" /> View
          </Link>
        ) : hasDetail ? (
          <ChevronDown className={`ml-auto h-4 w-4 shrink-0 text-muted-foreground transition-transform sm:ml-2 ${open ? 'rotate-180' : ''}`} />
        ) : null}
      </button>

      {open && hasDetail && (
        <div className="space-y-3 border-t border-border/40 p-4">
          {(scoreChips.length > 0 || metricChips.length > 0 || quizTopics.length > 0) && (
            <div className="flex flex-wrap gap-1.5 text-xs">
              {scoreChips.map((s) => (
                <span key={s.label} className="rounded-full border border-border px-2.5 py-0.5">
                  {s.label}: {s.value.toFixed(1)}/10
                </span>
              ))}
              {metricChips.map((m) => (
                <span key={m} className="rounded-full border border-border px-2.5 py-0.5 text-muted-foreground">
                  {m}
                </span>
              ))}
              {quizTopics.map((t) => (
                <span key={t} className="rounded-full border border-border px-2.5 py-0.5 text-muted-foreground">
                  {t}
                </span>
              ))}
            </div>
          )}
          {feedback && <p className="text-sm leading-relaxed text-foreground/85">{feedback}</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            {strengths.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-accent-emerald-ink">Strengths</p>
                <ul className="space-y-1 text-sm text-foreground/80">
                  {strengths.map((s, i) => (
                    <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-emerald" />{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {improvements.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-accent-amber-ink">To improve</p>
                <ul className="space-y-1 text-sm text-foreground/80">
                  {improvements.map((s, i) => (
                    <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-amber" />{s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ReportsListPage() {
  const { data: sessions, isLoading, error, refetch, isFetching } = useUserSessions(20);
  const { data: activity, isLoading: activityLoading } = useActivity(100);

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <PageHeader
          eyebrow="History"
          title="Interview Performance Reports"
          description="Review detailed AI evaluations, score breakdowns, and recommendations for all your completed sessions."
        />

      {error ? (
        <DataError
          title="Could not load your history"
          error={error}
          onRetry={() => refetch()}
          retrying={isFetching}
        />
      ) : isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : !sessions || sessions.length === 0 ? (
        <div className="mx-auto max-w-lg rounded-xl border border-border bg-surface-elevated p-10 text-center shadow-elev-1">
          <FileText className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
          <h3 className="font-semibold text-lg mb-2">No Reports Available Yet</h3>
          <p className="text-sm text-muted-foreground mb-6">
            Complete your first mock interview session to generate a detailed performance report.
          </p>
          <Link
            href="/interview"
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-bold text-primary-foreground hover:bg-primary/90 transition-[color,background-color,border-color,box-shadow,transform,opacity] shadow-glow"
          >
            <Play className="h-4 w-4" /> Start Interview
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {sessions.map((sess) => (
            <div
              key={sess.id}
              className="flex flex-col justify-between rounded-xl border border-border bg-surface-elevated p-5 shadow-elev-1 transition-shadow hover:shadow-elev-2"
            >
              <div>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 break-words text-xs font-bold uppercase text-primary">{sess.company_name}</span>
                  <span
                    className={`text-[10px] px-2.5 py-0.5 rounded-full font-semibold border ${
                      sess.status === 'completed'
                        ? 'bg-accent-emerald/10 text-accent-emerald-ink border-accent-emerald/30'
                        : 'bg-accent-amber/10 text-accent-amber-ink border-accent-amber/30'
                    }`}
                  >
                    {sess.status}
                  </span>
                </div>
                <h3 className="break-words text-base font-semibold">{sess.track_name}</h3>
                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5" />
                    {sess.started_at
                      ? new Date(sess.started_at).toLocaleString([], {
                          day: '2-digit',
                          month: 'short',
                          year: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })
                      : 'N/A'}
                  </span>
                  <span>•</span>
                  <span>{sess.questions_asked} Questions</span>
                </div>
                {sess.topics && sess.topics.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {sess.topics.slice(0, 5).map((t) => (
                      <span
                        key={t}
                        className="rounded-full border border-border bg-surface px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border/40 pt-4">
                <div>
                  <p className="text-[10px] text-muted-foreground uppercase">Overall Score</p>
                  <p className="text-xl font-bold text-foreground">
                    {sess.overall_score !== null ? `${sess.overall_score}/100` : '—'}
                  </p>
                </div>
                <Link
                  href={sess.status === 'completed' ? `/report/${sess.id}` : `/session/${sess.id}`}
                  // 44px minimum: a 30px-tall link is under the touch-target floor.
                  className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary/10 px-4 py-2 text-xs font-bold text-primary transition-colors hover:bg-primary/20 sm:min-h-0"
                >
                  {sess.status === 'completed' ? (
                    <>
                      <FileText className="h-3.5 w-3.5" /> View Report
                    </>
                  ) : (
                    <>
                      <Play className="h-3.5 w-3.5" /> Resume
                    </>
                  )}
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Unified activity feed — everything the candidate has done */}
      <div className="pt-4">
        <h2 className="text-xl font-semibold">All Activity</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Every session across the platform — interviews, group discussions, communication rounds and quizzes.
        </p>

        {activityLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : !activity || activity.length === 0 ? (
          <div className="glass mt-4 rounded-xl border border-border/50 p-8 text-center text-sm text-muted-foreground">
            No activity yet. Finish an interview, quiz, communication round or group discussion and it&apos;ll show up here.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {activity.map((a) => (
              <ActivityRow key={a.id} a={a} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
