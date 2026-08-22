'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { FocusGroup, FocusItem } from '@/components/lightswind-pro/focus-cards';
import { DataError } from '@/components/ui/data-error';
import { useTracks } from '@/hooks/useData';
import { Code2, Loader2, Play, Sparkles } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { PageHeader } from '@/components/ui/page-header';

export const runtime = 'edge';
export default function TracksPage() {
  const { data: tracks, isLoading, error, refetch, isFetching } = useTracks();

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-5xl space-y-8">
      <motion.div variants={fadeUp}>
        <PageHeader
          eyebrow="Practice"
          title="Interview Tracks"
          description="Explore corporate-tailored interview tracks designed for real hiring assessments."
        />
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
        /* Hovering one track dims the others, so a grid stops being a wall and becomes the
           one you are considering. The existing card keeps all of its own markup — the
           wrapper supplies only the focus. */
        <FocusGroup className="grid gap-6 md:grid-cols-2">
          {(tracks || []).map((track) => (
            <FocusItem key={track.id} id={track.id}>
            <motion.div variants={fadeUp}>
              <Card hoverable className="flex h-full flex-col justify-between p-6">
                <div>
                  {/* `min-w-0` down the whole chain, plus `shrink-0` on the icon tile.
                      "Cognizant Technology Solutions" beside a status pill is wider than the
                      248px this card has at 320px, and without the chain the name pushed the
                      pill off the card edge instead of wrapping. */}
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                        <Code2 className="h-5 w-5 text-primary" />
                      </div>
                      <div className="min-w-0">
                        <h3 className="break-words text-base font-semibold">{track.company.name}</h3>
                        <p className="break-words text-xs text-muted-foreground">{track.name}</p>
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
            </FocusItem>
          ))}
        </FocusGroup>
      )}
    </motion.div>
  );
}
