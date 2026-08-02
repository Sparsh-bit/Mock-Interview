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
        <div className="mb-4 flex items-start justify-between gap-3">
          <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
          <IconTile color={color} size="sm">
            {icon}
          </IconTile>
        </div>
        <p className="text-2xl font-medium tabular-nums tracking-[-0.03em]">{value}</p>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </Card>
    </motion.div>
  );
}
