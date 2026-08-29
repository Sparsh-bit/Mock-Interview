'use client';

import Link from 'next/link';
import { Check, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { Wordmark } from '@/components/brand/Brandmark';
import { BRAND } from '@/lib/brand';
import { useAuth } from '@/hooks/useAuth';
import {
  useBalance,
  useCheckout,
  useQuote,
  useStoreItems,
  useVerifyPayment,
  type ItemPrice,
  type StoreItem,
} from '@/hooks/useBilling';
import { describeOffer } from '@/lib/billing/describe-offer';
import { openCheckout } from '@/lib/billing/razorpay-checkout';
import { Turnstile } from '@/components/billing/Turnstile';
import { PaymentHistory } from '@/components/billing/PaymentHistory';
import { OrderSummarySheet } from '@/components/billing/OrderSummarySheet';
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
  price,
  onBuy,
  busy,
  signedIn,
}: {
  item: StoreItem;
  /**
   * This item's figure under the applied code, from the server, or null when no code is on.
   *
   * THE WHOLE POINT OF PASSING IT IN. The tile has to change the moment Apply succeeds and
   * change back the moment Remove is pressed, and the only honest way to do that is for the
   * number to arrive already computed. A tile that worked out its own discount would be a
   * second implementation of what money costs, sitting on the one screen that promises it.
   */
  price: ItemPrice | null;
  onBuy: (id: string) => void;
  busy: boolean;
  signedIn: boolean;
}) {
  const isBundle = item.quantity > 1;
  const perUnit = Math.round(item.price_rupees / item.quantity);
  // Only when the code actually reaches this item AND actually changes its price. A struck
  // price that is struck to the same number is a discount claimed where none was given, and
  // an out-of-scope item must show what the candidate will really be charged.
  const discounted =
    price && price.covered && price.charged_paise < item.price_paise ? price : null;
  const nowRupees = discounted ? Math.round(discounted.charged_paise / 100) : item.price_rupees;

  return (
    <Card
      variant={isBundle ? 'elevated' : 'flat'}
      padding="md"
      /*
       * THE BUNDLE IS THE LIT ONE, and it is the only lit thing on the page — see
       * docs/DESIGN-LANGUAGE §1. A pricing page whose tiles all look equally recommended
       * makes the reader do the arithmetic, and most people will not.
       *
       * Amber rather than the indigo ring it had: in this palette amber means money and
       * indigo means "primary action". A ring in the action colour around a tile promises
       * the tile itself is clickable, which it is not — the button inside it is.
       */
      className={cn('flex flex-col gap-4', isBundle && 'lit lit-hover')}
    >
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">{item.name}</h3>
          {isBundle && <Badge>Better value</Badge>}
        </div>
        <p className="text-xs text-muted-foreground">{item.tagline}</p>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {/* Monospace, like every other figure in this product. These are numbers a reader
            compares down a column — the tabular figures keep the rupee amounts aligned, and
            proportional digits make two prices of the same length different widths. */}
        <span className="font-mono text-2xl font-bold tabular-nums tracking-[-0.02em] text-foreground">
          ₹{nowRupees}
        </span>
        {discounted && (
          <span className="text-sm tabular-nums text-muted-foreground line-through">
            ₹{item.price_rupees}
          </span>
        )}
        {isBundle && !discounted && (
          <span className="text-xs text-muted-foreground">₹{perUnit} each</span>
        )}
        {discounted && (
          <span className="rounded-md bg-accent-emerald-soft px-1.5 py-0.5 text-[11px] font-semibold text-accent-emerald-ink">
            {discounted.is_free
              ? 'Free with your code'
              : `Save ₹${item.price_rupees - nowRupees}`}
          </span>
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
    kind: 'percent' | 'fixed' | 'free' | '';
    value: number;
    applies_to: string[];
    prices?: ItemPrice[];
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
  const [pendingOrder, setPendingOrder] = useState<StoreItem | null>(null);

  /*
   * THIS ITEM'S FIGURE UNDER THE APPLIED CODE, or null.
   *
   * `quoted.prices` is the whole catalogue priced by the server in the one request Apply
   * already made. Looking a tile up in it is the entire mechanism behind "prices change when a
   * code is applied and change back when it is removed" — Remove clears `quoted`, every lookup
   * returns null, and every tile falls back to its list price with no second request and
   * nothing to reset.
   */
  const priceFor = (itemId: string): ItemPrice | null =>
    quoted?.prices?.find((p) => p.item_id === itemId) ?? null;

  /*
   * CHECKED WITHOUT NAMING AN ITEM, because at this point there is no item.
   *
   * This used to price the code against `items[0]` — the cheapest thing in the store —
   * purely so the box had something to send. That quietly broke every code restricted to a
   * particular item: a code for the five-interview pack was validated against the single
   * interview, came back "that code does not apply to this item", and was refused while the
   * candidate was looking at the five-pack it was made for. From the outside the promo
   * simply did not work, and the code never reached checkout to be re-checked.
   *
   * Sending no item asks the question that can actually be answered now — does this code
   * exist, is it live, has this account already used it — and leaves WHICH items it covers
   * to checkout, where the real item is known. The price is computed server-side there
   * regardless; this was never the thing that decided what anybody pays.
   */
  const applyCode = () => {
    const code = codeInput.trim();
    if (!code) return;
    quote.mutate(
      { itemId: '', code },
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
    /*
     * EVERY ORDER GETS THE SUMMARY, not just the free ones.
     *
     * This used to open the sheet only for a ₹0 total and hand everything else straight to
     * Razorpay — a card form with an amount in it and no statement of what was being bought or
     * whether the code had come off. The sheet is the invoice now: one confirm for both kinds
     * of order, and the gateway is what varies behind it.
     *
     * Note what this deliberately no longer does. It read `quoted.is_free`, a flag about the
     * CODE rather than about this item — priced, at the time, against whichever item the Apply
     * box had guessed. `priceFor` answers that question for the actual item, so the branch it
     * was guarding is gone rather than repaired.
     */
    const item = items?.find((i) => i.id === itemId) ?? null;
    if (!item) return;
    setPendingOrder(item);
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
          setPendingOrder(null);
          toast.success('Added to your account. Nothing to pay.');
          setAppliedCode('');
          setQuoted(null);
          setCodeInput('');
          return;
        }
        if (!order.order_id || !order.key_id) {
          // Deliberately says nothing about WHY. "Add your Razorpay keys" is an
          // instruction to the operator that only ever reached customers, and it names the
          // provider and admits the integration is unfinished — neither is a visitor's
          // business. The operator learns this from the logs, where it belongs.
          toast.error('Payments are temporarily unavailable. Please try again shortly.');
          return;
        }

        const opened = await openCheckout({
          orderId: order.order_id,
          amountPaise: order.amount_paise,
          keyId: order.key_id,
          itemName: items?.find((i) => i.id === itemId)?.name ?? 'Hotseat',
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
        setPendingOrder(null);
        const notConfigured = err instanceof ApiError && err.status === 503;
        // An offer error carries a message the candidate can act on — "this offer has
        // expired" rather than "invalid code", which sends them hunting for a typo that is
        // not there. Surfaced verbatim rather than replaced with a generic line.
        const offerMessage =
          err instanceof ApiError && err.status === 400 ? err.message : null;
        toast.error(
          offerMessage ??
            (notConfigured
              ? 'Payments are temporarily unavailable. Please try again shortly.'
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
          <Link href="/" aria-label={`${BRAND.name} home`}>
            <Wordmark />
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
          eyebrow="Plans"
          title="Buy what you need"
          description="No subscription. Pay per session, and what you buy never expires."
        />

        {/* THE PROMO BOX, FIRST ON THE PAGE.
            Placed once, and now ABOVE the items rather than below them. Two reasons, and
            the second is the one that changed:

            A code applies to the purchase, not to a tile, so one box rather than six —
            identical boxes on every card would suggest six separate discounts.

            AND APPLYING IT NOW CHANGES EVERY PRICE ON THE PAGE. While the box sat under the
            items it was a footnote to a decision already made; a candidate scrolled past six
            full prices, chose one, and only then found the field. Above them, the code is
            entered before anything is chosen and every tile below is already showing what it
            will actually cost — which is the order the decision is really made in. It also
            means an unusable code is refused while they are still browsing rather than at the
            till. */}
        {signedIn && (
          <div
            /*
             * THE LANDING POINT FOR THE DASHBOARD PROMO BANNER.
             *
             * The banner links to `/pricing#apply-offer`, so this id is the other half of that
             * feature — renaming it silently turns the banner into a link that loads the page
             * and scrolls nowhere, which looks like the banner being broken. Pinned by
             * components/promo-banner.test.ts.
             *
             * `scroll-mt-24` because a bare anchor puts the target flush against the top of the
             * viewport, tucking the "Have a code?" label under the sticky header — the
             * candidate arrives at an unlabelled input. The offset leaves the label visible,
             * which is the whole point of scrolling here rather than to the input itself.
             */
            id="apply-offer"
            className="scroll-mt-24 rounded-2xl border border-border p-4 sm:p-5"
          >
            <label
              htmlFor="promo"
              className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground"
            >
              Have a code?
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <Input
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
                //
                // The design-system Input rather than a hand-rolled one: this was the only
                // field on the site that set its own height, radius and focus ring, so it was
                // the only field that did not grow the 16px minimum that stops iOS zooming
                // the page when it is focused.
                className="min-w-0 flex-1 font-mono uppercase tracking-wider"
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
                  {describeOffer(quoted)}
                </span>{' '}
                {/* WAS "the exact price is confirmed on the item you choose", which was true
                    only while the page could not price anything. Every tile below now shows
                    what the server will actually charge, so the old line would send a
                    candidate looking for a confirmation that has already happened. */}
                <span className="text-muted-foreground">
                  Prices below have been updated.
                </span>
              </p>
            )}

            {/* Only when this offer asks for it. */}
            {quoted?.requires_captcha && <Turnstile onToken={setCaptchaToken} />}
          </div>
        )}

        {/* WHAT IS ACTUALLY FREE, READ FROM THE SERVER.

            This card used to list "1 mock interview" and "1 group discussion" as free. Both
            went paid and the strip did not, because it was four strings typed into a page
            while plans.py said zero — so the most prominent claim on the pricing page was
            false for weeks, and nothing could have caught it: no test can know that a
            sentence disagrees with a number it never reads.

            It is now built from `trial_allowance` on the items response, which comes from the
            same constant the enforcement layer uses. If a feature's allowance changes, this
            line changes with it; if every allowance goes to zero, the card renders only the
            quizzes, which are genuinely unlimited and are not metered at all. */}
        {!!items?.length && (
          <Card variant="flat" padding="md">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              <span className="font-medium text-foreground">Free on every account:</span>
              {FEATURE_ORDER.map((feature) => {
                const item = items.find((i) => i.feature === feature);
                if (!item || item.trial_allowance <= 0) return null;
                const label =
                  item.trial_allowance === 1 ? item.feature_label_singular : item.feature_label;
                return (
                  <span key={feature} className="flex items-center gap-1.5 text-muted-foreground">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-emerald-ink" aria-hidden />
                    {item.trial_allowance} {label}
                  </span>
                );
              })}
              {/* Not metered by the credits ledger at all, so there is no allowance to read
                  — it is unlimited by construction rather than by configuration. */}
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Check className="h-3.5 w-3.5 text-primary" aria-hidden />
                Unlimited quizzes
              </span>
            </div>
          </Card>
        )}

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
                      price={priceFor(item.id)}
                      onBuy={buy}
                      busy={checkout.isPending && checkout.variables?.itemId === item.id}
                      signedIn={signedIn}
                    />
                  ))}
                </div>
              </section>
            );
          })}

        {/* Only for somebody signed in — there is nothing to show otherwise, and an empty
            "Payment history" card on a public pricing page is noise. */}
        {signedIn && <PaymentHistory />}

        {/* THE INVOICE, shown before anything is charged. A ₹0 order confirms here and is
            granted; anything else confirms here and hands over to Razorpay — one shape for
            both, so "no card form appeared" never reads as a fault. */}
        <OrderSummarySheet
          open={!!pendingOrder}
          item={pendingOrder}
          code={appliedCode}
          /* THE ITEM'S OWN PRICE, not the quote's.
           *
           * This read `quoted.original_paise` first, which was the price of whatever item
           * the Apply box happened to validate against — the cheapest one — so the sheet
           * struck through ₹19 while granting the ₹199 five-pack. The box names no item at
           * all now, so that field is 0, and `??` would pass the zero straight through since
           * it only falls back on null and undefined. The item being confirmed is right here
           * and knows its own price. */
          originalPaise={pendingOrder?.price_paise ?? 0}
          /* WHAT THE SERVER WILL ACTUALLY CHARGE for this item under this code. Falls back to
           * the list price when no code is applied, or when the code does not reach this item
           * — the same number the line above shows, so a no-discount invoice needs no branch
           * and cannot claim a saving it did not give. */
          chargedPaise={
            (pendingOrder && priceFor(pendingOrder.id)?.covered
              ? priceFor(pendingOrder.id)?.charged_paise
              : undefined) ??
            pendingOrder?.price_paise ??
            0
          }
          confirming={checkout.isPending}
          onCancel={() => setPendingOrder(null)}
          onConfirm={() => {
            if (pendingOrder) runCheckout(pendingOrder.id);
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
