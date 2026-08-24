'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, Loader2, Tag, X } from 'lucide-react';
import { useEffect, useRef } from 'react';

import { Button } from '@/components/ui/button';
import type { StoreItem } from '@/hooks/useBilling';

/**
 * The order summary — components/billing/OrderSummarySheet.tsx
 *
 * ONE SHEET FOR BOTH KINDS OF ORDER. It began as a free-order confirmation, because Razorpay
 * will not create an order below ₹1 and a 100%-off code therefore has no payment window to
 * open — a platform limit no amount of code gets around. What was missing then was the STEP:
 * the item was granted the instant Buy was pressed, with nothing to confirm, which reads as
 * the button having failed because everything a candidate knows about buying says a sheet
 * should appear.
 *
 * The same argument turned out to apply to a paid order. Pressing Buy opened a card form with
 * an amount in it and no statement of what was being bought, whether the code had come off, or
 * what the figure was made of. Every large Indian checkout shows a summary before the gateway;
 * the gateway is for moving money, not for explaining a total.
 *
 * SO THE SHEET IS ALWAYS SHOWN AND THE GATEWAY IS WHAT VARIES. A ₹0 order confirms and is
 * granted; anything else confirms and hands over to Razorpay. The candidate sees the same
 * shape either way, which is also what stops "no card form appeared" from reading as a fault.
 *
 * THE FIGURES ARE THE SERVER'S. `chargedPaise` is the number the server computed for THIS item
 * under THIS code — the same arithmetic checkout will use — not a discount re-derived here. A
 * summary that computed its own total would be a second implementation of what money costs,
 * and the one place it must never live is the screen that promises it.
 *
 * IT IS A REAL MODAL. Escape closes it, focus moves in and returns, the body does not scroll
 * behind it — the same rules the navigation drawer follows, for the same reason: a dialog
 * that traps nothing is a dialog a keyboard user is standing behind.
 */

export interface OrderSummarySheetProps {
  open: boolean;
  item: StoreItem | null;
  /** The applied code, or '' when none is. Drives the discount row. */
  code: string;
  /** List price before the code, in paise, so the saving can be shown honestly. */
  originalPaise: number;
  /**
   * What the server says this item costs under this code, in paise.
   *
   * NOT DERIVED HERE. The page reads it from the priced catalogue the quote returns, which is
   * computed by the same functions checkout and the webhook use. Equal to `originalPaise`
   * when no code applies, which is exactly how the no-discount case renders with no branch.
   */
  chargedPaise: number;
  confirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function OrderSummarySheet({
  open,
  item,
  code,
  originalPaise,
  chargedPaise,
  confirming,
  onConfirm,
  onCancel,
}: OrderSummarySheetProps) {
  // Rupees, rounded once, so every row on the invoice is derived from the same two numbers
  // and cannot disagree with itself by a rupee.
  const listRupees = Math.round(originalPaise / 100);
  const totalRupees = Math.round(chargedPaise / 100);
  const savedRupees = Math.max(0, listRupees - totalRupees);
  const isFree = chargedPaise <= 0;
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !confirming) {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key !== 'Tab') return;
      const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled])',
      );
      if (!focusables?.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.();
    };
  }, [open, confirming, onCancel]);

  return (
    <AnimatePresence>
      {open && item && (
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
          <motion.button
            type="button"
            aria-label="Cancel"
            onClick={() => !confirming && onCancel()}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute inset-0 h-full w-full bg-foreground/40 backdrop-blur-[2px]"
          />

          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Confirm your order"
            tabIndex={-1}
            initial={{ y: 24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 24, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 420, damping: 34 }}
            className="relative w-full max-w-md rounded-t-2xl border border-border/70 bg-surface p-6 shadow-2xl outline-none sm:rounded-2xl"
          >
            <button
              type="button"
              onClick={() => !confirming && onCancel()}
              aria-label="Cancel"
              className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>

            <h2 className="mb-1 text-lg font-semibold">Confirm your order</h2>
            <p className="mb-5 text-sm text-muted-foreground">
              {isFree
                ? 'Your code covers this in full — there is nothing to pay.'
                : 'Check the total, then continue to payment.'}
            </p>

            {/* THE INVOICE. Line item, then the code if there is one, then the total — the
                order every receipt in the world uses, because it is the order the arithmetic
                happens in. The struck-through list price only appears when something actually
                came off it; striking through a price that did not change is a discount
                claimed where none was given. */}
            <div className="mb-5 space-y-3 rounded-xl border border-border/60 bg-surface-elevated p-4">
              <div className="flex items-start justify-between gap-3">
                <span className="min-w-0 text-sm">
                  {item.name}
                  {item.quantity > 1 && (
                    <span className="ml-1.5 text-xs text-muted-foreground">
                      ×{item.quantity}
                    </span>
                  )}
                </span>
                <span
                  className={
                    savedRupees > 0
                      ? 'shrink-0 text-sm tabular-nums text-muted-foreground line-through'
                      : 'shrink-0 text-sm tabular-nums text-foreground'
                  }
                >
                  ₹{listRupees}
                </span>
              </div>

              {code && savedRupees > 0 && (
                <div className="flex items-center justify-between gap-3 border-t border-border/60 pt-3">
                  <span className="inline-flex min-w-0 items-center gap-1.5 text-sm text-accent-emerald-ink">
                    <Tag className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    <span className="truncate font-mono uppercase">{code}</span>
                  </span>
                  {/* The REAL saving, list minus what the server will charge. It used to be
                      the whole list price, which was true only because this sheet could only
                      ever show a free order. */}
                  <span className="shrink-0 text-sm tabular-nums text-accent-emerald-ink">
                    −₹{savedRupees}
                  </span>
                </div>
              )}

              <div className="flex items-center justify-between gap-3 border-t border-border/60 pt-3">
                <span className="text-sm font-semibold">Total</span>
                <span className="text-lg font-semibold tabular-nums">₹{totalRupees}</span>
              </div>
            </div>

            {/* Said plainly rather than left as a surprise. Somebody who expects a card form
                and does not get one assumes something went wrong — and somebody who does not
                expect one should be told it is next. */}
            <p className="mb-5 text-[11px] leading-relaxed text-muted-foreground">
              {isFree
                ? 'No payment method is needed for a ₹0 order, so the payment window is skipped. This will be added to your account straight away.'
                : 'The payment window opens next. Nothing is charged until you complete it there, and what you buy does not expire.'}
            </p>

            <div className="flex gap-2">
              <Button
                variant="secondary"
                className="flex-1"
                onClick={onCancel}
                disabled={confirming}
              >
                Cancel
              </Button>
              <Button className="flex-1" onClick={onConfirm} loading={confirming}>
                {confirming ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                {isFree ? 'Confirm order' : `Pay ₹${totalRupees}`}
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

export default OrderSummarySheet;
