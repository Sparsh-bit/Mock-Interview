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
export function StatCard({
  label,
  value,
  icon,
  sub,
  color = 'blue',
  className,
}: {
  label: string;
  /** Pass `—` rather than a zero when there is genuinely no value yet. */
  value: React.ReactNode;
  icon: React.ReactNode;
  sub?: string;
  color?: IconTileProps['color'];
  className?: string;
}) {
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
