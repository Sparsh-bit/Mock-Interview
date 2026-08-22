import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  amountLabel,
  findPayment,
  formatRupees,
  quantityLabel,
  receiptPath,
  statusLabel,
  type PaymentRecord,
  type PaymentsResponse,
} from './receipt';

/**
 * A payment a candidate can keep — lib/billing/receipt.test.ts
 *
 * WHY THIS FILE EXISTS. "the recipt of the payment must also be availble for the user." The
 * receipt now has two surfaces — the history row and the printable page — and the thing that
 * can go wrong is not either of them failing to render. It is the two of them describing one
 * payment differently, because every wording rule used to be an inline expression inside
 * PaymentHistory.tsx and the obvious way to build the second surface is to copy them.
 *
 * So the money-facing rules are asserted as functions, and the two facts that cannot be
 * expressed as a function — that the page opts into the Edge Runtime, and that it does not
 * fetch a payment by id — are asserted against the source. Both of those fail silently: the
 * first passes `next build` and breaks only the Cloudflare Pages deploy (see
 * app/edge-runtime.test.ts), and the second would be a working feature that is also a way to
 * read somebody else's payments.
 */

const row = (over: Partial<PaymentRecord> = {}): PaymentRecord => ({
  id: '11111111-1111-1111-1111-111111111111',
  at: '2026-08-20T09:00:00+00:00',
  receipt: 'pay_TestAbc123',
  order_id: 'order_TestAbc123',
  item_id: 'interview_5',
  item_name: '5 mock interviews',
  feature: 'interview',
  quantity: 5,
  amount_paise: 24900,
  amount_rupees: 249,
  offer: '',
  kind: 'purchase',
  paid: true,
  ...over,
});

describe('the amount on a receipt', () => {
  it('renders a whole rupee amount without decimals', () => {
    // "₹249.00" reads as an accounting document nobody asked for. Every price in the
    // catalogue is whole rupees, so this is the case that actually renders.
    expect(formatRupees(24900)).toBe('₹249');
  });

  it('renders a part-rupee amount with both decimal places', () => {
    // The first ₹49.50 offer is what breaks a naive `paise / 100`, which would print "₹49.5"
    // and read as a bug on a document about somebody's money.
    expect(formatRupees(4950)).toBe('₹49.50');
    expect(formatRupees(4905)).toBe('₹49.05');
  });

  it('is driven by paise, not by the derived rupee figure', () => {
    /*
     * The endpoint sends both. `amount_paise` is the integer Razorpay actually charged and the
     * ledger stored; `amount_rupees` is a convenience divided out of it. Reading the float
     * would put a rounding step between the gateway and the receipt for no gain, so this pins
     * that a wrong rupee figure cannot change what the receipt says.
     */
    expect(amountLabel(row({ amount_paise: 24900, amount_rupees: 1 }))).toBe('₹249');
  });

  it('a free grant says Free rather than ₹0', () => {
    // Same number, different sentence. ₹0 reads as a payment that went wrong, and somebody
    // who redeemed a 100%-off code did not have a payment go wrong.
    expect(amountLabel(row({ paid: false, amount_paise: 0 }))).toBe('Free');
  });
});

describe('what kind of line this is', () => {
  it('keys on whether money moved, not on the ledger kind', () => {
    // `kind` separates a purchase from an admin grant, which is provenance. What a candidate
    // is asking when they look at this page is whether they were charged.
    expect(statusLabel(row()).paid).toBe(true);
    expect(statusLabel(row({ paid: false, kind: 'grant' })).paid).toBe(false);
    expect(statusLabel(row({ paid: false, kind: 'grant' })).label).toBe('Free');
  });

  it('has no failed or pending state at all', () => {
    /*
     * DELIBERATE, AND THE REASON IS UPSTREAM. Nothing on the server records a failed or
     * abandoned payment attempt: no order row is persisted at checkout, /billing/verify writes
     * nothing on its `pending` branch, and the webhook drops every non-capture. The full list
     * of places checked is in the `my_payments` docstring in api/v1/billing.py.
     *
     * A label for a state no data can produce could only ever be reached by inventing a
     * payment, and a made-up "payment failed" row tells somebody something false about their
     * bank account. This pins the absence so that adding the label without adding the record
     * is a deliberate act rather than a plausible-looking commit.
     */
    const labels = [statusLabel(row()).label, statusLabel(row({ paid: false })).label];
    expect(labels).toEqual(['Paid', 'Free']);
  });
});

describe('what the payment put on the account', () => {
  it('pluralises', () => {
    expect(quantityLabel(row({ quantity: 5 }))).toBe('+5 interviews');
    expect(quantityLabel(row({ quantity: 1 }))).toBe('+1 interview');
  });

  it('spells out gd, which is not a word', () => {
    // The phrase has to be identical on both surfaces. "1 gd" on the receipt beside "1 group
    // discussion" on the list is the receipt contradicting the page it was opened from.
    expect(quantityLabel(row({ feature: 'gd', quantity: 1 }))).toBe('+1 group discussion');
    expect(quantityLabel(row({ feature: 'gd', quantity: 2 }))).toBe('+2 group discussions');
  });
});

