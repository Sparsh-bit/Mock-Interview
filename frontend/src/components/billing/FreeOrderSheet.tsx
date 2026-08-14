'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, Loader2, Tag, X } from 'lucide-react';
import { useEffect, useRef } from 'react';

import { Button } from '@/components/ui/button';
import type { StoreItem } from '@/hooks/useBilling';

/**
 * Confirming a free order — components/billing/FreeOrderSheet.tsx
 *
 * WHY THERE IS NO PAYMENT GATEWAY HERE, and why that is the industry-standard behaviour
 * rather than a shortcut.
 *
 * Razorpay will not create an order below ₹1. A 100%-off code produces a ₹0 total, so there
 * is no order to open a sheet for — the API rejects it before the widget ever loads. This is
 * a platform limit and no amount of code gets around it.
 *
 * Every large Indian checkout behaves the same way. Apply a full-value coupon on Amazon,
 * Swiggy or BookMyShow and the payment step disappears; you get an order summary and a
 * "Place order" button. The gateway is for moving money, and no money is moving.
 *
 * WHAT WAS ACTUALLY MISSING was this step. The item was granted the instant Buy was pressed,
 * with nothing to confirm — which reads as the button having failed, because everything a
 * candidate knows about buying says a sheet should appear. So this is that sheet: the same
 * shape, the same rhythm, one confirm, and no card.
 *
 * IT IS A REAL MODAL. Escape closes it, focus moves in and returns, the body does not scroll
 * behind it — the same rules the navigation drawer follows, for the same reason: a dialog
 * that traps nothing is a dialog a keyboard user is standing behind.
 */

export interface FreeOrderSheetProps {
  open: boolean;
  item: StoreItem | null;
  code: string;
  /** List price before the code, in paise, so the saving can be shown honestly. */
  originalPaise: number;
  confirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function FreeOrderSheet({
  open,
  item,
  code,
  originalPaise,
  confirming,
  onConfirm,
  onCancel,
}: FreeOrderSheetProps) {
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
            aria-label="Confirm your free order"
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
              Your code covers this in full — there is nothing to pay.
            </p>

            <div className="mb-5 space-y-3 rounded-xl border border-border/60 bg-surface-elevated p-4">
              <div className="flex items-start justify-between gap-3">
                <span className="text-sm">{item.name}</span>
                <span className="text-sm tabular-nums text-muted-foreground line-through">
                  ₹{Math.round(originalPaise / 100)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-border/60 pt-3">
                <span className="inline-flex items-center gap-1.5 text-sm text-accent-emerald-ink">
                  <Tag className="h-3.5 w-3.5" />
                  {code}
                </span>
                <span className="text-sm tabular-nums text-accent-emerald-ink">
                  −₹{Math.round(originalPaise / 100)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-border/60 pt-3">
                <span className="text-sm font-semibold">Total</span>
                <span className="text-lg font-semibold tabular-nums">₹0</span>
              </div>
            </div>

            {/* Said plainly rather than left as a surprise. Somebody who expects a card form
                and does not get one assumes something went wrong. */}
            <p className="mb-5 text-[11px] leading-relaxed text-muted-foreground">
              No payment method is needed for a ₹0 order, so the payment window is skipped.
              This will be added to your account straight away.
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
                Confirm order
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

export default FreeOrderSheet;
