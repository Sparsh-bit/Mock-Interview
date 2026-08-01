'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { DataError } from '@/components/ui/data-error';
import { useTracks } from '@/hooks/useData';
import { Code2, Loader2, Play, Sparkles } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';
export default function TracksPage() {
  const { data: tracks, isLoading, error, refetch, isFetching } = useTracks();

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-5xl space-y-8">
      <motion.div variants={fadeUp}>
        <h1 className="text-2xl font-bold tracking-tight">Interview Tracks</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Explore corporate-tailored interview tracks designed for real hiring assessments.
        </p>
      </motion.div>

      {error || (!isLoading && !tracks?.length) ? (
        <DataError
          title="Interview tracks unavailable"
          error={error}
          onRetry={() => refetch()}
          retrying={isFetching}
        />
      ) : isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {(tracks || []).map((track) => (
            <motion.div key={track.id} variants={fadeUp}>
              <Card hoverable className="flex h-full flex-col justify-between p-6">
                <div>
                  <div className="mb-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
                        <Code2 className="h-5 w-5 text-primary" />
                      </div>
                      <div>
                        <h3 className="text-base font-bold">{track.company.name}</h3>
                        <p className="text-xs text-muted-foreground">{track.name}</p>
                      </div>
                    </div>
                    <Badge variant="warning">Active</Badge>
                  </div>

                  <p className="text-sm leading-relaxed text-foreground/80">
                    {track.description || 'Comprehensive evaluation covering core concepts, system design, and coding principles.'}
                  </p>

                  <div className="mt-6 grid grid-cols-2 gap-3 text-xs">
                    <div className="rounded-xl border border-border/40 bg-surface/50 p-3">
                      <span className="text-muted-foreground">Duration:</span>
                      <p className="mt-0.5 font-semibold">{track.duration_minutes || 45} mins</p>
                    </div>
                    <div className="rounded-xl border border-border/40 bg-surface/50 p-3">
                      <span className="text-muted-foreground">Questions:</span>
                      <p className="mt-0.5 font-semibold">{track.interview_question_count} Asked</p>
                    </div>
                  </div>
                </div>

                <div className="mt-6 border-t border-border/40 pt-4">
                  <Link
                    href={`/interview?trackId=${track.id}`}
                    className={cn(buttonVariants({ size: 'md' }), 'w-full')}
                  >
                    <Play className="h-4 w-4" /> Start Track Assessment
                  </Link>
                </div>
              </Card>
            </motion.div>
          ))}

        </div>
      )}
    </motion.div>
  );
}
