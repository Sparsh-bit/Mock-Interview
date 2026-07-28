'use client';

import Link from 'next/link';
import {
  ArrowRight,
  BarChart2,
  BookOpen,
  CheckCircle2,
  Clock,
  Play,
  TrendingUp,
  Loader2,
  FileText,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useUserStats, useUserSessions, useTracks } from '@/hooks/useData';
import { useAuth } from '@/hooks/useAuth';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { IconTile, type IconTileProps } from '@/components/ui/icon-tile';
import { FeatureNudge } from '@/components/FeatureNudge';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

interface StatCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  sub?: string;
  color?: IconTileProps['color'];
}

function StatCard({ label, value, icon, sub, color = 'blue' }: StatCardProps) {
  return (
    <motion.div variants={fadeUp}>
      <Card hoverable className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</span>
          <IconTile color={color} size="sm">{icon}</IconTile>
        </div>
        <p className="text-3xl font-semibold tracking-tight">{value}</p>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </Card>
    </motion.div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { data: stats, isLoading: statsLoading } = useUserStats();
  const { data: sessions, isLoading: sessionsLoading } = useUserSessions(5);
  const { data: tracks, isLoading: tracksLoading } = useTracks();

  const displayName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'there';

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.08)}
      className="mx-auto max-w-6xl space-y-8"
    >
      {/* Welcome banner */}
      <motion.div variants={fadeUp} className="hero-wash glass relative overflow-hidden rounded-2xl border-primary/20 p-8">
        <div className="relative">
          <h1 className="text-2xl font-bold tracking-tight">Welcome back, {displayName} 👋</h1>
          <p className="mt-1.5 max-w-lg text-sm text-muted-foreground">
            {!stats || stats.total_sessions === 0
              ? 'Start your first mock interview and see exactly where you stand.'
              : `You have completed ${stats.completed_sessions} of ${stats.total_sessions} total sessions. Keep going!`}
          </p>
          <Link href="/interview" className={cn(buttonVariants({ size: 'md' }), 'mt-5 w-fit')}>
            <Play className="h-4 w-4" />
            Start Interview
          </Link>
        </div>
      </motion.div>

      {/* Nudge to try a round they haven't done yet (communication / GD) */}
      <motion.div variants={fadeUp}>
        <FeatureNudge />
      </motion.div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Total Sessions"
          value={statsLoading ? '…' : (stats?.total_sessions ? String(stats.total_sessions) : '0')}
          icon={<BookOpen className="h-4 w-4" />}
          sub="all time"
          color="blue"
        />
        <StatCard
          label="Average Score"
          value={statsLoading ? '…' : (stats?.average_score ? `${stats.average_score}/100` : '—')}
          icon={<BarChart2 className="h-4 w-4" />}
          sub={stats?.average_score ? 'across all sessions' : 'complete a session to see'}
          color="cyan"
        />
        <StatCard
          label="Hours Practiced"
          value={statsLoading ? '…' : `${stats?.hours_practiced ?? 0}h`}
          icon={<Clock className="h-4 w-4" />}
          sub="total time"
          color="violet"
        />
        <StatCard
          label="Day Streak"
          value={statsLoading ? '…' : `${stats?.streak_days ?? 0}🔥`}
          icon={<TrendingUp className="h-4 w-4" />}
          sub="keep it up"
          color="amber"
        />
      </div>

      {/* Main content grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Recent sessions — left 2/3 */}
        <motion.div variants={fadeUp} className="lg:col-span-2">
          <Card className="p-6">
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Recent Sessions</h2>
              {sessions && sessions.length > 0 && (
                <Link href="/report" className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-primary">
                  View reports <ArrowRight className="h-3 w-3" />
                </Link>
              )}
            </div>

            {sessionsLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : !sessions || sessions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="mb-4 rounded-full bg-secondary p-4">
                  <BookOpen className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-sm font-medium">No sessions yet</p>
                <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                  Complete your first mock interview to see your history and track your progress here.
                </p>
                <Link href="/interview" className={cn(buttonVariants({ variant: 'secondary', size: 'sm' }), 'mt-4')}>
                  <Play className="h-3.5 w-3.5" />
                  Start your first interview
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {sessions.map((sess) => (
                  <div
                    key={sess.id}
                    className="flex items-center justify-between rounded-xl border border-border/50 bg-surface/50 p-4 transition-colors hover:bg-surface"
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold">{sess.company_name} — {sess.track_name}</span>
                        <Badge variant={sess.status === 'completed' ? 'success' : 'warning'}>{sess.status}</Badge>
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        {sess.questions_asked} questions asked • {sess.started_at ? new Date(sess.started_at).toLocaleDateString() : 'Recent'}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      {sess.overall_score !== null && (
                        <span className="text-sm font-bold text-primary">{sess.overall_score}/100</span>
                      )}
                      <Link
                        href={sess.status === 'completed' ? `/report/${sess.id}` : `/session/${sess.id}`}
                        className="p-2 text-muted-foreground transition-colors hover:text-foreground"
                        title={sess.status === 'completed' ? 'View Report' : 'Resume Session'}
                      >
                        {sess.status === 'completed' ? <FileText className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </motion.div>

        {/* Tracks — right 1/3 */}
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <h2 className="mb-4 text-sm font-semibold">Available Tracks</h2>
            {tracksLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
              </div>
            ) : (
              <div className="space-y-3">
                {(tracks || []).map((track) => (
                  <Link
                    key={track.id}
                    href={`/interview?trackId=${track.id}`}
                    className="ease-out-expo block rounded-xl border border-border/70 bg-surface p-3 transition-colors hover:border-primary/40"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold">{track.company.name}</p>
                        <p className="mt-0.5 truncate text-[10px] text-muted-foreground">{track.name}</p>
                      </div>
                      <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-emerald-600" />
                    </div>
                    <p className="mt-1.5 text-[10px] text-muted-foreground">{track.interview_question_count} questions per interview</p>
                  </Link>
                ))}

                {(!tracks || tracks.length === 0) && (
                  <div className="rounded-xl border border-border/40 bg-surface/50 p-3 text-center">
                    <p className="text-xs text-muted-foreground">Cognizant Java FSE</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">200+ questions</p>
                  </div>
                )}
              </div>
            )}

            <Link href="/interview" className={cn(buttonVariants({ size: 'md' }), 'mt-4 w-full')}>
              <Play className="h-3.5 w-3.5" />
              Start Mock Interview
            </Link>
          </Card>
        </motion.div>
      </div>
    </motion.div>
  );
}
