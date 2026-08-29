'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, Code2, Download, Loader2, Receipt } from 'lucide-react';

import { usePayments } from '@/hooks/useBilling';
import {
  amountLabel,
  findPayment,
  formatRupees,
  quantityLabel,
  statusLabel,
} from '@/lib/billing/receipt';

export const runtime = 'edge';

/**
 * One payment, as something the candidate can keep — app/account/receipt/[paymentId]/page.tsx
 *
 * ASKED FOR AS "the recipt of the payment must also be availble for the user". The history list
 * on /pricing already showed what was bought and for how much; what it could not do is be
 * printed, saved or attached to a message. The moment somebody wants a receipt is the moment
 * they are already unhappy about a charge on a statement, and "look at the list on the pricing
 * page" is not an answer to that.
 *
 * PRINTED BY THE BROWSER, NOT BY A PDF LIBRARY. Exactly as the shared report at
 * app/r/[reportId] does it, for the reasons written in the `@media print` block in globals.css:
 * the browser's own pipeline gives a real vector PDF with selectable text at the right paper
 * size, on desktop and on a phone, with no dependency added. A canvas library would rasterise
 * this into a blurry image of a receipt whose numbers nobody can copy — on the one document
 * whose entire purpose is numbers somebody will copy.
 *
 * NO SEPARATE ENDPOINT, AND THAT IS THE SECURITY DESIGN. This selects out of the same
 * caller-scoped `GET /billing/payments` payload the history renders. There is no
 * `/billing/payments/{id}`, because an endpoint that takes a payment id is an endpoint that can
 * be handed somebody else's — and one candidate reading another candidate's payments is a data
 * breach involving money, which is the failure `test_only_the_caller` in
 * backend/tests/test_receipts.py exists to make impossible to reintroduce quietly. A stranger's
 * id is simply not in this list, so it renders as "not on this account" with no lookup having
 * happened at all.
 *
 * NOTHING IS INVENTED ON THIS PAGE. Every figure comes from the credit ledger by way of the
 * endpoint. In particular there is no company registration, no tax identifier and no invoice
 * number: this is a record of a payment, and dressing it as a tax invoice would be asserting
 * things about a legal entity that nobody here has established.
 */
