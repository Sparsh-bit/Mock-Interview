'use client';

import { Loader2, Receipt } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { usePayments } from '@/hooks/useBilling';

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
 */
export function PaymentHistory() {
  const { data, isLoading, isError } = usePayments();

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
      ) : !data?.length ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No payments yet. Anything you buy shows up here with its receipt number.
        </p>
      ) : (
        <div className="space-y-2">
          {data.map((p) => (
            <div
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/50 bg-surface/40 px-4 py-3"
            >
              <div className="min-w-0">
                <div className="mb-0.5 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{p.item_name}</span>
                  {!p.paid && <Badge variant="violet">free</Badge>}
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
              <div className="text-right">
                <p className="text-sm font-semibold tabular-nums">
                  {p.paid ? `₹${p.amount_rupees}` : 'Free'}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  +{p.quantity} {p.feature === 'gd' ? 'group discussion' : p.feature}
                  {p.quantity === 1 ? '' : 's'}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default PaymentHistory;
