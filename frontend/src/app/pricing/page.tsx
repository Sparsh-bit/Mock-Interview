'use client';

import Link from 'next/link';
import { Check, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { useAuth } from '@/hooks/useAuth';
import { useBalance, useCheckout, useStoreItems, type StoreItem } from '@/hooks/useBilling';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

/**
 * The store — app/pricing/page.tsx
 *
 * NO SUBSCRIPTION. One free trial of each thing, then you buy what you use, and what you
 * buy does not expire. The users here are campus students with a placement season a few
 * weeks long: they want three interviews the week before a drive and nothing for two
 * months. A monthly plan is a bad deal for that shape in both directions, and "is this
 * worth ₹299 a month" is a far harder question than "is one more mock interview worth ₹49"
 * — which is asked at the moment the answer is obviously yes.
 *
 * EVERY NUMBER COMES FROM THE SERVER. Prices and quantities are fetched from /billing/items
 * rather than written here, because a page advertising ₹49 while the server charges ₹79 is
 * a refund, and that divergence is invisible until a paying customer hits it. One source of
 * truth (backend/app/services/billing/plans.py) and this renders it.
 *
 * TOP-LEVEL, NOT INSIDE (dashboard), because that layout redirects anyone without a session
 * to /login — and requiring an account to see what something costs is the one place where
 * auth actively loses the sale.
 */

const FEATURE_ORDER = ['interview', 'gd', 'communication'] as const;

const FEATURE_HEADING: Record<string, string> = {
  interview: 'Mock interviews',
  gd: 'Group discussions',
  communication: 'Communication drills',
};

const FEATURE_BLURB: Record<string, string> = {
  interview: 'Twelve questions from a two-person panel, a coding round, and a full report.',
  gd: 'Eight minutes against three AI panelists who argue back, then scored.',
  communication: 'Speak an answer or read a passage; scored on clarity, pace and fillers.',
};

function ItemCard({
  item,
  onBuy,
  busy,
  signedIn,
}: {
  item: StoreItem;
  onBuy: (id: string) => void;
  busy: boolean;
  signedIn: boolean;
}) {
  const isBundle = item.quantity > 1;
  const perUnit = Math.round(item.price_rupees / item.quantity);

  return (
    <Card
      variant={isBundle ? 'elevated' : 'flat'}
      padding="md"
      className={cn('flex flex-col gap-4', isBundle && 'ring-1 ring-primary/30')}
    >
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">{item.name}</h3>
          {isBundle && <Badge>Better value</Badge>}
        </div>
        <p className="text-xs text-muted-foreground">{item.tagline}</p>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums text-foreground">
          ₹{item.price_rupees}
        </span>
        {isBundle && (
          <span className="text-xs text-muted-foreground">₹{perUnit} each</span>
        )}
      </div>

      <Button
        className="mt-auto w-full"
        variant={isBundle ? 'primary' : 'outline'}
        disabled={busy}
        onClick={() => onBuy(item.id)}
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : signedIn ? (
          'Buy'
        ) : (
          'Sign up to buy'
        )}
      </Button>
    </Card>
  );
}

export default function StorePage() {
  const { data: items, isLoading, isError } = useStoreItems();
  const { session, loading: authLoading } = useAuth();
  const signedIn = !!session;
  const { data: balance } = useBalance({ enabled: signedIn });
  const checkout = useCheckout();

  const buy = (itemId: string) => {
    if (!signedIn) {
      window.location.href = `/register?redirectTo=${encodeURIComponent('/pricing')}`;
      return;
    }
    checkout.mutate(itemId, {
      onSuccess: (order) => {
        /*
         * THE CHECKOUT WIDGET IS NOT WIRED YET, AND THIS SAYS SO RATHER THAN PRETENDING.
         *
         * Everything up to here is real: the order is opened against Razorpay with a
         * server-resolved amount, and the webhook that grants the items is written,
         * signature-verified, amount-checked and idempotent. What is missing is the browser
         * SDK, which cannot be integrated without live keys to load it with.
         *
         * Failing loudly is right for that gap. A button that silently does nothing reads
         * as a broken product, and one that optimistically says "bought" would be worse.
         */
        toast.success(
          `Order ${order.order_id} is ready. Add your Razorpay keys to finish checkout.`,
        );
      },
      onError: (err) => {
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
    <div className="min-h-screen bg-background paper-grain">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5 sm:px-10">
          <Link href="/" className="text-sm font-semibold tracking-tight text-foreground">
            InterviewOS
          </Link>
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

      <div className="mx-auto w-full max-w-5xl space-y-10 px-6 py-10 sm:px-10 sm:py-14">
        <PageHeader
          title="Buy what you need"
          description="No subscription. Try each thing free once, then pay per session — and what you buy never expires."
        />

        {/* The trial, stated plainly and first. It is the most persuasive thing on the page
            and it costs the reader nothing to accept. */}
        <Card variant="flat" padding="md">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <span className="font-medium text-foreground">Free on every account:</span>
            {['1 mock interview', '1 group discussion', '1 communication drill', 'Unlimited quizzes'].map(
              (t) => (
                <span key={t} className="flex items-center gap-1.5 text-muted-foreground">
                  <Check className="h-3.5 w-3.5 text-primary" aria-hidden />
                  {t}
                </span>
              ),
            )}
          </div>
        </Card>

        {isLoading && (
          <div className="flex justify-center py-16">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
          </div>
        )}

        {isError && (
          <Card variant="flat" padding="lg">
            <p className="text-sm text-muted-foreground">
              Could not load the store right now. Anything you have already bought is
              unaffected — refresh to try again.
            </p>
          </Card>
        )}

        {items &&
          FEATURE_ORDER.filter((f) => items.some((i) => i.feature === f)).map((feature) => {
            const forFeature = items
              .filter((i) => i.feature === feature)
              .sort((a, b) => a.price_paise - b.price_paise);
            const left = balance?.features.find((f) => f.feature === feature);

            return (
              <section key={feature} className="space-y-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <h2 className="text-base font-semibold text-foreground">
                      {FEATURE_HEADING[feature] ?? feature}
                    </h2>
                    <p className="text-sm text-muted-foreground">{FEATURE_BLURB[feature]}</p>
                  </div>
                  {left && (
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {left.remaining} left on your account
                    </span>
                  )}
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {forFeature.map((item) => (
                    <ItemCard
                      key={item.id}
                      item={item}
                      onBuy={buy}
                      busy={checkout.isPending && checkout.variables === item.id}
                      signedIn={signedIn}
                    />
                  ))}
                </div>
              </section>
            );
          })}

        <p className="text-xs text-muted-foreground">
          Quizzes are unlimited and free on every account. Purchases do not expire. Prices are
          in INR and include GST where applicable.
        </p>
      </div>
    </div>
  );
}
