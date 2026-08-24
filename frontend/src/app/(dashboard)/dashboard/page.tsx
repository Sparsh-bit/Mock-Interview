'use client';

import Link from 'next/link';
import { ArrowRight, BarChart2, BookOpen, CheckCircle2, Clock, FileText, Loader2, Play, Plus, TrendingUp } from 'lucide-react';
import { motion } from 'framer-motion';
import { FocusGroup, FocusItem } from '@/components/lightswind-pro/focus-cards';
import { useProgress, useTracks, useUserSessions, useUserStats } from '@/hooks/useData';
import { useAuth } from '@/hooks/useAuth';
import { useCandidateName } from '@/hooks/useCandidateName';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { IconTile, type IconTileProps } from '@/components/ui/icon-tile';
import { PromoBanner } from '@/components/PromoBanner';
import { NudgeDeck } from '@/components/dashboard/NudgeDeck';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { DataError } from '@/components/ui/data-error';
import { StatCard } from '@/components/ui/stat-card';
import { PageHeader } from '@/components/ui/page-header';
import { CreditMeter } from '@/components/billing/CreditMeter';

export const runtime = 'edge';

export default function DashboardPage() {
  const { user } = useAuth();
  const { data: stats, isLoading: statsLoading, error: statsError, refetch: refetchStats, isFetching: statsFetching } = useUserStats();
  const { data: sessions, isLoading: sessionsLoading } = useUserSessions(5);
  const { data: tracks, isLoading: tracksLoading } = useTracks();

  const { greeting: displayName } = useCandidateName();

  // Stats failing is NOT the same as stats being zero. Rendering "0 interviews,
  // 0% average" when the request errored tells the candidate they have done
  // nothing, which is both wrong and demoralising.
  if (statsError) {
    return (
      <DataError
        title="Could not load your dashboard"
        error={statsError}
        onRetry={() => refetchStats()}
        retrying={statsFetching}
      />
    );
  }

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.08)}
      className="mx-auto max-w-6xl space-y-8"
    >
      {/* Welcome banner */}
      {/* A title block, not a hero banner. A glass panel on a gradient wash with
          an emoji was the most template-looking element in the app; a macOS window
          opens with a title and a rule. */}
      <motion.div variants={fadeUp} className="border-b border-border pb-6">
        <PageHeader
          eyebrow="Overview"
          title={`Welcome back, ${displayName}`}
          description={
            !stats || stats.total_sessions === 0
              ? 'Start your first mock interview and see exactly where you stand.'
              : `You have completed ${stats.completed_sessions} of ${stats.total_sessions} total sessions. Keep going!`
          }
          actions={
            /* TWO ACTIONS, BECAUSE AN INTERVIEW IS NOW BOUGHT.
               Interviews are paid outright, so "Start interview" refuses with a 402 for
               anybody with none left — correctly, but that is a dead end if the only way to
               resolve it is to discover the pricing page. Buying is now a first-class action
               on the page every candidate lands on, sitting next to the thing it enables
               rather than behind it. Secondary styling: starting is still the primary intent
               for anybody who already has one. */
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href="/pricing"
                className={cn(buttonVariants({ variant: 'secondary', size: 'md' }))}
              >
                <Plus className="h-4 w-4" />
                Add interviews
              </Link>
              <Link href="/interview" className={cn(buttonVariants({ size: 'md' }))}>
                <Play className="h-4 w-4" />
                Start interview
              </Link>
            </div>
          }
        />
      </motion.div>

      {/* The rating, above everything else.
          A credential nobody sees is a credential nobody chases — and the whole
          point of the number is that it is the reason to come back. */}
      <motion.div variants={fadeUp}>
        <StandingBanner />
      </motion.div>

      {/* THE PROMO STRIP, HIGHEST ON THE PAGE.
          It is the only element here whose value depends on being SEEN — a code nobody
          notices is a code nobody redeems. It renders nothing at all when there is no live
          public offer with an image, which is most days, so this slot collapses and
          everything below is unchanged.

          WHAT USED TO SIT HERE, AND WHY IT NO LONGER DOES:

            THE UNFINISHED-REPORT NOTICE. It existed because a failed scoring pass left
            candidates on 0/100 with no way to know their answers were safe. That population
            is the one the report fixes were for — reports now complete themselves, and a
            partial one finishes on the next open — so a permanent banner about it is a
            standing apology for a bug that is gone.

            THE NAMED-DRIVE CARD. A card naming one company's drive on one date is the most
            perishable thing a dashboard can carry: the day after, it is an advert for
            something that has already happened. Its module went with it — the only part worth
            keeping was the strict ?isTechnical= parse, now lib/interview/params.ts, which the
            setup page still reads so an existing share link keeps working. */}
      <motion.div variants={fadeUp}>
        <PromoBanner />
      </motion.div>

      {/* THE NUDGE DECK, replacing the single FeatureNudge card.
          Same job — point somebody at the round they have not tried — but keyed on their real
          figures rather than on a static sentence, so it can also say "0 interviews left, one
          is Rs 49" and "your average is 54 across three interviews" to the people those are
          true for. It renders nothing when nothing is true, exactly as the old card did. */}
      <motion.div variants={fadeUp}>
        <NudgeDeck />
      </motion.div>

      {/* Stats grid — participation, deliberately BELOW the rating. Hours practised
          and sessions completed measure effort; the rating measures whether the
          effort worked, and the ordering should say which one matters. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
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
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent sessions — left 2/3 */}
        <motion.div variants={fadeUp} className="lg:col-span-2">
          <Card className="p-5">
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
              // Focus: hovering one session dims the rest. On a list you are scanning for
              // one particular round, that is the difference between reading and finding.
              <FocusGroup className="space-y-3">
                {sessions.map((sess) => (
                  <FocusItem
                    key={sess.id}
                    id={sess.id}
                    className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border border-border/50 bg-surface/50 p-4 hover:bg-surface"
                  >
                    {/* `min-w-0` on the block AND `break-words` on the label, together.
                        "Cognizant Technology Solutions — Digital Nurture Java FSE" plus a
                        status pill plus a score plus an icon is well over the 216px this
                        card gets on a 320px phone; without the pair the label pushed the
                        score and the report link off the right edge. */}
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="min-w-0 break-words text-xs font-semibold">{sess.company_name} — {sess.track_name}</span>
                        <Badge variant={sess.status === 'completed' ? 'success' : 'warning'}>{sess.status}</Badge>
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        {sess.questions_asked} questions asked • {sess.started_at ? new Date(sess.started_at).toLocaleDateString() : 'Recent'}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      {sess.overall_score !== null && (
                        <span className="text-sm font-bold text-primary">{sess.overall_score}/100</span>
                      )}
                      <Link
                        href={sess.status === 'completed' ? `/report/${sess.id}` : `/session/${sess.id}`}
                        // 44px square on a phone. `p-2` around a 16px icon is 32px, which
                        // is under the tap-target floor for the only way into the report.
                        className="flex h-11 w-11 items-center justify-center text-muted-foreground transition-colors hover:text-foreground sm:h-9 sm:w-9"
                        title={sess.status === 'completed' ? 'View Report' : 'Resume Session'}
                      >
                        {sess.status === 'completed' ? <FileText className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </Link>
                    </div>
                  </FocusItem>
                ))}
              </FocusGroup>
            )}
          </Card>
        </motion.div>

        {/* Allowance, then tracks — right 1/3.
            ABOVE the tracks on purpose: every track link goes to the interview setup, and
            knowing there is one interview left is information you want before you click one,
            not after. Renders nothing while loading, so it never flashes a zero. */}
        <motion.div variants={fadeUp} className="space-y-4">
          <CreditMeter />
          <Card className="p-5">
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
                        {/* `break-words`, not `truncate` — the track name is the whole
                            content of this link and half of it was being cut off. */}
                        <p className="break-words text-xs font-semibold">{track.company.name}</p>
                        <p className="mt-0.5 break-words text-[10px] text-muted-foreground">{track.name}</p>
                      </div>
                      <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-accent-emerald-ink" />
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

