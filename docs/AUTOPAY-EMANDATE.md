# Autopay: the registration flow that does not exist

**Status: not built, and deliberately not built blind.** Auto top-up cannot charge anybody
today, and that is the current compliance position rather than a bug — see
[[COMPLIANCE]] and `backend/tests/test_autopay_mandate_compliance.py`, which pins it.

This note is the traced specification for building it. It exists because the work is
blocked on one thing only, and the tracing should not have to be done twice.

## Why it is blocked

`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` are all empty. There
is no Razorpay account, so there is no test mode to run an authorisation transaction against.

Every step below touches money and an RBI-regulated mandate. Writing it against the
documentation and shipping it unexercised would replace a state that is safe *because it is
inert* with one that is live the moment somebody adds keys, and wrong in ways no unit test
can find — the request shapes, the webhook payload, the AFA redirect and the token lifecycle
are all things only the sandbox can confirm.

**To unblock:** a Razorpay account in Test Mode. Nothing else here needs a decision.

## What is actually missing

`autopay_token` and `autopay_customer_id` are read in three places and **written in none**.
`is_eligible` therefore returns `"no saved mandate"` for every account that will ever exist.

Confirmed against Razorpay's own documentation, not inferred: `charge_saved_token` also omits
three parameters the API marks mandatory — `email`, `contact` and `order_id`. So even with a
token in hand, the charge would 400. Those three are not fixable in isolation: the user model
holds no phone number, so `contact` has to come out of the registration below.

## The flow, end to end

### 1. Create the customer — `POST /v1/customers`

Returns `id` (`cust_…`) → store as `plan.autopay_customer_id`.

Idempotent by `email`; Razorpay returns the existing customer rather than erroring, so this
can be called on every registration attempt.

### 2. Create the authorisation order — `POST /v1/orders`

Not an ordinary order. It carries the mandate's ceiling and lifetime:

| Field | Value |
|---|---|
| `amount` | The first charge, or `0` for a zero-rupee registration |
| `currency` | `INR` |
| `customer_id` | From step 1 |
| `method` | `emandate`, `card`, `upi` or `nach` |
| `token.max_amount` | **The cap.** Set it to the largest pack price, not the default ₹99,999 |
| `token.expire_at` | Unix seconds. A mandate with no end date is one nobody remembers agreeing to |
| `token.frequency` | `as_presented` for top-up-on-demand |
| `payment_capture` | `true` |

`token.max_amount` is the single most important field here: it is the ceiling the *bank*
enforces, independently of anything this codebase does.

### 3. Checkout with `recurring: 1` — **this is the AFA step**

The browser opens Razorpay Checkout with `order_id`, `customer_id` and `recurring: 1`. The
customer authenticates at their own bank or card issuer.

This is the whole reason the compliance answer is simple: **AFA happens inside Razorpay's
authorisation transaction, at the issuer.** Razorpay is the licensed payment aggregator and
the party responsible for it. This product never sees a card, and must not try to.

### 4. Capture the token — `token.confirmed` webhook

| | |
|---|---|
| Event | `token.confirmed` — the bank has completed mandate registration |
| Token id | `payload.token.entity.id` |
| Also handle | `token.rejected`, `token.cancelled`, `token.paused` (UPI) |

`token.confirmed` does **not** carry `customer_id`; correlate on the authorisation payment,
whose `payload.payment.entity.customer_id` does.

**The only legitimate writer of `autopay_token` is this handler.** A token from anywhere else
— pasted from the dashboard, reused from a one-off payment — is a charge that skipped AFA.
That is exactly what `test_no_code_path_writes_the_mandate_token` exists to catch, and it
should be *narrowed to permit this one handler*, never deleted.

Store alongside it the `email` and `contact` the authorisation captured; step 5 needs both
and there is nowhere else to get them.

### 5. Each subsequent charge — a new order, then the recurring payment

A **new** `POST /v1/orders` every time. The authorisation order is not reusable.

Then `POST /v1/payments/create/recurring` with all eight mandatory fields:

`email`, `contact`, `amount`, `currency`, `order_id`, `customer_id`, `token`, `recurring`

The current call sends four of them.

Entitlement still comes from the webhook, through the same path a manual purchase takes —
`charge_saved_token` must not grant anything itself. One granting path is what keeps the
idempotency and amount checks true.

## What must change alongside the code

- **Migration** — `autopay_email`, `autopay_contact`, `autopay_max_amount_paise`,
  `autopay_mandate_expires_at`, and a token-status column.
- **`test_autopay_mandate_compliance.py`** — its own failure message says to update it when
  the registration flow arrives. Narrow the guards; do not remove them. In particular
  `test_the_feature_has_no_user_interface` becomes wrong by design once step 3 exists.
- **[[COMPLIANCE]]** — the "nothing can be charged" position stops being true.

## The amount ceiling is already pinned

Subsequent recurring transactions above ₹15,000 need AFA on *every* debit, which no
unattended top-up can supply. Every pack is two orders of magnitude below that, and
`TestTheAmountsStayInsideTheAfaExemption` fails if a price is ever set that would change the
regulatory shape of the feature rather than just its cost.
