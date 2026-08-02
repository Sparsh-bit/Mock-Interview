'use client';

import { useUserStats } from '@/hooks/useData';
import { Award, CheckCircle2, Lock, ShieldCheck, Star, Zap } from 'lucide-react';
import { motion } from 'framer-motion';
import { Card } from '@/components/ui/card';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { DataError } from '@/components/ui/data-error';
import { PageHeader } from '@/components/ui/page-header';

export const runtime = 'edge';
export default function AchievementsPage() {
  const { data: stats, error, refetch, isFetching } = useUserStats();

  const achievements = [
    {
      id: 'first_step',
      title: 'First Step',
      description: 'Completed your very first mock interview round',
      icon: Zap,
      unlocked: (stats?.completed_sessions ?? 0) >= 1,
    },
    {
      id: 'java_master',
      title: 'Java Practitioner',
      description: 'Answered at least 5 technical questions',
      icon: Star,
      unlocked: (stats?.total_questions_answered ?? 0) >= 5,
    },
    {
      id: 'high_scorer',
      title: 'High Scorer',
      description: 'Achieved an overall session score of 80/100 or higher',
      icon: Award,
      unlocked: (stats?.best_score ?? 0) >= 80,
    },
    {
      id: 'marathon',
      title: 'Interview Veteran',
      description: 'Completed 5 full mock interview sessions',
      icon: ShieldCheck,
      unlocked: (stats?.completed_sessions ?? 0) >= 5,
    },
  ];

  // Without this every achievement renders as locked, which reads as "you have
  // achieved nothing" rather than "we could not check".
  if (error) {
    return (
      <DataError
        title="Could not load your achievements"
        error={error}
        onRetry={() => refetch()}
        retrying={isFetching}
      />
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-5xl space-y-8">
      <motion.div variants={fadeUp}>
        <PageHeader
          eyebrow="Progress"
          title="Achievements & Milestones"
          description="Unlock badges and track your milestone achievements as you practice."
        />
      </motion.div>

      <div className="grid gap-4 md:grid-cols-2">
        {achievements.map((ach) => {
          const Icon = ach.icon;
          return (
            <motion.div key={ach.id} variants={fadeUp}>
              <Card
                hoverable={ach.unlocked}
                className={`flex items-start gap-4 p-6 ${
                  ach.unlocked ? 'border-accent-emerald/30 bg-accent-emerald/5' : 'border-border/40 opacity-50'
                }`}
              >
                <div
                  className={`flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl ${
                    ach.unlocked ? 'bg-accent-emerald/20 text-accent-emerald-ink' : 'bg-secondary text-muted-foreground'
                  }`}
                >
                  {ach.unlocked ? <Icon className="h-6 w-6" /> : <Lock className="h-6 w-6" />}
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold">{ach.title}</h3>
                    {ach.unlocked && <CheckCircle2 className="h-4 w-4 text-accent-emerald-ink" />}
                  </div>
                  <p className="text-xs leading-relaxed text-muted-foreground">{ach.description}</p>
                  <p className="mt-2 text-[10px] font-semibold uppercase tracking-wider">
                    {ach.unlocked ? (
                      <span className="text-accent-emerald-ink">Unlocked</span>
                    ) : (
                      <span className="text-muted-foreground">Locked</span>
                    )}
                  </p>
                </div>
              </Card>
            </motion.div>
          );
        })}
      </div>
    </motion.div>
  );
}
