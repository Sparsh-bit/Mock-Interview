'use client';

import Link from 'next/link';
import { Lock } from 'lucide-react';

import { cn } from '@/lib/utils';
import { ApiError } from '@/lib/api/errors';
// buttonVariants rather than <Button asChild> — this Button is a plain forwardRef around a
// <button> with no Slot support, so wrapping a Link in it would nest an anchor inside a
// button. That is invalid HTML and breaks keyboard activation in exactly the place a blocked
// user needs it to work.
import { buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { BuyPanel } from '@/components/billing/BuyPanel';

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
  deck: 'deck reviews',
};

//: The singular is needed now that the heading can say "Buy a mock interview to continue".
const FEATURE_COPY_SINGULAR: Record<string, string> = {
  interview: 'mock interview',
  gd: 'group discussion',
  communication: 'communication drill',
  deck: 'deck review',
};

export function Paywall({
  info,
  className,
  onPurchased,
}: {
  info: PaywallInfo;
  className?: string;
  /** Called once an item lands on the account, so the caller can retry what was blocked. */
  onPurchased?: () => void;
}) {
  const label = FEATURE_COPY[info.feature] ?? 'sessions';
  const one = FEATURE_COPY_SINGULAR[info.feature] ?? 'session';
  //: Nothing was ever free for this feature, so nothing has been "used up". See below.
  const neverHadAny = info.allowance <= 0;

  return (
    /*
     * LIT, because when this is on screen it IS the subject of the page — the candidate came
     * to start something and this is the only thing standing between them and it. One lit
     * element per view (docs/DESIGN-LANGUAGE §1); a paywall rendered as one more flat card
     * among several is a paywall people scroll past without reading, which helps nobody.
     */
    <Card variant="elevated" padding="lg" className={cn('lit', className)}>
      <div className="flex flex-col gap-5">
        {/*
          * LEFT-ALIGNED, not centred. DESIGN-RULES bans "everything centred" as a tell, and
          * there is a specific reason it matters here: this block is followed by BuyPanel,
          * which is a left-aligned list of priced options. A centred heading over a
          * left-aligned list reads as two components stacked by accident.
          */}
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-amber-soft">
          {/* Amber, not the primary indigo. In this palette amber means money and indigo
              means "the product / a primary action" — and an indigo padlock said "this is
              the main thing to click", which is the opposite of what a wall is. */}
          <Lock className="h-[18px] w-[18px] text-accent-amber-ink" aria-hidden />
        </div>

        <div className="space-y-1.5">
          <h2 className="text-lg font-semibold text-foreground">
            {/*
              * TWO SENTENCES, BECAUSE THERE ARE TWO SITUATIONS AND ONE OF THEM WAS NONSENSE.
              *
              * This read "You have used all {allowance} {label} on the {planId} plan" for
              * everybody. Once interviews and group discussions went paid their trial
              * allowance became 0, so the heading a blocked candidate actually saw was "You
              * have used all 0 mock interviews on the Free plan" — a sentence that is both
              * untrue and slightly insulting, since they had not used anything.
              *
              * The number is still shown where there IS one, because it is checkable against
              * what they remember doing, which is the whole reason it was put there.
              */}
            {neverHadAny
              ? `Buy a ${one} to continue`
              : `You have used all ${info.allowance} ${label}`}
          </h2>
          <p className="text-sm text-muted-foreground">
            {/*
              * "Your allowance resets each month" was here and there is no monthly reset —
              * this product does not have one and never did. Telling a blocked candidate to
              * wait for a reset that will not come is the worst of both: they do not buy, and
              * they come back to find nothing changed.
              */}
            {neverHadAny
              ? 'Nothing is lost — pick one below and carry straight on. What you buy does not expire.'
              : 'Buy more below and carry straight on. What you buy does not expire.'}
          </p>
        </div>

        {/*
          * THE PURCHASE HAPPENS HERE, on the page they were stopped on.
          *
          * "See plans" used to be the whole answer: leave, browse six products, find the one
          * you were already trying to use, come back. Every step there is a place to stop.
          */}
        <BuyPanel feature={info.feature} onPurchased={onPurchased} className="text-left" />

        {/*
          * WHAT USED TO BE THE SECOND BUTTON. "Take a free quiz instead" was offered as a real
          * alternative, and it is not one: somebody who came to sit a mock interview has not
          * been helped by being pointed at a quiz, and offering it at the moment of purchase
          * is an invitation to do the free thing instead of the thing they came for. The link
          * to the full store stays, for anybody who wants a different product or a bundle.
          */}
        <Link
          href="/pricing"
          className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          See everything in the store
        </Link>
      </div>
    </Card>
  );
}
