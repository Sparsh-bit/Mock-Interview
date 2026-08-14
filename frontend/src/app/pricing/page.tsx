'use client';

import Link from 'next/link';
import { Check, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { useAuth } from '@/hooks/useAuth';
import {
  useBalance,
  useCheckout,
  useQuote,
  useStoreItems,
  useVerifyPayment,
  type StoreItem,
} from '@/hooks/useBilling';
import { openCheckout } from '@/lib/billing/razorpay-checkout';
import { Turnstile } from '@/components/billing/Turnstile';
import { PaymentHistory } from '@/components/billing/PaymentHistory';
import { FreeOrderSheet } from '@/components/billing/FreeOrderSheet';
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
  const quote = useQuote();
  const verify = useVerifyPayment();
  const qc = useQueryClient();
  //: The code that has been CHECKED, not what is in the box. Only a code the server has
  //: already priced is sent with a purchase, so a half-typed one cannot ride along.
  const [appliedCode, setAppliedCode] = useState('');
  const [codeInput, setCodeInput] = useState('');
  const [quoted, setQuoted] = useState<{
    charged_paise: number;
    original_paise: number;
    is_free: boolean;
    requires_captcha: boolean;
    label: string;
  } | null>(null);
  const [captchaToken, setCaptchaToken] = useState('');
  /*
   * A FREE ORDER GETS A CONFIRMATION STEP, NOT A SILENT GRANT.
   *
   * Razorpay will not create an order below ₹1, so a 100%-off code has no sheet to open —
   * that is a platform limit, and it is also what every large Indian checkout does with a
   * full-value coupon: the payment step disappears and an order summary takes its place.
   *
   * What was missing was the summary. The item was granted the instant Buy was pressed with
   * nothing to confirm, which reads as the button having failed, because everything a
   * candidate knows about buying says something should appear.
   */
  const [freeOrder, setFreeOrder] = useState<StoreItem | null>(null);

  /*
   * Priced against the CHEAPEST item, purely so the box can be validated before the
   * candidate picks something.
   *
   * The real price is computed again server-side at purchase, against the item they
   * actually chose — this is a check that the code exists and applies, not the quote that
   * decides what they pay. A code restricted to other items fails here and says so, which
   * is better than accepting it and refusing at the till.
   */
  const applyCode = () => {
    const code = codeInput.trim();
    if (!code || !items?.length) return;
    quote.mutate(
      { itemId: items[0].id, code },
      {
        onSuccess: (q) => {
          setAppliedCode(code.toUpperCase());
          setQuoted(q);
          toast.success(q.label ? `${q.label} applied.` : 'Code applied.');
        },
        onError: (err) => {
          setAppliedCode('');
          setQuoted(null);
          toast.error(
            err instanceof ApiError && err.status === 400
              ? err.message
              : 'Could not check that code.',
          );
        },
      },
    );
  };

  const buy = (itemId: string) => {
    if (!signedIn) {
      window.location.href = `/register?redirectTo=${encodeURIComponent('/pricing')}`;
      return;
    }
    // A code that covers this in full goes through the confirm sheet. `quoted` is priced
    // against the cheapest item, so it is only a reliable "this is free" signal for a `free`
    // code — which is the only kind that can produce a ₹0 total on every item.
    if (quoted?.is_free && appliedCode) {
      const item = items?.find((i) => i.id === itemId) ?? null;
      if (item) {
        setFreeOrder(item);
        return;
      }
    }
    runCheckout(itemId);
  };

  /*
   * THE ONE PLACE THAT CHECKS OUT, and the reason it is extracted.
   *
   * Two call sites reach it — pressing Buy, and confirming a ₹0 order — and TanStack's
   * per-call `onSuccess` only fires for the call that passes it. Calling `mutate` a second
   * time from the confirm sheet without repeating the handlers left the sheet spinning
   * forever with the item silently granted behind it. One function, one set of handlers,
   * both paths.
   */
  const runCheckout = (itemId: string) => {
    checkout.mutate(
      { itemId, code: appliedCode, captchaToken },
      {
      onSuccess: async (order) => {
        /*
         * A FREE CODE HAS ALREADY GRANTED THE ITEM. There is nothing to pay and no sheet to
         * open — Razorpay has a ₹1 minimum, so a fully-discounted item never becomes an
         * order at all. Opening the widget here would show a payment form for ₹0.
         */
        if (order.granted) {
          // Reached from the confirm sheet, or from a code that turned out to be free only
          // for this particular item.
          setFreeOrder(null);
          toast.success('Added to your account. Nothing to pay.');
          setAppliedCode('');
          setQuoted(null);
          setCodeInput('');
          return;
        }
        if (!order.order_id || !order.key_id) {
          toast.error('Payments are not switched on yet.');
          return;
        }

        const opened = await openCheckout({
          orderId: order.order_id,
          amountPaise: order.amount_paise,
          keyId: order.key_id,
          itemName: items?.find((i) => i.id === itemId)?.name ?? 'InterviewOS',
          prefill: { email: session?.user?.email ?? undefined },
          onSuccess: (proof) => {
            /*
             * VERIFIED SERVER-SIDE, IMMEDIATELY. Not trusted from here — the server checks
             * Razorpay's signature over these ids, then asks Razorpay whether the money
             * actually moved, then checks the amount against the item.
             *
             * The webhook is still the primary path and still grants on its own. This is the
             * second, independent one, and it exists because a candidate paid and received
             * nothing: a webhook can be pointed at the wrong URL, signed with the wrong
             * secret, blocked, or late, and all four look identical to somebody who has just
             * been charged. Whichever path arrives second finds the payment already in the
             * ledger and does nothing.
             */
            verify.mutate(proof, {
              onSuccess: (res) => {
                toast.success(
                  res.status === 'granted' || res.status === 'already_applied'
                    ? 'Payment received — added to your account.'
                    : 'Payment received. Your account updates in a moment.',
                );
              },
              onError: () => {
                // The webhook is still coming. Saying "it failed" would be wrong and would
                // send them to support for something that resolves itself.
                toast.success('Payment received. Your account updates shortly.');
              },
            });
            void qc.invalidateQueries({ queryKey: ['billing', 'balance'] });
          },
          onDismiss: () => {
            // Closing the sheet is an ordinary thing to do and is not an error.
          },
          onFailure: (reason) => toast.error(reason),
        });

        if (!opened) {
          // A blocked CDN or an ad blocker. Saying so beats a button that appears dead.
          toast.error(
            'Could not load the payment window. Check your connection or any ad blocker, then try again.',
          );
        }
      },
      onError: (err) => {
        setFreeOrder(null);
        const notConfigured = err instanceof ApiError && err.status === 503;
        // An offer error carries a message the candidate can act on — "this offer has
        // expired" rather than "invalid code", which sends them hunting for a typo that is
        // not there. Surfaced verbatim rather than replaced with a generic line.
        const offerMessage =
          err instanceof ApiError && err.status === 400 ? err.message : null;
        toast.error(
          offerMessage ??
            (notConfigured
              ? 'Payments are not switched on yet. Add your Razorpay keys to enable checkout.'
              : 'Could not start the payment. Please try again.'),
        );
      },
      },
    );
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
                      busy={checkout.isPending && checkout.variables?.itemId === item.id}
                      signedIn={signedIn}
                    />
                  ))}
                </div>
              </section>
            );
          })}

        {/* THE PROMO BOX.
            Placed once, above the items, rather than on every card: a code applies to the
            purchase, not to a tile, and six identical boxes would suggest six separate
            discounts. Checking it before anything is chosen also means an unusable code is
            refused while the candidate is still browsing rather than at the till. */}
        {signedIn && (
          <div className="rounded-2xl border border-border p-4 sm:p-5">
            <label
              htmlFor="promo"
              className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground"
            >
              Have a code?
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id="promo"
                value={codeInput}
                onChange={(e) => setCodeInput(e.target.value.toUpperCase())}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') applyCode();
                }}
                placeholder="DIWALI25"
                // Uppercased as they type, because the server stores and compares uppercase.
                // Seeing the code in the form it will actually be checked in avoids the
                // "but I typed it correctly" class of support message.
                className="min-w-0 flex-1 rounded-lg border border-border bg-surface-elevated px-3 py-2 font-mono text-sm uppercase tracking-wider focus:border-primary focus:outline-none"
                maxLength={40}
              />
              <Button
                variant="secondary"
                onClick={applyCode}
                loading={quote.isPending}
                disabled={!codeInput.trim()}
              >
                Apply
              </Button>
              {appliedCode && (
                <button
                  onClick={() => {
                    setAppliedCode('');
                    setQuoted(null);
                    setCodeInput('');
                    setCaptchaToken('');
                  }}
                  className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                >
                  Remove
                </button>
              )}
            </div>

            {quoted && appliedCode && (
              <p className="mt-3 text-sm">
                <span className="font-semibold text-accent-emerald-ink">
                  {quoted.is_free
                    ? 'Free with this code'
                    : `Discount applied — ${Math.round(
                        (1 - quoted.charged_paise / quoted.original_paise) * 100,
                      )}% off`}
                </span>{' '}
                <span className="text-muted-foreground">
                  The exact price is confirmed on the item you choose.
                </span>
              </p>
            )}

            {/* Only when this offer asks for it. */}
            {quoted?.requires_captcha && <Turnstile onToken={setCaptchaToken} />}
          </div>
        )}

        {/* Only for somebody signed in — there is nothing to show otherwise, and an empty
            "Payment history" card on a public pricing page is noise. */}
        {signedIn && <PaymentHistory />}

        {/* The confirm step for a ₹0 order. Razorpay cannot open below ₹1, so this is the
            summary that takes the sheet's place — see FreeOrderSheet. */}
        <FreeOrderSheet
          open={!!freeOrder}
          item={freeOrder}
          code={appliedCode}
          originalPaise={quoted?.original_paise ?? freeOrder?.price_paise ?? 0}
          confirming={checkout.isPending}
          onCancel={() => setFreeOrder(null)}
          onConfirm={() => {
            if (freeOrder) runCheckout(freeOrder.id);
          }}
        />

        <p className="text-xs text-muted-foreground">
          Quizzes are unlimited and free on every account. Purchases do not expire. Prices are
          in INR and include GST where applicable.
        </p>
      </div>
    </div>
  );
}
