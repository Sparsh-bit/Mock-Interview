'use client';

import Link from 'next/link';
import { useTracks } from '@/hooks/useData';
import { BookOpen, CheckCircle2, Code2, Loader2, Play, Sparkles } from 'lucide-react';

export default function TracksPage() {
  const { data: tracks, isLoading } = useTracks();

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Interview Tracks</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Explore corporate-tailored interview tracks designed for real hiring assessments.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {(tracks || []).map((track) => (
            <div
              key={track.id}
              className="glass rounded-2xl border border-border/50 p-6 flex flex-col justify-between hover:border-primary/40 transition-colors"
            >
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-xl bg-primary/10 flex items-center justify-center">
                      <Code2 className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-bold text-base">{track.company.name}</h3>
                      <p className="text-xs text-muted-foreground">{track.name}</p>
                    </div>
                  </div>
                  <span className="badge-medium">Active</span>
                </div>

                <p className="text-sm text-foreground/80 leading-relaxed">
                  {track.description || 'Comprehensive evaluation covering core concepts, system design, and coding principles.'}
                </p>

                <div className="mt-6 grid grid-cols-2 gap-3 text-xs">
                  <div className="rounded-lg bg-surface/50 border border-border/40 p-3">
                    <span className="text-muted-foreground">Duration:</span>
                    <p className="font-semibold mt-0.5">{track.duration_minutes || 45} mins</p>
                  </div>
                  <div className="rounded-lg bg-surface/50 border border-border/40 p-3">
                    <span className="text-muted-foreground">Questions:</span>
                    <p className="font-semibold mt-0.5">{track.question_count} Available</p>
                  </div>
                </div>
              </div>

              <div className="mt-6 pt-4 border-t border-border/40">
                <Link
                  href={`/interview?trackId=${track.id}`}
                  className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm font-bold text-primary-foreground hover:bg-primary/90 transition-all shadow-glow"
                >
                  <Play className="h-4 w-4" /> Start Track Assessment
                </Link>
              </div>
            </div>
          ))}

          {/* Upcoming Track */}
          <div className="glass rounded-2xl border border-border/30 p-6 flex flex-col justify-between opacity-60">
            <div>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-xl bg-muted flex items-center justify-center">
                    <Sparkles className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <h3 className="font-bold text-base">TCS Digital</h3>
                    <p className="text-xs text-muted-foreground">Java & Data Structures</p>
                  </div>
                </div>
                <span className="text-[10px] bg-muted px-2.5 py-0.5 rounded-full font-semibold">Coming Soon</span>
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                TCS Digital recruitment track focusing on advanced algorithmic problem solving and Java ecosystem.
              </p>
            </div>
            <div className="mt-6 pt-4 border-t border-border/40">
              <button disabled className="w-full rounded-xl bg-muted px-4 py-3 text-sm font-bold text-muted-foreground cursor-not-allowed">
                Coming Soon
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
