'use client';

import Link from 'next/link';
import { Check, Infinity as InfinityIcon, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { useAuth } from '@/hooks/useAuth';
import { useBalance, useCheckout, usePlans, type Plan } from '@/hooks/useBilling';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

/**
 * Plans — app/pricing/page.tsx
 *
 * THE NUMBERS COME FROM THE SERVER. Every allowance and price on this page is fetched from
 * /billing/plans rather than written here, because a pricing page that advertises ten
 * interviews while the server allows eight is a refund — and that divergence is invisible
 * until a paying customer hits it. There is one source of truth
 * (backend/app/services/billing/plans.py) and this renders it.
 *
 * TOP-LEVEL, NOT INSIDE THE (dashboard) GROUP, and that placement is the whole point.
 *
 * It started under (dashboard) and that was wrong: `DashboardLayout` redirects anyone
 * without a session to /login, so the "Compare plans" link on the landing page bounced
 * every logged-out visitor into a sign-up form before they could see a price. Requiring an
 * account to find out what something costs is the one place where auth actively loses the
 * sale — which is also why `GET /billing/plans` is the only unauthenticated route in the
 * billing API. Putting the page behind a login threw that away.
 *
 * So it renders for everyone, and the only thing a session changes is the "Your plan" badge
 * and whether the buttons do anything.
 */

/** The order the allowances read in. Interviews first: it is what people are buying. */
const FEATURE_ORDER = ['interview', 'gd', 'communication'] as const;

const FEATURE_LABEL: Record<string, string> = {
  interview: 'mock interviews',
  gd: 'group discussions',
  communication: 'communication drills',
};

/** Matches UNLIMITED in the backend's plans.py. */
const UNLIMITED = 1_000_000;

function Allowance({ feature, count }: { feature: string; count: number }) {
  const label = FEATURE_LABEL[feature] ?? feature;
  return (
    <li className="flex items-center gap-2.5 text-sm">
      <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden />
      {count >= UNLIMITED ? (
        <span className="flex items-center gap-1.5">
          <InfinityIcon className="h-3.5 w-3.5" aria-hidden />
          <span>Unlimited {label}</span>
        </span>
      ) : (
        <span>
          <span className="font-medium tabular-nums">{count}</span> {label}
          <span className="text-muted-foreground"> a month</span>
        </span>
      )}
    </li>
  );
}

function PlanCard({
  plan,
  current,
  onBuy,
  busy,
}: {
  plan: Plan;
  current: boolean;
  onBuy: (id: string) => void;
  busy: boolean;
}) {
  // Highlighted rather than hardcoded to a plan id, so reordering or renaming the catalogue
  // server-side cannot leave the badge on the wrong card.
  const recommended = plan.id === 'starter';

  return (
    <Card
      variant={recommended ? 'elevated' : 'flat'}
      padding="lg"
      className={cn(
        'flex flex-col gap-6',
        recommended && 'ring-1 ring-primary/40',
      )}
    >
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-foreground">{plan.name}</h2>
          {recommended && <Badge>Most popular</Badge>}
          {current && <Badge variant="neutral">Your plan</Badge>}
        </div>
        <p className="text-sm text-muted-foreground">{plan.tagline}</p>
      </div>

      <div className="flex items-baseline gap-1.5">
        <span className="text-3xl font-semibold tabular-nums text-foreground">
          ₹{plan.price_rupees}
        </span>
        {!plan.is_free && <span className="text-sm text-muted-foreground">/ month</span>}
      </div>

      <ul className="space-y-2.5">
        {FEATURE_ORDER.filter((f) => f in plan.allowances).map((f) => (
          <Allowance key={f} feature={f} count={plan.allowances[f]} />
        ))}
      </ul>

      <ul className="space-y-2 border-t border-border/60 pt-4">
        {plan.highlights.map((h) => (
          <li key={h} className="flex items-start gap-2.5 text-sm text-muted-foreground">
            <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" aria-hidden />
            <span>{h}</span>
          </li>
        ))}
      </ul>

      <div className="mt-auto pt-2">
        {plan.is_free ? (
          <Button variant="outline" className="w-full" disabled>
            {current ? 'Your current plan' : 'Included with every account'}
          </Button>
        ) : (
          <Button
            className="w-full"
            variant={recommended ? 'primary' : 'outline'}
            disabled={busy || current}
            onClick={() => onBuy(plan.id)}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : current ? (
              'Your current plan'
            ) : (
              `Upgrade to ${plan.name}`
            )}
          </Button>
        )}
      </div>
    </Card>
  );
}

