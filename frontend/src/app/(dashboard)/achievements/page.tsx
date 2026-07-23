'use client';

import { useUserStats } from '@/hooks/useData';
import { Award, CheckCircle2, Flame, Lock, ShieldCheck, Star, Zap } from 'lucide-react';

export default function AchievementsPage() {
  const { data: stats } = useUserStats();

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

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Achievements & Milestones</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Unlock badges and track your milestone achievements as you practice.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {achievements.map((ach) => {
          const Icon = ach.icon;
          return (
            <div
              key={ach.id}
              className={`glass rounded-2xl border p-6 flex items-start gap-4 transition-all ${
                ach.unlocked
                  ? 'border-emerald-500/30 bg-emerald-500/5'
                  : 'border-border/40 opacity-50'
              }`}
            >
              <div
                className={`h-12 w-12 rounded-xl flex items-center justify-center flex-shrink-0 ${
                  ach.unlocked ? 'bg-emerald-500/20 text-emerald-400' : 'bg-muted text-muted-foreground'
                }`}
              >
                {ach.unlocked ? <Icon className="h-6 w-6" /> : <Lock className="h-6 w-6" />}
              </div>
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-bold text-base">{ach.title}</h3>
                  {ach.unlocked && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{ach.description}</p>
                <p className="text-[10px] font-semibold uppercase tracking-wider mt-2">
                  {ach.unlocked ? (
                    <span className="text-emerald-400">Unlocked</span>
                  ) : (
                    <span className="text-muted-foreground">Locked</span>
                  )}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
