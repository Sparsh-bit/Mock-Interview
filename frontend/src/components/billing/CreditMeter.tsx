'use client';

import Link from 'next/link';
import { Infinity as InfinityIcon } from 'lucide-react';

import { useBalance } from '@/hooks/useBilling';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * What is left this period — components/billing/CreditMeter.tsx
 *
 * SHOWS THE NUMBER BEFORE IT MATTERS. The worst version of a metered product is one where the
 * limit is invisible until you hit it — a candidate who sets up an interview, waits through
 * the plan generation and then gets refused has wasted the only thing they came with, which
 * is time. The count sits on the dashboard so "1 interview left" is known before anything is
 * started.
 *
 * IT IS A DISPLAY, NOT A GATE. The server refuses regardless of what this renders; see
 * hooks/useBilling.ts. Rendering nothing while loading is deliberate — a meter that flashes
 * "0 remaining" before its data arrives would tell a paying user they had run out.
 */

/** Amber below this fraction remaining, so the warning lands before the last one is gone. */
const LOW_FRACTION = 0.34;

export function CreditMeter({ className }: { className?: string }) {
  const { data, isLoading } = useBalance();

  // No skeleton on purpose. This is secondary information, and a placeholder box that
  // resolves into numbers pulls the eye to the one thing on the dashboard that is not the
  // task the candidate came to do.
  if (isLoading || !data) return null;

  const anythingLeft = data.features.some((f) => f.unlimited || f.remaining > 0);

  return (
    <Card variant="flat" padding="md" className={cn('space-y-4', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-foreground">{data.plan_name} plan</p>
          <p className="text-xs text-muted-foreground">
            Resets {new Date(data.period_end).toLocaleDateString(undefined, {
              day: 'numeric',
              month: 'short',
            })}
          </p>
        </div>
        <Link
          href="/pricing"
          className="text-xs font-medium text-primary hover:underline shrink-0"
        >
          {anythingLeft ? 'Upgrade' : 'Get more'}
        </Link>
      </div>

      <ul className="space-y-3">
        {data.features.map((f) => {
          const fraction = f.allowance > 0 ? f.remaining / f.allowance : 0;
          const low = !f.unlimited && fraction <= LOW_FRACTION;
          const gone = !f.unlimited && f.remaining === 0;

          return (
            <li key={f.feature} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="capitalize text-muted-foreground">{f.label}</span>
                {f.unlimited ? (
                  <span className="flex items-center gap-1 font-medium text-foreground">
                    <InfinityIcon className="h-3.5 w-3.5" aria-hidden />
                    <span className="sr-only">Unlimited</span>
                  </span>
                ) : (
                  <span
                    className={cn(
                      'font-medium tabular-nums',
                      gone ? 'text-destructive' : low ? 'text-amber-500' : 'text-foreground',
                    )}
                  >
                    {f.remaining} left
                  </span>
                )}
              </div>
              {!f.unlimited && (
                <div
                  className="h-1 overflow-hidden rounded-full bg-secondary"
                  // The bar is decorative — the number beside it is the accessible value, and
                  // a progressbar role here would have a screen reader read both.
                  aria-hidden
                >
                  <div
                    className={cn(
                      'h-full rounded-full transition-[width] duration-500',
                      gone ? 'bg-destructive' : low ? 'bg-amber-500' : 'bg-primary',
                    )}
                    style={{ width: `${Math.max(0, Math.min(100, fraction * 100))}%` }}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
