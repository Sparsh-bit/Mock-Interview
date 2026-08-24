'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2, Tag } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { OrderSummarySheet } from '@/components/billing/OrderSummarySheet';
import { Turnstile } from '@/components/billing/Turnstile';
import {
  useCheckout,
  useQuote,
  useStoreItems,
  useVerifyPayment,
  type ItemPrice,
  type StoreItem,
} from '@/hooks/useBilling';
import { ApiError } from '@/lib/api/errors';
import { openCheckout } from '@/lib/billing/razorpay-checkout';
import { cn } from '@/lib/utils';

/**
 * Buying one thing, from wherever you were stopped — components/billing/BuyPanel.tsx
 *
 * WHY THIS EXISTS RATHER THAN A LINK TO /pricing. A candidate who is blocked is blocked at a
 * specific moment: they have opened the interview page, chosen a role, and pressed start. The
 * old paywall's answer was "See plans", which sends them to a different page, to browse six
 * products, to find the one they were already trying to use, and then to come back. Every one
 * of those steps is a place to stop, and the drop-off between "wants to practise" and "has
 * practised" is the entire funnel.
 *
 * So the purchase happens here, for the thing they were actually stopped on, without leaving
 * the page. The link to the full store stays, because somebody who wants the five-pack or a
 * different product should still be able to get there.
 *
 * IT IS THE SAME FLOW, NOT A SECOND ONE. Same /billing/quote, same /billing/checkout, same
 * order summary, same Razorpay call, same server-side verification. Nothing about what money
 * costs is decided here — the figures come from the priced catalogue the quote returns, which
 * is computed by the same functions the till uses.
 *
 * THE CODE FIELD IS PART OF IT. Applying a code repaints the prices in this panel exactly as
 * it does on the store, because it is the same per-item response. A candidate holding a code
 * should not have to go somewhere else to use it — that is the moment the code is worth the
 * most and the moment it is easiest to lose them.
 */