export default function ReceiptPage() {
  const params = useParams();
  const paymentId = (params?.paymentId as string) ?? '';

  const { data, isLoading, isError } = usePayments();
  const payment = findPayment(data, paymentId);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
      </div>
    );
  }

  /*
   * TWO DIFFERENT MESSAGES, because they are two different situations and one of them is the
   * candidate's problem to wait out rather than to act on. A failed fetch is the backend being
   * slow or asleep and is worth retrying; a receipt that is not on this account will never
   * appear however many times they reload, and saying "try again" to that is sending somebody
   * in a circle.
   */
  if (isError) {
    return (
      <Empty
        title="Could not load this receipt"
        body="Your payments could not be fetched just now. Please try again in a moment — nothing on your account has changed."
      />
    );
  }

  if (!payment) {
    return (
      <Empty
        title="This receipt isn't on your account"
        body="The link may be for a different account, or the payment may not have completed. Only completed payments have a receipt, and an attempt that did not go through is never charged."
      />
    );
  }

  const status = statusLabel(payment);

  return (
    <div className="min-h-screen bg-background px-4 py-10 sm:px-6 print:py-0">
      <div className="mx-auto max-w-2xl">
        {/* Everything in this bar is an action, so none of it belongs on paper. */}
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4 print:hidden">
          <Link
            href="/pricing"
            className="inline-flex min-h-11 items-center gap-2 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Payment history
          </Link>
          <button
            onClick={() => window.print()}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-muted-foreground transition-colors hover:bg-secondary"
          >
            <Download className="h-3.5 w-3.5" /> Print or save as PDF
          </button>
        </div>

        {/* p-5 below 640px. At 320px the old flat `p-8` spent 64px of a 288px viewport on
            padding, leaving a 192px column — and the widest thing on this page is a Razorpay
            payment id, which at 192px breaks across three lines. */}
        <div className="rounded-2xl border border-border bg-surface p-5 sm:p-8 print:border-0 print:p-0">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border pb-6">
            <div className="flex items-center gap-2">
              <Code2 className="h-5 w-5 text-primary" aria-hidden />
              <span className="font-bold">Hotseat</span>
            </div>
            {/* `text-right` only once there are two columns. This is a `flex-wrap` row, so at
                320px the Receipt/Paid block drops onto its own full-width line and
                right-aligning it there leaves it floating away from the label it belongs to. */}
            <div className="text-left sm:text-right">
              <p className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                <Receipt className="h-3.5 w-3.5" aria-hidden /> Receipt
              </p>
              <p className="mt-1 text-sm font-semibold">
                {status.paid ? 'Paid' : 'Free — no payment taken'}
              </p>
            </div>
          </div>

          <dl className="grid gap-x-8 gap-y-4 border-b border-border py-6 sm:grid-cols-2">
            <Field label="Receipt number" value={payment.receipt} mono />
            <Field label="Date" value={new Date(payment.at).toLocaleString()} />
            <Field label="Issued to" value={data?.payer.email ?? '—'} />
            {/*
              Shown only when there is one. A free grant never touched Razorpay — the gateway
              cannot open an order below ₹1 — so it genuinely has no order id, and an "Order
              — " line invites the reader to think something is missing from their receipt.
            */}
            {payment.order_id ? (
              <Field label="Order" value={payment.order_id} mono />
            ) : null}
          </dl>

          <div className="py-6">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div className="min-w-0">
                <p className="break-words text-sm font-medium">{payment.item_name}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {quantityLabel(payment)} added to this account
                  {payment.offer ? ` · code ${payment.offer}` : ''}
                </p>
              </div>
              <p className="text-sm font-semibold tabular-nums">{amountLabel(payment)}</p>
            </div>
          </div>

          <div className="flex items-baseline justify-between border-t border-border pt-6">
            <p className="text-sm font-semibold">Total paid</p>
            {/*
              THE PAISE FIGURE IS THE SOURCE, not the rupee one. `amount_paise` is what
              Razorpay charged and what the ledger stored; `amount_rupees` on the same response
              is a convenience derived from it. Formatting the paise here means the total on the
              receipt is the integer the gateway actually moved, with no float in the path.
            */}
            <p className="text-lg font-semibold tabular-nums">
              {status.paid ? formatRupees(payment.amount_paise) : formatRupees(0)}
            </p>
          </div>

          <div className="mt-6 space-y-2 border-t border-border pt-6 text-[11px] leading-relaxed text-muted-foreground">
            <p>
              Quote the receipt number above in any question about this payment — it is the same
              reference the payment gateway indexes by, so it can be looked up from either side.
            </p>
            <p>
              {/* Worth stating on the receipt itself, because it is the one question this
                  document is otherwise silent on and the answer is unusually generous: there
                  is no period and no expiry on a purchased item. See models/billing.py. */}
              What this added to the account does not expire and is not consumed until you start
              the thing it pays for.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * One label-and-value pair.
 *
 * `mono` for the identifiers, because a payment id or an order id is something somebody will
 * read out over a phone or paste into a message, and proportional digits make a run of
 * characters harder to transcribe without a mistake.
 *
 * HOW IT WRAPS IS DECIDED BY THE VALUE, NOT BY `mono`, and that distinction is the whole reason
 * this receipt did not fit on a phone.
 *
 * `break-words` (`overflow-wrap: break-word`) breaks inside a word only as a last resort, and it
 * cannot help at all with the values on this page. Three of the four are SINGLE TOKENS with
 * nowhere to break: a Razorpay payment id (`pay_S1a2B3c4D5e6F7`), an order id, and the payer's
 * email — 20 to 30 characters with not one space in them. Inside the two-column grid at 320px
 * each was wider than its own track, so the track stretched, the card stretched, and the page
 * itself scrolled sideways. On the one document in this product whose entire purpose is numbers
 * somebody will copy off a phone.
 *
 * `break-all` permits a break at any character, so the token wraps to the column instead of
 * setting the column's width. It is chosen by asking whether the value has any whitespace to
 * break at, rather than off the `mono` flag — those are two different questions and conflating
 * them was wrong in both directions: the email needs breaking and is not mono, and a formatted
 * date is mono-adjacent prose that `break-all` would hyphenate mid-word for no reason.
 *
 * `min-w-0` on the wrapper is the other half of it. Without it the grid item refuses to be
 * narrower than its own content, and the wrapping rules inside are never consulted at all.
 */
function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  const unbreakable = !/\s/.test(value.trim());
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd
        className={`mt-1 text-sm ${unbreakable ? 'break-all' : 'break-words'} ${
          mono ? 'font-mono' : ''
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

/** Nothing to show, said in a way that tells the reader whether to retry or to leave. */
function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center sm:px-6 sm:py-20">
      <Receipt className="mx-auto mb-4 h-8 w-8 text-muted-foreground" aria-hidden />
      <h1 className="text-lg font-semibold text-foreground">{title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{body}</p>
      <Link
        href="/pricing"
        className="mt-6 inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline"
      >
        Back to payment history
      </Link>
    </div>
  );
}
