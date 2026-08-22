'use client';

import { motion } from 'framer-motion';
import {
  CheckCircle2,
  Flame,
  Lock,
  Minus,
  TrendingDown,
  TrendingUp,
  Trophy,
  Users,
} from 'lucide-react';

import { Card } from '@/components/ui/card';
import { DataError } from '@/components/ui/data-error';
import { PageHeader } from '@/components/ui/page-header';
import { useProgress, useUserStats, type RoundSummary, type TierProgress } from '@/hooks/useData';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

/**
 * Standing — the page that has to bring people back.
 *
 * This replaced four hardcoded badges whose unlock conditions were thresholds on
 * session counts ("Completed 5 sessions"). Those are participation trophies: they
 * say you turned up, which nobody chases and nobody would show anyone.
 *
 * What makes "412 solved, 180 medium" chaseable on LeetCode is that the number is
 * hard to move and therefore means something. So this leads with the rating and what
 * it CLAIMS about the candidate, states the exact distance to the next rung, and
 * shows the cleared-round ledger split by tier. Every number is derived from the
 * append-only ledger; see backend services/progress/rating.py for why grinding the
 * easy tier cannot climb it.
 */
export default function StandingPage() {
  const { data: progress, error, refetch, isFetching } = useProgress();
  const { data: stats } = useUserStats();

  if (error) {
    return (
      <DataError
        title="Could not load your standing"
        error={error}
        onRetry={() => refetch()}
        retrying={isFetching}
      />
    );
  }

  const rating = progress?.rating ?? null;
  const ladder = progress?.ladder ?? [];
  const nextRank = progress?.next_rank ?? null;

  // Progress along the CURRENT rung, not from zero. A bar that reads 60% full because
  // the rating is 1200 out of 2000 says nothing about the thing the candidate is
  // actually a few rounds away from.
  const rungFloor = progress?.rank.floor ?? 0;
  const rungCeil = nextRank?.floor ?? rungFloor;
  const rungSpan = Math.max(1, rungCeil - rungFloor);
  const rungFilled =
    rating === null ? 0 : Math.max(0, Math.min(100, ((rating - rungFloor) / rungSpan) * 100));

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.07)}
      className="mx-auto max-w-5xl space-y-8 pb-12"
    >
      <motion.div variants={fadeUp}>
        <PageHeader
          eyebrow="Standing"
          title="Your Interview Rating"
          description="One number for how you hold up under questioning. It rises when you beat what someone at your level is expected to score — and it barely moves for repeating rounds you have already proved."
        />
      </motion.div>

      {/* ── The number ─────────────────────────────────────────────────────── */}
      <motion.div variants={fadeUp}>
        <Card className="overflow-hidden p-0">
          <div className="grid gap-0 sm:grid-cols-[1.15fr_1fr]">
            <div className="space-y-4 border-b border-border/60 p-7 sm:border-b-0 sm:border-r">
              <div className="flex items-end gap-3">
                <p className="font-mono text-6xl font-bold leading-none tracking-tight tabular-nums">
                  {rating ?? '—'}
                </p>
                {/* Shown only when it applies. A dip is discouraging without the
                    reminder that they have already been higher, and hiding the dip
                    instead would make the number dishonest. */}
                {!!progress && progress.peak_rating > progress.rating && (
                  <p className="pb-1.5 text-xs font-medium text-muted-foreground">
                    peak {progress.peak_rating}
                  </p>
                )}
              </div>

              <div>
                <p className="text-sm font-bold uppercase tracking-wider text-primary">
                  {progress?.rank.name ?? 'Unrated'}
                </p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {progress?.rank.meaning ??
                    'Finish an interview or a group discussion and you get a rating.'}
                </p>
              </div>

              {nextRank && (
                <div className="space-y-1.5 pt-1">
                  <div className="flex items-baseline justify-between text-[11px] font-medium">
                    <span className="text-muted-foreground">
                      <span className="font-mono font-semibold tabular-nums text-foreground">
                        {progress?.points_to_next}
                      </span>{' '}
                      points to{' '}
                      <span className="font-semibold text-foreground">{nextRank.name}</span>
                    </span>
                    <span className="font-mono tabular-nums text-muted-foreground/70">
                      {nextRank.floor}
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                    <motion.div
                      className="h-full rounded-full bg-primary"
                      initial={{ width: 0 }}
                      animate={{ width: `${rungFilled}%` }}
                      transition={{ duration: 0.7, ease: 'easeOut' }}
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-px bg-border/60">
              <Stat
                icon={Trophy}
                label="Rounds cleared"
                value={progress?.total_cleared ?? 0}
                hint="Never goes down"
              />
              <Stat
                icon={CheckCircle2}
                label="Rounds rated"
                value={progress?.rated_rounds ?? 0}
                hint="Interviews + GDs"
              />
              <Stat
                icon={Users}
                label="Percentile"
                value={progress?.percentile != null ? `${progress.percentile}th` : '—'}
                hint={progress?.percentile != null ? 'Among active users' : 'Needs more users'}
              />
              <Stat
                icon={Flame}
                label="Day streak"
                value={stats?.streak_days ?? 0}
                hint="Consecutive days"
              />
            </div>
          </div>
        </Card>
      </motion.div>

      {/* ── The credential: cleared rounds by tier ─────────────────────────── */}
      <motion.div variants={fadeUp}>
        <Card className="space-y-5 p-7">
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wider">Cleared rounds</h2>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              A round clears when your report meets that tier&apos;s bar. This is the part that
              only ever goes up — and the part worth showing someone, because clearing Panel means
              something clearing Foundation does not.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {(progress?.tiers ?? []).map((t) => (
              <TierCard key={t.tier} tier={t} />
            ))}
          </div>
        </Card>
      </motion.div>

      {/* ── The whole ladder, so what is ahead is visible ──────────────────── */}
      {!!ladder.length && (
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-7">
            <div>
              <h2 className="text-sm font-bold uppercase tracking-wider">The ladder</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Grinding easy rounds tops out well short of the last two rungs. Once you are
                comfortably above a tier, clearing it again pays almost nothing — the only way up
                is a harder round.
              </p>
            </div>
            <div className="space-y-1.5">
              {ladder.map((r) => {
                const reached = rating !== null && rating >= r.floor;
                const isCurrent = progress?.rank.name === r.name;
                return (
                  <div
                    key={r.name}
                    className={cn(
                      'flex items-start gap-3 rounded-xl border px-4 py-3 transition-colors',
                      isCurrent
                        ? 'border-primary/50 bg-primary/10'
                        : reached
                          ? 'border-accent-emerald/30 bg-accent-emerald/5'
                          : 'border-border/60'
                    )}
                  >
                    <span className="mt-0.5">
                      {reached ? (
                        <CheckCircle2
                          className={cn(
                            'h-4 w-4',
                            isCurrent ? 'text-primary' : 'text-accent-emerald-ink'
                          )}
                        />
                      ) : (
                        <Lock className="h-4 w-4 text-muted-foreground/40" />
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                        <p
                          className={cn(
                            'text-sm font-semibold',
                            !reached && 'text-muted-foreground/70'
                          )}
                        >
                          {r.name}
                          {isCurrent && (
                            <span className="ml-2 text-[10px] font-bold uppercase tracking-wider text-primary">
                              you are here
                            </span>
                          )}
                        </p>
                        <span className="font-mono text-[11px] tabular-nums text-muted-foreground/60">
                          {r.floor}+
                        </span>
                      </div>
                      <p
                        className={cn(
                          'mt-0.5 text-[11px] leading-snug',
                          reached ? 'text-muted-foreground' : 'text-muted-foreground/60'
                        )}
                      >
                        {r.meaning}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </motion.div>
      )}

      {/* ── Recent rounds, each saying why it moved what it moved ──────────── */}
      {!!progress?.recent.length && (
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-7">
            <div>
              <h2 className="text-sm font-bold uppercase tracking-wider">Recent rounds</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Each round says why it moved the number by what it did. A small gain on a round
                that felt good usually means you were expected to clear it.
              </p>
            </div>
            <div className="space-y-2">
              {progress.recent.map((r, i) => (
                <RoundRow key={`${r.at}-${i}`} round={r} />
              ))}
            </div>
          </Card>
        </motion.div>
      )}

      {progress?.rated_rounds === 0 && (
        <motion.div variants={fadeUp}>
          <Card className="flex flex-col items-center gap-2 p-8 text-center">
            <p className="text-sm font-semibold">You have no rated rounds yet</p>
            <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
              Finish a mock interview or a group discussion and you get a rating. The first few
              rounds move it the most — the number settles as it learns where you actually are.
            </p>
          </Card>
        </motion.div>
      )}
    </motion.div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Trophy;
  label: string;
  value: string | number;
  hint: string;
}) {
  return (
    <div className="bg-card p-5">
      {/* This grid is `grid-cols-2` at every width, so each cell is ~104px of content on a
          320px phone. "PERCENTILE" at uppercase + tracking-wider is about 95px of that, and
          without `min-w-0`/`shrink-0` the label refused to shrink and squashed the icon
          instead of wrapping. */}
      <div className="flex items-center gap-1.5 text-muted-foreground">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 break-words text-[10px] font-semibold uppercase tracking-wider">{label}</span>
      </div>
      <p className="mt-1.5 font-mono text-2xl font-bold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[10px] text-muted-foreground/70">{hint}</p>
    </div>
  );
}

function TierCard({ tier }: { tier: TierProgress }) {
  const rate = tier.attempted > 0 ? tier.cleared / tier.attempted : 0;
  return (
    <div className="rounded-xl border border-border/60 bg-surface-elevated p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <p className="min-w-0 break-words text-xs font-bold uppercase tracking-wider">{tier.label}</p>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground/70">
          {tier.clear_bar}+ to clear
        </span>
      </div>
      <p className="mt-2 font-mono text-3xl font-bold tabular-nums">{tier.cleared}</p>
      {/* "of 11 attempted", not a bare 3. A cleared count without the attempts behind
          it implies every round cleared, which would make the credential dishonest. */}
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        {tier.attempted === 0 ? 'not attempted yet' : `of ${tier.attempted} attempted`}
      </p>
      {tier.attempted > 0 && (
        <div className="mt-2.5 h-1 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className={cn(
              'h-full rounded-full',
              rate >= 0.6
                ? 'bg-accent-emerald'
                : rate >= 0.3
                  ? 'bg-accent-amber'
                  : 'bg-accent-coral'
            )}
            style={{ width: `${Math.max(4, rate * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

function RoundRow({ round }: { round: RoundSummary }) {
  const up = round.delta > 0;
  const flat = round.delta === 0;
  const Icon = flat ? Minus : up ? TrendingUp : TrendingDown;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-border/60 px-4 py-3">
      <span
        className={cn(
          'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          flat
            ? 'bg-secondary text-muted-foreground'
            : up
              ? 'bg-accent-emerald/15 text-accent-emerald-ink'
              : 'bg-accent-coral/15 text-accent-coral-ink'
        )}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <p className="text-sm font-semibold">
            {round.kind === 'gd' ? 'Group discussion' : 'Interview'}
          </p>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {round.tier}
          </span>
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {round.score.toFixed(0)}/100
          </span>
          {round.cleared && (
            <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-accent-emerald-ink">
              <CheckCircle2 className="h-3 w-3" /> cleared
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{round.note}</p>
      </div>
      <div className="shrink-0 text-right">
        <p
          className={cn(
            'font-mono text-sm font-bold tabular-nums',
            flat
              ? 'text-muted-foreground'
              : up
                ? 'text-accent-emerald-ink'
                : 'text-accent-coral-ink'
          )}
        >
          {up ? '+' : ''}
          {round.delta}
        </p>
        <p className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
          {round.rating_after}
        </p>
      </div>
    </div>
  );
}
