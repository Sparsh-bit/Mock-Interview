'use client';

import Link from 'next/link';
import { ChevronRight, Loader2, Receipt } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { usePayments } from '@/hooks/useBilling';
import {
  amountLabel,
  quantityLabel,
  receiptPath,
  statusLabel,
} from '@/lib/billing/receipt';

/**
 * Every payment on this account — components/billing/PaymentHistory.tsx
 *
 * READ OFF THE CREDIT LEDGER, not a separate receipts table. The ledger is what entitlement
 * is computed from, so a receipt derived from it cannot disagree with what the account
 * actually received. A second store would be a second version of the truth about somebody's
 * money, which is the class of bug the ledger exists to prevent.
 *
 * THE RECEIPT NUMBER IS RAZORPAY'S PAYMENT ID, deliberately. It is what their dashboard,
 * their support and ours all index by, so a candidate quoting it can be helped by any of the
 * three. A prettier invented number would be a number nobody else can look up.
 *
 * FREE GRANTS APPEAR TOO, marked as such. A 100%-off code and admin goodwill both add
 * entitlement, and a history that showed only card payments would have unexplained gaps where
 * somebody's balance went up.
 *
 * EVERY ROW IS A LINK TO ITS OWN RECEIPT. Asked for as "the recipt of the payment must also be
 * availble for the user": a line on a list is not something a candidate can print or attach to
 * a message, and the moment they need one is the moment they are already unhappy about a
 * charge. The receipt page selects out of THIS query rather than fetching a payment by id — see
 * `findPayment` — so it cannot show a payment this list would not, and there is no
 * id-accepting endpoint to hand somebody else's id to.
 *
 * THE WORDING RULES ARE IMPORTED, NOT WRITTEN HERE. The amount, the plural, the `gd` mapping
 * and the paid/free wording were all inline expressions in this file, and the receipt page
 * needs every one of them. Two copies is two ways to describe one payment, and the receipt
 * contradicting the list it was opened from is worse than having no receipt.
 *
 * WHAT THIS LIST CANNOT SHOW YET is a failed or abandoned payment attempt. Nothing on the
 * server records one — the places that were checked are enumerated in the `my_payments`
 * docstring in api/v1/billing.py — and a "payment failed" row this component made up would be
 * telling somebody something false about their bank account. So the empty-state copy says
 * plainly that only completed payments reach this list, which is a true sentence a candidate
 * can act on, instead of a row that is not.
 */
export function PaymentHistory() {
  const { data, isLoading, isError } = usePayments();
  const payments = data?.payments;

  return (
    <Card className="p-5 sm:p-6">
      <div className="mb-4 flex items-center gap-2">
        <Receipt className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">Payment history</h2>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Could not load your payments. Please try again.
        </p>
      ) : !payments?.length ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No completed payments yet. Anything you buy shows up here with its receipt number.
          {/* Said out loud because the alternative is a candidate assuming the attempt that
              did not go through took their money. A failed card is never charged, and the one
              place they will look to check is this list. */}
          <span className="mt-1 block">
            An attempt that did not go through is not charged and does not appear.
          </span>
        </p>
      ) : (
        <div className="space-y-2">
          {payments.map((p) => {
            const status = statusLabel(p);
            return (
              <Link
                key={p.id}
                href={receiptPath(p)}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/50 bg-surface/40 px-4 py-3 transition-colors hover:border-border hover:bg-surface/70"
              >
                <div className="min-w-0">
                  <div className="mb-0.5 flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{p.item_name}</span>
                    {!status.paid && <Badge variant="violet">{status.label.toLowerCase()}</Badge>}
                    {p.offer && <Badge variant="neutral">{p.offer}</Badge>}
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {new Date(p.at).toLocaleString()}
                    {' · '}
                    {/* Monospace because it is an identifier somebody will read out or paste
                        into a support message, not prose. */}
                    <span className="font-mono">{p.receipt}</span>
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <p className="text-sm font-semibold tabular-nums">{amountLabel(p)}</p>
                    <p className="text-[11px] text-muted-foreground">{quantityLabel(p)}</p>
                  </div>
                  {/* The affordance. Without it a whole row being clickable is a thing
                      nobody discovers, and the receipt might as well not exist. */}
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </Card>
  );
}

export default PaymentHistory;