describe('finding one payment to show', () => {
  const response: PaymentsResponse = {
    payments: [row({ id: 'mine' }), row({ id: 'also-mine', receipt: 'pay_Second' })],
    payer: { email: 'candidate@example.test' },
  };

  it('selects out of the caller-scoped list', () => {
    expect(findPayment(response, 'also-mine')?.receipt).toBe('pay_Second');
  });

  it('an id that is not on this account is null, not an error', () => {
    /*
     * THE TENANCY PROPERTY, and the reason there is no GET /billing/payments/{id}. The list
     * arrives already scoped to the authenticated caller, so a stranger's id cannot be in it
     * however it was obtained — no lookup happens, and the page says "not on this account".
     * An endpoint taking an id is an endpoint that can be handed somebody else's, which is the
     * failure `test_only_the_caller` in backend/tests/test_receipts.py protects.
     */
    expect(findPayment(response, 'somebody-elses-payment-id')).toBeNull();
  });

  it('survives the first render, before the query has resolved', () => {
    // `undefined` is the normal state for one paint, not an error state. Throwing here would
    // put the error boundary up on every visit to the page.
    expect(findPayment(undefined, 'mine')).toBeNull();
  });

  it('the row links to the id the page looks up', () => {
    // These two are the whole navigation. If they ever disagree, every receipt link lands on
    // "this receipt isn't on your account" — which looks exactly like a payment having gone
    // missing, on the page where that is the worst thing it could look like.
    expect(receiptPath(row({ id: 'abc' }))).toBe('/account/receipt/abc');
  });
});

const PAGE = readFileSync(
  join(process.cwd(), 'src/app/account/receipt/[paymentId]/page.tsx'),
  'utf8',
);
const HISTORY = readFileSync(
  join(process.cwd(), 'src/components/billing/PaymentHistory.tsx'),
  'utf8',
);

/** Comments stripped, so no assertion can match its own explanation. */
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const PAGE_CODE = strip(PAGE);
const HISTORY_CODE = strip(HISTORY);

describe('the printable receipt page', () => {
  it('opts into the Edge Runtime', () => {
    // Duplicated from app/edge-runtime.test.ts on purpose: that check is a loop over every
    // route, and this is the route it was added for. Missing it passes `next build`, passes
    // lint, passes tsc, and silently stops the whole frontend deploying to Cloudflare Pages.
    expect(PAGE_CODE).toMatch(/export const runtime = 'edge'/);
  });

  it('prints through the browser rather than a PDF dependency', () => {
    // The same decision app/r/[reportId] made, for the reasons in the @media print block in
    // globals.css: a real vector PDF with selectable text, at the right paper size, on a phone
    // as well as a desktop, with nothing added to the bundle.
    expect(PAGE_CODE).toMatch(/window\.print\(\)/);
    expect(PAGE_CODE).toMatch(/print:hidden/);
  });

  it('reads the shared payments query and never a payment-by-id endpoint', () => {
    expect(PAGE_CODE).toMatch(/usePayments\(\)/);
    expect(PAGE_CODE).toMatch(/findPayment\(/);
    // The thing that must not appear. A per-payment fetch would work and would also be a way
    // to read another account's payment.
    expect(PAGE_CODE).not.toMatch(/billing\/payments\//);
  });

  it('asserts nothing about a legal entity', () => {
    // A record of a payment, not a tax invoice. GSTIN, a CIN or an invoice series would be
    // claims about a registered company that nobody here has established — and on a money
    // document an invented identifier is not a cosmetic mistake.
    for (const claim of ['GSTIN', 'GST No', 'CIN', 'Invoice No', 'Tax Invoice']) {
      expect(PAGE).not.toContain(claim);
    }
  });
});

describe('the history list', () => {
  it('uses the shared wording rules instead of its own', () => {
    // The regression this pins is a re-inlined expression: the moment one surface computes its
    // own amount or plural, the two can disagree about one payment.
    expect(HISTORY_CODE).toMatch(/from '@\/lib\/billing\/receipt'/);
    expect(HISTORY_CODE).not.toMatch(/amount_rupees/);
    expect(HISTORY_CODE).not.toMatch(/group discussion/);
  });

  it('every row opens its own receipt', () => {
    expect(HISTORY_CODE).toMatch(/receiptPath\(p\)/);
  });

  it('says that a failed attempt was not charged, rather than inventing a row for it', () => {
    // Nothing records a failed attempt (see the `my_payments` docstring), so the honest thing
    // this page can do is tell the candidate that the list is completed payments only — which
    // is the sentence that stops them assuming the card that declined took their money.
    expect(HISTORY_CODE).toMatch(/did not go through is not charged/);
  });
});
