'use client';

import { useParams, useRouter } from 'next/navigation';
import { useReport, useToggleShareReport } from '@/hooks/useData';
import { motion } from 'framer-motion';
import {
  Award,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ExternalLink,
  Loader2,
  Share2,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { fadeUp, scalePop, staggerContainer, easeOutExpo } from '@/lib/motion';

const REPORT_GENERATION_MESSAGES = [
  'Reading through your full session…',
  'Scoring each answer against the ideal response…',
  'Identifying strengths and gaps by topic…',
  'Building your improvement roadmap…',
  'Almost done…',
];

const READINESS_META: Record<string, { label: string; variant: 'success' | 'warning' | 'danger' }> = {
  interview_ready: { label: 'Interview Ready', variant: 'success' },
  close_to_ready: { label: 'Close to Ready', variant: 'warning' },
  significant_gaps: { label: 'Significant Gaps', variant: 'danger' },
  needs_more_practice: { label: 'Needs More Practice', variant: 'warning' },
};

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
        <span className="text-3xl font-bold tracking-tight text-primary">{score}</span>
        <span className="text-[10px] text-muted-foreground">/ 100 · {label}</span>
      </div>
    </div>
  );
}

export default function ReportDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const router = useRouter();

  const { data: report, isLoading, error } = useReport(sessionId);
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
    return (
      <motion.div initial="hidden" animate="visible" variants={scalePop} className="mx-auto mt-12 max-w-2xl">
        <Card className="border-destructive/20 p-8 text-center">
          <XCircle className="mx-auto mb-4 h-12 w-12 text-destructive" />
          <h2 className="mb-2 text-xl font-bold">Report Not Found</h2>
          <p className="mb-6 text-sm text-muted-foreground">
            Could not load the report for this session. Please make sure the session is complete.
          </p>
          <Button onClick={() => router.push('/dashboard')}>
            <ChevronLeft className="h-4 w-4" /> Back to Dashboard
          </Button>
        </Card>
      </motion.div>
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
        <button
          onClick={handleShare}
          disabled={toggleShare.isPending}
          className={`inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-xs font-semibold transition-all ${
            report.is_shared
              ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-600'
              : 'border-border bg-surface text-muted-foreground hover:bg-secondary'
          }`}
        >
          <Share2 className="h-3.5 w-3.5" />
          {report.is_shared ? 'Publicly Shared' : 'Share Report'}
        </button>
      </motion.div>

      {/* Header Banner */}
      <motion.div variants={fadeUp}>
        <Card className="hero-wash relative overflow-hidden border-primary/20 p-8">
          <div className="relative flex flex-col items-start justify-between gap-8 md:flex-row md:items-center">
            <div>
              <div className="mb-3 flex items-center gap-3">
                <Badge variant={readiness.variant}>{readiness.label}</Badge>
                <span className="text-xs text-muted-foreground">
                  Evaluated on {new Date(report.created_at).toLocaleDateString()}
                </span>
              </div>
              <h1 className="text-3xl font-bold tracking-[-0.02em]">Technical Evaluation Report</h1>
              <p className="mt-2 max-w-xl text-sm text-muted-foreground">{report.executive_summary}</p>
              {report.readiness_reasoning && (
                <p className="mt-2 max-w-xl text-xs italic text-muted-foreground/80">{report.readiness_reasoning}</p>
              )}
            </div>
            <OverallScoreRing score={report.overall_score} label={report.overall_score_label} />
          </div>
        </Card>
      </motion.div>

      {/* Grid: Strengths & Weaknesses */}
      <div className="grid gap-6 md:grid-cols-2">
        <motion.div variants={fadeUp}>
          <Card className="h-full border-emerald-500/20 p-6">
            <div className="mb-4 flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
              <h3 className="text-base font-bold">Key Strengths</h3>
            </div>
            <ul className="space-y-2.5">
              {report.strengths.map((str, idx) => (
                <li key={idx} className="flex items-start gap-2.5 text-sm text-foreground/90">
                  <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-emerald-400" />
                  <span>{str}</span>
                </li>
              ))}
            </ul>
          </Card>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card className="h-full border-yellow-500/20 p-6">
            <div className="mb-4 flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-amber-600" />
              <h3 className="text-base font-bold">Areas for Growth</h3>
            </div>
            <ul className="space-y-2.5">
              {report.weaknesses.map((w, idx) => (
                <li key={idx} className="flex items-start gap-2.5 text-sm text-foreground/90">
                  <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-yellow-400" />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </Card>
        </motion.div>
      </div>

      {/* Topic Breakdown */}
      {Object.keys(report.topic_scores || {}).length > 0 && (
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <h3 className="mb-6 flex items-center gap-2 text-base font-bold">
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
            <h3 className="mb-6 flex items-center gap-2 text-base font-bold">
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
                      <span className="font-semibold text-amber-600">Missing: </span>
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
            <h3 className="mb-6 flex items-center gap-2 text-base font-bold">
              <Sparkles className="h-5 w-5 text-accent-violet" /> Recommended Action Plan
            </h3>
            <div className="space-y-4">
              {report.improvement_roadmap.map((item, idx) => (
                <div key={idx} className="space-y-3 rounded-xl border border-border/50 bg-surface/50 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase text-primary">Priority #{item.priority}</span>
                    <span className="text-xs text-muted-foreground">Est. {item.study_hours_estimate} hrs study</span>
                  </div>
                  <h4 className="text-sm font-bold">{item.topic}</h4>
                  <div className="flex items-center gap-4 text-xs">
                    <span>Current: <strong className="text-amber-600">{item.current_score}</strong></span>
                    <span>→</span>
                    <span>Target: <strong className="text-emerald-600">{item.target_score}</strong></span>
                  </div>
                  {item.resources && item.resources.length > 0 && (
                    <div className="border-t border-border/40 pt-2">
                      <p className="mb-2 text-[11px] font-semibold text-muted-foreground">Recommended Study Resources:</p>
                      <div className="flex flex-wrap gap-2">
                        {item.resources.map((res, rIdx) => (
                          <a
                            key={rIdx}
                            href={res.url || '#'}
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
