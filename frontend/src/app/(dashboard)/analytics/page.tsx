'use client';

import { useUserStats } from '@/hooks/useData';
import { BarChart2, Clock, Loader2, Target, TrendingUp, Trophy, XCircle } from 'lucide-react';
import { motion } from 'framer-motion';
import { Card } from '@/components/ui/card';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';

export const runtime = 'edge';
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
          <h2 className="mb-2 text-xl font-semibold">Unable to Load Analytics</h2>
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
        <PageHeader
          eyebrow="Performance"
          title="Performance Analytics"
          description="Detailed metrics tracking your technical mastery and readiness across all sessions."
        />
      </motion.div>

      {/* The same StatCard the dashboard uses. These were four hand-rolled
          near-copies that had drifted apart from it and from each other. */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard
          label="Total practice time"
          value={`${stats?.hours_practiced ?? 0} hrs`}
          sub="across all sessions"
          icon={<Clock className="h-4 w-4" />}
          color="amber"
        />
        <StatCard
          label="Questions answered"
          value={stats?.total_questions_answered ?? 0}
          sub="all rounds"
          icon={<Target className="h-4 w-4" />}
          color="emerald"
        />
        <StatCard
          label="Highest score"
          value={stats?.best_score ? `${stats.best_score}/100` : '—'}
          sub={stats?.best_score ? 'personal best' : 'complete a session to see'}
          icon={<Trophy className="h-4 w-4" />}
          color="violet"
        />
        <StatCard
          label="Avg. accuracy"
          value={stats?.average_score ? `${stats.average_score}%` : '—'}
          sub={stats?.average_score ? 'across sessions' : 'complete a session to see'}
          icon={<BarChart2 className="h-4 w-4" />}
          color="cyan"
        />
      </div>

      <motion.div variants={fadeUp}>
        <Card className="space-y-3 p-6 text-center">
          <TrendingUp className="mx-auto mb-2 h-10 w-10 text-primary" />
          <h3 className="text-lg font-semibold">Analytics Engine Active</h3>
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            As you complete more mock interviews, detailed score trends, weak-topic heatmaps, and progress predictions will automatically populate here.
          </p>
        </Card>
      </motion.div>
    </motion.div>
  );
}
