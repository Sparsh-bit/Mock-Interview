'use client';

import * as React from 'react';
import { motion } from 'framer-motion';
import { Card } from '@/components/ui/card';
import { IconTile, type IconTileProps } from '@/components/ui/icon-tile';
import { fadeUp } from '@/lib/motion';

/**
 * The one metric tile the app uses.
 *
 * This lived privately inside the dashboard page while /analytics hand-rolled a
 * near-copy four times over. The two versions had drifted: different padding
 * (p-4 vs p-5), a different label case and weight, a different value size, a
 * tiled icon on one and a bare glyph on the other, and no support for the
 * sub-label at all on the second. Side by side they read as two products.
 *
 * `sub` matters more than it looks. Without it a metric reads as a fact —
 * "0" — when what it means is "0 so far, out of nothing yet". `—` for an
 * absent value rather than `0` is the same idea: a candidate who has completed
 * no sessions has no average score, and printing `0%` tells them they scored
 * zero, which is both wrong and demoralising.
 */
/**
 * TWO VARIANTS, AND THE DEFAULT IS UNCHANGED.
 *
 * `card` is what this component has always rendered and what /analytics, /ai-usage and the
 * three admin pages still get: a bordered tile with an icon, which is right when four metrics
 * sit among a dozen other panels and each needs its own edge to be found by.
 *
 * `bare` drops the border, the fill and the icon and leaves the number and its caption. It
 * exists for the dashboard's top row, where four bordered tiles in a row directly under the
 * page title produced four competing rectangles before the reader had reached anything they
 * came for. Grouped inside ONE panel with hairlines between them, the same four figures read
 * as a single summary — which is what they are. The icon goes because at that size it is
 * decoration: "Total Sessions" is already the label, and a book glyph beside it adds nothing
 * a reader did not have.
 *
 * The prop is opt-in rather than a new default so that no existing caller changes.
 */
export function StatCard({
  label,
  value,
  icon,
  sub,
  color = 'blue',
  variant = 'card',
  className,
}: {
  label: string;
  /** Pass `—` rather than a zero when there is genuinely no value yet. */
  value: React.ReactNode;
  icon: React.ReactNode;
  sub?: string;
  color?: IconTileProps['color'];
  variant?: 'card' | 'bare';
  className?: string;
}) {
  if (variant === 'bare') {
    return (
      <motion.div variants={fadeUp} className={className}>
        <span className="block min-w-0 break-words text-[10px] font-semibold uppercase tracking-[0.14em] text-accent-amber-ink/70">
          {label}
        </span>
        {/* Larger than the card variant's 2xl, because with the border and the icon gone the
            number is the only thing holding the tile together and it has to carry that on its
            own. Mono and tabular so a row of four aligns on the decimal and does not reflow
            when a figure ticks over a digit. */}
        <p className="mt-2 break-words font-mono text-[1.75rem] font-medium leading-none tabular-nums tracking-[-0.03em]">
          {value}
        </p>
        {sub && <p className="mt-1.5 text-xs text-muted-foreground">{sub}</p>}
      </motion.div>
    );
  }

  return (
    <motion.div variants={fadeUp} className={className}>
      <Card hoverable className="h-full p-4">
        {/*
          `min-w-0` ON THE LABEL AND `shrink-0` ON THE TILE, and this tile is the reason it
          matters more here than anywhere else: it is rendered inside `grid-cols-2` on the
          dashboard, /analytics, /ai-usage and three admin pages, so on a 320px phone each
          one gets about 138px — 106px of content once `p-4` is taken off, and 58px once the
          36px icon and its gap are.

          A flex item defaults to `min-width: auto`, meaning "never narrower than my longest
          unbreakable word". "QUESTIONS" at text-xs with `tracking-wider` is about 72px, so
          the label refused to shrink past 58px, the flex row grew wider than the card, and
          the card grew wider than its grid track — which is a horizontal scrollbar on the
          whole page from a label. Without `shrink-0` the flex row solves it the other way
          instead and squashes the 36px icon into an oval.

          `break-words` is the other half: `min-w-0` permits the shrink, and only a break
          opportunity lets the text actually reflow into the narrower box.
        */}
        <div className="mb-4 flex items-start justify-between gap-3">
          <span className="min-w-0 break-words text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
          <IconTile color={color} size="sm" className="shrink-0">
            {icon}
          </IconTile>
        </div>
        <p className="break-words text-2xl font-medium tabular-nums tracking-[-0.03em]">{value}</p>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </Card>
    </motion.div>
  );
}
