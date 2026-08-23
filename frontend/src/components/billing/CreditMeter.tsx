'use client';

import Link from 'next/link';

import { useBalance } from '@/hooks/useBilling';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * What is left on this account — components/billing/CreditMeter.tsx
 *
 * SHOWS THE NUMBER BEFORE IT MATTERS. The worst version of a metered product is one where
 * the limit is invisible until you hit it — a candidate who sets up an interview, waits
 * through the plan generation and then gets refused has wasted the only thing they came
 * with, which is time. The count sits on the dashboard and the setup page so "no interviews
 * left" is known before anything is started.
 *
 * IT IS A DISPLAY, NOT A GATE. The server refuses regardless of what this renders; see
 * hooks/useBilling.ts. Rendering nothing while loading is deliberate — a meter that flashes
 * "0 left" before its data arrives would tell somebody who has just paid that they have not.
 */

export function CreditMeter({ className }: { className?: string }) {
  const { data, isLoading } = useBalance();

  // No skeleton on purpose. This is secondary information, and a placeholder box resolving
  // into numbers pulls the eye to the one thing on the page that is not the task the
  // candidate came to do.
  if (isLoading || !data) return null;

  // An operator account is not metered, so a countdown would be a stuck number pretending
  // to mean something. Say what is true instead.
  if (data.unlimited) {
    return (
      <Card variant="flat" padding="md" className={cn('space-y-1', className)}>
        <p className="text-sm font-medium text-foreground">Unlimited access</p>
        <p className="text-xs text-muted-foreground">
          Admin account — sessions are not counted against a balance.
        </p>
      </Card>
    );
  }

  const anythingLeft = data.features.some((f) => f.remaining > 0);

  return (
    <Card variant="flat" padding="md" className={cn('space-y-4', className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div>
          <p className="text-sm font-medium text-foreground">
            {data.trial_started ? 'Your balance' : 'Your free trial'}
          </p>
          <p className="text-xs text-muted-foreground">
            {data.trial_started ? 'Purchases never expire' : 'One of each, on the house'}
          </p>
        </div>
        <Link href="/pricing" className="shrink-0 text-xs font-medium text-primary hover:underline">
          {anythingLeft ? 'Buy more' : 'Get more'}
        </Link>
      </div>

      <ul className="space-y-3">
        {data.features.map((f) => {
          const fraction = f.granted > 0 ? f.remaining / f.granted : 0;
          const gone = f.remaining === 0;
          // Amber below a third so the warning lands before the last one is gone.
          const low = !gone && fraction <= 0.34;

          return (
            <li key={f.feature} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 break-words capitalize text-muted-foreground">{f.label}</span>
                <span
                  className={cn(
                    'font-medium tabular-nums',
                    gone ? 'text-destructive' : low ? 'text-amber-500' : 'text-foreground',
                  )}
                >
                  {f.remaining} left
                </span>
              </div>
              <div
                className="h-1 overflow-hidden rounded-full bg-secondary"
                // Decorative — the number beside it is the accessible value, and a
                // progressbar role here would have a screen reader read both.
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
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