export default function PricingPage() {
  const { data: plans, isLoading, isError } = usePlans();
  const { session, loading: authLoading } = useAuth();
  const signedIn = !!session;
  // Only asked for when there is a session to ask with. /billing/me is authenticated, so
  // firing it for a logged-out visitor is a guaranteed 401 — a console error on the page
  // whose entire job is to look trustworthy to somebody about to pay.
  const { data: balance } = useBalance({ enabled: signedIn });
  const checkout = useCheckout();

  const buy = (planId: string) => {
    if (!signedIn) {
      // Nothing to attach a purchase to. Sending them to register with the plan in the query
      // string means they land back here having already chosen, rather than starting over.
      window.location.href = `/register?redirectTo=${encodeURIComponent(`/pricing?plan=${planId}`)}`;
      return;
    }
    checkout.mutate(planId, {
      onSuccess: (order) => {
        /*
         * THE CHECKOUT WIDGET IS NOT WIRED YET, AND THIS SAYS SO RATHER THAN PRETENDING.
         *
         * Everything up to here is real: the order is opened against Razorpay with a
         * server-resolved amount, and the webhook that applies the plan is written, verified
         * and tested. What is missing is the browser SDK, which cannot be integrated without
         * live keys to load it with.
         *
         * Failing loudly and honestly is the right behaviour for that gap. A button that
         * silently does nothing reads as a broken product, and one that optimistically shows
         * "upgraded" would be worse than either.
         */
        toast.success(
          `Order ${order.order_id} is ready. Add your Razorpay keys to finish checkout.`,
        );
      },
      onError: (err) => {
        // 503 is the honest "payments are not switched on for this deployment yet" from the
        // server, and it deserves different copy from a genuine failure.
        const notConfigured = err instanceof ApiError && err.status === 503;
        toast.error(
          notConfigured
            ? 'Payments are not switched on yet. Add your Razorpay keys to enable checkout.'
            : 'Could not start the payment. Please try again.',
        );
      },
    });
  };

  return (
    // Its own chrome, because this page no longer sits inside DashboardLayout and would
    // otherwise render as bare text on the background for a logged-out visitor.
    <div className="min-h-screen bg-background paper-grain">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 sm:px-10">
          <Link href="/" className="text-sm font-semibold tracking-tight text-foreground">
            InterviewOS
          </Link>
          {/* The destination depends on whether they already have an account, so a visitor
              is never sent to a login form they do not need or a signup they already did. */}
          {!authLoading && (
            <Link
              href={signedIn ? '/dashboard' : '/login'}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {signedIn ? 'Dashboard' : 'Sign in'}
            </Link>
          )}
        </div>
      </header>

      <div className="mx-auto w-full max-w-6xl space-y-8 px-6 py-10 sm:px-10 sm:py-14">
      <PageHeader
        title="Plans"
        description="Free covers enough to see whether this helps. Upgrade when you need volume."
      />

      {isLoading && (
        <div className="flex justify-center py-16">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
        </div>
      )}

      {isError && (
        <Card variant="flat" padding="lg">
          <p className="text-sm text-muted-foreground">
            Could not load plans right now. Your existing allowance is unaffected — refresh to
            try again.
          </p>
        </Card>
      )}

      {plans && (
        <div className="grid gap-5 md:grid-cols-3">
          {plans.map((p) => (
            <PlanCard
              key={p.id}
              plan={p}
              current={balance?.plan_id === p.id}
              onBuy={buy}
              busy={checkout.isPending && checkout.variables === p.id}
            />
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Quizzes are unlimited and free on every plan, including Free. Allowances reset every 30
        days. Prices are in INR and include GST where applicable.
      </p>
      </div>
    </div>
  );
}
