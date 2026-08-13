'use client';

import Link from 'next/link';
import { Lock } from 'lucide-react';

import { ApiError } from '@/lib/api/errors';
// buttonVariants rather than <Button asChild> — this Button is a plain forwardRef around a
// <button> with no Slot support, so wrapping a Link in it would nest an anchor inside a
// button. That is invalid HTML and breaks keyboard activation in exactly the place a blocked
// user needs it to work.
import { buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

/**
 * What the candidate sees when their allowance runs out — components/billing/Paywall.tsx
 *
 * TRIGGERED BY THE SERVER'S 402, NOT BY A CLIENT-SIDE COUNT. `fromError` reads the error the
 * request actually failed with, so this cannot appear when the server would have allowed the
 * action, and — more importantly — cannot be absent when the server refused. A paywall driven
 * by a locally-cached balance shows the wrong thing in both directions the moment that cache
 * is stale.
 *
 * IT NAMES WHAT RAN OUT. "Upgrade to continue" is a wall; "You have used all 2 mock
 * interviews on the Free plan" is an explanation with a number in it that the user can check
 * against what they remember doing. The server sends `feature`, `used` and `allowance` in
 * `details` precisely so this never has to parse a message string.
 */

export interface PaywallInfo {
  feature: string;
  planId: string;
  used: number;
  allowance: number;
}

/**
 * Read a failed request into paywall props, or null if it was not a 402.
 *
 * Returns null rather than throwing for any other error — callers use this to decide WHICH
 * error UI to show, and a helper that raises while classifying an error is a second failure
 * on top of the first.
 */
export function paywallFromError(error: unknown): PaywallInfo | null {
  if (!(error instanceof ApiError)) return null;
  const d = error.creditDetails;
  if (!d) return null;
  return { feature: d.feature, planId: d.plan_id, used: d.used, allowance: d.allowance };
}

const FEATURE_COPY: Record<string, string> = {
  interview: 'mock interviews',
  gd: 'group discussions',
  communication: 'communication drills',
};

export function Paywall({ info, className }: { info: PaywallInfo; className?: string }) {
  const label = FEATURE_COPY[info.feature] ?? 'sessions';
  const planName = info.planId === 'free' ? 'Free' : info.planId;

  return (
    <Card variant="elevated" padding="lg" className={className}>
      <div className="flex flex-col items-center gap-4 text-center">
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10">
          <Lock className="h-5 w-5 text-primary" aria-hidden />
        </div>

        <div className="space-y-1.5">
          <h2 className="text-lg font-semibold text-foreground">
            {/* The number, not a euphemism. It is checkable against what they remember. */}
            You have used all {info.allowance} {label} on the {planName} plan
          </h2>
          <p className="text-sm text-muted-foreground">
            Your allowance resets each month. Upgrade now to keep practising today.
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Link href="/pricing" className={buttonVariants({ variant: 'primary' })}>
            See plans
          </Link>
          {/* Quizzes are free on every tier, so this is a real alternative rather than a
              consolation link — somebody blocked from an interview can still do something
              useful in the next five minutes. */}
          <Link href="/quiz" className={buttonVariants({ variant: 'outline' })}>
            Take a free quiz instead
          </Link>
        </div>
      </div>
    </Card>
  );
}