/**
 * The rating, at the top of the dashboard.
 *
 * Deliberately compact and deliberately specific: the number, what it claims, and
 * the exact points to the next rung. "Keep practising" is not a goal; "38 points to
 * Offer Ready" is, and it is the difference between a stat and something someone
 * comes back for.
 *
 * Renders nothing at all until there is a rating. An empty ladder on day one is a
 * reminder that you have done nothing, which is the opposite of the intended effect —
 * the nudge deck below already handles a first-time user.
 */
function StandingBanner() {
  const { data } = useProgress();
  if (!data || data.rated_rounds === 0) return null;

  const last = data.recent[0];
  return (
    <Link
      href="/achievements"
      className="ease-out-expo group block rounded-2xl border border-border/60 bg-card p-5 transition-colors hover:border-primary/40"
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
        <div className="flex items-end gap-2.5">
          <p className="font-mono text-4xl font-bold leading-none tracking-tight tabular-nums">
            {data.rating}
          </p>
          {/* The delta from the most recent round, so the dashboard shows movement
              rather than a static figure. Movement is what makes a number habit-forming. */}
          {!!last && last.delta !== 0 && (
            <span
              className={cn(
                'pb-1 font-mono text-xs font-bold tabular-nums',
                last.delta > 0 ? 'text-accent-emerald-ink' : 'text-accent-coral-ink'
              )}
            >
              {last.delta > 0 ? '+' : ''}
              {last.delta}
            </span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-xs font-bold uppercase tracking-wider text-primary">
            {data.rank.name}
          </p>
          <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
            {data.next_rank
              ? `${data.points_to_next} points to ${data.next_rank.name}`
              : 'Top of the ladder — hold it.'}
            {data.percentile != null && ` · ${data.percentile}th percentile`}
          </p>
        </div>

        <div className="flex items-center gap-5">
          <div className="text-right">
            <p className="font-mono text-lg font-bold tabular-nums">{data.total_cleared}</p>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              cleared
            </p>
          </div>
          <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
        </div>
      </div>
    </Link>
  );
}
