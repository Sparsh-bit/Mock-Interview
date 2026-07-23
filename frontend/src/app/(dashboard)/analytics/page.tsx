'use client';

import { useUserStats } from '@/hooks/useData';
import { BarChart2, Clock, Loader2, Target, TrendingUp, Trophy, XCircle } from 'lucide-react';
import { motion } from 'framer-motion';
import { Card } from '@/components/ui/card';
import { fadeUp, staggerContainer } from '@/lib/motion';

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
      <motion.div initial="hidden" animate="visible" variants={fadeUp} className="mx-auto mt-12 max-w-2xl">
        <Card className="border-destructive/20 p-8 text-center">
          <XCircle className="mx-auto mb-4 h-12 w-12 text-destructive" />
          <h2 className="mb-2 text-xl font-bold">Unable to Load Analytics</h2>
          <p className="text-sm text-muted-foreground">
            Could not load your performance statistics. Please try again later.
          </p>
        </Card>
      </motion.div>
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-5xl space-y-8">
      <motion.div variants={fadeUp}>
        <h1 className="text-2xl font-bold tracking-tight">Performance Analytics</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Detailed metrics tracking your technical mastery and readiness across all sessions.
        </p>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <motion.div variants={fadeUp}>
          <Card hoverable className="p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase text-muted-foreground">Total Practice Time</span>
              <Clock className="h-4 w-4 text-accent-violet" />
            </div>
            <p className="text-3xl font-bold tracking-tight">{stats?.hours_practiced ?? 0} hrs</p>
          </Card>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card hoverable className="p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase text-muted-foreground">Questions Answered</span>
              <Target className="h-4 w-4 text-accent-emerald" />
            </div>
            <p className="text-3xl font-bold tracking-tight">{stats?.total_questions_answered ?? 0}</p>
          </Card>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card hoverable className="p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase text-muted-foreground">Highest Score</span>
              <Trophy className="h-4 w-4 text-amber-600" />
            </div>
            <p className="text-3xl font-bold tracking-tight">{stats?.best_score ? `${stats.best_score}/100` : '—'}</p>
          </Card>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Card hoverable className="p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase text-muted-foreground">Avg. Accuracy</span>
              <BarChart2 className="h-4 w-4 text-primary" />
            </div>
            <p className="text-3xl font-bold tracking-tight">{stats?.average_score ? `${stats.average_score}%` : '—'}</p>
          </Card>
        </motion.div>
      </div>

      <motion.div variants={fadeUp}>
        <Card className="hero-wash space-y-3 p-8 text-center">
          <TrendingUp className="mx-auto mb-2 h-10 w-10 text-primary" />
          <h3 className="text-lg font-bold">Analytics Engine Active</h3>
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            As you complete more mock interviews, detailed score trends, weak-topic heatmaps, and progress predictions will automatically populate here.
          </p>
        </Card>
      </motion.div>
    </motion.div>
  );
}
