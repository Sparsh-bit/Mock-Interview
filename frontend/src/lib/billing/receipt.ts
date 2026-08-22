/**
 * What a receipt says — lib/billing/receipt.ts
 *
 * ASKED FOR DIRECTLY: "the recipt of the payment must also be availble for the user." A row on
 * a list is not a receipt. A receipt is something a candidate can open on its own, print, and
 * quote back at us or at their bank when ₹249 has left their account and they want to know
 * what for.
 *
 * WHY THE RULES LIVE HERE AND NOT IN THE COMPONENTS. Two surfaces now render the same payment:
 * the history row on /pricing and the printable receipt at /account/receipt/[paymentId]. Every
 * one of these functions was previously an inline expression inside PaymentHistory.tsx — the
 * `gd` → "group discussion" mapping, the pluralisation, the paid/free wording, the rupee
 * figure. Copying four expressions into a second component is four places for the receipt to
 * describe a payment differently from the list it was opened from, and a receipt that
 * disagrees with the history is worse than no receipt at all: it is two answers to "what did I
 * pay for" with no way to tell which is right.
 *
 * NOTHING HERE DECIDES ANYTHING ABOUT MONEY. Every figure comes from the server, which derives
 * it from the credit ledger — see the `my_payments` docstring in api/v1/billing.py. This is
 * presentation only. It cannot make a payment look larger, smaller, paid or unpaid than the
 * ledger says it was.
 */

/**
 * One row from GET /billing/payments.
 *
 * A DERIVED VIEW OF `credit_events`, not a stored receipt. The ledger is what entitlement is
 * computed from, so a receipt read off it cannot disagree with what the account actually
 * received. There is deliberately no receipts table to drift from it.
 */
export interface PaymentRecord {
  id: string;
  at: string;
  /**
   * The Razorpay payment id — the number their support and ours both index by.
   *
   * For a free grant, which never touched the gateway, this is `free-xxxxxxxx` from the ledger
   * row's own id. Still quotable, because a row the candidate cannot refer to is a row they
   * cannot ask about.
   */
  receipt: string;
  /**
   * The Razorpay order the payment settled against, or '' for a free grant.
   *
   * Razorpay cannot open an order below ₹1, so a 100%-off code genuinely has none — the empty
   * string is the real answer, not a missing field.
   */
  order_id: string;
  item_id: string;
  item_name: string;
  feature: string;
  quantity: number;
  amount_paise: number;
  amount_rupees: number;
  offer: string;
  kind: string;
  paid: boolean;
}

/** Who the receipts on this response belong to. */
export interface Payer {
  email: string;
}

/**
 * The whole envelope from GET /billing/payments.
 *
 * `payer` sits beside the rows rather than on each of them because it is the same person for
 * every row by construction: the endpoint scopes on the authenticated user and takes no id.
 * Repeating it per row would offer an identity that looks per-row and could one day be
 * populated per row, which is the shape of the bug that scoping exists to prevent.
 */
export interface PaymentsResponse {
  payments: PaymentRecord[];
  payer: Payer;
}

/**
 * Paise to a rupee string.
 *
 * PAISE IS THE SOURCE FIGURE. Every price in this product is an integer number of paise
 * because that is what Razorpay bills in, and a rupee amount held as a float is a rounding bug
 * waiting for the first ₹49.50.
 *
 * The decimals appear only when there are any: "₹249" for a whole amount and "₹49.50" for one
 * that is not. A receipt showing "₹249.00" reads as an accounting document nobody asked for,
 * and "₹49.5" reads as a bug.
 *
 * NO LOCALE GROUPING, on purpose. `toLocaleString('en-IN')` would put the separators where an
 * Indian reader expects them and depends on the runtime shipping full ICU data — which the
 * edge runtime and Node's test environment do not agree about, so the same amount could render
 * differently in a test, in the browser and on paper. Nothing in this catalogue reaches four
 * digits, so the grouping would never be visible and the risk buys nothing.
 */
export function formatRupees(paise: number): string {
  const whole = Math.trunc(paise / 100);
  const remainder = Math.abs(paise % 100);
  if (remainder === 0) return `₹${whole}`;
  return `₹${whole}.${String(remainder).padStart(2, '0')}`;
}

/**
 * The headline amount for one payment.
 *
 * A grant is "Free", not "₹0". They are the same number and not the same sentence: ₹0 reads as
 * a payment that went wrong, and a candidate who redeemed a 100%-off code did not have a
 * payment go wrong.
 */
export function amountLabel(p: PaymentRecord): string {
  return p.paid ? formatRupees(p.amount_paise) : 'Free';
}

/**
 * What kind of line this is, for a badge.
 *
 * Keyed on `paid` rather than on `kind`, matching the server: `kind` distinguishes a purchase
 * from a grant, and `paid` is the thing a candidate is actually asking about when they look at
 * this page. Admin goodwill and a promo code are different provenance and the same fact —
 * entitlement arrived and no money left.
 *
 * There is no 'failed' or 'pending' case, and its absence is not an oversight. Nothing on the
 * server records a failed or abandoned attempt — the full list of places that was checked is
 * in the `my_payments` docstring in api/v1/billing.py. Adding the label before the record
 * exists would mean a badge that can only ever be produced by inventing a payment.
 */
export function statusLabel(p: PaymentRecord): { label: string; paid: boolean } {
  return p.paid ? { label: 'Paid', paid: true } : { label: 'Free', paid: false };
}

/**
 * "+5 mock interviews" — what the payment actually put on the account.
 *
 * The plural and the `gd` mapping were inline in the history row. They are here because the
 * receipt needs the identical phrase: "1 gd" on the receipt beside "1 group discussion" on the
 * list is the receipt contradicting the page it was opened from.
 */
export function quantityLabel(p: PaymentRecord): string {
  const noun = p.feature === 'gd' ? 'group discussion' : p.feature;
  return `+${p.quantity} ${noun}${p.quantity === 1 ? '' : 's'}`;
}

/** Where the printable receipt for this payment lives. */
export function receiptPath(p: PaymentRecord): string {
  return `/account/receipt/${p.id}`;
}

/**
 * Find one payment in a response by its ledger id.
 *
 * THE RECEIPT PAGE READS THE SAME CALLER-SCOPED PAYLOAD THE HISTORY DOES, and that is the
 * whole reason there is no `GET /billing/payments/{id}` endpoint. An endpoint that takes an id
 * is an endpoint that can be handed somebody else's id, and the one thing this feature may not
 * do is show one candidate another candidate's payment. Selecting from a list the server
 * already scoped to the caller cannot do that however the id is guessed — a stranger's id
 * simply is not in the list, which is why `null` here renders as "not on this account" rather
 * than as an error.
 */
export function findPayment(
  response: PaymentsResponse | undefined,
  id: string,
): PaymentRecord | null {
  if (!response) return null;
  return response.payments.find((p) => p.id === id) ?? null;
}
