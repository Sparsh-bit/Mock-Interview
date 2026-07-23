'use client';

import { useUserStats } from '@/hooks/useData';
import { BarChart2, BookOpen, Clock, Loader2, Target, TrendingUp, Trophy, XCircle } from 'lucide-react';

export default function AnalyticsPage() {
  const { data: stats, isLoading, error } = useUserStats();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto mt-12 glass rounded-2xl p-8 border border-destructive/20 text-center">
        <XCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
        <h2 className="text-xl font-bold mb-2">Unable to Load Analytics</h2>
        <p className="text-sm text-muted-foreground">
          Could not load your performance statistics. Please try again later.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Performance Analytics</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Detailed metrics tracking your technical mastery and readiness across all sessions.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="glass rounded-xl p-5 border border-border/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-muted-foreground uppercase font-semibold">Total Practice Time</span>
            <Clock className="h-4 w-4 text-purple-400" />
          </div>
          <p className="text-3xl font-bold">{stats?.hours_practiced ?? 0} hrs</p>
        </div>

        <div className="glass rounded-xl p-5 border border-border/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-muted-foreground uppercase font-semibold">Questions Answered</span>
            <Target className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="text-3xl font-bold">{stats?.total_questions_answered ?? 0}</p>
        </div>

        <div className="glass rounded-xl p-5 border border-border/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-muted-foreground uppercase font-semibold">Highest Score</span>
            <Trophy className="h-4 w-4 text-yellow-400" />
          </div>
          <p className="text-3xl font-bold">{stats?.best_score ? `${stats.best_score}/100` : '—'}</p>
        </div>

        <div className="glass rounded-xl p-5 border border-border/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-muted-foreground uppercase font-semibold">Avg. Accuracy</span>
            <BarChart2 className="h-4 w-4 text-blue-400" />
          </div>
          <p className="text-3xl font-bold">{stats?.average_score ? `${stats.average_score}%` : '—'}</p>
        </div>
      </div>

      <div className="glass rounded-2xl border border-border/50 p-8 text-center space-y-3">
        <TrendingUp className="h-10 w-10 text-primary mx-auto mb-2" />
        <h3 className="text-lg font-bold">Analytics Engine Active</h3>
        <p className="text-sm text-muted-foreground max-w-md mx-auto">
          As you complete more mock interviews, detailed score trends, weak-topic heatmaps, and progress predictions will automatically populate here.
        </p>
      </div>
    </div>
  );
}
