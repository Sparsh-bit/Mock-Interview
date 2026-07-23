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
import { useUserStats, useUserSessions, useTracks } from '@/hooks/useData';
import { useAuth } from '@/hooks/useAuth';

interface StatCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  sub?: string;
  color?: string;
}

function StatCard({ label, value, icon, sub, color = 'text-primary' }: StatCardProps) {
  return (
    <div className="stat-card">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
        <div className={`${color} opacity-70`}>{icon}</div>
      </div>
      <p className="text-3xl font-bold">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { data: stats, isLoading: statsLoading } = useUserStats();
  const { data: sessions, isLoading: sessionsLoading } = useUserSessions(5);
  const { data: tracks, isLoading: tracksLoading } = useTracks();

  const displayName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'there';

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Welcome banner */}
      <div className="glass rounded-xl border border-primary/20 p-6 relative overflow-hidden">
        <div className="pointer-events-none absolute right-0 top-0 h-full w-64 bg-gradient-radial from-primary/10 to-transparent" />
        <div className="relative">
          <h1 className="text-2xl font-bold">Welcome back, {displayName} 👋</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {!stats || stats.total_sessions === 0
              ? 'Start your first mock interview and see exactly where you stand.'
              : `You have completed ${stats.completed_sessions} of ${stats.total_sessions} total sessions. Keep going!`}
          </p>
          <Link
            href="/interview"
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-all shadow-glow"
          >
            <Play className="h-4 w-4" />
            Start Interview
          </Link>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Total Sessions"
          value={statsLoading ? '...' : (stats?.total_sessions ? String(stats.total_sessions) : '0')}
          icon={<BookOpen className="h-4 w-4" />}
          sub="all time"
        />
        <StatCard
          label="Average Score"
          value={statsLoading ? '...' : (stats?.average_score ? `${stats.average_score}/100` : '—')}
          icon={<BarChart2 className="h-4 w-4" />}
          sub={stats?.average_score ? 'across all sessions' : 'complete a session to see'}
          color="text-blue-400"
        />
        <StatCard
          label="Hours Practiced"
          value={statsLoading ? '...' : `${stats?.hours_practiced ?? 0}h`}
          icon={<Clock className="h-4 w-4" />}
          sub="total time"
          color="text-purple-400"
        />
        <StatCard
          label="Day Streak"
          value={statsLoading ? '...' : `${stats?.streak_days ?? 0}🔥`}
          icon={<TrendingUp className="h-4 w-4" />}
          sub="keep it up"
          color="text-orange-400"
        />
      </div>

      {/* Main content grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Recent sessions — left 2/3 */}
        <div className="lg:col-span-2 glass rounded-xl border border-border/50 p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-sm font-semibold">Recent Sessions</h2>
            {sessions && sessions.length > 0 && (
              <Link href="/report" className="text-xs text-muted-foreground hover:text-primary transition-colors flex items-center gap-1">
                View reports <ArrowRight className="h-3 w-3" />
              </Link>
            )}
          </div>

          {sessionsLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : !sessions || sessions.length === 0 ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="mb-4 rounded-full bg-muted/50 p-4">
                <BookOpen className="h-6 w-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No sessions yet</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                Complete your first mock interview to see your history and track your progress here.
              </p>
              <Link
                href="/interview"
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary/10 px-4 py-2 text-xs font-medium text-primary hover:bg-primary/20 transition-colors"
              >
                <Play className="h-3.5 w-3.5" />
                Start your first interview
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              {sessions.map((sess) => (
                <div
                  key={sess.id}
                  className="flex items-center justify-between p-4 rounded-lg border border-border/50 bg-surface/50 hover:bg-surface transition-colors"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold">{sess.company_name} — {sess.track_name}</span>
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                          sess.status === 'completed'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
                        }`}
                      >
                        {sess.status}
                      </span>
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      {sess.questions_asked} questions asked • {sess.started_at ? new Date(sess.started_at).toLocaleDateString() : 'Recent'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {sess.overall_score !== null && (
                      <span className="text-sm font-bold text-primary">
                        {sess.overall_score}/100
                      </span>
                    )}
                    <Link
                      href={sess.status === 'completed' ? `/report/${sess.id}` : `/session/${sess.id}`}
                      className="p-2 text-muted-foreground hover:text-foreground transition-colors"
                      title={sess.status === 'completed' ? 'View Report' : 'Resume Session'}
                    >
                      {sess.status === 'completed' ? <FileText className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tracks — right 1/3 */}
        <div className="glass rounded-xl border border-border/50 p-6">
          <h2 className="text-sm font-semibold mb-4">Available Tracks</h2>
          {tracksLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
            </div>
          ) : (
            <div className="space-y-3">
              {(tracks || []).map((track) => (
                <Link
                  key={track.id}
                  href="/interview"
                  className="block rounded-lg border border-border/80 bg-surface hover:border-primary/40 p-3 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold truncate">{track.company.name}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5 truncate">{track.name}</p>
                    </div>
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                  </div>
                  <p className="mt-1.5 text-[10px] text-muted-foreground">{track.question_count} questions available</p>
                </Link>
              ))}

              {(!tracks || tracks.length === 0) && (
                <div className="rounded-lg border border-border/40 bg-surface/50 p-3 text-center">
                  <p className="text-xs text-muted-foreground">Cognizant Java FSE</p>
                  <p className="text-[10px] text-muted-foreground mt-1">200+ questions</p>
                </div>
              )}
            </div>
          )}

          <Link
            href="/interview"
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-all shadow-glow"
          >
            <Play className="h-3.5 w-3.5" />
            Start Mock Interview
          </Link>
        </div>
      </div>
    </div>
  );
}
