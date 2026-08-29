'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { FocusGroup, FocusItem } from '@/components/lightswind-pro/focus-cards';
import { DataError } from '@/components/ui/data-error';
import { useTracks } from '@/hooks/useData';
import { Clock, Code2, Loader2, Play } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { buttonVariants } from '@/components/ui/button';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { PageHeader } from '@/components/ui/page-header';

export const runtime = 'edge';

/**
 * HOW HARD IS THIS SEAT — the heat scale from docs/DESIGN-LANGUAGE §2.
 *
 * Heat means difficulty and nothing else in this product: teal is a warm-up, amber is the real
 * thing, coral is the round that decides it. It is deliberately NOT the emerald/coral pair used
 * for pass and fail — a colour that means two things means nothing, and "hard" is not "bad".
 *
 * This replaced a `<Badge variant="warning">Active</Badge>` that appeared on every card without
 * exception. A badge that is always the same is not a badge; it is a decoration with a border,
 * and it was occupying the one slot on the card where a real distinction could live.
 *
 * Every class is written out in full rather than assembled from the level name: Tailwind
 * compiles the classes it can literally see, so an interpolated one survives dev and vanishes
 * from the production build with no error anywhere.
 *
 * Falls back to no chip rather than guessing, so a difficulty the backend adds later renders
 * as an honest unlabelled track instead of being silently miscoloured.
 */
const HEAT: Record<string, { label: string; chip: string; dot: string }> = {
  easy: {
    label: 'Warm-up',
    chip: 'bg-accent-teal-soft text-accent-teal-ink',
    dot: 'bg-accent-teal',
  },
  medium: {
    label: 'Standard',
    chip: 'bg-accent-amber-soft text-accent-amber-ink',
    dot: 'bg-accent-amber',
  },
  hard: {
    label: 'Runs hot',
    chip: 'bg-accent-coral-soft text-accent-coral-ink',
    dot: 'bg-accent-coral',
  },
};

export default function TracksPage() {
  const { data: tracks, isLoading, error, refetch, isFetching } = useTracks();

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.08)}
      className="mx-auto max-w-5xl space-y-8"
    >
      <motion.div variants={fadeUp}>
        <PageHeader
          eyebrow="Practice"
          title="Interview Tracks"
          description="Every panel we can sit you in front of. Pick the one you are actually being interviewed by."
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
          <Loader2 className="h-8 w-8 animate-spin text-accent-indigo" />
        </div>
      ) : (
        /* Hovering one track dims the others, so a grid stops being a wall and becomes the
           one you are considering. The existing card keeps all of its own markup — the
           wrapper supplies only the focus. */
        <FocusGroup className="grid gap-5 md:grid-cols-2">
          {(tracks || []).map((track, i) => {
            const heat = HEAT[track.difficulty_level?.toLowerCase()] ?? null;

            /*
             * THE FIRST TRACK IS THE LIT ONE, AND IT SPANS BOTH COLUMNS.
             *
             * Two problems solved by one decision. The page was a perfectly symmetric
             * two-column grid of identical cards, which DESIGN-RULES names as a tell — nobody
             * laying this out by hand lands on twelve equal rectangles. And it had no subject:
             * every track looked exactly as recommended as every other, so the page gave no
             * answer to "which one should I take?".
             *
             * The backend returns tracks in its own considered order, so the first is the one
             * to lead with. Lit and full-width, it reads as the recommendation without a
             * "Recommended" sticker claiming something we have not measured.
             */
            const lead = i === 0;

            return (
              <FocusItem
                key={track.id}
                id={track.id}
                className={lead ? 'md:col-span-2' : undefined}
              >
                <motion.div variants={fadeUp} className="h-full">
                  <Card
                    hoverable={!lead}
                    padding="none"
                    variant={lead ? 'outline' : 'flat'}
                    className={cn(
                      'flex h-full flex-col justify-between p-6',
                      lead && 'lit lit-hover',
                    )}
                  >
                    <div>
                      {/* `min-w-0` down the whole chain, plus `shrink-0` on the icon tile.
                          "Cognizant Technology Solutions" beside a status pill is wider than
                          the 248px this card has at 320px, and without the chain the name
                          pushed the pill off the card edge instead of wrapping. */}
                      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-indigo-soft">
                            <Code2 className="h-5 w-5 text-accent-indigo-ink" />
                          </div>
                          <div className="min-w-0">
                            <h3
                              className={cn(
                                'break-words font-semibold',
                                lead ? 'text-lg' : 'text-base',
                              )}
                            >
                              {track.company.name}
                            </h3>
                            <p className="break-words text-xs text-muted-foreground">
                              {track.name}
                            </p>
                          </div>
                        </div>

                        {heat && (
                          <span
                            className={cn(
                              'flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium',
                              heat.chip,
                            )}
                          >
                            <span
                              aria-hidden
                              className={cn('h-1.5 w-1.5 rounded-full', heat.dot)}
                            />
                            {heat.label}
                          </span>
                        )}
                      </div>

                      {/* The old fallback read "Comprehensive evaluation covering core
                          concepts, system design, and coding principles" — a sentence
                          DESIGN-RULES bans by name, and one that claimed system design for
                          tracks that do not test it. Better to say the true, small thing. */}
                      <p className="max-w-2xl text-sm leading-relaxed text-foreground/80">
                        {track.description ||
                          `${track.interview_question_count} questions, asked the way ${track.company.name} asks them.`}
                      </p>

                      {/*
                        * A ROW OF FACTS, NOT TWO BOXES. These were two bordered tiles in their
                        * own nested grid — four borders to carry eleven characters. Set as a
                        * plain line, the numbers are easier to compare between cards, which is
                        * the only thing anybody does with them.
                        */}
                      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
                        <span className="flex items-center gap-1.5">
                          <Clock className="h-3.5 w-3.5 shrink-0 text-accent-amber" />
                          <span className="font-mono tabular-nums text-foreground">
                            {track.duration_minutes || 45}
                          </span>
                          min
                        </span>
                        <span className="flex items-center gap-1.5">
                          <Play className="h-3.5 w-3.5 shrink-0 text-accent-indigo" />
                          <span className="font-mono tabular-nums text-foreground">
                            {track.interview_question_count}
                          </span>
                          questions
                        </span>
                      </div>
                    </div>

                    <div className="mt-6 border-t border-border/50 pt-4">
                      <Link
                        href={`/interview?trackId=${track.id}`}
                        className={cn(
                          buttonVariants({ size: 'md', variant: lead ? 'primary' : 'secondary' }),
                          lead ? 'w-full sm:w-auto' : 'w-full',
                        )}
                      >
                        <Play className="h-4 w-4" /> Start this track
                      </Link>
                    </div>
                  </Card>
                </motion.div>
              </FocusItem>
            );
          })}
        </FocusGroup>
      )}
    </motion.div>
  );
}