export function BuyPanel({
  feature,
  className,
  onPurchased,
}: {
  /** Which product to sell. One of the catalogue's features. */
  feature: string;
  className?: string;
  /** Called after an item lands on the account, so the caller can retry what was blocked. */
  onPurchased?: () => void;
}) {
  const { data: items } = useStoreItems();
  const checkout = useCheckout();
  const quote = useQuote();
  const verify = useVerifyPayment();
  const qc = useQueryClient();

  const [codeInput, setCodeInput] = useState('');
  //: The code the SERVER has priced, not what is in the box — a half-typed one must not ride
  //: along with a purchase.
  const [appliedCode, setAppliedCode] = useState('');
  const [prices, setPrices] = useState<ItemPrice[] | null>(null);
  const [requiresCaptcha, setRequiresCaptcha] = useState(false);
  const [captchaToken, setCaptchaToken] = useState('');
  const [pendingOrder, setPendingOrder] = useState<StoreItem | null>(null);

  const forFeature = (items ?? [])
    .filter((i) => i.feature === feature)
    .sort((a, b) => a.price_paise - b.price_paise);

  if (!forFeature.length) return null;

  const priceFor = (id: string): ItemPrice | null =>
    prices?.find((p) => p.item_id === id) ?? null;

  const applyCode = () => {
    const code = codeInput.trim();
    if (!code) return;
    // No item named, exactly as the store does: this asks whether the code exists, is live and
    // is unused by this account, and gets back the whole catalogue priced under it.
    quote.mutate(
      { itemId: '', code },
      {
        onSuccess: (q) => {
          setAppliedCode(code.toUpperCase());
          setPrices(q.prices ?? null);
          setRequiresCaptcha(!!q.requires_captcha);
          toast.success(q.label ? `${q.label} applied.` : 'Code applied.');
        },
        onError: (err) => {
          setAppliedCode('');
          setPrices(null);
          toast.error(
            err instanceof ApiError && err.status === 400
              ? err.message
              : 'Could not check that code.',
          );
        },
      },
    );
  };

  const clearCode = () => {
    setAppliedCode('');
    setPrices(null);
    setCodeInput('');
    setCaptchaToken('');
    setRequiresCaptcha(false);
  };

  const runCheckout = (itemId: string) => {
    checkout.mutate(
      { itemId, code: appliedCode, captchaToken },
      {
        onSuccess: async (order) => {
          if (order.granted) {
            // A fully-discounted item never becomes an order — Razorpay has a ₹1 minimum — so
            // there is nothing to open and it is already on the account.
            setPendingOrder(null);
            clearCode();
            toast.success('Added to your account. Nothing to pay.');
            void qc.invalidateQueries({ queryKey: ['billing', 'balance'] });
            onPurchased?.();
            return;
          }
          if (!order.order_id || !order.key_id) {
            // Says nothing about WHY. "Add your Razorpay keys" is an instruction to the
            // operator that only ever reached customers.
            toast.error('Payments are temporarily unavailable. Please try again shortly.');
            return;
          }
          const opened = await openCheckout({
            orderId: order.order_id,
            amountPaise: order.amount_paise,
            keyId: order.key_id,
            itemName: forFeature.find((i) => i.id === itemId)?.name ?? 'InterviewOS',
            onSuccess: (proof) => {
              // Verified server-side immediately. The webhook is still the primary path and
              // still grants on its own; this is the second, independent one, because a
              // webhook can be misrouted, mis-signed, blocked or late and all four look
              // identical to somebody who has just been charged.
              verify.mutate(proof, {
                onSuccess: () => toast.success('Payment received — added to your account.'),
                onError: () => toast.success('Payment received. Your account updates shortly.'),
              });
              void qc.invalidateQueries({ queryKey: ['billing', 'balance'] });
              setPendingOrder(null);
              onPurchased?.();
            },
            onDismiss: () => setPendingOrder(null),
            onFailure: (reason) => toast.error(reason),
          });
          if (!opened) {
            toast.error(
              'Could not load the payment window. Check your connection or any ad blocker, then try again.',
            );
          }
        },
        onError: (err) => {
          setPendingOrder(null);
          const offerMessage = err instanceof ApiError && err.status === 400 ? err.message : null;
          toast.error(
            offerMessage ??
              (err instanceof ApiError && err.status === 503
                ? 'Payments are temporarily unavailable. Please try again shortly.'
                : 'Could not start the payment. Please try again.'),
          );
        },
      },
    );
  };

  return (
    <div className={cn('w-full space-y-3', className)}>
      {/* THE CODE FIRST, for the same reason it is first on the store: applying it changes
          every price below, so it belongs before the choice rather than after it. */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={codeInput}
          onChange={(e) => setCodeInput(e.target.value.toUpperCase())}
          onKeyDown={(e) => {
            if (e.key === 'Enter') applyCode();
          }}
          placeholder="Have a code?"
          aria-label="Promo code"
          className="min-w-0 flex-1 font-mono uppercase tracking-wider"
          maxLength={40}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={applyCode}
          loading={quote.isPending}
          disabled={!codeInput.trim()}
        >
          Apply
        </Button>
        {appliedCode && (
          <button
            type="button"
            onClick={clearCode}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Remove
          </button>
        )}
      </div>

      {appliedCode && (
        <p className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent-emerald-ink">
          <Tag className="h-3.5 w-3.5" aria-hidden />
          <span className="font-mono uppercase">{appliedCode}</span> applied
        </p>
      )}

      {requiresCaptcha && <Turnstile onToken={setCaptchaToken} />}

      <div className="grid gap-2 sm:grid-cols-2">
        {forFeature.map((item) => {
          const p = priceFor(item.id);
          const discounted = p && p.covered && p.charged_paise < item.price_paise ? p : null;
          const nowRupees = discounted
            ? Math.round(discounted.charged_paise / 100)
            : item.price_rupees;
          const isBundle = item.quantity > 1;
          const busy = checkout.isPending && checkout.variables?.itemId === item.id;

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setPendingOrder(item)}
              disabled={busy}
              className={cn(
                'flex min-w-0 flex-col gap-1 rounded-xl border p-3 text-left transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                isBundle
                  ? 'border-primary/40 bg-primary/[0.04] hover:bg-primary/[0.07]'
                  : 'border-border hover:bg-secondary/60',
              )}
            >
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-semibold text-foreground">{item.name}</span>
                {isBundle && <Badge>Better value</Badge>}
              </span>
              <span className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="text-lg font-semibold tabular-nums text-foreground">
                  ₹{nowRupees}
                </span>
                {discounted && (
                  <span className="text-xs tabular-nums text-muted-foreground line-through">
                    ₹{item.price_rupees}
                  </span>
                )}
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
              </span>
            </button>
          );
        })}
      </div>

      <OrderSummarySheet
        open={!!pendingOrder}
        item={pendingOrder}
        code={appliedCode}
        originalPaise={pendingOrder?.price_paise ?? 0}
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
    </div>
  );
}

export default BuyPanel;
