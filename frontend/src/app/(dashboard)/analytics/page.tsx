'use client';

import Link from 'next/link';

import { motion } from 'framer-motion';
import { BarChart2, Clock, Loader2, Play, Target, Trophy } from 'lucide-react';

import { DataError } from '@/components/ui/data-error';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { buttonVariants } from '@/components/ui/button';
import { useUserStats } from '@/hooks/useData';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { scoreBand } from '@/lib/score-bands';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

export default function AnalyticsPage() {
  const { data: stats, isLoading, error, refetch, isFetching } = useUserStats();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-accent-teal" />
      </div>
    );
  }

  if (error) {
    /*
     * DataError, not a hand-rolled panel. This page had its own centred card with an XCircle,
     * its own wording, and NO RETRY BUTTON — so a transient network failure was a dead end
     * with nothing to press. Every other page in the product already uses this component,
     * which offers the retry and distinguishes "we could not load this" from "you have
     * nothing", a confusion that has already cost an incident on the report path.
     */
    return (
      <DataError
        title="Could not load your analytics"
        error={error}
        onRetry={() => refetch()}
        retrying={isFetching}
      />
    );
  }

  const attempted = stats?.total_sessions ?? 0;
  const completed = stats?.completed_sessions ?? 0;
  const avg = stats?.average_score ?? null;
  const band = avg !== null ? scoreBand(avg) : null;

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.08)}
      className="mx-auto max-w-5xl space-y-8"
    >
      <motion.div variants={fadeUp}>
        <PageHeader
          eyebrow="Performance"
          title="Performance Analytics"
          description="What your rounds add up to. Every figure here is counted from sessions you actually finished."
        />
      </motion.div>

      {/*
        * THE AVERAGE IS THE SUBJECT OF THIS PAGE, so it is the lit element and the four tiles
        * below it are supporting detail. Previously all five were the same white card, and the
        * page's answer to "how am I doing" was buried in the fourth tile of a symmetric row,
        * labelled "Avg. accuracy" — a different claim from what the number is. It is a
        * composite score out of 100, not a proportion of correct answers.
        *
        * It renders as an empty-state prompt rather than a zero when there is nothing yet.
        * "0/100" and "you have not sat a round yet" are opposite messages, and printing the
        * first when the second is true tells somebody they failed something they never took.
        */}
      <motion.div variants={fadeUp}>
        <div className="lit rounded-2xl p-6 sm:p-7">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Average score
          </p>

          {avg !== null && band ? (
            <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-3">
              <p className="font-mono text-[44px] font-bold leading-[0.85] tracking-[-0.04em] tabular-nums sm:text-[52px]">
                {avg}
                <span className="ml-1 text-base font-medium text-muted-foreground">/100</span>
              </p>
              <div className="min-w-0 flex-1">
                {/* The band's own word, in the band's own colour — the same pairing the report
                    prints, from lib/score-bands. A score labelled "Good" here and coloured like
                    a 51 on its own report page is how a candidate stops trusting either. */}
                <span
                  className={cn(
                    'inline-block rounded-full px-2.5 py-1 text-[11px] font-semibold',
                    band.chip,
                  )}
                >
                  {band.label}
                </span>
                <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
                  Across{' '}
                  <span className="font-mono tabular-nums text-foreground">{completed}</span>{' '}
                  completed {completed === 1 ? 'round' : 'rounds'}
                  {stats?.best_score != null && (
                    <>
                      {' '}· best{' '}
                      <span className="font-mono tabular-nums text-foreground">
                        {stats.best_score}
                      </span>
                    </>
                  )}
                </p>
              </div>
            </div>
          ) : (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-lg font-medium tracking-tight">
                  {attempted > 0 ? 'Nothing scored yet' : "You haven't taken the seat yet"}
                </p>
                <p className="mt-1 max-w-md text-sm text-muted-foreground">
                  {attempted > 0
                    ? 'You have started a round but not finished one. A score appears once an interview is completed and reported.'
                    : 'Sit one interview and this page fills in: your average, your best, and how the two are moving.'}
                </p>
              </div>
              <Link href="/interview" className={cn(buttonVariants({ size: 'md' }), 'shrink-0')}>
                <Play className="h-4 w-4" />
                Start interview
              </Link>
            </div>
          )}
        </div>
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
          value={stats?.best_score != null ? `${stats.best_score}/100` : '—'}
          sub={stats?.best_score != null ? 'personal best' : 'complete a session to see'}
          icon={<Trophy className="h-4 w-4" />}
          color="violet"
        />
        {/* WAS "Avg. accuracy", showing the average score with a % appended. Three things
            wrong in one tile: it duplicated the number now lit at the top of the page,
            "accuracy" claims a proportion of correct answers when the figure is a composite
            score, and the % turned a score into a percentage. This says something the other
            tiles do not. */}
        <StatCard
          label="Rounds completed"
          value={`${completed}`}
          sub={attempted > completed ? `${attempted - completed} still open` : 'finished and reported'}
          icon={<BarChart2 className="h-4 w-4" />}
          color="cyan"
        />
      </div>

      {/*
        * WHAT USED TO BE HERE: a centred card headed "Analytics Engine Active" promising
        * "score trends, weak-topic heatmaps, and progress predictions" that would "populate
        * automatically". None of those exist. DESIGN-RULES' last non-negotiable is that the
        * interface makes no claim the code cannot support, and a permanent notice advertising
        * three unbuilt features is the clearest possible breach — it also made the real
        * numbers above look like a placeholder for the good version.
        *
        * Nothing replaces it. A page that shows four true figures and stops is finished; a
        * page that apologises for its own size is not.
        */}
    </motion.div>
  );
}
