'use client';

import { useParams, useRouter } from 'next/navigation';
import { type ReportData, useReport, useToggleShareReport } from '@/hooks/useData';
import { motion } from 'framer-motion';
import { Award, BookOpen, CheckCircle2, ChevronLeft, ExternalLink, ListChecks, Loader2, RefreshCw, ShieldCheck, Sparkles, TrendingUp, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { ShareMenu } from '@/components/report/ShareMenu';
import { DriveReportPaywall } from '@/components/billing/DriveReportPaywall';
import { readReportLock } from '@/lib/billing/drive-report';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { fadeUp, scalePop, staggerContainer, easeOutExpo } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

const REPORT_GENERATION_MESSAGES = [
  'Reading through your full session…',
  'Scoring each answer against the ideal response…',
  'Identifying strengths and gaps by topic…',
  'Building your improvement roadmap…',
  'Almost done…',
];

/**
 * The four competencies the report scores, in the order a real assessment reads
 * them: what they knew, how completely they answered, how clearly they explained
 * it, how assured they seemed.
 *
 * Explicit rather than derived from Object.keys so the order is stable between
 * reports and the labels are presentable — a candidate should not be shown
 * `technical_accuracy`. Any dimension the model returns that isn't listed here is
 * still rendered (title-cased) rather than silently dropped.
 */
const DIMENSION_LABELS: Record<string, string> = {
  technical_accuracy: 'Technical Accuracy',
  answer_completeness: 'Answer Completeness',
  communication_clarity: 'Communication Clarity',
  confidence: 'Confidence & Composure',
};

const DIMENSION_ORDER = Object.keys(DIMENSION_LABELS);

function dimensionLabel(key: string): string {
  return (
    DIMENSION_LABELS[key] ??
    key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/** Known dimensions first in their canonical order, then anything unexpected. */
function orderedDimensions(scores: Record<string, number>): Array<[string, number]> {
  const entries = Object.entries(scores);
  return entries.sort(([a], [b]) => {
    const ia = DIMENSION_ORDER.indexOf(a);
    const ib = DIMENSION_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
}

/**
 * Bar colour by band, so the breakdown is readable at a glance.
 *
 * Flat fills, not gradients. These were two-stop gradients between adjacent
 * steps of the same Tailwind hue (emerald-500 → emerald-400), a difference of
 * about 8% lightness across a 6px bar — invisible, and it cost a paint layer
 * per bar. The bands are what carry the meaning; a gradient inside one band
 * says nothing.
 */
function scoreTone(score: number): string {
  if (score >= 75) return 'bg-accent-emerald';
  if (score >= 50) return 'bg-accent-indigo';
  if (score >= 30) return 'bg-accent-amber';
  return 'bg-accent-coral';
}

const READINESS_META: Record<string, { label: string; variant: 'success' | 'warning' | 'danger' }> = {
  interview_ready: { label: 'Interview Ready', variant: 'success' },
  close_to_ready: { label: 'Close to Ready', variant: 'warning' },
  significant_gaps: { label: 'Significant Gaps', variant: 'danger' },
  needs_more_practice: { label: 'Needs More Practice', variant: 'warning' },
};

/**
 * Resolve a resource to a link that ALWAYS works. The AI supplies a URL for
 * some resources but leaves others null (they're study tasks, e.g. "record
 * yourself answering…"), and it can occasionally hallucinate a broken URL. So
 * we use the given URL only when it's a well-formed http(s) link, and otherwise
 * fall back to a Google search of the title (+author) — which reliably lands on
 * the real resource — so no pill is ever a dead "#" link.
 */
function resourceHref(res: { title: string; url: string | null; author: string | null }): string {
  const url = res.url?.trim() ?? '';
  if (/^https?:\/\/\S+\.\S+/i.test(url)) return url;
  const query = [res.title, res.author].filter(Boolean).join(' ');
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}

function OverallScoreRing({ score, label }: { score: number; label: string }) {
  const circumference = 2 * Math.PI * 54;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div className="relative flex h-36 w-36 items-center justify-center">
      <svg className="h-36 w-36 -rotate-90" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="54" strokeWidth="8" className="stroke-border/50" fill="none" />
        <motion.circle
          cx="60" cy="60" r="54" strokeWidth="8" fill="none" strokeLinecap="round"
          className="stroke-primary"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.1, ease: easeOutExpo, delay: 0.2 }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-3xl font-medium tracking-[-0.025em] text-primary">{score}</span>
        <span className="text-[10px] text-muted-foreground">/ 100 · {label}</span>
      </div>
    </div>
  );
}

export default function ReportDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const router = useRouter();

  const { data: report, isLoading, isFetching, error, refetch } = useReport(sessionId);
  const toggleShare = useToggleShareReport();

  const handleShare = () => {
    if (!report) return;
    toggleShare.mutate(report.id, {
      onSuccess: (data) => {
        toast.success(data.is_shared ? 'Report sharing enabled' : 'Report sharing disabled');
      },
    });
  };

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <AIWorkingIndicator messages={REPORT_GENERATION_MESSAGES} intervalMs={5000} />
      </div>
    );
  }

  if (error || !report) {
    // The API explains exactly why a report can't be produced — the session was
    // never completed, or no answers were recorded. Showing a generic "not
    // found" threw that away and left the candidate with nothing to act on.
    const reason = (error as { message?: string } | null)?.message?.trim();
    const generic = 'Could not load the report for this session.';
    return (
      <motion.div initial="hidden" animate="visible" variants={scalePop} className="mx-auto mt-12 max-w-2xl">
        <Card className="border-destructive/20 p-8 text-center">
          <XCircle className="mx-auto mb-4 h-12 w-12 text-destructive" />
          <h2 className="mb-2 text-xl font-semibold">Report Unavailable</h2>
          <p className="text-sm text-muted-foreground">{reason || generic}</p>
          <p className="mt-3 text-xs text-muted-foreground">
            A report needs a finished session with at least one answered question. If you left the
            interview early, open it again and use “End interview” so it can be scored.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Button variant="secondary" onClick={() => refetch()} loading={isFetching}>
              Try again
            </Button>
            <Button onClick={() => router.push(`/session/${sessionId}`)}>
              Resume interview
            </Button>
            <Button variant="ghost" onClick={() => router.push('/dashboard')}>
              <ChevronLeft className="h-4 w-4" /> Dashboard
            </Button>
          </div>
        </Card>
      </motion.div>
    );
  }

  /*
   * THE PAYWALL, AND WHY IT IS A RETURN RATHER THAN A PROP.
   *
   * On the Cognizant Digital Nurture 24 August drive the interview is free and the report is
   * ₹50. The gate is on DELIVERY, not on generation: the report below was still generated and
   * stored exactly as it always is, and the server simply sent less of it. So there is nothing
   * to hide field by field — the dimension scores, the per-question analysis, the roadmap and
   * the study resources were never in this response. Everything after this point renders what
   * arrived, which is why returning early is the honest shape: a `locked` prop threaded
   * through the sections below would be twelve chances to leak one of them, and every one of
   * those chances would have to stay correct forever.
   *
   * `readReportLock` FAILS OPEN and is the only thing on the frontend that decides this. Any
   * response that is not unambiguously a locked drive report — every other track, every
   * report generated before the gate existed, and anything malformed enough that the predicate
   * cannot decide — falls straight through to the full report. A locked report shown to
   * somebody who owes nothing is the worst outcome available here and it would land on
   * students who are mid-placement-season, so the ambiguous case is always "deliver".
   *
   * Unlocking is `refetch()` for the same reason: the report was never not there.
   */
  const lock = readReportLock(report);
  if (lock) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 pb-12">
        <button
          onClick={() => router.push('/dashboard')}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Back to Dashboard
        </button>
        {/* No ShareMenu and no Detailed Analysis link: neither is something to offer for a
            report the candidate has not seen yet, and a share link to a locked report is a
            link to a paywall with somebody else's name on it. */}
        <DriveReportPaywall lock={lock} onUnlocked={() => void refetch()} />
      </div>
    );
  }

  const readiness = READINESS_META[report.readiness_level] ?? { label: report.readiness_level, variant: 'warning' as const };

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-5xl space-y-8 pb-12">
      {/* Top nav / controls */}
      <motion.div variants={fadeUp} className="flex items-center justify-between">
        <button
          onClick={() => router.push('/dashboard')}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Back to Dashboard
        </button>
        <div className="flex flex-wrap items-center gap-2">
          {/* The detailed view is a free database read, so it is offered up front
              rather than behind a warning about cost. Model answers inside it are
              generated per question, on request. */}
          <button
            onClick={() => router.push(`/report/${sessionId}/analysis`)}
            className="inline-flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-4 py-2 text-xs font-semibold text-primary transition-[color,background-color,border-color,box-shadow,transform,opacity] hover:bg-primary/20"
          >
            <ListChecks className="h-3.5 w-3.5" />
            Detailed Analysis
          </button>
          <ShareMenu
            reportId={report.id}
            isShared={report.is_shared}
            onToggleShare={handleShare}
            toggling={toggleShare.isPending}
            summary={`${Math.round(report.overall_score)}/100 · ${readiness.label}`}
          />
        </div>
      </motion.div>

      {/* Header Banner */}
      <motion.div variants={fadeUp}>
        <Card className="relative overflow-hidden p-6">
          <div className="relative flex flex-col items-start justify-between gap-8 md:flex-row md:items-center">
            <div>
              <div className="mb-3 flex items-center gap-3">
                <Badge variant={readiness.variant}>{readiness.label}</Badge>
                <span className="text-xs text-muted-foreground">
                  Evaluated on {new Date(report.created_at).toLocaleDateString()}
                </span>
              </div>
              <h1 className="text-3xl font-semibold tracking-[-0.02em]">Technical Evaluation Report</h1>
              <p className="mt-2 max-w-xl text-sm text-muted-foreground">{report.executive_summary}</p>
              {report.readiness_reasoning && (
                <p className="mt-2 max-w-xl text-xs italic text-muted-foreground/80">{report.readiness_reasoning}</p>
              )}
            </div>
            <OverallScoreRing score={report.overall_score} label={report.overall_score_label} />
          </div>
        </Card>
      </motion.div>

      {/* The report did not finish scoring. Say WHY, because the four reasons imply
          completely different actions — and one of them is not a fault at all. */}
      {report.unscored_reason && (
        <motion.div variants={fadeUp}>
          <UnscoredNotice reason={report.unscored_reason} onRetry={() => refetch()} retrying={isFetching} />
        </motion.div>
      )}

      {/* Progress vs last interview + delivery (pauses / fillers / pace) */}
      {(report.previous || report.delivery) && (
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <div className="grid gap-4 sm:grid-cols-2">
              {/* Comparison */}
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  vs your last interview
                </p>
                {report.previous ? (
                  (() => {
                    const delta = Math.round((report.overall_score - report.previous.overall_score) * 10) / 10;
                    // Three cases, not two. Treating 0 as "improved" rendered a
                    // green up-arrow reading "0 points higher than last time",
                    // which is both wrong and the kind of detail that makes a
                    // report look unfinished.
                    const direction = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
                    return (
                      <div className="flex items-center gap-3">
                        <span
                          className={cn(
                            'text-2xl font-bold',
                            direction === 'up' && 'text-accent-emerald-ink',
                            direction === 'down' && 'text-accent-coral-ink',
                            direction === 'flat' && 'text-muted-foreground'
                          )}
                        >
                          {direction === 'up' ? '▲' : direction === 'down' ? '▼' : '='}{' '}
                          {Math.abs(delta)}
                        </span>
                        <span className="text-sm text-muted-foreground">
                          {direction === 'up'
                            ? 'points higher than last time'
                            : direction === 'down'
                              ? 'points lower than last time'
                              : 'no change from last time'}
                          {' '}({report.previous.overall_score}/100 → {report.overall_score}/100)
                        </span>
                      </div>
                    );
                  })()
                ) : (
                  <p className="text-sm text-muted-foreground">
                    This is your first interview — great start! Future reports will compare against it.
                  </p>
                )}
              </div>

              {/* Delivery */}
              {report.delivery && (
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Delivery
                  </p>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span
                      className={cn(
                        'rounded-full border px-2.5 py-1',
                        (report.delivery.pause_count ?? 0) > 4
                          ? 'border-accent-coral/40 bg-accent-coral/10 text-accent-coral-ink'
                          : 'border-border text-muted-foreground'
                      )}
                    >
                      {report.delivery.pause_count ?? 0} pauses
                      {report.delivery.total_pause_seconds
                        ? ` · ${report.delivery.total_pause_seconds}s`
                        : ''}
                    </span>
                    <span
                      className={cn(
                        'rounded-full border px-2.5 py-1',
                        (report.delivery.filler_count ?? 0) > 5
                          ? 'border-accent-coral/40 bg-accent-coral/10 text-accent-coral-ink'
                          : 'border-border text-muted-foreground'
                      )}
                    >
                      {report.delivery.filler_count ?? 0} filler words
                    </span>
                    {!!report.delivery.wpm && (
                      <span className="rounded-full border border-border px-2.5 py-1 text-muted-foreground">
                        {report.delivery.wpm} wpm
                      </span>
                    )}
                    {/* Its own colour, not the amber the other chips share: this is
                        not a metric to improve by a few points, it is something a
                        real panel wrote down. Quoted back, because "you said X" is
                        actionable in a way "1 incident" is not. */}
                    {!!report.delivery.unprofessional_count && (
                      <span className="rounded-full border border-destructive/40 bg-destructive/10 px-2.5 py-1 font-medium text-destructive">
                        Unprofessional language
                        {report.delivery.unprofessional_words?.length
                          ? `: ${report.delivery.unprofessional_words.map((w) => `“${w}”`).join(', ')}`
                          : ''}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Card>
        </motion.div>
      )}

      {/* Grid: Strengths & Weaknesses */}
      <div className="grid gap-6 md:grid-cols-2">
        <motion.div variants={fadeUp}>
          <Card className="h-full border-accent-emerald/20 p-6">
            <div className="mb-4 flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-accent-emerald-ink" />
              <h3 className="text-base font-semibold">Key Strengths</h3>
            </div>
            <ul className="space-y-2.5">
              {report.strengths.map((str, idx) => (
                <li key={idx} className="flex items-start gap-2.5 text-sm text-foreground/90">
                  <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-accent-emerald" />
                  <span>{str}</span>
                </li>
              ))}
            </ul>
          </Card>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card className="h-full border-accent-amber/20 p-6">
            <div className="mb-4 flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-accent-amber-ink" />
              <h3 className="text-base font-semibold">Areas for Growth</h3>
            </div>
            <ul className="space-y-2.5">
              {report.weaknesses.map((w, idx) => (
                <li key={idx} className="flex items-start gap-2.5 text-sm text-foreground/90">
                  <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-accent-amber" />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </Card>
        </motion.div>
      </div>

      {/* Competency Assessment — the four dimension scores plus the percentile.
          Both are produced by the report model and were previously discarded,
          which is what left the report thin: a real evaluation reports HOW the
          candidate performed, not just a single number. */}
      {Object.keys(report.dimension_scores || {}).length > 0 && (
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <h3 className="flex items-center gap-2 text-base font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" /> Competency Assessment
              </h3>
              {!!report.performance_percentile && (
                // Stated as "better than N%", not "top N%". A 3rd-percentile
                // result inverts to "Top 97%", which reads as praise for a poor
                // performance — the one thing an assessment report must not do.
                <span className="rounded-full border border-border bg-secondary/60 px-3 py-1 text-xs font-semibold text-muted-foreground">
                  Better than {Math.round(report.performance_percentile)}% of candidates on this track
                </span>
              )}
            </div>
            <div className="grid gap-5 sm:grid-cols-2">
              {orderedDimensions(report.dimension_scores).map(([key, score]) => (
                <div key={key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-xs font-semibold">{dimensionLabel(key)}</span>
                    <span className="text-sm font-bold tabular-nums text-foreground">
                      {Math.round(score)}
                      <span className="text-[11px] font-medium text-muted-foreground">/100</span>
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                    <motion.div
                      className={cn('h-full rounded-full', scoreTone(score))}
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(Math.max(score, 0), 100)}%` }}
                      transition={{ duration: 0.8, ease: easeOutExpo }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </motion.div>
      )}

      {/* Topic Breakdown */}
      {Object.keys(report.topic_scores || {}).length > 0 && (
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <h3 className="mb-6 flex items-center gap-2 text-base font-semibold">
              <Award className="h-5 w-5 text-primary" /> Topic Performance Breakdown
            </h3>
            <div className="space-y-4">
              {Object.entries(report.topic_scores).map(([topic, score]) => (
                <div key={topic} className="space-y-1.5">
                  <div className="flex justify-between text-xs font-semibold">
                    <span>{topic}</span>
                    <span className="text-primary">{score}/100</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                    <motion.div
                      className="h-full rounded-full bg-gradient-to-r from-primary to-accent-violet"
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(score, 100)}%` }}
                      transition={{ duration: 0.8, ease: easeOutExpo }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </motion.div>
      )}

      {/* Question-by-Question Analysis */}
      {report.question_analysis && report.question_analysis.length > 0 && (
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <h3 className="mb-6 flex items-center gap-2 text-base font-semibold">
              <ShieldCheck className="h-5 w-5 text-primary" /> Question-by-Question Analysis
            </h3>
            <div className="space-y-4">
              {report.question_analysis.map((qa, idx) => (
                <div key={idx} className="space-y-2 rounded-xl border border-border/50 bg-surface/50 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="flex-1 text-sm font-semibold">{qa.question}</p>
                    <span className="whitespace-nowrap text-xs font-bold text-primary">{qa.score}/10</span>
                  </div>
                  <span className="inline-block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {qa.answer_quality.replace('_', ' ')}
                  </span>
                  {qa.missing_concepts.length > 0 && (
                    <p className="text-xs text-foreground/80">
                      <span className="font-semibold text-accent-amber-ink">Missing: </span>
                      {qa.missing_concepts.join(', ')}
                    </p>
                  )}
                  {qa.ideal_answer_summary && (
                    <p className="text-xs text-muted-foreground">
                      <span className="font-semibold">Ideal answer: </span>
                      {qa.ideal_answer_summary}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Card>
        </motion.div>
      )}

      {/* Improvement Roadmap */}
      {report.improvement_roadmap && report.improvement_roadmap.length > 0 && (
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <h3 className="mb-6 flex items-center gap-2 text-base font-semibold">
              <Sparkles className="h-5 w-5 text-accent-violet" /> Recommended Action Plan
            </h3>
            <div className="space-y-4">
              {report.improvement_roadmap.map((item, idx) => (
                <div key={idx} className="space-y-3 rounded-xl border border-border/50 bg-surface/50 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase text-primary">Priority #{item.priority}</span>
                    <span className="text-xs text-muted-foreground">Est. {item.study_hours_estimate} hrs study</span>
                  </div>
                  <h4 className="text-sm font-semibold">{item.topic}</h4>
                  <div className="flex items-center gap-4 text-xs">
                    <span>
                      Current: <strong className="text-accent-amber-ink">{item.current_score}</strong>
                      <span className="text-muted-foreground">/10</span>
                    </span>
                    <span>→</span>
                    <span>
                      Target: <strong className="text-accent-emerald-ink">{item.target_score}</strong>
                      <span className="text-muted-foreground">/10</span>
                    </span>
                  </div>
                  {item.resources && item.resources.length > 0 && (
                    <div className="border-t border-border/40 pt-2">
                      <p className="mb-2 text-[11px] font-semibold text-muted-foreground">Recommended Study Resources:</p>
                      <div className="flex flex-wrap gap-2">
                        {item.resources.map((res, rIdx) => (
                          <a
                            key={rIdx}
                            href={resourceHref(res)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-md border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs text-primary transition-colors hover:bg-primary/20"
                          >
                            <BookOpen className="h-3 w-3" />
                            {res.title}
                            <ExternalLink className="h-3 w-3 opacity-60" />
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        </motion.div>
      )}
    </motion.div>
  );
}

/**
 * Why the report did not finish scoring.
 *
 * Four situations that used to produce one sentence — "AI scoring is temporarily
 * unavailable, please retry shortly". That sentence is wrong for three of them and
 * actively misleading for one: a candidate who has used their day's practice allowance
 * is not looking at a broken service, and telling them to retry shortly sends them into
 * a loop that cannot succeed.
 *
 * So each reason gets its own copy, its own tone, and — the part that matters — a retry
 * button only where retrying can actually work.
 */
function UnscoredNotice({
  reason,
  onRetry,
  retrying,
}: {
  reason: NonNullable<ReportData['unscored_reason']>;
  onRetry: () => void;
  retrying: boolean;
}) {
  const copy = {
    user_quota: {
      tone: 'amber' as const,
      title: "You've used today's AI practice",
      body:
        "Nothing is broken and nothing is lost — your answers are all saved. Full scoring " +
        'resumes tomorrow, and your report will generate then. This limit exists so one ' +
        'very heavy day cannot use up everyone else’s.',
      // Deliberately NO retry. Retrying cannot succeed until the day rolls over, and a
      // button that is guaranteed to fail is worse than no button.
      canRetry: false,
    },
    service_limit: {
      tone: 'coral' as const,
      title: 'Scoring is paused across the service',
      body:
        'This is on our side, not yours — a safety limit tripped and we have been alerted. ' +
        'Your answers are saved. Try again in a little while.',
      canRetry: true,
    },
    timeout: {
      tone: 'coral' as const,
      title: 'Scoring took too long',
      body:
        'A long interview is a lot to grade at once and this one ran past the time limit. ' +
        'Your answers are saved — generating again usually works.',
      canRetry: true,
    },
    provider_unavailable: {
      tone: 'coral' as const,
      title: 'Scoring could not be completed',
      body:
        'The model was unreachable. Your answers are saved, so nothing needs redoing — ' +
        'generate the report again in a moment.',
      canRetry: true,
    },
  }[reason];

  return (
    <Card
      className={cn(
        'flex flex-col gap-3 p-6 sm:flex-row sm:items-start sm:justify-between',
        copy.tone === 'amber'
          ? 'border-accent-amber/40 bg-accent-amber/5'
          : 'border-accent-coral/40 bg-accent-coral/5'
      )}
    >
      <div className="min-w-0">
        <p
          className={cn(
            'text-sm font-semibold',
            copy.tone === 'amber' ? 'text-accent-amber-ink' : 'text-accent-coral-ink'
          )}
        >
          {copy.title}
        </p>
        <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">{copy.body}</p>
      </div>
      {copy.canRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry} loading={retrying} className="shrink-0">
          <RefreshCw className="h-3.5 w-3.5" /> Generate again
        </Button>
      )}
    </Card>
  );
}
