'use client';

import Link from 'next/link';
import { useUserSessions } from '@/hooks/useData';
import { FileText, Loader2, Play, Calendar, Award } from 'lucide-react';

export default function ReportsListPage() {
  const { data: sessions, isLoading } = useUserSessions(20);

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Interview Performance Reports</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Review detailed AI evaluations, score breakdowns, and recommendations for all your completed sessions.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : !sessions || sessions.length === 0 ? (
        <div className="glass rounded-2xl p-12 border border-border/50 text-center max-w-lg mx-auto">
          <FileText className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
          <h3 className="font-bold text-lg mb-2">No Reports Available Yet</h3>
          <p className="text-sm text-muted-foreground mb-6">
            Complete your first mock interview session to generate a detailed performance report.
          </p>
          <Link
            href="/interview"
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-bold text-primary-foreground hover:bg-primary/90 transition-all shadow-glow"
          >
            <Play className="h-4 w-4" /> Start Interview
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {sessions.map((sess) => (
            <div
              key={sess.id}
              className="glass rounded-xl border border-border/50 p-6 flex flex-col justify-between hover:border-primary/40 transition-colors"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-bold text-primary uppercase">{sess.company_name}</span>
                  <span
                    className={`text-[10px] px-2.5 py-0.5 rounded-full font-semibold border ${
                      sess.status === 'completed'
                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                        : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30'
                    }`}
                  >
                    {sess.status}
                  </span>
                </div>
                <h3 className="font-bold text-base">{sess.track_name}</h3>
                <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5" />
                    {sess.started_at ? new Date(sess.started_at).toLocaleDateString() : 'N/A'}
                  </span>
                  <span>•</span>
                  <span>{sess.questions_asked} Questions</span>
                </div>
              </div>

              <div className="mt-6 pt-4 border-t border-border/40 flex items-center justify-between">
                <div>
                  <p className="text-[10px] text-muted-foreground uppercase">Overall Score</p>
                  <p className="text-xl font-bold text-foreground">
                    {sess.overall_score !== null ? `${sess.overall_score}/100` : '—'}
                  </p>
                </div>
                <Link
                  href={sess.status === 'completed' ? `/report/${sess.id}` : `/session/${sess.id}`}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary px-4 py-2 text-xs font-bold transition-colors"
                >
                  {sess.status === 'completed' ? (
                    <>
                      <FileText className="h-3.5 w-3.5" /> View Report
                    </>
                  ) : (
                    <>
                      <Play className="h-3.5 w-3.5" /> Resume
                    </>
                  )}
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
