'use client';

import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';

/**
 * A progress bar for work whose duration we do not know — components/ui/progress-bar.tsx
 *
 * REQUESTED: "try to show a loading bar while building the interview ... so that the user must
 * not feel that something is stucked."
 *
 * THE HONESTY PROBLEM, AND WHY THIS IS NOT A PERCENTAGE. Building an interview plan is one AI
 * call with a 110-second ceiling and no progress to report — the model does not tell us how far
 * through it is. So a bar that claims 40% is inventing a number, and the usual result is worse
 * than no bar: it fills confidently, reaches 100%, and then sits there while the request is
 * still running. A user watching a full bar do nothing concludes the app is broken, which is
 * exactly the feeling this was added to remove.
 *
 * SO IT ASYMPTOTES AND NEVER ARRIVES. The fill approaches `ceiling` (90% by default) and slows
 * as it goes, on a curve driven by elapsed time against `expectedMs`. That encodes the only two
 * things actually known: work is still happening, and it has been going on for this long. It
 * cannot reach the end, because reaching the end would be a claim. When the caller unmounts it
 * — because the work finished — the bar disappears mid-travel, which reads correctly as "that
 * finished" rather than as a completed measurement.
 *
 * Past `expectedMs` it keeps creeping, more slowly. A job that is taking longer than usual
 * should look like it is taking longer than usual.
 *
 * `expectedMs` IS A REAL NUMBER OR IT IS NOTHING. Pass what the operation actually takes,
 * measured. Guessing low makes every run look overdue; guessing high makes a fast run look
 * stalled at 10%.
 */
export interface ProgressBarProps {
  /** Roughly how long this work takes when healthy. Measured, not hoped for. */
  expectedMs: number;
  /** The fraction the bar approaches but never reaches. */
  ceiling?: number;
  className?: string;
  /** Announced to assistive tech. The bar itself is decorative without it. */
  label?: string;
}

export function ProgressBar({
  expectedMs,
  ceiling = 0.9,
  className,
  label = 'Working',
}: ProgressBarProps) {
  const [fraction, setFraction] = useState(0.02);
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    startedAt.current = Date.now();
    /*
     * 100ms, not requestAnimationFrame. The bar moves slowly by design and rAF would wake the
     * page sixty times a second to move it a fraction of a pixel — on the phones this product's
     * users actually have, that is battery spent on a decoration. The CSS transition below
     * smooths the steps, so a tenth of a second is invisible.
     */
    const id = setInterval(() => {
      const elapsed = Date.now() - (startedAt.current ?? Date.now());
      /*
       * 1 - e^(-t/expected), which is the standard shape for "no idea how long, but still
       * going": fast at first because early progress is the reassuring part, then slower and
       * slower. At t = expectedMs it sits at about 63% of the ceiling; it approaches the
       * ceiling and never touches it.
       */
      const eased = 1 - Math.exp(-elapsed / Math.max(expectedMs, 1));
      setFraction(Math.min(ceiling, Math.max(0.02, eased * ceiling)));
    }, 100);
    return () => clearInterval(id);
  }, [expectedMs, ceiling]);

  return (
    <div
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-muted/40', className)}
      // No aria-valuenow: the number is an animation, not a measurement, and announcing "41
      // percent" to a screen reader would be a claim this component exists to avoid making.
      role="progressbar"
      aria-label={label}
      aria-valuetext="in progress"
    >
      <div
        className="h-full rounded-full bg-primary transition-[width] duration-200 ease-out"
        style={{ width: `${(fraction * 100).toFixed(1)}%` }}
      />
    </div>
  );
}
