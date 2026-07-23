'use client';

import { useParams, useRouter } from 'next/navigation';
import { useReport, useToggleShareReport } from '@/hooks/useData';
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
        <p className="text-sm font-medium text-muted-foreground">Generating your AI Performance Report...</p>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="max-w-2xl mx-auto mt-12 glass rounded-2xl p-8 border border-destructive/20 text-center">
        <XCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
        <h2 className="text-xl font-bold mb-2">Report Not Found</h2>
        <p className="text-sm text-muted-foreground mb-6">
          Could not load the report for this session. Please make sure the session is complete.
        </p>
        <button
          onClick={() => router.push('/dashboard')}
          className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-bold text-primary-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Back to Dashboard
        </button>
      </div>
    );
  }

  const getRecommendationBadge = (rec: string) => {
    switch (rec) {
      case 'strong_hire':
        return { label: 'Strong Hire', color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' };
      case 'hire':
        return { label: 'Hire', color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' };
      case 'borderline':
        return { label: 'Borderline', color: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30' };
      default:
        return { label: 'Needs Improvement', color: 'bg-red-500/10 text-red-400 border-red-500/30' };
    }
  };

  const recBadge = getRecommendationBadge(report.hire_recommendation);

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-12">
      {/* Top nav / controls */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => router.push('/dashboard')}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronLeft className="h-4 w-4" /> Back to Dashboard
        </button>
        <button
          onClick={handleShare}
          disabled={toggleShare.isPending}
          className={`inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-xs font-semibold transition-all ${
            report.is_shared
              ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400'
              : 'border-border bg-surface hover:bg-accent text-muted-foreground'
          }`}
        >
          <Share2 className="h-3.5 w-3.5" />
          {report.is_shared ? 'Publicly Shared' : 'Share Report'}
        </button>
      </div>

      {/* Header Banner */}
      <div className="glass rounded-2xl border border-primary/20 p-8 relative overflow-hidden">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className={`px-3 py-1 rounded-full text-xs font-bold border ${recBadge.color}`}>
                {recBadge.label}
              </span>
              <span className="text-xs text-muted-foreground">
                Evaluated on {new Date(report.created_at).toLocaleDateString()}
              </span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">Technical Evaluation Report</h1>
            <p className="text-sm text-muted-foreground mt-2 max-w-xl">
              {report.executive_summary}
            </p>
          </div>

          <div className="flex flex-col items-center justify-center rounded-2xl bg-surface/80 border border-border/50 p-6 min-w-[160px] text-center shadow-glow">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Overall Score</span>
            <span className="text-4xl font-bold text-primary mt-1">{report.overall_score}</span>
            <span className="text-[10px] text-muted-foreground mt-0.5">out of 100 ({report.overall_score_label})</span>
          </div>
        </div>
      </div>

      {/* Grid: Strengths & Weaknesses */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Strengths */}
        <div className="glass rounded-xl border border-emerald-500/20 p-6">
          <div className="flex items-center gap-2 mb-4">
            <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            <h3 className="font-bold text-base">Key Strengths</h3>
          </div>
          <ul className="space-y-2.5">
            {report.strengths.map((str, idx) => (
              <li key={idx} className="flex items-start gap-2.5 text-sm text-foreground/90">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 mt-2 flex-shrink-0" />
                <span>{str}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Weaknesses / Growth Areas */}
        <div className="glass rounded-xl border border-yellow-500/20 p-6">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="h-5 w-5 text-yellow-400" />
            <h3 className="font-bold text-base">Areas for Growth</h3>
          </div>
          <ul className="space-y-2.5">
            {report.weaknesses.map((w, idx) => (
              <li key={idx} className="flex items-start gap-2.5 text-sm text-foreground/90">
                <span className="h-1.5 w-1.5 rounded-full bg-yellow-400 mt-2 flex-shrink-0" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Topic Breakdown */}
      {Object.keys(report.topic_scores || {}).length > 0 && (
        <div className="glass rounded-xl border border-border/50 p-6">
          <h3 className="font-bold text-base mb-6 flex items-center gap-2">
            <Award className="h-5 w-5 text-blue-400" /> Topic Performance Breakdown
          </h3>
          <div className="space-y-4">
            {Object.entries(report.topic_scores).map(([topic, score]) => (
              <div key={topic} className="space-y-1.5">
                <div className="flex justify-between text-xs font-semibold">
                  <span>{topic}</span>
                  <span className="text-primary">{score}/100</span>
                </div>
                <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(score, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Improvement Roadmap */}
      {report.improvement_roadmap && report.improvement_roadmap.length > 0 && (
        <div className="glass rounded-xl border border-border/50 p-6">
          <h3 className="font-bold text-base mb-6 flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-purple-400" /> Recommended Action Plan
          </h3>
          <div className="space-y-4">
            {report.improvement_roadmap.map((item, idx) => (
              <div key={idx} className="rounded-xl border border-border/50 bg-surface/50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-primary uppercase">Priority #{item.priority}</span>
                  <span className="text-xs text-muted-foreground">Est. {item.study_hours_estimate} hrs study</span>
                </div>
                <h4 className="font-bold text-sm">{item.topic}</h4>
                <div className="flex items-center gap-4 text-xs">
                  <span>Current: <strong className="text-yellow-400">{item.current_score}</strong></span>
                  <span>→</span>
                  <span>Target: <strong className="text-emerald-400">{item.target_score}</strong></span>
                </div>
                {item.resources && item.resources.length > 0 && (
                  <div className="pt-2 border-t border-border/40">
                    <p className="text-[11px] text-muted-foreground font-semibold mb-2">Recommended Study Resources:</p>
                    <div className="flex flex-wrap gap-2">
                      {item.resources.map((res, rIdx) => (
                        <a
                          key={rIdx}
                          href={res.url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 text-xs bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 rounded-md px-2.5 py-1 transition-colors"
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
        </div>
      )}
    </div>
  );
}
