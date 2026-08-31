'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Code2, Download, Lock } from 'lucide-react';
import { BrandLoader } from '@/components/brand/BrandLoader';
import { formatDate } from '@/lib/format-date';
import { getBrowserApiClient } from '@/lib/api';
import { scoreBarTone, scoreChipTone } from '@/lib/score-bands';
import { cn } from '@/lib/utils';
import { AiAssessmentNotice } from '@/components/report/AiAssessmentNotice';


interface PublicReport {
  report_id: string;
  candidate_name: string;
  track_name: string;
  company_name: string;
  overall_score: number;
  overall_score_label: string;
  readiness_level: string;
  executive_summary: string;
  strengths: string[];
  weaknesses: string[];
  topic_scores: Record<string, number>;
  dimension_scores: Record<string, number>;
  created_at: string;
}

const READINESS_LABELS: Record<string, string> = {
  interview_ready: 'Interview Ready',
  close_to_ready: 'Close to Ready',
  needs_more_practice: 'Needs More Practice',
  significant_gaps: 'Significant Gaps',
};

function label(key: string): string {
  return READINESS_LABELS[key] ?? key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/*
 * A FOURTH COPY OF THESE THRESHOLDS lived here — 75 / 50 / 30, matching neither the backend's
 * 85 / 70 / 55 / 40 (which produces the words) nor the two other frontend copies. This is the
 * PUBLIC report: the page a candidate shares with a friend or a placement cell, so it is the
 * one surface where our own numbers disagreeing with each other is visible to somebody who
 * does not have an account and cannot check.
 *
 * lib/score-bands.ts is the only answer now, pinned against composer.py by a test.
 */
const tone = scoreBarTone;

function Bars({ scores }: { scores: Record<string, number> }) {
  return (
    <div className="space-y-3">
      {Object.entries(scores).map(([name, score]) => (
        <div key={name} className="space-y-1">
          <div className="flex items-baseline justify-between text-xs">
            <span className="font-medium">{label(name)}</span>
            <span
              className={cn(
                'rounded px-1.5 py-0.5 font-mono text-xs font-bold tabular-nums',
                scoreChipTone(score),
              )}
            >
              {Math.round(score)}
              <span className="text-[10px] font-medium opacity-60">/100</span>
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
            <div
              className={cn('h-full rounded-full', tone(score))}
              style={{ width: `${Math.min(Math.max(score, 0), 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function PublicReportPage() {
  const params = useParams();
  const reportId = params.reportId as string;

  const { data, isLoading, error } = useQuery({
    queryKey: ['public-report', reportId],
    queryFn: async () => {
      const res = await getBrowserApiClient().get(`/api/v1/reports/public/${reportId}`);
      return res.data as PublicReport;
    },
    enabled: !!reportId,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <BrandLoader label="Loading this report" size={56} />
      </div>
    );
  }

  // A withdrawn link is the normal case, not a crash: the owner turned sharing
  // off, and the viewer should be told that rather than shown an error.
  if (error || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="max-w-md rounded-2xl border border-border bg-surface p-8 text-center">
          <Lock className="mx-auto mb-4 h-10 w-10 text-muted-foreground" />
          <h1 className="mb-2 text-lg font-semibold">This report isn&apos;t shared</h1>
          <p className="text-sm text-muted-foreground">
            The link may have been turned off by its owner, or it may be incorrect.
          </p>
          <Link
            href="/"
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground"
          >
            Try InterviewOS <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background px-6 py-10 print:py-0">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-2">
            <Code2 className="h-5 w-5 text-primary" />
            <span className="font-bold">InterviewOS</span>
          </Link>
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-muted-foreground transition-colors hover:bg-secondary print:hidden"
          >
            <Download className="h-3.5 w-3.5" /> Download PDF
          </button>
        </div>

        <div className="rounded-2xl border border-border bg-surface p-8 print:border-0 print:p-0">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {data.company_name ? `${data.company_name} · ` : ''}
                {data.track_name}
              </p>
              <p className="mt-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-accent-teal-ink">
                <span aria-hidden className="h-px w-3.5 shrink-0 bg-accent-teal" />
                Shared report
              </p>
              <h1 className="mt-1.5 text-2xl font-semibold tracking-tight">{data.candidate_name}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Mock interview assessment · {formatDate(data.created_at)}
              </p>
              <span className="mt-3 inline-block rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
                {label(data.readiness_level)}
              </span>
            </div>

            <div className="text-right">
              <p className="text-5xl font-bold tabular-nums text-primary">
                {Math.round(data.overall_score)}
              </p>
              <p className="text-xs text-muted-foreground">
                / 100 · {data.overall_score_label}
              </p>
            </div>
          </div>

          {/* FULL VARIANT ON A SHARED REPORT, deliberately. The person reading this is very
              often NOT the candidate — it is a link they sent to a mentor, a senior, or
              somebody deciding something about them. That reader has seen none of the
              product's framing and has the least context for how the number was produced,
              so this is the surface where the short label is not enough. */}
          <AiAssessmentNotice variant="full" className="mt-6" />

          {data.executive_summary && (
            <p className="mt-6 border-t border-border pt-6 text-sm leading-relaxed text-foreground/85">
              {data.executive_summary}
            </p>
          )}

          {Object.keys(data.dimension_scores).length > 0 && (
            <div className="mt-8">
              <h2 className="mb-4 text-sm font-semibold">Competency Assessment</h2>
              <Bars scores={data.dimension_scores} />
            </div>
          )}

          {(data.strengths.length > 0 || data.weaknesses.length > 0) && (
            <div className="mt-8 grid gap-6 sm:grid-cols-2">
              {data.strengths.length > 0 && (
                <div>
                  <h2 className="mb-3 text-sm font-semibold text-accent-emerald-ink">Key Strengths</h2>
                  <ul className="space-y-2">
                    {data.strengths.map((s, i) => (
                      <li key={i} className="text-xs leading-relaxed text-foreground/85">
                        • {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {data.weaknesses.length > 0 && (
                <div>
                  <h2 className="mb-3 text-sm font-semibold text-accent-amber-ink">Areas for Growth</h2>
                  <ul className="space-y-2">
                    {data.weaknesses.map((w, i) => (
                      <li key={i} className="text-xs leading-relaxed text-foreground/85">
                        • {w}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {Object.keys(data.topic_scores).length > 0 && (
            <div className="mt-8">
              <h2 className="mb-4 text-sm font-semibold">Topic Performance</h2>
              <Bars scores={data.topic_scores} />
            </div>
          )}

          <p className="mt-8 border-t border-border pt-4 text-[11px] text-muted-foreground">
            Generated by InterviewOS. Individual answers are not included in a shared report.
          </p>
        </div>

        <div className="mt-8 text-center print:hidden">
          <Link
            href="/register"
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground"
          >
            Run your own mock interview <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
